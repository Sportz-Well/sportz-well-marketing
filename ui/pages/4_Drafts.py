"""Drafts — review and manage AI-generated post drafts."""

import json
from itertools import groupby

import streamlit as st
from services.page_utils import init_page

from agents.copywriter import (
    count_draft_stats,
    get_angle_draft_coverage,
    get_approved_angles,
    get_drafts_library,
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


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _load_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _platform_label(platform: str) -> str:
    return {
        "instagram": "📷 Instagram",
        "facebook":  "🔵 Facebook",
        "linkedin":  "💼 LinkedIn",
    }.get(platform, platform.capitalize())


def _status_label(status: str) -> str:
    return {
        "draft":    "⏳ Draft",
        "approved": "✅ Approved",
        "rejected": "❌ Rejected",
        "edited":   "✏️ Edited",
    }.get(status, status)


def _format_ts(ts: str | None) -> str:
    """Format a SQLite timestamp string to a readable short form.
    Input:  '2026-05-21 14:32:07' or '2026-05-21T14:32:07' or None
    Output: '21 May 2026, 2:32 pm' or ''
    Windows-safe: avoids %-d / %-I format codes.
    """
    if not ts:
        return ""
    try:
        from datetime import datetime
        cleaned = ts[:19].replace("T", " ")
        dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
        day   = str(dt.day)
        month = dt.strftime("%b %Y")
        hour  = dt.hour % 12 or 12
        mins  = dt.strftime("%M")
        ampm  = "am" if dt.hour < 12 else "pm"
        return f"{day} {month}, {hour}:{mins} {ampm}"
    except Exception:
        return ts[:16]


def _render_draft_card(draft: dict) -> None:
    draft_id        = draft["id"]
    platform        = draft["platform"]
    variant         = draft["variant_number"]
    status          = draft["status"]
    headline        = draft.get("headline") or ""
    body            = draft.get("body") or ""
    cta_line        = draft.get("cta_line")
    hashtags        = _load_json(draft.get("hashtags"), [])
    carousel_slides = _load_json(draft.get("carousel_slides"), None)
    reel_script     = _load_json(draft.get("reel_script"), None)
    image_brief     = draft.get("image_brief") or ""
    word_count      = draft.get("word_count") or 0
    char_count      = draft.get("char_count") or 0
    created_at      = draft.get("created_at")
    updated_at      = draft.get("updated_at")

    edit_key = f"editing_{draft_id}"
    if edit_key not in st.session_state:
        st.session_state[edit_key] = False

    with st.container(border=True):
        # Card header row 1: platform/variant + word count
        h_left, h_right = st.columns([3, 1])
        with h_left:
            st.markdown(
                f"**{_platform_label(platform)} — Variant {variant}** &nbsp; "
                f"_{_status_label(status)}_"
            )
        with h_right:
            st.caption(f"{word_count} words / {char_count} chars")

        # Card header row 2: timestamps
        ts_parts = []
        if created_at:
            ts_parts.append(f"Created: {_format_ts(created_at)}")
        if updated_at and updated_at != created_at:
            ts_parts.append(f"Updated: {_format_ts(updated_at)}")
        if ts_parts:
            st.caption(" · ".join(ts_parts))

        # Headline
        if headline:
            st.markdown(f"**{headline}**")

        # Body — display only
        st.text_area(
            "body",
            value=body,
            height=160,
            disabled=True,
            key=f"body_ro_{draft_id}",
            label_visibility="collapsed",
        )

        # CTA line
        if cta_line:
            st.markdown(f"_CTA: {cta_line}_")

        # Hashtags
        if hashtags:
            st.markdown(" ".join(f"`{tag}`" for tag in hashtags))

        # Carousel slides (not applicable for LinkedIn)
        if carousel_slides:
            with st.expander(f"Slides ({len(carousel_slides)})"):
                for slide in carousel_slides:
                    num   = slide.get("slide_number", "?")
                    title = slide.get("slide_title", "")
                    sbody = slide.get("slide_body", "")
                    st.markdown(f"**Slide {num}: {title}**")
                    st.caption(sbody)

        # Reel script (not applicable for LinkedIn)
        if reel_script:
            with st.expander("Reel script"):
                hook = reel_script.get("hook_seconds_0_3", "")
                if hook:
                    st.markdown(f"**Hook (0–3 s):** {hook}")
                beats = reel_script.get("beats") or []
                if beats:
                    st.markdown("**Beats:**")
                    for b in beats:
                        st.markdown(f"- {b}")
                vo = reel_script.get("voiceover", "")
                if vo:
                    st.markdown(f"**Voiceover:** {vo}")
                on_screen = reel_script.get("on_screen_text") or []
                if on_screen:
                    st.markdown("**On-screen text:** " + " · ".join(on_screen))

        # Image brief (not shown for LinkedIn text_post which has null image_brief)
        if image_brief:
            st.caption(f"🖼 Image brief: {image_brief}")

        # Action buttons or inline edit form
        if not st.session_state[edit_key]:
            b1, b2, b3, _ = st.columns([1, 1, 1, 2])
            with b1:
                if st.button("✅ Approve", key=f"approve_{draft_id}", use_container_width=True):
                    update_draft_status(draft_id, "approved")
                    st.rerun()
            with b2:
                if st.button("❌ Reject", key=f"reject_{draft_id}", use_container_width=True):
                    update_draft_status(draft_id, "rejected")
                    st.rerun()
            with b3:
                if st.button("✏️ Edit", key=f"edit_btn_{draft_id}", use_container_width=True):
                    st.session_state[edit_key] = True
                    st.rerun()
        else:
            with st.form(key=f"edit_form_{draft_id}"):
                new_headline = st.text_input("Headline", value=headline)
                new_body     = st.text_area("Body", value=body, height=220)
                new_cta      = st.text_input(
                    "CTA Line (leave blank for no CTA)",
                    value=cta_line or "",
                )
                s1, s2 = st.columns(2)
                with s1:
                    save_clicked   = st.form_submit_button("Save", use_container_width=True)
                with s2:
                    cancel_clicked = st.form_submit_button("Cancel", use_container_width=True)

            if save_clicked:
                update_draft_content(draft_id, new_headline, new_body, new_cta or None)
                st.session_state[edit_key] = False
                st.rerun()
            elif cancel_clicked:
                st.session_state[edit_key] = False
                st.rerun()


# ─── Tabs ─────────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["Generate Drafts", "Drafts Library", "Pipeline Overview"])


# ── TAB 1: Generate Drafts ────────────────────────────────────────────────────

with tab1:
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
                        f"Cost: ${result['total_cost_usd']:.4f} USD."
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
                        f"Cost: ${result['est_cost_usd']:.4f} USD."
                    )
                    for w in result["warnings"]:
                        st.warning(w)
                    st.rerun()


# ── TAB 2: Drafts Library ─────────────────────────────────────────────────────

with tab2:
    st.subheader("Drafts Library")

    approved_angles = get_approved_angles(product_id)

    f1, f2, f3 = st.columns([1, 1, 2])
    with f1:
        status_filter = st.selectbox(
            "Status",
            ["All", "draft", "approved", "rejected", "edited"],
            key="lib_status",
        )
    with f2:
        platform_filter = st.selectbox(
            "Platform",
            ["All", "instagram", "facebook", "linkedin"],
            key="lib_platform",
        )
    with f3:
        angle_label_map: dict[int, str] = {0: "All angles"}
        for a in approved_angles:
            angle_label_map[a["id"]] = f"[{a['id']}] {a['angle_title']}"
        angle_id_filter = st.selectbox(
            "Angle",
            options=list(angle_label_map.keys()),
            format_func=lambda x: angle_label_map[x],
            key="lib_angle",
        )

    drafts = get_drafts_library(
        product_id,
        status_filter=status_filter    if status_filter    != "All" else None,
        platform_filter=platform_filter if platform_filter != "All" else None,
        angle_id_filter=angle_id_filter if angle_id_filter != 0     else None,
    )

    if not drafts:
        st.info("No drafts match the current filters.")
    else:
        st.caption(f"{len(drafts)} draft(s) shown")
        for angle_gid, group_iter in groupby(drafts, key=lambda d: d["story_angle_id"]):
            group = list(group_iter)
            angle_title = group[0].get("angle_title", "Untitled")
            st.markdown(f"### {angle_title}")
            for draft in group:
                _render_draft_card(draft)
            st.divider()


# ── TAB 3: Pipeline Overview ──────────────────────────────────────────────────

with tab3:
    st.subheader("Pipeline Overview")

    stats = count_draft_stats(product_id)

    # Status breakdown
    st.markdown("**Drafts by Status**")
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Draft",    stats["by_status"].get("draft",    0))
    sc2.metric("Approved", stats["by_status"].get("approved", 0))
    sc3.metric("Rejected", stats["by_status"].get("rejected", 0))
    sc4.metric("Edited",   stats["by_status"].get("edited",   0))
    st.caption(f"Total drafts in DB: {stats['total_drafts']}")

    st.divider()

    # Platform split
    st.markdown("**Platform Split**")
    pc1, pc2, pc3 = st.columns(3)
    pc1.metric("📷 Instagram", stats["by_platform"].get("instagram", 0))
    pc2.metric("🔵 Facebook",  stats["by_platform"].get("facebook",  0))
    pc3.metric("💼 LinkedIn",  stats["by_platform"].get("linkedin",  0))

    st.divider()

    # Per-angle coverage
    st.markdown("**Per-Angle Draft Coverage**")
    st.caption("Target: 2 drafts per platform targeted by the angle (2 for single-platform, 4 for both, 6 for all three).")

    coverage = get_angle_draft_coverage(product_id)
    if not coverage:
        st.info("No approved angles yet.")
    else:
        for row in coverage:
            platform_fit = row.get("platform_fit", "both")
            if platform_fit in ("instagram", "facebook", "linkedin"):
                target = 2
            elif platform_fit == "both":
                target = 6   # all three platforms now
            else:
                target = 6
            actual = int(row["draft_count"])
            label  = f"[{row['id']}] {row['angle_title']}"
            pct    = min(actual / target, 1.0) if target else 0.0
            status_icon = "✅" if actual >= target else ("⚠️" if actual > 0 else "⏳")
            st.markdown(f"{status_icon} **{label}** — {actual}/{target} drafts")
            st.progress(pct)
