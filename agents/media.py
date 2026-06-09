"""
agents/media.py
───────────────
Media agent — generates three AI image generation prompts per draft:
Adobe Firefly, ChatGPT (DALL-E 3), and Google Gemini.

Visual Photography Note: an optional per-draft note added by the user
that supplements the copywriter's image_brief with specific creative
direction. The note takes priority over the image_brief when present.

Public API
──────────
    generate_media_brief(draft_id, force=False)   -> dict
    generate_all_pending(product_id, force=False)  -> dict
    save_visual_note(draft_id, note)               -> None
    get_visual_note(draft_id)                      -> str | None
    get_media_library(product_id, ...)             -> list[dict]
    update_brief_status(brief_id, status)          -> None
    get_brief_for_draft(draft_id)                  -> dict | None
    count_media_stats(product_id)                  -> dict
    get_last_run_info()                            -> dict | None

Output schema (three prompts per draft)
────────────────────────────────────────
    { "firefly": str, "chatgpt": str, "gemini": str }

Cost model
──────────
    ~$0.003–0.006 per brief (pure reasoning, no web search).
    Logged to api_log table and data/api_log.csv.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from json import JSONDecoder
from pathlib import Path
from typing import Any

from services.anthropic_client import ask_with_usage
from services.brand_context import build_brand_context_prompt
from services.database import get_connection

AGENT_NAME            = "media"
CSV_LOG_PATH          = Path(__file__).parent.parent / "data" / "api_log.csv"
VALID_STATUSES        = {"pending", "approved", "rejected"}
COST_PER_INPUT_TOKEN  = 3.0  / 1_000_000
COST_PER_OUTPUT_TOKEN = 15.0 / 1_000_000

# Platform-specific aspect ratios for each tool
_ASPECT_RATIOS = {
    "instagram": {
        "firefly": "4:5 (Portrait)",
        "chatgpt": "Tall",
        "gemini":  "Portrait",
    },
    "facebook": {
        "firefly": "1:1 (Square)",
        "chatgpt": "Square",
        "gemini":  "Square",
    },
    "linkedin": {
        "firefly": "16:9 (Widescreen)",
        "chatgpt": "Widescreen",
        "gemini":  "Landscape",
    },
}

_last_run_info: dict | None = None


# ── System prompt ──────────────────────────────────────────────────────────

def _build_system_prompt(product_id: int) -> str:
    brand_block = build_brand_context_prompt(product_id)
    return f"""You are an AI image prompt specialist for a sports and lifestyle brand.

Your job is to read a social media draft's context and image_brief, then generate
three ready-to-use image generation prompts: one each for Adobe Firefly,
ChatGPT (DALL-E 3), and Google Gemini.

{brand_block}

Use the brand context above to determine the correct visual world: appropriate
settings, subjects, style, and emotional register. Every prompt must feel native
to this brand — not generic.

If a VISUAL PHOTOGRAPHY NOTE is provided in the draft context, it takes priority
over the image brief and brand defaults. It is specific creative direction for
this exact post — honour it precisely.

UNIVERSAL VISUAL PRINCIPLES
─────────────────────────────
- Authentic and editorial style — never stock-photo, never posed glamour
- No clearly identifiable faces
- No brand logos, no product packaging, no text or numbers in frame
- Emotional tone must match the caption hook exactly
- Composition should feel documentary, not promotional

FIREFLY RULES (Adobe Firefly)
──────────────────────────────
- 2 sentences, plain English
- Sentence 1: subject, action, setting — drawn from brand context and brief
- Sentence 2: lighting mood, photography style, colour palette
- End with: 'No logos, no text. In Firefly, set Content Type to Photo and
  aspect ratio to [use the Firefly value from draft context].'

CHATGPT RULES (DALL-E 3 via ChatGPT)
──────────────────────────────────────
- 3-4 sentences starting with: 'Photorealistic documentary photograph of...'
- Include camera detail: 'shot on 85mm lens, shallow depth of field'
- Include lighting quality: golden hour / overcast / indoor / studio
- End with: 'No text, no logos. In ChatGPT, click the image icon and
  select [use the ChatGPT size from draft context].'

GEMINI RULES (Google Gemini)
─────────────────────────────
- 2-3 sentences, plain conversational English
- Describe as if briefing a photographer on location — scene and atmosphere
- Include the emotional feeling, not just the physical description
- End with: 'No text, no logos. Generate as [use the Gemini orientation
  from draft context].'

OUTPUT RULES
────────────
1. Respond ONLY with a single valid JSON object — no prose, no markdown fences.
2. All three fields required: firefly, chatgpt, gemini
3. Do NOT use double-quote characters inside string values. Use single quotes.
4. Output once — no revisions, no commentary after the JSON.

JSON SCHEMA
───────────
{{
  "firefly": "<Adobe Firefly prompt with aspect ratio instruction>",
  "chatgpt": "<ChatGPT DALL-E 3 prompt with size selection instruction>",
  "gemini":  "<Google Gemini prompt with orientation instruction>"
}}
"""


# ── User prompt builder ────────────────────────────────────────────────────

def _build_user_prompt(draft: dict) -> str:
    angle_title  = draft.get("angle_title") or "Untitled angle"
    platform     = (draft.get("platform") or "instagram").lower()
    headline     = draft.get("headline") or "(no headline)"
    body_snippet = (draft.get("body") or "")[:300]
    image_brief  = draft.get("image_brief") or "(no image brief provided)"
    visual_note  = (draft.get("visual_photography_note") or "").strip()

    ar = _ASPECT_RATIOS.get(platform, _ASPECT_RATIOS["instagram"])

    note_block = ""
    if visual_note:
        note_block = f"""
VISUAL PHOTOGRAPHY NOTE  \u2190 prioritise this over the image brief below
\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
{visual_note}
"""

    return f"""Generate three AI image generation prompts for the following social media draft.

DRAFT CONTEXT
\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
Story angle  : {angle_title}
Platform     : {platform.capitalize()}
Headline     : {headline}
Body snippet : {body_snippet}{"..." if len(draft.get("body", "")) > 300 else ""}

IMAGE BRIEF (from Copywriter)
\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
{image_brief}
{note_block}
ASPECT RATIOS FOR THIS DRAFT
\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
Firefly  : {ar['firefly']}
ChatGPT  : {ar['chatgpt']}
Gemini   : {ar['gemini']}

Generate three prompts following the JSON schema and the rules for each tool.
Use the exact aspect ratio values above in each prompt's closing instruction.
"""


# ── JSON parser (4-strategy) ───────────────────────────────────────────────

def _parse_brief_response(raw: str) -> dict | None:
    # Strategy 1 — direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Strategy 2 — strip markdown fences
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Strategy 3 — remove trailing commas
    no_trailing = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        return json.loads(no_trailing)
    except json.JSONDecodeError:
        pass

    # Strategy 4 — raw_decode from first {
    decoder = JSONDecoder()
    for match in re.finditer(r"\{", no_trailing):
        try:
            obj, _ = decoder.raw_decode(no_trailing, match.start())
            return obj
        except json.JSONDecodeError:
            continue

    return None


# ── Validation ─────────────────────────────────────────────────────────────

def _validate_and_normalise(data: dict) -> tuple[bool, str, dict]:
    for field in ("firefly", "chatgpt", "gemini"):
        if not data.get(field) or not str(data[field]).strip():
            return False, f"Missing required field: {field}", data
    return True, "", data


# ── DB helpers ─────────────────────────────────────────────────────────────

def _get_draft_with_angle(draft_id: int, conn) -> dict | None:
    row = conn.execute(
        """
        SELECT d.id, d.product_id, d.platform, d.content_format,
               d.headline, d.body, d.cta_line, d.image_brief, d.status,
               d.visual_photography_note,
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
        "visual_photography_note",
        "angle_title", "angle_description", "editorial_brief",
    ]
    return dict(zip(cols, row))


def _save_brief(conn, draft_id: int, product_id: int,
                data: dict, raw: str, input_tokens: int,
                output_tokens: int, cost: float) -> int:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO media_briefs (
            draft_id, product_id,
            shot_type, subject, setting, time_of_day, lighting_mood,
            props, composition_notes, color_palette, wardrobe_notes,
            do_not, caption_sync_note,
            firefly_prompt, chatgpt_prompt, gemini_prompt,
            raw_model_response, model_input_tokens, model_output_tokens, cost_usd,
            status, created_at, updated_at
        ) VALUES (
            ?, ?,
            'ai-prompt', '', '', '', '',
            '[]', '', '[]', NULL,
            '[]', '',
            ?, ?, ?,
            ?, ?, ?, ?,
            'pending', ?, ?
        )
        ON CONFLICT(draft_id) DO UPDATE SET
            firefly_prompt      = EXCLUDED.firefly_prompt,
            chatgpt_prompt      = EXCLUDED.chatgpt_prompt,
            gemini_prompt       = EXCLUDED.gemini_prompt,
            raw_model_response  = EXCLUDED.raw_model_response,
            model_input_tokens  = EXCLUDED.model_input_tokens,
            model_output_tokens = EXCLUDED.model_output_tokens,
            cost_usd            = EXCLUDED.cost_usd,
            status              = 'pending',
            updated_at          = EXCLUDED.updated_at
        """,
        (
            draft_id, product_id,
            data["firefly"], data["chatgpt"], data["gemini"],
            raw, input_tokens, output_tokens, cost,
            now, now,
        ),
    )
    row = conn.execute(
        "SELECT id FROM media_briefs WHERE draft_id = ?", (draft_id,)
    ).fetchone()
    return row[0] if row else -1


def _log_api_call(conn, action: str, input_tokens: int,
                  output_tokens: int, cost: float, notes: str = "") -> None:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO api_log
            (timestamp, agent, action, input_tokens, output_tokens,
             web_searches, est_cost_usd, notes)
        VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (now, AGENT_NAME, action, input_tokens, output_tokens, cost, notes),
    )
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


# ── Public: visual note ────────────────────────────────────────────────────

def save_visual_note(draft_id: int, note: str) -> None:
    """Save or update the visual photography note on a draft."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE drafts SET visual_photography_note = ? WHERE id = ?",
            (note.strip() if note else None, draft_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_visual_note(draft_id: int) -> str | None:
    """Return the visual photography note for a draft, or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT visual_photography_note FROM drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ── Core generation ────────────────────────────────────────────────────────

def generate_media_brief(draft_id: int, force: bool = False) -> dict:
    """
    Generate (or regenerate) AI image prompts for a single draft.
    Returns cached brief without API call if one exists and force=False.
    """
    global _last_run_info

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM media_briefs WHERE draft_id = ?", (draft_id,)
        ).fetchone()
        if existing and not force:
            brief = get_brief_for_draft(draft_id)
            return {
                "ok": True, "brief_id": existing[0], "draft_id": draft_id,
                "data": brief, "cost_usd": 0.0,
                "input_tokens": 0, "output_tokens": 0, "cached": True,
            }

        draft = _get_draft_with_angle(draft_id, conn)
        if not draft:
            return {"ok": False, "draft_id": draft_id,
                    "error": f"Draft {draft_id} not found."}

        has_image_brief = bool((draft.get("image_brief") or "").strip())
        has_visual_note = bool((draft.get("visual_photography_note") or "").strip())

        if not has_image_brief and not has_visual_note:
            return {
                "ok": False, "draft_id": draft_id,
                "error": (
                    f"Draft {draft_id} has no image_brief or visual note — "
                    "add one before generating."
                ),
            }

        product_id    = draft["product_id"]
        system_prompt = _build_system_prompt(product_id)
        user_prompt   = _build_user_prompt(draft)

        result = ask_with_usage(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1200,
        )

        if result.get("error"):
            return {"ok": False, "draft_id": draft_id,
                    "error": f"API error: {result['error']}", "cost_usd": 0.0}

        response_text = result["text"]
        input_tokens  = result.get("input_tokens", 0)
        output_tokens = result.get("output_tokens", 0)
        cost = (input_tokens * COST_PER_INPUT_TOKEN +
                output_tokens * COST_PER_OUTPUT_TOKEN)

        parsed = _parse_brief_response(response_text)
        if parsed is None:
            _log_api_call(conn, f"draft_{draft_id}_PARSE_FAIL",
                          input_tokens, output_tokens, cost, "JSON parse failed")
            conn.commit()
            return {
                "ok": False, "draft_id": draft_id,
                "error": "Could not parse model response as JSON.",
                "raw_response": response_text, "cost_usd": cost,
            }

        ok, err, normalised = _validate_and_normalise(parsed)
        if not ok:
            _log_api_call(conn, f"draft_{draft_id}_VALIDATION_FAIL",
                          input_tokens, output_tokens, cost, f"Validation: {err}")
            conn.commit()
            return {"ok": False, "draft_id": draft_id,
                    "error": err, "cost_usd": cost}

        brief_id = _save_brief(conn, draft_id, product_id, normalised,
                               response_text, input_tokens, output_tokens, cost)

        action_label = (draft.get("angle_title") or f"draft_{draft_id}")[:80]
        _log_api_call(conn, f"prompts: {action_label}",
                      input_tokens, output_tokens, cost)
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
            "ok": True, "brief_id": brief_id, "draft_id": draft_id,
            "data": normalised, "cost_usd": cost,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cached": False,
        }

    finally:
        conn.close()


def generate_all_pending(product_id: int, force: bool = False) -> dict:
    """
    Generate prompts for all drafts without a brief.
    If force=True, regenerates existing briefs too.
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
                WHERE  d.product_id = ? AND mb.id IS NULL
                ORDER  BY d.id
                """,
                (product_id,),
            ).fetchall()
    finally:
        conn.close()

    results = {
        "generated": 0, "cached": 0, "skipped_no_source": 0,
        "failed": 0, "total_cost_usd": 0.0, "errors": [],
    }

    for (did,) in rows:
        res = generate_media_brief(did, force=force)
        if not res["ok"]:
            err = res.get("error", "unknown error")
            if "no image_brief or visual note" in err.lower():
                results["skipped_no_source"] += 1
            else:
                results["failed"] += 1
                results["errors"].append(f"Draft {did}: {err}")
        elif res.get("cached"):
            results["cached"] += 1
        else:
            results["generated"] += 1
            results["total_cost_usd"] += res.get("cost_usd", 0)

    return results


# ── Query helpers ──────────────────────────────────────────────────────────

def get_brief_for_draft(draft_id: int) -> dict | None:
    """Return the brief dict for a given draft, or None if absent."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT mb.id, mb.draft_id, mb.product_id,
                   mb.firefly_prompt, mb.chatgpt_prompt, mb.gemini_prompt,
                   mb.model_input_tokens, mb.model_output_tokens, mb.cost_usd,
                   mb.status, mb.created_at, mb.updated_at,
                   d.platform, d.headline, d.image_brief,
                   d.visual_photography_note,
                   sa.angle_title
            FROM   media_briefs mb
            JOIN   drafts d        ON d.id  = mb.draft_id
            JOIN   story_angles sa ON sa.id = d.story_angle_id
            WHERE  mb.draft_id = ?
            """,
            (draft_id,),
        ).fetchone()
        if not row:
            return None
        cols = [
            "id", "draft_id", "product_id",
            "firefly_prompt", "chatgpt_prompt", "gemini_prompt",
            "model_input_tokens", "model_output_tokens", "cost_usd",
            "status", "created_at", "updated_at",
            "platform", "headline", "image_brief",
            "visual_photography_note",
            "angle_title",
        ]
        return dict(zip(cols, row))
    finally:
        conn.close()


def get_media_library(
    product_id: int,
    status_filter: str | None = None,
    platform_filter: str | None = None,
) -> list[dict]:
    """Return all media briefs joined with draft and angle info."""
    conn = get_connection()
    try:
        where: list[str] = ["mb.product_id = ?"]
        params: list[Any] = [product_id]

        if status_filter and status_filter != "all":
            where.append("mb.status = ?")
            params.append(status_filter)
        if platform_filter and platform_filter != "all":
            where.append("d.platform = ?")
            params.append(platform_filter)

        sql = f"""
            SELECT mb.id, mb.draft_id,
                   mb.firefly_prompt, mb.chatgpt_prompt, mb.gemini_prompt,
                   mb.model_input_tokens, mb.model_output_tokens, mb.cost_usd,
                   mb.status, mb.created_at, mb.updated_at,
                   d.platform, d.variant_number, d.headline, d.image_brief,
                   d.content_format, d.status AS draft_status,
                   d.visual_photography_note,
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
            "firefly_prompt", "chatgpt_prompt", "gemini_prompt",
            "model_input_tokens", "model_output_tokens", "cost_usd",
            "status", "created_at", "updated_at",
            "platform", "variant_number", "headline", "image_brief",
            "content_format", "draft_status",
            "visual_photography_note",
            "angle_title", "theme",
        ]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def update_brief_status(brief_id: int, status: str) -> None:
    """Set brief status: pending | approved | rejected."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
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
    """Return coverage and status counts for the pipeline overview."""
    conn = get_connection()
    try:
        total_drafts = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE product_id = ?", (product_id,)
        ).fetchone()[0]

        drafts_with_brief = conn.execute(
            "SELECT COUNT(DISTINCT draft_id) FROM media_briefs WHERE product_id = ?",
            (product_id,),
        ).fetchone()[0]

        drafts_no_source = conn.execute(
            """
            SELECT COUNT(*) FROM drafts
            WHERE  product_id = ?
            AND    (image_brief IS NULL OR TRIM(image_brief) = '')
            AND    (visual_photography_note IS NULL
                    OR TRIM(visual_photography_note) = '')
            """,
            (product_id,),
        ).fetchone()[0]

        status_rows = conn.execute(
            "SELECT status, COUNT(*) FROM media_briefs WHERE product_id = ? GROUP BY status",
            (product_id,),
        ).fetchall()
        status_counts = {r[0]: r[1] for r in status_rows}

        return {
            "total_drafts":         total_drafts,
            "drafts_with_brief":    drafts_with_brief,
            "drafts_without_brief": total_drafts - drafts_with_brief,
            "drafts_no_source":     drafts_no_source,
            "briefs_pending":       status_counts.get("pending",  0),
            "briefs_approved":      status_counts.get("approved", 0),
            "briefs_rejected":      status_counts.get("rejected", 0),
        }
    finally:
        conn.close()


def get_last_run_info() -> dict | None:
    return _last_run_info