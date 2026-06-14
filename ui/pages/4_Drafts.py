"""Drafts — review and manage AI-generated post drafts.

Two tabs only:
  1. Weekly Drafts  — week picker + platform filter, one clean view
  2. Generate       — draft generation from approved angles (unchanged)

Rules:
  - Posted drafts are invisible. They're done.
  - Rejected drafts are invisible. They're dead.
  - Navigate week by week to review, approve, and manage all content.
  - Platform dropdown filters to LinkedIn / Facebook / Instagram.
"""

import json
from datetime import datetime, timedelta, timezone

import streamlit as st
from services.page_utils import init_page

from agents.copywriter import (
    count_draft_stats,
    get_approved_angles,
    get_drafts_library,
    get_editor_review_status,
    update_draft_content,
    update_draft_status,
    write_drafts_for_all_approved,
    write_drafts_for_angle,
)
from services.brand_context import get_active_product

st.set_page_config(page_title="Drafts — Sportz-Well", page_icon="✍️")
init_page()
st.title("✍️ Drafts")

product = get_active_product()
if product is None:
    st.error("No active product found. Go to Brand Brain → Tab D to seed Sportz-Well / SWPI.")
    st.stop()

product_id = product["product_id"]


# ─── Constants ────────────────────────────────────────────────────────────────

PLATFORM_ORDER = ["linkedin", "facebook", "instagram"]

PLATFORM_LABEL = {
    "instagram": "📷 Instagram",
    "facebook":  "🔵 Facebook",
    "linkedin":  "💼 LinkedIn",
}

# Status badge HTML — inline coloured pill
STATUS_BADGE: dict[str, str] = {
    "scheduled": (
        '<span style="background:#14532d;color:#86efac;padding:2px 10px;'
        'border-radius:12px;font-size:0.75rem;font-weight:600;">📅 Scheduled</span>'
    ),
    "approved": (
        '<span style="background:#1e3a5f;color:#93c5fd;padding:2px 10px;'
        'border-radius:12px;font-size:0.75rem;font-weight:600;">✅ Approved</span>'
    ),
    "ready_to_approve": (
        '<span style="background:#14532d;color:#86efac;padding:2px 10px;'
        'border-radius:12px;font-size:0.75rem;font-weight:600;">🟢 Editor Clean</span>'
    ),
    "needs_fix": (
        '<span style="background:#7f1d1d;color:#fca5a5;padding:2px 10px;'
        'border-radius:12px;font-size:0.75rem;font-weight:600;">🚩 Needs Fix</span>'
    ),
    "not_reviewed": (
        '<span style="background:#1c1c3a;color:#a5b4fc;padding:2px 10px;'
        'border-radius:12px;font-size:0.75rem;font-weight:600;">⏳ Not Reviewed</span>'
    ),
}


# ─── Utility helpers ──────────────────────────────────────────────────────────

def _load_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _parse_dt(ts: str | None) -> datetime | None:
    """Parse stored timestamp string to UTC datetime."""
    if not ts:
        return None
    try:
        cleaned = ts[:19].replace("T", " ")
        return datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _week_start(dt: datetime) -> datetime:
    """Return Monday 00:00 UTC of the week containing dt."""
    return (dt - timedelta(days=dt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _week_label(monday: datetime) -> str:
    """Human-readable week label: Jun 8 – Jun 14, 2026"""
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        return f"{monday.strftime('%b %d')} – {sunday.strftime('%d, %Y')}"
    return f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}"


def _get_status(draft: dict, editor_status: str | None) -> str:
    """Derive a single display status string for a draft."""
    if draft.get("is_posted"):
        return "posted"       # invisible — caller must skip
    if draft["status"] == "rejected":
        return "rejected"     # invisible — caller must skip
    if draft["status"] == "approved":
        return "scheduled" if draft.get("is_scheduled") else "approved"
    # status is 'draft' or 'edited' — check editor
    if editor_status == "flagged":
        return "needs_fix"
    if editor_status == "clean":
        return "ready_to_approve"
    return "not_reviewed"


# ─── Content rendering ────────────────────────────────────────────────────────

def _render_body(body: str) -> None:
    body_html = (
        body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
    )
    st.markdown(
        f'<div style="background:#0d0d1a;border:1px solid #2a2a4a;border-radius:4px;'
        f'padding:12px 16px;color:#e8e8f0;font-family:Inter,sans-serif;font-size:0.9rem;'
        f'line-height:1.7;white-space:pre-wrap;margin-bottom:6px;">'
        f'{body_html}</div>',
        unsafe_allow_html=True,
    )


def _copyable_post_text(draft: dict) -> str:
    """Body + hashtags assembled for copy-paste (no CTA — CTA handled separately)."""
    parts: list[str] = []
    body = draft.get("body") or ""
    if body:
        parts.append(body)
    hashtags = _load_json(draft.get("hashtags"), [])
    if hashtags:
        parts.append(" ".join(hashtags))
    return "\n\n".join(parts)


def _render_inline_edit(draft: dict) -> None:
    draft_id = draft["id"]
    with st.form(key=f"edit_form_{draft_id}"):
        new_headline = st.text_input("Headline", value=draft.get("headline") or "")
        new_body     = st.text_area("Body", value=draft.get("body") or "", height=220)
        new_cta      = st.text_input(
            "CTA Line (leave blank for none)",
            value=draft.get("cta_line") or "",
        )
        s1, s2 = st.columns(2)
        with s1:
            save_clicked   = st.form_submit_button("Save", use_container_width=True)
        with s2:
            cancel_clicked = st.form_submit_button("Cancel", use_container_width=True)

    if save_clicked:
        update_draft_content(draft_id, new_headline, new_body, new_cta or None)
        st.session_state[f"editing_{draft_id}"] = False
        st.rerun()
    elif cancel_clicked:
        st.session_state[f"editing_{draft_id}"] = False
        st.rerun()


# ─── Weekly Draft Card ────────────────────────────────────────────────────────

def _render_weekly_card(draft: dict, status: str) -> None:
    """Single unified card for the weekly view. Adapts buttons to status."""
    draft_id    = draft["id"]
    platform    = draft["platform"]
    variant     = draft["variant_number"]
    headline    = draft.get("headline") or ""
    body        = draft.get("body") or ""
    cta_line    = draft.get("cta_line")
    hashtags    = _load_json(draft.get("hashtags"), [])
    word_count  = draft.get("word_count") or 0
    char_count  = draft.get("char_count") or 0
    angle_title = draft.get("angle_title") or "Untitled"

    edit_key = f"editing_{draft_id}"
    if edit_key not in st.session_state:
        st.session_state[edit_key] = False

    with st.container(border=True):

        # ── Header row: platform/variant | status badge | word count
        h_col, badge_col, meta_col = st.columns([4, 2, 1])
        with h_col:
            st.markdown(
                f"**{PLATFORM_LABEL.get(platform, platform)} — Variant {variant}**"
            )
            st.caption(f"Angle: {angle_title}")
        with badge_col:
            st.markdown(STATUS_BADGE.get(status, ""), unsafe_allow_html=True)
        with meta_col:
            st.caption(f"{word_count}w")

        # ── If editing, render edit form and return
        if st.session_state[edit_key]:
            _render_inline_edit(draft)
            return

        # ── Preview line (first ~120 chars of body, italic)
        preview = (body[:120] + "…") if len(body) > 120 else body
        st.markdown(f"_{preview}_")

        # ── Full draft in expander
        with st.expander("📖 Read full draft"):
            if headline:
                st.markdown(f"**{headline}**")
            _render_body(body)
            if cta_line and platform != "linkedin":
                st.markdown(f"_📢 {cta_line}_")
            if hashtags:
                st.markdown(" ".join(f"`{t}`" for t in hashtags))

            # Copy helpers
            if platform == "linkedin":
                with st.expander("📋 Copy — post body (no SWPI mention)"):
                    st.code(_copyable_post_text(draft), language=None)
                if cta_line:
                    with st.expander("💬 Copy — first comment (post immediately after publishing)"):
                        st.code(cta_line, language=None)
                st.caption(
                    "💼 LinkedIn rule: publish body first, "
                    "then immediately add first comment with SWPI link."
                )
            else:
                with st.expander("📋 Copy-ready text"):
                    full_text = _copyable_post_text(draft)
                    if cta_line:
                        full_text += f"\n\n{cta_line}"
                    st.code(full_text, language=None)

        # ── Action buttons — vary by status
        if status == "scheduled":
            # Already in calendar — just allow editing
            c1, _ = st.columns([1, 3])
            with c1:
                if st.button("✏️ Edit", key=f"edit_{draft_id}", use_container_width=True):
                    st.session_state[edit_key] = True
                    st.rerun()
            st.caption("📅 Scheduled in Calendar. Unschedule there before making changes.")

        elif status == "approved":
            # Approved but not yet scheduled
            c1, c2, _ = st.columns([1, 1, 2])
            with c1:
                if st.button("✏️ Edit", key=f"edit_{draft_id}", use_container_width=True):
                    st.session_state[edit_key] = True
                    st.rerun()
            with c2:
                if st.button("❌ Reject", key=f"reject_{draft_id}", use_container_width=True):
                    update_draft_status(draft_id, "rejected")
                    st.rerun()

        else:
            # needs_fix / ready_to_approve / not_reviewed — all need a decision
            if status == "needs_fix":
                st.caption("⚠️ Editor flagged issues. Fix before approving if they matter.")
            c1, c2, c3, _ = st.columns([1, 1, 1, 1])
            with c1:
                if st.button("✅ Approve", key=f"approve_{draft_id}", use_container_width=True):
                    update_draft_status(draft_id, "approved")
                    st.rerun()
            with c2:
                if st.button("❌ Reject", key=f"reject_{draft_id}", use_container_width=True):
                    update_draft_status(draft_id, "rejected")
                    st.rerun()
            with c3:
                if st.button("✏️ Edit", key=f"edit_{draft_id}", use_container_width=True):
                    st.session_state[edit_key] = True
                    st.rerun()


# ─── Load all data once ───────────────────────────────────────────────────────

all_drafts      = get_drafts_library(product_id)
editor_statuses = get_editor_review_status(product_id)


# ─── Tabs ─────────────────────────────────────────────────────────────────────

tab_weekly, tab_generate = st.tabs(["📅 Weekly Drafts", "⚙️ Generate"])


# ── TAB 1: Weekly Drafts ──────────────────────────────────────────────────────

with tab_weekly:

    # Build week options from draft creation dates
    week_map: dict[str, datetime] = {}   # label → monday datetime
    for d in all_drafts:
        dt = _parse_dt(d.get("created_at"))
        if dt:
            monday = _week_start(dt)
            label  = _week_label(monday)
            week_map[label] = monday

    if not week_map:
        st.info(
            "No drafts yet. Go to **Generate** tab to create your first batch.",
            icon="💡",
        )
    else:
        # Sort descending — most recent week first
        sorted_weeks = sorted(week_map.items(), key=lambda x: x[1], reverse=True)
        week_labels  = [lbl for lbl, _ in sorted_weeks]

        # Default: current week if it has drafts, otherwise most recent
        today_monday = _week_start(datetime.now(timezone.utc))
        today_label  = _week_label(today_monday)
        default_idx  = week_labels.index(today_label) if today_label in week_labels else 0

        # ── Two controls: week picker + platform filter
        ctrl_week, ctrl_platform = st.columns([2, 1])

        with ctrl_week:
            selected_label = st.selectbox(
                "Week",
                options=week_labels,
                index=default_idx,
                key="week_picker",
                label_visibility="visible",
            )
        with ctrl_platform:
            platform_filter = st.selectbox(
                "Platform",
                options=["All", "LinkedIn", "Facebook", "Instagram"],
                key="weekly_platform",
            )

        selected_monday = week_map[selected_label]
        selected_sunday = selected_monday + timedelta(days=6, hours=23, minutes=59, seconds=59)

        # ── Filter drafts: this week + platform + exclude posted/rejected
        week_drafts: list[tuple[dict, str]] = []
        for d in all_drafts:
            dt = _parse_dt(d.get("created_at"))
            if not dt:
                continue
            if not (selected_monday <= dt <= selected_sunday):
                continue
            if platform_filter != "All" and d["platform"] != platform_filter.lower():
                continue
            status = _get_status(d, editor_statuses.get(d["id"]))
            if status in ("posted", "rejected"):
                continue
            week_drafts.append((d, status))

        if not week_drafts:
            if platform_filter != "All":
                st.info(
                    f"No active {platform_filter} drafts for {selected_label}. "
                    "Try 'All' platforms or check another week.",
                    icon="🔍",
                )
            else:
                st.info(
                    f"No active drafts for {selected_label}. "
                    "All are either posted or rejected — or none were generated this week.",
                    icon="✅",
                )
        else:
            # ── Summary line
            counts: dict[str, int] = {}
            for _, s in week_drafts:
                counts[s] = counts.get(s, 0) + 1

            parts = []
            if counts.get("scheduled"):
                parts.append(f"📅 {counts['scheduled']} scheduled")
            if counts.get("approved"):
                parts.append(f"✅ {counts['approved']} approved")
            if counts.get("ready_to_approve"):
                parts.append(f"🟢 {counts['ready_to_approve']} editor clean")
            if counts.get("needs_fix"):
                parts.append(f"🚩 {counts['needs_fix']} need fixing")
            if counts.get("not_reviewed"):
                parts.append(f"⏳ {counts['not_reviewed']} not reviewed")

            st.caption(
                f"{len(week_drafts)} active draft{'s' if len(week_drafts) != 1 else ''} · "
                + " · ".join(parts)
                + " · Posted drafts hidden"
            )

            # ── Group by platform in order: LinkedIn → Facebook → Instagram
            grouped: dict[str, list[tuple[dict, str]]] = {}
            for d, s in week_drafts:
                grouped.setdefault(d["platform"], []).append((d, s))

            for platform in PLATFORM_ORDER:
                if platform not in grouped:
                    continue
                plat_list = grouped[platform]
                n         = len(plat_list)
                st.subheader(
                    f"{PLATFORM_LABEL.get(platform, platform)}  "
                    f"({n} draft{'s' if n != 1 else ''})"
                )
                for draft, status in plat_list:
                    _render_weekly_card(draft, status)
                st.divider()


# ── TAB 2: Generate ───────────────────────────────────────────────────────────

with tab_generate:
    st.subheader("Generate Drafts from Approved Angles")

    stats           = count_draft_stats(product_id)
    approved_angles = get_approved_angles(product_id)

    m1, m2, m3 = st.columns(3)
    m1.metric("Approved Angles",    stats["total_approved"])
    m2.metric("Already Drafted",    stats["drafted_angles"])
    m3.metric("Waiting for Drafts", stats["waiting"])

    st.info(
        "Each angle costs approximately ₹4–10 to draft "
        "(2 variants per target platform, single API call per angle)."
    )

    regenerate = st.checkbox("Regenerate — overwrite existing drafts", value=False)
    st.divider()

    col_all, col_single = st.columns([1, 2])

    with col_all:
        if st.button(
            "GENERATE ALL WAITING ANGLES",
            type="primary",
            use_container_width=True,
            disabled=(stats["waiting"] == 0 and not regenerate),
        ):
            target_count = stats["total_approved"] if regenerate else stats["waiting"]
            if target_count == 0:
                st.warning("No angles waiting. Tick 'Regenerate' to overwrite existing drafts.")
            else:
                with st.spinner(f"Drafting {target_count} angle(s)…"):
                    result = write_drafts_for_all_approved(product_id)
                if result["errors"]:
                    for err in result["errors"]:
                        st.error(err)
                if result["drafts_created"] > 0 or result["angles_processed"] > 0:
                    st.success(
                        f"Done — {result['drafts_created']} draft(s) created across "
                        f"{result['angles_processed']} angle(s). "
                        f"Cost: ₹{result['total_cost_usd'] * 95:.2f}"
                    )
                for w in result["warnings"]:
                    st.warning(w)
                st.rerun()

    with col_single:
        if not approved_angles:
            st.caption("No approved angles available yet.")
        else:
            angle_options = {
                a["id"]: f"[{a['id']}] {a['angle_title']}  ({a['platform_fit']})"
                for a in approved_angles
            }
            selected_id = st.selectbox(
                "Pick a single angle",
                options=list(angle_options.keys()),
                format_func=lambda x: angle_options[x],
                key="single_angle_select",
                label_visibility="collapsed",
            )
            if st.button("GENERATE DRAFTS FOR THIS ANGLE ONLY", use_container_width=True):
                with st.spinner("Drafting…"):
                    result = write_drafts_for_angle(selected_id, regenerate=regenerate)
                if result["error"]:
                    st.error(result["error"])
                elif result["drafts_created"] == 0:
                    msg = result["warnings"][0] if result["warnings"] else "No new drafts created."
                    st.info(msg)
                else:
                    st.success(
                        f"Created {result['drafts_created']} draft(s) for "
                        f"'{result['angle_title']}'. "
                        f"Cost: ₹{result['est_cost_usd'] * 95:.2f}"
                    )
                    for w in result["warnings"]:
                        st.warning(w)
                    st.rerun()