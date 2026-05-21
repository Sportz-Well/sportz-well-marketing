"""One-off script: run the Editor agent over the 7 unreviewed drafts.

Draft 1 already has a review. Remaining unreviewed draft_ids: 2, 3, 4, 5, 6, 11, 12.
Note: IDs 7-10 do not exist in the database (gap from a prior deletion).

Usage:
    python scripts/batch_review_remaining.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3

from agents.editor import review_draft
from services.database import get_connection

DRAFT_IDS   = [2, 3, 4, 5, 6, 11, 12]
INR_PER_USD = 85.0


def _fetch_draft_meta(draft_ids: list[int]) -> dict[int, dict]:
    """Return {draft_id: {platform, variant_number}} for the given IDs."""
    placeholders = ",".join("?" * len(draft_ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, platform, variant_number FROM drafts WHERE id IN ({placeholders})",
            draft_ids,
        ).fetchall()
    return {r["id"]: {"platform": r["platform"], "variant_number": r["variant_number"]} for r in rows}


def main() -> None:
    meta      = _fetch_draft_meta(DRAFT_IDS)
    total_usd = 0.0

    print(f"{'draft_id':<10} {'platform':<12} {'variant':<8} {'verdict':<8} {'issues':<7} cost_inr")
    print("-" * 65)

    for draft_id in DRAFT_IDS:
        result   = review_draft(draft_id)
        platform = meta.get(draft_id, {}).get("platform", "?")
        variant  = meta.get(draft_id, {}).get("variant_number", "?")

        if result["error"]:
            print(f"draft_id={draft_id:<2} | {platform:<12} | v{variant:<6} | ERROR    | -      | {result['error'][:40]}")
            continue

        cost_inr   = result["est_cost_usd"] * INR_PER_USD
        total_usd += result["est_cost_usd"]

        print(
            f"draft_id={draft_id:<2} | "
            f"{platform:<12} | "
            f"v{variant:<6} | "
            f"{result['verdict']:<8} | "
            f"{len(result['issues']):<6} | "
            f"INR {cost_inr:.2f}"
        )

    total_inr = total_usd * INR_PER_USD
    print("-" * 65)
    print(f"Total: ${total_usd:.6f} USD  |  INR {total_inr:.2f}  ({len(DRAFT_IDS)} drafts)")


if __name__ == "__main__":
    main()
