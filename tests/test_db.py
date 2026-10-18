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
