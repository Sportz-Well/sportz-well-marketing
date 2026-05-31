"""Strategist agent — second agent in the pipeline.

Reads research_items from the DB, clusters them into themes, and proposes
2–4 story angles per theme for Instagram, Facebook, and/or LinkedIn.
No web search — pure reasoning over existing data.

Brand-aware constraints enforced:
  - Vision-hint quota: ≤ 1 in 20 angles may use phase_2_hint or phase_3_hint
  - Sparing proof points: ≤ 1 in 10 angles may use [sparingly] proof points
  - CTA distribution: ~20% hard_cta, ~40% soft_cta, ~40% no_cta

Public API
----------
propose_story_angles(product_id, min_relevance, max_angles, focus) -> dict
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
from services.brand_context import build_brand_context_prompt, get_brand_profile
from services.database import get_connection

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_LOG_PATH = PROJECT_ROOT / "data" / "api_log.csv"

_INPUT_COST_PER_TOKEN  = 3.00  / 1_000_000
_OUTPUT_COST_PER_TOKEN = 15.00 / 1_000_000

_VALID_PLATFORM_FIT  = {"instagram", "facebook", "linkedin", "both"}
_VALID_PHASE_TAG     = {"phase_1", "phase_2_hint", "phase_3_hint", "founder_credibility", "evergreen"}
_VALID_FUNNEL_STAGE  = {"awareness", "consideration", "demo_pitch"}
_VALID_CONTENT_FMT   = {"single_image", "carousel", "video_script", "text_post", "reel_script"}
_VALID_CTA_STRENGTH  = {"hard_cta", "soft_cta", "no_cta"}


# ─── Public entry point ───────────────────────────────────────────────────────

def propose_story_angles(
    product_id: int,
    min_relevance: int = 7,
    max_angles: int = 12,
    focus: str | None = None,
) -> dict[str, Any]:
    """Cluster research items into themes and propose story angles."""
    research_items = _fetch_research_items(product_id, min_relevance)
    if not research_items:
        return {
            "themes_identified": 0,
            "angles_proposed": 0,
            "est_cost_usd": 0.0,
            "angles": [],
            "warnings": [f"No research items found at min_relevance ≥ {min_relevance}."],
            "error": None,
        }

    brand_ctx    = build_brand_context_prompt(product_id)
    profile      = get_brand_profile(product_id)
    sparing_pps  = profile.get("proof_points_sparing", [])

    max_vision_hints = max(1, max_angles // 20)
    max_sparing_uses = max(1, max_angles // 10)

    system_prompt = _build_system_prompt(brand_ctx, max_angles, max_vision_hints, max_sparing_uses)
    user_prompt   = _build_user_prompt(research_items, product_id, max_angles, focus)

    api_result = ask_with_usage(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=DEFAULT_MODEL,
        max_tokens=4096,
    )

    cost = _estimate_cost(api_result["input_tokens"], api_result["output_tokens"])

    if api_result["error"]:
        _log_api_call(
            product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
            f"FAILURE: API error: {api_result['error'][:200]}",
        )
        return {
            "themes_identified": 0, "angles_proposed": 0,
            "est_cost_usd": cost, "angles": [], "warnings": [],
            "error": api_result["error"],
        }

    parse_result = _parse_strategist_json(api_result["text"])
    if parse_result is None:
        _log_failed_response(api_result["text"])
        _log_api_call(
            product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
            f"FAILURE: JSON parse failed. Raw (first 300): {api_result['text'][:300]}",
        )
        return {
            "themes_identified": 0, "angles_proposed": 0,
            "est_cost_usd": cost, "angles": [], "warnings": [],
            "error": (
                "Could not parse the model's response as JSON. "
                "The full response has been saved to data/strategist_failed_responses.log. "
                f"Raw response (first 500 chars): {api_result['text'][:500]}"
            ),
        }

    themes   = parse_result.get("themes", [])
    warnings = list(parse_result.get("warnings", []))

    themes = _validate_themes(themes)
    warnings += _enforce_vision_quota(themes, max_vision_hints)
    warnings += _enforce_sparing_quota(themes, sparing_pps, max_sparing_uses)

    themes, cap_warning = _cap_angles(themes, max_angles)
    if cap_warning:
        warnings.append(cap_warning)

    saved = _save_angles(themes, product_id)
    all_angles = [a for t in themes for a in t.get("angles", [])]

    _log_api_call(
        product_id, api_result["input_tokens"], api_result["output_tokens"], cost,
        f"SUCCESS: Themes: {len(themes)}, Angles saved: {saved}, Warnings: {len(warnings)}",
    )

    return {
        "themes_identified": len(themes),
        "angles_proposed":   saved,
        "est_cost_usd":      cost,
        "angles":            all_angles,
        "warnings":          warnings,
        "error":             None,
    }


# ─── Data fetching ────────────────────────────────────────────────────────────

def _fetch_research_items(product_id: int, min_relevance: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, source_title, title, topic, summary,
                   relevance_score, source_geography, source_url
            FROM research_items
            WHERE product_id = ?
              AND COALESCE(relevance_score, 0) >= ?
            ORDER BY relevance_score DESC, fetched_at DESC
            """,
            (product_id, min_relevance),
        ).fetchall()
    return [dict(r) for r in rows]


# ─── Prompt construction ──────────────────────────────────────────────────────

def _build_system_prompt(
    brand_ctx: str,
    max_angles: int,
    max_vision_hints: int,
    max_sparing_uses: int,
) -> str:
    return f"""You are the Strategist agent for a social media content pipeline.

{brand_ctx}

## Your Role

Given research items, you cluster them into themes and propose story angles for Instagram, Facebook, and/or LinkedIn. You do NOT write the posts — you write angle premises and editorial briefs that the Copywriter agent will use.

## Platform Guidance for platform_fit

Choose platform_fit deliberately based on audience and content type. Do NOT default to "both" unless the angle genuinely and equally serves both the Instagram and Facebook audiences.

### INSTAGRAM
- **Audience:** Young cricketers (U10–U17) and parents who are emotionally invested in their child's journey.
- **Tone:** Visual-first, aspirational, energetic, punchy. The image carries 70% of the story — the caption supports it.
- **Caption style:** Short and impactful. Hook line + 2–3 tight paragraphs. 80–130 words max.
- **Best angles:** Player development moments, training insights, technique tips, youth inspiration, match preparation, academy culture.
- **Key distinction:** Speaks to the player's journey and the emotionally engaged parent.

### FACEBOOK
- **Audience:** Parents aged 30–50 who are evaluating, deciding, and comparing cricket academies for their child.
- **Tone:** Reassuring, informative, community-focused. Concise but impactful — every word earns its place.
- **Caption style:** 60–120 words. The image does visual work; the words build trust and answer parent concerns.
- **Best angles:** Academy safety and structure, coach–parent communication, progress reporting, selection process transparency, what parents should look for in a good academy.
- **Key distinction:** Speaks to the PARENT making decisions — not the player. Same family as Instagram, completely different mindset.

### LINKEDIN
- **Audience:** Academy directors, head coaches, sports institution operators. B2B decision-makers.
- **Tone:** Professional, evidence-based, detailed. Longer-form is expected and appropriate.
- **Caption style:** 150–300 words. Detailed insight is a feature, not a bug, for this audience.
- **Best angles:** Coaching methodology, academy management, performance data systems, coach development, institutional decisions, structured player assessment frameworks.
- **LinkedIn content format rule:** Only single_image or text_post. Never carousel or reel_script.

### BOTH (Instagram + Facebook)
- Use ONLY when the angle serves BOTH the young-player/aspirational-parent audience (IG) AND the decision-making parent audience (FB) equally well.
- When in doubt: pick the primary platform. Do NOT use "both" as a default.
- Good "both" examples: a factual cricket development news story, a general academy milestone, a coach philosophy that resonates with both audiences.

### X / Twitter — FUTURE PLATFORM
- X is on the product roadmap as a fourth platform. It is NOT yet supported.
- Do NOT assign platform_fit = "twitter" or "x".
- If an angle would naturally suit short punchy viral content (X-style), note it in the editorial_brief as: "Potential X/Twitter angle for future use."
- This flags it for when X support is added without disrupting current pipeline.

### Blog and Newsletter — FUTURE INTEGRATION
- Blogs (weekly) and newsletters (fortnightly) are on the roadmap.
- Once live, Facebook and LinkedIn posts should reference the blog as a secondary CTA.
- Do NOT include blog or newsletter links yet — they do not exist.
- If an angle has strong long-form potential, note in editorial_brief: "Strong blog expansion candidate."

## Hard Constraints

### CONSTRAINT 1: Vision-hint quota
At most {max_vision_hints} angle(s) may use phase_tag "phase_2_hint" or "phase_3_hint".
Vision hints are subtle asides — never make them the headline. Never say "SWPI will soon..." or "coming soon."

### CONSTRAINT 2: Sparing proof points
Proof points labelled "Use sparingly" may appear in at most {max_sparing_uses} angle(s) total.

### CONSTRAINT 3: Topics
Every angle MUST map to one or more of the brand's owned topics. No avoided topics.

### CONSTRAINT 4: CTA distribution
- hard_cta: ~20% of angles
- soft_cta: ~40% of angles
- no_cta: ~40% of angles
LinkedIn hard_cta must use professional invitation style, not consumer urgency.

### CONSTRAINT 5: Voice
Expert, Structured, Purposeful. No hype, no celebrity drama, no superlatives.

### CONSTRAINT 6: LinkedIn format
LinkedIn angles: only "single_image" or "text_post". Never "carousel" or "reel_script".

## Output Format

Return ONLY the JSON object below. No markdown fences. No prose before or after.

{{
  "themes": [
    {{
      "theme_name": "concise label for this theme cluster",
      "angles": [
        {{
          "angle_title": "short punchy title, max 10 words",
          "angle_description": "2–3 sentences: what is this post about and what key insight does it share?",
          "editorial_brief": "1 paragraph for the Copywriter: what to say, tone notes, proof points. For Instagram: note visual-first approach and what the image should show. For Facebook: note parent-focused reassuring tone. For LinkedIn: note B2B professional tone explicitly. Include 'Potential X/Twitter angle' or 'Strong blog expansion candidate' notes where relevant.",
          "platform_fit": "instagram" or "facebook" or "linkedin" or "both",
          "phase_tag": "phase_1" or "phase_2_hint" or "phase_3_hint" or "founder_credibility" or "evergreen",
          "funnel_stage": "awareness" or "consideration" or "demo_pitch",
          "content_format": "single_image" or "carousel" or "video_script" or "text_post" or "reel_script",
          "cta_strength": "hard_cta" or "soft_cta" or "no_cta",
          "source_research_ids": [<integer IDs of research items that inform this angle>],
          "proof_points_used": ["exact proof point string as listed in Brand Context, or empty list"]
        }}
      ]
    }}
  ],
  "warnings": ["quota enforcement actions taken; empty array if none"]
}}"""


def _build_user_prompt(
    items: list[dict],
    product_id: int,
    max_angles: int,
    focus: str | None,
) -> str:
    lines = [f"Research items for product ID {product_id} (ordered by relevance, highest first):\n"]
    for item in items:
        display_title = item.get("source_title") or item.get("title") or "Untitled"
        lines.append(
            f"[ID: {item['id']}] {display_title}\n"
            f"  Topic: {item.get('topic') or '—'}  |  "
            f"Score: {item.get('relevance_score', '?')}/10  |  "
            f"Geography: {item.get('source_geography') or 'Unknown'}\n"
            f"  Summary: {(item.get('summary') or '').strip()}\n"
        )

    lines.append(f"\nPropose up to {max_angles} story angles total (2–4 per theme, 2–5 themes).")
    lines.append("Platform mix target: ~3 Instagram angles, ~3 Facebook angles, ~2–3 LinkedIn angles, remainder 'both' only where genuinely appropriate.")
    lines.append("Remember: Instagram = young player/emotional parent. Facebook = decision-making parent. LinkedIn = academy director/coach. These are DIFFERENT audiences with DIFFERENT messages.")
    if focus:
        lines.append(f"\nEditorial focus for this run: {focus.strip()}")
    else:
        lines.append("\nNo specific focus — draw on the full research library above.")

    return "\n".join(lines)


# ─── JSON parsing ─────────────────────────────────────────────────────────────

def _parse_strategist_json(text: str) -> dict[str, Any] | None:
    original = text.strip()
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
                if isinstance(parsed, dict) and "themes" in parsed:
                    return parsed
            except json.JSONDecodeError:
                continue

    return None


# ─── Validation and quota enforcement ────────────────────────────────────────

def _validate_themes(themes: list) -> list[dict]:
    if not isinstance(themes, list):
        return []

    valid_themes = []
    for theme_obj in themes:
        if not isinstance(theme_obj, dict):
            continue
        angles = theme_obj.get("angles", [])
        if not isinstance(angles, list):
            angles = []

        clean_angles = []
        for a in angles:
            if not isinstance(a, dict):
                continue
            if not a.get("angle_title") or not a.get("angle_description"):
                continue

            a["platform_fit"]   = a.get("platform_fit",  "both")         if a.get("platform_fit")   in _VALID_PLATFORM_FIT  else "both"
            a["phase_tag"]      = a.get("phase_tag",     "phase_1")      if a.get("phase_tag")      in _VALID_PHASE_TAG     else "phase_1"
            a["funnel_stage"]   = a.get("funnel_stage",  "awareness")    if a.get("funnel_stage")   in _VALID_FUNNEL_STAGE  else "awareness"
            a["content_format"] = a.get("content_format","single_image") if a.get("content_format") in _VALID_CONTENT_FMT   else "single_image"
            a["cta_strength"]   = a.get("cta_strength",  "no_cta")       if a.get("cta_strength")   in _VALID_CTA_STRENGTH  else "no_cta"

            # LinkedIn format enforcement
            if a["platform_fit"] == "linkedin" and a["content_format"] not in ("single_image", "text_post"):
                a["content_format"] = "single_image"

            if not isinstance(a.get("source_research_ids"), list):
                a["source_research_ids"] = []
            if not isinstance(a.get("proof_points_used"), list):
                a["proof_points_used"] = []
            a.setdefault("editorial_brief", "")

            clean_angles.append(a)

        if clean_angles:
            valid_themes.append({
                "theme_name": str(theme_obj.get("theme_name") or "Uncategorized"),
                "angles": clean_angles,
            })

    return valid_themes


def _enforce_vision_quota(themes: list[dict], max_hints: int) -> list[str]:
    vision_tags = {"phase_2_hint", "phase_3_hint"}
    count = 0
    warnings = []

    for theme in themes:
        for angle in theme["angles"]:
            if angle["phase_tag"] in vision_tags:
                if count < max_hints:
                    count += 1
                else:
                    angle["phase_tag"] = "phase_1"
                    warnings.append(
                        f"Vision-hint quota enforced: changed \"{angle['angle_title']}\" "
                        f"phase_tag to phase_1 (limit is {max_hints})."
                    )

    return warnings


def _enforce_sparing_quota(
    themes: list[dict],
    sparing_proof_points: list[str],
    max_uses: int,
) -> list[str]:
    if not sparing_proof_points:
        return []

    sparing_set = set(sparing_proof_points)
    count = 0
    warnings = []

    for theme in themes:
        for angle in theme["angles"]:
            used_sparing = [pp for pp in angle["proof_points_used"] if pp in sparing_set]
            if used_sparing:
                if count < max_uses:
                    count += 1
                else:
                    angle["proof_points_used"] = [
                        pp for pp in angle["proof_points_used"] if pp not in sparing_set
                    ]
                    warnings.append(
                        f"Sparing proof-point quota enforced: removed sparing proof point(s) "
                        f"from \"{angle['angle_title']}\" (limit is {max_uses})."
                    )

    return warnings


def _cap_angles(themes: list[dict], max_angles: int) -> tuple[list[dict], str | None]:
    total = sum(len(t["angles"]) for t in themes)
    if total <= max_angles:
        return themes, None

    remaining = max_angles
    trimmed_themes = []
    for theme in themes:
        if remaining <= 0:
            break
        angles = theme["angles"][:remaining]
        remaining -= len(angles)
        trimmed_themes.append({**theme, "angles": angles})

    removed = total - max_angles
    return trimmed_themes, f"Capped at {max_angles} angles (removed {removed} to stay within limit)."


# ─── Database persistence ─────────────────────────────────────────────────────

def _save_angles(themes: list[dict], product_id: int) -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = 0

    with get_connection() as conn:
        for theme_obj in themes:
            theme_name = theme_obj.get("theme_name", "Uncategorized")
            for angle in theme_obj.get("angles", []):
                angle_title = angle.get("angle_title", "Untitled")
                angle_desc  = angle.get("angle_description", "")
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
                        angle_title,
                        angle_desc,
                        theme_name,
                        angle_title,
                        angle_desc,
                        angle.get("editorial_brief", ""),
                        angle.get("platform_fit", "both"),
                        angle.get("phase_tag", "phase_1"),
                        angle.get("funnel_stage", "awareness"),
                        angle.get("content_format", "single_image"),
                        angle.get("cta_strength", "no_cta"),
                        json.dumps(angle.get("source_research_ids", [])),
                        json.dumps(angle.get("proof_points_used", [])),
                        "proposed",
                        now,
                        now,
                    ),
                )
                count += 1

    return count


# ─── Cost and logging ─────────────────────────────────────────────────────────

def _log_failed_response(raw_text: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_path = PROJECT_ROOT / "data" / "strategist_failed_responses.log"
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
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = f"strategist run (product_id={product_id})"

    CSV_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not CSV_LOG_PATH.exists()
    with CSV_LOG_PATH.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if write_header:
            writer.writerow(["timestamp", "agent", "topic", "input_tokens",
                             "output_tokens", "web_searches", "est_cost_usd"])
        writer.writerow([ts, "strategist", action, input_tokens, output_tokens, 0, cost])

    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO api_log
                   (timestamp, agent, action, input_tokens, output_tokens,
                    web_searches, est_cost_usd, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, "strategist", action, input_tokens, output_tokens, 0, cost, notes),
            )
    except sqlite3.OperationalError:
        pass


# ─── UI query helpers ─────────────────────────────────────────────────────────

def count_research_items(product_id: int, min_relevance: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) FROM research_items
               WHERE product_id = ? AND COALESCE(relevance_score, 0) >= ?""",
            (product_id, min_relevance),
        ).fetchone()
    return int(row[0])


def get_last_run_info(product_id: int) -> dict | None:
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT timestamp, est_cost_usd, notes FROM api_log
                   WHERE agent = 'strategist' AND action LIKE ?
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


def count_approved_angles(product_id: int) -> int:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM story_angles WHERE product_id = ? AND status = 'approved'",
                (product_id,),
            ).fetchone()
        return int(row[0])
    except sqlite3.OperationalError:
        return 0