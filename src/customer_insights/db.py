"""Database access."""
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "data/customers.db")


def connect(path=None):
    """Open an existing database for read-only reporting; callers must close it."""
    database = Path(DB_PATH if path is None else path).resolve(strict=True)
    conn = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_customers(conn):
    return conn.execute("SELECT cancelled FROM v_customers_analytics").fetchall()


def get_customers_by_country(conn, country):
    return conn.execute(
        "SELECT cancelled FROM v_customers_analytics WHERE country = ?", (country,)
    ).fetchall()


def get_comments(conn):
    return conn.execute("SELECT * FROM support_comments").fetchall()


def get_factor_customers(conn):
    return conn.execute(
        "SELECT customer_id, signup_date, cancelled, cancelled_date, "
        "last_payment_status, support_tickets FROM v_customers_analytics"
    ).fetchall()


def get_factor_comments(conn):
    return conn.execute(
        "SELECT customer_id, created_at, comment_text FROM support_comments"
    ).fetchall()
