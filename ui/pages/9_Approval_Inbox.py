"""
ui/pages/9_Approval_Inbox.py
─────────────────────────────
Approval Inbox — two-decision content pipeline.

Section 1: Proposed story angles → Approve triggers auto-cascade
           (Copywriter → Editor → Media — all automatic)

Section 2: Generated drafts → Read full content inline, see Editor
           verdict, Approve to auto-schedule to next available slot

Two decisions per piece of content. Everything else is automatic.
"""

import json
import streamlit as st
from datetime import datetime, date, timedelta, timezone

from services.brand_context import get_active_product
from services.page_utils import init_page, format_cost_inr
from services.database import get_connection
from agents.copywriter import write_drafts_for_angle, update_draft_status
from agents.editor import review_draft
from agents.media import generate_media_brief
from agents.scheduler import schedule_draft


# ── Page init ─────────────────────────────────────────────────────────────

init_page("📥 Approval Inbox")

product = get_active_product()
if not product:
    st.error("No active product found. Set up Brand Brain first.")
    st.stop()

product_id = product["product_id"]
product_name = product["product_name"]


# ── Helper: fetch proposed angles ─────────────────────────────────────────

def _get_proposed_angles(pid: int) -> list[dict]:
    """Fetch story angles waiting for human review (status = proposed)."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, angle_title, title, angle_description,
                      editorial_brief, platform_fit, cta_strength,
                      content_format, theme
               FROM story_angles
               WHERE product_id = ? AND status = 'proposed'
               ORDER BY id DESC""",
            (pid,),
        ).fetchall()
    return [
        {
            "id":                r[0],
            "angle_title":       r[1] or r[2] or "Untitled",
            "angle_description": r[3] or "",
            "editorial_brief":   r[4] or "",
            "platform_fit":      r[5] or "both",
            "cta_strength":      r[6] or "no_cta",
            "content_format":    r[7] or "single_image",
            "theme":             r[8] or "",
        }
        for r in rows
    ]


# ── Helper: approve / reject angle ────────────────────────────────────────

def _set_angle_status(angle_id: int, status: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        conn.execute(
            "UPDATE story_angles SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, angle_id),
        )
        conn.commit()


# ── Helper: get draft IDs for an angle ────────────────────────────────────

def _get_draft_ids_for_angle(angle_id: int) -> list[int]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM drafts WHERE story_angle_id = ? ORDER BY id",
            (angle_id,),
        ).fetchall()
    return [r[0] for r in rows]


# ── Helper: fetch drafts needing human review ─────────────────────────────

def _get_reviewable_drafts(pid: int) -> list[dict]:
    """Drafts with status draft/edited — includes editor verdict if available."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT d.id, d.story_angle_id, d.platform, d.variant_number,
                      d.content_format, d.headline, d.body, d.cta_line,
                      d.hashtags, d.word_count, d.status,
                      d.visual_photography_note,
                      COALESCE(sa.angle_title, sa.title, 'Untitled')
               FROM drafts d
               LEFT JOIN story_angles sa ON sa.id = d.story_angle_id
               WHERE d.product_id = ? AND d.status IN ('draft', 'edited')
               ORDER BY d.story_angle_id, d.platform, d.variant_number""",
            (pid,),
        ).fetchall()

        drafts = []
        for r in rows:
            drafts.append({
                "id":                     r[0],
                "story_angle_id":         r[1],
                "platform":               r[2],
                "variant_number":         r[3],
                "content_format":         r[4],
                "headline":               r[5] or "",
                "body":                   r[6] or "",
                "cta_line":               r[7],
                "hashtags":               r[8],
                "word_count":             r[9] or 0,
                "status":                 r[10],
                "visual_photography_note": r[11],
                "angle_title":            r[12] or "Untitled",
            })

        # Attach editor review for each draft (latest only)
        for d in drafts:
            rev = conn.execute(
                """SELECT verdict, issues_json
                   FROM editor_reviews
                   WHERE draft_id = ?
                   ORDER BY review_number DESC LIMIT 1""",
                (d["id"],),
            ).fetchone()
            if rev:
                try:
                    issues = json.loads(rev[1]) if rev[1] else []
                except (json.JSONDecodeError, TypeError):
                    issues = []
                d["review"] = {"verdict": rev[0], "issues": issues}
            else:
                d["review"] = None

    return drafts


# ── Helper: find next available posting slot ──────────────────────────────

_POSTING_DAYS  = {0, 2, 4}          # Monday, Wednesday, Friday
_POSTING_TIMES = ["09:00", "18:00"]  # 9 AM and 6 PM IST


def _find_next_slot(pid: int) -> tuple[str, date, str]:
    """Return (iso_datetime, slot_date, time_str) for the next open slot.

    Walks forward from tomorrow through Mon/Wed/Fri at 9 AM then 6 PM,
    skipping slots already taken by a pending (unposted) schedule entry.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT s.scheduled_for
               FROM schedule s
               JOIN drafts d ON d.id = s.draft_id
               WHERE d.product_id = ? AND s.posted_at IS NULL""",
            (pid,),
        ).fetchall()

    taken = set()
    for r in rows:
        if r[0]:
            taken.add(r[0][:16])  # 'YYYY-MM-DDTHH:MM'

    today = date.today()
    check = today + timedelta(days=1)

    for _ in range(90):
        if check.weekday() in _POSTING_DAYS:
            for t in _POSTING_TIMES:
                slot_iso = f"{check.isoformat()}T{t}:00"
                if slot_iso[:16] not in taken:
                    return slot_iso, check, t
        check += timedelta(days=1)

    # Fallback — should never reach here
    fallback = today + timedelta(days=1)
    return f"{fallback.isoformat()}T09:00:00", fallback, "09:00"


def _format_slot_display(slot_date: date, slot_time: str) -> str:
    """'Monday Jul 07 at 9:00 AM IST'"""
    day_name = slot_date.strftime("%A")
    date_str = slot_date.strftime("%b %d")
    hour = int(slot_time.split(":")[0])
    if hour == 0:
        time_display = "12:00 AM"
    elif hour < 12:
        time_display = f"{hour}:00 AM"
    elif hour == 12:
        time_display = "12:00 PM"
    else:
        time_display = f"{hour - 12}:00 PM"
    return f"{day_name} {date_str} at {time_display} IST"


# ── Helper: platform display ─────────────────────────────────────────────

_PLATFORM_EMOJI = {
    "instagram": "📷",
    "facebook":  "📘",
    "linkedin":  "💼",
}

_PLATFORM_FIT_LABEL = {
    "both":      "📷 IG + 📘 FB",
    "instagram": "📷 Instagram",
    "facebook":  "📘 Facebook",
    "linkedin":  "💼 LinkedIn",
}


# ══════════════════════════════════════════════════════════════════════════
#  PAGE LAYOUT
# ══════════════════════════════════════════════════════════════════════════

st.title("📥 Approval Inbox")
st.caption(
    "Two decisions per piece of content. "
    "Approve an angle → drafts, editor review, and image prompts are generated automatically. "
    "Approve a draft → it is auto-scheduled to the next available slot."
)

# ── Show persistent messages from previous action ─────────────────────────

if st.session_state.get("inbox_message"):
    msg = st.session_state.inbox_message
    st.session_state.inbox_message = None
    st.success(msg)

# ── Fetch current data ────────────────────────────────────────────────────

proposed_angles   = _get_proposed_angles(product_id)
reviewable_drafts = _get_reviewable_drafts(product_id)

# ── Summary metrics ───────────────────────────────────────────────────────

col1, col2 = st.columns(2)
with col1:
    st.metric("Angles Waiting", len(proposed_angles))
with col2:
    st.metric("Drafts Waiting", len(reviewable_drafts))

st.divider()

# ══════════════════════════════════════════════════════════════════════════
#  SECTION 1 — Story Angles to Review
# ══════════════════════════════════════════════════════════════════════════

st.header("📐 Story Angles to Review")

if not proposed_angles:
    st.info(
        "No proposed angles waiting. "
        "Run Strategy first to generate new angles."
    )
else:
    for angle in proposed_angles:
        with st.container(border=True):
            st.subheader(angle["angle_title"])

            # Metadata line
            plat_label = _PLATFORM_FIT_LABEL.get(
                angle["platform_fit"], angle["platform_fit"]
            )
            meta_parts = [
                f"**Platform:** {plat_label}",
                f"**Format:** {angle['content_format']}",
                f"**CTA:** {angle['cta_strength']}",
            ]
            if angle["theme"]:
                meta_parts.append(f"**Theme:** {angle['theme']}")
            st.markdown(" · ".join(meta_parts))

            # Description
            if angle["angle_description"]:
                st.markdown(angle["angle_description"])

            # Editorial brief — expandable
            if angle["editorial_brief"]:
                with st.expander("📋 Editorial Brief"):
                    st.markdown(angle["editorial_brief"])

            # Action buttons
            btn_cols = st.columns([3, 2, 7])

            with btn_cols[0]:
                approve_clicked = st.button(
                    "✅ Approve & Generate",
                    key=f"approve_angle_{angle['id']}",
                    type="primary",
                )

            with btn_cols[1]:
                reject_clicked = st.button(
                    "❌ Reject",
                    key=f"reject_angle_{angle['id']}",
                )

            # ── Reject handler ────────────────────────────────────────
            if reject_clicked:
                _set_angle_status(angle["id"], "rejected")
                st.session_state.inbox_message = (
                    f"Angle rejected: {angle['angle_title']}"
                )
                st.rerun()

            # ── Approve + Cascade handler ─────────────────────────────
            if approve_clicked:
                total_cost = 0.0
                cascade_ok = True

                with st.status(
                    "🚀 Processing — generating drafts, reviewing, creating image prompts...",
                    expanded=True,
                ) as status:

                    # Step 1 — Approve the angle
                    st.write("✓ Approving angle...")
                    _set_angle_status(angle["id"], "approved")

                    # Step 2 — Generate drafts
                    st.write("✍️ Generating drafts (15–30 seconds)...")
                    draft_result = write_drafts_for_angle(angle["id"])
                    drafts_created = draft_result.get("drafts_created", 0)
                    total_cost += draft_result.get("est_cost_usd", 0.0)

                    if draft_result.get("error"):
                        status.update(
                            label="❌ Draft generation failed", state="error",
                        )
                        st.error(f"Copywriter error: {draft_result['error']}")
                        cascade_ok = False
                    else:
                        st.write(f"✓ Created {drafts_created} drafts")

                        # Step 3 — Editor review on each new draft
                        draft_ids = _get_draft_ids_for_angle(angle["id"])

                        if draft_ids:
                            st.write(
                                f"🔍 Running Editor review on "
                                f"{len(draft_ids)} drafts..."
                            )
                            clean_count   = 0
                            flagged_count = 0
                            for did in draft_ids:
                                rev = review_draft(did)
                                total_cost += rev.get("est_cost_usd", 0.0)
                                if rev.get("verdict") == "clean":
                                    clean_count += 1
                                elif rev.get("verdict") == "flagged":
                                    flagged_count += 1
                            st.write(
                                f"✓ Editor done — {clean_count} clean, "
                                f"{flagged_count} flagged"
                            )

                            # Step 4 — Media briefs (zero cost, instant)
                            st.write("📸 Creating image prompts...")
                            media_ok = 0
                            for did in draft_ids:
                                mres = generate_media_brief(did)
                                if mres.get("ok"):
                                    media_ok += 1
                            st.write(
                                f"✓ {media_ok} image prompts ready"
                            )

                        status.update(
                            label=(
                                f"✅ Done — {drafts_created} drafts ready "
                                f"for review ({format_cost_inr(total_cost)})"
                            ),
                            state="complete",
                        )

                if cascade_ok:
                    st.session_state.inbox_message = (
                        f"✅ '{angle['angle_title']}' processed — "
                        f"{drafts_created} drafts ready for review "
                        f"({format_cost_inr(total_cost)})"
                    )
                    st.rerun()


st.divider()

# ══════════════════════════════════════════════════════════════════════════
#  SECTION 2 — Drafts to Review
# ══════════════════════════════════════════════════════════════════════════

st.header("✍️ Drafts to Review")

if not reviewable_drafts:
    st.info(
        "No drafts waiting for review. "
        "Approve an angle above to generate drafts automatically."
    )
else:
    # Group drafts by angle for clean display
    angle_groups: dict[int, dict] = {}
    for draft in reviewable_drafts:
        aid = draft["story_angle_id"]
        if aid not in angle_groups:
            angle_groups[aid] = {
                "title":  draft["angle_title"],
                "drafts": [],
            }
        angle_groups[aid]["drafts"].append(draft)

    for aid, group in angle_groups.items():
        st.subheader(f"📐 {group['title']}")

        for draft in group["drafts"]:
            with st.container(border=True):
                # ── Header ────────────────────────────────────────────
                emoji = _PLATFORM_EMOJI.get(draft["platform"], "📄")
                st.markdown(
                    f"### {emoji} {draft['platform'].capitalize()} — "
                    f"Variant {draft['variant_number']}"
                )

                # ── Editor verdict ────────────────────────────────────
                review = draft.get("review")
                if review:
                    if review["verdict"] == "clean":
                        st.success("✅ Editor: Clean — no issues found")
                    else:
                        issue_count = len(review.get("issues", []))
                        hard_count = sum(
                            1 for i in review.get("issues", [])
                            if i.get("severity") == "hard"
                        )
                        soft_count = issue_count - hard_count
                        label_parts = []
                        if hard_count:
                            label_parts.append(f"{hard_count} hard")
                        if soft_count:
                            label_parts.append(f"{soft_count} soft")
                        st.warning(
                            f"⚠️ Editor: Flagged — "
                            f"{', '.join(label_parts)} issue(s)"
                        )
                        for issue in review.get("issues", []):
                            sev_icon = (
                                "🔴" if issue.get("severity") == "hard"
                                else "🟡"
                            )
                            st.markdown(
                                f"{sev_icon} **{issue.get('code', '?')}** "
                                f"({issue.get('field', '?')}): "
                                f"{issue.get('message', '')}"
                            )
                            if issue.get("evidence"):
                                st.caption(
                                    f"Evidence: {issue['evidence'][:200]}"
                                )
                else:
                    st.info("⏳ Not yet reviewed by Editor")

                # ── Full draft content ────────────────────────────────
                with st.expander("📄 Read Full Draft", expanded=True):
                    if draft["headline"]:
                        st.markdown(f"**Hook:** {draft['headline']}")

                    body = draft["body"]
                    if body:
                        # Handle escaped newlines from JSON storage
                        display_body = body.replace("\\n\\n", "\n\n")
                        display_body = display_body.replace("\\n", "\n")
                        st.markdown(display_body)

                    if draft["cta_line"]:
                        st.markdown(f"**CTA:** {draft['cta_line']}")

                    # Hashtags
                    try:
                        raw_tags = draft["hashtags"]
                        if isinstance(raw_tags, str):
                            tags = json.loads(raw_tags)
                        elif isinstance(raw_tags, list):
                            tags = raw_tags
                        else:
                            tags = []
                        if tags:
                            st.markdown(" ".join(tags))
                    except (json.JSONDecodeError, TypeError):
                        pass

                    st.caption(
                        f"📊 {draft['word_count']} words · "
                        f"{draft['content_format']}"
                    )

                # ── Action buttons ────────────────────────────────────
                btn_cols = st.columns([3, 2, 7])

                with btn_cols[0]:
                    approve_draft_clicked = st.button(
                        "✅ Approve & Schedule",
                        key=f"approve_draft_{draft['id']}",
                        type="primary",
                    )

                with btn_cols[1]:
                    reject_draft_clicked = st.button(
                        "❌ Reject",
                        key=f"reject_draft_{draft['id']}",
                    )

                # ── Reject draft handler ──────────────────────────────
                if reject_draft_clicked:
                    update_draft_status(draft["id"], "rejected")
                    st.session_state.inbox_message = (
                        f"Draft rejected: {draft['platform'].capitalize()} "
                        f"V{draft['variant_number']} "
                        f"— {draft['angle_title']}"
                    )
                    st.rerun()

                # ── Approve + auto-schedule handler ───────────────────
                if approve_draft_clicked:
                    # Step 1 — approve the draft
                    update_draft_status(draft["id"], "approved")

                    # Step 2 — find next available slot and schedule
                    slot_iso, slot_date, slot_time = _find_next_slot(
                        product_id
                    )
                    sched_result = schedule_draft(draft["id"], slot_iso)

                    if sched_result.get("ok"):
                        slot_display = _format_slot_display(
                            slot_date, slot_time,
                        )
                        st.session_state.inbox_message = (
                            f"📅 {draft['platform'].capitalize()} "
                            f"V{draft['variant_number']} approved and "
                            f"scheduled for {slot_display}"
                        )
                    else:
                        st.session_state.inbox_message = (
                            f"✅ Draft approved but scheduling failed: "
                            f"{sched_result.get('error', 'Unknown')}. "
                            f"Schedule manually from Calendar page."
                        )

                    st.rerun()


# ── Footer ────────────────────────────────────────────────────────────────

st.divider()
st.caption(
    "💡 Tip: Approve the variant you prefer and reject the other. "
    "Each angle produces 2 variants per platform — pick the stronger one."
)