"""Throwaway dry-run: send one draft through the Editor system prompt and print the raw response.

NO side effects — no DB inserts, no api_log writes, no file writes.

Usage (from project root):
    python scripts/dry_run_editor.py

Expected: PROOF_POINT_LINEAGE_DRIFT fires for Achrekar IG V2 (draft_id=2).
Pass criterion: clean parseable JSON + that flag present.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── path setup so services/agents are importable from project root ──────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.editor import _build_system_prompt
from services.anthropic_client import ask_with_usage, DEFAULT_MODEL
from services.brand_context import build_brand_context_prompt
from services.database import get_connection

# ── config ──────────────────────────────────────────────────────────────────
DRAFT_ID = 2
INPUT_COST_PER_TOKEN  = 3.00  / 1_000_000   # USD
OUTPUT_COST_PER_TOKEN = 15.00 / 1_000_000   # USD
USD_TO_INR            = 85.0                 # approximate


# ── helpers ─────────────────────────────────────────────────────────────────

def load_draft(draft_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        raise ValueError(f"draft_id={draft_id} not found in drafts table")
    return dict(row)


def load_angle(story_angle_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM story_angles WHERE id = ?", (story_angle_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"story_angle_id={story_angle_id} not found in story_angles table")
    return dict(row)


def load_siblings(story_angle_id: int, exclude_draft_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM drafts WHERE story_angle_id = ? AND id != ?",
            (story_angle_id, exclude_draft_id),
        ).fetchall()
    return [dict(r) for r in rows]


def parse_hashtags(raw: str | None, draft_id: int) -> list[str]:
    if raw is None:
        raise ValueError(
            f"draft_id={draft_id}: hashtags column is NULL. "
            "Cannot safely pass an empty list — that would manufacture a false HASHTAG_COUNT_LOW flag."
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"draft_id={draft_id}: hashtags column is not valid JSON: {exc}"
        ) from exc
    if not isinstance(parsed, list):
        raise ValueError(
            f"draft_id={draft_id}: hashtags parsed to {type(parsed).__name__}, expected list"
        )
    return parsed


def build_draft_block(draft: dict, angle: dict) -> dict:
    """Assemble the 'draft' sub-object the system prompt expects."""
    hashtags = parse_hashtags(draft.get("hashtags"), draft["id"])

    slides = None
    if draft.get("carousel_slides"):
        try:
            slides = json.loads(draft["carousel_slides"])
        except json.JSONDecodeError:
            slides = draft["carousel_slides"]  # pass raw; model will still see the value

    reel_script = None
    if draft.get("reel_script"):
        try:
            reel_script = json.loads(draft["reel_script"])
        except json.JSONDecodeError:
            reel_script = draft["reel_script"]

    return {
        "id":             draft["id"],
        "platform":       draft["platform"],
        "variant_number": draft["variant_number"],
        "content_format": draft["content_format"],
        "headline":       draft.get("headline"),
        "body":           draft["body"],
        "cta_line":       draft.get("cta_line"),
        "cta_strategy":   angle["cta_strength"],   # check 7 and 10 read this
        "hashtags":       hashtags,
        "image_brief":    draft.get("image_brief"),
        "slides":         slides,
        "reel_script":    reel_script,
    }


def build_angle_block(angle: dict) -> dict:
    return {
        "angle_title":     angle.get("angle_title") or angle["title"],
        "editorial_brief": angle.get("editorial_brief"),   # check 6 reads this
        "cta_strength":    angle["cta_strength"],
        "content_format":  angle.get("content_format"),
        "platform_fit":    angle.get("platform_fit"),
    }


def build_sibling_block(sibling: dict) -> dict:
    hook = ""
    if sibling.get("body"):
        hook = sibling["body"].split("\n")[0].strip()
    return {
        "variant_number": sibling["variant_number"],
        "platform":       sibling["platform"],
        "headline":       sibling.get("headline"),
        "hook":           hook,
    }


# ── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Loading draft_id={DRAFT_ID} ...")
    draft  = load_draft(DRAFT_ID)
    angle  = load_angle(draft["story_angle_id"])
    siblings = load_siblings(draft["story_angle_id"], exclude_draft_id=DRAFT_ID)

    print(f"  Draft  : {draft['platform']} variant {draft['variant_number']} "
          f"({draft['content_format']}) — status={draft['status']}")
    print(f"  Angle  : {angle.get('angle_title') or angle['title']}")
    print(f"  Siblings found: {len(siblings)}")
    for s in siblings:
        print(f"    - draft_id={s['id']} {s['platform']} v{s['variant_number']}")

    # Build brand context
    product_id = draft["product_id"]
    brand_ctx  = build_brand_context_prompt(product_id)

    # Build user message
    user_message = json.dumps(
        {
            "draft":            build_draft_block(draft, angle),
            "source_angle":     build_angle_block(angle),
            "sibling_variants": [build_sibling_block(s) for s in siblings],
        },
        ensure_ascii=False,
        indent=2,
    )

    print("\n── USER MESSAGE SENT TO MODEL ──────────────────────────────────────────")
    print(user_message)
    print("────────────────────────────────────────────────────────────────────────\n")

    # Call the model
    system_prompt = _build_system_prompt(brand_ctx)
    print(f"Calling {DEFAULT_MODEL} (max_tokens=8192) ...")

    api_result = ask_with_usage(
        system_prompt=system_prompt,
        user_prompt=user_message,
        model=DEFAULT_MODEL,
        max_tokens=8192,
    )

    if api_result["error"]:
        print(f"\nAPI ERROR: {api_result['error']}")
        sys.exit(1)

    raw_response  = api_result["text"]
    input_tokens  = api_result["input_tokens"]
    output_tokens = api_result["output_tokens"]
    web_searches  = api_result["web_searches"]
    cost_usd      = (input_tokens * INPUT_COST_PER_TOKEN) + (output_tokens * OUTPUT_COST_PER_TOKEN)
    cost_inr      = cost_usd * USD_TO_INR

    print("\n── RAW MODEL RESPONSE ──────────────────────────────────────────────────")
    print(raw_response)
    print("────────────────────────────────────────────────────────────────────────")

    print(f"\n── USAGE ───────────────────────────────────────────────────────────────")
    print(f"  Input tokens  : {input_tokens:,}")
    print(f"  Output tokens : {output_tokens:,}")
    print(f"  Web searches  : {web_searches}")
    print(f"  Cost          : ${cost_usd:.4f} USD  /  ₹{cost_inr:.2f} INR")
    print("────────────────────────────────────────────────────────────────────────")

    # Quick sanity check — don't parse deeply, just confirm it's JSON with "issues"
    print("\n── QUICK SANITY CHECK ──────────────────────────────────────────────────")
    try:
        parsed = json.loads(raw_response.strip())
        issues = parsed.get("issues", [])
        codes  = [i.get("code") for i in issues]
        print(f"  JSON valid    : YES")
        print(f"  Issues count  : {len(issues)}")
        print(f"  Codes found   : {codes}")
        if "PROOF_POINT_LINEAGE_DRIFT" in codes:
            print("  PROOF_POINT_LINEAGE_DRIFT : FIRED ✓  (expected)")
        else:
            print("  PROOF_POINT_LINEAGE_DRIFT : DID NOT FIRE  ← investigate")
    except json.JSONDecodeError as exc:
        print(f"  JSON valid    : NO — {exc}")
        print("  ← Model did not return clean JSON; inspect raw response above.")
    print("────────────────────────────────────────────────────────────────────────")


if __name__ == "__main__":
    main()
