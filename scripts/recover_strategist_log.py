"""One-time recovery script: parse strategist_failed_responses.log and import salvaged angles.

Usage:
    python scripts/recover_strategist_log.py [--dry-run]

    --dry-run  Print what would be inserted without writing to the database.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = PROJECT_ROOT / "data" / "strategist_failed_responses.log"
DB_PATH  = PROJECT_ROOT / "data" / "app.db"

_VALID_PLATFORM  = {"instagram", "facebook", "both"}
_VALID_PHASE     = {"phase_1", "phase_2_hint", "phase_3_hint", "founder_credibility", "evergreen"}
_VALID_FUNNEL    = {"awareness", "consideration", "demo_pitch"}
_VALID_FORMAT    = {"single_image", "carousel", "video_script", "text_post", "reel_script"}
_VALID_CTA       = {"hard_cta", "soft_cta", "no_cta"}


# ─── Log parsing ──────────────────────────────────────────────────────────────

def extract_json_blocks(log_text: str) -> list[str]:
    """Split log on ==== separators and return the JSON portion of each entry."""
    blocks = []
    for part in re.split(r"={20,}", log_text):
        part = part.strip()
        if not part:
            continue
        lines = part.splitlines()
        # Skip the timestamp line; find the first line that begins the JSON object
        json_start = next(
            (i for i, ln in enumerate(lines) if ln.lstrip().startswith("{")), None
        )
        if json_start is not None:
            blocks.append("\n".join(lines[json_start:]))
    return blocks


def try_parse_complete(text: str) -> dict | None:
    """Same three-strategy parser as agents/strategist.py _parse_strategist_json()."""
    original = text.strip()
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
                if isinstance(parsed, dict) and "themes" in parsed:
                    return parsed
            except json.JSONDecodeError:
                continue
    return None


def salvage_themes(text: str) -> list[dict]:
    """Extract every complete theme object from truncated JSON via raw_decode."""
    m = re.search(r'"themes"\s*:\s*\[', text)
    if not m:
        return []

    remaining = text[m.end():]
    decoder   = json.JSONDecoder()
    themes: list[dict] = []

    while True:
        remaining = remaining.lstrip()
        if not remaining or remaining[0] in ("]", "}"):
            break
        if remaining[0] == ",":
            remaining = remaining[1:]
            continue
        try:
            obj, idx = decoder.raw_decode(remaining)
            if isinstance(obj, dict) and "angles" in obj:
                themes.append(obj)
            remaining = remaining[idx:]
        except json.JSONDecodeError:
            break

    return themes


# ─── Database helpers ─────────────────────────────────────────────────────────

def get_active_product_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM products WHERE is_active_client = 1 LIMIT 1"
    ).fetchone()
    return row[0] if row else 1


def angle_exists(conn: sqlite3.Connection, product_id: int, angle_title: str) -> bool:
    row = conn.execute(
        "SELECT id FROM story_angles WHERE product_id = ? AND angle_title = ? LIMIT 1",
        (product_id, angle_title),
    ).fetchone()
    return row is not None


def insert_angle(
    conn: sqlite3.Connection,
    product_id: int,
    theme_name: str,
    angle: dict,
) -> None:
    now         = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    title       = angle.get("angle_title", "Untitled")
    description = angle.get("angle_description", "")

    platform  = angle.get("platform_fit")   if angle.get("platform_fit")   in _VALID_PLATFORM else "both"
    phase     = angle.get("phase_tag")      if angle.get("phase_tag")      in _VALID_PHASE    else "phase_1"
    funnel    = angle.get("funnel_stage")   if angle.get("funnel_stage")   in _VALID_FUNNEL   else "awareness"
    fmt       = angle.get("content_format") if angle.get("content_format") in _VALID_FORMAT   else "single_image"
    cta       = angle.get("cta_strength")   if angle.get("cta_strength")   in _VALID_CTA      else "no_cta"

    src_ids  = angle.get("source_research_ids", [])
    proofs   = angle.get("proof_points_used", [])

    conn.execute(
        """
        INSERT INTO story_angles (
            product_id, title, angle,
            theme, angle_title, angle_description, editorial_brief,
            platform_fit, phase_tag, funnel_stage, content_format,
            cta_strength, source_research_ids, proof_points_used,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            title,       # legacy title column
            description, # legacy angle column
            theme_name,
            title,
            description,
            angle.get("editorial_brief", ""),
            platform,
            phase,
            funnel,
            fmt,
            cta,
            json.dumps(src_ids if isinstance(src_ids, list) else []),
            json.dumps(proofs  if isinstance(proofs,  list) else []),
            "proposed",
            now,
            now,
        ),
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    dry_run = "--dry-run" in sys.argv

    if not LOG_PATH.exists():
        print(f"ERROR: Log file not found: {LOG_PATH}")
        sys.exit(1)
    if not DB_PATH.exists():
        print(f"ERROR: Database not found: {DB_PATH}")
        sys.exit(1)

    log_text = LOG_PATH.read_text(encoding="utf-8")
    print(f"Log file : {LOG_PATH}  ({len(log_text):,} bytes)")

    json_blocks = extract_json_blocks(log_text)
    print(f"Log entries : {len(json_blocks)}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    product_id = get_active_product_id(conn)
    print(f"Product ID  : {product_id}")

    all_themes: list[dict] = []

    for i, block in enumerate(json_blocks, start=1):
        parsed = try_parse_complete(block)
        if parsed:
            themes = parsed.get("themes", [])
            print(f"Entry {i} : complete JSON — {len(themes)} theme(s)")
            all_themes.extend(themes)
        else:
            salvaged = salvage_themes(block)
            if salvaged:
                print(f"Entry {i} : truncated JSON — salvaged {len(salvaged)} complete theme(s)")
                all_themes.extend(salvaged)
            else:
                print(f"Entry {i} : WARNING — could not extract any themes")

    total_found = sum(
        len([a for a in t.get("angles", []) if isinstance(a, dict) and a.get("angle_title")])
        for t in all_themes
    )
    print(f"\nAngles found in log : {total_found}")

    inserted = 0
    skipped  = 0

    for theme_obj in all_themes:
        theme_name = str(theme_obj.get("theme_name") or "Uncategorized")
        for angle in theme_obj.get("angles", []):
            if not isinstance(angle, dict):
                continue
            if not angle.get("angle_title") or not angle.get("angle_description"):
                continue

            title = angle["angle_title"]

            if angle_exists(conn, product_id, title):
                print(f"  SKIP (already exists) : {title[:70]}")
                skipped += 1
                continue

            if dry_run:
                print(f"  DRY-RUN [{theme_name[:30]}] {title[:60]}")
            else:
                insert_angle(conn, product_id, theme_name, angle)
                print(f"  INSERTED [{theme_name[:30]}] {title[:60]}")
            inserted += 1

    if not dry_run:
        conn.commit()

    conn.close()

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Results:")
    print(f"  Angles in log file : {total_found}")
    print(f"  Imported           : {inserted}")
    print(f"  Skipped (duplicate): {skipped}")
    if dry_run:
        print("\nRe-run without --dry-run to commit.")


if __name__ == "__main__":
    main()
