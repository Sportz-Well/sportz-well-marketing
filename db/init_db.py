"""Initialize (or migrate) the PostgreSQL (Supabase) database from schema.sql.

Run from the project root:  python db/init_db.py

Behaviour
---------
- Applies schema.sql to the Supabase database (idempotent).
- Runs column migrations for any columns added after initial deploy.
- Safe to run repeatedly. Never drops or recreates existing tables.
- Requires DATABASE_URL in .env (local) or Streamlit Secrets (production).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH  = PROJECT_ROOT / "db" / "schema.sql"

sys.path.insert(0, str(PROJECT_ROOT))

from services.database import get_connection  # noqa: E402


# ─── Helpers ────────────────────────────────────────────────────────────────

def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = ?",
        (table,)
    ).fetchone()
    return row is not None


def _get_table_columns(conn, table: str) -> set:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ?",
        (table,)
    ).fetchall()
    return {row["column_name"] for row in rows}


def _add_columns(conn, table: str, additions: list) -> None:
    """Add missing columns. PostgreSQL supports ADD COLUMN IF NOT EXISTS."""
    existing = _get_table_columns(conn, table)
    for col_name, col_def in additions:
        if col_name not in existing:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_def}"
            )
            print(f"  Migrated: added {table}.{col_name}")


# ─── Migration ──────────────────────────────────────────────────────────────

def _migrate_existing_db(conn) -> None:
    """Add columns introduced after the initial schema. Idempotent."""

    if _table_exists(conn, "research_items"):
        _add_columns(conn, "research_items", [
            ("source_title",          "TEXT"),
            ("source_published_date", "TEXT"),
            ("relevance_score",       "INTEGER"),
            ("relevance_reason",      "TEXT"),
            ("url_status",            "TEXT DEFAULT 'unchecked'"),
            ("final_url",             "TEXT"),
            ("source_geography",      "TEXT"),
        ])

    if _table_exists(conn, "story_angles"):
        _add_columns(conn, "story_angles", [
            ("theme",               "TEXT"),
            ("angle_title",         "TEXT"),
            ("angle_description",   "TEXT"),
            ("editorial_brief",     "TEXT"),
            ("platform_fit",        "TEXT"),
            ("phase_tag",           "TEXT"),
            ("funnel_stage",        "TEXT"),
            ("content_format",      "TEXT"),
            ("cta_strength",        "TEXT"),
            ("proof_points_used",   "TEXT"),
            ("status",              "TEXT DEFAULT 'proposed'"),
            ("user_notes",          "TEXT"),
            ("updated_at",          "TEXT"),
        ])

    if _table_exists(conn, "media_briefs"):
        _add_columns(conn, "media_briefs", [
            ("shot_type",           "TEXT NOT NULL DEFAULT ''"),
            ("subject",             "TEXT NOT NULL DEFAULT ''"),
            ("setting",             "TEXT NOT NULL DEFAULT ''"),
            ("time_of_day",         "TEXT NOT NULL DEFAULT ''"),
            ("lighting_mood",       "TEXT NOT NULL DEFAULT ''"),
            ("props",               "TEXT NOT NULL DEFAULT '[]'"),
            ("composition_notes",   "TEXT NOT NULL DEFAULT ''"),
            ("color_palette",       "TEXT NOT NULL DEFAULT '[]'"),
            ("wardrobe_notes",      "TEXT"),
            ("do_not",              "TEXT NOT NULL DEFAULT '[]'"),
            ("caption_sync_note",   "TEXT NOT NULL DEFAULT ''"),
            ("raw_model_response",  "TEXT"),
            ("model_input_tokens",  "INTEGER NOT NULL DEFAULT 0"),
            ("model_output_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("cost_usd",            "REAL NOT NULL DEFAULT 0.0"),
            ("status",              "TEXT NOT NULL DEFAULT 'pending'"),
            ("created_at",          "TEXT"),
            ("updated_at",          "TEXT"),
        ])

    print("  Migration check complete.")


# ─── Entry point ────────────────────────────────────────────────────────────

def init_db() -> None:
    """Apply schema.sql to PostgreSQL and run column migrations."""
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
        print("Schema applied.")

        _migrate_existing_db(conn)
        conn.commit()
        print("Database ready.")
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("Initialising database...")
    init_db()