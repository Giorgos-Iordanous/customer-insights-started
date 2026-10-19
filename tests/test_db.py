from contextlib import closing
import sqlite3

import pytest

from customer_insights import db


@pytest.fixture
def analytics_db(tmp_path):
    path = tmp_path / "customer # analytics.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "CREATE TABLE customers (cancelled INTEGER, country TEXT, email TEXT)"
        )
        conn.executemany(
            "INSERT INTO customers VALUES (?, ?, ?)",
            [
                (0, "CY", "synthetic-one@example.invalid"),
                (1, "GB", "synthetic-two@example.invalid"),
                (0, "CY' OR 1=1 --", "synthetic-three@example.invalid"),
            ],
        )
        conn.execute(
            "CREATE VIEW v_customers_analytics AS "
            "SELECT cancelled, country FROM customers"
        )
        conn.commit()
    return path


def test_get_customers_only_retrieves_cancellation_status(analytics_db):
    with closing(db.connect(analytics_db)) as conn:
        rows = db.get_customers(conn)

    assert len(rows) == 3
    assert all(isinstance(row, sqlite3.Row) for row in rows)
    assert all(row.keys() == ["cancelled"] for row in rows)
    assert [row["cancelled"] for row in rows] == [0, 1, 0]


def test_country_filter_treats_input_as_a_literal(analytics_db):
    with closing(db.connect(analytics_db)) as conn:
        ordinary = db.get_customers_by_country(conn, "GB")
        crafted = db.get_customers_by_country(conn, "CY' OR 1=1 --")
        missing = db.get_customers_by_country(conn, "missing' OR 1=1 --")

    assert [row["cancelled"] for row in ordinary] == [1]
    assert [row["cancelled"] for row in crafted] == [0]
    assert all(row.keys() == ["cancelled"] for row in ordinary + crafted)
    assert missing == []


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO customers VALUES (1, 'ZZ', 'synthetic@example.invalid')",
        "UPDATE customers SET cancelled = 1",
        "DELETE FROM customers",
    ],
)
def test_connection_blocks_database_writes(analytics_db, statement):
    with closing(db.connect(analytics_db)) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(statement)
        assert [row["cancelled"] for row in db.get_customers(conn)] == [0, 1, 0]


def test_missing_database_fails_without_creating_a_file(tmp_path):
    missing = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError):
        db.connect(missing)

    assert not missing.exists()


@pytest.mark.parametrize("filtered", [False, True])
def test_missing_analytics_view_does_not_fall_back_to_customers(tmp_path, filtered):
    path = tmp_path / "no-view.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE customers (cancelled INTEGER, country TEXT)")
        conn.execute("INSERT INTO customers VALUES (1, 'CY')")
        conn.commit()

    with closing(db.connect(path)) as conn:
        with pytest.raises(sqlite3.OperationalError, match="v_customers_analytics"):
            if filtered:
                db.get_customers_by_country(conn, "CY")
            else:
                db.get_customers(conn)


@pytest.fixture
def factor_db(tmp_path):
    path = tmp_path / "factor analytics.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "CREATE TABLE customers (customer_id INTEGER, signup_date TEXT, "
            "cancelled INTEGER, cancelled_date TEXT, last_payment_status TEXT, "
            "support_tickets INTEGER, full_name TEXT, email TEXT, phone TEXT)"
        )
        conn.execute(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1, "2025-01-01", 1, "2025-02-01", "failed", 4,
                "SYNTHETIC_FACTOR_NAME", "factor-canary@example.invalid", "FAKE_PHONE",
            ),
        )
        conn.execute(
            "CREATE VIEW v_customers_analytics AS SELECT customer_id, signup_date, "
            "cancelled, cancelled_date, last_payment_status, support_tickets "
            "FROM customers"
        )
        conn.execute(
            "CREATE TABLE support_comments (comment_id INTEGER, customer_id INTEGER, "
            "created_at TEXT, comment_text TEXT, private_metadata TEXT)"
        )
        conn.execute(
            "INSERT INTO support_comments VALUES (?, ?, ?, ?, ?)",
            (1, 1, "2025-01-15", "Synthetic buffering issue", "UNNEEDED_METADATA"),
        )
        conn.commit()
    return path


def test_factor_customer_query_only_retrieves_required_analytics_fields(factor_db):
    statements = []
    with closing(db.connect(factor_db)) as conn:
        conn.set_trace_callback(statements.append)
        rows = db.get_factor_customers(conn)

    assert len(rows) == 1
    assert rows[0].keys() == [
        "customer_id", "signup_date", "cancelled", "cancelled_date",
        "last_payment_status", "support_tickets",
    ]
    assert rows[0]["customer_id"] == 1
    assert rows[0]["cancelled"] == 1
    assert len(statements) == 1
    assert "FROM v_customers_analytics" in statements[0]
    assert "SELECT *" not in statements[0]


def test_factor_comment_query_only_retrieves_required_fields(factor_db):
    with closing(db.connect(factor_db)) as conn:
        rows = db.get_factor_comments(conn)

    assert len(rows) == 1
    assert rows[0].keys() == ["customer_id", "created_at", "comment_text"]
    assert rows[0]["customer_id"] == 1
    assert rows[0]["comment_text"] == "Synthetic buffering issue"


@pytest.mark.parametrize("view", ["absent", "incomplete"])
def test_factor_customer_query_never_falls_back_to_raw_customers(tmp_path, view):
    path = tmp_path / "incomplete-analytics.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "CREATE TABLE customers (customer_id INTEGER, signup_date TEXT, "
            "cancelled INTEGER, cancelled_date TEXT, last_payment_status TEXT, "
            "support_tickets INTEGER)"
        )
        conn.execute(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)",
            (1, "2025-01-01", 1, "2025-02-01", "failed", 4),
        )
        if view == "incomplete":
            conn.execute("CREATE VIEW v_customers_analytics AS SELECT cancelled FROM customers")
        conn.commit()

    expected = "v_customers_analytics" if view == "absent" else "customer_id"
    with closing(db.connect(path)) as conn:
        with pytest.raises(sqlite3.OperationalError, match=expected):
            db.get_factor_customers(conn)


def test_factor_comments_missing_table_fails_clearly(analytics_db):
    with closing(db.connect(analytics_db)) as conn:
        with pytest.raises(sqlite3.OperationalError, match="support_comments"):
            db.get_factor_comments(conn)
