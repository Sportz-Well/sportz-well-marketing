"""Editor module — Editor agent UI (Prompt 6).

Three tabs:
  A. Review Draft        — pick draft, Review (cached) or Re-review (force API)
  B. Reviews Library     — filters, grouped by draft, full review-history audit trail
  C. Pipeline Overview   — review coverage, verdict distribution, top issue codes,
                           plus Editor spend ticker at the bottom

Editor is V1 flag-only: identifies issues, no rewrites, no Approve/Reject actions
in this page. The human decides what to do downstream.

Run from the project root:  streamlit run ui/app.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from db.init_db import init_db
from services.brand_context import get_active_product
from services.database import get_connection
from agents.editor import (
    get_last_run_info,
    count_unreviewed_drafts,
    count_reviews_total,
)

st.set_page_config(page_title="Editor — Sportz-Well", page_icon="🖊️", layout="wide")

init_db()


# ─── Badge helpers ────────────────────────────────────────────────────────────

_PLATFORM_BADGE: dict[str, str] = {
    "instagram": "📸 Instagram",
    "facebook":  "📘 Facebook",
}
_VERDICT_BADGE: dict[str, str] = {
    "clean":   "✅ Clean",
    "flagged": "🚩 Flagged",
}
_SEVERITY_BADGE: dict[str, str] = {
    "hard": "🔴 Hard",
    "soft": "🟡 Soft",
}


# ─── DB helpers (UI-page local, per Strategy precedent) ───────────────────────

def _safe_json_list(value: str | None) -> list:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _get_all_drafts_with_review_status(product_id: int) -> list[dict]:
    """Return every draft for this product, with a summary of its latest review (if any).

    Sort order: unreviewed first (NULLS FIRST), then most-recently-reviewed.
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    d.id              AS draft_id,
                    d.platform        AS platform,
                    d.variant_number  AS variant_number,
                    d.content_format  AS content_format,
                    d.story_angle_id  AS story_angle_id,
                    sa.angle_title    AS angle_title,
                    sa.title          AS angle_title_legacy,
                    latest.review_number  AS latest_review_number,
                    latest.verdict        AS latest_verdict,
                    latest.issues_json    AS latest_issues_json,
                    latest.reviewed_at    AS latest_reviewed_at,
                    total.review_count    AS review_count
                FROM drafts d
                LEFT JOIN story_angles sa ON sa.id = d.story_angle_id
                LEFT JOIN (
                    SELECT r1.draft_id, r1.review_number, r1.verdict,
                           r1.issues_json, r1.reviewed_at
                    FROM editor_reviews r1
                    JOIN (
                        SELECT draft_id, MAX(review_number) AS max_rn
                        FROM editor_reviews GROUP BY draft_id
                    ) r2 ON r2.draft_id = r1.draft_id AND r2.max_rn = r1.review_number
                ) latest ON latest.draft_id = d.id
                LEFT JOIN (
                    SELECT draft_id, COUNT(*) AS review_count
                    FROM editor_reviews GROUP BY draft_id
                ) total ON total.draft_id = d.id
                WHERE d.product_id = ?
                ORDER BY
                    CASE WHEN latest.reviewed_at IS NULL THEN 0 ELSE 1 END,
                    latest.reviewed_at DESC,
                    d.id ASC
                """,
                (product_id,),
            ).fetchall()
    except Exception:
        return []

    result = []
    for row in rows:
        d = dict(row)
        d["issues"]       = _safe_json_list(d.get("latest_issues_json"))
        d["angle_title"]  = d.get("angle_title") or d.get("angle_title_legacy") or "—"
        d["review_count"] = int(d.get("review_count") or 0)
        result.append(d)
    return result


def _get_review_history(draft_id: int) -> list[dict]:
    """Return every review for this draft, oldest first."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT id, review_number, verdict, issues_json,
                          model_input_tokens, model_output_tokens, cost_usd, reviewed_at
                   FROM editor_reviews
                   WHERE draft_id = ?
                   ORDER BY review_number ASC""",
                (draft_id,),
            ).fetchall()
    except Exception:
        return []

    result = []
    for row in rows:
        d = dict(row)
        d["issues"] = _safe_json_list(d.get("issues_json"))
        result.append(d)
    return result


def _get_pipeline_stats(product_id: int) -> dict:
    """Aggregate stats for Tab C. Single trip to the DB per logical view."""
    stats = {
        "total_drafts":          0,
        "unreviewed":            0,
        "reviewed":              0,
        "clean":                 0,
        "flagged":               0,
        "total_reviews":         0,
        "drafts_re_reviewed":    0,
        "issue_codes":           Counter(),
        "issue_severities":      Counter(),
    }

    try:
        with get_connection() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) FROM drafts WHERE product_id = ?", (product_id,)
            ).fetchone()
            stats["total_drafts"] = int(total_row[0])

            review_rows = conn.execute(
                """SELECT r.draft_id, r.verdict, r.issues_json, r.review_number
                   FROM editor_reviews r
                   JOIN drafts d ON d.id = r.draft_id
                   WHERE d.product_id = ?
                   ORDER BY r.draft_id, r.review_number""",
                (product_id,),
            ).fetchall()
    except Exception:
        return stats

    latest_by_draft: dict[int, dict] = {}
    review_counts:   dict[int, int]  = Counter()
    for row in review_rows:
        draft_id = row["draft_id"]
        review_counts[draft_id] += 1
        latest_by_draft[draft_id] = dict(row)  # last write wins → latest review_number

        for issue in _safe_json_list(row["issues_json"]):
            if isinstance(issue, dict):
                stats["issue_codes"][issue.get("code", "UNKNOWN")] += 1
                stats["issue_severities"][issue.get("severity", "unknown")] += 1

    stats["total_reviews"] = len(review_rows)
    stats["reviewed"]      = len(latest_by_draft)
    stats["unreviewed"]    = stats["total_drafts"] - stats["reviewed"]
    stats["drafts_re_reviewed"] = sum(1 for c in review_counts.values() if c > 1)

    for d in latest_by_draft.values():
        if d["verdict"] == "clean":
            stats["clean"] += 1
        elif d["verdict"] == "flagged":
            stats["flagged"] += 1

    return stats


def _get_editor_spend() -> dict:
    """Return Editor-specific spend stats from api_log.

    Shape:
        {
            "today_usd":     float,
            "month_usd":     float,
            "alltime_usd":   float,
            "total_calls":   int,
            "recent_calls":  list[dict],   # last 20, newest first
        }
    """
    stats = {
        "today_usd":    0.0,
        "month_usd":    0.0,
        "alltime_usd":  0.0,
        "total_calls":  0,
        "recent_calls": [],
    }

    now      = datetime.now(timezone.utc)
    today    = now.strftime("%Y-%m-%d")
    month    = now.strftime("%Y-%m")

    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT
                       COALESCE(SUM(CASE WHEN timestamp LIKE ? THEN est_cost_usd ELSE 0 END), 0) AS today,
                       COALESCE(SUM(CASE WHEN timestamp LIKE ? THEN est_cost_usd ELSE 0 END), 0) AS month,
                       COALESCE(SUM(est_cost_usd), 0) AS alltime,
                       COUNT(*) AS calls
                   FROM api_log
                   WHERE agent = 'editor'""",
                (f"{today}%", f"{month}%"),
            ).fetchone()
            stats["today_usd"]   = float(row["today"])
            stats["month_usd"]   = float(row["month"])
            stats["alltime_usd"] = float(row["alltime"])
            stats["total_calls"] = int(row["calls"])

            recent_rows = conn.execute(
                """SELECT timestamp, est_cost_usd, input_tokens, output_tokens, notes
                   FROM api_log
                   WHERE agent = 'editor'
                   ORDER BY timestamp DESC
                   LIMIT 20""",
            ).fetchall()
            stats["recent_calls"] = [dict(r) for r in recent_rows]
    except sqlite3.OperationalError:
        # api_log table missing — return zeros, no crash
        pass
    except Exception:
        pass

    return stats


def _draft_label(d: dict) -> str:
    """Format a draft as: #11 · 📘 Facebook V1 · Kirti angle title (40 chars)."""
    plat = _PLATFORM_BADGE.get(d["platform"], d["platform"])
    title = (d.get("angle_title") or "—")[:50]
    suffix = ""
    if d.get("latest_verdict"):
        suffix = f"  ·  {_VERDICT_BADGE.get(d['latest_verdict'], d['latest_verdict'])}"
    elif d.get("review_count", 0) == 0:
        suffix = "  ·  ⚪ Not reviewed"
    return f"#{d['draft_id']} · {plat} V{d['variant_number']} · {title}{suffix}"


def _render_issues(issues: list[dict], expanded: bool = True) -> None:
    """Render a list of issues grouped by severity. Used in Tab A and Tab B."""
    if not issues:
        st.success("No issues — draft is clean.", icon="✅")
        return

    hard_issues = [i for i in issues if i.get("severity") == "hard"]
    soft_issues = [i for i in issues if i.get("severity") == "soft"]

    if hard_issues:
        st.markdown(f"#### 🔴 Hard issues — {len(hard_issues)}")
        for issue in hard_issues:
            _render_single_issue(issue)

    if soft_issues:
        st.markdown(f"#### 🟡 Soft issues — {len(soft_issues)}")
        for issue in soft_issues:
            _render_single_issue(issue)


def _render_single_issue(issue: dict) -> None:
    code     = issue.get("code", "UNKNOWN")
    field    = issue.get("field", "—")
    evidence = issue.get("evidence", "")
    message  = issue.get("message", "")
    severity = issue.get("severity", "soft")

    border_color = "#dc3545" if severity == "hard" else "#ffc107"
    bg_color     = "#fff5f5" if severity == "hard" else "#fffbf0"

    st.markdown(
        f"""
        <div style="
            border-left: 4px solid {border_color};
            background: {bg_color};
            padding: 0.6rem 0.9rem;
            margin-bottom: 0.5rem;
            border-radius: 4px;
        ">
            <div style="font-weight: 600; font-size: 0.95rem;">
                <code style="background: rgba(0,0,0,0.05); padding: 1px 6px; border-radius: 3px;">
                    {code}
                </code>
                &nbsp;<span style="color: #666;">in {field}</span>
            </div>
            <div style="margin-top: 0.4rem; font-size: 0.9rem;">{message}</div>
            <div style="margin-top: 0.3rem; font-size: 0.85rem; color: #555;">
                <span style="color: #888;">Evidence:</span>
                <em>{evidence}</em>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("🖊️ Editor")
st.caption("Review Copywriter drafts against brand voice, format, and platform rules.")

product = get_active_product()
if product is None:
    st.error("No active client found. Go to **Brand Brain → Tab D** to seed Sportz-Well / SWPI first.")
    st.stop()

product_id = product["product_id"]

tab_a, tab_b, tab_c = st.tabs(["Review Draft", "Reviews Library", "Pipeline Overview"])


# ─── TAB A — Review Draft ────────────────────────────────────────────────────

with tab_a:
    st.info(
        "**Cost heads-up:** Each new review costs approximately **$0.02 – $0.08** "
        "(pure reasoning, no web search). Cached reviews are free.",
        icon="💰",
    )

    last_run = get_last_run_info(product_id)
    if last_run and last_run["failed"]:
        st.warning(
            f"⚠ Last run failed and cost **${last_run['cost']:.4f}** — "
            "see `data/editor_failed_responses.log` for the full raw response.",
            icon="⚠️",
        )

    drafts = _get_all_drafts_with_review_status(product_id)

    if not drafts:
        st.warning(
            "No drafts found for this product. Run the Copywriter first to generate drafts.",
            icon="⚠️",
        )
    else:
        unreviewed_n = sum(1 for d in drafts if d["review_count"] == 0)
        st.caption(
            f"{len(drafts)} draft{'s' if len(drafts) != 1 else ''} total · "
            f"{unreviewed_n} not yet reviewed"
        )

        # ── Draft picker ──
        draft_options = {_draft_label(d): d for d in drafts}
        selected_label = st.selectbox(
            "Pick a draft to review",
            options=list(draft_options.keys()),
            key="tab_a_draft_picker",
        )
        selected = draft_options[selected_label]
        selected_id = selected["draft_id"]

        # ── Status under picker ──
        rc = selected["review_count"]
        if rc == 0:
            st.info("Not yet reviewed. Click **Review** to run the editor on this draft.",
                    icon="🆕")
        else:
            verdict = selected.get("latest_verdict") or "?"
            verdict_badge = _VERDICT_BADGE.get(verdict, verdict)
            st.info(
                f"Already reviewed — **{rc} review{'s' if rc != 1 else ''}** in history. "
                f"Latest verdict: {verdict_badge}",
                icon="📋",
            )

        # ── Two buttons ──
        col_review, col_rereview, _ = st.columns([1, 1, 3])

        with col_review:
            review_btn = st.button(
                "Review (cached if exists)",
                type="primary",
                key="tab_a_review_btn",
                help="Returns the latest existing review for free if one exists. "
                     "If no review exists, calls the API.",
            )

        with col_rereview:
            rereview_btn = st.button(
                "Re-review (force new API call)",
                type="secondary",
                key="tab_a_rereview_btn",
                help="Always calls the API and adds a new review row to the history. "
                     "Costs $0.02–$0.08.",
                disabled=(rc == 0),  # nothing to re-review if never reviewed
            )

        # ── Run handler ──
        result = None
        if review_btn:
            from agents.editor import review_draft
            with st.spinner(f"Reviewing draft #{selected_id}…"):
                result = review_draft(selected_id)
        elif rereview_btn:
            from agents.editor import rereview_draft
            with st.spinner(f"Re-reviewing draft #{selected_id} (new API call)…"):
                result = rereview_draft(selected_id)

        if result is not None:
            if result.get("error"):
                st.error(f"Review failed: {result['error']}")
            else:
                verdict      = result["verdict"]
                issues       = result["issues"]
                cost         = result["est_cost_usd"]
                review_num   = result["review_number"]
                hard_n       = sum(1 for i in issues if i.get("severity") == "hard")
                soft_n       = sum(1 for i in issues if i.get("severity") == "soft")

                cost_display = "Free (cached)" if cost == 0.0 else f"${cost:.4f}"
                verdict_badge = _VERDICT_BADGE.get(verdict, verdict or "?")

                st.success(
                    f"Done — Review #{review_num} · {verdict_badge} · "
                    f"{hard_n} hard, {soft_n} soft issue{'s' if (hard_n + soft_n) != 1 else ''} · "
                    f"Cost: **{cost_display}**"
                )

                st.markdown("---")
                _render_issues(issues)


# ─── TAB B — Reviews Library ─────────────────────────────────────────────────

with tab_b:
    all_drafts = _get_all_drafts_with_review_status(product_id)

    if not all_drafts:
        st.info(
            "No drafts to review yet. Run the Copywriter first.",
            icon="ℹ️",
        )
    else:
        # ── Filters ──
        col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 2])

        with col_f1:
            verdict_opts = ["All", "Clean", "Flagged", "Not reviewed"]
            verdict_filter = st.selectbox("Verdict", verdict_opts, key="lib_verdict")

        with col_f2:
            platform_opts = ["All", "Instagram", "Facebook"]
            platform_filter = st.selectbox("Platform", platform_opts, key="lib_platform")

        with col_f3:
            severity_opts = ["All", "Has hard issues", "Has soft only", "No issues"]
            severity_filter = st.selectbox("Issues", severity_opts, key="lib_severity")

        with col_f4:
            sort_opts = ["Newest review first", "Draft ID asc", "Verdict (flagged first)"]
            sort_by = st.selectbox("Sort by", sort_opts, key="lib_sort")

        # ── Apply filters ──
        filtered = all_drafts

        if verdict_filter == "Clean":
            filtered = [d for d in filtered if d.get("latest_verdict") == "clean"]
        elif verdict_filter == "Flagged":
            filtered = [d for d in filtered if d.get("latest_verdict") == "flagged"]
        elif verdict_filter == "Not reviewed":
            filtered = [d for d in filtered if d["review_count"] == 0]

        if platform_filter != "All":
            filtered = [d for d in filtered if d["platform"] == platform_filter.lower()]

        if severity_filter == "Has hard issues":
            filtered = [d for d in filtered
                        if any(i.get("severity") == "hard" for i in d["issues"])]
        elif severity_filter == "Has soft only":
            filtered = [d for d in filtered
                        if d["issues"] and not any(i.get("severity") == "hard" for i in d["issues"])]
        elif severity_filter == "No issues":
            filtered = [d for d in filtered
                        if d.get("latest_verdict") == "clean"]

        # ── Sort ──
        if sort_by == "Draft ID asc":
            filtered = sorted(filtered, key=lambda d: d["draft_id"])
        elif sort_by == "Verdict (flagged first)":
            order = {"flagged": 0, "clean": 1, None: 2}
            filtered = sorted(filtered, key=lambda d: order.get(d.get("latest_verdict"), 3))
        # Newest review first is already the default DB sort order

        st.caption(f"{len(filtered)} draft{'s' if len(filtered) != 1 else ''} shown")

        if not filtered:
            st.info("No drafts match the current filters.", icon="🔍")

        for d in filtered:
            draft_id = d["draft_id"]
            verdict  = d.get("latest_verdict")
            verdict_badge = (
                _VERDICT_BADGE.get(verdict, verdict)
                if verdict else "⚪ Not reviewed"
            )
            platform = _PLATFORM_BADGE.get(d["platform"], d["platform"])
            title    = d.get("angle_title") or "—"
            rc       = d["review_count"]

            issues = d["issues"]
            hard_n = sum(1 for i in issues if i.get("severity") == "hard")
            soft_n = sum(1 for i in issues if i.get("severity") == "soft")

            issue_summary = ""
            if rc > 0:
                if hard_n + soft_n == 0:
                    issue_summary = " — clean"
                else:
                    parts = []
                    if hard_n:
                        parts.append(f"{hard_n} hard")
                    if soft_n:
                        parts.append(f"{soft_n} soft")
                    issue_summary = " — " + ", ".join(parts)

            review_label = (
                f"{rc} review{'s' if rc != 1 else ''}"
                if rc > 0 else "no reviews yet"
            )

            with st.expander(
                f"**#{draft_id}** · {platform} V{d['variant_number']} · {title}  "
                f"&nbsp;&nbsp;{verdict_badge}{issue_summary}  "
                f"·  {review_label}",
                expanded=False,
            ):
                if rc == 0:
                    st.caption("This draft has no reviews yet. Go to **Review Draft** tab to run one.")
                else:
                    # ── Latest review issues ──
                    st.markdown(
                        f"##### Latest review (#{d['latest_review_number']}) · "
                        f"{d.get('latest_reviewed_at', '—')}"
                    )
                    _render_issues(issues)

                    # ── Full audit trail ──
                    if rc > 1:
                        with st.expander(f"📜 Full review history ({rc} reviews)"):
                            history = _get_review_history(draft_id)
                            for h in history:
                                h_verdict = _VERDICT_BADGE.get(h["verdict"], h["verdict"])
                                cost_str  = (
                                    f"${h['cost_usd']:.4f}"
                                    if h.get("cost_usd") else "—"
                                )
                                st.markdown(
                                    f"**Review #{h['review_number']}** · "
                                    f"{h_verdict} · "
                                    f"{h.get('reviewed_at', '—')} · "
                                    f"{cost_str}"
                                )
                                if h["issues"]:
                                    _render_issues(h["issues"])
                                else:
                                    st.caption("No issues.")
                                st.markdown("---")

                    # ── Re-review button ──
                    col_rr, _ = st.columns([1, 4])
                    with col_rr:
                        if st.button(
                            "🔄 Re-review",
                            key=f"rereview_lib_{draft_id}",
                            help="Force a new API call. Adds a new review row to history.",
                        ):
                            from agents.editor import rereview_draft
                            with st.spinner(f"Re-reviewing draft #{draft_id}…"):
                                rereview_draft(draft_id)
                            st.rerun()


# ─── TAB C — Pipeline Overview ───────────────────────────────────────────────

with tab_c:
    stats = _get_pipeline_stats(product_id)

    if stats["total_drafts"] == 0:
        st.info(
            "No drafts in the pipeline yet. Run the Copywriter to populate this view.",
            icon="ℹ️",
        )
    else:
        # ── Review coverage ──
        st.markdown("### Review coverage")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total drafts",  stats["total_drafts"])
        c2.metric("Reviewed",      stats["reviewed"])
        c3.metric("Unreviewed",    stats["unreviewed"])
        c4.metric("Total reviews", stats["total_reviews"],
                  help="Includes re-reviews (one draft can have multiple).")

        if stats["unreviewed"] > 0:
            st.warning(
                f"**{stats['unreviewed']} draft{'s' if stats['unreviewed'] != 1 else ''}** "
                "not yet reviewed. Head to **Review Draft** tab to work through them.",
                icon="📋",
            )

        st.divider()

        # ── Verdict distribution ──
        st.markdown("### Verdict distribution (latest review per draft)")
        col_v1, col_v2, col_v3 = st.columns(3)
        col_v1.metric("✅ Clean",   stats["clean"])
        col_v2.metric("🚩 Flagged", stats["flagged"])

        clean_pct = (
            round(100 * stats["clean"] / stats["reviewed"])
            if stats["reviewed"] else 0
        )
        col_v3.metric("Clean rate", f"{clean_pct}%",
                      help="% of reviewed drafts that came back clean.")

        st.divider()

        # ── Issue severity breakdown ──
        if stats["issue_severities"]:
            st.markdown("### All issues — severity breakdown")
            col_s1, col_s2 = st.columns(2)
            col_s1.metric("🔴 Hard issues", stats["issue_severities"].get("hard", 0))
            col_s2.metric("🟡 Soft issues", stats["issue_severities"].get("soft", 0))
            st.caption("Counts include duplicates across re-reviews.")

            st.divider()

        # ── Top issue codes ──
        if stats["issue_codes"]:
            st.markdown("### Most common issue codes")
            st.caption(
                "Useful signal for tuning the Copywriter system prompt — recurring codes "
                "indicate systemic gaps."
            )
            top = stats["issue_codes"].most_common(10)
            for code, count in top:
                st.markdown(f"- **`{code}`** — {count} occurrence{'s' if count != 1 else ''}")

        # ── Drafts re-reviewed ──
        if stats["drafts_re_reviewed"] > 0:
            st.divider()
            st.markdown("### Drafts re-reviewed")
            n = stats["drafts_re_reviewed"]
            verb = "has" if n == 1 else "have"
            st.warning(
                f"**{n} draft{'s' if n != 1 else ''}** {verb} been reviewed more than once. "
                "Filter the Library by Draft ID to inspect the history — repeated re-reviews "
                "suggest persistent issues or instability.",
                icon="🔄",
            )

        # ── Editor spend ──
        st.divider()
        st.markdown("### 💸 Editor spend")

        spend = _get_editor_spend()

        col_sp1, col_sp2, col_sp3, col_sp4 = st.columns(4)
        col_sp1.metric("Today",      f"${spend['today_usd']:.4f}")
        col_sp2.metric("This month", f"${spend['month_usd']:.4f}")
        col_sp3.metric("All time",   f"${spend['alltime_usd']:.4f}")
        col_sp4.metric(
            "Total calls", spend["total_calls"],
            help="Total Editor API calls (success + failure)."
        )

        if spend["total_calls"] > 0:
            avg_cost = spend["alltime_usd"] / spend["total_calls"]
            st.caption(f"Average cost per call: **${avg_cost:.4f}**")

        # ── Recent calls table ──
        if spend["recent_calls"]:
            with st.expander(f"Recent {len(spend['recent_calls'])} Editor calls"):
                for call in spend["recent_calls"]:
                    ts        = call.get("timestamp") or "—"
                    cost_usd  = call.get("est_cost_usd") or 0.0
                    in_tok    = call.get("input_tokens") or 0
                    out_tok   = call.get("output_tokens") or 0
                    notes     = (call.get("notes") or "")[:120]
                    failed    = notes.startswith("FAILURE:") or notes.startswith("ERROR:")
                    status_icon = "❌" if failed else "✅"

                    st.markdown(
                        f"{status_icon} `{ts}` · **${cost_usd:.4f}** · "
                        f"{in_tok:,} in / {out_tok:,} out tokens"
                    )
                    st.caption(notes if notes else "—")
                    st.markdown("---")
        else:
            st.caption("No Editor API calls logged yet.")