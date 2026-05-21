"""Research module — Researcher agent UI (Prompt 3.5).

Three tabs:
  A. Run Research  — topic, geography mix, quality threshold, cost warning
  B. Research Library — filters include geography and URL status; broken-link badges
  C. API Spend     — spend breakdown from api_log

Run from the project root:  streamlit run ui/app.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from db.init_db import init_db
from services.brand_context import get_active_product
from services.database import get_connection
from agents.researcher import GEOGRAPHY_OPTIONS

st.set_page_config(page_title="Research — Sportz-Well", page_icon="🔍", layout="wide")

init_db()


# ─── Display helpers ──────────────────────────────────────────────────────────

_GEO_FLAGS: dict[str, str] = {
    "India":     "🇮🇳",
    "UK":        "🇬🇧",
    "Australia": "🇦🇺",
    "USA":       "🇺🇸",
    "Global":    "🌍",
    "Unknown":   "❓",
}

_URL_STATUS_BADGE: dict[str, str] = {
    "ok":         "",
    "redirected": "↪",
    "broken":     "⚠️ Link broken",
    "timeout":    "⚠️ Link timed out",
    "unchecked":  "·",
}


def _score_badge(score: int) -> str:
    if score >= 8:
        return f"🟢 {score}/10"
    elif score >= 5:
        return f"🟡 {score}/10"
    else:
        return f"🔴 {score}/10"


def _geo_badge(geography: str | None) -> str:
    g = (geography or "Unknown").strip()
    flag = _GEO_FLAGS.get(g, "🌐")
    return f"{flag} {g}"


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _month_spend() -> float:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(est_cost_usd), 0) FROM api_log WHERE timestamp LIKE ?",
                (f"{month}%",),
            ).fetchone()
        return float(row[0])
    except Exception:
        return 0.0


def _alltime_spend() -> float:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(est_cost_usd), 0) FROM api_log"
            ).fetchone()
        return float(row[0])
    except Exception:
        return 0.0


def _get_distinct_topics(product_id: int) -> list[str]:
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT DISTINCT topic FROM research_items
                   WHERE product_id = ? AND topic IS NOT NULL ORDER BY topic""",
                (product_id,),
            ).fetchall()
        return [r["topic"] for r in rows]
    except Exception:
        return []


def _get_distinct_geographies(product_id: int) -> list[str]:
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT DISTINCT source_geography FROM research_items
                   WHERE product_id = ? AND source_geography IS NOT NULL
                   ORDER BY source_geography""",
                (product_id,),
            ).fetchall()
        return [r["source_geography"] for r in rows if r["source_geography"]]
    except Exception:
        return []


def _get_research_items(
    product_id: int,
    topic_filter: str | None,
    min_score: int,
    geo_filter: str | None,
    url_status_filter: str | None,
    sort_by: str,
) -> list[dict]:
    sql = """
        SELECT id, topic, source_url, final_url, source_title, title,
               source_published_date, summary, relevance_score, relevance_reason,
               url_status, source_geography, fetched_at
        FROM research_items
        WHERE product_id = ?
          AND COALESCE(relevance_score, 0) >= ?
    """
    params: list = [product_id, min_score]

    if topic_filter:
        sql += " AND topic = ?"
        params.append(topic_filter)
    if geo_filter:
        sql += " AND source_geography = ?"
        params.append(geo_filter)
    if url_status_filter == "Broken/Timeout":
        sql += " AND url_status IN ('broken', 'timeout')"
    elif url_status_filter == "OK/Redirected":
        sql += " AND url_status IN ('ok', 'redirected')"

    order = (
        "relevance_score DESC, fetched_at DESC"
        if sort_by == "Relevance"
        else "fetched_at DESC"
    )
    sql += f" ORDER BY {order}"

    try:
        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _delete_research_item(item_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM research_items WHERE id = ?", (item_id,))


def _get_recent_topics(product_id: int, limit: int = 5) -> list[str]:
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT DISTINCT topic FROM research_items
                   WHERE product_id = ? AND topic IS NOT NULL
                   ORDER BY fetched_at DESC LIMIT ?""",
                (product_id, limit),
            ).fetchall()
        return [r["topic"] for r in rows]
    except Exception:
        return []


def _get_api_log(limit: int = 20) -> list[dict]:
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT timestamp, agent, action, input_tokens,
                          output_tokens, web_searches, est_cost_usd, notes
                   FROM api_log ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _get_spend_by_agent() -> list[dict]:
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT agent, COUNT(*) AS calls,
                          COALESCE(SUM(est_cost_usd), 0) AS total_usd
                   FROM api_log GROUP BY agent ORDER BY total_usd DESC"""
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("🔍 Research")
st.caption("Gather signals — news, sports science, athlete content — filtered for SWPI brand fit.")

product = get_active_product()
if product is None:
    st.error(
        "No active client found. Go to **Brand Brain → Tab D** to seed Sportz-Well / SWPI first."
    )
    st.stop()

product_id = product["product_id"]

tab_a, tab_b, tab_c = st.tabs(["Run Research", "Research Library", "API Spend"])


# ─── TAB A — Run Research ─────────────────────────────────────────────────────

with tab_a:
    month_spend = _month_spend()

    st.info(
        f"**Cost heads-up:** Each research run costs approximately **$0.05 – $0.15** "
        f"depending on results returned. "
        f"**This month's spend so far: ${month_spend:.4f}**",
        icon="💰",
    )

    st.markdown("#### Topic")
    topic_input = st.text_input(
        "What should the Researcher investigate?",
        placeholder="e.g. parent communication in cricket academies India",
        label_visibility="collapsed",
    )

    col_geo, col_thresh = st.columns(2)

    with col_geo:
        geo_options = list(GEOGRAPHY_OPTIONS.keys())
        geo_choice = st.selectbox(
            "Source geography mix",
            options=geo_options,
            index=0,               # "Indian-heavy (3:2)" is default
            help=(
                "Controls the ratio of Indian vs international sources. "
                "'Quality wins' means geography is ignored entirely."
            ),
        )

    with col_thresh:
        min_relevance = st.slider(
            "Minimum relevance score",
            min_value=1,
            max_value=10,
            value=7,
            help=(
                "Items scoring below this threshold are rejected. "
                "Higher = fewer but more brand-aligned results."
            ),
        )

    n_results = st.slider(
        "Max results to aim for",
        min_value=3, max_value=15, value=8,
        help="The agent will return fewer if quality sources are scarce.",
    )

    run_btn = st.button(
        "Run Research",
        type="primary",
        disabled=not topic_input.strip(),
    )

    if run_btn and topic_input.strip():
        from agents.researcher import research_topic

        with st.spinner(
            f'Searching the web for "{topic_input.strip()}" '
            f'(threshold ≥ {min_relevance}, {geo_choice})…'
        ):
            result = research_topic(
                topic=topic_input.strip(),
                product_id=product_id,
                max_results=n_results,
                min_relevance=min_relevance,
                geography=geo_choice,
            )

        if result.get("error"):
            st.error(f"Research failed: {result['error']}")
        else:
            saved     = result["items_saved"]
            cost      = result["total_cost_estimate_usd"]
            requested = result["requested_count"]
            rejected  = result["rejected_count"]
            rej_note  = result["rejection_summary"]

            if saved == requested:
                st.success(
                    f"Done — saved **{saved} item{'s' if saved != 1 else ''}** "
                    f"(all {requested} requested met the threshold). "
                    f"Estimated cost: **${cost:.4f}**"
                )
            else:
                st.success(
                    f"Done — saved **{saved} item{'s' if saved != 1 else ''}** "
                    f"(you requested up to {requested}, but only {saved} met the "
                    f"relevance threshold of {min_relevance}). "
                    f"Estimated cost: **${cost:.4f}**"
                )
                if rejected > 0 and rej_note:
                    st.info(
                        f"**{rejected} item{'s' if rejected != 1 else ''} rejected:** {rej_note}",
                        icon="🚫",
                    )

            if saved > 0:
                st.caption("Switch to the **Research Library** tab to view and filter results.")

            # Quick preview of top results from this run
            if result["items"]:
                st.markdown("#### Top results from this run")
                for item in sorted(result["items"], key=lambda x: -x.get("relevance_score", 0))[:3]:
                    score    = item.get("relevance_score", 0)
                    title    = item.get("source_title") or item.get("title") or "Untitled"
                    url      = item.get("source_url", "")
                    geo      = _geo_badge(item.get("source_geography"))
                    u_status = item.get("url_status", "unchecked")
                    broken   = u_status in ("broken", "timeout")

                    header = f"{_score_badge(score)}  {geo}  {title}"
                    if broken:
                        header += "  ⚠️"
                    with st.expander(header):
                        if url:
                            st.markdown(f"[{url}]({url})")
                        if broken:
                            st.warning(
                                f"⚠ Link {u_status} — summary is unverified. "
                                "Score has been reduced by 3 points.",
                                icon="⚠️",
                            )
                        st.write(item.get("summary", ""))
                        if item.get("relevance_reason"):
                            st.caption(f"Relevance: {item['relevance_reason']}")

    # Recent topics for quick re-runs
    recent = _get_recent_topics(product_id)
    if recent:
        st.markdown("---")
        st.markdown("#### Recently researched topics")
        for t in recent:
            st.markdown(f"- `{t}`")
        st.caption("Tip: copy any topic above into the text box to run it again.")


# ─── TAB B — Research Library ─────────────────────────────────────────────────

with tab_b:
    topics     = _get_distinct_topics(product_id)
    geographies = _get_distinct_geographies(product_id)

    col_f1, col_f2, col_f3, col_f4 = st.columns([3, 2, 2, 2])

    with col_f1:
        topic_options       = ["All topics"] + topics
        topic_filter_label  = st.selectbox("Filter by topic", topic_options, key="lib_topic")
        topic_filter        = None if topic_filter_label == "All topics" else topic_filter_label

    with col_f2:
        geo_options_lib     = ["All geographies"] + geographies
        geo_filter_label    = st.selectbox("Geography", geo_options_lib, key="lib_geo")
        geo_filter          = None if geo_filter_label == "All geographies" else geo_filter_label

    with col_f3:
        url_status_options  = ["All", "OK/Redirected", "Broken/Timeout"]
        url_filter_label    = st.selectbox("URL status", url_status_options, key="lib_url")
        url_filter          = None if url_filter_label == "All" else url_filter_label

    with col_f4:
        min_score_lib = st.slider("Min score", 1, 10, 4, key="lib_min_score")

    sort_by = st.radio("Sort by", ["Date (newest)", "Relevance"], horizontal=True, key="lib_sort")

    items = _get_research_items(
        product_id,
        topic_filter,
        min_score_lib,
        geo_filter,
        url_filter,
        "Relevance" if sort_by == "Relevance" else "Date",
    )

    if not items:
        st.info(
            "No research items found. Run a search in **Run Research** or adjust filters.",
            icon="ℹ️",
        )
    else:
        # Count broken links
        broken_count = sum(1 for i in items if i.get("url_status") in ("broken", "timeout"))
        if broken_count:
            st.warning(
                f"{broken_count} item{'s' if broken_count != 1 else ''} "
                "in this view have a broken or unreachable link — their summaries are unverified.",
                icon="⚠️",
            )
        st.caption(f"{len(items)} item{'s' if len(items) != 1 else ''} found")

        for item in items:
            item_id   = item["id"]
            title     = item.get("source_title") or item.get("title") or "Untitled"
            url       = item.get("source_url", "")
            final_url = item.get("final_url") or url
            pub_date  = item.get("source_published_date") or "—"
            score     = item.get("relevance_score") or 0
            summary   = item.get("summary") or ""
            reason    = item.get("relevance_reason") or ""
            fetched   = (item.get("fetched_at") or "")[:10]
            topic_tag = item.get("topic") or ""
            u_status  = item.get("url_status") or "unchecked"
            geo       = item.get("source_geography") or "Unknown"
            broken    = u_status in ("broken", "timeout")

            geo_tag    = _geo_badge(geo)
            url_tag    = _URL_STATUS_BADGE.get(u_status, "")
            broken_sfx = "  ⚠️" if broken else ""
            header     = f"{_score_badge(score)}  {geo_tag}  {title}{broken_sfx}"

            with st.expander(header):
                col_meta, col_del = st.columns([5, 1])
                with col_meta:
                    display_url = final_url if final_url != url else url
                    if display_url:
                        st.markdown(f"[{display_url}]({display_url})")
                    if final_url and final_url != url:
                        st.caption(f"Redirected from: {url}")
                    st.caption(
                        f"Published: {pub_date}  ·  Fetched: {fetched}  "
                        f"·  Topic: *{topic_tag}*  ·  URL: {url_tag or u_status}"
                    )
                with col_del:
                    arm_key     = f"arm_del_{item_id}"
                    confirm_key = f"confirm_del_{item_id}"
                    if st.session_state.get(confirm_key):
                        _delete_research_item(item_id)
                        st.session_state.pop(confirm_key, None)
                        st.session_state.pop(arm_key, None)
                        st.rerun()
                    elif st.session_state.get(arm_key):
                        if st.button("Confirm delete", key=f"yes_{item_id}", type="primary"):
                            st.session_state[confirm_key] = True
                            st.rerun()
                        if st.button("Cancel", key=f"no_{item_id}"):
                            st.session_state.pop(arm_key, None)
                            st.rerun()
                    else:
                        if st.button("🗑️ Delete", key=f"del_{item_id}"):
                            st.session_state[arm_key] = True
                            st.rerun()

                # Broken-link warning banner — prominent, inside expander
                if broken:
                    st.error(
                        f"⚠ Link {u_status} — this summary could not be verified against the source page. "
                        f"Score was automatically reduced by 3 points. "
                        f"Consider deleting this item or manually checking the URL.",
                        icon="⚠️",
                    )

                st.markdown(summary)
                if reason:
                    st.info(f"**Why this score:** {reason}", icon="🎯")


# ─── TAB C — API Spend ───────────────────────────────────────────────────────

with tab_c:
    month_spend  = _month_spend()
    alltime      = _alltime_spend()
    by_agent     = _get_spend_by_agent()
    recent_calls = _get_api_log(20)

    col1, col2 = st.columns(2)
    col1.metric("This month's spend", f"${month_spend:.4f}")
    col2.metric("All-time spend", f"${alltime:.4f}")

    if by_agent:
        st.markdown("#### Breakdown by agent")
        for row in by_agent:
            st.markdown(
                f"- **{row['agent'].capitalize()}** — "
                f"{row['calls']} call{'s' if row['calls'] != 1 else ''}, "
                f"${row['total_usd']:.4f}"
            )

    st.markdown("#### Last 20 API calls")
    if not recent_calls:
        st.info("No API calls logged yet.", icon="ℹ️")
    else:
        for call in recent_calls:
            ts       = (call.get("timestamp") or "")[:19].replace("T", " ")
            agent    = call.get("agent") or "—"
            action   = call.get("action") or "—"
            cost     = call.get("est_cost_usd") or 0.0
            searches = call.get("web_searches") or 0
            notes    = call.get("notes") or ""
            st.markdown(
                f"`{ts}` · **{agent}** · *{action}* · "
                f"{searches} search{'es' if searches != 1 else ''} · **${cost:.4f}**"
                + (f"  \n  `{notes}`" if notes else "")
            )
