"""Copywriter agent — third agent in the pipeline.

Reads an approved story angle from story_angles, calls the Anthropic API
(pure reasoning, no web search), and saves 2 platform-appropriate draft
variants per target platform to the drafts table.

Each draft also generates a visual_photography_note — a 1-3 sentence AI
image directive saved to the drafts table and used by the Media agent.

Public API
----------
write_drafts_for_angle(angle_id, regenerate=False) -> dict
write_drafts_for_all_approved(product_id) -> dict
delete_draft_permanently(draft_id) -> None
get_editor_review_status(product_id) -> dict[int, str]
"""

from __future__ import annotations

import csv
import json
import re
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

_VALID_PLATFORMS   = {"instagram", "facebook", "linkedin"}
_VALID_CTA         = {"hard_cta", "soft_cta", "no_cta"}
_VALID_CONTENT_FMT = {"single_image", "carousel", "text_post", "reel_script", "video_script"}

_VALID_DIFFERENTIATION_STRATEGIES = {
    "question_hook", "scenario_hook", "statement_hook", "story_hook", "framework_hook",
    "coach_pov", "parent_pov", "player_pov", "academy_pov",
}


# ─── Public entry points ──────────────────────────────────────────────────────

def write_drafts_for_angle(angle_id: int, regenerate: bool = False) -> dict[str, Any]:
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
    elif platform_fit == "linkedin":
        platforms = ["linkedin"]
    else:
        # "both" = instagram + facebook only. LinkedIn must be explicitly assigned.
        platforms = ["instagram", "facebook"]

    if not regenerate:
        existing = _fetch_existing_drafts(angle_id)
        if existing:
            return {
                "angle_id": angle_id, "angle_title": angle_title, "platforms": platforms,
                "drafts_created": 0, "est_cost_usd": 0.0, "drafts": existing,
                "warnings": ["Drafts already exist. Tick 'Regenerate' to overwrite."],
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
        _log_api_call(product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
            f"FAILURE: API error: {api_result['error'][:200]}")
        return _error_result(angle_id, angle_title, platforms, cost, api_result["error"])

    parse_result = _parse_copywriter_json(api_result["text"])
    if parse_result is None:
        _log_failed_response(api_result["text"])
        _log_api_call(product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
            f"FAILURE: JSON parse failed. Raw (first 300): {api_result['text'][:300]}")
        return _error_result(angle_id, angle_title, platforms, cost,
            "Could not parse the model's response as JSON. "
            f"Raw response (first 500 chars): {api_result['text'][:500]}")

    raw_drafts     = parse_result.get("drafts", [])
    model_warnings = list(parse_result.get("warnings", []))

    validated, validation_warnings = _validate_drafts(raw_drafts, platforms, cta_strength, content_format)
    all_warnings = model_warnings + validation_warnings
    saved = _save_drafts(validated, angle_id, product_id)

    _log_api_call(product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
        f"SUCCESS: angle={angle_id}, platforms={platforms}, saved={saved}, warnings={len(all_warnings)}")

    return {
        "angle_id": angle_id, "angle_title": angle_title, "platforms": platforms,
        "drafts_created": saved, "est_cost_usd": cost, "drafts": validated,
        "warnings": all_warnings, "error": None,
    }


def write_drafts_for_all_approved(product_id: int) -> dict[str, Any]:
    angles = _fetch_undrafted_approved_angles(product_id)
    if not angles:
        return {
            "angles_processed": 0, "drafts_created": 0, "total_cost_usd": 0.0,
            "errors": [], "warnings": ["No approved angles without existing drafts found."],
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
            errors.append(f"Angle {angle['id']} ({angle.get('angle_title') or angle.get('title', '?')}): {result['error']}")
        all_warnings.extend(result.get("warnings", []))

    return {
        "angles_processed": len(angles), "drafts_created": total_drafts,
        "total_cost_usd": round(total_cost, 6), "errors": errors, "warnings": all_warnings,
    }


# ─── Data fetching ────────────────────────────────────────────────────────────

def _fetch_angle(angle_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, product_id, angle_title, title, angle_description, angle,
                      editorial_brief, platform_fit, cta_strength, content_format,
                      proof_points_used, status
               FROM story_angles WHERE id = ?""",
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
            """SELECT sa.id, sa.angle_title, sa.title
               FROM story_angles sa
               WHERE sa.product_id = ? AND sa.status IN ('approved', 'edited')
                 AND NOT EXISTS (SELECT 1 FROM drafts d WHERE d.story_angle_id = sa.id)
               ORDER BY sa.id""",
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

Given a single approved story angle and its editorial brief, you produce 2 distinct draft variants per target platform ({platform_list}). You translate the angle into ready-to-post copy.

## CRITICAL — Punctuation rules inside JSON string fields

Inside body, headline, cta_line, image_brief, visual_photography_note, and any other string field, you MUST NOT use double-quote characters (") for any reason.

- For dialogue: use single quotes. CORRECT: He said, 'doing well.' WRONG: He said, "doing well."
- For emphasis: rephrase or use em-dash. CORRECT: what amounts to a holding message. WRONG: a "holding message".
- For titles: capitalize naturally. CORRECT: the Mumbai Under-16 selection trial. WRONG: the "Mumbai Under-16 selection trial".

The ONLY double quotes in your output are JSON structural quotes. Any double quote inside a string value breaks JSON parsing.

## Platform Rules — HARD RULES

### INSTAGRAM
**Audience:** Young cricketers (U10–U17) and emotionally invested parents.
**Visual-first rule:** The image carries 70% of the story. Your words SUPPORT the visual — they do not replace it. Write as if the reader has already seen the image.
- Caption length: 80–130 words for single_image and carousel. 50–100 words for reel_script and video_script.
- Hook in line 1 — one punchy sentence that earns a thumb-stop in under 3 seconds.
- Structure: Hook (1 line) → 2–3 short tight paragraphs → hashtags. Never more than 3 paragraphs.
- Every sentence must earn its place. If it can be cut, cut it.
- Tone: Energetic, aspirational, direct. Speaks to the player's journey.
- Blank line between every paragraph — use \\n\\n in the JSON body field.
- Hashtags: 8–15 tags, relevant only. Place after main body, separated by a blank line.
- Banned openers: 'In today's world...', 'Did you know...', 'Imagine if...', 'Let's talk about...'
- For carousel: 5–8 slides. Each slide_body strict max 20 words — tight and punchy.
- image_brief: Describe a specific visual moment — an action shot, a coaching interaction, a player drill. Not generic. Something a photographer can actually shoot.

### FACEBOOK
**Audience:** Parents aged 30–50 evaluating and deciding on cricket academy for their child.
**Visual-first rule:** The image does the visual work. Your words build trust and answer parent concerns.
- Caption length: 60–120 words for single_image and carousel. 60–150 words for text_post. 50–100 words for reel_script.
- Hook in line 1 — one concrete, specific sentence that speaks to a parent concern or decision.
- Structure: Hook → 1–2 short paragraphs → optional CTA. Never more than 2 paragraphs of body text.
- Tone: Reassuring, informative, community-focused. Speaks to the PARENT making decisions — not the player.
- Blank line between paragraphs — use \\n\\n in the JSON body field.
- Hashtags: 2–5 only. Topic-specific. No generic tags.
- Banned openers: Same as Instagram. Be specific and concrete.
- image_brief: Describe a visual that reassures a parent — structured environment, coach interaction, safe training, progress being tracked.

### LINKEDIN
**Audience:** Academy directors, head coaches, sports institution operators. B2B decision-makers.
- Caption length: 150–300 words for single_image and text_post.
- Formats: single_image and text_post ONLY. carousel and reel_script are NOT valid for LinkedIn.
- Tone: B2B professional. Detailed explanation is appropriate and expected. Longer paragraphs are fine.
- Hook in line 1 — frames a professional problem or insight that a decision-maker would stop to read.
- Structure: Hook → insight/evidence → practical implication → optional CTA.
- Blank line between paragraphs — use \\n\\n in the JSON body field.
- Hashtags: 3–5 only. Professional and topic-specific. No generic tags.
- No emojis anywhere in LinkedIn body or CTA.
- CTA style: Professional invitation. CORRECT: If your academy is evaluating structured performance tracking, SWPI was built for this — visit sportz-well.com. WRONG: Book now! Limited spots!
- image_brief: For text_post, set image_brief to null. For single_image, describe a clean professional visual — coach reviewing data, structured training environment, academy session. No consumer-style graphics.

### X / Twitter — FUTURE PLATFORM
X is on the product roadmap. It is NOT yet supported. Do not produce X/Twitter drafts. If a platform field arrives as "twitter" or "x", skip it and add a warning.

### Blog and Newsletter — FUTURE INTEGRATION
Blogs and newsletters are on the roadmap but do not yet exist. Do NOT include any blog URL or newsletter link. Once live, they will be referenced via the brand context CTA block. For now: do not reference blog or newsletter in any post.

## Visual Photography Note — REQUIRED (except LinkedIn text_post)

For every draft, produce a visual_photography_note alongside the image_brief.

This is NOT the same as image_brief. image_brief is general visual context for a human photographer.
visual_photography_note is a precise directive for an AI image generator (Firefly, DALL-E 3, Gemini)
that can be pasted directly into the tool and produce a usable image.

Rules:
- 1-3 sentences maximum — tight and specific
- Include: subject + action, setting, lighting and mood, one clear AVOID
- Must match the emotional hook of THIS specific post — not a generic brand image
- Authentic settings: maidans, practice nets, academy grounds, school grounds, club grounds
- Documentary and editorial — no posed shots, no stock-photo energy
- No clearly identifiable faces. No logos. No text in the image.
- Set to null for LinkedIn text_post only — required for ALL other formats

Good example (coach-parent disconnect post):
'A U-14 batter at outdoor practice nets with coach crouching beside him correcting
grip, parent figure watching from beyond the boundary rope in soft background blur,
warm late afternoon light, documentary and unposed. Avoid anything celebratory or
staged.'

Bad example (too generic, not tied to this post):
'A cricket player training at an academy.' — useless. Be specific to the hook.

## CTA Rules — cta_strength is "{cta_strength}". Match it exactly.

- **no_cta**: cta_line MUST be null. No product pitch, no implicit invitation. Post earns trust on its own.
- **soft_cta**: One gentle mention only. No urgency. Examples: If you are thinking about structured reporting in your academy, SWPI was built for exactly this. OR Learn more at sportz-well.com if this resonates.
- **hard_cta**: One direct invitation. Always include sportz-well.com. Examples: Book a demo at sportz-well.com. OR Reply to schedule a 20-minute walkthrough.

URL FORMATTING — CRITICAL:
- MUST appear exactly as: sportz-well.com
- Do NOT add www. Do NOT add https://
- CORRECT: sportz-well.com | WRONG: www.sportz-well.com | WRONG: https://sportz-well.com

## Proof Point Rules
- Use ONLY proof points explicitly listed in the angle's proof_points_used array. Never invent.
- Sparing proof points (Achrekar, Tendulkar, Shardashram) must be framed institutionally:
  - CORRECT: grounded in the same disciplined coaching philosophy that shaped Mumbai's grassroots tradition
  - WRONG: inspired by the coach of Sachin Tendulkar

## Voice Rules
- Expert, Structured, Purposeful. No hype.
- Specific nouns: U-12 batter not young player; video analysis session not training tool.
- Banned hype words: amazing, incredible, game-changing, revolutionary, transformative, world-class (as filler), elevate (as hype), empower, supercharge, unleash.
- India-specific framing where appropriate — BCCI, Ranji Trophy, city academy contexts are on-brand.
- English only. No Hindi, Hinglish, or transliterated cricket slang unless editorial brief explicitly calls for it.

## Variant Differentiation — MANDATORY

For each platform, produce 2 variants that differ in BOTH:
1. **Hook structure** — different rhetorical mode: question_hook | scenario_hook | statement_hook | story_hook | framework_hook
2. **Perspective focus** — different stakeholder: coach_pov | parent_pov | player_pov | academy_pov

Declare both fields in every draft JSON. Siblings on the same platform MUST use different values for BOTH fields.

## Output Format

Return ONLY the JSON object below. No markdown fences. No prose before or after.

{{
  "drafts": [
    {{
      "platform": "instagram" or "facebook" or "linkedin",
      "variant_number": 1 or 2,
      "content_format": "<mirror angle content_format: single_image | carousel | text_post | reel_script | video_script>",
      "hook_strategy": "<question_hook | scenario_hook | statement_hook | story_hook | framework_hook>",
      "perspective_focus": "<coach_pov | parent_pov | player_pov | academy_pov>",
      "headline": "opening hook line — first sentence of body",
      "body": "full caption with \\n\\n between paragraphs",
      "cta_line": "CTA line or null if no_cta",
      "hashtags": ["#tag1", "#tag2"],
      "carousel_slides": [{{"slide_number": 1, "slide_title": "...", "slide_body": "max 20 words"}}],
      "reel_script": {{"hook_seconds_0_3": "...", "beats": ["beat 1"], "voiceover": "...", "on_screen_text": ["text 1"]}},
      "image_brief": "1-2 sentences for the Media agent, or null for LinkedIn text_post",
      "visual_photography_note": "1-3 sentence AI image directive — subject, action, setting, mood, one avoid. Specific to this post's hook. Null only for LinkedIn text_post.",
      "proof_points_used": ["exact proof point strings used"],
      "word_count": <integer>,
      "char_count": <integer>
    }}
  ],
  "warnings": ["deviations or issues; empty array if none"]
}}

IMPORTANT:
- carousel_slides: null when not carousel
- reel_script: null when not reel_script
- LinkedIn: carousel_slides and reel_script MUST always be null
- visual_photography_note: null for LinkedIn text_post only. REQUIRED for all other formats.
- Total drafts must equal exactly {total_drafts} ({2} variants × {len(platforms)} platform(s): {", ".join(platforms)})
- hook_strategy and perspective_focus are REQUIRED on every draft
- NO double-quote characters inside any string value"""


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
        if proof_points else "  (none — do not invent proof points)"
    )

    total_drafts = 2 * len(platforms)
    platform_notes = []
    if "instagram" in platforms:
        platform_notes.append("Instagram: visual-first, 80-130 words, speaks to young players and emotionally invested parents")
    if "facebook" in platforms:
        platform_notes.append("Facebook: concise impact, 60-120 words, speaks to parents making decisions about their child's academy")
    if "linkedin" in platforms:
        platform_notes.append("LinkedIn: B2B professional, 150-300 words, speaks to academy directors and head coaches")

    return f"""Write drafts for the following approved story angle.

**Angle Title:** {angle_title}
**Angle Description:** {angle_desc}

**Editorial Brief:**
{editorial if editorial else "(no brief provided)"}

**Target Platform(s):** {", ".join(platforms)}
**Platform audience notes:**
{chr(10).join(f"  - {n}" for n in platform_notes)}
**Content Format:** {content_fmt}
**CTA Strength:** {cta_strength}

**Proof Points Approved for This Angle:**
{pp_block}

Produce exactly {total_drafts} drafts ({2} variants per platform). Each platform has a DIFFERENT audience — write accordingly. Do not write the same message reformatted. Write genuinely different content for each audience.

For every draft declare hook_strategy and perspective_focus. Sibling variants on the same platform MUST use different values for BOTH.

For every draft (except LinkedIn text_post) write a visual_photography_note: 1-3 sentences specific to this post's hook, ready to paste into an AI image tool.

NO double-quote characters inside any string field."""


# ─── JSON parsing ─────────────────────────────────────────────────────────────

def _parse_copywriter_json(text: str) -> dict[str, Any] | None:
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

    decoder   = json.JSONDecoder()
    all_valid: list[dict] = []
    for m in re.finditer(r'\{[\s\r\n]*"drafts"', original):
        try:
            parsed, _ = decoder.raw_decode(original, m.start())
            if isinstance(parsed, dict) and "drafts" in parsed:
                all_valid.append(parsed)
        except json.JSONDecodeError:
            pass
    if all_valid:
        return all_valid[-1]

    return None


# ─── Validation and persistence ───────────────────────────────────────────────

def _validate_drafts(
    drafts: list,
    expected_platforms: list[str],
    cta_strength: str,
    content_format: str,
) -> tuple[list[dict], list[str]]:
    if not isinstance(drafts, list):
        return [], ["No drafts array found in model response."]

    warnings: list[str] = []
    seen: dict[tuple[str, int], bool] = {}
    valid: list[dict] = []
    strategies_by_platform: dict[str, list[dict]] = {}

    for d in drafts:
        if not isinstance(d, dict):
            continue
        if not d.get("body"):
            warnings.append(f"Dropped draft missing 'body' (platform={d.get('platform')}, variant={d.get('variant_number')}).")
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
            warnings.append(f"Invalid variant_number {d.get('variant_number')} for {platform} — skipped.")
            continue

        key = (platform, variant)
        if key in seen:
            warnings.append(f"Duplicate ({platform}, variant {variant}) — kept first, dropped duplicate.")
            continue
        seen[key] = True

        if platform == "linkedin":
            if content_format not in ("single_image", "text_post"):
                d["content_format"] = "single_image"
                warnings.append(f"LinkedIn draft ({platform}, v{variant}) had unsupported format '{content_format}' — forced to 'single_image'.")
            else:
                d["content_format"] = content_format
        else:
            d["content_format"] = content_format

        if cta_strength == "no_cta" and d.get("cta_line"):
            warnings.append(f"cta_strength is no_cta but model produced cta_line for ({platform}, v{variant}) — cleared.")
            d["cta_line"] = None

        if d.get("cta_line"):
            original_cta = d["cta_line"]
            cleaned = re.sub(r"https?://", "", original_cta)
            cleaned = cleaned.replace("www.sportz-well.com", "sportz-well.com")
            if cleaned != original_cta:
                d["cta_line"] = cleaned
                warnings.append(f"URL prefix stripped from cta_line for ({platform}, v{variant}).")

        if content_format != "carousel" or platform == "linkedin":
            d["carousel_slides"] = None
        elif not isinstance(d.get("carousel_slides"), list):
            d["carousel_slides"] = None

        if content_format != "reel_script" or platform == "linkedin":
            d["reel_script"] = None
        elif not isinstance(d.get("reel_script"), dict):
            d["reel_script"] = None

        # Null image_brief and visual_photography_note for LinkedIn text_post
        if platform == "linkedin" and d.get("content_format") == "text_post":
            d["image_brief"] = None
            d["visual_photography_note"] = None

        # Normalise visual_photography_note for all other drafts
        vn = d.get("visual_photography_note")
        if d.get("visual_photography_note") is not None:
            if not isinstance(vn, str) or not vn.strip():
                d["visual_photography_note"] = None

        hook_strategy     = d.get("hook_strategy")
        perspective_focus = d.get("perspective_focus")

        if hook_strategy is not None and hook_strategy not in _VALID_DIFFERENTIATION_STRATEGIES:
            warnings.append(f"Draft ({platform}, v{variant}) declared unrecognised hook_strategy='{hook_strategy}'.")
            hook_strategy = None
        if perspective_focus is not None and perspective_focus not in _VALID_DIFFERENTIATION_STRATEGIES:
            warnings.append(f"Draft ({platform}, v{variant}) declared unrecognised perspective_focus='{perspective_focus}'.")
            perspective_focus = None
        if hook_strategy is None or perspective_focus is None:
            warnings.append(f"Draft ({platform}, v{variant}) missing hook_strategy or perspective_focus.")

        strategies_by_platform.setdefault(platform, []).append({
            "variant": variant, "hook_strategy": hook_strategy, "perspective_focus": perspective_focus,
        })

        body = d.get("body", "")
        d["word_count"] = len(body.split())
        d["char_count"] = len(body)

        if not isinstance(d.get("hashtags"), list):
            d["hashtags"] = []
        if not isinstance(d.get("proof_points_used"), list):
            d["proof_points_used"] = []
        if not d.get("headline"):
            d["headline"] = ""
        if d.get("image_brief") is None and platform != "linkedin":
            d["image_brief"] = ""
        if "visual_photography_note" not in d:
            d["visual_photography_note"] = None

        d["platform"]       = platform
        d["variant_number"] = variant
        d.pop("hook_strategy", None)
        d.pop("perspective_focus", None)

        valid.append(d)

    for platform, declarations in strategies_by_platform.items():
        if len(declarations) < 2:
            continue
        v1 = next((d for d in declarations if d["variant"] == 1), None)
        v2 = next((d for d in declarations if d["variant"] == 2), None)
        if v1 is None or v2 is None:
            continue
        if v1["hook_strategy"] and v2["hook_strategy"] and v1["hook_strategy"] == v2["hook_strategy"]:
            warnings.append(f"Variant differentiation FAILED on {platform}: V1 and V2 both declared hook_strategy='{v1['hook_strategy']}'.")
        if v1["perspective_focus"] and v2["perspective_focus"] and v1["perspective_focus"] == v2["perspective_focus"]:
            warnings.append(f"Variant differentiation FAILED on {platform}: V1 and V2 both declared perspective_focus='{v1['perspective_focus']}'.")

    if len(strategies_by_platform) > 1:
        all_combos: list[tuple[str, tuple[str, str]]] = []
        for platform, declarations in strategies_by_platform.items():
            for d in declarations:
                if d["hook_strategy"] and d["perspective_focus"]:
                    all_combos.append((f"{platform} V{d['variant']}", (d["hook_strategy"], d["perspective_focus"])))

        seen_combos: dict[tuple[str, str], str] = {}
        for label, combo in all_combos:
            if combo in seen_combos:
                warnings.append(f"Cross-platform soft-warning: {label} and {seen_combos[combo]} share same (hook, perspective) combo.")
            else:
                seen_combos[combo] = label

    return valid, warnings


def _save_drafts(drafts: list[dict], angle_id: int, product_id: int) -> int:
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = 0

    with get_connection() as conn:
        for d in drafts:
            conn.execute(
                """INSERT INTO drafts (
                    story_angle_id, product_id, platform, variant_number,
                    content_format, headline, body, cta_line, hashtags,
                    carousel_slides, reel_script, image_brief, proof_points_used,
                    word_count, char_count, visual_photography_note,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    angle_id, product_id, d["platform"], d["variant_number"],
                    d["content_format"], d.get("headline", ""), d.get("body", ""),
                    d.get("cta_line"),
                    json.dumps(d.get("hashtags", [])),
                    json.dumps(d["carousel_slides"]) if d.get("carousel_slides") else None,
                    json.dumps(d["reel_script"])     if d.get("reel_script")     else None,
                    d.get("image_brief"),
                    json.dumps(d.get("proof_points_used", [])),
                    d.get("word_count", 0), d.get("char_count", 0),
                    d.get("visual_photography_note"),
                    "draft", now, now,
                ),
            )
            count += 1

    return count


# ─── Cost and logging ─────────────────────────────────────────────────────────

def _log_failed_response(raw_text: str) -> None:
    ts       = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_path = PROJECT_ROOT / "data" / "copywriter_failed_responses.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n{'=' * 60}\n{ts}\n{raw_text}\n")


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return round(input_tokens * _INPUT_COST_PER_TOKEN + output_tokens * _OUTPUT_COST_PER_TOKEN, 6)


def _log_api_call(product_id, input_tokens, output_tokens, cost, notes=""):
    ts     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = f"copywriter run (product_id={product_id})"

    CSV_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not CSV_LOG_PATH.exists()
    with CSV_LOG_PATH.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if write_header:
            writer.writerow(["timestamp", "agent", "topic", "input_tokens", "output_tokens", "web_searches", "est_cost_usd"])
        writer.writerow([ts, "copywriter", action, input_tokens, output_tokens, 0, cost])

    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO api_log (timestamp, agent, action, input_tokens, output_tokens, web_searches, est_cost_usd, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, "copywriter", action, input_tokens, output_tokens, 0, cost, notes),
            )
    except Exception:
        pass


def _error_result(angle_id, angle_title, platforms, cost, error):
    return {
        "angle_id": angle_id, "angle_title": angle_title, "platforms": platforms,
        "drafts_created": 0, "est_cost_usd": cost, "drafts": [], "warnings": [], "error": error,
    }


# ─── UI query helpers ─────────────────────────────────────────────────────────

def count_draft_stats(product_id: int) -> dict[str, Any]:
    try:
        with get_connection() as conn:
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM drafts WHERE product_id = ? GROUP BY status",
                (product_id,),
            ).fetchall()
            by_status = {r["status"]: r["n"] for r in status_rows}

            total_approved = conn.execute(
                "SELECT COUNT(*) FROM story_angles WHERE product_id = ? AND status IN ('approved', 'edited')",
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
            "by_status": by_status, "total_approved": int(total_approved),
            "drafted_angles": int(drafted_angles),
            "waiting": max(0, int(total_approved) - int(drafted_angles)),
            "by_platform": by_platform, "total_drafts": sum(by_status.values()),
        }
    except Exception:
        return {"by_status": {}, "total_approved": 0, "drafted_angles": 0, "waiting": 0, "by_platform": {}, "total_drafts": 0}


def get_drafts_library(
    product_id: int,
    status_filter: str | None = None,
    platform_filter: str | None = None,
    angle_id_filter: int | None = None,
) -> list[dict]:
    """Return drafts enriched with schedule state.

    Added columns vs raw drafts table:
    - is_posted   (0|1): draft has a schedule entry with posted_at IS NOT NULL
    - is_scheduled (0|1): draft has a schedule entry with posted_at IS NULL (pending)
    """
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
                f"""SELECT d.*,
                           COALESCE(sa.angle_title, sa.title, 'Untitled') AS angle_title,
                           sa.cta_strength AS angle_cta_strength,
                           sa.platform_fit,
                           CASE WHEN EXISTS (
                               SELECT 1 FROM schedule s
                               WHERE s.draft_id = d.id AND s.posted_at IS NOT NULL
                           ) THEN 1 ELSE 0 END AS is_posted,
                           CASE WHEN EXISTS (
                               SELECT 1 FROM schedule s
                               WHERE s.draft_id = d.id AND s.posted_at IS NULL
                           ) THEN 1 ELSE 0 END AS is_scheduled
                    FROM drafts d
                    LEFT JOIN story_angles sa ON sa.id = d.story_angle_id
                    WHERE {where}
                    ORDER BY d.story_angle_id, d.platform, d.variant_number""",
                params,
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def delete_draft_permanently(draft_id: int) -> None:
    """Hard-delete a draft and all linked rows (schedule entries, editor reviews, media briefs).

    Safe to call on drafts that have no linked rows — the DELETEs are no-ops.
    """
    with get_connection() as conn:
        conn.execute("DELETE FROM schedule       WHERE draft_id = ?", (draft_id,))
        conn.execute("DELETE FROM editor_reviews WHERE draft_id = ?", (draft_id,))
        conn.execute("DELETE FROM media_briefs   WHERE draft_id = ?", (draft_id,))
        conn.execute("DELETE FROM drafts         WHERE id       = ?", (draft_id,))


def get_editor_review_status(product_id: int) -> dict[int, str]:
    """Return {draft_id: overall_status} for all editor-reviewed drafts of this product.

    Only the most recent review per draft is kept (rows ordered DESC by id).
    Returns empty dict on any DB error — callers treat missing keys as 'not reviewed'.
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT er.draft_id, er.overall_status
                   FROM editor_reviews er
                   JOIN drafts d ON d.id = er.draft_id
                   WHERE d.product_id = ?
                   ORDER BY er.id DESC""",
                (product_id,),
            ).fetchall()
        result: dict[int, str] = {}
        for row in rows:
            if row["draft_id"] not in result:
                result[row["draft_id"]] = row["overall_status"]
        return result
    except Exception:
        return {}


def update_draft_status(draft_id: int, new_status: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        conn.execute(
            "UPDATE drafts SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, draft_id),
        )


def update_draft_content(draft_id: int, headline: str, body: str, cta_line: str | None) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        conn.execute(
            """UPDATE drafts
               SET headline=?, body=?, cta_line=?, word_count=?, char_count=?,
                   status='edited', updated_at=?
               WHERE id=?""",
            (headline, body, cta_line or None, len(body.split()), len(body), now, draft_id),
        )


def get_approved_angles(product_id: int) -> list[dict]:
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
    except Exception:
        return []


def get_angle_draft_coverage(product_id: int) -> list[dict]:
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT sa.id,
                          COALESCE(sa.angle_title, sa.title, 'Untitled') AS angle_title,
                          sa.platform_fit,
                          COUNT(d.id) AS draft_count
                   FROM story_angles sa
                   LEFT JOIN drafts d ON d.story_angle_id = sa.id
                   WHERE sa.product_id = ? AND sa.status IN ('approved', 'edited')
                   GROUP BY sa.id
                   ORDER BY sa.id""",
                (product_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []