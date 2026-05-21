"""Copywriter agent — third agent in the pipeline.

Reads an approved story angle from story_angles, calls the Anthropic API
(pure reasoning, no web search), and saves 2 platform-appropriate draft
variants per target platform to the drafts table.

Public API
----------
write_drafts_for_angle(angle_id, regenerate=False) -> dict
write_drafts_for_all_approved(product_id) -> dict
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

_VALID_PLATFORMS   = {"instagram", "facebook"}
_VALID_CTA         = {"hard_cta", "soft_cta", "no_cta"}
_VALID_CONTENT_FMT = {"single_image", "carousel", "text_post", "reel_script", "video_script"}

# Allowed differentiation strategies. The model must pick one per draft.
# Used at validation time to catch sibling variants that claim to differ but don't.
_VALID_DIFFERENTIATION_STRATEGIES = {
    "question_hook",       # Opens with a pointed specific question
    "scenario_hook",       # Opens with a concrete situation or moment
    "statement_hook",      # Opens with a direct declarative claim or observation
    "story_hook",          # Opens with a brief anecdote or mini-narrative
    "framework_hook",      # Opens by naming a structure or numbered approach
    "coach_pov",           # Foregrounds the coach's perspective and decisions
    "parent_pov",          # Foregrounds the parent's perspective and concerns
    "player_pov",          # Foregrounds the player's perspective and experience
    "academy_pov",         # Foregrounds the academy operator's institutional view
}


# ─── Public entry points ──────────────────────────────────────────────────────

def write_drafts_for_angle(angle_id: int, regenerate: bool = False) -> dict[str, Any]:
    """Produce 2 draft variants per target platform for a single approved angle.

    Returns:
        {
            "angle_id":       int,
            "angle_title":    str,
            "platforms":      list[str],
            "drafts_created": int,
            "est_cost_usd":   float,
            "drafts":         list[dict],
            "warnings":       list[str],
            "error":          str | None,
        }
    """
    angle = _fetch_angle(angle_id)
    if angle is None:
        return _error_result(angle_id, "", [], 0.0, "Angle not found.")

    angle_title = angle.get("angle_title") or angle.get("title") or "Untitled"
    status      = angle.get("status", "")

    if status not in ("approved", "edited"):
        return _error_result(
            angle_id, angle_title, [], 0.0,
            f"Angle must be approved or edited before drafting (current status: {status}).",
        )

    platform_fit = angle.get("platform_fit", "both")
    if platform_fit == "instagram":
        platforms = ["instagram"]
    elif platform_fit == "facebook":
        platforms = ["facebook"]
    else:
        platforms = ["instagram", "facebook"]

    if not regenerate:
        existing = _fetch_existing_drafts(angle_id)
        if existing:
            return {
                "angle_id":       angle_id,
                "angle_title":    angle_title,
                "platforms":      platforms,
                "drafts_created": 0,
                "est_cost_usd":   0.0,
                "drafts":         existing,
                "warnings":       [
                    "Drafts already exist for this angle. "
                    "Tick 'Regenerate' to overwrite."
                ],
                "error": None,
            }

    if regenerate:
        _delete_drafts_for_angle(angle_id)

    product_id     = angle["product_id"]
    cta_strength   = angle.get("cta_strength", "no_cta")
    content_format = angle.get("content_format", "single_image")

    brand_ctx     = build_brand_context_prompt(product_id)
    system_prompt = _build_system_prompt(brand_ctx, cta_strength, content_format, platforms)
    user_prompt   = _build_user_prompt(angle, platforms)

    api_result = ask_with_usage(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=DEFAULT_MODEL,
        max_tokens=8192,
    )

    cost = _estimate_cost(api_result["input_tokens"], api_result["output_tokens"])

    if api_result["error"]:
        _log_api_call(
            product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
            f"FAILURE: API error: {api_result['error'][:200]}",
        )
        return _error_result(angle_id, angle_title, platforms, cost, api_result["error"])

    parse_result = _parse_copywriter_json(api_result["text"])
    if parse_result is None:
        _log_failed_response(api_result["text"])
        _log_api_call(
            product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
            f"FAILURE: JSON parse failed. Raw (first 300): {api_result['text'][:300]}",
        )
        return _error_result(
            angle_id, angle_title, platforms, cost,
            "Could not parse the model's response as JSON. "
            "The full response has been saved to data/copywriter_failed_responses.log. "
            f"Raw response (first 500 chars): {api_result['text'][:500]}",
        )

    raw_drafts     = parse_result.get("drafts", [])
    model_warnings = list(parse_result.get("warnings", []))

    validated, validation_warnings = _validate_drafts(
        raw_drafts, platforms, cta_strength, content_format
    )
    all_warnings = model_warnings + validation_warnings

    saved = _save_drafts(validated, angle_id, product_id)

    _log_api_call(
        product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
        f"SUCCESS: angle={angle_id}, platforms={platforms}, saved={saved}, "
        f"warnings={len(all_warnings)}",
    )

    return {
        "angle_id":       angle_id,
        "angle_title":    angle_title,
        "platforms":      platforms,
        "drafts_created": saved,
        "est_cost_usd":   cost,
        "drafts":         validated,
        "warnings":       all_warnings,
        "error":          None,
    }


def write_drafts_for_all_approved(product_id: int) -> dict[str, Any]:
    """Run the Copywriter on every approved/edited angle without existing drafts.

    Returns aggregated stats: angles_processed, drafts_created, total_cost_usd, errors.
    """
    angles = _fetch_undrafted_approved_angles(product_id)
    if not angles:
        return {
            "angles_processed": 0,
            "drafts_created":   0,
            "total_cost_usd":   0.0,
            "errors":           [],
            "warnings":         ["No approved angles without existing drafts found."],
        }

    total_drafts = 0
    total_cost   = 0.0
    errors: list[str] = []
    all_warnings: list[str] = []

    for angle in angles:
        result = write_drafts_for_angle(angle["id"], regenerate=False)
        total_cost   += result.get("est_cost_usd", 0.0)
        total_drafts += result.get("drafts_created", 0)
        if result.get("error"):
            errors.append(
                f"Angle {angle['id']} "
                f"({angle.get('angle_title') or angle.get('title', '?')}): "
                f"{result['error']}"
            )
        all_warnings.extend(result.get("warnings", []))

    return {
        "angles_processed": len(angles),
        "drafts_created":   total_drafts,
        "total_cost_usd":   round(total_cost, 6),
        "errors":           errors,
        "warnings":         all_warnings,
    }


# ─── Data fetching ────────────────────────────────────────────────────────────

def _fetch_angle(angle_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, product_id, angle_title, title, angle_description, angle,
                   editorial_brief, platform_fit, cta_strength, content_format,
                   proof_points_used, status
            FROM story_angles WHERE id = ?
            """,
            (angle_id,),
        ).fetchone()
    return dict(row) if row else None


def _fetch_existing_drafts(angle_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM drafts WHERE story_angle_id = ? ORDER BY platform, variant_number",
            (angle_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_undrafted_approved_angles(product_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT sa.id, sa.angle_title, sa.title
            FROM story_angles sa
            WHERE sa.product_id = ?
              AND sa.status IN ('approved', 'edited')
              AND NOT EXISTS (
                  SELECT 1 FROM drafts d WHERE d.story_angle_id = sa.id
              )
            ORDER BY sa.id
            """,
            (product_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _delete_drafts_for_angle(angle_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM drafts WHERE story_angle_id = ?", (angle_id,))


# ─── Prompt construction ──────────────────────────────────────────────────────

def _build_system_prompt(
    brand_ctx: str,
    cta_strength: str,
    content_format: str,
    platforms: list[str],
) -> str:
    platform_list = " and ".join(p.capitalize() for p in platforms)
    total_drafts  = 2 * len(platforms)
    return f"""You are the Copywriter agent for a social media content pipeline.

{brand_ctx}

## Your Role

Given a single approved story angle and its editorial brief, you produce 2 distinct draft variants per target platform ({platform_list}). You do NOT do research or set strategy — that work is already done. Your job is to translate the angle into ready-to-post copy.

## Platform Conventions — HARD RULES

### INSTAGRAM
- Caption length: 150–220 words for single_image and carousel; 80–150 words for reel_script
- Hook in line 1 — must earn a thumb-stop on the feed. Banned openers (too generic): 'In today's world...', 'Did you know...', 'Imagine if...', 'Let's talk about...', 'Have you ever wondered...'. Specific questions or scenarios are allowed and encouraged (e.g. 'Why does your U-12 batter improve faster in net sessions than in match scenarios?' is fine — it's specific. 'Did you know cricket coaching is important?' is not — it's generic).
- Blank line between every paragraph — Instagram strips single newlines; the formatting must be explicit in the JSON body field as \\n\\n
- Hashtags: 8–15 tags, mix of broad (#cricketcoaching) and niche (#mumbaicricketacademies). Place after main body, separated by a blank line
- Hashtag quality rule: hashtags must be relevant to the post's actual topic, not generic. Allowed examples: #cricketcoaching, #mumbaicricketacademies, #grassrootscricket, #u12cricket, #cricketdevelopment. Banned: #motivation, #inspiration, #mondaymotivation, #fitfam, #sportsfan, #hustle. If unsure, fewer is better — never pad to hit the count.
- For carousel: produce 5–8 slides. Each slide has slide_number, slide_title, and slide_body (strict max 30 words per slide_body)

### FACEBOOK
- Caption length: 80–180 words. Facebook rewards shorter, punchier posts
- Hook in line 1 — same quality standard as Instagram. Banned generic openers: 'In today's world...', 'Did you know...', 'Imagine if...', 'Let's talk about...'. Specific questions or concrete scenarios are fine and encouraged.
- Structure: hook → value → (optional) CTA
- Hashtags: 2–5 only. Facebook penalises hashtag stuffing
- Hashtag quality rule: same standard as Instagram — topic-specific only, no generic tags
- For text_post format: pure text, no image prompt needed, may run up to 250 words if the substance warrants it
- For carousel: same 5–8 slide structure as Instagram

## CTA Rules — critical. The angle's cta_strength is "{cta_strength}". Match it exactly in every draft.

- **no_cta**: No demo link, no "book a call", nothing transactional. The post earns trust on its own merit. The cta_line field MUST be null. Do not end with any product pitch, question about interest, or implicit invitation.
- **soft_cta**: One gentle mention only. Examples: "If you're thinking about structured reporting in your academy, SWPI was built for exactly this." OR "Learn more at sportz-well.com if this resonates." No urgency, no "limited time", no "book a demo today".
- **hard_cta**: One direct invitation. Examples: "Book a demo at sportz-well.com." or "Reply to this post to schedule a 20-minute walkthrough." Always include the URL sportz-well.com.

  URL FORMATTING — CRITICAL:
  - The URL MUST appear in any CTA EXACTLY as: sportz-well.com
  - Do NOT add "www." in front. Do NOT add "https://" in front. Do NOT use any other variant.
  - CORRECT: "Book a demo at sportz-well.com."
  - CORRECT: "Reply to schedule a walkthrough, or visit sportz-well.com."
  - WRONG: "Book a demo at www.sportz-well.com."
  - WRONG: "Visit https://sportz-well.com to learn more."
  - WRONG: "https://www.sportz-well.com"

## Proof Point Rules

- Use ONLY proof points explicitly listed in the angle's proof_points_used array. Never invent proof points.
- If the angle's proof_points_used array is empty, do not reference any credentials or historical associations.
- Proof points marked "Use sparingly" — any line referencing Achrekar, Tendulkar, or the Shardashram founding philosophy — must be framed institutionally, never as name-dropping:
  - CORRECT: "grounded in the same disciplined coaching philosophy that shaped Mumbai's grassroots tradition"
  - CORRECT: "built on a culture of structured, long-view development"
  - CORRECT: "rooted in a coaching tradition that treated documentation and discipline as the foundation of player development"
  - WRONG: "inspired by the coach of Sachin Tendulkar"
  - WRONG: "from the academy that produced Sachin Tendulkar"

## Voice Rules

- Brand voice: Expert, Structured, Purposeful
- Use specific nouns over vague generalisations:
  - "U-12 batter" not "young player"
  - "video analysis session" not "training tool"
  - "coach–parent progress report" not "communication"
  - "Mumbai Under-16 selection trial" not "important event"
- Banned words (hype mode): amazing, incredible, game-changing, revolutionary, transformative, powerful (as hype), world-class (as filler)
- No celebrity drama, no national team politics, no supplement advice, no generic Western fitness content
- India-specific framing where the angle calls for it — tournament structures, board acronyms, city academy contexts are all on-brand
- Language: default to English. Do not use Hindi words, Hinglish, or transliterated cricket slang (e.g. "gully cricket", "maidan") unless the editorial brief explicitly calls for it. SWPI's audience is academy directors and coaches who read English business communication.

## Variant Differentiation — MANDATORY, ENFORCED IN CODE

This is the most-violated rule in the pipeline. The Editor agent has been catching duplicated variants at a rate of 46%. Read this section twice before producing JSON.

### The hard rule

For each platform you target, you produce 2 variants. The two variants MUST be different in BOTH of the following dimensions simultaneously:

1. **Hook structure** — the opening sentence (line 1 of body) MUST use a different rhetorical mode in V1 vs V2. Pick TWO different modes from this list, one per variant:
   - `question_hook` — pointed specific question
   - `scenario_hook` — concrete moment, situation, or vignette
   - `statement_hook` — direct declarative claim or observation
   - `story_hook` — brief anecdote or mini-narrative (1–2 sentences)
   - `framework_hook` — names a structure or numbered approach

2. **Perspective focus** — V1 and V2 MUST foreground a different stakeholder's viewpoint. Pick TWO different POVs from this list, one per variant:
   - `coach_pov` — what the coach sees, decides, struggles with
   - `parent_pov` — what the parent worries about, looks for, asks
   - `player_pov` — what the player experiences, feels, notices
   - `academy_pov` — what the academy operator manages, measures, scales

### Concrete checks before you submit

Before writing each draft, complete this sentence in your head:
"V1's hook is a [HOOK_MODE] from the [POV] perspective. V2 must use a different hook mode AND a different perspective."

If V1 starts "Why does your U-12 batter improve faster in nets than in matches?" (`question_hook`, `coach_pov`), then V2 CANNOT start with a question, AND CANNOT be from the coach's perspective. A valid V2 might open: "Last Tuesday's Under-14 selection trial in Dadar produced 47 batters but only 3 wicket-keepers." (`statement_hook`, `academy_pov`).

### Forbidden — these patterns count as duplication

- Same opening noun in V1 and V2 (e.g., both starting with "Your U-12 batter…")
- Same opening verb (e.g., both starting with "Imagine…" or both starting with "Watch…")
- Same rhetorical mode even with different words (two questions, two scenarios, etc.)
- Same perspective even with different content (both coach-centric, both parent-centric)
- Paraphrases of the same insight in different sentence orders

### Cross-platform also applies

If platform_fit is "both", you produce 4 drafts: IG V1, IG V2, FB V1, FB V2. The hook differentiation rule applies across ALL FOUR — not just within a single platform. IG V1's hook mode cannot equal FB V1's hook mode. Pick 4 different combinations from the hook × perspective grid.

### Declare your strategy

For each draft, you MUST include two fields in the JSON output:
- `hook_strategy`: one of the hook modes listed above
- `perspective_focus`: one of the POVs listed above

These declarations are validated in code. If two sibling variants share the same hook_strategy OR the same perspective_focus, the system raises a warning that gets logged and surfaced in the UI.

Both variants must remain faithful to the angle's editorial_brief — same core insight, different execution.

## Output Format

Return ONLY the JSON object below. No markdown fences. No prose before or after the JSON.

{{
  "drafts": [
    {{
      "platform": "instagram" or "facebook",
      "variant_number": 1 or 2,
      "content_format": "<mirror the angle's content_format exactly: single_image | carousel | text_post | reel_script | video_script>",
      "hook_strategy": "<one of: question_hook | scenario_hook | statement_hook | story_hook | framework_hook>",
      "perspective_focus": "<one of: coach_pov | parent_pov | player_pov | academy_pov>",
      "headline": "the opening hook line — first sentence of the post body",
      "body": "the full caption body, with \\n\\n between paragraphs",
      "cta_line": "the explicit CTA line, or null if cta_strength is no_cta",
      "hashtags": ["#tag1", "#tag2"],
      "carousel_slides": [
        {{"slide_number": 1, "slide_title": "...", "slide_body": "max 30 words"}}
      ],
      "reel_script": {{
        "hook_seconds_0_3": "...",
        "beats": ["beat 1", "beat 2"],
        "voiceover": "full VO script",
        "on_screen_text": ["text overlay 1", "text overlay 2"]
      }},
      "image_brief": "1-2 sentences describing the visual the Media agent should produce",
      "proof_points_used": ["exact proof point strings used in this draft, subset of the angle's list"],
      "word_count": <integer — count words in body>,
      "char_count": <integer — count characters in body>
    }}
  ],
  "warnings": ["list any deviations or issues; empty array if none"]
}}

IMPORTANT:
- Set carousel_slides to null when content_format is not "carousel"
- Set reel_script to null when content_format is not "reel_script"
- Total drafts in the array must equal exactly {total_drafts} ({2} variants × {len(platforms)} platform(s): {", ".join(platforms)})
- hook_strategy and perspective_focus are REQUIRED on every draft. Validation will fail otherwise."""


def _build_user_prompt(angle: dict, platforms: list[str]) -> str:
    angle_title  = angle.get("angle_title") or angle.get("title") or "Untitled"
    angle_desc   = angle.get("angle_description") or angle.get("angle") or ""
    editorial    = (angle.get("editorial_brief") or "").strip()
    cta_strength = angle.get("cta_strength", "no_cta")
    content_fmt  = angle.get("content_format", "single_image")

    raw_pps = angle.get("proof_points_used") or "[]"
    if isinstance(raw_pps, str):
        try:
            proof_points = json.loads(raw_pps)
        except (json.JSONDecodeError, ValueError):
            proof_points = []
    else:
        proof_points = raw_pps if isinstance(raw_pps, list) else []

    pp_block = (
        "\n".join(f"  - {pp}" for pp in proof_points)
        if proof_points
        else "  (none — do not invent proof points)"
    )

    total_drafts = 2 * len(platforms)
    return f"""Write drafts for the following approved story angle.

**Angle Title:** {angle_title}
**Angle Description:** {angle_desc}

**Editorial Brief:**
{editorial if editorial else "(no brief provided)"}

**Target Platform(s):** {", ".join(platforms)}
**Content Format:** {content_fmt}
**CTA Strength:** {cta_strength}

**Proof Points Approved for This Angle:**
{pp_block}

Produce exactly {total_drafts} drafts ({2} variants per platform). Follow all platform conventions, CTA rules, proof-point rules, and — critically — the variant differentiation rules from the system prompt.

Reminder: for every draft you MUST declare a hook_strategy and perspective_focus. Sibling variants on the same platform MUST use different values for BOTH fields. If platform_fit covers both platforms, all 4 drafts should use 4 distinct (hook_strategy, perspective_focus) combinations."""


# ─── JSON parsing ─────────────────────────────────────────────────────────────

def _parse_copywriter_json(text: str) -> dict[str, Any] | None:
    """Extract and parse the JSON blob from the model's response.

    Three extraction strategies tried in order, each with trailing-comma cleanup:
      1. Content captured inside a ```(json)? ... ``` block
      2. Raw text after stripping fences
      3. Substring from the first { to the last }
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
                if isinstance(parsed, dict) and "drafts" in parsed:
                    return parsed
            except json.JSONDecodeError:
                continue

    return None


# ─── Validation and persistence ───────────────────────────────────────────────

def _validate_drafts(
    drafts: list,
    expected_platforms: list[str],
    cta_strength: str,
    content_format: str,
) -> tuple[list[dict], list[str]]:
    """Coerce enum fields, enforce CTA and format rules, compute word/char counts,
    validate variant differentiation strategies.

    The differentiation_strategy fields (hook_strategy + perspective_focus) are checked
    here at runtime, then dropped before save. They are not persisted to the DB —
    they exist only as a forcing function on the model's output. Forensic data lives
    in the warnings list, which is logged to api_log.notes.

    Returns (valid_drafts, warnings).
    """
    if not isinstance(drafts, list):
        return [], ["No drafts array found in model response."]

    warnings: list[str] = []
    seen: dict[tuple[str, int], bool] = {}
    valid: list[dict] = []

    # Track declared strategies per platform for cross-variant checks after the loop
    strategies_by_platform: dict[str, list[dict]] = {}

    for d in drafts:
        if not isinstance(d, dict):
            continue

        if not d.get("body"):
            warnings.append(
                f"Dropped draft missing required 'body' field "
                f"(platform={d.get('platform')}, variant={d.get('variant_number')})."
            )
            continue

        platform = d.get("platform", "")
        if platform not in _VALID_PLATFORMS:
            warnings.append(f"Invalid platform '{platform}' — skipped.")
            continue
        if platform not in expected_platforms:
            warnings.append(f"Draft for unexpected platform '{platform}' — skipped.")
            continue

        try:
            variant = int(d.get("variant_number", 0))
        except (TypeError, ValueError):
            variant = 0
        if variant not in (1, 2):
            warnings.append(
                f"Invalid variant_number {d.get('variant_number')} for {platform} — skipped."
            )
            continue

        key = (platform, variant)
        if key in seen:
            warnings.append(
                f"Duplicate ({platform}, variant {variant}) — kept first, dropped duplicate."
            )
            continue
        seen[key] = True

        # Mirror the angle's content_format — don't trust what the model echoed
        d["content_format"] = content_format

        # Enforce CTA rule server-side regardless of what the model produced
        if cta_strength == "no_cta" and d.get("cta_line"):
            warnings.append(
                f"cta_strength is no_cta but model produced a cta_line for "
                f"({platform}, variant {variant}) — cleared."
            )
            d["cta_line"] = None

        # Sanitise URL formatting in cta_line — strip www. and https?:// prefixes.
        # Order matters: remove protocol first so https://www.sportz-well.com collapses cleanly.
        if d.get("cta_line"):
            original_cta = d["cta_line"]
            cleaned      = re.sub(r"https?://", "", original_cta)
            cleaned      = cleaned.replace("www.sportz-well.com", "sportz-well.com")
            if cleaned != original_cta:
                d["cta_line"] = cleaned
                warnings.append(
                    f"URL prefix stripped from cta_line for ({platform}, variant {variant}): "
                    f"'{original_cta}' → '{cleaned}'. Model added a disallowed prefix."
                )

        # Enforce carousel_slides
        if content_format != "carousel":
            d["carousel_slides"] = None
        elif not isinstance(d.get("carousel_slides"), list):
            d["carousel_slides"] = None

        # Enforce reel_script
        if content_format != "reel_script":
            d["reel_script"] = None
        elif not isinstance(d.get("reel_script"), dict):
            d["reel_script"] = None

        # ── Variant differentiation strategy validation ──
        # Capture declared strategies for cross-variant comparison below.
        # Missing or invalid values become None — handled in the cross-check loop.
        hook_strategy     = d.get("hook_strategy")
        perspective_focus = d.get("perspective_focus")

        if hook_strategy is not None and hook_strategy not in _VALID_DIFFERENTIATION_STRATEGIES:
            # Could be valid perspective in wrong field; check before warning
            warnings.append(
                f"Draft ({platform}, variant {variant}) declared "
                f"hook_strategy='{hook_strategy}' which is not a recognised hook mode. "
                "Differentiation check skipped for this draft."
            )
            hook_strategy = None

        if perspective_focus is not None and perspective_focus not in _VALID_DIFFERENTIATION_STRATEGIES:
            warnings.append(
                f"Draft ({platform}, variant {variant}) declared "
                f"perspective_focus='{perspective_focus}' which is not a recognised perspective. "
                "Differentiation check skipped for this draft."
            )
            perspective_focus = None

        if hook_strategy is None or perspective_focus is None:
            warnings.append(
                f"Draft ({platform}, variant {variant}) is missing hook_strategy or "
                "perspective_focus declaration. Cannot validate differentiation."
            )

        strategies_by_platform.setdefault(platform, []).append({
            "variant":           variant,
            "hook_strategy":     hook_strategy,
            "perspective_focus": perspective_focus,
        })

        # Compute word_count and char_count server-side — don't trust the model's arithmetic
        body = d.get("body", "")
        d["word_count"] = len(body.split())
        d["char_count"] = len(body)

        if not isinstance(d.get("hashtags"), list):
            d["hashtags"] = []
        if not isinstance(d.get("proof_points_used"), list):
            d["proof_points_used"] = []
        if not d.get("headline"):
            d["headline"] = ""
        if not d.get("image_brief"):
            d["image_brief"] = ""

        d["platform"]       = platform
        d["variant_number"] = variant

        # Drop differentiation declaration fields before persistence — validation-only.
        # Schema is unchanged; these fields would be ignored by INSERT anyway, but explicit
        # is better than implicit.
        d.pop("hook_strategy", None)
        d.pop("perspective_focus", None)

        valid.append(d)

    # ── Cross-variant differentiation checks ──
    # Within each platform: V1 and V2 must declare different hook_strategy AND different perspective_focus.
    # Across platforms (for platform_fit=both): all 4 drafts ideally use 4 distinct
    # (hook_strategy, perspective_focus) combinations — soft warning if any combo repeats.

    for platform, declarations in strategies_by_platform.items():
        if len(declarations) < 2:
            continue
        v1 = next((d for d in declarations if d["variant"] == 1), None)
        v2 = next((d for d in declarations if d["variant"] == 2), None)
        if v1 is None or v2 is None:
            continue
        if v1["hook_strategy"] and v2["hook_strategy"] and v1["hook_strategy"] == v2["hook_strategy"]:
            warnings.append(
                f"Variant differentiation FAILED on {platform}: V1 and V2 both declared "
                f"hook_strategy='{v1['hook_strategy']}'. Likely duplicate hook patterns — "
                "review before approving."
            )
        if (v1["perspective_focus"] and v2["perspective_focus"]
                and v1["perspective_focus"] == v2["perspective_focus"]):
            warnings.append(
                f"Variant differentiation FAILED on {platform}: V1 and V2 both declared "
                f"perspective_focus='{v1['perspective_focus']}'. Likely duplicate perspectives — "
                "review before approving."
            )

    # Cross-platform check — for platform_fit=both
    if len(strategies_by_platform) > 1:
        all_combos: list[tuple[str, tuple[str, str]]] = []
        for platform, declarations in strategies_by_platform.items():
            for d in declarations:
                if d["hook_strategy"] and d["perspective_focus"]:
                    combo = (d["hook_strategy"], d["perspective_focus"])
                    label = f"{platform} V{d['variant']}"
                    all_combos.append((label, combo))

        seen_combos: dict[tuple[str, str], str] = {}
        for label, combo in all_combos:
            if combo in seen_combos:
                warnings.append(
                    f"Cross-platform differentiation soft-warning: {label} and "
                    f"{seen_combos[combo]} both declared "
                    f"(hook={combo[0]}, perspective={combo[1]}). "
                    "Across-platform hook+perspective combos ideally all distinct."
                )
            else:
                seen_combos[combo] = label

    return valid, warnings


def _save_drafts(drafts: list[dict], angle_id: int, product_id: int) -> int:
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = 0

    with get_connection() as conn:
        for d in drafts:
            conn.execute(
                """
                INSERT OR REPLACE INTO drafts (
                    story_angle_id, product_id, platform, variant_number,
                    content_format, headline, body, cta_line, hashtags,
                    carousel_slides, reel_script, image_brief, proof_points_used,
                    word_count, char_count, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    angle_id,
                    product_id,
                    d["platform"],
                    d["variant_number"],
                    d["content_format"],
                    d.get("headline", ""),
                    d.get("body", ""),
                    d.get("cta_line"),
                    json.dumps(d.get("hashtags", [])),
                    json.dumps(d["carousel_slides"]) if d.get("carousel_slides") else None,
                    json.dumps(d["reel_script"])     if d.get("reel_script")     else None,
                    d.get("image_brief", ""),
                    json.dumps(d.get("proof_points_used", [])),
                    d.get("word_count", 0),
                    d.get("char_count", 0),
                    "draft",
                    now,
                    now,
                ),
            )
            count += 1

    return count


# ─── Cost and logging ─────────────────────────────────────────────────────────

def _log_failed_response(raw_text: str) -> None:
    """Append the full raw model response to data/copywriter_failed_responses.log."""
    ts       = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_path = PROJECT_ROOT / "data" / "copywriter_failed_responses.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n{'=' * 60}\n{ts}\n{raw_text}\n")


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
    action = f"copywriter run (product_id={product_id})"

    CSV_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not CSV_LOG_PATH.exists()
    with CSV_LOG_PATH.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if write_header:
            writer.writerow(["timestamp", "agent", "topic", "input_tokens",
                             "output_tokens", "web_searches", "est_cost_usd"])
        writer.writerow([ts, "copywriter", action, input_tokens, output_tokens, 0, cost])

    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO api_log
                   (timestamp, agent, action, input_tokens, output_tokens,
                    web_searches, est_cost_usd, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, "copywriter", action, input_tokens, output_tokens, 0, cost, notes),
            )
    except sqlite3.OperationalError:
        pass


def _error_result(
    angle_id: int,
    angle_title: str,
    platforms: list[str],
    cost: float,
    error: str,
) -> dict[str, Any]:
    return {
        "angle_id":       angle_id,
        "angle_title":    angle_title,
        "platforms":      platforms,
        "drafts_created": 0,
        "est_cost_usd":   cost,
        "drafts":         [],
        "warnings":       [],
        "error":          error,
    }


# ─── UI query helpers ─────────────────────────────────────────────────────────

def count_draft_stats(product_id: int) -> dict[str, Any]:
    """Return counts needed for Tab 1 and Tab 3 of the Drafts page."""
    try:
        with get_connection() as conn:
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM drafts WHERE product_id = ? GROUP BY status",
                (product_id,),
            ).fetchall()
            by_status = {r["status"]: r["n"] for r in status_rows}

            total_approved = conn.execute(
                """SELECT COUNT(*) FROM story_angles
                   WHERE product_id = ? AND status IN ('approved', 'edited')""",
                (product_id,),
            ).fetchone()[0]

            drafted_angles = conn.execute(
                "SELECT COUNT(DISTINCT story_angle_id) FROM drafts WHERE product_id = ?",
                (product_id,),
            ).fetchone()[0]

            plat_rows = conn.execute(
                "SELECT platform, COUNT(*) AS n FROM drafts WHERE product_id = ? GROUP BY platform",
                (product_id,),
            ).fetchall()
            by_platform = {r["platform"]: r["n"] for r in plat_rows}

        return {
            "by_status":      by_status,
            "total_approved": int(total_approved),
            "drafted_angles": int(drafted_angles),
            "waiting":        max(0, int(total_approved) - int(drafted_angles)),
            "by_platform":    by_platform,
            "total_drafts":   sum(by_status.values()),
        }
    except sqlite3.OperationalError:
        return {
            "by_status": {}, "total_approved": 0, "drafted_angles": 0,
            "waiting": 0, "by_platform": {}, "total_drafts": 0,
        }


def get_drafts_library(
    product_id: int,
    status_filter: str | None = None,
    platform_filter: str | None = None,
    angle_id_filter: int | None = None,
) -> list[dict]:
    """Return drafts joined with their angle title, optionally filtered."""
    clauses: list[str] = ["d.product_id = ?"]
    params: list[Any]  = [product_id]

    if status_filter:
        clauses.append("d.status = ?")
        params.append(status_filter)
    if platform_filter:
        clauses.append("d.platform = ?")
        params.append(platform_filter)
    if angle_id_filter:
        clauses.append("d.story_angle_id = ?")
        params.append(angle_id_filter)

    where = " AND ".join(clauses)
    try:
        with get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT d.*,
                       COALESCE(sa.angle_title, sa.title, 'Untitled') AS angle_title,
                       sa.cta_strength AS angle_cta_strength,
                       sa.platform_fit
                FROM drafts d
                LEFT JOIN story_angles sa ON sa.id = d.story_angle_id
                WHERE {where}
                ORDER BY d.story_angle_id, d.platform, d.variant_number
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def update_draft_status(draft_id: int, new_status: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        conn.execute(
            "UPDATE drafts SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, draft_id),
        )


def update_draft_content(
    draft_id: int,
    headline: str,
    body: str,
    cta_line: str | None,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        conn.execute(
            """UPDATE drafts
               SET headline = ?, body = ?, cta_line = ?,
                   word_count = ?, char_count = ?,
                   status = 'edited', updated_at = ?
               WHERE id = ?""",
            (
                headline,
                body,
                cta_line or None,
                len(body.split()),
                len(body),
                now,
                draft_id,
            ),
        )


def get_approved_angles(product_id: int) -> list[dict]:
    """Return approved/edited angles for the single-angle dropdown."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT id, COALESCE(angle_title, title, 'Untitled') AS angle_title,
                          platform_fit, status
                   FROM story_angles
                   WHERE product_id = ? AND status IN ('approved', 'edited')
                   ORDER BY id""",
                (product_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def get_angle_draft_coverage(product_id: int) -> list[dict]:
    """Return per-angle draft count for the pipeline overview."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT sa.id,
                       COALESCE(sa.angle_title, sa.title, 'Untitled') AS angle_title,
                       sa.platform_fit,
                       COUNT(d.id) AS draft_count
                FROM story_angles sa
                LEFT JOIN drafts d ON d.story_angle_id = sa.id
                WHERE sa.product_id = ? AND sa.status IN ('approved', 'edited')
                GROUP BY sa.id
                ORDER BY sa.id
                """,
                (product_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []