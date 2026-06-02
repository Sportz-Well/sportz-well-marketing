"""Shared database connection helper — PostgreSQL (Supabase) edition.

All modules that need database access import get_connection() from here.
The interface is intentionally sqlite3-compatible so no agent or UI files
need to change.

Never call psycopg2.connect() directly elsewhere — always use get_connection().
"""

from __future__ import annotations

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set. "
            "Add it to .env locally or Streamlit Secrets in production."
        )
    return url


def _pg(sql: str) -> str:
    """Convert SQLite-style ? placeholders to PostgreSQL %s."""
    return sql.replace("?", "%s")


class _Cursor:
    """sqlite3-compatible wrapper around a psycopg2 DictCursor."""

    def __init__(self, cursor: psycopg2.extensions.cursor, raw_conn):
        self._c = cursor
        self._raw_conn = raw_conn

    def fetchall(self):
        try:
            return self._c.fetchall()
        except psycopg2.ProgrammingError:
            return []

    def fetchone(self):
        try:
            return self._c.fetchone()
        except psycopg2.ProgrammingError:
            return None

    @property
    def lastrowid(self) -> int | None:
        """Return last inserted row ID using PostgreSQL lastval()."""
        try:
            cur = self._raw_conn.cursor()
            cur.execute("SELECT lastval()")
            row = cur.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    @property
    def rowcount(self) -> int:
        return self._c.rowcount

    def __iter__(self):
        return iter(self._c)


class _Connection:
    """sqlite3-compatible wrapper around a psycopg2 connection."""

    def __init__(self, conn: psycopg2.extensions.connection):
        self._conn = conn

    def execute(self, sql: str, params=None) -> _Cursor:
        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute(_pg(sql), params or ())
        return _Cursor(cursor, self._conn)

    def executemany(self, sql: str, params_list) -> _Cursor:
        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.executemany(_pg(sql), params_list)
        return _Cursor(cursor, self._conn)

    def executescript(self, sql: str) -> None:
        """Run multiple SQL statements (sqlite3 executescript compatibility)."""
        cursor = self._conn.cursor()
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for statement in statements:
            try:
                cursor.execute(statement)
            except psycopg2.Error as e:
                print(f"[executescript] Skipped: {e}")
                self._conn.rollback()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        self._conn.close()
        return False


def get_connection() -> _Connection:
    """Return a persistent PostgreSQL connection with sqlite3-compatible interface."""
    conn = psycopg2.connect(_get_database_url())
    return _Connection(conn)