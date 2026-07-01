"""
Orchestrator page — Sportz-Well Marketing Studio
Prompt 9: One-click full pipeline runner

Pipeline: Research → Strategy → Drafts → Editor → Media
Scheduler is NOT automated — user picks dates manually in Calendar.

Each stage shows live progress, cost, and pass/fail status.
The user can run the full pipeline or resume from any stage.
"""

import streamlit as st
from services.page_utils import init_page, format_cost_inr
import time
from datetime import datetime, timedelta, timezone

from services.brand_context import get_active_product
from agents.researcher import research_topic, GEOGRAPHY_OPTIONS
from agents.strategist import propose_story_angles
from agents.copywriter import write_drafts_for_all_approved
from agents.editor import count_unreviewed_drafts, review_draft
from agents.media import generate_all_pending
from agents.scheduler import get_pipeline_summary, get_approved_unscheduled_drafts
from services.database import get_connection

# ─── page config ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Orchestrator — Sportz-Well",
    page_icon="🎛",
    layout="wide",
)

init_page()

# ─── brand context ────────────────────────────────────────────────────────────

product = get_active_product()
if not product:
    st.error("No active product found. Go to Brand Brain and set an active product.")
    st.stop()

product_id   = product["product_id"]
product_name = product["product_name"]

# ─── header ──────────────────────────────────────────────────────────────────

st.title("🎛 Orchestrator")
st.caption(
    f"Product: **{product_name}** · "
    "Run the full pipeline in one click, or pick up from any stage."
)
st.divider()

# ─── helpers ─────────────────────────────────────────────────────────────────

def _fmt_cost(usd: float) -> str:
    """Format USD cost as INR for display."""
    return format_cost_inr(usd)


def _stage_header(icon: str, name: str, status: str = "") -> None:
    col1, col2 = st.columns([5, 1])
    col1.markdown(f"### {icon} {name}")
    if status:
        col2.markdown(status)


def _get_unreviewed_draft_ids(product_id: int) -> list[int]:
    """Return IDs of drafts with no editor review."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT d.id FROM drafts d
               WHERE d.product_id = ?
                 AND NOT EXISTS (
                     SELECT 1 FROM editor_reviews r WHERE r.draft_id = d.id
                 )
               ORDER BY d.id""",
            (product_id,),
        ).fetchall()
    return [r[0] for r in rows]


def _pipeline_snapshot(product_id: int) -> dict:
    """Quick counts across all pipeline stages."""
    with get_connection() as conn:
        research_n = conn.execute(
            "SELECT COUNT(*) FROM research_items WHERE product_id = ?",
            (product_id,)
        ).fetchone()[0]

        angles_proposed = conn.execute(
            "SELECT COUNT(*) FROM story_angles WHERE product_id = ?",
            (product_id,)
        ).fetchone()[0]

        angles_approved = conn.execute(
            "SELECT COUNT(*) FROM story_angles WHERE product_id = ? AND status='approved'",
            (product_id,)
        ).fetchone()[0]

        total_drafts = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE product_id = ?",
            (product_id,)
        ).fetchone()[0]

        approved_drafts = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE product_id = ? AND status='approved'",
            (product_id,)
        ).fetchone()[0]

        reviewed_drafts = conn.execute(
            """SELECT COUNT(DISTINCT draft_id) FROM editor_reviews r
               JOIN drafts d ON d.id = r.draft_id
               WHERE d.product_id = ?""",
            (product_id,)
        ).fetchone()[0]

        media_briefs = conn.execute(
            "SELECT COUNT(*) FROM media_briefs WHERE product_id = ?",
            (product_id,)
        ).fetchone()[0]

    sched_summary = get_pipeline_summary(product_id)
    unreviewed    = count_unreviewed_drafts(product_id)

    return {
        "research_items":    research_n,
        "angles_proposed":   angles_proposed,
        "angles_approved":   angles_approved,
        "total_drafts":      total_drafts,
        "approved_drafts":   approved_drafts,
        "reviewed_drafts":   reviewed_drafts,
        "unreviewed_drafts": unreviewed,
        "media_briefs":      media_briefs,
        "scheduled":         sched_summary["scheduled_pending"],
        "unscheduled":       sched_summary["unscheduled"],
        "posted":            sched_summary["posted_this_month"],
    }


def _get_all_agent_spend() -> dict:
    """Return consolidated spend breakdown by agent from api_log.

    Includes: today, this week (Mon–now), this month, all-time, and per-agent.
    All row access uses positional indexing (PostgreSQL-safe).
    """
    now        = datetime.now(timezone.utc)
    today_str  = now.strftime("%Y-%m-%d")
    month_str  = now.strftime("%Y-%m")
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")

    result = {
        "today_usd":   0.0,
        "week_usd":    0.0,
        "month_usd":   0.0,
        "alltime_usd": 0.0,
        "total_calls": 0,
        "by_agent":    [],
    }

    try:
        with get_connection() as conn:
            totals_row = conn.execute(
                """SELECT
                       COALESCE(SUM(CASE WHEN timestamp LIKE ? THEN est_cost_usd ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN timestamp >= ? THEN est_cost_usd ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN timestamp LIKE ? THEN est_cost_usd ELSE 0 END), 0),
                       COALESCE(SUM(est_cost_usd), 0),
                       COUNT(*)
                   FROM api_log""",
                (f"{today_str}%", f"{week_start}", f"{month_str}%"),
            ).fetchone()
            result["today_usd"]   = float(totals_row[0])
            result["week_usd"]    = float(totals_row[1])
            result["month_usd"]   = float(totals_row[2])
            result["alltime_usd"] = float(totals_row[3])
            result["total_calls"] = int(totals_row[4])

            by_agent_rows = conn.execute(
                """SELECT
                       agent,
                       COUNT(*),
                       COALESCE(SUM(est_cost_usd), 0),
                       COALESCE(SUM(CASE WHEN timestamp LIKE ? THEN est_cost_usd ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN timestamp >= ? THEN est_cost_usd ELSE 0 END), 0)
                   FROM api_log
                   GROUP BY agent
                   ORDER BY 3 DESC""",
                (f"{month_str}%", f"{week_start}"),
            ).fetchall()
            for r in by_agent_rows:
                result["by_agent"].append({
                    "agent":       r[0] or "unknown",
                    "calls":       int(r[1]),
                    "alltime_usd": float(r[2]),
                    "month_usd":   float(r[3]),
                    "week_usd":    float(r[4]),
                })
    except Exception:
        pass

    return result


# ─── pipeline status snapshot ─────────────────────────────────────────────────

st.subheader("📊 Pipeline Status")
snap = _pipeline_snapshot(product_id)

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("🔍 Research",  snap["research_items"],
          help="Items in research library")
c2.metric("📐 Angles",    f"{snap['angles_approved']}/{snap['angles_proposed']}",
          help="Approved / Total proposed")
c3.metric("✍️ Drafts",    f"{snap['approved_drafts']}/{snap['total_drafts']}",
          help="Approved / Total drafts")
c4.metric("🔎 Reviewed",  f"{snap['reviewed_drafts']}/{snap['total_drafts']}",
          help="Reviewed / Total drafts")
c5.metric("📸 Media",     snap["media_briefs"],
          help="Media briefs generated")
c6.metric("🗓 Scheduled", snap["scheduled"],
          help="Posts on calendar (pending)")

st.divider()

# ─── consolidated api spend dashboard ────────────────────────────────────────

st.subheader("💸 Total API Spend")

spend = _get_all_agent_spend()

sp1, sp2, sp3, sp4, sp5 = st.columns(5)
sp1.metric("Today",          format_cost_inr(spend["today_usd"]))
sp2.metric("This week",      format_cost_inr(spend["week_usd"]))
sp3.metric("This month",     format_cost_inr(spend["month_usd"]))
sp4.metric("All time",       format_cost_inr(spend["alltime_usd"]))
sp5.metric("Total API calls", spend["total_calls"])

if spend["by_agent"]:
    with st.expander("Breakdown by agent"):
        # Agent display name map
        _AGENT_LABEL = {
            "researcher": "🔍 Researcher",
            "strategist": "📐 Strategist",
            "copywriter": "✍️ Copywriter",
            "editor":     "🔎 Editor",
            "media":      "📸 Media (free)",
        }
        for row in spend["by_agent"]:
            agent     = row.get("agent", "unknown")
            label     = _AGENT_LABEL.get(agent, agent.capitalize())
            calls     = row.get("calls", 0)
            alltime   = row.get("alltime_usd", 0.0)
            month_usd = row.get("month_usd", 0.0)
            week_usd  = row.get("week_usd", 0.0)
            st.markdown(
                f"**{label}** — "
                f"{calls} call{'s' if calls != 1 else ''} · "
                f"This week: {format_cost_inr(week_usd)} · "
                f"This month: {format_cost_inr(month_usd)} · "
                f"All time: {format_cost_inr(alltime)}"
            )

st.divider()

# ─── tabs ─────────────────────────────────────────────────────────────────────

tab_full, tab_stage = st.tabs([
    "🚀 Full Pipeline Run",
    "🔧 Run Individual Stage",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — FULL PIPELINE RUN
# ══════════════════════════════════════════════════════════════════════════════

with tab_full:
    st.subheader("Full Pipeline Run")
    st.caption(
        "Runs all 5 stages in sequence: **Research → Strategy → Drafts → Editor → Media**. "
        "Scheduling is always manual — go to Calendar after this run."
    )

    with st.expander("⚙️ Configure this run", expanded=True):
        col_a, col_b = st.columns(2)
        with col_a:
            research_topic_input = st.text_input(
                "Research topic",
                placeholder="e.g. grassroots cricket academies India 2026",
                help="Leave blank to skip Research stage and use existing research.",
            )
            geography = st.selectbox(
                "Geography mix",
                options=list(GEOGRAPHY_OPTIONS.keys()),
                index=0,
            )
            max_results = st.slider("Max research items", 3, 12, 6)

        with col_b:
            min_relevance = st.slider("Min relevance score (research)", 5, 10, 7)
            max_angles    = st.slider("Max story angles to propose", 4, 20, 10)
            focus_input   = st.text_input(
                "Optional editorial focus",
                placeholder="e.g. focus on coach-parent communication",
            )

    st.markdown(
        "**Estimated cost:** ~₹5–₹25 depending on research items and angles. "
        "Drafts + Editor are the main cost drivers."
    )

    run_btn = st.button("🚀 Run Full Pipeline", type="primary", use_container_width=True)

    if run_btn:
        total_cost = 0.0
        pipeline_log = []

        st.divider()
        st.markdown("#### Pipeline Progress")

        # ── STAGE 1: Research ──────────────────────────────────────────────
        with st.status("🔍 Stage 1: Research", expanded=True) as s1:
            if not research_topic_input.strip():
                st.write("⏭ Skipped — no topic provided. Using existing research library.")
                s1.update(label="🔍 Stage 1: Research — Skipped", state="complete")
                pipeline_log.append(("Research", "skipped", 0.0, None))
            else:
                st.write(f"Searching: **{research_topic_input}**")
                result = research_topic(
                    topic=research_topic_input.strip(),
                    product_id=product_id,
                    max_results=max_results,
                    min_relevance=min_relevance,
                    geography=geography,
                )
                cost = result.get("total_cost_estimate_usd", 0.0)
                total_cost += cost

                if result.get("error"):
                    st.error(f"Research failed: {result['error']}")
                    s1.update(label="🔍 Stage 1: Research — ❌ Failed", state="error")
                    pipeline_log.append(("Research", "failed", cost, result["error"]))
                    st.stop()
                else:
                    saved = result.get("items_saved", 0)
                    st.write(f"✅ Saved **{saved}** items | Cost: {_fmt_cost(cost)}")
                    s1.update(
                        label=f"🔍 Stage 1: Research — ✅ {saved} items | {_fmt_cost(cost)}",
                        state="complete"
                    )
                    pipeline_log.append(("Research", "ok", cost, None))

        # ── STAGE 2: Strategy ──────────────────────────────────────────────
        with st.status("📐 Stage 2: Strategy", expanded=True) as s2:
            st.write("Proposing story angles from research library…")
            result = propose_story_angles(
                product_id=product_id,
                min_relevance=min_relevance,
                max_angles=max_angles,
                focus=focus_input.strip() or None,
            )
            cost = result.get("est_cost_usd", 0.0)
            total_cost += cost

            if result.get("error"):
                st.error(f"Strategy failed: {result['error']}")
                s2.update(label="📐 Stage 2: Strategy — ❌ Failed", state="error")
                pipeline_log.append(("Strategy", "failed", cost, result["error"]))
                st.stop()
            else:
                n = result.get("angles_proposed", 0)
                st.write(f"✅ Proposed **{n}** angles | Cost: {_fmt_cost(cost)}")
                if result.get("warnings"):
                    for w in result["warnings"]:
                        st.caption(f"⚠️ {w}")
                s2.update(
                    label=f"📐 Stage 2: Strategy — ✅ {n} angles | {_fmt_cost(cost)}",
                    state="complete"
                )
                pipeline_log.append(("Strategy", "ok", cost, None))

        st.warning(
            "⏸ **Strategy complete.** Go to **Approval Inbox** to approve angles. "
            "The Inbox will auto-generate drafts, run Editor, and create image prompts "
            "when you approve each angle."
        )
        st.info(f"💡 Total cost so far: **{_fmt_cost(total_cost)}**")
        st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — INDIVIDUAL STAGE RUNNER
# ══════════════════════════════════════════════════════════════════════════════

with tab_stage:
    st.subheader("Run Individual Stage")
    st.caption("Pick up from any stage. Each stage is independent.")

    stage = st.radio(
        "Select stage to run",
        [
            "🔍 Research",
            "📐 Strategy",
            "✍️ Drafts (all approved angles)",
            "🔎 Editor (all unreviewed drafts)",
            "📸 Media (all drafts without brief)",
        ],
        horizontal=False,
    )

    st.divider()

    # ── Research ──────────────────────────────────────────────────────────
    if stage == "🔍 Research":
        st.markdown("#### Research Stage")
        topic_s   = st.text_input("Topic to research", key="s_topic")
        geo_s     = st.selectbox("Geography", list(GEOGRAPHY_OPTIONS.keys()), key="s_geo")
        max_r_s   = st.slider("Max items", 3, 12, 6, key="s_maxr")
        min_rel_s = st.slider("Min relevance", 5, 10, 7, key="s_minrel")

        if st.button("Run Research", type="primary", key="btn_research"):
            if not topic_s.strip():
                st.error("Enter a topic first.")
            else:
                with st.spinner("Searching the web…"):
                    result = research_topic(
                        topic=topic_s.strip(),
                        product_id=product_id,
                        max_results=max_r_s,
                        min_relevance=min_rel_s,
                        geography=geo_s,
                    )
                if result.get("error"):
                    st.error(f"Failed: {result['error']}")
                else:
                    st.success(
                        f"✅ Saved **{result['items_saved']}** items · "
                        f"Cost: {_fmt_cost(result['total_cost_estimate_usd'])}"
                    )
                    if result.get("rejection_summary"):
                        st.caption(f"Rejected: {result['rejection_summary']}")

    # ── Strategy ──────────────────────────────────────────────────────────
    elif stage == "📐 Strategy":
        st.markdown("#### Strategy Stage")
        max_a_s    = st.slider("Max angles", 4, 20, 10, key="s_maxa")
        min_rel_s2 = st.slider("Min relevance", 5, 10, 7, key="s_minrel2")
        focus_s    = st.text_input("Optional editorial focus", key="s_focus")

        if st.button("Run Strategy", type="primary", key="btn_strategy"):
            with st.spinner("Clustering research into story angles…"):
                result = propose_story_angles(
                    product_id=product_id,
                    min_relevance=min_rel_s2,
                    max_angles=max_a_s,
                    focus=focus_s.strip() or None,
                )
            if result.get("error"):
                st.error(f"Failed: {result['error']}")
            else:
                st.success(
                    f"✅ Proposed **{result['angles_proposed']}** angles across "
                    f"**{result['themes_identified']}** themes · "
                    f"Cost: {_fmt_cost(result['est_cost_usd'])}"
                )
                if result.get("warnings"):
                    for w in result["warnings"]:
                        st.caption(f"⚠️ {w}")
                st.info("Go to **Approval Inbox** to approve angles and auto-generate drafts.")

    # ── Drafts ────────────────────────────────────────────────────────────
    elif stage == "✍️ Drafts (all approved angles)":
        st.markdown("#### Drafts Stage")
        st.caption("Generates 2 variants per platform for every approved angle without existing drafts.")

        with get_connection() as conn:
            approved_count = conn.execute(
                """SELECT COUNT(*) FROM story_angles
                   WHERE product_id = ? AND status IN ('approved','edited')
                     AND NOT EXISTS (SELECT 1 FROM drafts d WHERE d.story_angle_id = story_angles.id)""",
                (product_id,)
            ).fetchone()[0]

        st.metric("Approved angles without drafts", approved_count)

        if approved_count == 0:
            st.info("Nothing to draft. Either no approved angles, or all angles already have drafts.")
        else:
            est_usd = approved_count * 0.08
            st.markdown(f"**Estimated cost:** ~{_fmt_cost(est_usd)} (rough estimate)")
            if st.button("Run Drafts", type="primary", key="btn_drafts"):
                with st.spinner(f"Writing drafts for {approved_count} angle(s)…"):
                    result = write_drafts_for_all_approved(product_id)
                if result.get("errors"):
                    for e in result["errors"]:
                        st.error(e)
                st.success(
                    f"✅ Created **{result['drafts_created']}** drafts across "
                    f"**{result['angles_processed']}** angles · "
                    f"Cost: {_fmt_cost(result['total_cost_usd'])}"
                )
                if result.get("warnings"):
                    with st.expander("Warnings"):
                        for w in result["warnings"]:
                            st.caption(f"⚠️ {w}")

    # ── Editor ────────────────────────────────────────────────────────────
    elif stage == "🔎 Editor (all unreviewed drafts)":
        st.markdown("#### Editor Stage")
        st.caption("Reviews all drafts that have never been reviewed.")

        unreviewed = count_unreviewed_drafts(product_id)
        st.metric("Unreviewed drafts", unreviewed)

        if unreviewed == 0:
            st.info("All drafts have been reviewed.")
        else:
            est_usd = unreviewed * 0.027
            st.markdown(f"**Estimated cost:** ~{_fmt_cost(est_usd)}")
            if st.button("Run Editor", type="primary", key="btn_editor"):
                draft_ids = _get_unreviewed_draft_ids(product_id)
                progress  = st.progress(0, text="Reviewing drafts…")
                clean_n, flagged_n, failed_n = 0, 0, 0
                total_cost = 0.0

                for i, draft_id in enumerate(draft_ids):
                    result = review_draft(draft_id)
                    total_cost += result.get("est_cost_usd", 0.0)
                    if result.get("error"):
                        failed_n += 1
                    elif result.get("verdict") == "clean":
                        clean_n += 1
                    else:
                        flagged_n += 1
                    progress.progress(
                        (i + 1) / len(draft_ids),
                        text=f"Reviewing draft {i+1}/{len(draft_ids)}…"
                    )

                progress.empty()
                st.success(
                    f"✅ Reviewed **{len(draft_ids)}** drafts · "
                    f"Clean: {clean_n} · Flagged: {flagged_n} · Failed: {failed_n} · "
                    f"Cost: {_fmt_cost(total_cost)}"
                )
                if flagged_n > 0:
                    st.info("Go to **Editor** page to review flagged drafts, or use **Approval Inbox**.")

    # ── Media ────────────────────────────────────────────────────────────
    elif stage == "📸 Media (all drafts without brief)":
        st.markdown("#### Media Stage")
        st.caption("Generates image prompts for all drafts that don't have one yet.")

        with get_connection() as conn:
            without_brief = conn.execute(
                """SELECT COUNT(*) FROM drafts d
                   LEFT JOIN media_briefs mb ON mb.draft_id = d.id
                   WHERE d.product_id = ? AND mb.id IS NULL""",
                (product_id,)
            ).fetchone()[0]

        st.metric("Drafts without media brief", without_brief)

        if without_brief == 0:
            st.info("All drafts have media briefs.")
        else:
            st.markdown("**Cost: Free** (Media briefs use zero-cost templates)")
            if st.button("Run Media", type="primary", key="btn_media"):
                with st.spinner(f"Generating briefs for {without_brief} draft(s)…"):
                    result = generate_all_pending(product_id, force=False)

                st.success(
                    f"✅ Generated: **{result['generated']}** · "
                    f"Skipped (no image note): {result.get('skipped_no_source', 0)} · "
                    f"Failed: {result['failed']} · "
                    f"Cost: Free"
                )
                if result.get("errors"):
                    with st.expander("Errors"):
                        for e in result["errors"]:
                            st.error(e)
                if result["generated"] > 0:
                    st.info("Go to **Media Studio → Library** to approve the new briefs.")

    st.divider()

    # ── What's next nudge ─────────────────────────────────────────────────
    st.markdown("#### What's next?")
    unscheduled = get_approved_unscheduled_drafts(product_id)
    if unscheduled:
        st.warning(
            f"**{len(unscheduled)} approved draft(s)** are ready to schedule. "
            "Go to **Calendar → Schedule a Draft** or use **Approval Inbox**."
        )
    else:
        st.info("Pipeline is up to date. Check Calendar for scheduled posts.")