"""
Scheduler agent — Sportz-Well Marketing Studio
Pure DB logic. Zero API calls. Zero cost.

Public functions
----------------
schedule_draft(draft_id, scheduled_for)        → dict  schedule a draft
unschedule(schedule_id)                        → dict  remove from schedule
reschedule(schedule_id, new_datetime)          → dict  change time
get_scheduled_drafts(start_date, end_date)     → list  calendar view
mark_as_posted(schedule_id)                    → dict  set posted_at
get_pipeline_summary(product_id)               → dict  approved: scheduled vs unscheduled
get_schedule_entry(schedule_id)                → dict | None  single row lookup
get_approved_unscheduled_drafts(product_id)    → list  drafts ready to schedule

record_performance(schedule_id, ...)           → dict  log an engagement snapshot
get_performance_for_draft(draft_id)            → list  full snapshot history
get_latest_performance_for_draft(draft_id)     → dict | None  most recent snapshot

NOTE (2026-06-29): This file previously used sqlite3-only patterns
(conn.row_factory = sqlite3.Row, dict-key row access, cursor.lastrowid) that
do not exist on the Postgres connection this app now runs on. Fixed throughout
— all row access is now positional (tuple indexing), matching the pattern
already proven working in 6_Media.py. INSERTs use RETURNING id instead of
lastrowid, which is the correct Postgres convention.
"""

from datetime import datetime, timezone
from services.database import get_connection


# ─── helpers ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _row_to_dict(cursor, row) -> dict:
    """Backend-agnostic dict conversion using cursor.description. Works the
    same whether the underlying driver is sqlite3 or psycopg2."""
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
    try:
        datetime.fromisoformat(scheduled_for)
    except ValueError:
        return _err(f"Invalid datetime format: '{scheduled_for}'. Use YYYY-MM-DDTHH:MM:SS")

    with get_connection() as conn:
        draft = conn.execute(
            "SELECT id, status, platform, product_id FROM drafts WHERE id = ?",
            (draft_id,)
        ).fetchone()

        if draft is None:
            return _err(f"Draft #{draft_id} not found.")

        draft_status = draft[1]
        draft_platform = draft[2]

        if draft_status != "approved":
            return _err(
                f"Draft #{draft_id} has status='{draft_status}'. "
                "Only approved drafts can be scheduled."
            )

        existing = conn.execute(
            "SELECT id FROM schedule WHERE draft_id = ?",
            (draft_id,)
        ).fetchone()

        if existing:
            return _err(
                f"Draft #{draft_id} is already scheduled (schedule #{existing[0]}). "
                "Use reschedule() to change the time."
            )

        result = conn.execute(
            """
            INSERT INTO schedule (draft_id, scheduled_for, posted_manually)
            VALUES (?, ?, 1)
            RETURNING id
            """,
            (draft_id, scheduled_for)
        ).fetchone()
        conn.commit()

        return _ok({
            "schedule_id": result[0],
            "draft_id": draft_id,
            "platform": draft_platform,
            "scheduled_for": scheduled_for,
        })


def unschedule(schedule_id: int) -> dict:
    """
    Remove a draft from the schedule entirely.
    Only allowed if the entry has not been posted yet.
    """
    with get_connection() as conn:
        entry = conn.execute(
            "SELECT id, draft_id, scheduled_for, posted_at FROM schedule WHERE id = ?",
            (schedule_id,)
        ).fetchone()

        if entry is None:
            return _err(f"Schedule entry #{schedule_id} not found.")

        if entry[3] is not None:
            return _err(
                f"Schedule entry #{schedule_id} has already been posted. Cannot unschedule."
            )

        conn.execute("DELETE FROM schedule WHERE id = ?", (schedule_id,))
        conn.commit()

        return _ok({
            "schedule_id": schedule_id,
            "draft_id": entry[1],
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
        entry = conn.execute(
            "SELECT id, draft_id, scheduled_for, posted_at FROM schedule WHERE id = ?",
            (schedule_id,)
        ).fetchone()

        if entry is None:
            return _err(f"Schedule entry #{schedule_id} not found.")

        if entry[3] is not None:
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
            "draft_id": entry[1],
            "old_datetime": entry[2],
            "new_datetime": new_datetime,
        })


def mark_as_posted(schedule_id: int) -> dict:
    """
    Mark a scheduled post as manually posted (copy-paste into Meta Business
    Suite / LinkedIn). Sets posted_at to current UTC time.
    """
    with get_connection() as conn:
        entry = conn.execute(
            "SELECT id, draft_id, scheduled_for, posted_at FROM schedule WHERE id = ?",
            (schedule_id,)
        ).fetchone()

        if entry is None:
            return _err(f"Schedule entry #{schedule_id} not found.")

        if entry[3] is not None:
            return _err(
                f"Schedule entry #{schedule_id} was already marked posted at {entry[3]}."
            )

        posted_at = _now_iso()
        conn.execute(
            "UPDATE schedule SET posted_at = ? WHERE id = ?",
            (posted_at, schedule_id)
        )
        conn.commit()

        return _ok({
            "schedule_id": schedule_id,
            "draft_id": entry[1],
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
    start_dt = f"{start_date}T00:00:00"
    end_dt   = f"{end_date}T23:59:59"

    with get_connection() as conn:
        cursor = conn.execute(
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
        )
        rows = cursor.fetchall()
        return [_row_to_dict(cursor, r) for r in rows]


def get_schedule_entry(schedule_id: int) -> dict | None:
    """Return a single schedule row with draft details, or None if not found."""
    with get_connection() as conn:
        cursor = conn.execute(
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
        )
        row = cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None


def get_pipeline_summary(product_id: int) -> dict:
    """
    Return counts for the pipeline overview:
    - approved drafts total
    - approved drafts that ARE scheduled (and not yet posted)
    - approved drafts that are NOT scheduled
    - posted this month
    """
    with get_connection() as conn:
        total_approved = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE product_id = ? AND status = 'approved'",
            (product_id,)
        ).fetchone()[0]

        scheduled_pending = conn.execute(
            """
            SELECT COUNT(*)
            FROM schedule s
            JOIN drafts d ON d.id = s.draft_id
            WHERE d.product_id = ? AND d.status = 'approved' AND s.posted_at IS NULL
            """,
            (product_id,)
        ).fetchone()[0]

        unscheduled = conn.execute(
            """
            SELECT COUNT(*)
            FROM drafts d
            WHERE d.product_id = ? AND d.status = 'approved'
              AND NOT EXISTS (SELECT 1 FROM schedule s WHERE s.draft_id = d.id)
            """,
            (product_id,)
        ).fetchone()[0]

        month_prefix = datetime.now().strftime("%Y-%m")
        posted_this_month = conn.execute(
            """
            SELECT COUNT(*)
            FROM schedule s
            JOIN drafts d ON d.id = s.draft_id
            WHERE d.product_id = ? AND s.posted_at LIKE ?
            """,
            (product_id, f"{month_prefix}%")
        ).fetchone()[0]

        platform_rows = conn.execute(
            """
            SELECT d.platform, COUNT(*)
            FROM schedule s
            JOIN drafts d ON d.id = s.draft_id
            WHERE d.product_id = ? AND d.status = 'approved' AND s.posted_at IS NULL
            GROUP BY d.platform
            """,
            (product_id,)
        ).fetchall()

        platform_breakdown = {r[0]: r[1] for r in platform_rows}

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
        cursor = conn.execute(
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
        )
        rows = cursor.fetchall()
        return [_row_to_dict(cursor, r) for r in rows]


# ─── performance tracking (added 2026-06-29) ───────────────────────────────
# No platform API pulls these numbers automatically — Jitendra types in what
# he sees on FB/IG/LinkedIn. Multiple snapshots per schedule_id are allowed
# on purpose, so growth over time can be tracked (check at posting, check
# again a few days later). This is the feedback loop Strategist currently
# has no access to — closing it is the prerequisite for any future
# performance-weighted angle scoring.

def record_performance(
    schedule_id: int,
    likes: int = 0,
    comments: int = 0,
    shares: int = 0,
    notes: str | None = None,
) -> dict:
    """
    Log an engagement snapshot for a posted draft.

    Only allowed once the schedule entry has been marked as posted — there's
    nothing meaningful to measure before that. Each call adds a NEW row; it
    never overwrites a previous snapshot, so the same post can be checked
    multiple times to see how engagement grows.

    Parameters
    ----------
    schedule_id : int   — the schedule entry this snapshot belongs to
    likes       : int   — count seen on the platform
    comments    : int
    shares      : int
    notes       : str | None  — optional, e.g. "checked 48hrs after posting"

    Returns
    -------
    dict with ok=True, performance_id, and engagement_total, or ok=False + error.
    """
    for label, val in (("likes", likes), ("comments", comments), ("shares", shares)):
        if val < 0:
            return _err(f"{label} cannot be negative.")

    with get_connection() as conn:
        entry = conn.execute(
            "SELECT id, draft_id, posted_at FROM schedule WHERE id = ?",
            (schedule_id,)
        ).fetchone()

        if entry is None:
            return _err(f"Schedule entry #{schedule_id} not found.")

        if entry[2] is None:
            return _err(
                f"Schedule entry #{schedule_id} has not been marked as posted yet. "
                "Mark it as posted before recording performance."
            )

        result = conn.execute(
            """
            INSERT INTO post_performance (schedule_id, likes, comments, shares, notes)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id, recorded_at
            """,
            (schedule_id, likes, comments, shares, notes)
        ).fetchone()
        conn.commit()

        return _ok({
            "performance_id": result[0],
            "schedule_id": schedule_id,
            "draft_id": entry[1],
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "engagement_total": likes + comments + shares,
            "recorded_at": result[1],
        })


def get_performance_for_draft(draft_id: int) -> list[dict]:
    """
    Return every performance snapshot recorded for a draft's scheduled post,
    oldest first. Each entry includes engagement_total (likes + comments +
    shares) — a plain sum, no weighting or formula yet. That comes later,
    once there's enough real data to weight against.

    Returns an empty list if the draft was never scheduled, never posted,
    or has no recorded snapshots yet.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT pp.id, pp.schedule_id, pp.likes, pp.comments, pp.shares,
                   pp.notes, pp.recorded_at
            FROM post_performance pp
            JOIN schedule s ON s.id = pp.schedule_id
            WHERE s.draft_id = ?
            ORDER BY pp.recorded_at ASC
            """,
            (draft_id,)
        )
        rows = cursor.fetchall()

        results = []
        for r in rows:
            likes, comments, shares = r[2], r[3], r[4]
            results.append({
                "performance_id":   r[0],
                "schedule_id":      r[1],
                "likes":            likes,
                "comments":         comments,
                "shares":           shares,
                "notes":            r[5],
                "recorded_at":      r[6],
                "engagement_total": likes + comments + shares,
            })
        return results


def get_latest_performance_for_draft(draft_id: int) -> dict | None:
    """
    Return only the most recent performance snapshot for a draft, or None if
    nothing has been recorded yet. Convenience wrapper so the Calendar page
    can show one number next to a posted entry without pulling full history.
    """
    history = get_performance_for_draft(draft_id)
    return history[-1] if history else None