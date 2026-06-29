"""Home page — Sportz-Well Marketing Studio.

Redesigned as a "This Week" command centre.
Three sections: week grid (Mon–Sun) · to-do list · week stats.
No pipeline-stage thinking. Just tasks.

Run from project root:  streamlit run ui/app.py
"""

from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from db.init_db import init_db
from services.brand_context import get_active_product
from services.database import get_connection
from agents.editor import count_unreviewed_drafts
from agents.media import count_media_stats
from agents.scheduler import get_pipeline_summary

init_db()

st.set_page_config(
    page_title="Sportz-Well Marketing Studio",
    page_icon="🏏",
    layout="wide",
)

# ── IST date helpers (UTC+5:30) ───────────────────────────────────────────────
_now       = datetime.utcnow() + timedelta(hours=5, minutes=30)
_today     = _now.date()
_monday    = _today - timedelta(days=_today.weekday())
_week_days = [_monday + timedelta(days=i) for i in range(7)]
_w_start   = _monday.strftime("%Y-%m-%d 00:00:00")
_w_end     = (_monday + timedelta(days=6)).strftime("%Y-%m-%d 23:59:59")
_DAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
_PLAT      = {"instagram": "📸 IG", "facebook": "👥 FB", "linkedin": "💼 LI"}

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@300;400;500&display=swap');

#MainMenu { visibility:hidden; }
header[data-testid="stHeader"] { background-color:#0f172a!important; border-bottom:1px solid #334155!important; }
[data-testid="stToolbar"] { display:none!important; }
footer { visibility:hidden; }
.stApp { background-color:#0f172a; color:#f1f5f9; }
[data-testid="stSidebar"] { background-color:#0c1524!important; border-right:1px solid #334155; }
[data-testid="stSidebar"] * { color:#cbd5e1!important; }
[data-testid="stSidebar"] a:hover { color:#f5a623!important; }
.main .block-container { padding-top:1.5rem; padding-bottom:3rem; max-width:1200px; }
h1,h2,h3 { font-family:'Rajdhani',sans-serif!important; color:#f8fafc!important; letter-spacing:0.04em!important; }

/* ── Hero ── */
.sw-hero {
    background: linear-gradient(135deg,#1e293b 0%,#243347 50%,#1e293b 100%);
    border:1px solid #334155; border-top:3px solid #f5a623;
    border-radius:6px; padding:1.2rem 2rem; margin-bottom:1.25rem;
}
.sw-hero-title {
    font-family:'Rajdhani',sans-serif; font-size:1.9rem; font-weight:700;
    color:#f8fafc; letter-spacing:0.05em; text-transform:uppercase;
    margin:0; line-height:1.1;
}
.sw-hero-title span { color:#f5a623; }
.sw-hero-meta { font-family:'Inter',sans-serif; font-size:0.8rem; color:#64748b; margin-top:4px; }
.sw-hero-date {
    font-family:'Rajdhani',sans-serif; font-size:0.95rem;
    color:#94a3b8; letter-spacing:0.06em;
}

/* ── Section label ── */
.sw-lbl {
    font-family:'Rajdhani',sans-serif; font-size:0.7rem; font-weight:600;
    letter-spacing:0.22em; text-transform:uppercase; color:#f5a623;
    margin-bottom:0.6rem; padding-bottom:0.35rem; border-bottom:1px solid #334155;
}

/* ── Week grid ── */
.week-grid {
    display:grid; grid-template-columns:repeat(7,1fr);
    gap:8px; margin-bottom:1.4rem;
}
.day-col {
    background:#1e293b; border:1px solid #334155;
    border-radius:6px; padding:0.65rem 0.55rem; min-height:145px;
}
.day-col.is-today { border-color:#f5a623; border-top:3px solid #f5a623; }
.day-col.is-past  { opacity:0.72; }
.day-name {
    font-family:'Rajdhani',sans-serif; font-size:0.62rem;
    letter-spacing:0.18em; color:#475569; text-transform:uppercase;
}
.today-dot {
    display:inline-block; width:5px; height:5px; background:#f5a623;
    border-radius:50%; margin-left:4px; vertical-align:middle;
}
.day-num {
    font-family:'Rajdhani',sans-serif; font-size:1.25rem;
    font-weight:700; color:#94a3b8; line-height:1; margin-bottom:7px;
}
.is-today .day-num { color:#f5a623; }
.post-pill {
    background:#0f172a; border:1px solid #334155;
    border-radius:4px; padding:5px 6px; margin-top:5px;
}
.post-pill.posted  { border-left:2px solid #6ee7b7; }
.post-pill.pending { border-left:2px solid #f5a623; }
.post-pill.overdue { border-left:2px solid #f87171; }
.pill-plat {
    font-size:0.6rem; color:#64748b;
    letter-spacing:0.07em; margin-bottom:2px;
}
.pill-text {
    font-family:'Inter',sans-serif; font-size:0.7rem;
    color:#cbd5e1; line-height:1.25;
    display:-webkit-box; -webkit-line-clamp:2;
    -webkit-box-orient:vertical; overflow:hidden;
}
.pill-st { font-size:0.6rem; color:#64748b; margin-top:3px; }
.pill-st.ok   { color:#6ee7b7; }
.pill-st.late { color:#f87171; }
.day-empty {
    font-size:0.68rem; color:#334155;
    text-align:center; padding-top:1rem;
    font-family:'Inter',sans-serif;
}

/* ── Action items ── */
.act-card {
    background:#1e293b; border:1px solid #334155;
    border-left:3px solid #f5a623; border-radius:6px;
    padding:0.85rem 1rem; margin-bottom:4px;
}
.act-num {
    font-family:'Rajdhani',sans-serif;
    font-size:1rem; font-weight:700; color:#f5a623; margin-right:6px;
}
.act-label {
    font-family:'Inter',sans-serif;
    font-size:0.88rem; font-weight:500; color:#f1f5f9;
}
.act-detail {
    font-family:'Inter',sans-serif; font-size:0.75rem;
    color:#64748b; margin-top:4px; margin-left:1.55rem;
}
.all-clear {
    background:#1e293b; border:1px solid #334155;
    border-radius:6px; padding:2rem 1rem; text-align:center;
}

/* ── Stats block ── */
.stats-block {
    background:#1e293b; border:1px solid #334155;
    border-radius:6px; padding:1.2rem 1.4rem;
}
.stat-row {
    display:flex; align-items:center;
    justify-content:space-between;
    padding:0.55rem 0; border-bottom:1px solid #0f172a;
}
.stat-row:last-child { border-bottom:none; }
.stat-lbl { font-family:'Inter',sans-serif; font-size:0.82rem; color:#94a3b8; }
.stat-val {
    font-family:'Rajdhani',sans-serif;
    font-size:1.4rem; font-weight:700; color:#f8fafc;
}
.stat-val.green { color:#6ee7b7; }
.stat-val.gold  { color:#f5a623; }

/* ── Streamlit widget overrides ── */
.stMetric { background:#1e293b!important; border:1px solid #334155!important; border-radius:6px!important; padding:1rem!important; }
[data-testid="stMetricValue"] { color:#f8fafc!important; }
[data-testid="stMetricLabel"] { color:#94a3b8!important; }
.stButton>button {
    background:transparent!important; border:1px solid #f5a623!important;
    color:#f5a623!important; font-family:'Rajdhani',sans-serif!important;
    font-weight:600!important; letter-spacing:0.1em!important;
    text-transform:uppercase!important; border-radius:2px!important;
}
.stButton>button:hover { background:#f5a623!important; color:#0f172a!important; }
[data-testid="stDivider"] { border-color:#334155!important; }
[data-testid="stPageLink"] { color:#f5a623!important; font-size:0.78rem!important; }
[data-testid="stPageLink"]:hover { color:#fcd34d!important; }
</style>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# PRODUCT GUARD
# ═════════════════════════════════════════════════════════════════════════════
product = get_active_product()

# ── Hero ──────────────────────────────────────────────────────────────────────
_date_str  = _now.strftime("%A, %d %B %Y")
_range_str = f"{_monday.strftime('%d %b')} – {(_monday + timedelta(days=6)).strftime('%d %b %Y')}"
_client    = f" &nbsp;·&nbsp; <span style='color:#f5a623;'>{product['product_name']}</span>" if product else ""

st.markdown(f"""
<div class="sw-hero">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;">
        <div>
            <div class="sw-hero-title">SPORTZ-WELL <span>MARKETING STUDIO</span></div>
            <div class="sw-hero-meta">{_date_str}{_client}</div>
        </div>
        <div class="sw-hero-date">{_range_str}</div>
    </div>
</div>
""", unsafe_allow_html=True)

if not product:
    st.info("No client set up yet. Go to **Brand Brain → Tab D** to seed Sportz-Well / SWPI.")
    st.stop()

product_id = product["product_id"]


# ═════════════════════════════════════════════════════════════════════════════
# DATA — all DB queries in one block
# ═════════════════════════════════════════════════════════════════════════════
week_rows        = []
posted_this_week = 0
angles_no_draft  = 0
conn             = None

try:
    conn = get_connection()

    # Posts scheduled for this week
    week_rows = conn.execute(
        """
        SELECT s.scheduled_for, s.posted_at, d.platform, d.headline
        FROM   schedule s
        JOIN   drafts d ON d.id = s.draft_id
        WHERE  d.product_id = %s
        AND    s.scheduled_for >= %s
        AND    s.scheduled_for <= %s
        ORDER  BY s.scheduled_for
        """,
        (product_id, _w_start, _w_end),
    ).fetchall()

    # Count published this week
    _row = conn.execute(
        """
        SELECT COUNT(*) FROM schedule s
        JOIN   drafts d ON d.id = s.draft_id
        WHERE  d.product_id = %s
        AND    s.posted_at IS NOT NULL
        AND    s.scheduled_for >= %s AND s.scheduled_for <= %s
        """,
        (product_id, _w_start, _w_end),
    ).fetchone()
    posted_this_week = (_row[0] if _row else 0) or 0

    # Approved angles with no drafts yet
    _row2 = conn.execute(
        """
        SELECT COUNT(*) FROM story_angles sa
        WHERE  sa.product_id = %s
        AND    sa.status = 'approved'
        AND    NOT EXISTS (SELECT 1 FROM drafts d WHERE d.story_angle_id = sa.id)
        """,
        (product_id,),
    ).fetchone()
    angles_no_draft = (_row2[0] if _row2 else 0) or 0

except Exception:
    pass
finally:
    if conn:
        conn.close()

# Agent helpers
try:
    unreviewed = count_unreviewed_drafts(product_id)
except Exception:
    unreviewed = 0

try:
    pipeline    = get_pipeline_summary(product_id)
    unscheduled = pipeline.get("unscheduled", 0)
    sched_pend  = pipeline.get("scheduled_pending", 0)
except Exception:
    unscheduled = sched_pend = 0

try:
    ms             = count_media_stats(product_id)
    pending_briefs = ms.get("briefs_pending", 0)
    without_brief  = ms.get("drafts_without_brief", 0)
except Exception:
    pending_briefs = without_brief = 0


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — THIS WEEK GRID
# ═════════════════════════════════════════════════════════════════════════════
by_date: dict[str, list] = defaultdict(list)
for r in week_rows:
    dk = str(r[0])[:10]          # "2026-06-29"
    by_date[dk].append({
        "scheduled_for": str(r[0]),
        "posted_at":     r[1],
        "platform":      str(r[2] or ""),
        "headline":      str(r[3] or ""),
    })

cols_html = ""
for i, day in enumerate(_week_days):
    dk       = day.strftime("%Y-%m-%d")
    is_today = day == _today
    is_past  = day < _today and not is_today
    posts    = by_date.get(dk, [])

    cls = "day-col" + (" is-today" if is_today else "") + (" is-past" if is_past else "")
    today_dot = '<span class="today-dot"></span>' if is_today else ""

    pills = ""
    for p in posts:
        is_posted  = bool(p["posted_at"])
        is_overdue = not is_posted and is_past

        if is_posted:
            pill_cls = "post-pill posted"
            st_html  = '<div class="pill-st ok">✅ Posted</div>'
        elif is_overdue:
            pill_cls = "post-pill overdue"
            st_html  = '<div class="pill-st late">⚠️ Not posted</div>'
        else:
            pill_cls = "post-pill pending"
            t = p["scheduled_for"][11:16] if len(p["scheduled_for"]) > 10 else ""
            st_html  = f'<div class="pill-st">🕐 {t} IST</div>'

        plat  = _PLAT.get(p["platform"].lower(), p["platform"].upper()[:4])
        head  = (p["headline"] or "Untitled")[:42]
        # Single-line HTML — multi-line f-strings create 4+ space indentation
        # which Streamlit's markdown parser treats as code blocks before HTML renders.
        pills += (
            f'<div class="{pill_cls}">'
            f'<div class="pill-plat">{plat}</div>'
            f'<div class="pill-text">{head}</div>'
            f'{st_html}'
            f'</div>'
        )

    if not pills:
        pills = '<div class="day-empty">—</div>'

    cols_html += (
        f'<div class="{cls}">'
        f'<div class="day-name">{_DAY_NAMES[i]}{today_dot}</div>'
        f'<div class="day-num">{day.day}</div>'
        f'{pills}'
        f'</div>'
    )

st.markdown(
    f'<div class="sw-lbl">THIS WEEK</div>'
    f'<div class="week-grid">{cols_html}</div>',
    unsafe_allow_html=True,
)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2 — TO-DO LIST  +  WEEK STATS
# ═════════════════════════════════════════════════════════════════════════════
col_todo, col_stats = st.columns([3, 2], gap="large")

# ── Build action list ─────────────────────────────────────────────────────────
actions = []
if unreviewed > 0:
    actions.append({
        "icon":   "📋",
        "label":  f"Review {unreviewed} draft{'s' if unreviewed != 1 else ''} in Editor",
        "detail": "Quality check before you publish — flags any issues automatically",
        "page":   "pages/5_Editor.py",
    })
if angles_no_draft > 0:
    actions.append({
        "icon":   "✍️",
        "label":  f"Write posts for {angles_no_draft} approved angle{'s' if angles_no_draft != 1 else ''}",
        "detail": "Angles are approved — ready to generate the actual post text",
        "page":   "pages/4_Drafts.py",
    })
if unscheduled > 0:
    actions.append({
        "icon":   "🗓",
        "label":  f"Schedule {unscheduled} approved post{'s' if unscheduled != 1 else ''} to calendar",
        "detail": "Posts approved and ready — just need a publishing date",
        "page":   "pages/7_Calendar.py",
    })
if without_brief > 0:
    actions.append({
        "icon":   "📸",
        "label":  f"Generate image prompts for {without_brief} post{'s' if without_brief != 1 else ''}",
        "detail": "No Firefly / ChatGPT prompt yet for these posts",
        "page":   "pages/6_Media.py",
    })
if pending_briefs > 0:
    actions.append({
        "icon":   "🖼",
        "label":  f"Approve {pending_briefs} image prompt{'s' if pending_briefs != 1 else ''}",
        "detail": "Image prompts are ready — your approval needed before shooting",
        "page":   "pages/6_Media.py",
    })

# ── Render to-do list ─────────────────────────────────────────────────────────
with col_todo:
    st.markdown('<div class="sw-lbl">YOUR TO-DO LIST</div>', unsafe_allow_html=True)

    if not actions:
        st.markdown("""
        <div class="all-clear">
            <div style="font-size:2rem;">🏏</div>
            <div style="font-family:'Inter',sans-serif;font-size:0.9rem;
                        color:#6ee7b7;font-weight:500;margin-top:0.5rem;">
                All clear — nothing pending!</div>
            <div style="font-family:'Inter',sans-serif;font-size:0.78rem;
                        color:#64748b;margin-top:0.3rem;">
                You're ahead of schedule. Check back after posting today.</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        for i, a in enumerate(actions, 1):
            st.markdown(f"""
            <div class="act-card">
                <span class="act-num">{i}.</span>
                <span class="act-label">{a['icon']} {a['label']}</span>
                <div class="act-detail">{a['detail']}</div>
            </div>
            """, unsafe_allow_html=True)
            st.page_link(a["page"], label="↳ Go there now →")


# ── Render week stats ─────────────────────────────────────────────────────────
with col_stats:
    st.markdown('<div class="sw-lbl">THIS WEEK AT A GLANCE</div>', unsafe_allow_html=True)

    # Pending (scheduled but not posted) within this week
    week_pending = sum(
        1 for posts in by_date.values()
        for p in posts
        if not p["posted_at"]
    )

    posted_cls  = "green" if posted_this_week > 0 else ""
    pending_cls = "gold"  if week_pending > 0 else ""
    todo_cls    = "gold"  if actions else "green"
    todo_val    = len(actions)
    in_pipe     = unreviewed + angles_no_draft + unscheduled

    st.markdown(f"""
    <div class="stats-block">
        <div class="stat-row">
            <div class="stat-lbl">✅ Published this week</div>
            <div class="stat-val {posted_cls}">{posted_this_week}</div>
        </div>
        <div class="stat-row">
            <div class="stat-lbl">📅 Scheduled (coming up)</div>
            <div class="stat-val {pending_cls}">{week_pending}</div>
        </div>
        <div class="stat-row">
            <div class="stat-lbl">⚠️ Need your attention</div>
            <div class="stat-val {todo_cls}">{todo_val}</div>
        </div>
        <div class="stat-row">
            <div class="stat-lbl">📝 Total in pipeline</div>
            <div class="stat-val">{in_pipe}</div>
        </div>
    </div>
    <div style="font-family:'Inter',sans-serif;font-size:0.72rem;
                color:#475569;margin-top:0.7rem;text-align:center;">
        {_range_str}
    </div>
    """, unsafe_allow_html=True)