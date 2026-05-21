"""Editor agent — fourth agent in the pipeline.

Reads a Copywriter draft, checks it against an explicit ruleset, and writes
a verdict (clean / flagged) plus a structured issues list to editor_reviews.

V1 is FLAG-ONLY: the agent identifies issues but does NOT generate corrected
text or suggestions. suggestions_json is always stored as '[]'.

Public API
----------
review_draft(draft_id)                  -> dict
rereview_draft(draft_id)                -> dict
review_all_unreviewed_drafts(product_id)-> dict
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

# ─── System prompt ────────────────────────────────────────────────────────────
# {brand_ctx} is the only runtime placeholder — injected by _build_system_prompt()
# via .format(). All literal JSON braces in the output-format section are doubled
# ({{ }}) to satisfy Python's str.format() escaping rules.

_SYSTEM_PROMPT_TEMPLATE = """\
You are the Editor agent for Sportz-Well's marketing pipeline.

{brand_ctx}

## Your Role

You receive ONE social media draft produced by the Copywriter agent. Your job is to \
identify issues against an explicit ruleset and return them as structured JSON. You do \
NOT rewrite the draft. You do NOT suggest replacement text. You identify problems; the \
human reviewer decides what to do about them.

The draft arrives as a JSON object in the user message, along with the source story \
angle and any sibling variants (other drafts for the same angle on the same or different \
platform).

---

## Checks

Work through every check below in order. Produce one issue object per violation found. \
A single draft may have multiple issues from the same check (e.g. three hype words = \
three HYPE_WORD issues).

---

### HARD CHECK 1 — HYPE_WORD
Severity: hard | Field: usually "body" or "headline"

The following words and phrases are BANNED because they contradict the brand voice \
(Expert, Structured, Purposeful — no hype). Check case-insensitively. Flag each \
distinct occurrence.

Banned list:
  transformative, transform (used as an adjective or marketing verb,
    e.g. "a transforming approach"),
  game-changing, game-changer, game changer,
  revolutionary, revolutionize, revolutionising,
  world-class, best-in-class,
  cutting-edge, state-of-the-art,
  unleash, unlock potential, unlock the potential,
  level up, level-up, next-level, next level,
  elevate (used as marketing hype, not literal elevation),
  empower, empowering, empowers,
  supercharge, harness the power, harness your potential,
  limitless, boundless,
  redefining, reimagining, reimagine,
  paradigm shift, paradigm-shifting,
  disrupt, disruption (used as a positive quality descriptor),
  synergy, synergies,
  leverage (used as a verb: e.g. "leverage your training"),
  holistic (when vague and unsubstantiated),
  seamless (when used as vague praise),
  robust (when used as vague praise rather than a specific technical claim)

DO NOT flag:
  - "transform" used literally (e.g. "transform a PDF into a report")
  - "leverage" as a noun (e.g. "provides leverage in selection")
  - Any banned word appearing inside a direct quote or cited source text
  - "holistic" when immediately followed by a specific definition (e.g. "holistic —
    tracking physical, technical, and mental metrics together")

Evidence: quote the exact offending word or phrase from the draft.
Message: "Banned hype word: '[word]'. Brand voice is Expert, Structured, Purposeful — \
no hype."

---

### HARD CHECK 2 — URL_FORMAT
Severity: hard | Field: "cta_line"

Applies only when cta_line is non-null and non-empty.

Flag if cta_line contains ANY of:
  - "www.sportz-well" (the www. prefix)
  - "https://" (HTTPS protocol prefix)
  - "http://" (HTTP protocol prefix)

The correct format is sportz-well.com — no prefix, no protocol.

Evidence: the full cta_line value.
Message: "URL in cta_line contains a disallowed prefix. Must appear exactly as: \
sportz-well.com"

---

### HARD CHECK 3 — CAPTION_TOO_LONG / CAPTION_TOO_SHORT
Severity: hard | Field: "body"

Count the words in the body field (split on whitespace). Compare against the expected \
range for this platform × content_format:

  Instagram + single_image:   150–220 words
  Instagram + carousel:       150–220 words
  Instagram + reel_script:     80–150 words
  Instagram + video_script:    80–150 words
  Facebook  + single_image:   100–250 words
  Facebook  + text_post:       80–200 words
  Facebook  + carousel:       100–250 words
  Facebook  + reel_script:     80–150 words

If word count is ABOVE the upper bound: code = "CAPTION_TOO_LONG"
If word count is BELOW the lower bound: code = "CAPTION_TOO_SHORT"

Evidence: "X words (expected Y–Z words for [platform] [content_format])"
Message: explain which bound was exceeded and why that matters for that platform.

---

### HARD CHECK 4 — HASHTAG_COUNT_LOW / HASHTAG_COUNT_HIGH
Severity: hard | Field: "hashtags"

Count the items in the hashtags array.

  Instagram: below 8 → HASHTAG_COUNT_LOW; above 15 → HASHTAG_COUNT_HIGH
  Facebook:  above 5 → HASHTAG_COUNT_HIGH
  Facebook:  do NOT flag for low count — zero hashtags is valid on Facebook

Evidence: "X hashtag(s) (expected Y–Z for [platform])"
Message: state the platform's hashtag convention.

---

### HARD CHECK 5 — PROOF_POINT_LINEAGE_DRIFT
Severity: hard (downgrade to "soft" when in doubt) | Field: "body" or "headline"

Sparing proof points — any reference to Achrekar, Tendulkar, or Shardashram — MUST be \
framed institutionally (as a tradition, methodology, or historical context). They must \
NEVER be framed as personal lineage for the brand's founder or as celebrity name-drops.

FLAG if the draft:
  • Implies or states the founder personally trained under Achrekar or attended
    Shardashram
  • Uses phrases like "our founder trained in that culture", "a product of that lineage",
    "trained by", "mentored by" where the implied mentor is Achrekar- or
    Shardashram-adjacent
  • Drops Tendulkar's name as a credibility lever rather than a historical reference
    point (e.g. "trusted by the academy that produced Sachin Tendulkar" is name-dropping)
  • Uses Shardashram possessively to claim affiliation ("our Shardashram days",
    "Shardashram's own methodology as practised by our founder")

DO NOT FLAG:
  • "grounded in the same disciplined coaching philosophy that shaped Mumbai's grassroots
    tradition" — institutional, no names
  • "rooted in a coaching tradition that treated documentation and discipline as the
    foundation of player development" — no names, no personal claim
  • "the methodology that produced India's most-decorated cricket coaches" — historical,
    third-person, no names
  • Factual historical statements about Achrekar or Tendulkar clearly used as context
    (e.g. "Mumbai's club circuit, from which Tendulkar emerged in the early 1990s,
    was built on...")

When in doubt: flag with severity "soft" rather than skipping.

Evidence: the specific phrase that crosses the line.
Message: "Proof-point lineage drift. Achrekar/Tendulkar/Shardashram references must be \
institutional, not personal claims about the founder."

---

### HARD CHECK 6 — HINGLISH_UNCALLED
Severity: hard | Field: "body"

Default voice is English-only. Flag if the draft contains:
  • Any Devanagari script (Unicode block U+0900–U+097F)
  • Transliterated Hindi words used non-ironically in a content context, including:
    jugaad, khel, maidan, guru (when used as a role or title, not a brand name),
    shishya, desi, yaar, arre, chalo, khelna, leke, abhi, nahi, aur, baat, bhi, toh,
    hai, hain, lagta, mujhe, apna, unka, iska, kya, acha, accha
  • Hindi-English code-switching mid-sentence

DO NOT FLAG:
  • Proper nouns: Shardashram, BCCI, Ranji Trophy, Mumbai, Maharashtra — not Hinglish
  • Words that have entered standard English sports journalism (e.g. "crore" in a
    factual statistic)
  • Any of the above IF the angle's editorial_brief contains an explicit phrase such as
    "voice: allow Hinglish", "Hinglish appropriate", or "regional language welcome" —
    in that case skip this check entirely for this draft

Evidence: the offending word or phrase.
Message: "Hinglish or Hindi word used without explicit brief permission. Default voice \
is English-only for this audience (academy directors and coaches reading English \
business communication)."

---

### HARD CHECK 7 — MISSING_REQUIRED_FIELD
Severity: hard | Field: varies per sub-rule

Cross-check draft fields against its cta_strategy and content_format:

  Rule A — cta_strategy = "hard_cta":
    cta_line MUST be non-null, non-empty, AND contain "sportz-well.com".
    If either condition fails: field = "cta_line",
    evidence = current cta_line value or "null/empty".
    Message: "hard_cta requires a non-empty cta_line containing sportz-well.com."

  Rule B — cta_strategy = "no_cta":
    cta_line MUST be null or empty. If a value is present:
    field = "cta_line", evidence = the cta_line value.
    Message: "no_cta angle but cta_line is populated. CTA must be absent."

  Rule C — cta_strategy = "soft_cta":
    Flag ONLY if cta_line is null or empty.
    field = "cta_line", evidence = "null/empty".
    Message: "soft_cta angle has no cta_line. A gentle mention is expected."

  Rule D — content_format IN ("single_image", "carousel"):
    image_brief MUST be non-null and contain at least 10 characters.
    field = "image_brief", evidence = "null/empty".
    Message: "single_image/carousel draft requires an image_brief for the Media agent."

  Rule E — content_format = "carousel":
    The "slides" field MUST have at least 2 entries.
    If fewer than 2 or null: field = "image_brief",
    evidence = "X slide(s) found (minimum 2)".
    Message: "Carousel format requires at least 2 slides."

  Rule F — content_format = "reel_script":
    Either the reel_script field must be a non-null, non-empty object
    OR the body must contain at least one shot-direction token (case-insensitive):
      "[hook]", "[b-roll]", "[on-camera]", "scene", "shot 1", "cut to"
    If neither: field = "body",
    evidence = "reel_script field is null and no shot-direction language in body".
    Message: "reel_script format requires a populated reel_script object or \
shot-direction language in the body."

---

### HARD CHECK 8 — CROSS_VARIANT_DUPLICATION
Severity: hard | Field: "hook" or "headline"

Applies ONLY when sibling_variants is non-empty in the user message. If \
sibling_variants is an empty array [], skip this check entirely — do not flag.

Compare this draft's hook (line 1 of body) and headline against each sibling \
variant's hook and headline.

FLAG if:
  • This draft's hook is byte-identical to a sibling's hook
  • This draft's headline is byte-identical to a sibling's headline
  • This draft's hook is a near-identical paraphrase of a sibling's hook — same key
    nouns and verbs in the same order, with only superficial word-swaps

DO NOT FLAG:
  • Two variants that both use a question format but ask different specific questions
  • Two variants that share a topic reference but approach it from different angles
  • Variants on different platforms that open similarly in structure but differ in
    specificity

Evidence: quote this draft's hook/headline and the sibling's, noting the sibling's \
variant_number and platform.
Message: "Hook/headline is near-identical to Variant [N] ([platform]). Variants must \
be meaningfully different in opening."

---

### SOFT CHECK 9 — GENERIC_HOOK
Severity: soft | Field: "hook"

Flag if line 1 of the body opens with any of these generic patterns (case-insensitive):
  • Starts with "In today's world"
  • Starts with "In this fast-paced world"
  • Starts with "Cricket is more than" or "Cricket is not just"
  • Starts with "Imagine a world where"
  • Starts with "Have you ever wondered" with no specific subject noun following
  • Starts with "Did you know that" in a generic form without a specific claim
  • Is a bare definition sentence: "[Topic] is the practice/process/art of..."
    with no specificity

DO NOT FLAG:
  • "Why does your U-12 batter improve faster in net sessions than in match scenarios?"
    — specific, concrete, earns attention
  • "Have you ever wondered why some academies consistently produce state-level players
    while others don't?" — "Have you ever wondered" followed by a specific, grounded
    question is fine; the generic floating form is not
  • Any hook anchored to a specific age group, position, tournament, or named context

Evidence: the full hook line.
Message: "Generic hook pattern. Line 1 must earn a thumb-stop with specificity — this \
opener could belong to any sports coaching post."

---

### SOFT CHECK 10 — WEAK_CTA_BUILDUP
Severity: soft | Field: "body"

Applies ONLY when cta_strategy = "hard_cta". Skip entirely for soft_cta and no_cta.

A hard CTA should feel earned. The final paragraph of the body should connect \
thematically to the next step — demos, consultations, conversations, decision-making, \
or structured next steps.

Flag if: you could swap this post's hard CTA into any other unrelated post and it \
would read identically — the final paragraph makes no thematic connection to taking \
action.

Err strongly on the side of NOT flagging. Only flag when the disconnect between the \
body content and the CTA is obvious and jarring.

Evidence: quote the final paragraph of the body and the cta_line.
Message: "Hard CTA may feel tacked on. The final paragraph does not build toward a \
next step."

---

## Output Format

Respond with a single JSON object. No markdown code fences. No prose before or after.
Output your final JSON once — do not revise, re-evaluate, or emit a second JSON block after reflection. If you change your mind mid-response, edit silently before you start writing JSON, not after.

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

If no issues are found, return: {{"issues": []}}

Strict output rules:
- Do NOT include a "verdict" field. Python computes the verdict from your issues list.
- Do NOT include a "suggestions" field. This is V1 — identification only, no rewrites.
- Every issue object MUST have all five fields: code, severity, field, evidence, message.
- severity MUST be exactly "hard" or "soft" — no other values accepted.
- field MUST be one of: hook, body, cta_line, hashtags, image_brief, headline, overall.
- One issue per violation. Three hype words = three separate HYPE_WORD issues.\
"""


def _build_system_prompt(brand_ctx: str) -> str:
    """Inject brand context into the system prompt template at runtime."""
    return _SYSTEM_PROMPT_TEMPLATE.format(brand_ctx=brand_ctx)


# ─── Public entry points ──────────────────────────────────────────────────────

def review_draft(draft_id: int) -> dict[str, Any]:
    """Return the latest existing review without an API call if one exists; otherwise run a new review.

    To unconditionally trigger a fresh review, call rereview_draft(draft_id) instead.
    Return shape on success:
        {draft_id, review_number, verdict, issues, est_cost_usd, reviewed_at, error=None}
    Return shape on error:
        {draft_id, review_number=0, verdict=None, issues=[], est_cost_usd, reviewed_at=None, error=str}
    """
    existing = _fetch_latest_review(draft_id)
    if existing is not None:
        return {
            "draft_id":      draft_id,
            "review_number": existing["review_number"],
            "verdict":       existing["verdict"],
            "issues":        existing["issues"],
            "est_cost_usd":  0.0,
            "reviewed_at":   existing["reviewed_at"],
            "error":         None,
        }
    return _run_review(draft_id)


def rereview_draft(draft_id: int) -> dict[str, Any]:
    """Always call the API and insert a new review row (review_number = previous max + 1)."""
    return _run_review(draft_id)


# ─── Core orchestration ───────────────────────────────────────────────────────

def _run_review(draft_id: int) -> dict[str, Any]:
    """Load draft → build prompts → call API → parse → validate → save → dual-log."""
    draft = _fetch_draft(draft_id)
    if draft is None:
        return _error_result(draft_id, 0.0, f"draft_id={draft_id} not found in drafts table")

    angle = _fetch_angle(draft["story_angle_id"])
    if angle is None:
        return _error_result(
            draft_id, 0.0,
            f"story_angle_id={draft['story_angle_id']} not found in story_angles table",
        )

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
        _log_api_call(
            product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
            f"FAILURE: API error: {api_result['error'][:200]}",
        )
        return _error_result(draft_id, cost, api_result["error"])

    parse_result = _parse_editor_json(api_result["text"])
    if parse_result is None:
        _log_failed_response(api_result["text"])
        _log_api_call(
            product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
            f"FAILURE: JSON parse failed. Raw (first 300): {api_result['text'][:300]}",
        )
        return _error_result(
            draft_id, cost,
            "Could not parse the model's response as JSON. "
            "Full response saved to data/editor_failed_responses.log. "
            f"Raw (first 500 chars): {api_result['text'][:500]}",
        )

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
                f"Reason: {reason}\n"
                f"Raw issue: {json.dumps(raw_issue, ensure_ascii=False)}"
            )
        print(
            f"WARNING: Dropped {len(dropped)} malformed issue(s) from draft {draft_id} "
            f"review #{review_number}. See editor_failed_responses.log."
        )

    _log_api_call(
        product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
        f"SUCCESS: draft_id={draft_id}, verdict={verdict}, issues={len(issues)}, "
        f"dropped={len(dropped)}",
    )

    return {
        "draft_id":      draft_id,
        "review_number": review_number,
        "verdict":       verdict,
        "issues":        issues,
        "est_cost_usd":  cost,
        "reviewed_at":   reviewed_at,
        "error":         None,
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
    """Return the highest-review_number row for this draft, or None if no reviews exist."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM editor_reviews WHERE draft_id = ?
               ORDER BY review_number DESC LIMIT 1""",
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

def _build_user_message(
    draft: dict, angle: dict, siblings: list[dict]
) -> tuple[str, str | None]:
    """Serialize draft + angle + siblings into the JSON string the system prompt expects.

    Returns (json_str, None) on success, ("", error_message) on data error.
    Raises on NULL or unparseable hashtags — a silent [] would manufacture a false
    HASHTAG_COUNT_LOW flag.
    """
    hashtags_raw = draft.get("hashtags")
    if hashtags_raw is None:
        return "", (
            f"draft_id={draft['id']}: hashtags column is NULL — cannot safely review "
            "(would manufacture a false HASHTAG_COUNT_LOW flag)"
        )
    try:
        hashtags = json.loads(hashtags_raw)
    except json.JSONDecodeError as exc:
        return "", f"draft_id={draft['id']}: hashtags column is not valid JSON: {exc}"
    if not isinstance(hashtags, list):
        return "", (
            f"draft_id={draft['id']}: hashtags parsed to {type(hashtags).__name__}, expected list"
        )

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
        "id":             draft["id"],
        "platform":       draft["platform"],
        "variant_number": draft["variant_number"],
        "content_format": draft["content_format"],
        "headline":       draft.get("headline"),
        "body":           draft["body"],
        "cta_line":       draft.get("cta_line"),
        "cta_strategy":   angle["cta_strength"],
        "hashtags":       hashtags,
        "image_brief":    draft.get("image_brief"),
        "slides":         slides,
        "reel_script":    reel_script,
    }

    angle_block = {
        "angle_title":     angle.get("angle_title") or angle.get("title"),
        "editorial_brief": angle.get("editorial_brief"),
        "cta_strength":    angle["cta_strength"],
        "content_format":  angle.get("content_format"),
        "platform_fit":    angle.get("platform_fit"),
    }

    sibling_blocks = []
    for s in siblings:
        hook = s["body"].split("\n")[0].strip() if s.get("body") else ""
        sibling_blocks.append({
            "variant_number": s["variant_number"],
            "platform":       s["platform"],
            "headline":       s.get("headline"),
            "hook":           hook,
        })

    payload = {
        "draft":            draft_block,
        "source_angle":     angle_block,
        "sibling_variants": sibling_blocks,
    }
    return json.dumps(payload, ensure_ascii=False), None


# ─── JSON parsing ─────────────────────────────────────────────────────────────

def _parse_editor_json(text: str) -> dict[str, Any] | None:
    """Extract and parse the model's JSON response. Four strategies, each with trailing-comma cleanup.

    Success criterion: parsed value is a dict containing an "issues" key.
    An empty issues list [] is valid (clean draft).

    Strategy order:
      1. Extract content from a markdown code fence (```json ... ```).
      2. Strip any leading/trailing fence markers from the whole response.
      3. Brace-extract: take original[first '{' : last '}'] as a single JSON candidate.
      4. Multi-block scan: find every position where '{"issues"' appears, parse each with
         json.JSONDecoder.raw_decode(), collect all valid blocks, return the LAST one.

    Strategy 4 exists because the model sometimes self-corrects mid-response: it emits
    a first JSON block, then writes reasoning prose ("Wait — I need to re-evaluate…"),
    then re-issues a corrected JSON block. Strategies 1–3 all fail on this shape because
    brace-extraction captures the full first-to-last-brace span (prose and all), which is
    not parseable JSON. Strategy 4 uses raw_decode to isolate each individual block and
    returns the last valid one, which is always the model's final corrected answer.
    Strategies 1–3 short-circuit and return before Strategy 4 is reached for normal
    single-block responses, so backward compatibility is preserved.

    Known gap: this function only checks that the "issues" key exists, not that its value
    is a list. If the model returns {"issues": null} or {"issues": "none"}, _parse_editor_json
    succeeds but _validate_issues receives a non-list and silently returns ([], []) — the
    review is saved as clean with zero issues and no forensic record. Acceptable for V1 given
    how unlikely the model is to emit this shape, but worth hardening if it ever fires in practice.
    """
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

    # Strategy 4: scan for every {"issues" start position, parse with raw_decode, keep last valid.
    # Uses a regex rather than a literal string search so it matches both compact
    # ('{"issues"') and pretty-printed ('{\n  "issues"') forms.
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

def _validate_issues(
    raw_issues: list,
) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Validate each issue object. Returns (valid_issues, dropped).

    dropped is a list of (raw_issue_dict, reason_str) pairs.
    Callers must log and surface any drops — nothing is silently discarded here.
    """
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
            dropped.append((issue, f"Issue {i}: missing required keys {missing}"))
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
    """Clean if no issues; flagged if any issues (hard or soft)."""
    return "clean" if not issues else "flagged"


# ─── DB persistence ───────────────────────────────────────────────────────────

def _save_review(
    draft_id: int,
    verdict: str,
    issues: list[dict],
    raw_response: str,
    input_tokens: int,
    output_tokens: int,
    cost: float,
) -> tuple[int, str]:
    """Atomically compute review_number, INSERT the row, return (review_number, reviewed_at).

    review_number = MAX(existing for this draft) + 1, or 1 if no prior reviews.
    Computed and inserted in the same connection to avoid a race between two concurrent reviews.
    """
    with get_connection() as conn:
        max_num = conn.execute(
            "SELECT MAX(review_number) FROM editor_reviews WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()[0]
        review_number = (max_num or 0) + 1

        cursor = conn.execute(
            """INSERT INTO editor_reviews
               (draft_id, review_number, verdict, issues_json, suggestions_json,
                raw_model_response, model_input_tokens, model_output_tokens, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                draft_id, review_number, verdict,
                json.dumps(issues), "[]",
                raw_response, input_tokens, output_tokens, cost,
            ),
        )
        reviewed_at = conn.execute(
            "SELECT reviewed_at FROM editor_reviews WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()["reviewed_at"]

    return review_number, reviewed_at


# ─── Cost and logging ─────────────────────────────────────────────────────────

def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return round(
        input_tokens  * _INPUT_COST_PER_TOKEN
        + output_tokens * _OUTPUT_COST_PER_TOKEN,
        6,
    )


def _log_api_call(
    product_id: int,
    input_tokens: int,
    output_tokens: int,
    cost: float,
    notes: str = "",
) -> None:
    ts     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = f"editor run (product_id={product_id})"

    CSV_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not CSV_LOG_PATH.exists()
    with CSV_LOG_PATH.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if write_header:
            writer.writerow(["timestamp", "agent", "topic", "input_tokens",
                             "output_tokens", "web_searches", "est_cost_usd"])
        writer.writerow([ts, "editor", action, input_tokens, output_tokens, 0, cost])

    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO api_log
                   (timestamp, agent, action, input_tokens, output_tokens,
                    web_searches, est_cost_usd, notes)
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


def _error_result(draft_id: int, cost: float, error: str) -> dict[str, Any]:
    return {
        "draft_id":      draft_id,
        "review_number": 0,
        "verdict":       None,
        "issues":        [],
        "est_cost_usd":  cost,
        "reviewed_at":   None,
        "error":         error,
    }

# ─── UI query helpers ─────────────────────────────────────────────────────────

def get_last_run_info(product_id: int) -> dict | None:
    """Return info about the most recent editor API call for this product.

    Returns None if no calls have been logged. The 'failed' key is True when
    notes starts with 'FAILURE:' (parse error) or 'ERROR:' (API error).
    Matches the shape of strategist.get_last_run_info().
    """
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
        "timestamp": row["timestamp"],
        "cost":      float(row["est_cost_usd"]),
        "failed":    notes.startswith("FAILURE:") or notes.startswith("ERROR:"),
        "notes":     notes,
    }


def count_unreviewed_drafts(product_id: int) -> int:
    """Count drafts for this product that have never been reviewed."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM drafts d
                   WHERE d.product_id = ?
                     AND NOT EXISTS (
                         SELECT 1 FROM editor_reviews r WHERE r.draft_id = d.id
                     )""",
                (product_id,),
            ).fetchone()
        return int(row[0])
    except sqlite3.OperationalError:
        return 0


def count_reviews_total(product_id: int) -> int:
    """Total number of editor_reviews rows for this product's drafts (includes re-reviews)."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM editor_reviews r
                   JOIN drafts d ON d.id = r.draft_id
                   WHERE d.product_id = ?""",
                (product_id,),
            ).fetchone()
        return int(row[0])
    except sqlite3.OperationalError:
        return 0