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

# Ensure the DB exists (idempotent — safe on every page load).
init_db()

st.set_page_config(
    page_title="Sportz-Well Marketing Studio",
    page_icon="🏏",
    layout="wide",
)

st.title("Sportz-Well Marketing Studio")
st.caption("Plan, draft, and schedule social media content for SWPI.")

st.divider()

# ─── Active client summary card ──────────────────────────────────────────────

product = get_active_product()

if product is None:
    st.info(
        "No client set up yet — go to **Brand Brain → Tab D** to seed Sportz-Well / SWPI.",
        icon="ℹ️",
    )
else:
    profile  = get_brand_profile(product["product_id"])
    phase    = product.get("active_phase")

    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader(f"{product['product_name']} — {product.get('full_name') or ''}")
        if product.get("one_liner"):
            st.markdown(f"*{product['one_liner']}*")
        st.markdown(f"**Parent organisation:** {product['org_name']}")
        if product.get("product_website"):
            st.markdown(f"**Website:** {product['product_website']}")

    with col_right:
        social_badge = "🟢 Social active" if product["product_social_active"] else "⚫ Social inactive"
        st.markdown(f"**Status:** {social_badge}")
        if phase:
            st.markdown(f"**Active phase:** Phase {phase['phase_number']} — {phase['name']}")
            if phase.get("focus"):
                st.caption(phase["focus"])
        if profile.get("sales_cycle_type"):
            st.markdown(f"**Sales cycle:** {profile['sales_cycle_type']}")

st.divider()

# ─── Module overview ─────────────────────────────────────────────────────────

st.subheader("Modules")

modules = [
    ("Brand Brain",  "pages/1_Brand_Brain",  "✅ Ready",       "Define the brand, phases, voice, and content rules."),
    ("Research",     "pages/2_Research",     "✅ Ready",       "Gather news, trends, and athlete signals."),
    ("Strategy",     "pages/3_Strategy",     "✅ Ready",       "Turn research into story angles tied to brand positioning."),
    ("Drafts",       "pages/4_Drafts",       "✅ Ready",       "Draft platform-specific posts from story angles."),
    ("Editor",       "pages/5_Editor",       "✅ Ready",       "Review drafts for voice, accuracy, and brand guardrails."),
    ("Media",        None,                   "⏭ Prompt 7",    "Suggest and organise media assets for each post."),
    ("Calendar",     None,                   "⏭ Prompt 8",    "Schedule approved drafts on the content calendar."),
    ("Orchestrator", None,                   "⏭ Prompt 9",    "Run the full pipeline end-to-end with one click."),
]

for name, _page, status, description in modules:
    col_name, col_status, col_desc = st.columns([2, 1, 4])
    col_name.markdown(f"**{name}**")
    col_status.markdown(status)
    col_desc.caption(description)

st.divider()

# ─── Approved angles widget ───────────────────────────────────────────────────

if product is not None:
    approved_n = count_approved_angles(product["product_id"])
    if approved_n > 0:
        st.success(
            f"**{approved_n} approved angle{'s' if approved_n != 1 else ''} ready for drafting.** "
            "Go to [Strategy → Story Angles Library](/Strategy) to review them.",
            icon="✅",
        )

st.divider()

# ─── Recent research widget ───────────────────────────────────────────────────

st.subheader("Recent Research")

if product is None:
    st.info("No client set up yet — seed data in Brand Brain to get started.")
else:
    try:
        with get_connection() as conn:
            recent_items = conn.execute(
                """
                SELECT source_title, title, source_url, relevance_score,
                       topic, fetched_at
                FROM research_items
                WHERE product_id = ?
                ORDER BY fetched_at DESC
                LIMIT 3
                """,
                (product["product_id"],),
            ).fetchall()
    except Exception:
        recent_items = []

    if not recent_items:
        st.info(
            "No research yet — go to **Research → Run Research** to gather your first signals.",
            icon="🔍",
        )
    else:
        for row in recent_items:
            display_title = row["source_title"] or row["title"] or row["source_url"] or "Untitled"
            score = row["relevance_score"] or 0
            badge = "🟢" if score >= 8 else ("🟡" if score >= 5 else "🔴")
            fetched = (row["fetched_at"] or "")[:10]
            st.markdown(
                f"{badge} **{display_title}** &nbsp; `{score}/10` &nbsp; "
                f"*{row['topic'] or ''}* · {fetched}"
            )
        st.caption("See all research items in the [Research Library](/Research).")