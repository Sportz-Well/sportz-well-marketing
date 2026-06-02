"""Strategy module — Strategist agent UI (Prompt 4).

Three tabs:
  A. Run Strategist  — controls + run button + results banner
  B. Story Angles Library — filters, grouped by theme, approve/reject/edit cards
  C. Pipeline Overview   — counts, platform breakdown, distribution charts

Run from the project root:  streamlit run ui/app.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from services.page_utils import init_page
from services.brand_context import get_active_product
from services.database import get_connection
from agents.strategist import count_research_items, count_approved_angles, get_last_run_info

st.set_page_config(page_title="Strategy — Sportz-Well", page_icon="🎯", layout="wide")

init_page()


# ─── Badge helpers ────────────────────────────────────────────────────────────

_PLATFORM_BADGE: dict[str, str] = {
    "instagram": "📸 Instagram",
    "facebook":  "📘 Facebook",
    "both":      "📸📘 Both",
}
_PHASE_BADGE: dict[str, str] = {
    "phase_1":            "🟢 Phase 1",
    "phase_2_hint":       "🔵 Phase 2 Hint",
    "phase_3_hint":       "🟣 Phase 3 Hint",
    "founder_credibility":"🏅 Founder Cred",
    "evergreen":          "🌿 Evergreen",
}
_FUNNEL_BADGE: dict[str, str] = {
    "awareness":     "👁 Awareness",
    "consideration": "🤔 Consideration",
    "demo_pitch":    "📞 Demo Pitch",
}
_FORMAT_BADGE: dict[str, str] = {
    "single_image": "🖼 Single Image",
    "carousel":     "🎠 Carousel",
    "video_script": "🎬 Video Script",
    "text_post":    "📝 Text Post",
    "reel_script":  "🎥 Reel",
}
_CTA_BADGE: dict[str, str] = {
    "hard_cta": "🔴 Hard CTA",
    "soft_cta": "🟡 Soft CTA",
    "no_cta":   "🟢 No CTA",
}
_STATUS_COLOR: dict[str, str] = {
    "proposed": "🔵",
    "approved": "✅",
    "rejected": "❌",
    "edited":   "✏️",
}


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _get_all_angles(product_id: int) -> list[dict]:
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, theme, angle_title, angle_description, editorial_brief,
                       platform_fit, phase_tag, funnel_stage, content_format,
                       cta_strength, source_research_ids, proof_points_used,
                       status, user_notes, created_at, updated_at
                FROM story_angles
                WHERE product_id = ?
                ORDER BY theme, created_at
                """,
                (product_id,),
            ).fetchall()
    except Exception:
        return []

    result = []
    for row in rows:
        d = dict(row)
        d["source_research_ids"] = _safe_json_list(d.get("source_research_ids"))
        d["proof_points_used"]   = _safe_json_list(d.get("proof_points_used"))
        result.append(d)
    return result


def _safe_json_list(value: str | None) -> list:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _get_research_items_by_ids(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    try:
        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT id, source_title, title, source_url, final_url "
                f"FROM research_items WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _update_angle_status(angle_id: int, status: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        conn.execute(
            "UPDATE story_angles SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, angle_id),
        )


def _update_angle_edit(
    angle_id: int,
    angle_title: str,
    angle_description: str,
    editorial_brief: str,
    user_notes: str,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        conn.execute(
            """UPDATE story_angles
               SET angle_title = ?, title = ?, angle_description = ?, angle = ?,
                   editorial_brief = ?, user_notes = ?,
                   status = 'edited', updated_at = ?
               WHERE id = ?""",
            (angle_title, angle_title, angle_description, angle_description,
             editorial_brief, user_notes, now, angle_id),
        )


def _get_pipeline_stats(product_id: int) -> dict:
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT status, platform_fit, phase_tag, cta_strength, COUNT(*) AS n
                   FROM story_angles WHERE product_id = ?
                   GROUP BY status, platform_fit, phase_tag, cta_strength""",
                (product_id,),
            ).fetchall()
    except Exception:
        return {}

    stats: dict = {
        "total": 0,
        "by_status": {},
        "by_platform": {},
        "by_phase": {},
        "by_cta": {},
    }
    for row in rows:
        n          = row["n"]
        status     = row["status"] or "proposed"
        platform   = row["platform_fit"] or "both"
        phase      = row["phase_tag"] or "phase_1"
        cta        = row["cta_strength"] or "no_cta"

        stats["total"] += n
        stats["by_status"][status]   = stats["by_status"].get(status, 0)   + n
        stats["by_platform"][platform] = stats["by_platform"].get(platform, 0) + n
        stats["by_phase"][phase]     = stats["by_phase"].get(phase, 0)     + n
        stats["by_cta"][cta]         = stats["by_cta"].get(cta, 0)         + n

    return stats


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("🎯 Strategy")
st.caption("Cluster research signals into actionable story angles for Instagram & Facebook.")

product = get_active_product()
if product is None:
    st.error("No active client found. Go to **Brand Brain → Tab D** to seed Sportz-Well / SWPI first.")
    st.stop()

product_id = product["product_id"]

tab_a, tab_b, tab_c = st.tabs(["Run Strategist", "Story Angles Library", "Pipeline Overview"])


# ─── TAB A — Run Strategist ───────────────────────────────────────────────────

with tab_a:
    st.info(
        "**Cost heads-up:** Each strategy run costs approximately **$0.05 – $0.15** "
        "(no web search — pure reasoning over your existing research library).",
        icon="💰",
    )

    # Show a warning if the most recent run for this product failed
    last_run = get_last_run_info(product_id)
    if last_run and last_run["failed"]:
        st.warning(
            f"⚠ Last run failed and cost **${last_run['cost']:.4f}** — "
            "see `data/strategist_failed_responses.log` for the full raw response.",
            icon="⚠️",
        )

    col_rel, col_ang = st.columns(2)

    with col_rel:
        min_rel = st.slider(
            "Minimum relevance score",
            min_value=1, max_value=10, value=7,
            help="Only research items at or above this score feed into the strategist.",
            key="tab_a_min_rel",
        )

    with col_ang:
        max_ang = st.slider(
            "Max angles to propose",
            min_value=5, max_value=20, value=12,
            help="The model will propose up to this many angles across all themes.",
            key="tab_a_max_ang",
        )

    n_available = count_research_items(product_id, min_rel)
    if n_available == 0:
        st.warning(
            f"**No research items** found at min relevance ≥ {min_rel}. "
            "Lower the slider or run the Researcher first.",
            icon="⚠️",
        )
    else:
        st.success(
            f"**{n_available} research item{'s' if n_available != 1 else ''}** available "
            f"at min relevance ≥ {min_rel}.",
            icon="📚",
        )

    focus_input = st.text_input(
        "Editorial focus (optional)",
        placeholder="e.g. lean into parent communication this round",
        help="Leave blank to draw on the full research library without bias.",
        key="tab_a_focus",
    )

    run_btn = st.button(
        "Propose Story Angles",
        type="primary",
        disabled=(n_available == 0),
    )

    if run_btn:
        from agents.strategist import propose_story_angles

        with st.spinner(
            f"Strategising over {n_available} research items "
            f"(max {max_ang} angles, min relevance ≥ {min_rel})…"
        ):
            result = propose_story_angles(
                product_id=product_id,
                min_relevance=min_rel,
                max_angles=max_ang,
                focus=focus_input.strip() or None,
            )

        if result.get("error"):
            st.error(f"Strategy run failed: {result['error']}")
        else:
            themes_n = result["themes_identified"]
            angles_n = result["angles_proposed"]
            cost     = result["est_cost_usd"]
            warnings = result.get("warnings", [])

            st.success(
                f"Done — **{themes_n} theme{'s' if themes_n != 1 else ''}** identified, "
                f"**{angles_n} angle{'s' if angles_n != 1 else ''}** proposed. "
                f"Estimated cost: **${cost:.4f}**"
            )
            for w in warnings:
                st.warning(w, icon="⚠️")

            if angles_n > 0:
                st.caption(
                    "Switch to **Story Angles Library** to review, approve, reject, or edit."
                )


# ─── TAB B — Story Angles Library ────────────────────────────────────────────

with tab_b:
    all_angles = _get_all_angles(product_id)

    if not all_angles:
        st.info(
            "No story angles yet. Run the Strategist in **Run Strategist** tab to generate angles.",
            icon="ℹ️",
        )
    else:
        # ── Filters ──
        col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns([2, 2, 2, 2, 2])

        with col_f1:
            status_opts = ["All", "Proposed", "Approved", "Rejected", "Edited"]
            status_filter = st.selectbox("Status", status_opts, key="lib_status")

        with col_f2:
            platform_opts = ["All", "Instagram", "Facebook", "Both"]
            platform_filter = st.selectbox("Platform", platform_opts, key="lib_platform")

        with col_f3:
            all_phases = sorted({a["phase_tag"] for a in all_angles if a.get("phase_tag")})
            phase_opts = ["All"] + all_phases
            phase_filter = st.selectbox("Phase tag", phase_opts, key="lib_phase")

        with col_f4:
            all_funnel = sorted({a["funnel_stage"] for a in all_angles if a.get("funnel_stage")})
            funnel_opts = ["All"] + all_funnel
            funnel_filter = st.selectbox("Funnel stage", funnel_opts, key="lib_funnel")

        with col_f5:
            sort_by = st.selectbox(
                "Sort by",
                ["Theme (default)", "Newest first", "Funnel stage"],
                key="lib_sort",
            )

        # ── Apply filters ──
        filtered = all_angles
        if status_filter != "All":
            filtered = [a for a in filtered if a["status"] == status_filter.lower()]
        if platform_filter != "All":
            pf_val = platform_filter.lower()
            filtered = [a for a in filtered if a.get("platform_fit") in (pf_val, "both")]
        if phase_filter != "All":
            filtered = [a for a in filtered if a.get("phase_tag") == phase_filter]
        if funnel_filter != "All":
            filtered = [a for a in filtered if a.get("funnel_stage") == funnel_filter]

        # ── Sorting ──
        if sort_by == "Newest first":
            filtered = sorted(filtered, key=lambda a: a.get("created_at") or "", reverse=True)
        elif sort_by == "Funnel stage":
            funnel_order = {"awareness": 0, "consideration": 1, "demo_pitch": 2}
            filtered = sorted(filtered, key=lambda a: funnel_order.get(a.get("funnel_stage", ""), 9))

        # ── Group by theme ──
        theme_groups: dict[str, list[dict]] = {}
        for angle in filtered:
            theme = angle.get("theme") or "Uncategorized"
            theme_groups.setdefault(theme, []).append(angle)

        st.caption(f"{len(filtered)} angle{'s' if len(filtered) != 1 else ''} shown")

        if not filtered:
            st.info("No angles match the current filters.", icon="🔍")

        for theme_name, angles in theme_groups.items():
            with st.expander(f"**{theme_name}** — {len(angles)} angle{'s' if len(angles) != 1 else ''}", expanded=True):
                for angle in angles:
                    angle_id = angle["id"]
                    edit_key = f"editing_{angle_id}"
                    title    = angle.get("angle_title") or "Untitled"
                    desc     = angle.get("angle_description") or ""
                    brief    = angle.get("editorial_brief") or ""
                    platform = angle.get("platform_fit", "both")
                    phase    = angle.get("phase_tag", "phase_1")
                    funnel   = angle.get("funnel_stage", "awareness")
                    fmt      = angle.get("content_format", "single_image")
                    cta      = angle.get("cta_strength", "no_cta")
                    status   = angle.get("status", "proposed")
                    notes    = angle.get("user_notes") or ""
                    src_ids  = angle.get("source_research_ids", [])
                    proofs   = angle.get("proof_points_used", [])

                    # Dim rejected angles
                    if status == "rejected":
                        st.markdown(f"~~**{title}**~~ {_STATUS_COLOR.get(status, '')} *{status}*")
                        continue

                    st.markdown(f"### {_STATUS_COLOR.get(status, '')} {title}")
                    st.markdown(desc)

                    # Badge row
                    st.markdown(
                        f"{_PLATFORM_BADGE.get(platform, platform)}  &nbsp; "
                        f"{_PHASE_BADGE.get(phase, phase)}  &nbsp; "
                        f"{_FUNNEL_BADGE.get(funnel, funnel)}  &nbsp; "
                        f"{_FORMAT_BADGE.get(fmt, fmt)}  &nbsp; "
                        f"{_CTA_BADGE.get(cta, cta)}"
                    )

                    # Sources and editorial brief expanders
                    col_src, col_brief = st.columns(2)

                    with col_src:
                        with st.expander(f"Sources ({len(src_ids)})"):
                            if src_ids:
                                source_items = _get_research_items_by_ids(
                                    [int(i) for i in src_ids if str(i).isdigit() or isinstance(i, int)]
                                )
                                if source_items:
                                    for si in source_items:
                                        si_title = si.get("source_title") or si.get("title") or "Untitled"
                                        si_url   = si.get("final_url") or si.get("source_url") or ""
                                        if si_url:
                                            st.markdown(f"- [{si_title}]({si_url})")
                                        else:
                                            st.markdown(f"- {si_title}")
                                else:
                                    st.caption("Source items not found in DB.")
                            else:
                                st.caption("No source research items linked.")

                    with col_brief:
                        with st.expander("Editorial brief"):
                            st.markdown(brief or "*No brief provided.*")
                            if proofs:
                                st.markdown("**Proof points to use:**")
                                for pp in proofs:
                                    st.markdown(f"- {pp}")
                            if notes:
                                st.caption(f"Notes: {notes}")

                    # ── Inline edit form ──
                    if st.session_state.get(edit_key):
                        with st.form(key=f"edit_form_{angle_id}"):
                            new_title = st.text_input("Angle title", value=title)
                            new_desc  = st.text_area("Angle description", value=desc, height=100)
                            new_brief = st.text_area("Editorial brief", value=brief, height=120)
                            new_notes = st.text_input("Notes", value=notes)
                            col_save, col_cancel = st.columns(2)
                            with col_save:
                                if st.form_submit_button("Save", type="primary"):
                                    _update_angle_edit(
                                        angle_id, new_title.strip(), new_desc.strip(),
                                        new_brief.strip(), new_notes.strip(),
                                    )
                                    st.session_state.pop(edit_key, None)
                                    st.rerun()
                            with col_cancel:
                                if st.form_submit_button("Cancel"):
                                    st.session_state.pop(edit_key, None)
                                    st.rerun()
                    else:
                        # ── Action buttons ──
                        col_approve, col_reject, col_edit, _ = st.columns([1, 1, 1, 3])

                        with col_approve:
                            if status != "approved":
                                if st.button("✅ Approve", key=f"approve_{angle_id}"):
                                    _update_angle_status(angle_id, "approved")
                                    st.rerun()
                            else:
                                st.success("Approved", icon="✅")

                        with col_reject:
                            if status != "rejected":
                                if st.button("❌ Reject", key=f"reject_{angle_id}"):
                                    _update_angle_status(angle_id, "rejected")
                                    st.rerun()

                        with col_edit:
                            if st.button("✏️ Edit", key=f"edit_{angle_id}"):
                                st.session_state[edit_key] = True
                                st.rerun()

                    st.divider()


# ─── TAB C — Pipeline Overview ────────────────────────────────────────────────

with tab_c:
    stats = _get_pipeline_stats(product_id)

    if not stats.get("total"):
        st.info(
            "No story angles in the pipeline yet. Run the Strategist to populate this view.",
            icon="ℹ️",
        )
    else:
        total = stats["total"]
        by_status   = stats["by_status"]
        by_platform = stats["by_platform"]
        by_phase    = stats["by_phase"]
        by_cta      = stats["by_cta"]

        # ── Total counts by status ──
        st.markdown("### Total angles")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total",    total)
        c2.metric("Proposed", by_status.get("proposed", 0))
        c3.metric("Approved", by_status.get("approved", 0))
        c4.metric("Edited",   by_status.get("edited", 0))
        c5.metric("Rejected", by_status.get("rejected", 0))

        st.divider()

        # ── Approved angles ready for Copywriter ──
        approved = by_status.get("approved", 0)
        if approved:
            st.success(
                f"**{approved} approved angle{'s' if approved != 1 else ''} ready for drafting.** "
                "Filter the Library to Approved to review them before passing to the Copywriter.",
                icon="✅",
            )

        # ── Platform breakdown (approved + edited only) ──
        st.markdown("### Approved & Edited — platform breakdown")
        col_p1, col_p2, col_p3 = st.columns(3)
        col_p1.metric("Instagram only", by_platform.get("instagram", 0))
        col_p2.metric("Facebook only",  by_platform.get("facebook", 0))
        col_p3.metric("Both platforms", by_platform.get("both", 0))

        st.divider()

        # ── Phase tag distribution ──
        st.markdown("### Phase tag distribution")
        st.caption(
            "Check that phase_2_hint + phase_3_hint total ≤ 1 per 20 angles "
            "(vision-hint quota). Green = compliant."
        )
        phase_order = ["phase_1", "founder_credibility", "evergreen", "phase_2_hint", "phase_3_hint"]
        phase_labels = {
            "phase_1": "Phase 1",
            "founder_credibility": "Founder Cred",
            "evergreen": "Evergreen",
            "phase_2_hint": "Phase 2 Hint ⚠️",
            "phase_3_hint": "Phase 3 Hint ⚠️",
        }
        ph_cols = st.columns(len(phase_order))
        for col, key in zip(ph_cols, phase_order):
            label = phase_labels.get(key, key)
            n     = by_phase.get(key, 0)
            col.metric(label, n)

        vision_total = by_phase.get("phase_2_hint", 0) + by_phase.get("phase_3_hint", 0)
        vision_limit = max(1, total // 20)
        if vision_total > vision_limit:
            st.error(
                f"Vision-hint quota exceeded: {vision_total} vision-hint angle(s) vs "
                f"limit of {vision_limit} for {total} total angles. "
                "Review and reject/edit the excess angles.",
                icon="🚨",
            )
        else:
            st.success(
                f"Vision-hint quota OK: {vision_total} vision-hint angle(s) "
                f"(limit {vision_limit} for {total} total).",
                icon="✅",
            )

        st.divider()

        # ── CTA strength distribution ──
        st.markdown("### CTA strength distribution")
        st.caption("Target: ~20% hard_cta · ~40% soft_cta · ~40% no_cta.")
        col_c1, col_c2, col_c3 = st.columns(3)
        hard_n = by_cta.get("hard_cta", 0)
        soft_n = by_cta.get("soft_cta", 0)
        none_n = by_cta.get("no_cta", 0)

        hard_pct = round(100 * hard_n / total) if total else 0
        soft_pct = round(100 * soft_n / total) if total else 0
        none_pct = round(100 * none_n / total) if total else 0

        col_c1.metric("Hard CTA 🔴", hard_n, f"{hard_pct}% (target ~20%)")
        col_c2.metric("Soft CTA 🟡", soft_n, f"{soft_pct}% (target ~40%)")
        col_c3.metric("No CTA 🟢",   none_n, f"{none_pct}% (target ~40%)")

        if hard_pct > 35:
            st.warning(
                f"Hard CTA proportion is {hard_pct}% — above the ~20% target. "
                "Consider rejecting some hard-CTA angles or rebalancing on the next run.",
                icon="⚠️",
            )
