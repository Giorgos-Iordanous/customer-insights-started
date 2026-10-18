from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3

import pytest

from customer_insights import db, report


def make_database(path, statuses):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "CREATE TABLE customers (cancelled, full_name TEXT, email TEXT, phone TEXT)"
        )
        conn.executemany(
            "INSERT INTO customers VALUES (?, ?, ?, ?)",
            [
                (status, "SYNTHETIC_CONTACT_NAME", "canary@example.invalid", "FAKE_PHONE")
                for status in statuses
            ],
        )
        conn.execute(
            "CREATE VIEW v_customers_analytics AS SELECT cancelled FROM customers"
        )
        conn.commit()
    return path


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [([0, 1, 0], "33.33%"), ([0, 0], "0.00%"), ([1, 1], "100.00%"), ([], "N/A")],
)
def test_summary_formats_rate_and_leaves_optional_sections_empty(tmp_path, statuses, expected):
    source = make_database(tmp_path / "input.db", statuses)
    output = tmp_path / "nested" / "summary.md"

    returned = report.build(db_path=source, output_path=output)
    summary = output.read_text(encoding="utf-8")

    assert isinstance(returned, Path)
    assert returned == output
    assert summary.startswith("# Weekly customer summary\n\n")
    assert f"Customers in scope: {len(statuses)}\n" in summary
    assert f"Cancellation rate: {expected}\n" in summary
    reasons = summary.split("## Main reasons customers cancel\n", 1)[1]
    reasons, at_risk = reasons.split("## At-risk customers to contact this week\n", 1)
    assert not reasons.strip()
    assert at_risk.strip() == (
        "| Name | Email | Phone | Plan | Reason |\n"
        "|---|---|---|---|---|"
    )
    for marker in ("SYNTHETIC_CONTACT_NAME", "canary@example.invalid", "FAKE_PHONE"):
        assert marker not in summary


@pytest.mark.parametrize("alias", ["same", "normalized", "hardlink", "symlink"])
def test_output_cannot_overwrite_input_database(tmp_path, alias):
    source = make_database(tmp_path / "input.db", [0, 1])
    before = hashlib.sha256(source.read_bytes()).digest()
    if alias == "same":
        output = source
    elif alias == "normalized":
        (tmp_path / "nested").mkdir()
        output = tmp_path / "nested" / ".." / "input.db"
    else:
        output = tmp_path / "summary.md"
        try:
            if alias == "hardlink":
                os.link(source, output)
            else:
                output.symlink_to(source)
        except OSError as error:
            pytest.skip(f"Filesystem does not support this alias: {error}")

    with pytest.raises(ValueError):
        report.build(db_path=source, output_path=output)

    assert hashlib.sha256(source.read_bytes()).digest() == before


def test_missing_database_does_not_create_database_or_summary(tmp_path):
    source = tmp_path / "missing.db"
    output = tmp_path / "summary.md"

    with pytest.raises(FileNotFoundError):
        report.build(db_path=source, output_path=output)

    assert not source.exists()
    assert not output.exists()


def test_invalid_status_does_not_overwrite_an_existing_summary(tmp_path):
    source = make_database(tmp_path / "input.db", [0, None])
    output = tmp_path / "summary.md"
    output.write_text("Existing summary", encoding="utf-8")

    with pytest.raises(ValueError):
        report.build(db_path=source, output_path=output)

    assert output.read_text(encoding="utf-8") == "Existing summary"


@pytest.mark.parametrize("failure", [None, "query", "template"])
def test_report_closes_connection_after_success_or_failure(tmp_path, monkeypatch, failure):
    source = make_database(tmp_path / "input.db", [0, 1])
    output = tmp_path / "summary.md"
    opened = []
    original_connect = db.connect

    def tracked_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    def failing_query(conn):
        raise RuntimeError("Synthetic query failure")

    def failing_template(source):
        raise RuntimeError("Synthetic template failure")

    monkeypatch.setattr(db, "connect", tracked_connect)
    if failure == "query":
        monkeypatch.setattr(db, "get_customers", failing_query)
    elif failure == "template":
        monkeypatch.setattr(report, "Template", failing_template)

    if failure:
        with pytest.raises(RuntimeError, match=f"Synthetic {failure} failure"):
            report.build(db_path=source, output_path=output)
        assert not output.exists()
    else:
        report.build(db_path=source, output_path=output)

    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
