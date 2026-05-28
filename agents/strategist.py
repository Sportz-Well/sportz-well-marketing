"""Strategist agent — second agent in the pipeline.

Reads research_items from the DB, clusters them by theme, and proposes
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
    """Cluster research items into themes and propose story angles.

    Returns:
        {
            "themes_identified": int,
            "angles_proposed":   int,
            "est_cost_usd":      float,
            "angles":            list[dict],   # flat list across all themes
            "warnings":          list[str],
            "error":             str | None,
        }
    """
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

    # Validate angle structure and coerce enum fields
    themes = _validate_themes(themes)

    # Flatten angles for quota checks (mutates themes in-place)
    warnings += _enforce_vision_quota(themes, max_vision_hints)
    warnings += _enforce_sparing_quota(themes, sparing_pps, max_sparing_uses)

    # Cap total angles at max_angles
    themes, cap_warning = _cap_angles(themes, max_angles)
    if cap_warning:
        warnings.append(cap_warning)

    # Save to DB
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

Choose platform_fit based on the angle's content and audience:

- **instagram** — visual-first content, parent and player audience, emotional hooks, shorter punchy angles
- **facebook** — community content, slightly older academy parent audience, slightly more editorial
- **linkedin** — B2B professional content targeting academy directors, head coaches, and sports institution operators. Longer-form insights, methodology, management, and performance tracking topics. Use linkedin when the angle is about: coaching methodology, academy management, performance data, coach development, institutional decisions, or anything a decision-maker in a sports organisation would read.
- **both** — angles that work equally well on Instagram and Facebook (consumer-facing)

**LinkedIn guidance:** Aim for 2–3 LinkedIn angles per batch when the research supports it. LinkedIn angles must be genuinely B2B in nature — do not force consumer content onto LinkedIn. Good LinkedIn topics: structured player development frameworks, data-driven coaching decisions, academy operations, coach–parent communication systems, selection methodology.

## Hard Constraints — verify each before returning JSON

### CONSTRAINT 1: Vision-hint quota
At most {max_vision_hints} angle(s) in this batch may use phase_tag "phase_2_hint" or "phase_3_hint".
Before finalising your JSON: count phase_2_hint + phase_3_hint tags. If count > {max_vision_hints}, change the excess to "phase_1" or "evergreen" and add a warning.
Vision hints are subtle asides — never make them the headline. Never say "SWPI will soon..." or "coming soon."

### CONSTRAINT 2: Sparing proof points
Proof points labelled "Use sparingly" may appear in proof_points_used in at most {max_sparing_uses} angle(s) total.
If you exceed this limit, remove sparing proof points from the excess angles and add a warning.

### CONSTRAINT 3: Topics
Every angle MUST map to one or more of the brand's owned topics. No angle may touch any avoided topic.

### CONSTRAINT 4: CTA distribution (approximate, across the full batch)
- hard_cta (direct "book a demo" call to action): ~20% of total angles
- soft_cta (gentle product or demo mention): ~40% of total angles
- no_cta (pure trust-building content): ~40% of total angles
Do not force a CTA onto every angle — trust-building content is more valuable long-term.
LinkedIn angles with hard_cta should use professional invitation style, not consumer urgency.

### CONSTRAINT 5: Voice
Every angle_title, angle_description, and editorial_brief must reflect the brand voice: Expert, Structured, Purposeful. No hype, no celebrity drama, no generic fitness content, no superlatives.

### CONSTRAINT 6: LinkedIn content format
LinkedIn angles must use only "single_image" or "text_post" as content_format. Never assign "carousel" or "reel_script" to a LinkedIn angle.

## Output Format

Return ONLY the JSON object below. Do not wrap it in markdown code fences. Do not write any prose before or after the JSON.

{{
  "themes": [
    {{
      "theme_name": "concise label for this theme cluster",
      "angles": [
        {{
          "angle_title": "short punchy title, max 10 words",
          "angle_description": "2–3 sentences: what is this post about and what key insight does it share?",
          "editorial_brief": "1 paragraph for the Copywriter: what to say, tone notes, which proof points to use and how. For LinkedIn angles, note the B2B professional tone and decision-maker audience explicitly.",
          "platform_fit": "instagram" or "facebook" or "linkedin" or "both",
          "phase_tag": "phase_1" or "phase_2_hint" or "phase_3_hint" or "founder_credibility" or "evergreen",
          "funnel_stage": "awareness" or "consideration" or "demo_pitch",
          "content_format": "single_image" or "carousel" or "video_script" or "text_post" or "reel_script",
          "cta_strength": "hard_cta" or "soft_cta" or "no_cta",
          "source_research_ids": [<integer IDs of research items that inform this angle>],
          "proof_points_used": ["exact proof point string as listed in Brand Context above, or empty list if none fit naturally"]
        }}
      ]
    }}
  ],
  "warnings": ["list any quota enforcement actions taken, e.g. capped vision hints; empty array if no warnings"]
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
    lines.append("Include 2–3 LinkedIn-specific angles where the research supports B2B professional content.")
    if focus:
        lines.append(f"\nEditorial focus for this run: {focus.strip()}")
    else:
        lines.append("\nNo specific focus — draw on the full research library above.")

    return "\n".join(lines)


# ─── JSON parsing ─────────────────────────────────────────────────────────────

def _parse_strategist_json(text: str) -> dict[str, Any] | None:
    """Extract and parse the JSON blob from the model's response.

    Three extraction strategies tried in order, each with trailing-comma cleanup:
      1. Content captured inside a ```(json)? ... ``` block (non-greedy, handles
         prose before/after the fence and Windows CRLF line endings).
      2. Raw text after stripping fences with simple regexes (belt-and-braces).
      3. Substring from the first { to the last } in the full response.
    """
    original = text.strip()
    candidates: list[str] = []

    # Strategy 1: non-greedy capture inside code fence — most reliable
    fence_match = re.search(r"```(?:json)?\s*\r?\n?([\s\S]*?)\r?\n?```", original)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    # Strategy 2: strip opening/closing fences with simple regexes
    stripped = re.sub(r"^```(?:json)?\s*\r?\n?", "", original)
    stripped = re.sub(r"\r?\n?```\s*$", "", stripped).strip()
    if stripped and stripped not in candidates:
        candidates.append(stripped)

    # Strategy 3: first { to last } — catches prose before/after the JSON block
    first_brace = original.find("{")
    last_brace  = original.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        brace_extract = original[first_brace : last_brace + 1]
        if brace_extract not in candidates:
            candidates.append(brace_extract)

    for candidate in candidates:
        # Try with trailing-comma cleanup first (common model quirk)
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
    """Validate angle structure and coerce invalid enum values to safe defaults."""
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

            # LinkedIn format enforcement — carousel and reel_script not valid
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
    """Cap phase_2_hint + phase_3_hint angles. Returns list of warning strings."""
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
                        f"phase_tag from vision-hint to phase_1 (limit is {max_hints})."
                    )

    return warnings


def _enforce_sparing_quota(
    themes: list[dict],
    sparing_proof_points: list[str],
    max_uses: int,
) -> list[str]:
    """Cap angles using sparing proof points. Returns list of warning strings."""
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
    """Trim angles across themes to stay within max_angles. Returns (themes, warning|None)."""
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
    """Append the full raw model response to data/strategist_failed_responses.log."""
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
    """Return info about the most recent strategist API call for this product."""
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