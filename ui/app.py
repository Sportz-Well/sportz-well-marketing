"""Home page — Sportz-Well Marketing Studio.

This is the Streamlit entry point. All other pages live in ui/pages/.
Run from the project root:  streamlit run ui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from db.init_db import init_db
from services.brand_context import get_active_product, get_brand_profile
from services.database import get_connection
from agents.strategist import count_approved_angles
from agents.editor import count_unreviewed_drafts
from agents.media import count_media_stats
from agents.scheduler import get_pipeline_summary

init_db()

st.set_page_config(
    page_title="Sportz-Well Marketing Studio",
    page_icon="🏏",
    layout="wide",
)

# ── Warm slate theme — matches inner pages via page_utils ─────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@300;400;500&display=swap');

/* ── Hide Streamlit chrome ── */
#MainMenu { visibility: hidden; }
header[data-testid="stHeader"] {
    background-color: #0f172a !important;
    border-bottom: 1px solid #334155 !important;
}
[data-testid="stToolbar"] { display: none !important; }
footer { visibility: hidden; }

/* ── Core background ── */
.stApp { background-color: #0f172a; color: #f1f5f9; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: #0c1524 !important;
    border-right: 1px solid #334155;
}
[data-testid="stSidebar"] * { color: #cbd5e1 !important; }
[data-testid="stSidebar"] a:hover { color: #f5a623 !important; }

/* ── Main container ── */
.main .block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1200px;
}

/* ── Hero card ── */
.sw-hero {
    background: linear-gradient(135deg, #1e293b 0%, #243347 50%, #1e293b 100%);
    border: 1px solid #334155;
    border-top: 3px solid #f5a623;
    border-radius: 6px;
    padding: 2rem 2.5rem;
    margin-bottom: 1.5rem;
    position: relative;
    overflow: hidden;
}
.sw-hero::before {
    content: '';
    position: absolute;
    top: 0; right: 0;
    width: 300px; height: 100%;
    background: radial-gradient(ellipse at right, rgba(245,166,35,0.07) 0%, transparent 70%);
    pointer-events: none;
}
.sw-hero-title {
    font-family: 'Rajdhani', sans-serif;
    font-size: 2.4rem;
    font-weight: 700;
    color: #f8fafc;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin: 0;
    line-height: 1.1;
}
.sw-hero-title span { color: #f5a623; }
.sw-hero-sub {
    font-family: 'Inter', sans-serif;
    font-size: 0.85rem;
    color: #64748b;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-top: 0.4rem;
}

/* ── Section labels ── */
.sw-section-label {
    font-family: 'Rajdhani', sans-serif;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #f5a623;
    margin-bottom: 0.8rem;
    padding-bottom: 0.4rem;
    border-bottom: 1px solid #334155;
}

/* ── Client card ── */
.sw-client-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-left: 3px solid #f5a623;
    border-radius: 6px;
    padding: 1.5rem 2rem;
    margin-bottom: 1.5rem;
}
.sw-client-name {
    font-family: 'Rajdhani', sans-serif;
    font-size: 1.6rem;
    font-weight: 700;
    color: #f8fafc;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}
.sw-client-oneliner {
    font-family: 'Inter', sans-serif;
    font-size: 0.88rem;
    color: #94a3b8;
    margin-top: 0.2rem;
    font-style: italic;
}
.sw-badge-active {
    display: inline-block;
    background: rgba(52,211,153,0.12);
    color: #6ee7b7;
    border: 1px solid rgba(52,211,153,0.3);
    border-radius: 4px;
    font-family: 'Inter', sans-serif;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 2px 8px;
}
.sw-badge-inactive {
    display: inline-block;
    background: rgba(100,116,139,0.12);
    color: #64748b;
    border: 1px solid rgba(100,116,139,0.3);
    border-radius: 4px;
    font-family: 'Inter', sans-serif;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 2px 8px;
}
.sw-meta {
    font-family: 'Inter', sans-serif;
    font-size: 0.82rem;
    color: #64748b;
    margin-top: 0.3rem;
}
.sw-meta strong { color: #94a3b8; }

/* ── Module table ── */
.sw-module-row {
    display: flex;
    align-items: center;
    padding: 0.7rem 1.2rem;
    border-bottom: 1px solid #0f172a;
    transition: background 0.15s;
}
.sw-module-row:hover { background: rgba(245,166,35,0.04); }
.sw-module-row:last-child { border-bottom: none; }
.sw-module-name {
    font-family: 'Rajdhani', sans-serif;
    font-size: 0.95rem;
    font-weight: 600;
    color: #e2e8f0;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    width: 160px;
    flex-shrink: 0;
}
.sw-module-status {
    width: 90px;
    flex-shrink: 0;
    font-family: 'Inter', sans-serif;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #6ee7b7;
}
.sw-module-desc {
    font-family: 'Inter', sans-serif;
    font-size: 0.82rem;
    color: #64748b;
}
.sw-module-table {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    margin-bottom: 1.5rem;
    overflow: hidden;
}

/* ── Pipeline alert boxes ── */
.sw-alert {
    border-radius: 4px;
    padding: 0.75rem 1.2rem;
    margin-bottom: 0.5rem;
    font-family: 'Inter', sans-serif;
    font-size: 0.84rem;
    display: flex;
    align-items: center;
    gap: 0.8rem;
}
.sw-alert-warn {
    background: rgba(245,166,35,0.09);
    border: 1px solid rgba(245,166,35,0.28);
    color: #fcd34d;
}
.sw-alert-success {
    background: rgba(52,211,153,0.08);
    border: 1px solid rgba(52,211,153,0.22);
    color: #6ee7b7;
}
.sw-alert-info {
    background: rgba(96,165,250,0.08);
    border: 1px solid rgba(96,165,250,0.25);
    color: #93c5fd;
}

/* ── Research items ── */
.sw-research-item {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 0.65rem 1rem;
    margin-bottom: 0.35rem;
    font-family: 'Inter', sans-serif;
    display: flex;
    align-items: center;
    gap: 0.8rem;
    transition: border-color 0.15s;
}
.sw-research-item:hover { border-color: #475569; }
.sw-research-score {
    font-family: 'Rajdhani', sans-serif;
    font-size: 0.9rem;
    font-weight: 700;
    flex-shrink: 0;
    width: 38px;
}
.sw-research-title { font-size: 0.83rem; color: #e2e8f0; flex: 1; }
.sw-research-meta  { font-size: 0.74rem; color: #64748b; white-space: nowrap; }

/* ── Generic Streamlit overrides ── */
h1, h2, h3 {
    font-family: 'Rajdhani', sans-serif !important;
    color: #f8fafc !important;
    letter-spacing: 0.04em !important;
}
.stMetric {
    background: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 6px !important;
    padding: 1rem !important;
}
[data-testid="stMetricValue"] { color: #f8fafc !important; }
[data-testid="stMetricLabel"] { color: #94a3b8 !important; }
.stButton > button {
    background: transparent !important;
    border: 1px solid #f5a623 !important;
    color: #f5a623 !important;
    font-family: 'Rajdhani', sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    border-radius: 2px !important;
}
.stButton > button:hover {
    background: #f5a623 !important;
    color: #0f172a !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid #334155 !important;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Rajdhani', sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    color: #64748b !important;
}
.stTabs [aria-selected="true"] {
    color: #f5a623 !important;
    border-bottom: 2px solid #f5a623 !important;
}
[data-testid="stDivider"] { border-color: #334155 !important; }
</style>
""", unsafe_allow_html=True)


# ── Hero ──────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="sw-hero">
    <div class="sw-hero-title">SPORTZ-WELL <span>MARKETING STUDIO</span></div>
    <div class="sw-hero-sub">AI-Powered Content Pipeline &nbsp;·&nbsp; SWPI Phase 1</div>
</div>
""", unsafe_allow_html=True)


# ── Active client ─────────────────────────────────────────────────────────────

product = get_active_product()

if product is None:
    st.markdown("""
    <div class="sw-alert sw-alert-info">
        <span>ℹ️</span>
        <span>No client set up yet — go to <strong>Brand Brain → Tab D</strong> to seed Sportz-Well / SWPI.</span>
    </div>
    """, unsafe_allow_html=True)
else:
    profile = get_brand_profile(product["product_id"])
    phase   = product.get("active_phase")

    badge = (
        '<span class="sw-badge-active">● Social Active</span>'
        if product["product_social_active"]
        else '<span class="sw-badge-inactive">● Social Inactive</span>'
    )
    phase_html = ""
    if phase:
        phase_html = (
            f'<div class="sw-meta" style="margin-top:0.5rem;">'
            f'<strong>Active Phase:</strong> Phase {phase["phase_number"]} — {phase["name"]}</div>'
        )
        if phase.get("focus"):
            phase_html += f'<div class="sw-meta">{phase["focus"]}</div>'

    website_html = ""
    if product.get("product_website"):
        website_html = (
            f'<div class="sw-meta"><strong>Website:</strong> '
            f'<a href="{product["product_website"]}" style="color:#f5a623;text-decoration:none;">'
            f'{product["product_website"]}</a></div>'
        )

    sales_html = ""
    if profile.get("sales_cycle_type"):
        sales_html = f'<div class="sw-meta"><strong>Sales Cycle:</strong> {profile["sales_cycle_type"]}</div>'

    st.markdown(f"""
<div class="sw-section-label">Active Client</div>
<div class="sw-client-card">
    <div style="display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:1rem;">
        <div>
            <div class="sw-client-name">{product['product_name']} — {product.get('full_name') or ''}</div>
            <div class="sw-client-oneliner">{product.get('one_liner') or ''}</div>
            <div class="sw-meta"><strong>Organisation:</strong> {product['org_name']}</div>
            {website_html}
        </div>
        <div style="text-align:right;">
            {badge}
            {phase_html}
            {sales_html}
        </div>
    </div>
</div>
""", unsafe_allow_html=True)


# ── Modules ───────────────────────────────────────────────────────────────────

modules = [
    ("Brand Brain",  "Define the brand, phases, voice, and content rules."),
    ("Research",     "Gather news, trends, and athlete signals."),
    ("Strategy",     "Turn research into story angles tied to brand positioning."),
    ("Drafts",       "Draft platform-specific posts from story angles."),
    ("Editor",       "Review drafts for voice, accuracy, and brand guardrails."),
    ("Media",        "Generate shoot-ready photography briefs for each draft."),
    ("Calendar",     "Schedule approved drafts on the content calendar."),
    ("Orchestrator", "Run the full pipeline end-to-end with one click."),
]

rows = "".join(
    f'<div class="sw-module-row">'
    f'<div class="sw-module-name">{name}</div>'
    f'<div class="sw-module-status">✓ Ready</div>'
    f'<div class="sw-module-desc">{desc}</div>'
    f'</div>'
    for name, desc in modules
)

st.markdown(f"""
<div class="sw-section-label">Pipeline Modules</div>
<div class="sw-module-table">{rows}</div>
""", unsafe_allow_html=True)


# ── Pipeline alerts ───────────────────────────────────────────────────────────

if product is not None:
    product_id   = product["product_id"]
    approved_n   = count_approved_angles(product_id)
    unreviewed_n = count_unreviewed_drafts(product_id)

    try:
        ms             = count_media_stats(product_id)
        pending_briefs = ms["briefs_pending"]
        without_brief  = ms["drafts_without_brief"]
    except Exception:
        pending_briefs = without_brief = 0

    try:
        ss            = get_pipeline_summary(product_id)
        unscheduled_n = ss["unscheduled"]
        scheduled_n   = ss["scheduled_pending"]
    except Exception:
        unscheduled_n = scheduled_n = 0

    alerts = ""
    if approved_n > 0:
        alerts += (
            f'<div class="sw-alert sw-alert-success"><span>✅</span>'
            f'<span><strong>{approved_n} approved angle{"s" if approved_n != 1 else ""}</strong>'
            f' ready for drafting — go to Strategy.</span></div>'
        )
    if unreviewed_n > 0:
        alerts += (
            f'<div class="sw-alert sw-alert-warn"><span>📋</span>'
            f'<span><strong>{unreviewed_n} draft{"s" if unreviewed_n != 1 else ""}</strong>'
            f' awaiting Editor review.</span></div>'
        )
    if without_brief > 0:
        alerts += (
            f'<div class="sw-alert sw-alert-warn"><span>📸</span>'
            f'<span><strong>{without_brief} draft{"s" if without_brief != 1 else ""}</strong>'
            f' without a media brief — go to Media Studio.</span></div>'
        )
    if pending_briefs > 0:
        alerts += (
            f'<div class="sw-alert sw-alert-info"><span>🟡</span>'
            f'<span><strong>{pending_briefs} media brief{"s" if pending_briefs != 1 else ""}</strong>'
            f' pending approval.</span></div>'
        )
    if unscheduled_n > 0:
        alerts += (
            f'<div class="sw-alert sw-alert-warn"><span>🗓</span>'
            f'<span><strong>{unscheduled_n} approved draft{"s" if unscheduled_n != 1 else ""}</strong>'
            f' not yet scheduled — go to Calendar.</span></div>'
        )
    elif scheduled_n > 0:
        alerts += (
            f'<div class="sw-alert sw-alert-success"><span>🗓</span>'
            f'<span><strong>{scheduled_n} post{"s" if scheduled_n != 1 else ""}</strong>'
            f' scheduled and ready to go.</span></div>'
        )

    if alerts:
        st.markdown(
            f'<div class="sw-section-label">Pipeline Status</div>{alerts}',
            unsafe_allow_html=True,
        )

st.divider()


# ── Recent research ───────────────────────────────────────────────────────────

st.markdown('<div class="sw-section-label">Recent Research</div>', unsafe_allow_html=True)

if product is None:
    st.markdown(
        '<div class="sw-alert sw-alert-info"><span>No client set up yet.</span></div>',
        unsafe_allow_html=True,
    )
else:
    try:
        with get_connection() as conn:
            rows_db = conn.execute(
                """SELECT source_title, title, source_url, relevance_score, topic, fetched_at
                   FROM research_items WHERE product_id = ?
                   ORDER BY fetched_at DESC LIMIT 5""",
                (product["product_id"],),
            ).fetchall()
    except Exception:
        rows_db = []

    if not rows_db:
        st.markdown(
            '<div class="sw-alert sw-alert-info">'
            '<span>🔍</span>'
            '<span>No research yet — go to <strong>Research → Run Research</strong>.</span>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        items_html = ""
        for row in rows_db:
            title   = row["source_title"] or row["title"] or row["source_url"] or "Untitled"
            score   = row["relevance_score"] or 0
            color   = "#6ee7b7" if score >= 8 else ("#fcd34d" if score >= 5 else "#fca5a5")
            fetched = (row["fetched_at"] or "")[:10]
            topic   = row["topic"] or ""
            items_html += (
                f'<div class="sw-research-item">'
                f'<div class="sw-research-score" style="color:{color};">{score}/10</div>'
                f'<div class="sw-research-title">{title}</div>'
                f'<div class="sw-research-meta">{topic} · {fetched}</div>'
                f'</div>'
            )
        st.markdown(items_html, unsafe_allow_html=True)
        st.markdown(
            '<div style="font-family:Inter,sans-serif;font-size:0.74rem;'
            'color:#64748b;margin-top:0.4rem;">'
            'See all research in the Research Library page.</div>',
            unsafe_allow_html=True,
        )