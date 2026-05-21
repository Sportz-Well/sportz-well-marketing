"""One-time analysis script: parse copywriter_failed_responses.log and report recoverable drafts.

Because failed-response log entries don't include the angle_id, this script
cannot insert directly into the database. It reports what JSON was found and
which angle to re-trigger drafting for from the UI.

Usage:
    python scripts/recover_copywriter_log.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = PROJECT_ROOT / "data" / "copywriter_failed_responses.log"


# ─── Log parsing ──────────────────────────────────────────────────────────────

def extract_log_entries(log_text: str) -> list[tuple[str, str]]:
    """Split log on ==== separators. Returns list of (timestamp, raw_text) tuples."""
    entries = []
    for part in re.split(r"={20,}", log_text):
        part = part.strip()
        if not part:
            continue
        lines = part.splitlines()
        timestamp = lines[0].strip() if lines else "unknown"
        body = "\n".join(lines[1:]).strip()
        if body:
            entries.append((timestamp, body))
    return entries


def try_parse_json(text: str) -> dict | None:
    """Same three-strategy parser as agents/copywriter.py _parse_copywriter_json()."""
    original   = text.strip()
    candidates: list[str] = []

    m = re.search(r"```(?:json)?\s*\r?\n?([\s\S]*?)\r?\n?```", original)
    if m:
        candidates.append(m.group(1).strip())

    stripped = re.sub(r"^```(?:json)?\s*\r?\n?", "", original)
    stripped = re.sub(r"\r?\n?```\s*$", "", stripped).strip()
    if stripped and stripped not in candidates:
        candidates.append(stripped)

    fb, lb = original.find("{"), original.rfind("}")
    if fb != -1 and lb > fb:
        brace = original[fb : lb + 1]
        if brace not in candidates:
            candidates.append(brace)

    for candidate in candidates:
        cleaned = re.sub(r",(\s*[}\]])", r"\1", candidate)
        for attempt in (cleaned, candidate):
            try:
                parsed = json.loads(attempt)
                if isinstance(parsed, dict) and "drafts" in parsed:
                    return parsed
            except json.JSONDecodeError:
                continue
    return None


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if not LOG_PATH.exists():
        print(f"No log file found at {LOG_PATH}")
        print("Either no parse failures have occurred yet, or the file was deleted.")
        sys.exit(0)

    log_text = LOG_PATH.read_text(encoding="utf-8")
    entries  = extract_log_entries(log_text)
    print(f"Log file : {LOG_PATH}  ({len(log_text):,} bytes)")
    print(f"Entries  : {len(entries)}\n")

    recovered  = 0
    unreadable = 0

    for i, (ts, body) in enumerate(entries, start=1):
        parsed = try_parse_json(body)
        if parsed:
            drafts = parsed.get("drafts", [])
            pairs  = [(d.get("platform"), d.get("variant_number")) for d in drafts]
            print(f"Entry {i} [{ts}] — RECOVERABLE JSON")
            print(f"  Drafts found : {len(drafts)}")
            print(f"  Pairs        : {pairs}")
            warnings = parsed.get("warnings", [])
            if warnings:
                print(f"  Warnings     : {warnings}")
            print(
                "  Action       : Re-trigger drafting for the affected angle from "
                "the Drafts page (Tab 1 → pick angle → Generate)."
            )
            recovered += 1
        else:
            print(f"Entry {i} [{ts}] — unparseable (truncated or malformed JSON)")
            print(f"  First 200 chars: {body[:200]!r}")
            unreadable += 1
        print()

    print(f"Summary: {recovered} recoverable, {unreadable} unreadable out of {len(entries)} entries.")
    if recovered > 0:
        print(
            "\nTo recover: open the Drafts page, identify which angle(s) have no drafts "
            "(Tab 3 → Pipeline Overview), then re-trigger from Tab 1."
        )


if __name__ == "__main__":
    main()
