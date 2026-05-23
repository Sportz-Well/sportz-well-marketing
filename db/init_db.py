"""Initialize (or migrate) the SQLite database from schema.sql.

Run from the project root:  python db/init_db.py

Behaviour
---------
- If data/app.db does not exist → creates it from schema.sql.
- If data/app.db exists with the new schema (has 'organizations' table) →
  applies CREATE IF NOT EXISTS clauses only (idempotent, safe to run repeatedly).
- If data/app.db exists but does NOT have 'organizations' (old Prompt-1 schema or
  a partial/corrupt state) → deletes the file and recreates from scratch. The DB
  was empty anyway, so no data is lost.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH  = PROJECT_ROOT / "db" / "schema.sql"
DB_PATH      = PROJECT_ROOT / "data" / "app.db"


def _has_new_schema(path: Path) -> bool:
    """Return True if the DB at *path* already has the current schema (organizations table)."""
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='organizations'"
        ).fetchone()
    return row is not None


def _get_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _migrate_existing_db(conn: sqlite3.Connection) -> None:
    """Add columns and tables that were introduced after the initial schema."""
    # New columns for research_items (Prompts 3 and 3.5)
    if _table_exists(conn, "research_items"):
        existing = _get_table_columns(conn, "research_items")
        additions = [
            ("source_title",          "TEXT"),
            ("source_published_date", "TEXT"),
            ("relevance_score",       "INTEGER"),
            ("relevance_reason",      "TEXT"),
            ("url_status",            "TEXT DEFAULT 'unchecked'"),
            ("final_url",             "TEXT"),
            ("source_geography",      "TEXT"),
        ]
        for col_name, col_type in additions:
            if col_name not in existing:
                conn.execute(
                    f"ALTER TABLE research_items ADD COLUMN {col_name} {col_type}"
                )
                print(f"  Migrated: added research_items.{col_name}")

    # api_log table (Prompt 3) — created by schema.sql IF NOT EXISTS; just confirm
    if not _table_exists(conn, "api_log"):
        print("  Note: api_log table not found; schema.sql should have created it.")

    # New columns for story_angles (Prompt 4)
    if _table_exists(conn, "story_angles"):
        existing = _get_table_columns(conn, "story_angles")
        sa_additions = [
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
            ("status",              "TEXT NOT NULL DEFAULT 'proposed'"),
            ("user_notes",          "TEXT"),
            ("updated_at",          "TEXT NOT NULL DEFAULT (datetime('now'))"),
        ]
        for col_name, col_type in sa_additions:
            if col_name not in existing:
                conn.execute(
                    f"ALTER TABLE story_angles ADD COLUMN {col_name} {col_type}"
                )
                print(f"  Migrated: added story_angles.{col_name}")

        # Create status index after the column is guaranteed to exist
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_story_angles_status ON story_angles(status)"
        )

    # Drafts table (Prompt 5) — rebuild to new schema if old placeholder exists.
    # The old stub had 'content' and 'media_suggestion' but no 'variant_number'.
    # No real data was ever written there (UI was a placeholder), so drop is safe.
    if _table_exists(conn, "drafts"):
        existing = _get_table_columns(conn, "drafts")
        if "variant_number" not in existing:
            conn.execute("DROP TABLE drafts")
            conn.execute("""
                CREATE TABLE drafts (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    story_angle_id      INTEGER NOT NULL REFERENCES story_angles(id),
                    product_id          INTEGER NOT NULL,
                    platform            TEXT    NOT NULL,
                    variant_number      INTEGER NOT NULL,
                    content_format      TEXT    NOT NULL,
                    headline            TEXT,
                    body                TEXT    NOT NULL,
                    cta_line            TEXT,
                    hashtags            TEXT,
                    carousel_slides     TEXT,
                    reel_script         TEXT,
                    image_brief         TEXT,
                    proof_points_used   TEXT,
                    word_count          INTEGER,
                    char_count          INTEGER,
                    status              TEXT    NOT NULL DEFAULT 'draft',
                    created_at          TEXT    NOT NULL,
                    updated_at          TEXT    NOT NULL,
                    UNIQUE(story_angle_id, platform, variant_number)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_drafts_angle ON drafts(story_angle_id)"
            )
            print("  Migrated: rebuilt drafts table to Prompt-5 schema (old placeholder dropped)")

    # editor_reviews table (Prompt 6) — new table, created by schema.sql IF NOT EXISTS; confirm.
    if not _table_exists(conn, "editor_reviews"):
        print("  Note: editor_reviews table not found after executescript; check schema.sql.")
    else:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_editor_reviews_draft_id "
            "ON editor_reviews(draft_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_editor_reviews_draft_review "
            "ON editor_reviews(draft_id, review_number)"
        )

    # media_briefs table (Prompt 7) — created by schema.sql IF NOT EXISTS.
    # This block adds any columns that might be missing on a DB that was created
    # before Prompt 7 landed (safe to run on a fresh DB — _get_table_columns
    # returns an empty set only if the table somehow didn't get created above,
    # which schema.sql's CREATE TABLE IF NOT EXISTS prevents).
    if _table_exists(conn, "media_briefs"):
        existing = _get_table_columns(conn, "media_briefs")
        mb_additions = [
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
            ("created_at",          "TEXT NOT NULL DEFAULT (datetime('now'))"),
            ("updated_at",          "TEXT NOT NULL DEFAULT (datetime('now'))"),
        ]
        for col_name, col_type in mb_additions:
            if col_name not in existing:
                conn.execute(
                    f"ALTER TABLE media_briefs ADD COLUMN {col_name} {col_type}"
                )
                print(f"  Migrated: added media_briefs.{col_name}")

        # Ensure indexes exist
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_briefs_product "
            "ON media_briefs(product_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_briefs_draft "
            "ON media_briefs(draft_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_briefs_status "
            "ON media_briefs(status)"
        )
        print("  media_briefs: schema confirmed / indexes ensured.")
    else:
        print("  Note: media_briefs table not found after executescript; check schema.sql.")

    # Indexes (idempotent — schema.sql uses CREATE INDEX IF NOT EXISTS)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def init_db() -> Path:
    """Create or migrate data/app.db. Returns the DB path."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    if DB_PATH.exists() and not _has_new_schema(DB_PATH):
        print("Stale or old schema detected. Deleting data/app.db and rebuilding...")
        DB_PATH.unlink()

    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema_sql)
        _migrate_existing_db(conn)

    return DB_PATH


if __name__ == "__main__":
    path = init_db()
    print(f"Database ready at: {path}")