"""
ui/pages/6_Media.py
────────────────────
Media Studio — three tabs:
  Tab 1 – Generate   : Add visual notes and run the Media agent.
  Tab 2 – Library    : Copy Firefly / ChatGPT / Gemini prompts, approve / reject.
  Tab 3 – Pipeline   : Coverage overview and spend summary.
"""

import streamlit as st
from services.page_utils import init_page

from agents.media import (
    count_media_stats,
    generate_all_pending,
    generate_media_brief,
    get_media_library,
    get_visual_note,
    save_visual_note,
    update_brief_status,
)
from services.brand_context import get_active_product
from services.database import get_connection

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(page_title="Media Studio · SWPI", layout="wide")
init_page()
st.title("📸 Media Studio")
st.caption(
    "Generate AI image prompts for Adobe Firefly, ChatGPT (DALL-E 3), and Google Gemini. "
    "Add a Visual Photography Note to any draft for specific creative direction."
)

# ── Active product guard ───────────────────────────────────────────────────
product = get_active_product()
if not product:
    st.error("No active product found. Go to Brand Brain → Seed Data first.")
    st.stop()

product_id   = product["product_id"]
product_name = product["product_name"]

# ── Tabs ───────────────────────────────────────────────────────────────────
tab_gen, tab_lib, tab_pipe = st.tabs(
    ["🎬 Generate", "📂 Library", "📊 Pipeline Overview"]
)


# ══════════════════════════════════════════════════════════════════════════
# TAB 1 — GENERATE
# ══════════════════════════════════════════════════════════════════════════
with tab_gen:
    st.subheader("Generate AI Image Prompts")

    st.info(
        "💡 **Cost:** ~₹0.25–₹0.50 per brief (three prompts per draft, no web search).  \n"
        "Each prompt has a built-in copy button in the Library tab."
    )

    stats = count_media_stats(product_id)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Drafts",      stats["total_drafts"])
    c2.metric("Prompts Generated", stats["drafts_with_brief"])
    c3.metric("Awaiting Prompts",  stats["drafts_without_brief"])

    st.divider()

    # ── Generate ALL pending ──────────────────────────────────────────────
    st.markdown("#### Generate All Pending Drafts")
    col_a, col_b = st.columns([3, 1])
    with col_a:
        force_regen = st.checkbox(
            "Regenerate existing prompts (resets status to pending)",
            value=False,
            help="If unchecked, only drafts without prompts are processed.",
        )
    with col_b:
        run_all = st.button(
            "▶ Generate All",
            type="primary",
            use_container_width=True,
            disabled=(stats["drafts_without_brief"] == 0 and not force_regen),
        )

    if run_all:
        pending_count = (
            stats["total_drafts"] if force_regen else stats["drafts_without_brief"]
        )
        if pending_count == 0:
            st.warning("No drafts to process.")
        else:
            with st.spinner(f"Generating prompts for {pending_count} draft(s)…"):
                result = generate_all_pending(product_id, force=force_regen)

            if result["failed"] == 0:
                st.success(
                    f"✅ Done!  "
                    f"Generated: **{result['generated']}** · "
                    f"Skipped (no source): **{result['skipped_no_source']}** · "
                    f"Cached: **{result['cached']}** · "
                    f"Cost: **${result['total_cost_usd']:.4f}**"
                )
            else:
                st.warning(
                    f"Completed with errors.  "
                    f"Generated: **{result['generated']}** · "
                    f"Failed: **{result['failed']}** · "
                    f"Skipped: **{result['skipped_no_source']}**"
                )
                with st.expander("⚠ Errors"):
                    for e in result["errors"]:
                        st.text(e)
            st.rerun()

    st.divider()

    # ── Visual note + single draft ────────────────────────────────────────
    st.markdown("#### Add Visual Note & Generate for One Draft")
    st.caption(
        "A Visual Photography Note gives the AI specific creative direction for this exact post.  \n"
        "It overrides the copywriter's image brief. Optional — but the more specific you are, "
        "the better the prompts."
    )

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT d.id, d.platform, d.variant_number, d.headline,
                   d.image_brief, d.visual_photography_note,
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
        # Build selector with status indicators
        draft_options: dict[str, int] = {}
        for r in rows:
            has_brief = bool(r[7])
            has_note  = bool(r[5])
            if has_brief:
                prefix = "✅"
            elif has_note:
                prefix = "📝"
            else:
                prefix = "⬜"
            label = (
                f"{prefix} Draft #{r[0]} · "
                f"{(r[1] or '').capitalize()} v{r[2]} · "
                f"{(r[6] or 'Untitled')[:40]}"
            )
            draft_options[label] = r[0]

        st.caption("✅ prompts done  ·  📝 note saved, prompts not yet generated  ·  ⬜ nothing yet")
        selected_label = st.selectbox("Select draft", list(draft_options.keys()))
        selected_id    = draft_options[selected_label]

        # Pull context for selected draft
        image_brief_text = ""
        current_note     = ""
        for r in rows:
            if r[0] == selected_id:
                image_brief_text = r[4] or ""
                current_note     = r[5] or ""
                break

        # Copywriter image brief (read-only reference)
        if image_brief_text:
            st.markdown(
                f"<div style='background:#1a1a2e;padding:10px 14px;"
                f"border-left:3px solid #f5a623;border-radius:4px;"
                f"font-size:0.85rem;color:#ccc;margin-bottom:12px;'>"
                f"<strong>Copywriter image brief:</strong><br>{image_brief_text}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.warning(
                "⚠ This draft has no copywriter image brief. "
                "Add a Visual Photography Note below to enable generation."
            )

        # Visual photography note editor
        note_input = st.text_area(
            "Visual Photography Note",
            value=current_note,
            height=110,
            max_chars=600,
            key=f"note_{selected_id}",
            placeholder=(
                "Describe exactly what you want in the image. "
                "Example: U-14 batter at nets, coach crouching beside him pointing "
                "at bat grip, late afternoon light, no spectators, earthy tones. "
                "Avoid anything that looks posed or performative."
            ),
        )
        st.caption(f"{len(note_input)}/600 characters")

        col_save, col_force, col_gen = st.columns([2, 2, 3])

        with col_save:
            if st.button("💾 Save Note Only", key=f"save_note_{selected_id}"):
                save_visual_note(selected_id, note_input)
                st.success("Note saved.")
                st.rerun()

        with col_force:
            force_single = st.checkbox(
                "Force regenerate",
                value=False,
                key=f"force_single_{selected_id}",
                help="Regenerate even if prompts already exist.",
            )

        with col_gen:
            can_gen = bool(image_brief_text or note_input.strip())
            if st.button(
                "▶ Generate Prompts",
                type="primary",
                use_container_width=True,
                disabled=not can_gen,
                key=f"gen_single_{selected_id}",
            ):
                # Auto-save note if it changed before generating
                if note_input.strip() != current_note:
                    save_visual_note(selected_id, note_input)

                with st.spinner("Generating AI image prompts…"):
                    res = generate_media_brief(selected_id, force=force_single)

                if res["ok"]:
                    if res.get("cached"):
                        st.info(
                            "Prompts already exist — returned from cache. "
                            "Tick Force regenerate to redo."
                        )
                    else:
                        st.success(
                            f"✅ Prompts generated!  "
                            f"Tokens: {res['input_tokens']}in / {res['output_tokens']}out  "
                            f"|  Cost: ${res['cost_usd']:.5f}"
                        )
                    st.rerun()
                else:
                    st.error(f"❌ {res.get('error', 'Unknown error')}")
                    if res.get("raw_response"):
                        with st.expander("Raw model response"):
                            st.text(res["raw_response"][:2000])


# ══════════════════════════════════════════════════════════════════════════
# TAB 2 — LIBRARY
# ══════════════════════════════════════════════════════════════════════════
with tab_lib:
    st.subheader("Image Prompt Library")
    st.caption(
        "Click the copy icon (top-right of each code box) to copy a prompt. "
        "Paste directly into Firefly, ChatGPT, or Gemini."
    )

    fcol1, fcol2 = st.columns(2)
    with fcol1:
        status_filter = st.selectbox(
            "Filter by status",
            ["all", "pending", "approved", "rejected"],
            key="lib_status",
        )
    with fcol2:
        platform_filter = st.selectbox(
            "Filter by platform",
            ["all", "instagram", "facebook", "linkedin"],
            key="lib_platform",
        )

    briefs = get_media_library(
        product_id,
        status_filter=None if status_filter == "all" else status_filter,
        platform_filter=None if platform_filter == "all" else platform_filter,
    )

    if not briefs:
        st.info("No prompts found. Generate some in the Generate tab.")
    else:
        st.caption(f"{len(briefs)} brief(s) found.")

        for b in briefs:
            status_badge = {
                "pending":  "🟡 Pending",
                "approved": "✅ Approved",
                "rejected": "❌ Rejected",
            }.get(b["status"], b["status"])

            platform_icon = {
                "instagram": "📸",
                "facebook":  "👥",
                "linkedin":  "💼",
            }.get((b["platform"] or "").lower(), "📄")

            card_title = (
                f"{status_badge} · {platform_icon} "
                f"{(b['platform'] or '').capitalize()} v{b['variant_number']} · "
                f"Draft #{b['draft_id']} · "
                f"{(b['angle_title'] or 'Untitled')[:50]}"
            )

            with st.expander(card_title, expanded=(b["status"] == "pending")):

                # Visual photography note banner
                if b.get("visual_photography_note"):
                    st.info(
                        f"📝 **Visual Photography Note used:** "
                        f"{b['visual_photography_note']}"
                    )

                # Copywriter image brief (reference)
                if b.get("image_brief"):
                    st.markdown(
                        f"<div style='background:#1a1a2e;padding:8px 12px;"
                        f"border-left:3px solid #555;border-radius:4px;"
                        f"font-size:0.82rem;color:#aaa;margin-bottom:10px;'>"
                        f"<strong>Copywriter brief:</strong> {b['image_brief']}</div>",
                        unsafe_allow_html=True,
                    )

                st.divider()

                # Check if this is a new-style brief with AI prompts
                has_prompts = any([
                    b.get("firefly_prompt"),
                    b.get("chatgpt_prompt"),
                    b.get("gemini_prompt"),
                ])

                if not has_prompts:
                    st.warning(
                        "⚠ This brief was created with the old photography system. "
                        "Click Regenerate to get AI image prompts."
                    )
                else:
                    # Adobe Firefly
                    if b.get("firefly_prompt"):
                        st.markdown(
                            "**🔥 Adobe Firefly** — "
                            "[open firefly.adobe.com](https://firefly.adobe.com)"
                        )
                        st.code(b["firefly_prompt"], language=None)
                        st.caption("↑ Click the copy icon top-right to copy")

                    # ChatGPT / DALL-E 3
                    if b.get("chatgpt_prompt"):
                        st.markdown(
                            "**🤖 ChatGPT (DALL-E 3)** — "
                            "[open chatgpt.com](https://chatgpt.com)"
                        )
                        st.code(b["chatgpt_prompt"], language=None)
                        st.caption("↑ In ChatGPT: click the image icon, paste prompt, select size from instructions")

                    # Google Gemini
                    if b.get("gemini_prompt"):
                        st.markdown(
                            "**✨ Google Gemini** — "
                            "[open gemini.google.com](https://gemini.google.com)"
                        )
                        st.code(b["gemini_prompt"], language=None)
                        st.caption("↑ In Gemini: paste prompt, set orientation as instructed")

                st.caption(
                    f"Created: {b['created_at']} · "
                    f"Updated: {b['updated_at']} · "
                    f"Cost: ${b['cost_usd']:.5f}"
                )

                # Approve / Reject / Regenerate buttons
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
                                st.success(f"Done. Cost: ${res['cost_usd']:.5f}")
                                st.rerun()
                            else:
                                st.error(res.get("error", "Error"))
                else:
                    ba2, bregen2 = st.columns(2)
                    with ba2:
                        if st.button("↩ Revert to Pending", key=f"revert_{b['id']}"):
                            update_brief_status(b["id"], "pending")
                            st.rerun()
                    with bregen2:
                        if st.button("🔄 Regenerate", key=f"regen2_{b['id']}"):
                            with st.spinner("Regenerating…"):
                                res = generate_media_brief(b["draft_id"], force=True)
                            if res["ok"]:
                                st.success(f"Done. Cost: ${res['cost_usd']:.5f}")
                                st.rerun()
                            else:
                                st.error(res.get("error", "Error"))


# ══════════════════════════════════════════════════════════════════════════
# TAB 3 — PIPELINE OVERVIEW
# ══════════════════════════════════════════════════════════════════════════
with tab_pipe:
    st.subheader("Pipeline Overview")

    stats = count_media_stats(product_id)

    st.markdown("#### Brief Coverage")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Drafts",      stats["total_drafts"])
    c2.metric("Prompts Generated", stats["drafts_with_brief"])
    c3.metric("Awaiting Prompts",  stats["drafts_without_brief"])
    c4.metric(
        "No Source",
        stats["drafts_no_source"],
        help="Drafts with no image_brief AND no visual photography note.",
    )

    if stats["total_drafts"] > 0:
        pct = int(stats["drafts_with_brief"] / stats["total_drafts"] * 100)
        st.progress(pct / 100, text=f"Coverage: {pct}% of drafts have prompts")

    st.divider()

    st.markdown("#### Brief Status")
    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("🟡 Pending",  stats["briefs_pending"])
    sc2.metric("✅ Approved", stats["briefs_approved"])
    sc3.metric("❌ Rejected", stats["briefs_rejected"])

    st.divider()

    st.markdown("#### Per-Draft Coverage")
    conn = get_connection()
    try:
        cov_rows = conn.execute(
            """
            SELECT d.id, d.platform, d.variant_number, d.status AS draft_status,
                   d.visual_photography_note,
                   sa.angle_title,
                   mb.id AS brief_id, mb.status AS brief_status, mb.cost_usd,
                   CASE WHEN mb.firefly_prompt IS NOT NULL THEN 1 ELSE 0 END AS has_prompts
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

    if cov_rows:
        import pandas as pd

        table_data = []
        for r in cov_rows:
            table_data.append({
                "Draft #":       r[0],
                "Platform":      (r[1] or "").capitalize(),
                "Variant":       f"v{r[2]}",
                "Draft Status":  r[3],
                "Visual Note":   "📝 Yes" if r[4] else "—",
                "Angle":         (r[5] or "")[:40],
                "Prompts":       "✅" if r[6] else "⬜",
                "Prompt Status": r[7] if r[6] else "— none",
                "Cost ($)":      f"{r[8]:.5f}" if r[8] else "—",
            })
        df = pd.DataFrame(table_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    st.markdown("#### Media Agent Spend")
    conn = get_connection()
    try:
        spend = conn.execute(
            """
            SELECT SUM(model_input_tokens), SUM(model_output_tokens),
                   SUM(cost_usd), COUNT(*)
            FROM   media_briefs
            WHERE  product_id = ?
            """,
            (product_id,),
        ).fetchone()
    finally:
        conn.close()

    if spend and spend[3]:
        sp1, sp2, sp3, sp4 = st.columns(4)
        sp1.metric("Total Briefs",  spend[3])
        sp2.metric("Input Tokens",  f"{spend[0]:,}" if spend[0] else "0")
        sp3.metric("Output Tokens", f"{spend[1]:,}" if spend[1] else "0")
        sp4.metric("Total Cost",    f"${spend[2]:.4f}" if spend[2] else "$0.0000")
    else:
        st.info("No spend data yet. Generate some prompts first.")

    st.markdown("#### Last 10 API Calls")
    conn = get_connection()
    try:
        log_rows = conn.execute(
            """
            SELECT timestamp, action, input_tokens, output_tokens,
                   est_cost_usd, notes
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
            "Timestamp", "Action", "Input Tokens", "Output Tokens",
            "Cost ($)", "Notes",
        ])
        st.dataframe(log_df, use_container_width=True, hide_index=True)
    else:
        st.info("No API calls logged yet.")