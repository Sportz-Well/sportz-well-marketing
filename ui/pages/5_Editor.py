"""Editor module — Editor agent UI (Prompt 6).

Three tabs:
  A. Review Draft  — bulk review all unreviewed in one click; individual review
                     shows full draft content on the SAME screen — no back-and-forth
  B. Reviews Library — filters, grouped by draft, full review-history audit trail
  C. Pipeline Overview — coverage, verdict distribution, issue codes, spend ticker

Editor is V1 flag-only: identifies issues, never rewrites.
The human decides what to do in Drafts after reviewing here.

Run from the project root:  streamlit run ui/app.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from services.page_utils import init_page, format_cost_inr
from services.brand_context import get_active_product
from services.database import get_connection
from agents.editor import (
    get_last_run_info,
    count_unreviewed_drafts,
    count_reviews_total,
    review_draft,
    rereview_draft,
)

st.set_page_config(page_title="Editor — Sportz-Well", page_icon="🖊️", layout="wide")
init_page()


# ─── Badge helpers ────────────────────────────────────────────────────────────

_PLATFORM_BADGE: dict[str, str] = {
    "instagram": "📸 Instagram",
    "facebook":  "📘 Facebook",
    "linkedin":  "💼 LinkedIn",
}
_VERDICT_BADGE: dict[str, str] = {
    "clean":   "✅ Clean",
    "flagged": "🚩 Flagged",
}


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _safe_json_list(value: str | None) -> list:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _get_draft_content(draft_id: int) -> dict | None:
    """Fetch full post content for display in the review panel."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT d.headline, d.body, d.cta_line, d.hashtags,
                          d.platform, d.variant_number, d.word_count,
                          sa.angle_title
                   FROM drafts d
                   LEFT JOIN story_angles sa ON sa.id = d.story_angle_id
                   WHERE d.id = ?""",
                (draft_id,),
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def _get_all_drafts_with_review_status(
    product_id: int,
    exclude_posted: bool = True,
) -> list[dict]:
    posted_filter = """
        AND NOT EXISTS (
            SELECT 1 FROM schedule s
            WHERE s.draft_id = d.id AND s.posted_at IS NOT NULL
        )
    """ if exclude_posted else ""

    try:
        with get_connection() as conn:
            rows = conn.execute(
                f"""
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
                {posted_filter}
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
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT id, review_number, verdict, issues_json,
                          model_input_tokens, model_output_tokens, cost_usd, reviewed_at
                   FROM editor_reviews WHERE draft_id = ?
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
    stats = {
        "total_drafts": 0, "unreviewed": 0, "reviewed": 0,
        "clean": 0, "flagged": 0, "total_reviews": 0,
        "drafts_re_reviewed": 0,
        "issue_codes": Counter(), "issue_severities": Counter(),
    }
    try:
        with get_connection() as conn:
            stats["total_drafts"] = int(conn.execute(
                "SELECT COUNT(*) FROM drafts WHERE product_id = ?", (product_id,)
            ).fetchone()[0])
            review_rows = conn.execute(
                """SELECT r.draft_id, r.verdict, r.issues_json, r.review_number
                   FROM editor_reviews r JOIN drafts d ON d.id = r.draft_id
                   WHERE d.product_id = ? ORDER BY r.draft_id, r.review_number""",
                (product_id,),
            ).fetchall()
    except Exception:
        return stats

    latest_by_draft: dict[int, dict] = {}
    review_counts:   dict[int, int]  = Counter()
    for row in review_rows:
        did = row["draft_id"]
        review_counts[did] += 1
        latest_by_draft[did] = dict(row)
        for issue in _safe_json_list(row["issues_json"]):
            if isinstance(issue, dict):
                stats["issue_codes"][issue.get("code", "UNKNOWN")] += 1
                stats["issue_severities"][issue.get("severity", "unknown")] += 1

    stats["total_reviews"]      = len(review_rows)
    stats["reviewed"]           = len(latest_by_draft)
    stats["unreviewed"]         = stats["total_drafts"] - stats["reviewed"]
    stats["drafts_re_reviewed"] = sum(1 for c in review_counts.values() if c > 1)
    for d in latest_by_draft.values():
        if d["verdict"] == "clean":    stats["clean"]   += 1
        elif d["verdict"] == "flagged": stats["flagged"] += 1
    return stats


def _get_editor_spend() -> dict:
    stats = {"today_usd": 0.0, "month_usd": 0.0, "alltime_usd": 0.0,
             "total_calls": 0, "recent_calls": []}
    now   = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT
                   COALESCE(SUM(CASE WHEN timestamp LIKE ? THEN est_cost_usd ELSE 0 END),0) AS today,
                   COALESCE(SUM(CASE WHEN timestamp LIKE ? THEN est_cost_usd ELSE 0 END),0) AS month,
                   COALESCE(SUM(est_cost_usd),0) AS alltime, COUNT(*) AS calls
                   FROM api_log WHERE agent = 'editor'""",
                (f"{today}%", f"{month}%"),
            ).fetchone()
            stats["today_usd"]   = float(row[0])
            stats["month_usd"]   = float(row[1])
            stats["alltime_usd"] = float(row[2])
            stats["total_calls"] = int(row[3])
            stats["recent_calls"] = [dict(r) for r in conn.execute(
                """SELECT timestamp, est_cost_usd, input_tokens, output_tokens, notes
                   FROM api_log WHERE agent = 'editor'
                   ORDER BY timestamp DESC LIMIT 20"""
            ).fetchall()]
    except Exception:
        pass
    return stats


def _draft_label(d: dict) -> str:
    plat   = _PLATFORM_BADGE.get(d["platform"], d["platform"].capitalize())
    title  = (d.get("angle_title") or "—")[:50]
    suffix = ""
    if d.get("latest_verdict"):
        suffix = f"  ·  {_VERDICT_BADGE.get(d['latest_verdict'], d['latest_verdict'])}"
    elif d.get("review_count", 0) == 0:
        suffix = "  ·  ⚪ Not reviewed"
    return f"#{d['draft_id']} · {plat} V{d['variant_number']} · {title}{suffix}"


def _render_draft_content(content: dict) -> None:
    """Show the full post body, CTA, hashtags and copy helpers in one panel."""
    platform = content.get("platform", "")
    body     = content.get("body") or ""
    cta_line = content.get("cta_line") or ""
    hashtags = _safe_json_list(content.get("hashtags"))
    wc       = content.get("word_count") or 0

    st.caption(
        f"{_PLATFORM_BADGE.get(platform, platform)} · "
        f"Variant {content.get('variant_number', '')} · {wc} words"
    )

    if content.get("headline"):
        st.markdown(f"**{content['headline']}**")

    if body:
        body_html = (
            body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\n", "<br>")
        )
        st.markdown(
            f'<div style="background:#1e293b;border:1px solid #334155;border-radius:6px;'
            f'padding:14px 18px;color:#f1f5f9;font-family:Inter,sans-serif;font-size:0.9rem;'
            f'line-height:1.75;white-space:pre-wrap;margin-bottom:8px;">'
            f'{body_html}</div>',
            unsafe_allow_html=True,
        )

    if hashtags:
        st.markdown(" ".join(f"`{t}`" for t in hashtags))

    # Platform-specific copy helpers
    if platform == "linkedin":
        copy_body = body + ("\n\n" + " ".join(hashtags) if hashtags else "")
        c1, c2 = st.columns(2)
        with c1:
            with st.expander("📋 Copy — post body (no SWPI mention)"):
                st.code(copy_body, language=None)
        with c2:
            if cta_line:
                with st.expander("💬 Copy — first comment (post immediately after)"):
                    st.code(cta_line, language=None)
        st.caption("💼 LinkedIn rule: publish body → add first comment immediately.")
    else:
        full = body
        if hashtags: full += "\n\n" + " ".join(hashtags)
        if cta_line: full += f"\n\n{cta_line}"
        with st.expander("📋 Copy-ready text"):
            st.code(full, language=None)


def _render_issues(issues: list[dict]) -> None:
    if not issues:
        st.success("No issues — draft is clean.", icon="✅")
        return
    hard = [i for i in issues if i.get("severity") == "hard"]
    soft = [i for i in issues if i.get("severity") == "soft"]
    if hard:
        st.markdown(f"#### 🔴 Hard issues — {len(hard)}")
        for i in hard: _render_single_issue(i)
    if soft:
        st.markdown(f"#### 🟡 Soft issues — {len(soft)}")
        for i in soft: _render_single_issue(i)


def _render_single_issue(issue: dict) -> None:
    code     = issue.get("code", "UNKNOWN")
    field    = issue.get("field", "—")
    evidence = issue.get("evidence", "")
    message  = issue.get("message", "")
    severity = issue.get("severity", "soft")
    border   = "#ef4444" if severity == "hard" else "#f59e0b"
    bg       = "rgba(239,68,68,0.08)" if severity == "hard" else "rgba(245,158,11,0.08)"
    st.markdown(
        f"""<div style="border-left:4px solid {border};background:{bg};
            padding:0.6rem 0.9rem;margin-bottom:0.5rem;border-radius:4px;">
          <div style="font-weight:600;font-size:0.95rem;color:#f1f5f9;">
            <code style="background:rgba(255,255,255,0.08);padding:1px 6px;
            border-radius:3px;">{code}</code>
            &nbsp;<span style="color:#94a3b8;">in {field}</span>
          </div>
          <div style="margin-top:0.4rem;font-size:0.9rem;color:#e2e8f0;">{message}</div>
          <div style="margin-top:0.3rem;font-size:0.85rem;color:#94a3b8;"><em>{evidence}</em></div>
        </div>""",
        unsafe_allow_html=True,
    )


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("🖊️ Editor")
st.caption("Review Copywriter drafts against brand voice, format, and platform rules.")

product = get_active_product()
if product is None:
    st.error("No active client found. Go to Brand Brain → Tab D to seed Sportz-Well / SWPI.")
    st.stop()

product_id = product["product_id"]
tab_a, tab_b, tab_c = st.tabs(["Review Draft", "Reviews Library", "Pipeline Overview"])


# ─── TAB A — Review Draft ────────────────────────────────────────────────────

with tab_a:
    st.info(
        "**Cost heads-up:** Each new review costs approximately **₹2–₹8** "
        "(pure reasoning, no web search). Cached reviews are free.",
        icon="💰",
    )

    last_run = get_last_run_info(product_id)
    if last_run and last_run["failed"]:
        st.warning(f"⚠ Last run failed — cost {format_cost_inr(last_run['cost'])}.", icon="⚠️")

    drafts = _get_all_drafts_with_review_status(product_id, exclude_posted=True)

    if not drafts:
        st.warning(
            "No active drafts found. Posted drafts are hidden. Run the Copywriter to generate new drafts.",
            icon="⚠️",
        )
    else:
        unreviewed_n = sum(1 for d in drafts if d["review_count"] == 0)
        st.caption(
            f"{len(drafts)} active draft{'s' if len(drafts) != 1 else ''} · "
            f"{unreviewed_n} not yet reviewed · Posted drafts hidden"
        )

        # ── BULK REVIEW ──────────────────────────────────────────────────────
        if unreviewed_n > 0:
            st.markdown("#### Review All Unreviewed")
            col_bulk, col_meta = st.columns([2, 3])
            with col_bulk:
                bulk_btn = st.button(
                    f"📋 Review All Unreviewed  ({unreviewed_n} draft{'s' if unreviewed_n != 1 else ''})",
                    type="primary",
                    use_container_width=True,
                    key="bulk_review_all_btn",
                )
            with col_meta:
                est = unreviewed_n * 0.027 * 95
                st.caption(f"Estimated cost: **₹{est:.2f}** · Runs Editor on all unreviewed drafts in one pass.")

            if bulk_btn:
                ids  = [d["draft_id"] for d in drafts if d["review_count"] == 0]
                prog = st.progress(0, text="Starting bulk review…")
                clean_n, flagged_n, failed_n, total_usd = 0, 0, 0, 0.0
                for i, did in enumerate(ids):
                    prog.progress(i / len(ids), text=f"Reviewing draft #{did}  ({i+1}/{len(ids)})…")
                    res = review_draft(did)
                    total_usd += res.get("est_cost_usd", 0.0)
                    if res.get("error"):          failed_n  += 1
                    elif res.get("verdict") == "clean": clean_n  += 1
                    else:                          flagged_n += 1
                prog.progress(1.0, text="Done.")
                prog.empty()
                st.success(
                    f"✅ Reviewed **{len(ids)}** draft{'s' if len(ids) != 1 else ''} · "
                    f"Clean: **{clean_n}** · Flagged: **{flagged_n}** · Failed: **{failed_n}** · "
                    f"Cost: **{format_cost_inr(total_usd)}**"
                )
                if flagged_n > 0:
                    st.info(f"**{flagged_n} flagged.** Select each below to read the issues.", icon="🚩")
                st.rerun()

            st.divider()

        # ── INDIVIDUAL REVIEW ─────────────────────────────────────────────────
        st.markdown("#### Review Individual Draft")
        draft_options  = {_draft_label(d): d for d in drafts}
        selected_label = st.selectbox(
            "Pick a draft to review",
            options=list(draft_options.keys()),
            key="tab_a_draft_picker",
        )
        selected    = draft_options[selected_label]
        selected_id = selected["draft_id"]

        # ── FULL DRAFT CONTENT — no more back-and-forth to Drafts page ────────
        content = _get_draft_content(selected_id)
        if content:
            with st.expander("📄 Full draft — read before reviewing", expanded=True):
                _render_draft_content(content)

        st.divider()

        # ── REVIEW STATUS + BUTTONS ───────────────────────────────────────────
        rc = selected["review_count"]
        if rc == 0:
            st.info("Not yet reviewed. Click **Review** to run the Editor on this draft.", icon="🆕")
        else:
            verdict_badge = _VERDICT_BADGE.get(selected.get("latest_verdict") or "?", "?")
            st.info(
                f"**{rc} review{'s' if rc != 1 else ''}** in history. Latest: {verdict_badge}",
                icon="📋",
            )

        col_r, col_rr, _ = st.columns([1, 1, 3])
        with col_r:
            review_btn = st.button(
                "Review (cached if exists)",
                type="primary",
                key="tab_a_review_btn",
                help="Returns cached review for free if one exists; calls API if none.",
            )
        with col_rr:
            rereview_btn = st.button(
                "Re-review (force new API call)",
                type="secondary",
                key="tab_a_rereview_btn",
                help="Always calls the API. Costs ₹2–₹8.",
                disabled=(rc == 0),
            )

        result = None
        if review_btn:
            with st.spinner(f"Reviewing draft #{selected_id}…"):
                result = review_draft(selected_id)
        elif rereview_btn:
            with st.spinner(f"Re-reviewing draft #{selected_id}…"):
                result = rereview_draft(selected_id)

        if result is not None:
            if result.get("error"):
                st.error(f"Review failed: {result['error']}")
            else:
                v      = result["verdict"]
                issues = result["issues"]
                cost   = result["est_cost_usd"]
                hard_n = sum(1 for i in issues if i.get("severity") == "hard")
                soft_n = sum(1 for i in issues if i.get("severity") == "soft")
                cost_d = "Free (cached)" if cost == 0.0 else format_cost_inr(cost)
                st.success(
                    f"Review #{result['review_number']} · {_VERDICT_BADGE.get(v, v)} · "
                    f"{hard_n} hard, {soft_n} soft · Cost: **{cost_d}**"
                )
                st.markdown("---")
                _render_issues(issues)


# ─── TAB B — Reviews Library ─────────────────────────────────────────────────

with tab_b:
    show_posted = st.checkbox(
        "Show posted drafts", value=False,
        help="Posted drafts are hidden by default — they're done.",
        key="lib_show_posted",
    )
    all_drafts = _get_all_drafts_with_review_status(product_id, exclude_posted=not show_posted)

    if not all_drafts:
        st.info("No drafts yet. Run the Copywriter first.", icon="ℹ️")
    else:
        col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 2])
        with col_f1:
            verdict_filter  = st.selectbox("Verdict", ["All","Clean","Flagged","Not reviewed"], key="lib_verdict")
        with col_f2:
            platform_filter = st.selectbox("Platform", ["All","Instagram","Facebook","LinkedIn"], key="lib_platform")
        with col_f3:
            severity_filter = st.selectbox("Issues", ["All","Has hard issues","Has soft only","No issues"], key="lib_severity")
        with col_f4:
            sort_by = st.selectbox("Sort by", ["Newest review first","Draft ID asc","Verdict (flagged first)"], key="lib_sort")

        filtered = all_drafts
        if verdict_filter == "Clean":         filtered = [d for d in filtered if d.get("latest_verdict") == "clean"]
        elif verdict_filter == "Flagged":     filtered = [d for d in filtered if d.get("latest_verdict") == "flagged"]
        elif verdict_filter == "Not reviewed":filtered = [d for d in filtered if d["review_count"] == 0]
        if platform_filter != "All":          filtered = [d for d in filtered if d["platform"] == platform_filter.lower()]
        if severity_filter == "Has hard issues":
            filtered = [d for d in filtered if any(i.get("severity") == "hard" for i in d["issues"])]
        elif severity_filter == "Has soft only":
            filtered = [d for d in filtered if d["issues"] and not any(i.get("severity") == "hard" for i in d["issues"])]
        elif severity_filter == "No issues":
            filtered = [d for d in filtered if d.get("latest_verdict") == "clean"]
        if sort_by == "Draft ID asc":
            filtered = sorted(filtered, key=lambda d: d["draft_id"])
        elif sort_by == "Verdict (flagged first)":
            order = {"flagged": 0, "clean": 1, None: 2}
            filtered = sorted(filtered, key=lambda d: order.get(d.get("latest_verdict"), 3))

        hidden_note = "" if show_posted else " · Posted drafts hidden"
        st.caption(f"{len(filtered)} draft{'s' if len(filtered) != 1 else ''} shown{hidden_note}")
        if not filtered:
            st.info("No drafts match the current filters.", icon="🔍")

        for d in filtered:
            did           = d["draft_id"]
            verdict       = d.get("latest_verdict")
            vbadge        = _VERDICT_BADGE.get(verdict, verdict) if verdict else "⚪ Not reviewed"
            platform      = _PLATFORM_BADGE.get(d["platform"], d["platform"].capitalize())
            title         = d.get("angle_title") or "—"
            rc            = d["review_count"]
            issues        = d["issues"]
            hard_n        = sum(1 for i in issues if i.get("severity") == "hard")
            soft_n        = sum(1 for i in issues if i.get("severity") == "soft")
            issue_summary = ""
            if rc > 0:
                if hard_n + soft_n == 0: issue_summary = " — clean"
                else:
                    parts = []
                    if hard_n: parts.append(f"{hard_n} hard")
                    if soft_n: parts.append(f"{soft_n} soft")
                    issue_summary = " — " + ", ".join(parts)
            rlabel = f"{rc} review{'s' if rc != 1 else ''}" if rc > 0 else "no reviews yet"

            with st.expander(
                f"**#{did}** · {platform} V{d['variant_number']} · {title}  "
                f"&nbsp;&nbsp;{vbadge}{issue_summary}  ·  {rlabel}",
                expanded=False,
            ):
                if rc == 0:
                    st.caption("No reviews yet. Go to **Review Draft** tab.")
                else:
                    st.markdown(f"##### Latest review (#{d['latest_review_number']}) · {d.get('latest_reviewed_at','—')}")
                    _render_issues(issues)
                    if rc > 1:
                        with st.expander(f"📜 Full review history ({rc} reviews)"):
                            for h in _get_review_history(did):
                                hv = _VERDICT_BADGE.get(h["verdict"], h["verdict"])
                                cs = format_cost_inr(h["cost_usd"] or 0) if h.get("cost_usd") else "—"
                                st.markdown(f"**Review #{h['review_number']}** · {hv} · {h.get('reviewed_at','—')} · {cs}")
                                _render_issues(h["issues"]) if h["issues"] else st.caption("No issues.")
                                st.markdown("---")
                    col_rr, _ = st.columns([1, 4])
                    with col_rr:
                        if st.button("🔄 Re-review", key=f"rereview_lib_{did}"):
                            with st.spinner(f"Re-reviewing #{did}…"):
                                rereview_draft(did)
                            st.rerun()


# ─── TAB C — Pipeline Overview ───────────────────────────────────────────────

with tab_c:
    stats = _get_pipeline_stats(product_id)

    if stats["total_drafts"] == 0:
        st.info("No drafts yet. Run the Copywriter.", icon="ℹ️")
    else:
        st.markdown("### Review coverage")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total drafts",  stats["total_drafts"])
        c2.metric("Reviewed",      stats["reviewed"])
        c3.metric("Unreviewed",    stats["unreviewed"])
        c4.metric("Total reviews", stats["total_reviews"])
        if stats["unreviewed"] > 0:
            st.warning(
                f"**{stats['unreviewed']} draft{'s' if stats['unreviewed'] != 1 else ''}** not yet reviewed. "
                "Go to **Review Draft** → click **Review All Unreviewed**.",
                icon="📋",
            )

        st.divider()
        st.markdown("### Verdict distribution")
        cv1, cv2, cv3 = st.columns(3)
        cv1.metric("✅ Clean",   stats["clean"])
        cv2.metric("🚩 Flagged", stats["flagged"])
        clean_pct = round(100 * stats["clean"] / stats["reviewed"]) if stats["reviewed"] else 0
        cv3.metric("Clean rate", f"{clean_pct}%")

        if stats["issue_severities"]:
            st.divider()
            st.markdown("### Issue severity")
            cs1, cs2 = st.columns(2)
            cs1.metric("🔴 Hard", stats["issue_severities"].get("hard", 0))
            cs2.metric("🟡 Soft", stats["issue_severities"].get("soft", 0))

        if stats["issue_codes"]:
            st.divider()
            st.markdown("### Most common issue codes")
            for code, count in stats["issue_codes"].most_common(10):
                st.markdown(f"- **`{code}`** — {count} occurrence{'s' if count != 1 else ''}")

        st.divider()
        st.markdown("### 💸 Editor spend")
        spend = _get_editor_spend()
        sp1, sp2, sp3, sp4 = st.columns(4)
        sp1.metric("Today",       format_cost_inr(spend["today_usd"]))
        sp2.metric("This month",  format_cost_inr(spend["month_usd"]))
        sp3.metric("All time",    format_cost_inr(spend["alltime_usd"]))
        sp4.metric("Total calls", spend["total_calls"])
        if spend["total_calls"] > 0:
            avg = (spend["alltime_usd"] / spend["total_calls"]) * 95
            st.caption(f"Average per call: **₹{avg:.2f}**")
        if spend["recent_calls"]:
            with st.expander(f"Last {len(spend['recent_calls'])} Editor calls"):
                for call in spend["recent_calls"]:
                    ts    = call.get("timestamp") or "—"
                    ci    = (call.get("est_cost_usd") or 0.0) * 95
                    notes = (call.get("notes") or "")[:120]
                    icon  = "❌" if notes.startswith(("FAILURE:", "ERROR:")) else "✅"
                    st.markdown(
                        f"{icon} `{ts}` · **₹{ci:.2f}** · "
                        f"{call.get('input_tokens') or 0:,} in / {call.get('output_tokens') or 0:,} out"
                    )
                    if notes: st.caption(notes)
                    st.markdown("---")