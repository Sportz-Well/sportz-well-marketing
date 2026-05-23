"""
Scheduler agent — Sportz-Well Marketing Studio
Pure DB logic. Zero API calls. Zero cost.

Public functions
----------------
schedule_draft(draft_id, scheduled_for)  → dict  schedule a draft
unschedule(schedule_id)                  → dict  remove from schedule
reschedule(schedule_id, new_datetime)    → dict  change time
get_scheduled_drafts(start_date, end_date) → list  calendar view
mark_as_posted(schedule_id)              → dict  set posted_at
get_pipeline_summary(product_id)         → dict  approved: scheduled vs unscheduled
get_schedule_entry(schedule_id)          → dict | None  single row lookup
"""

import sqlite3
from datetime import datetime, timezone
from services.database import get_connection


# ─── helpers ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _row_to_dict(cursor, row) -> dict:
    """sqlite3 row_factory helper."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _ok(data: dict) -> dict:
    return {"ok": True, **data}


def _err(msg: str) -> dict:
    return {"ok": False, "error": msg}


# ─── core functions ───────────────────────────────────────────────────────────

def schedule_draft(draft_id: int, scheduled_for: str) -> dict:
    """
    Schedule an approved draft.

    Parameters
    ----------
    draft_id      : int   — must exist in drafts table with status='approved'
    scheduled_for : str   — ISO 8601 datetime string, e.g. '2026-05-25T10:00:00'

    Returns
    -------
    dict with ok=True and schedule_id, or ok=False and error message.
    """
    # Validate datetime format
    try:
        datetime.fromisoformat(scheduled_for)
    except ValueError:
        return _err(f"Invalid datetime format: '{scheduled_for}'. Use YYYY-MM-DDTHH:MM:SS")

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row

        # Check draft exists and is approved
        draft = conn.execute(
            "SELECT id, status, platform, product_id FROM drafts WHERE id = ?",
            (draft_id,)
        ).fetchone()

        if draft is None:
            return _err(f"Draft #{draft_id} not found.")

        if draft["status"] != "approved":
            return _err(
                f"Draft #{draft_id} has status='{draft['status']}'. "
                "Only approved drafts can be scheduled."
            )

        # Check not already scheduled
        existing = conn.execute(
            "SELECT id FROM schedule WHERE draft_id = ?",
            (draft_id,)
        ).fetchone()

        if existing:
            return _err(
                f"Draft #{draft_id} is already scheduled (schedule #{existing['id']}). "
                "Use reschedule() to change the time."
            )

        cursor = conn.execute(
            "INSERT INTO schedule (draft_id, scheduled_for, posted_manually) VALUES (?, ?, 1)",
            (draft_id, scheduled_for)
        )
        conn.commit()

        return _ok({
            "schedule_id": cursor.lastrowid,
            "draft_id": draft_id,
            "platform": draft["platform"],
            "scheduled_for": scheduled_for,
        })


def unschedule(schedule_id: int) -> dict:
    """
    Remove a draft from the schedule entirely.
    Only allowed if the entry has not been posted yet.
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row

        entry = conn.execute(
            "SELECT * FROM schedule WHERE id = ?", (schedule_id,)
        ).fetchone()

        if entry is None:
            return _err(f"Schedule entry #{schedule_id} not found.")

        if entry["posted_at"] is not None:
            return _err(
                f"Schedule entry #{schedule_id} has already been posted. Cannot unschedule."
            )

        conn.execute("DELETE FROM schedule WHERE id = ?", (schedule_id,))
        conn.commit()

        return _ok({
            "schedule_id": schedule_id,
            "draft_id": entry["draft_id"],
            "message": "Removed from schedule.",
        })


def reschedule(schedule_id: int, new_datetime: str) -> dict:
    """
    Change the scheduled time for an existing schedule entry.
    Only allowed if not yet posted.
    """
    try:
        datetime.fromisoformat(new_datetime)
    except ValueError:
        return _err(f"Invalid datetime format: '{new_datetime}'. Use YYYY-MM-DDTHH:MM:SS")

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row

        entry = conn.execute(
            "SELECT * FROM schedule WHERE id = ?", (schedule_id,)
        ).fetchone()

        if entry is None:
            return _err(f"Schedule entry #{schedule_id} not found.")

        if entry["posted_at"] is not None:
            return _err(
                f"Schedule entry #{schedule_id} has already been posted. Cannot reschedule."
            )

        conn.execute(
            "UPDATE schedule SET scheduled_for = ? WHERE id = ?",
            (new_datetime, schedule_id)
        )
        conn.commit()

        return _ok({
            "schedule_id": schedule_id,
            "draft_id": entry["draft_id"],
            "old_datetime": entry["scheduled_for"],
            "new_datetime": new_datetime,
        })


def mark_as_posted(schedule_id: int) -> dict:
    """
    Mark a scheduled post as manually posted (copy-paste into Meta Business Suite).
    Sets posted_at to current UTC time.
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row

        entry = conn.execute(
            "SELECT * FROM schedule WHERE id = ?", (schedule_id,)
        ).fetchone()

        if entry is None:
            return _err(f"Schedule entry #{schedule_id} not found.")

        if entry["posted_at"] is not None:
            return _err(
                f"Schedule entry #{schedule_id} was already marked posted at {entry['posted_at']}."
            )

        posted_at = _now_iso()
        conn.execute(
            "UPDATE schedule SET posted_at = ? WHERE id = ?",
            (posted_at, schedule_id)
        )
        conn.commit()

        return _ok({
            "schedule_id": schedule_id,
            "draft_id": entry["draft_id"],
            "posted_at": posted_at,
        })


def get_scheduled_drafts(start_date: str, end_date: str) -> list[dict]:
    """
    Return all schedule entries in a date range (inclusive).

    Parameters
    ----------
    start_date : str   — 'YYYY-MM-DD'
    end_date   : str   — 'YYYY-MM-DD'

    Returns
    -------
    List of dicts, each containing schedule + draft fields.
    Ordered by scheduled_for ASC.
    """
    # Normalise to datetime range strings for ISO comparison
    start_dt = f"{start_date}T00:00:00"
    end_dt   = f"{end_date}T23:59:59"

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT
                s.id            AS schedule_id,
                s.draft_id,
                s.scheduled_for,
                s.posted_at,
                s.posted_manually,
                d.platform,
                d.variant_number,
                d.content_format,
                d.headline,
                d.body,
                d.cta_line,
                d.status        AS draft_status,
                d.product_id,
                sa.angle_title
            FROM schedule s
            JOIN drafts d       ON d.id = s.draft_id
            LEFT JOIN story_angles sa ON sa.id = d.story_angle_id
            WHERE s.scheduled_for BETWEEN ? AND ?
            ORDER BY s.scheduled_for ASC
            """,
            (start_dt, end_dt)
        ).fetchall()

        return [dict(r) for r in rows]


def get_schedule_entry(schedule_id: int) -> dict | None:
    """Return a single schedule row with draft details, or None if not found."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT
                s.id            AS schedule_id,
                s.draft_id,
                s.scheduled_for,
                s.posted_at,
                s.posted_manually,
                d.platform,
                d.variant_number,
                d.content_format,
                d.headline,
                d.body,
                d.cta_line,
                d.status        AS draft_status,
                d.product_id,
                sa.angle_title
            FROM schedule s
            JOIN drafts d       ON d.id = s.draft_id
            LEFT JOIN story_angles sa ON sa.id = d.story_angle_id
            WHERE s.id = ?
            """,
            (schedule_id,)
        ).fetchone()

        return dict(row) if row else None


def get_pipeline_summary(product_id: int) -> dict:
    """
    Return counts for the pipeline overview:
    - approved drafts total
    - approved drafts that ARE scheduled (and not yet posted)
    - approved drafts that are NOT scheduled
    - posted this month
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row

        # Total approved drafts
        total_approved = conn.execute(
            "SELECT COUNT(*) AS n FROM drafts WHERE product_id = ? AND status = 'approved'",
            (product_id,)
        ).fetchone()["n"]

        # Approved drafts that are scheduled but not posted
        scheduled_pending = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM schedule s
            JOIN drafts d ON d.id = s.draft_id
            WHERE d.product_id = ? AND d.status = 'approved' AND s.posted_at IS NULL
            """,
            (product_id,)
        ).fetchone()["n"]

        # Approved drafts with no schedule entry at all
        unscheduled = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM drafts d
            WHERE d.product_id = ? AND d.status = 'approved'
              AND NOT EXISTS (SELECT 1 FROM schedule s WHERE s.draft_id = d.id)
            """,
            (product_id,)
        ).fetchone()["n"]

        # Posts marked as posted this calendar month
        month_prefix = datetime.now().strftime("%Y-%m")
        posted_this_month = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM schedule s
            JOIN drafts d ON d.id = s.draft_id
            WHERE d.product_id = ? AND s.posted_at LIKE ?
            """,
            (product_id, f"{month_prefix}%")
        ).fetchone()["n"]

        # Platform breakdown for scheduled (pending)
        platform_rows = conn.execute(
            """
            SELECT d.platform, COUNT(*) AS n
            FROM schedule s
            JOIN drafts d ON d.id = s.draft_id
            WHERE d.product_id = ? AND d.status = 'approved' AND s.posted_at IS NULL
            GROUP BY d.platform
            """,
            (product_id,)
        ).fetchall()

        platform_breakdown = {r["platform"]: r["n"] for r in platform_rows}

        return {
            "total_approved": total_approved,
            "scheduled_pending": scheduled_pending,
            "unscheduled": unscheduled,
            "posted_this_month": posted_this_month,
            "platform_breakdown": platform_breakdown,
        }


def get_approved_unscheduled_drafts(product_id: int) -> list[dict]:
    """
    Return approved drafts that have no schedule entry yet.
    Used by Tab 1 (Schedule a Draft) to populate the dropdown.
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT
                d.id            AS draft_id,
                d.platform,
                d.variant_number,
                d.content_format,
                d.headline,
                d.body,
                sa.angle_title
            FROM drafts d
            LEFT JOIN story_angles sa ON sa.id = d.story_angle_id
            WHERE d.product_id = ?
              AND d.status = 'approved'
              AND NOT EXISTS (SELECT 1 FROM schedule s WHERE s.draft_id = d.id)
            ORDER BY d.id ASC
            """,
            (product_id,)
        ).fetchall()

        return [dict(r) for r in rows]