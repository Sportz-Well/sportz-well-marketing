"""
ui/pages/6_Media.py
────────────────────
Media Studio page — three tabs:
  Tab 1 – Generate   : Run the Media agent on drafts without a brief.
  Tab 2 – Library    : Browse, filter, approve / reject briefs.
  Tab 3 – Pipeline   : Coverage overview and spend summary.
"""

import streamlit as st

from agents.media import (
    count_media_stats,
    generate_all_pending,
    generate_media_brief,
    get_media_library,
    update_brief_status,
)
from services.brand_context import get_active_product
from services.database import get_connection

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(page_title="Media Studio · SWPI", layout="wide")
st.title("📸 Media Studio")
st.caption("Turn caption image briefs into shoot-ready photography creative briefs.")

# ── Active product guard ───────────────────────────────────────────────────
product = get_active_product()
if not product:
    st.error("No active product found. Go to Brand Brain → Seed Data first.")
    st.stop()

product_id   = product["id"]
product_name = product["name"]

# ── Tabs ───────────────────────────────────────────────────────────────────
tab_gen, tab_lib, tab_pipe = st.tabs(
    ["🎬 Generate", "📂 Library", "📊 Pipeline Overview"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — GENERATE
# ══════════════════════════════════════════════════════════════════════════════
with tab_gen:
    st.subheader("Generate Photography Briefs")

    # Cost callout
    st.info(
        "💡 **Estimated cost:** ~₹0.35 – ₹0.70 per brief (pure reasoning, no web search).  \n"
        "One brief per draft. Drafts with no `image_brief` are skipped automatically."
    )

    stats = count_media_stats(product_id)

    # Summary metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Drafts", stats["total_drafts"])
    c2.metric("Briefs Generated", stats["drafts_with_brief"])
    c3.metric("Awaiting Brief", stats["drafts_without_brief"],
              delta=f"-{stats['drafts_no_image_brief']} have no image_brief" if stats["drafts_no_image_brief"] else None,
              delta_color="off")

    st.divider()

    # ── Generate ALL pending ──────────────────────────────────────────────
    st.markdown("#### Generate All Pending Briefs")
    col_a, col_b = st.columns([3, 1])
    with col_a:
        force_regen = st.checkbox(
            "Regenerate existing briefs (resets status to pending)",
            value=False,
            help="If unchecked, only drafts without a brief are processed.",
        )
    with col_b:
        run_all = st.button(
            "▶ Generate All",
            type="primary",
            use_container_width=True,
            disabled=(stats["drafts_without_brief"] == 0 and not force_regen),
        )

    if run_all:
        pending_count = stats["total_drafts"] if force_regen else stats["drafts_without_brief"]
        if pending_count == 0:
            st.warning("No drafts to process.")
        else:
            with st.spinner(f"Generating briefs for {pending_count} draft(s)…"):
                result = generate_all_pending(product_id, force=force_regen)

            # Result banner
            if result["failed"] == 0:
                st.success(
                    f"✅ Done!  "
                    f"Generated: **{result['generated']}** | "
                    f"Skipped (no image brief): **{result['skipped_no_brief']}** | "
                    f"Cached: **{result['cached']}** | "
                    f"Est. cost: **${result['total_cost_usd']:.4f}**"
                )
            else:
                st.warning(
                    f"Completed with errors.  "
                    f"Generated: **{result['generated']}** | "
                    f"Failed: **{result['failed']}** | "
                    f"Skipped: **{result['skipped_no_brief']}**"
                )
                with st.expander("⚠ Errors"):
                    for e in result["errors"]:
                        st.text(e)
            st.rerun()

    st.divider()

    # ── Generate single draft ─────────────────────────────────────────────
    st.markdown("#### Generate Brief for a Single Draft")

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT d.id, d.platform, d.variant_number, d.headline, d.image_brief,
                   sa.angle_title,
                   CASE WHEN mb.id IS NOT NULL THEN 1 ELSE 0 END AS has_brief
            FROM   drafts d
            JOIN   story_angles sa ON sa.id = d.story_angle_id
            LEFT   JOIN media_briefs mb ON mb.draft_id = d.id
            WHERE  d.product_id = ?
            ORDER  BY has_brief ASC, d.id ASC
            """,
            (product_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        st.info("No drafts found. Run the Copywriter first.")
    else:
        draft_options = {}
        for r in rows:
            label = (
                f"{'✅' if r[6] else '⬜'} "
                f"Draft #{r[0]} · {r[1].capitalize()} v{r[2]} · "
                f"{(r[5] or 'Untitled')[:40]}"
            )
            draft_options[label] = r[0]

        selected_label = st.selectbox(
            "Select draft",
            list(draft_options.keys()),
            help="✅ = brief already exists  ⬜ = no brief yet",
        )
        selected_id = draft_options[selected_label]

        # Show image_brief preview
        for r in rows:
            if r[0] == selected_id:
                if r[4]:
                    st.caption(f"**Image brief:** {r[4]}")
                else:
                    st.warning("⚠ This draft has no image_brief — generation will be skipped.")
                break

        force_single = st.checkbox("Force regenerate if brief exists", value=False, key="force_single")
        run_one = st.button("▶ Generate This Brief", type="secondary")

        if run_one:
            with st.spinner("Generating brief…"):
                res = generate_media_brief(selected_id, force=force_single)
            if res["ok"]:
                if res.get("cached"):
                    st.info("Brief already exists — returned from cache. Check ✅ 'Force regenerate' to redo.")
                else:
                    st.success(
                        f"✅ Brief generated!  "
                        f"Tokens: {res['input_tokens']}in / {res['output_tokens']}out  |  "
                        f"Cost: ${res['cost_usd']:.5f}"
                    )
                st.rerun()
            else:
                st.error(f"❌ {res.get('error', 'Unknown error')}")
                if res.get("raw_response"):
                    with st.expander("Raw model response"):
                        st.text(res["raw_response"][:2000])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — LIBRARY
# ══════════════════════════════════════════════════════════════════════════════
with tab_lib:
    st.subheader("Media Brief Library")

    # Filters
    fcol1, fcol2 = st.columns(2)
    with fcol1:
        status_options = ["all", "pending", "approved", "rejected"]
        status_filter = st.selectbox("Filter by status", status_options, key="lib_status")
    with fcol2:
        platform_options = ["all", "instagram", "facebook"]
        platform_filter = st.selectbox("Filter by platform", platform_options, key="lib_platform")

    briefs = get_media_library(
        product_id,
        status_filter=None if status_filter == "all" else status_filter,
        platform_filter=None if platform_filter == "all" else platform_filter,
    )

    if not briefs:
        st.info("No briefs found. Generate some in the Generate tab.")
    else:
        st.caption(f"{len(briefs)} brief(s) found.")

        for b in briefs:
            # Card header
            status_badge = {
                "pending":  "🟡 Pending",
                "approved": "✅ Approved",
                "rejected": "❌ Rejected",
            }.get(b["status"], b["status"])

            platform_icon = "📸" if b["platform"] == "instagram" else "👥"
            card_title = (
                f"{status_badge} · {platform_icon} {b['platform'].capitalize()} "
                f"v{b['variant_number']} · "
                f"Draft #{b['draft_id']} · "
                f"{(b['angle_title'] or 'Untitled')[:50]}"
            )

            with st.expander(card_title, expanded=(b["status"] == "pending")):

                # Original image brief
                if b.get("image_brief"):
                    st.markdown(
                        f"> **Copywriter brief:** *{b['image_brief']}*"
                    )
                st.divider()

                # Two-column layout for brief fields
                left, right = st.columns(2)

                with left:
                    st.markdown(f"**Shot type:** `{b['shot_type']}`")
                    st.markdown(f"**Subject:** {b['subject']}")
                    st.markdown(f"**Setting:** {b['setting']}")
                    st.markdown(f"**Time of day:** {b['time_of_day']}")
                    st.markdown(f"**Lighting mood:** {b['lighting_mood']}")

                    if b["props"]:
                        st.markdown("**Props:**")
                        for p in b["props"]:
                            st.markdown(f"  - {p}")
                    else:
                        st.markdown("**Props:** *none*")

                with right:
                    st.markdown(f"**Composition:** {b['composition_notes']}")

                    if b["color_palette"]:
                        st.markdown("**Colour palette:**")
                        for c in b["color_palette"]:
                            st.markdown(f"  - {c}")
                    else:
                        st.markdown("**Colour palette:** *not specified*")

                    if b.get("wardrobe_notes"):
                        st.markdown(f"**Wardrobe:** {b['wardrobe_notes']}")

                    if b["do_not"]:
                        st.markdown("**⛔ Do NOT:**")
                        for dn in b["do_not"]:
                            st.markdown(f"  - {dn}")

                st.markdown(
                    f"🔗 **Caption sync:** *{b['caption_sync_note']}*"
                )

                # Timestamps + cost
                st.caption(
                    f"Created: {b['created_at']} · "
                    f"Updated: {b['updated_at']} · "
                    f"Cost: ${b['cost_usd']:.5f}"
                )

                # Approve / Reject buttons
                if b["status"] != "approved":
                    ba, br, bregen = st.columns(3)
                    with ba:
                        if st.button("✅ Approve", key=f"approve_{b['id']}"):
                            update_brief_status(b["id"], "approved")
                            st.rerun()
                    with br:
                        if st.button("❌ Reject", key=f"reject_{b['id']}"):
                            update_brief_status(b["id"], "rejected")
                            st.rerun()
                    with bregen:
                        if st.button("🔄 Regenerate", key=f"regen_{b['id']}"):
                            with st.spinner("Regenerating…"):
                                res = generate_media_brief(b["draft_id"], force=True)
                            if res["ok"]:
                                st.success(f"Regenerated. Cost: ${res['cost_usd']:.5f}")
                                st.rerun()
                            else:
                                st.error(res.get("error", "Error"))
                else:
                    # Approved — only offer reject or regenerate
                    ba, br = st.columns(2)
                    with ba:
                        if st.button("↩ Revert to Pending", key=f"revert_{b['id']}"):
                            update_brief_status(b["id"], "pending")
                            st.rerun()
                    with br:
                        if st.button("🔄 Regenerate", key=f"regen2_{b['id']}"):
                            with st.spinner("Regenerating…"):
                                res = generate_media_brief(b["draft_id"], force=True)
                            if res["ok"]:
                                st.success(f"Regenerated. Cost: ${res['cost_usd']:.5f}")
                                st.rerun()
                            else:
                                st.error(res.get("error", "Error"))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — PIPELINE OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_pipe:
    st.subheader("Pipeline Overview")

    stats = count_media_stats(product_id)

    # Coverage metrics
    st.markdown("#### Brief Coverage")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Drafts", stats["total_drafts"])
    c2.metric("With Brief", stats["drafts_with_brief"])
    c3.metric("Without Brief", stats["drafts_without_brief"])
    c4.metric("No Image Brief", stats["drafts_no_image_brief"],
              help="Drafts the Copywriter wrote without an image_brief — cannot be processed.")

    if stats["total_drafts"] > 0:
        pct = int(stats["drafts_with_brief"] / stats["total_drafts"] * 100)
        st.progress(pct / 100, text=f"Coverage: {pct}% of drafts have a media brief")

    st.divider()

    # Status breakdown
    st.markdown("#### Brief Status")
    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("🟡 Pending",  stats["briefs_pending"])
    sc2.metric("✅ Approved", stats["briefs_approved"])
    sc3.metric("❌ Rejected", stats["briefs_rejected"])

    st.divider()

    # Per-draft coverage table
    st.markdown("#### Per-Draft Coverage")
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT d.id, d.platform, d.variant_number, d.status AS draft_status,
                   sa.angle_title,
                   mb.id AS brief_id, mb.status AS brief_status,
                   mb.cost_usd
            FROM   drafts d
            JOIN   story_angles sa ON sa.id = d.story_angle_id
            LEFT   JOIN media_briefs mb ON mb.draft_id = d.id
            WHERE  d.product_id = ?
            ORDER  BY d.id ASC
            """,
            (product_id,),
        ).fetchall()
    finally:
        conn.close()

    if rows:
        import pandas as pd

        table_data = []
        for r in rows:
            brief_status = r[6] if r[5] else "— no brief"
            table_data.append({
                "Draft #":      r[0],
                "Platform":     r[1].capitalize() if r[1] else "",
                "Variant":      f"v{r[2]}",
                "Draft Status": r[3],
                "Angle":        (r[4] or "")[:40],
                "Brief":        "✅" if r[5] else "⬜",
                "Brief Status": brief_status,
                "Cost ($)":     f"{r[7]:.5f}" if r[7] else "—",
            })
        df = pd.DataFrame(table_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    # Spend summary
    st.markdown("#### Media Agent Spend")
    conn = get_connection()
    try:
        spend_rows = conn.execute(
            """
            SELECT SUM(model_input_tokens), SUM(model_output_tokens), SUM(cost_usd),
                   COUNT(*)
            FROM   media_briefs
            WHERE  product_id = ?
            """,
            (product_id,),
        ).fetchone()
    finally:
        conn.close()

    if spend_rows and spend_rows[3]:
        sp1, sp2, sp3, sp4 = st.columns(4)
        sp1.metric("Total Briefs Generated", spend_rows[3])
        sp2.metric("Input Tokens",  f"{spend_rows[0]:,}" if spend_rows[0] else "0")
        sp3.metric("Output Tokens", f"{spend_rows[1]:,}" if spend_rows[1] else "0")
        sp4.metric("Total Cost",    f"${spend_rows[2]:.4f}" if spend_rows[2] else "$0.0000")
    else:
        st.info("No spend data yet. Generate some briefs first.")

    # Last 10 API calls
    st.markdown("#### Last 10 Media Agent API Calls")
    conn = get_connection()
    try:
        log_rows = conn.execute(
            """
            SELECT timestamp, action, input_tokens, output_tokens, est_cost_usd, notes
            FROM   api_log
            WHERE  agent = 'media'
            ORDER  BY id DESC
            LIMIT  10
            """,
        ).fetchall()
    finally:
        conn.close()

    if log_rows:
        import pandas as pd

        log_df = pd.DataFrame(log_rows, columns=[
            "Timestamp", "Action", "Input Tokens", "Output Tokens", "Cost ($)", "Notes"
        ])
        st.dataframe(log_df, use_container_width=True, hide_index=True)
    else:
        st.info("No API calls logged yet.")