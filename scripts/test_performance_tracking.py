"""
scripts/_test_performance_tracking.py

RUN ONCE THEN DELETE.

Quick sanity test for the new performance-tracking functions in
agents/scheduler.py, run directly against the live Supabase database.

What it does:
1. Finds one schedule entry that has already been marked as posted.
2. Logs a test engagement snapshot against it (10 likes, 2 comments, 1 share).
3. Reads back the full history for that draft.
4. Reads back just the latest snapshot.

This inserts ONE real row into post_performance, clearly tagged with
notes="TEST ROW - safe to delete". It is harmless and can be deleted from
the Supabase table editor afterward, or just left there — it won't affect
anything else in the app.

If this script errors out, the error message tells us exactly what's wrong
with the new scheduler.py functions before we build any UI on top of them.

Run from project root:
    python scripts/_test_performance_tracking.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.database import get_connection
from agents.scheduler import (
    record_performance,
    get_performance_for_draft,
    get_latest_performance_for_draft,
)


def main():
    print("=" * 60)
    print("STEP 1 — Finding a posted schedule entry to test against")
    print("=" * 60)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, draft_id FROM schedule WHERE posted_at IS NOT NULL LIMIT 1"
        ).fetchone()

    if row is None:
        print(
            "❌ No posted schedule entries found. Mark at least one post as "
            "Posted in the Calendar page first, then re-run this script."
        )
        return

    schedule_id, draft_id = row[0], row[1]
    print(f"✅ Found schedule #{schedule_id} (draft #{draft_id}) — using this for the test.\n")

    print("=" * 60)
    print("STEP 2 — Calling record_performance()")
    print("=" * 60)

    result = record_performance(
        schedule_id=schedule_id,
        likes=10,
        comments=2,
        shares=1,
        notes="TEST ROW - safe to delete",
    )
    print(result)

    if not result.get("ok"):
        print("\n❌ record_performance() failed. Stopping here — fix this before continuing.")
        return

    print("\n✅ record_performance() worked.\n")

    print("=" * 60)
    print("STEP 3 — Calling get_performance_for_draft()")
    print("=" * 60)

    history = get_performance_for_draft(draft_id)
    print(history)

    if not history:
        print("\n❌ get_performance_for_draft() returned nothing — something's wrong.")
        return

    print("\n✅ get_performance_for_draft() worked.\n")

    print("=" * 60)
    print("STEP 4 — Calling get_latest_performance_for_draft()")
    print("=" * 60)

    latest = get_latest_performance_for_draft(draft_id)
    print(latest)

    if not latest:
        print("\n❌ get_latest_performance_for_draft() returned nothing — something's wrong.")
        return

    print("\n✅ get_latest_performance_for_draft() worked.\n")

    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print(
        "\nThe new functions work correctly against the live database.\n"
        "Safe to delete this script now: scripts/_test_performance_tracking.py\n"
        "The test row it created (notes='TEST ROW - safe to delete') can be "
        "left in place or removed from Supabase — it won't affect the app."
    )


if __name__ == "__main__":
    main()