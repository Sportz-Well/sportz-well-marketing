"""Drafts — review and manage AI-generated post drafts."""

import json
from datetime import datetime, timezone

import streamlit as st
from services.page_utils import init_page

from agents.copywriter import (
    count_draft_stats,
    delete_draft_permanently,
    get_angle_draft_coverage,
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


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _format_ts(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        cleaned = ts[:19].replace("T", " ")
        dt      = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
        day     = str(dt.day)
        month   = dt.strftime("%b %Y")
        hour    = dt.hour % 12 or 12
        mins    = dt.strftime("%M")
        ampm    = "am" if dt.hour < 12 else "pm"
        return f"{day} {month}, {hour}:{mins} {ampm}"
    except Exception:
        return ts[:16]


def _days_since(ts: str | None) -> int:
    if not ts:
        return 0
    try:
        cleaned = ts[:19].replace("T", " ")
        dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return 0


def _age_badge_html(created_at: str | None, is_scheduled: bool) -> str:
    """Returns an inline HTML badge for draft age or schedule state."""
    if is_scheduled:
        return (
            '<span style="background:#14532d;color:#86efac;padding:2px 10px;'
            'border-radius:12px;font-size:0.75rem;font-weight:600;">📅 Scheduled</span>'
        )
    days = _days_since(created_at)
    if days >= 14:
        return (
            f'<span style="background:#b45309;color:#fef3c7;padding:2px 10px;'
            f'border-radius:12px;font-size:0.75rem;font-weight:600;">⚠️ {days}d old</span>'
        )
    if days >= 7:
        return (
            f'<span style="background:#78350f;color:#fef9c3;padding:2px 10px;'
            f'border-radius:12px;font-size:0.75rem;">📆 {days}d old</span>'
        )
    return (
        f'<span style="background:#1e3a5f;color:#93c5fd;padding:2px 10px;'
        f'border-radius:12px;font-size:0.75rem;">{days}d old</span>'
    )


def _editor_badge_html(status: str | None) -> str:
    if status == "clean":
        return (
            '<span style="background:#14532d;color:#86efac;padding:2px 8px;'
            'border-radius:10px;font-size:0.75rem;">✅ Editor Clean</span>'
        )
    if status == "flagged":
        return (
            '<span style="background:#7f1d1d;color:#fca5a5;padding:2px 8px;'
            'border-radius:10px;font-size:0.75rem;">🚩 Editor Flagged</span>'
        )
    return (
        '<span style="background:#1c1c3a;color:#a5b4fc;padding:2px 8px;'
        'border-radius:10px;font-size:0.75rem;">⏳ Not Reviewed</span>'
    )


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


# ─── Card Renderers ───────────────────────────────────────────────────────────

def _render_ready_card(draft: dict) -> None:
    """Card for Ready to Post tab. Shows full content + copy helpers + age badge."""
    draft_id     = draft["id"]
    platform     = draft["platform"]
    variant      = draft["variant_number"]
    headline     = draft.get("headline") or ""
    body         = draft.get("body") or ""
    cta_line     = draft.get("cta_line")
    hashtags     = _load_json(draft.get("hashtags"), [])
    word_count   = draft.get("word_count") or 0
    char_count   = draft.get("char_count") or 0
    created_at   = draft.get("created_at")
    angle_title  = draft.get("angle_title") or "Untitled"
    is_scheduled = bool(draft.get("is_scheduled", 0))

    edit_key = f"editing_{draft_id}"
    if edit_key not in st.session_state:
        st.session_state[edit_key] = False

    with st.container(border=True):
        # ── Header
        h_col, badge_col, meta_col = st.columns([3, 1, 1])
        with h_col:
            st.markdown(
                f"**{PLATFORM_LABEL.get(platform, platform)} — Variant {variant}**"
            )
            st.caption(f"Angle: {angle_title}")
        with badge_col:
            st.markdown(
                _age_badge_html(created_at, is_scheduled),
                unsafe_allow_html=True,
            )
        with meta_col:
            st.caption(f"{word_count}w / {char_count}c")

        if st.session_state[edit_key]:
            _render_inline_edit(draft)
            return

        # ── Content
        if headline:
            st.markdown(f"**{headline}**")

        _render_body(body)

        if cta_line and platform != "linkedin":
            st.markdown(f"_📢 {cta_line}_")
        if hashtags:
            st.markdown(" ".join(f"`{t}`" for t in hashtags))

        # ── Copy helpers
        if platform == "linkedin":
            with st.expander("📋 Copy — post body (no SWPI mention)"):
                st.code(_copyable_post_text(draft), language=None)
            if cta_line:
                with st.expander("💬 Copy — first comment (post immediately after publishing)"):
                    st.code(cta_line, language=None)
            st.caption(
                "💼 LinkedIn rule: publish body first, then immediately post "
                "the first comment containing the SWPI mention."
            )
        else:
            with st.expander("📋 Copy-ready text"):
                full_text = _copyable_post_text(draft)
                if cta_line:
                    full_text += f"\n\n{cta_line}"
                st.code(full_text, language=None)

        # ── Actions
        if is_scheduled:
            st.caption("📅 Scheduled — unschedule in Calendar before archiving.")
            edit_col, _ = st.columns([1, 3])
            with edit_col:
                if st.button("✏️ Edit", key=f"edit_rtp_{draft_id}", use_container_width=True):
                    st.session_state[edit_key] = True
                    st.rerun()
        else:
            b1, b2, _ = st.columns([1, 1, 2])
            with b1:
                if st.button("✏️ Edit", key=f"edit_rtp_{draft_id}", use_container_width=True):
                    st.session_state[edit_key] = True
                    st.rerun()
            with b2:
                if st.button("📦 Archive", key=f"archive_rtp_{draft_id}", use_container_width=True):
                    update_draft_status(draft_id, "rejected")
                    st.rerun()


def _render_review_card(draft: dict, editor_status: str | None) -> None:
    """Card for Review Queue tab. Has Approve / Reject / Edit buttons."""
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
        # ── Header
        h_col, badge_col, meta_col = st.columns([3, 1, 1])
        with h_col:
            st.markdown(
                f"**{PLATFORM_LABEL.get(platform, platform)} — Variant {variant}**"
            )
            st.caption(f"Angle: {angle_title}")
        with badge_col:
            st.markdown(_editor_badge_html(editor_status), unsafe_allow_html=True)
        with meta_col:
            st.caption(f"{word_count}w / {char_count}c")

        if st.session_state[edit_key]:
            _render_inline_edit(draft)
            return

        # ── Content
        if headline:
            st.markdown(f"**{headline}**")
        _render_body(body)
        if cta_line:
            st.markdown(f"_📢 {cta_line}_")
        if hashtags:
            st.markdown(" ".join(f"`{t}`" for t in hashtags))

        # ── Actions
        b1, b2, b3, _ = st.columns([1, 1, 1, 1])
        with b1:
            if st.button("✅ Approve", key=f"approve_rq_{draft_id}", use_container_width=True):
                update_draft_status(draft_id, "approved")
                st.rerun()
        with b2:
            if st.button("❌ Reject", key=f"reject_rq_{draft_id}", use_container_width=True):
                update_draft_status(draft_id, "rejected")
                st.rerun()
        with b3:
            if st.button("✏️ Edit", key=f"edit_rq_{draft_id}", use_container_width=True):
                st.session_state[edit_key] = True
                st.rerun()


def _render_posted_card(draft: dict) -> None:
    """Read-only card for posted drafts in Archive."""
    platform    = draft["platform"]
    variant     = draft["variant_number"]
    headline    = draft.get("headline") or ""
    body        = draft.get("body") or ""
    angle_title = draft.get("angle_title") or "Untitled"
    word_count  = draft.get("word_count") or 0

    with st.container(border=True):
        h_col, meta_col = st.columns([4, 1])
        with h_col:
            st.markdown(
                f"**{PLATFORM_LABEL.get(platform, platform)} — Variant {variant}** &nbsp; "
                f'<span style="color:#86efac;font-size:0.85rem;">✅ Posted</span>',
                unsafe_allow_html=True,
            )
            st.caption(f"Angle: {angle_title}")
        with meta_col:
            st.caption(f"{word_count}w")

        if headline:
            st.markdown(f"**{headline}**")
        with st.expander("View post"):
            _render_body(body)


def _render_rejected_card(draft: dict) -> None:
    """Card for rejected drafts. Restore puts it back to Review Queue. Delete is permanent."""
    draft_id    = draft["id"]
    platform    = draft["platform"]
    variant     = draft["variant_number"]
    headline    = draft.get("headline") or ""
    body        = draft.get("body") or ""
    angle_title = draft.get("angle_title") or "Untitled"
    word_count  = draft.get("word_count") or 0

    confirm_key = f"confirm_delete_{draft_id}"
    if confirm_key not in st.session_state:
        st.session_state[confirm_key] = False

    with st.container(border=True):
        h_col, meta_col = st.columns([4, 1])
        with h_col:
            st.markdown(
                f"**{PLATFORM_LABEL.get(platform, platform)} — Variant {variant}** &nbsp; "
                f'<span style="color:#fca5a5;font-size:0.85rem;">❌ Rejected</span>',
                unsafe_allow_html=True,
            )
            st.caption(f"Angle: {angle_title}")
        with meta_col:
            st.caption(f"{word_count}w")

        if headline:
            st.markdown(f"**{headline}**")
        with st.expander("View post"):
            _render_body(body)

        if not st.session_state[confirm_key]:
            b1, b2, _ = st.columns([1, 1, 2])
            with b1:
                if st.button("↩️ Restore", key=f"restore_{draft_id}", use_container_width=True):
                    update_draft_status(draft_id, "draft")
                    st.rerun()
            with b2:
                if st.button("🗑️ Delete", key=f"del_btn_{draft_id}", use_container_width=True):
                    st.session_state[confirm_key] = True
                    st.rerun()
        else:
            st.warning("⚠️ Permanently delete this draft? This cannot be undone.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button(
                    "Confirm Delete",
                    key=f"confirm_del_{draft_id}",
                    type="primary",
                    use_container_width=True,
                ):
                    delete_draft_permanently(draft_id)
                    st.session_state[confirm_key] = False
                    st.rerun()
            with c2:
                if st.button("Cancel", key=f"cancel_del_{draft_id}", use_container_width=True):
                    st.session_state[confirm_key] = False
                    st.rerun()


# ─── Page-level data load (single query, all tabs filter from this) ────────────

all_drafts      = get_drafts_library(product_id)
editor_statuses = get_editor_review_status(product_id)

# Filtered views — derived in Python, no extra DB calls
ready_drafts    = [
    d for d in all_drafts
    if d["status"] in ("approved", "edited") and not d.get("is_posted", 0)
]
review_drafts   = [d for d in all_drafts if d["status"] in ("draft", "edited")]
posted_drafts   = [
    d for d in all_drafts
    if d["status"] in ("approved", "edited") and d.get("is_posted", 0)
]
rejected_drafts = [d for d in all_drafts if d["status"] == "rejected"]

# NOTE: 'edited' drafts appear in both ready_drafts (if approved cycle completed) and
# review_drafts. To avoid double-listing, only show 'edited' in Review Queue.
# Ready to Post = approved + not posted.
ready_drafts = [
    d for d in all_drafts
    if d["status"] == "approved" and not d.get("is_posted", 0)
]


# ─── Tabs ─────────────────────────────────────────────────────────────────────

tab_ready, tab_generate, tab_review, tab_archive, tab_pipeline = st.tabs([
    "✅ Ready to Post",
    "⚙️ Generate",
    "🔍 Review Queue",
    "📦 Archive",
    "📊 Pipeline",
])


# ── TAB 1: Ready to Post ──────────────────────────────────────────────────────

with tab_ready:
    if not ready_drafts:
        st.info(
            "No approved drafts waiting to post.\n\n"
            "Go to **Review Queue** to approve generated drafts, "
            "or **Generate** to create new ones."
        )
    else:
        # Platform counts header
        plat_counts: dict[str, int] = {}
        for d in ready_drafts:
            plat_counts[d["platform"]] = plat_counts.get(d["platform"], 0) + 1

        count_cols = st.columns(max(len(plat_counts), 1))
        ordered_platforms = [p for p in PLATFORM_ORDER if p in plat_counts]
        for i, plat in enumerate(ordered_platforms):
            count_cols[i].metric(PLATFORM_LABEL.get(plat, plat), plat_counts[plat])

        st.caption(
            "💡 To schedule: Calendar → Schedule a Draft. "
            "After publishing, return to Calendar → Mark Posted."
        )
        st.divider()

        # Group by platform — LinkedIn → Facebook → Instagram
        grouped: dict[str, list] = {}
        for d in ready_drafts:
            grouped.setdefault(d["platform"], []).append(d)

        for platform in PLATFORM_ORDER:
            if platform not in grouped:
                continue
            plat_drafts = grouped[platform]
            n = len(plat_drafts)
            st.subheader(f"{PLATFORM_LABEL[platform]}  ({n} draft{'s' if n != 1 else ''})")
            for draft in plat_drafts:
                _render_ready_card(draft)
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
            "Generate ALL waiting angles",
            type="primary",
            use_container_width=True,
            disabled=(stats["waiting"] == 0 and not regenerate),
        ):
            target_count = stats["total_approved"] if regenerate else stats["waiting"]
            if target_count == 0:
                st.warning("No angles to draft. Tick 'Regenerate' to overwrite existing drafts.")
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
                        f"Cost: ${result['total_cost_usd']:.4f}"
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
            if st.button("Generate drafts for this angle only", use_container_width=True):
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
                        f"Cost: ${result['est_cost_usd']:.4f}"
                    )
                    for w in result["warnings"]:
                        st.warning(w)
                    st.rerun()


# ── TAB 3: Review Queue ────────────────────────────────────────────────────────

with tab_review:
    st.subheader("Review Queue")
    st.caption(
        "Drafts that have been generated but need your decision. "
        "Run the Editor (Page 5) to check quality before approving."
    )

    if not review_drafts:
        st.success("✅ Nothing to review. All drafts are approved or rejected.")
    else:
        # Sort into three buckets
        flagged = [d for d in review_drafts if editor_statuses.get(d["id"]) == "flagged"]
        unrev   = [d for d in review_drafts if d["id"] not in editor_statuses]
        clean   = [d for d in review_drafts if editor_statuses.get(d["id"]) == "clean"]

        if flagged:
            st.markdown(f"### 🚩 Editor Flagged ({len(flagged)})")
            st.caption("The Editor found issues. Fix before approving.")
            for draft in flagged:
                _render_review_card(draft, "flagged")
            st.divider()

        if unrev:
            st.markdown(f"### ⏳ Not Yet Reviewed by Editor ({len(unrev)})")
            st.caption(
                "Run the Editor (Page 5) on these, or approve directly "
                "if you've read them and they look right."
            )
            for draft in unrev:
                _render_review_card(draft, None)
            st.divider()

        if clean:
            st.markdown(f"### ✅ Editor Clean — Ready to Approve ({len(clean)})")
            st.caption("No issues found. Approve when ready.")
            for draft in clean:
                _render_review_card(draft, "clean")


# ── TAB 4: Archive ─────────────────────────────────────────────────────────────

with tab_archive:
    st.subheader("Archive")

    # ── Posted section
    st.markdown(
        f"### ✅ Posted ({len(posted_drafts)})"
        if posted_drafts else "### ✅ Posted"
    )
    if posted_drafts:
        st.caption("Published and marked as posted. Read-only.")
        for draft in posted_drafts:
            _render_posted_card(draft)
    else:
        st.caption(
            "No posted drafts yet. After publishing on LinkedIn or Meta Business Suite, "
            "go to Calendar → Mark Posted and they will appear here."
        )

    st.divider()

    # ── Rejected section
    st.markdown(
        f"### ❌ Rejected ({len(rejected_drafts)})"
        if rejected_drafts else "### ❌ Rejected"
    )
    if rejected_drafts:
        st.caption(
            "↩️ Restore sends the draft back to Review Queue. "
            "🗑️ Delete permanently removes it — this cannot be undone."
        )
        for draft in rejected_drafts:
            _render_rejected_card(draft)
    else:
        st.caption("No rejected drafts.")


# ── TAB 5: Pipeline ────────────────────────────────────────────────────────────

with tab_pipeline:
    st.subheader("Pipeline Overview")

    stats = count_draft_stats(product_id)

    st.markdown("**Drafts by Status**")
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Draft",    stats["by_status"].get("draft",    0))
    sc2.metric("Approved", stats["by_status"].get("approved", 0))
    sc3.metric("Rejected", stats["by_status"].get("rejected", 0))
    sc4.metric("Edited",   stats["by_status"].get("edited",   0))
    st.caption(f"Total drafts in DB: {stats['total_drafts']}")

    st.divider()

    st.markdown("**Platform Split**")
    pc1, pc2, pc3 = st.columns(3)
    pc1.metric("📷 Instagram", stats["by_platform"].get("instagram", 0))
    pc2.metric("🔵 Facebook",  stats["by_platform"].get("facebook",  0))
    pc3.metric("💼 LinkedIn",  stats["by_platform"].get("linkedin",  0))

    st.divider()

    st.markdown("**Per-Angle Draft Coverage**")
    st.caption(
        "Target: 2 drafts per platform targeted by the angle "
        "(2 for single-platform, 4 for two platforms, 6 for all three)."
    )

    coverage = get_angle_draft_coverage(product_id)
    if not coverage:
        st.info("No approved angles yet.")
    else:
        for row in coverage:
            platform_fit = row.get("platform_fit", "both")
            if platform_fit in ("instagram", "facebook", "linkedin"):
                target = 2
            else:
                target = 6
            actual = int(row["draft_count"])
            label  = f"[{row['id']}] {row['angle_title']}"
            pct    = min(actual / target, 1.0) if target else 0.0
            icon   = "✅" if actual >= target else ("⚠️" if actual > 0 else "⏳")
            st.markdown(f"{icon} **{label}** — {actual}/{target} drafts")
            st.progress(pct)