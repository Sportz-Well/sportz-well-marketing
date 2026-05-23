"""
agents/media.py
───────────────
Media agent — takes a draft's image_brief and produces a structured
photography creative brief for the Sportz-Well content team.

Public API
──────────
    generate_media_brief(draft_id, force=False) -> dict
    generate_all_pending(product_id, force=False) -> dict
    get_media_library(product_id, status_filter=None, platform_filter=None) -> list[dict]
    update_brief_status(brief_id, status) -> None
    get_brief_for_draft(draft_id) -> dict | None
    count_media_stats(product_id) -> dict
    get_last_run_info() -> dict | None

Output schema (one brief per draft)
────────────────────────────────────
    {
      "shot_type":         str,   # close-up | mid-shot | wide | overhead | action
      "subject":           str,
      "setting":           str,
      "time_of_day":       str,
      "lighting_mood":     str,
      "props":             list[str],
      "composition_notes": str,
      "color_palette":     list[str],
      "wardrobe_notes":    str | None,
      "do_not":            list[str],
      "caption_sync_note": str
    }

Cost model (approximate)
────────────────────────
    ~$0.004–0.008 per brief (pure reasoning, no web search).
    Logged to api_log table and data/api_log.csv.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from json import JSONDecoder
from pathlib import Path
from typing import Any

from services.anthropic_client import ask_with_usage
from services.brand_context import build_brand_context_prompt
from services.database import get_connection

# ── Constants ──────────────────────────────────────────────────────────────
AGENT_NAME   = "media"
CSV_LOG_PATH = Path(__file__).parent.parent / "data" / "api_log.csv"

VALID_SHOT_TYPES = {"close-up", "mid-shot", "wide", "overhead", "action"}
VALID_STATUSES   = {"pending", "approved", "rejected"}

# Cost per token (claude-sonnet-4-6, May 2026)
COST_PER_INPUT_TOKEN  = 3.0  / 1_000_000   # $3 / 1M
COST_PER_OUTPUT_TOKEN = 15.0 / 1_000_000   # $15 / 1M

# Module-level cache for last run metadata (cleared on each new run)
_last_run_info: dict | None = None


# ── System prompt ──────────────────────────────────────────────────────────

def _build_system_prompt(product_id: int) -> str:
    brand_block = build_brand_context_prompt(product_id)
    return f"""You are the Creative Director for a premium Indian sports brand.
Your job is to translate a social media caption's image_brief into a precise,
actionable photography creative brief that a real photographer can execute on shoot day.

{brand_block}

OUTPUT RULES
────────────
1. Respond ONLY with a single valid JSON object — no prose, no markdown fences.
2. Every field is required except wardrobe_notes (may be null).
3. shot_type MUST be exactly one of: close-up | mid-shot | wide | overhead | action
4. props, color_palette, do_not MUST be JSON arrays (may be empty []).
5. Do NOT use double-quote characters inside string values.
   Use single quotes for dialogue. Use em-dash (—) for emphasis.
6. Output your final JSON once — no revisions, no commentary.

JSON SCHEMA
───────────
{{
  "shot_type":         "<close-up | mid-shot | wide | overhead | action>",
  "subject":           "<who or what is the primary subject in frame>",
  "setting":           "<specific location description — indoor/outdoor, surface, backdrop>",
  "time_of_day":       "<golden hour | blue hour | indoor studio | midday outdoor | overcast | etc.>",
  "lighting_mood":     "<soft natural | high contrast | dramatic | flat bright | moody | etc.>",
  "props":             ["<prop 1>", "<prop 2>"],
  "composition_notes": "<framing, rule-of-thirds, depth-of-field, camera angle, subject placement>",
  "color_palette":     ["<colour descriptor 1>", "<colour descriptor 2>"],
  "wardrobe_notes":    "<clothing and kit guidance — or null if not applicable>",
  "do_not":            ["<hard avoidance rule 1>", "<hard avoidance rule 2>"],
  "caption_sync_note": "<one sentence: how the visual should reinforce the caption hook>"
}}

BRAND PHOTOGRAPHY GUIDELINES
─────────────────────────────
- Authentic Indian sports environments preferred: maidans, nets, academies, school grounds.
- Real athletes and coaches over models — raw, disciplined energy over glamour.
- No stock-photo poses. Every shot should look documentary or editorial.
- Brand colours and product packaging should appear only when contextually natural.
- Avoid clichéd sports clichés: no fist-pumps-to-the-sky, no unrealistic slow-motion implied poses.
- do_not MUST include any brand or logo avoidance rules relevant to the brief.
"""


# ── Prompt builder ────────────────────────────────────────────────────────

def _build_user_prompt(draft: dict) -> str:
    angle_title = draft.get("angle_title") or draft.get("title") or "Untitled angle"
    platform    = draft.get("platform", "instagram").capitalize()
    headline    = draft.get("headline") or "(no headline)"
    body_snippet = (draft.get("body") or "")[:300]
    image_brief  = draft.get("image_brief") or "(no image brief provided)"

    return f"""Generate a photography creative brief for the following social media draft.

DRAFT CONTEXT
─────────────
Story angle : {angle_title}
Platform    : {platform}
Headline    : {headline}
Body snippet: {body_snippet}{"..." if len(draft.get("body","")) > 300 else ""}

IMAGE BRIEF (from Copywriter)
──────────────────────────────
{image_brief}

Expand this image_brief into a complete, shoot-ready photography creative brief
following the JSON schema exactly.
"""


# ── JSON parser (4-strategy, mirrors Editor / Copywriter) ─────────────────

def _parse_brief_response(raw: str) -> dict | None:
    """
    Strategy 1: direct json.loads
    Strategy 2: strip markdown fences then json.loads
    Strategy 3: remove trailing commas then json.loads
    Strategy 4: raw_decode — handles prose before/after JSON block
    """
    # Strategy 1
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Strategy 2
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Strategy 3
    no_trailing = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        return json.loads(no_trailing)
    except json.JSONDecodeError:
        pass

    # Strategy 4: find first { and raw_decode from there
    decoder = JSONDecoder()
    for match in re.finditer(r"\{", no_trailing):
        try:
            obj, _ = decoder.raw_decode(no_trailing, match.start())
            return obj
        except json.JSONDecodeError:
            continue

    return None


# ── Validation ────────────────────────────────────────────────────────────

def _validate_and_normalise(data: dict) -> tuple[bool, str, dict]:
    """
    Returns (ok, error_message, normalised_data).
    Coerces list fields; normalises shot_type to lowercase.
    """
    required = [
        "shot_type", "subject", "setting", "time_of_day",
        "lighting_mood", "composition_notes", "caption_sync_note",
    ]
    for field in required:
        if not data.get(field):
            return False, f"Missing required field: {field}", data

    # Normalise shot_type
    shot = str(data["shot_type"]).strip().lower()
    if shot not in VALID_SHOT_TYPES:
        # Accept partial matches
        for valid in VALID_SHOT_TYPES:
            if valid in shot or shot in valid:
                shot = valid
                break
        else:
            shot = "mid-shot"   # safe fallback
    data["shot_type"] = shot

    # Ensure list fields are lists
    for list_field in ("props", "color_palette", "do_not"):
        val = data.get(list_field, [])
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                val = [v.strip() for v in val.split(",") if v.strip()]
        data[list_field] = val if isinstance(val, list) else []

    # wardrobe_notes may be None/null
    if data.get("wardrobe_notes") == "null":
        data["wardrobe_notes"] = None

    return True, "", data


# ── DB helpers ────────────────────────────────────────────────────────────

def _get_draft_with_angle(draft_id: int, conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        """
        SELECT d.id, d.product_id, d.platform, d.content_format,
               d.headline, d.body, d.cta_line, d.image_brief, d.status,
               sa.angle_title, sa.angle_description, sa.editorial_brief
        FROM   drafts d
        JOIN   story_angles sa ON sa.id = d.story_angle_id
        WHERE  d.id = ?
        """,
        (draft_id,),
    ).fetchone()
    if not row:
        return None
    cols = [
        "id", "product_id", "platform", "content_format",
        "headline", "body", "cta_line", "image_brief", "status",
        "angle_title", "angle_description", "editorial_brief",
    ]
    return dict(zip(cols, row))


def _save_brief(conn: sqlite3.Connection, draft_id: int, product_id: int,
                data: dict, raw: str, input_tokens: int,
                output_tokens: int, cost: float) -> int:
    """
    Upsert a media brief (INSERT OR REPLACE).
    Returns the brief id.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO media_briefs (
            draft_id, product_id,
            shot_type, subject, setting, time_of_day, lighting_mood,
            props, composition_notes, color_palette, wardrobe_notes,
            do_not, caption_sync_note,
            raw_model_response, model_input_tokens, model_output_tokens, cost_usd,
            status, created_at, updated_at
        ) VALUES (
            ?, ?,  ?, ?, ?, ?, ?,  ?, ?, ?, ?,  ?, ?,  ?, ?, ?, ?,  'pending', ?, ?
        )
        ON CONFLICT(draft_id) DO UPDATE SET
            shot_type           = excluded.shot_type,
            subject             = excluded.subject,
            setting             = excluded.setting,
            time_of_day         = excluded.time_of_day,
            lighting_mood       = excluded.lighting_mood,
            props               = excluded.props,
            composition_notes   = excluded.composition_notes,
            color_palette       = excluded.color_palette,
            wardrobe_notes      = excluded.wardrobe_notes,
            do_not              = excluded.do_not,
            caption_sync_note   = excluded.caption_sync_note,
            raw_model_response  = excluded.raw_model_response,
            model_input_tokens  = excluded.model_input_tokens,
            model_output_tokens = excluded.model_output_tokens,
            cost_usd            = excluded.cost_usd,
            status              = 'pending',
            updated_at          = excluded.updated_at
        """,
        (
            draft_id, product_id,
            data["shot_type"], data["subject"], data["setting"],
            data["time_of_day"], data["lighting_mood"],
            json.dumps(data["props"]),
            data["composition_notes"],
            json.dumps(data["color_palette"]),
            data.get("wardrobe_notes"),
            json.dumps(data["do_not"]),
            data["caption_sync_note"],
            raw, input_tokens, output_tokens, cost,
            now, now,
        ),
    )
    row = conn.execute(
        "SELECT id FROM media_briefs WHERE draft_id = ?", (draft_id,)
    ).fetchone()
    return row[0] if row else -1


def _log_api_call(conn: sqlite3.Connection, action: str,
                  input_tokens: int, output_tokens: int, cost: float,
                  notes: str = "") -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO api_log
            (timestamp, agent, action, input_tokens, output_tokens,
             web_searches, est_cost_usd, notes)
        VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (now, AGENT_NAME, action, input_tokens, output_tokens, cost, notes),
    )
    # Mirror to CSV
    CSV_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not CSV_LOG_PATH.exists()
    with open(CSV_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow([
                "timestamp", "agent", "action",
                "input_tokens", "output_tokens", "web_searches",
                "est_cost_usd", "notes",
            ])
        w.writerow([
            now, AGENT_NAME, action,
            input_tokens, output_tokens, 0, round(cost, 6), notes,
        ])


# ── Core generation ───────────────────────────────────────────────────────

def generate_media_brief(draft_id: int, force: bool = False) -> dict:
    """
    Generate (or regenerate) a media creative brief for a single draft.

    Parameters
    ──────────
    draft_id : int
        Primary key of the draft.
    force : bool
        If False and a brief already exists, return the cached brief without
        calling the API.  If True, regenerate unconditionally.

    Returns
    ───────
    dict with keys: ok (bool), brief_id, draft_id, data (dict),
                    cost_usd, input_tokens, output_tokens,
                    error (str, only on failure)
    """
    global _last_run_info

    conn = get_connection()
    try:
        # Check for existing brief
        existing = conn.execute(
            "SELECT id FROM media_briefs WHERE draft_id = ?", (draft_id,)
        ).fetchone()
        if existing and not force:
            brief = get_brief_for_draft(draft_id)
            return {
                "ok": True,
                "brief_id": existing[0],
                "draft_id": draft_id,
                "data": brief,
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cached": True,
            }

        # Fetch draft + angle context
        draft = _get_draft_with_angle(draft_id, conn)
        if not draft:
            return {"ok": False, "draft_id": draft_id,
                    "error": f"Draft {draft_id} not found."}

        if not draft.get("image_brief"):
            return {"ok": False, "draft_id": draft_id,
                    "error": f"Draft {draft_id} has no image_brief — skipping."}

        product_id  = draft["product_id"]
        system_prompt = _build_system_prompt(product_id)
        user_prompt   = _build_user_prompt(draft)

        # Call the API
        result = ask_with_usage(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1024,
        )

        if result.get("error"):
            return {
                "ok": False,
                "draft_id": draft_id,
                "error": f"API error: {result['error']}",
                "cost_usd": 0.0,
            }

        response_text = result["text"]
        input_tokens  = result.get("input_tokens", 0)
        output_tokens = result.get("output_tokens", 0)
        cost          = (input_tokens * COST_PER_INPUT_TOKEN +
                         output_tokens * COST_PER_OUTPUT_TOKEN)

        # Parse
        parsed = _parse_brief_response(response_text)
        if parsed is None:
            _log_api_call(
                conn,
                action=f"draft_{draft_id}_PARSE_FAIL",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                notes="JSON parse failed — raw response logged",
            )
            conn.commit()
            return {
                "ok": False,
                "draft_id": draft_id,
                "error": "Could not parse model response as JSON.",
                "raw_response": response_text,
                "cost_usd": cost,
            }

        # Validate
        ok, err, normalised = _validate_and_normalise(parsed)
        if not ok:
            _log_api_call(
                conn,
                action=f"draft_{draft_id}_VALIDATION_FAIL",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                notes=f"Validation error: {err}",
            )
            conn.commit()
            return {
                "ok": False,
                "draft_id": draft_id,
                "error": err,
                "cost_usd": cost,
            }

        # Save
        brief_id = _save_brief(
            conn, draft_id, product_id, normalised,
            response_text, input_tokens, output_tokens, cost,
        )

        action_label = (
            draft.get("angle_title") or f"draft_{draft_id}"
        )[:80]
        _log_api_call(
            conn,
            action=f"brief: {action_label}",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        )
        conn.commit()

        _last_run_info = {
            "draft_id":      draft_id,
            "brief_id":      brief_id,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "cost_usd":      cost,
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        }

        return {
            "ok":            True,
            "brief_id":      brief_id,
            "draft_id":      draft_id,
            "data":          normalised,
            "cost_usd":      cost,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "cached":        False,
        }

    finally:
        conn.close()


def generate_all_pending(product_id: int, force: bool = False) -> dict:
    """
    Generate media briefs for all drafts that don't yet have one.
    If force=True, regenerates even existing briefs.

    Returns summary dict: generated, skipped_no_brief, cached, failed, total_cost_usd
    """
    conn = get_connection()
    try:
        if force:
            rows = conn.execute(
                "SELECT id FROM drafts WHERE product_id = ? ORDER BY id",
                (product_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT d.id
                FROM   drafts d
                LEFT   JOIN media_briefs mb ON mb.draft_id = d.id
                WHERE  d.product_id = ?
                AND    mb.id IS NULL
                ORDER  BY d.id
                """,
                (product_id,),
            ).fetchall()
    finally:
        conn.close()

    draft_ids = [r[0] for r in rows]
    results   = {
        "generated": 0, "cached": 0,
        "skipped_no_brief": 0, "failed": 0,
        "total_cost_usd": 0.0,
        "errors": [],
    }

    for did in draft_ids:
        res = generate_media_brief(did, force=force)
        if not res["ok"]:
            err_msg = res.get("error", "unknown error")
            if "no image_brief" in err_msg.lower():
                results["skipped_no_brief"] += 1
            else:
                results["failed"] += 1
                results["errors"].append(f"Draft {did}: {err_msg}")
        elif res.get("cached"):
            results["cached"] += 1
        else:
            results["generated"] += 1
            results["total_cost_usd"] += res.get("cost_usd", 0)

    return results


# ── Query helpers ─────────────────────────────────────────────────────────

def get_brief_for_draft(draft_id: int) -> dict | None:
    """Return the media brief dict for a given draft, or None if absent."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT mb.id, mb.draft_id, mb.product_id,
                   mb.shot_type, mb.subject, mb.setting,
                   mb.time_of_day, mb.lighting_mood, mb.props,
                   mb.composition_notes, mb.color_palette, mb.wardrobe_notes,
                   mb.do_not, mb.caption_sync_note,
                   mb.model_input_tokens, mb.model_output_tokens, mb.cost_usd,
                   mb.status, mb.created_at, mb.updated_at,
                   d.platform, d.headline, d.image_brief,
                   sa.angle_title
            FROM   media_briefs mb
            JOIN   drafts d       ON d.id  = mb.draft_id
            JOIN   story_angles sa ON sa.id = d.story_angle_id
            WHERE  mb.draft_id = ?
            """,
            (draft_id,),
        ).fetchone()
        if not row:
            return None
        cols = [
            "id", "draft_id", "product_id",
            "shot_type", "subject", "setting",
            "time_of_day", "lighting_mood", "props",
            "composition_notes", "color_palette", "wardrobe_notes",
            "do_not", "caption_sync_note",
            "model_input_tokens", "model_output_tokens", "cost_usd",
            "status", "created_at", "updated_at",
            "platform", "headline", "image_brief",
            "angle_title",
        ]
        d = dict(zip(cols, row))
        for list_col in ("props", "color_palette", "do_not"):
            try:
                d[list_col] = json.loads(d[list_col] or "[]")
            except Exception:
                d[list_col] = []
        return d
    finally:
        conn.close()


def get_media_library(
    product_id: int,
    status_filter: str | None = None,
    platform_filter: str | None = None,
) -> list[dict]:
    """
    Return all media briefs for a product, joined with draft + angle info.
    Optional filters: status_filter ('pending'|'approved'|'rejected'),
                      platform_filter ('instagram'|'facebook')
    """
    conn = get_connection()
    try:
        where = ["mb.product_id = ?"]
        params: list[Any] = [product_id]

        if status_filter and status_filter != "all":
            where.append("mb.status = ?")
            params.append(status_filter)
        if platform_filter and platform_filter != "all":
            where.append("d.platform = ?")
            params.append(platform_filter)

        sql = f"""
            SELECT mb.id, mb.draft_id,
                   mb.shot_type, mb.subject, mb.setting,
                   mb.time_of_day, mb.lighting_mood, mb.props,
                   mb.composition_notes, mb.color_palette, mb.wardrobe_notes,
                   mb.do_not, mb.caption_sync_note,
                   mb.model_input_tokens, mb.model_output_tokens, mb.cost_usd,
                   mb.status, mb.created_at, mb.updated_at,
                   d.platform, d.variant_number, d.headline, d.image_brief,
                   d.content_format, d.status AS draft_status,
                   sa.angle_title, sa.theme
            FROM   media_briefs mb
            JOIN   drafts d        ON d.id  = mb.draft_id
            JOIN   story_angles sa ON sa.id = d.story_angle_id
            WHERE  {" AND ".join(where)}
            ORDER  BY mb.created_at DESC
        """
        rows = conn.execute(sql, params).fetchall()
        cols = [
            "id", "draft_id",
            "shot_type", "subject", "setting",
            "time_of_day", "lighting_mood", "props",
            "composition_notes", "color_palette", "wardrobe_notes",
            "do_not", "caption_sync_note",
            "model_input_tokens", "model_output_tokens", "cost_usd",
            "status", "created_at", "updated_at",
            "platform", "variant_number", "headline", "image_brief",
            "content_format", "draft_status",
            "angle_title", "theme",
        ]
        results = []
        for row in rows:
            d = dict(zip(cols, row))
            for list_col in ("props", "color_palette", "do_not"):
                try:
                    d[list_col] = json.loads(d[list_col] or "[]")
                except Exception:
                    d[list_col] = []
            results.append(d)
        return results
    finally:
        conn.close()


def update_brief_status(brief_id: int, status: str) -> None:
    """Set status of a media brief. status must be pending|approved|rejected."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE media_briefs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, brief_id),
        )
        conn.commit()
    finally:
        conn.close()


def count_media_stats(product_id: int) -> dict:
    """
    Returns counts for the pipeline overview:
      total_drafts, drafts_with_brief, drafts_without_brief,
      briefs_pending, briefs_approved, briefs_rejected,
      drafts_no_image_brief  (drafts where image_brief IS NULL or empty)
    """
    conn = get_connection()
    try:
        total_drafts = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE product_id = ?", (product_id,)
        ).fetchone()[0]

        drafts_with_brief = conn.execute(
            """SELECT COUNT(DISTINCT draft_id) FROM media_briefs
               WHERE product_id = ?""",
            (product_id,),
        ).fetchone()[0]

        drafts_no_image_brief = conn.execute(
            """SELECT COUNT(*) FROM drafts
               WHERE product_id = ?
               AND (image_brief IS NULL OR TRIM(image_brief) = '')""",
            (product_id,),
        ).fetchone()[0]

        status_rows = conn.execute(
            """SELECT status, COUNT(*) FROM media_briefs
               WHERE product_id = ?
               GROUP BY status""",
            (product_id,),
        ).fetchall()
        status_counts = {r[0]: r[1] for r in status_rows}

        return {
            "total_drafts":          total_drafts,
            "drafts_with_brief":     drafts_with_brief,
            "drafts_without_brief":  total_drafts - drafts_with_brief,
            "drafts_no_image_brief": drafts_no_image_brief,
            "briefs_pending":        status_counts.get("pending", 0),
            "briefs_approved":       status_counts.get("approved", 0),
            "briefs_rejected":       status_counts.get("rejected", 0),
        }
    finally:
        conn.close()


def get_last_run_info() -> dict | None:
    """Return metadata from the last generate_media_brief call in this process."""
    return _last_run_info