"""One-time analysis script: parse editor_failed_responses.log and report recoverable reviews.

agents/editor.py writes two distinct entry types to the same log file:

  1. Full parse failures — the raw model response that could not be parsed as valid JSON.
     draft_id is NOT present in these entries; the model only returns {"issues": [...]},
     so the script cannot map a failure to a specific draft. Re-trigger by finding drafts
     with no review in the Editor page (Tab 3 -> Pipeline Overview).

  2. Dropped-issue entries — JSON was parsed successfully but one or more individual
     issue objects were malformed and stripped before the review was saved. These entries
     start with "DROPPED ISSUE — draft_id=<N> review_number=<N>". The review row was
     written; recovery means re-triggering a fresh re-review from the Editor page.

Because parse-failure entries don't include the draft_id, this script cannot insert
directly into the database for those entries. It reports what JSON was found, how many
issues are valid vs. dropped, and which draft to re-review from the UI.

Usage:
    python scripts/recover_editor_log.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import re

from agents.editor import _parse_editor_json, _validate_issues

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH     = PROJECT_ROOT / "data" / "editor_failed_responses.log"


# ─── Log parsing ──────────────────────────────────────────────────────────────

def extract_log_entries(log_text: str) -> list[tuple[str, str]]:
    """Split log on ={60} separators. Returns list of (timestamp, raw_text) tuples."""
    entries = []
    for part in re.split(r"={60,}", log_text):
        part = part.strip()
        if not part:
            continue
        lines = part.splitlines()
        timestamp = lines[0].strip() if lines else "unknown"
        body = "\n".join(lines[1:]).strip()
        if body:
            entries.append((timestamp, body))
    return entries


# ─── Dropped-issue entry helpers ──────────────────────────────────────────────

def _is_dropped_issue_entry(body: str) -> bool:
    return body.startswith("DROPPED ISSUE")


def _extract_dropped_issue_meta(body: str) -> tuple[int | None, int | None, str]:
    """Parse 'DROPPED ISSUE — draft_id=X review_number=Y\nReason: ...' header.

    Returns (draft_id, review_number, reason). Any field is None/"" when not found.
    """
    draft_id      = None
    review_number = None
    reason        = ""

    m = re.search(r"draft_id=(\d+)", body)
    if m:
        draft_id = int(m.group(1))

    m = re.search(r"review_number=(\d+)", body)
    if m:
        review_number = int(m.group(1))

    m = re.search(r"^Reason:\s*(.+)$", body, re.MULTILINE)
    if m:
        reason = m.group(1).strip()

    return draft_id, review_number, reason


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if not LOG_PATH.exists():
        print(f"No log file found at {LOG_PATH}")
        print("Either no parse failures or dropped issues have occurred yet, or the file was deleted.")
        sys.exit(0)

    log_text = LOG_PATH.read_text(encoding="utf-8")
    entries  = extract_log_entries(log_text)
    print(f"Log file : {LOG_PATH}  ({len(log_text):,} bytes)")
    print(f"Entries  : {len(entries)}\n")

    recovered      = 0
    partial        = 0
    dropped_count  = 0
    unreadable     = 0

    for i, (ts, body) in enumerate(entries, start=1):
        if _is_dropped_issue_entry(body):
            draft_id, review_number, reason = _extract_dropped_issue_meta(body)
            label = f"draft_id={draft_id}" if draft_id is not None else "draft_id=unknown"
            print(f"Entry {i} [{ts}] — DROPPED ISSUE ({label})")
            if review_number is not None:
                print(f"  Review number : {review_number}")
            if reason:
                print(f"  Reason        : {reason}")
            print(
                "  Action        : Re-trigger a fresh re-review for this draft from "
                "the Editor page (Tab 1 -> pick draft -> Re-review)."
            )
            dropped_count += 1

        else:
            parsed = _parse_editor_json(body)
            if parsed is None:
                print(f"Entry {i} [{ts}] — unparseable (truncated or malformed JSON)")
                print(f"  draft_id      : N/A (not present in model response)")
                print(f"  First 200 chars: {body[:200]!r}")
                unreadable += 1
            else:
                raw_issues           = parsed.get("issues", [])
                valid, dropped_issues = _validate_issues(raw_issues)
                codes                = [(iss["code"], iss["severity"]) for iss in valid]

                if not dropped_issues:
                    print(f"Entry {i} [{ts}] — RECOVERABLE JSON")
                    print(f"  draft_id      : N/A (not present in model response)")
                    print(f"  Issues found  : {len(valid)}")
                    if codes:
                        print(f"  Issue codes   : {codes}")
                    print(
                        "  Action        : Re-trigger review for the affected draft from "
                        "the Editor page (Tab 1 -> pick draft -> Re-review)."
                    )
                    recovered += 1
                else:
                    print(f"Entry {i} [{ts}] — PARTIALLY RECOVERABLE JSON")
                    print(f"  draft_id      : N/A (not present in model response)")
                    print(f"  Valid issues  : {len(valid)}")
                    print(f"  Dropped issues: {len(dropped_issues)}")
                    for _, reason in dropped_issues:
                        print(f"    Drop reason : {reason}")
                    if codes:
                        print(f"  Valid codes   : {codes}")
                    print(
                        "  Action        : Re-trigger review for the affected draft from "
                        "the Editor page (Tab 1 -> pick draft -> Re-review)."
                    )
                    partial += 1

        print()

    parse_total = recovered + partial + unreadable
    print(
        f"Summary — parse failures : {recovered} recoverable, {partial} partially recoverable, "
        f"{unreadable} unreadable  (of {parse_total} parse-failure entries)"
    )
    print(f"          dropped issues  : {dropped_count} dropped-issue entries")

    if recovered + partial > 0:
        print(
            "\nTo recover parse failures: open the Editor page, find drafts with no review "
            "(Tab 3 -> Pipeline Overview), then re-trigger from Tab 1."
        )
    if dropped_count > 0:
        print(
            "\nTo recover dropped issues: open the Editor page, find the listed draft_id(s) "
            "in Tab 1 and use Re-review to get a clean full result."
        )


if __name__ == "__main__":
    main()
