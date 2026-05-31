"""Editor agent — fourth agent in the pipeline.

Reads a Copywriter draft, checks it against an explicit ruleset, and writes
a verdict (clean / flagged) plus a structured issues list to editor_reviews.

V1 is FLAG-ONLY: the agent identifies issues but does NOT rewrite.

Public API
----------
review_draft(draft_id)                   -> dict
rereview_draft(draft_id)                 -> dict
review_all_unreviewed_drafts(product_id) -> dict
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.anthropic_client import ask_with_usage, DEFAULT_MODEL
from services.brand_context import build_brand_context_prompt
from services.database import get_connection

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_LOG_PATH = PROJECT_ROOT / "data" / "api_log.csv"

_INPUT_COST_PER_TOKEN  = 3.00  / 1_000_000
_OUTPUT_COST_PER_TOKEN = 15.00 / 1_000_000

_VALID_SEVERITIES    = {"hard", "soft"}
_VALID_FIELDS        = {"hook", "body", "cta_line", "hashtags", "image_brief", "headline", "overall"}
_REQUIRED_ISSUE_KEYS = {"code", "severity", "field", "evidence", "message"}

_SYSTEM_PROMPT_TEMPLATE = """\
You are the Editor agent for Sportz-Well's marketing pipeline.

{brand_ctx}

## Your Role

You receive ONE social media draft. Identify issues against an explicit ruleset and return structured JSON. Do NOT rewrite. Do NOT suggest replacement text. Identify problems only.

---

## Checks

### HARD CHECK 1 — HYPE_WORD
Severity: hard | Field: body or headline

Banned words (check case-insensitively):
  transformative, transform (as marketing verb), game-changing, game-changer,
  revolutionary, revolutionize, revolutionising, world-class, best-in-class,
  cutting-edge, state-of-the-art, unleash, unlock potential, level up, level-up,
  next-level, elevate (as hype), empower, empowering, empowers, supercharge,
  harness the power, limitless, boundless, redefining, reimagining, paradigm shift,
  disrupt (as positive descriptor), synergy, leverage (as verb), holistic (vague),
  seamless (vague praise), robust (vague praise)

DO NOT flag: "transform" used literally, "leverage" as noun, banned word in a direct quote.

Evidence: quote the offending word/phrase.
Message: "Banned hype word: '[word]'. Brand voice is Expert, Structured, Purposeful."

---

### HARD CHECK 2 — URL_FORMAT
Severity: hard | Field: cta_line

Applies only when cta_line is non-null and non-empty.
Flag if cta_line contains: "www.sportz-well", "https://", or "http://"
Correct format: sportz-well.com — no prefix, no protocol.

Evidence: the full cta_line value.
Message: "URL in cta_line contains a disallowed prefix. Must appear exactly as: sportz-well.com"

---

### HARD CHECK 3 — CAPTION_TOO_LONG / CAPTION_TOO_SHORT
Severity: hard | Field: body

Count words in body (split on whitespace). Compare against expected range:

  Instagram + single_image:    80–130 words
  Instagram + carousel:        80–130 words
  Instagram + reel_script:     50–100 words
  Instagram + video_script:    50–100 words
  Facebook  + single_image:    60–120 words
  Facebook  + text_post:       60–150 words
  Facebook  + carousel:        60–120 words
  Facebook  + reel_script:     50–100 words
  LinkedIn  + single_image:   150–300 words
  LinkedIn  + text_post:      100–250 words

CAPTION_TOO_LONG if above upper bound. CAPTION_TOO_SHORT if below lower bound.

Evidence: "X words (expected Y–Z words for [platform] [content_format])"
Message: explain which bound was exceeded and why it matters for that platform.

---

### HARD CHECK 4 — HASHTAG_COUNT_LOW / HASHTAG_COUNT_HIGH
Severity: hard | Field: hashtags

  Instagram: below 8 → HASHTAG_COUNT_LOW; above 15 → HASHTAG_COUNT_HIGH
  Facebook:  above 5 → HASHTAG_COUNT_HIGH; do NOT flag for low count
  LinkedIn:  above 5 → HASHTAG_COUNT_HIGH; do NOT flag for low count

Evidence: "X hashtag(s) (expected Y–Z for [platform])"
Message: state the platform's hashtag convention.

---

### HARD CHECK 5 — PROOF_POINT_LINEAGE_DRIFT
Severity: hard (downgrade to soft when in doubt) | Field: body or headline

Sparing proof points (Achrekar, Tendulkar, Shardashram) MUST be framed institutionally.
FLAG if the draft implies personal founder lineage or uses names as celebrity credibility levers.
DO NOT FLAG institutional framing like "coaching philosophy that shaped Mumbai's grassroots tradition."

Evidence: the specific offending phrase.
Message: "Proof-point lineage drift. References must be institutional, not personal claims."

---

### HARD CHECK 6 — HINGLISH_UNCALLED
Severity: hard | Field: body

Flag if draft contains Devanagari script or transliterated Hindi words used non-ironically:
  jugaad, khel, maidan, guru (as role), shishya, desi, yaar, arre, chalo, khelna, leke,
  abhi, nahi, aur, baat, bhi, toh, hai, hain, lagta, mujhe, apna, unka, iska, kya, acha

DO NOT FLAG: Shardashram, BCCI, Ranji Trophy, Mumbai — not Hinglish.
Skip check if editorial_brief explicitly permits Hinglish.

Evidence: the offending word/phrase.
Message: "Hinglish word used without explicit brief permission. Default voice is English-only."

---

### HARD CHECK 7 — MISSING_REQUIRED_FIELD
Severity: hard | Field: varies

  Rule A — hard_cta: cta_line MUST be non-null, non-empty, AND contain "sportz-well.com".
  Rule B — no_cta: cta_line MUST be null or empty.
  Rule C — soft_cta: flag ONLY if cta_line is null or empty.
  Rule D — single_image or carousel (non-LinkedIn): image_brief must be ≥10 chars.
  Rule D2 — LinkedIn single_image: image_brief must be ≥10 chars.
  Rule E — carousel: slides field must have ≥2 entries.
  Rule F — reel_script: reel_script field must be non-null OR body must contain shot-direction language.
  Rule G — LinkedIn + unsupported format: flag if content_format not in (single_image, text_post).

---

### HARD CHECK 8 — CROSS_VARIANT_DUPLICATION
Severity: hard | Field: hook or headline

Skip entirely if sibling_variants is empty.
FLAG if this draft's hook or headline is byte-identical or near-identical paraphrase of a sibling's.

Evidence: quote both hooks/headlines with sibling variant_number and platform.
Message: "Hook/headline is near-identical to Variant [N] ([platform])."

---

### SOFT CHECK 9 — GENERIC_HOOK
Severity: soft | Field: hook

Flag if line 1 opens with generic patterns:
  "In today's world", "In this fast-paced world", "Cricket is more than",
  "Imagine a world where", "Have you ever wondered" (floating, no specific subject),
  "Did you know that" (generic, no specific claim),
  bare definition: "[Topic] is the practice/process/art of..."

DO NOT FLAG specific, concrete hooks anchored to age group, position, or tournament.

Evidence: the full hook line.
Message: "Generic hook pattern. Line 1 must earn attention with specificity."

---

### SOFT CHECK 10 — WEAK_CTA_BUILDUP
Severity: soft | Field: body

Applies ONLY for hard_cta. Skip for soft_cta and no_cta.
Flag only when the final paragraph makes zero thematic connection to the CTA. Err strongly toward NOT flagging.

Evidence: quote the final paragraph and cta_line.
Message: "Hard CTA may feel tacked on. Final paragraph does not build toward a next step."

---

## Output Format

Respond with a single JSON object. No markdown fences. No prose before or after.
Output your final JSON once only.

{{
  "issues": [
    {{
      "code":     "HYPE_WORD",
      "severity": "hard",
      "field":    "body",
      "evidence": "exact quote or value from the draft, max ~120 chars",
      "message":  "human-readable explanation, max ~200 chars"
    }}
  ]
}}

If no issues: {{"issues": []}}

Rules:
- No "verdict" field — Python computes it.
- No "suggestions" field — identification only.
- Every issue needs all five fields: code, severity, field, evidence, message.
- severity: exactly "hard" or "soft".
- field: one of: hook, body, cta_line, hashtags, image_brief, headline, overall.
- One issue per violation.\
"""


def _build_system_prompt(brand_ctx: str) -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(brand_ctx=brand_ctx)


# ─── Public entry points ──────────────────────────────────────────────────────

def review_draft(draft_id: int) -> dict[str, Any]:
    existing = _fetch_latest_review(draft_id)
    if existing is not None:
        return {
            "draft_id": draft_id, "review_number": existing["review_number"],
            "verdict": existing["verdict"], "issues": existing["issues"],
            "est_cost_usd": 0.0, "reviewed_at": existing["reviewed_at"], "error": None,
        }
    return _run_review(draft_id)


def rereview_draft(draft_id: int) -> dict[str, Any]:
    return _run_review(draft_id)


# ─── Core orchestration ───────────────────────────────────────────────────────

def _run_review(draft_id: int) -> dict[str, Any]:
    draft = _fetch_draft(draft_id)
    if draft is None:
        return _error_result(draft_id, 0.0, f"draft_id={draft_id} not found")

    angle = _fetch_angle(draft["story_angle_id"])
    if angle is None:
        return _error_result(draft_id, 0.0, f"story_angle_id={draft['story_angle_id']} not found")

    siblings   = _fetch_siblings(draft["story_angle_id"], exclude_draft_id=draft_id)
    product_id = draft["product_id"]
    brand_ctx  = build_brand_context_prompt(product_id)

    user_message, msg_error = _build_user_message(draft, angle, siblings)
    if msg_error:
        return _error_result(draft_id, 0.0, msg_error)

    api_result = ask_with_usage(
        system_prompt=_build_system_prompt(brand_ctx),
        user_prompt=user_message,
        model=DEFAULT_MODEL,
        max_tokens=8192,
    )

    cost = _estimate_cost(api_result["input_tokens"], api_result["output_tokens"])

    if api_result["error"]:
        _log_api_call(product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
            f"FAILURE: API error: {api_result['error'][:200]}")
        return _error_result(draft_id, cost, api_result["error"])

    parse_result = _parse_editor_json(api_result["text"])
    if parse_result is None:
        _log_failed_response(api_result["text"])
        _log_api_call(product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
            f"FAILURE: JSON parse failed. Raw (first 300): {api_result['text'][:300]}")
        return _error_result(draft_id, cost,
            f"Could not parse model response as JSON. Raw (first 500): {api_result['text'][:500]}")

    issues, dropped = _validate_issues(parse_result.get("issues", []))
    verdict = _compute_verdict(issues)

    review_number, reviewed_at = _save_review(
        draft_id, verdict, issues, api_result["text"],
        api_result["input_tokens"], api_result["output_tokens"], cost,
    )

    if dropped:
        for raw_issue, reason in dropped:
            _log_failed_response(
                f"DROPPED ISSUE — draft_id={draft_id} review_number={review_number}\n"
                f"Reason: {reason}\nRaw issue: {json.dumps(raw_issue, ensure_ascii=False)}"
            )

    _log_api_call(product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
        f"SUCCESS: draft_id={draft_id}, verdict={verdict}, issues={len(issues)}, dropped={len(dropped)}")

    return {
        "draft_id": draft_id, "review_number": review_number, "verdict": verdict,
        "issues": issues, "est_cost_usd": cost, "reviewed_at": reviewed_at, "error": None,
    }


# ─── Data loading ─────────────────────────────────────────────────────────────

def _fetch_draft(draft_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    return dict(row) if row else None


def _fetch_angle(story_angle_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, product_id, angle_title, title, editorial_brief,
                      platform_fit, cta_strength, content_format
               FROM story_angles WHERE id = ?""",
            (story_angle_id,),
        ).fetchone()
    return dict(row) if row else None


def _fetch_siblings(story_angle_id: int, exclude_draft_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM drafts WHERE story_angle_id = ? AND id != ?",
            (story_angle_id, exclude_draft_id),
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_latest_review(draft_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM editor_reviews WHERE draft_id = ? ORDER BY review_number DESC LIMIT 1",
            (draft_id,),
        ).fetchone()
    if row is None:
        return None
    r = dict(row)
    try:
        r["issues"] = json.loads(r["issues_json"])
    except (json.JSONDecodeError, TypeError):
        r["issues"] = []
    return r


# ─── User message construction ────────────────────────────────────────────────

def _build_user_message(draft, angle, siblings):
    hashtags_raw = draft.get("hashtags")
    if hashtags_raw is None:
        return "", f"draft_id={draft['id']}: hashtags column is NULL"
    try:
        hashtags = json.loads(hashtags_raw)
    except json.JSONDecodeError as exc:
        return "", f"draft_id={draft['id']}: hashtags not valid JSON: {exc}"
    if not isinstance(hashtags, list):
        return "", f"draft_id={draft['id']}: hashtags parsed to {type(hashtags).__name__}, expected list"

    slides = None
    if draft.get("carousel_slides"):
        try:
            slides = json.loads(draft["carousel_slides"])
        except json.JSONDecodeError:
            slides = draft["carousel_slides"]

    reel_script = None
    if draft.get("reel_script"):
        try:
            reel_script = json.loads(draft["reel_script"])
        except json.JSONDecodeError:
            reel_script = draft["reel_script"]

    draft_block = {
        "id": draft["id"], "platform": draft["platform"], "variant_number": draft["variant_number"],
        "content_format": draft["content_format"], "headline": draft.get("headline"),
        "body": draft["body"], "cta_line": draft.get("cta_line"),
        "cta_strategy": angle["cta_strength"], "hashtags": hashtags,
        "image_brief": draft.get("image_brief"), "slides": slides, "reel_script": reel_script,
    }

    angle_block = {
        "angle_title": angle.get("angle_title") or angle.get("title"),
        "editorial_brief": angle.get("editorial_brief"),
        "cta_strength": angle["cta_strength"],
        "content_format": angle.get("content_format"),
        "platform_fit": angle.get("platform_fit"),
    }

    sibling_blocks = []
    for s in siblings:
        hook = s["body"].split("\n")[0].strip() if s.get("body") else ""
        sibling_blocks.append({
            "variant_number": s["variant_number"], "platform": s["platform"],
            "headline": s.get("headline"), "hook": hook,
        })

    payload = {"draft": draft_block, "source_angle": angle_block, "sibling_variants": sibling_blocks}
    return json.dumps(payload, ensure_ascii=False), None


# ─── JSON parsing ─────────────────────────────────────────────────────────────

def _parse_editor_json(text: str) -> dict[str, Any] | None:
    original   = text.strip()
    candidates: list[str] = []

    fence_match = re.search(r"```(?:json)?\s*\r?\n?([\s\S]*?)\r?\n?```", original)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    stripped = re.sub(r"^```(?:json)?\s*\r?\n?", "", original)
    stripped = re.sub(r"\r?\n?```\s*$", "", stripped).strip()
    if stripped and stripped not in candidates:
        candidates.append(stripped)

    first_brace = original.find("{")
    last_brace  = original.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        brace_extract = original[first_brace : last_brace + 1]
        if brace_extract not in candidates:
            candidates.append(brace_extract)

    for candidate in candidates:
        cleaned = re.sub(r",(\s*[}\]])", r"\1", candidate)
        for attempt in (cleaned, candidate):
            try:
                parsed = json.loads(attempt)
                if isinstance(parsed, dict) and "issues" in parsed:
                    return parsed
            except json.JSONDecodeError:
                continue

    decoder   = json.JSONDecoder()
    all_valid: list[dict] = []
    for m in re.finditer(r'\{[\s\r\n]*"issues"', original):
        try:
            parsed, _ = decoder.raw_decode(original, m.start())
            if isinstance(parsed, dict) and "issues" in parsed:
                all_valid.append(parsed)
        except json.JSONDecodeError:
            pass
    if all_valid:
        return all_valid[-1]

    return None


# ─── Issue validation and verdict ─────────────────────────────────────────────

def _validate_issues(raw_issues):
    if not isinstance(raw_issues, list):
        return [], []

    valid:   list[dict]             = []
    dropped: list[tuple[dict, str]] = []

    for i, issue in enumerate(raw_issues):
        if not isinstance(issue, dict):
            dropped.append(({}, f"Issue {i}: not a dict"))
            continue
        missing = _REQUIRED_ISSUE_KEYS - set(issue.keys())
        if missing:
            dropped.append((issue, f"Issue {i}: missing keys {missing}"))
            continue
        if issue["severity"] not in _VALID_SEVERITIES:
            dropped.append((issue, f"Issue {i}: invalid severity '{issue['severity']}'"))
            continue
        if issue["field"] not in _VALID_FIELDS:
            dropped.append((issue, f"Issue {i}: invalid field '{issue['field']}'"))
            continue
        valid.append({
            "code":     str(issue["code"]),
            "severity": issue["severity"],
            "field":    issue["field"],
            "evidence": str(issue.get("evidence", ""))[:500],
            "message":  str(issue.get("message", ""))[:500],
        })

    return valid, dropped


def _compute_verdict(issues: list[dict]) -> str:
    return "clean" if not issues else "flagged"


# ─── DB persistence ───────────────────────────────────────────────────────────

def _save_review(draft_id, verdict, issues, raw_response, input_tokens, output_tokens, cost):
    with get_connection() as conn:
        max_num = conn.execute(
            "SELECT MAX(review_number) FROM editor_reviews WHERE draft_id = ?", (draft_id,)
        ).fetchone()[0]
        review_number = (max_num or 0) + 1

        cursor = conn.execute(
            """INSERT INTO editor_reviews
               (draft_id, review_number, verdict, issues_json, suggestions_json,
                raw_model_response, model_input_tokens, model_output_tokens, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (draft_id, review_number, verdict, json.dumps(issues), "[]",
             raw_response, input_tokens, output_tokens, cost),
        )
        reviewed_at = conn.execute(
            "SELECT reviewed_at FROM editor_reviews WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()["reviewed_at"]

    return review_number, reviewed_at


# ─── Cost and logging ─────────────────────────────────────────────────────────

def _estimate_cost(input_tokens, output_tokens):
    return round(input_tokens * _INPUT_COST_PER_TOKEN + output_tokens * _OUTPUT_COST_PER_TOKEN, 6)


def _log_api_call(product_id, input_tokens, output_tokens, cost, notes=""):
    ts     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = f"editor run (product_id={product_id})"

    CSV_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not CSV_LOG_PATH.exists()
    with CSV_LOG_PATH.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if write_header:
            writer.writerow(["timestamp", "agent", "topic", "input_tokens", "output_tokens", "web_searches", "est_cost_usd"])
        writer.writerow([ts, "editor", action, input_tokens, output_tokens, 0, cost])

    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO api_log (timestamp, agent, action, input_tokens, output_tokens, web_searches, est_cost_usd, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, "editor", action, input_tokens, output_tokens, 0, cost, notes),
            )
    except sqlite3.OperationalError:
        pass


def _log_failed_response(raw_text: str) -> None:
    ts       = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_path = PROJECT_ROOT / "data" / "editor_failed_responses.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n{'=' * 60}\n{ts}\n{raw_text}\n")


def _error_result(draft_id, cost, error):
    return {
        "draft_id": draft_id, "review_number": 0, "verdict": None,
        "issues": [], "est_cost_usd": cost, "reviewed_at": None, "error": error,
    }


# ─── UI query helpers ─────────────────────────────────────────────────────────

def get_last_run_info(product_id: int) -> dict | None:
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT timestamp, est_cost_usd, notes FROM api_log
                   WHERE agent = 'editor' AND action LIKE ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (f"%product_id={product_id}%",),
            ).fetchone()
    except Exception:
        return None

    if row is None:
        return None

    notes = row["notes"] or ""
    return {
        "timestamp": row["timestamp"], "cost": float(row["est_cost_usd"]),
        "failed": notes.startswith("FAILURE:") or notes.startswith("ERROR:"), "notes": notes,
    }


def count_unreviewed_drafts(product_id: int) -> int:
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM drafts d WHERE d.product_id = ?
                   AND NOT EXISTS (SELECT 1 FROM editor_reviews r WHERE r.draft_id = d.id)""",
                (product_id,),
            ).fetchone()
        return int(row[0])
    except sqlite3.OperationalError:
        return 0


def count_reviews_total(product_id: int) -> int:
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM editor_reviews r
                   JOIN drafts d ON d.id = r.draft_id WHERE d.product_id = ?""",
                (product_id,),
            ).fetchone()
        return int(row[0])
    except sqlite3.OperationalError:
        return 0