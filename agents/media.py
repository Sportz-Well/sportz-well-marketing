"""
agents/media.py
───────────────
Media agent — generates three AI image generation prompts per draft
using a template function. Zero API cost.

Prompts are built from the draft's visual_photography_note (written by
the Copywriter) or image_brief as fallback. The template wraps the source
text with tool-specific style instructions and the correct platform aspect
ratio.

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

Cost
────
    Zero. Template-based — no API call.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from services.database import get_connection

AGENT_NAME     = "media"
VALID_STATUSES = {"pending", "approved", "rejected"}

# Platform-specific aspect ratios per tool
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

# Style suffix appended to source text for each tool
_TOOL_STYLE = {
    "firefly": (
        "Documentary photography style, authentic and unposed, "
        "no clearly identifiable faces, no logos, no text in frame."
    ),
    "chatgpt": (
        "Shot on 85mm lens, shallow depth of field, editorial documentary "
        "photography style, authentic and unposed, no clearly identifiable faces. "
        "No text, no logos."
    ),
    "gemini": (
        "Authentic and editorial atmosphere, no posed shots, "
        "no clearly identifiable faces, no logos, no text."
    ),
}

_last_run_info: dict | None = None


# ── Template prompt builder ────────────────────────────────────────────────

def _build_prompts_from_note(source_text: str, platform: str) -> dict:
    """
    Build three tool-specific image prompts from a source text.
    source_text is the visual_photography_note (preferred) or image_brief.
    Platform determines aspect ratio injected into each prompt.
    """
    ar   = _ASPECT_RATIOS.get(platform.lower(), _ASPECT_RATIOS["instagram"])
    text = source_text.strip()

    # Ensure source ends with sentence-ending punctuation before appending
    if text and text[-1] not in (".", "!", "?"):
        text += "."

    firefly = (
        f"{text} "
        f"{_TOOL_STYLE['firefly']} "
        f"In Firefly, set Content Type to Photo and aspect ratio to "
        f"{ar['firefly']} in Firefly settings."
    )

    chatgpt = (
        f"Photorealistic documentary photograph. {text} "
        f"{_TOOL_STYLE['chatgpt']} "
        f"In ChatGPT, click the image icon and select {ar['chatgpt']}."
    )

    gemini = (
        f"{text} "
        f"{_TOOL_STYLE['gemini']} "
        f"Generate as {ar['gemini']}."
    )

    return {"firefly": firefly, "chatgpt": chatgpt, "gemini": gemini}


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
                prompts: dict, source_text: str) -> int:
    """
    Insert or update a media brief. Legacy photography columns receive empty
    defaults so existing schema constraints are satisfied.
    input_tokens, output_tokens, and cost_usd are always 0 (no API call).
    """
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
            ?, 0, 0, 0.0,
            'pending', ?, ?
        )
        ON CONFLICT(draft_id) DO UPDATE SET
            firefly_prompt      = EXCLUDED.firefly_prompt,
            chatgpt_prompt      = EXCLUDED.chatgpt_prompt,
            gemini_prompt       = EXCLUDED.gemini_prompt,
            raw_model_response  = EXCLUDED.raw_model_response,
            model_input_tokens  = 0,
            model_output_tokens = 0,
            cost_usd            = 0.0,
            status              = 'pending',
            updated_at          = EXCLUDED.updated_at
        """,
        (
            draft_id, product_id,
            prompts["firefly"], prompts["chatgpt"], prompts["gemini"],
            source_text,
            now, now,
        ),
    )
    row = conn.execute(
        "SELECT id FROM media_briefs WHERE draft_id = ?", (draft_id,)
    ).fetchone()
    return row[0] if row else -1


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
    Uses template function — zero API cost, instant generation.
    Returns cached brief without regenerating if force=False and brief exists.
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
                "data": brief, "cost_usd": 0.0, "cached": True,
            }

        draft = _get_draft_with_angle(draft_id, conn)
        if not draft:
            return {"ok": False, "draft_id": draft_id,
                    "error": f"Draft {draft_id} not found."}

        visual_note = (draft.get("visual_photography_note") or "").strip()
        image_brief = (draft.get("image_brief") or "").strip()
        source_text = visual_note or image_brief

        if not source_text:
            return {
                "ok": False, "draft_id": draft_id,
                "error": (
                    f"Draft {draft_id} has no visual note or image brief — "
                    "add one before generating."
                ),
            }

        platform   = (draft.get("platform") or "instagram").lower()
        product_id = draft["product_id"]

        prompts  = _build_prompts_from_note(source_text, platform)
        brief_id = _save_brief(conn, draft_id, product_id, prompts, source_text)
        conn.commit()

        _last_run_info = {
            "draft_id":  draft_id,
            "brief_id":  brief_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "ok": True, "brief_id": brief_id, "draft_id": draft_id,
            "data": prompts, "cost_usd": 0.0, "cached": False,
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
            if "no visual note or image brief" in err.lower():
                results["skipped_no_source"] += 1
            else:
                results["failed"] += 1
                results["errors"].append(f"Draft {did}: {err}")
        elif res.get("cached"):
            results["cached"] += 1
        else:
            results["generated"] += 1

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
                   mb.cost_usd, mb.status, mb.created_at, mb.updated_at,
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
            "cost_usd", "status", "created_at", "updated_at",
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
                   mb.cost_usd, mb.status, mb.created_at, mb.updated_at,
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
            "cost_usd", "status", "created_at", "updated_at",
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