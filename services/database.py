"""Shared database connection helper.

All modules that need SQLite access import get_connection() from here.
Never call sqlite3.connect() directly elsewhere — doing so bypasses the
Row factory and foreign-key enforcement set up here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "app.db"


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with Row factory and FK enforcement."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
