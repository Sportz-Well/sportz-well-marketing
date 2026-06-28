"""Shared page utilities — warm slate theme CSS + cached database initialisation.

Every inner page calls init_page() immediately after st.set_page_config().

Usage in any inner page:

    st.set_page_config(page_title="...", page_icon="...", layout="wide")
    init_page()

This ensures:
  1. Database is initialised exactly once per server lifecycle (not on every page load).
  2. Warm slate dark theme applied consistently across every inner page.

Theme palette (Tailwind slate family — warm, readable, not cold):
  Background:  #0f172a  (slate-900)
  Cards:       #1e293b  (slate-800)
  Borders:     #334155  (slate-700)
  Primary text:#f1f5f9  (slate-100)
  Muted text:  #94a3b8  (slate-400)
  Gold accent: #f5a623  (unchanged)
"""

from __future__ import annotations

import streamlit as st
from db.init_db import init_db


@st.cache_resource
def _init_db_once() -> bool:
    """Run init_db exactly once per server lifecycle. Never runs twice."""
    init_db()
    return True


_DARK_THEME_CSS = """
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

/* ── Typography ── */
h1, h2, h3, h4, h5, h6 {
    font-family: 'Rajdhani', sans-serif !important;
    color: #f8fafc !important;
    letter-spacing: 0.04em !important;
}
p, li, span { color: #e2e8f0; }

/* ── Metrics ── */
.stMetric {
    background: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 6px !important;
    padding: 1rem !important;
}
[data-testid="stMetricValue"] { color: #f8fafc !important; }
[data-testid="stMetricLabel"] { color: #94a3b8 !important; }

/* ── Buttons — secondary (default) ── */
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

/* ── Buttons — primary ── */
.stButton > button[kind="primary"] {
    background: #f5a623 !important;
    color: #0f172a !important;
    border-color: #f5a623 !important;
}
.stButton > button[kind="primary"]:hover {
    background: #e09520 !important;
    border-color: #e09520 !important;
}

/* ── Tabs ── */
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
    background: transparent !important;
}
.stTabs [aria-selected="true"] {
    color: #f5a623 !important;
    border-bottom: 2px solid #f5a623 !important;
}

/* ── Divider ── */
[data-testid="stDivider"] { border-color: #334155 !important; }

/* ── Input fields ── */
.stTextInput > div > div > input,
.stTextInput > div > div > input:disabled,
.stTextInput > div > div > input[readonly],
.stTextArea > div > div > textarea,
.stTextArea > div > div > textarea:disabled,
.stTextArea > div > div > textarea[readonly],
textarea,
textarea:disabled,
textarea[disabled],
textarea[readonly] {
    background-color: #1e293b !important;
    border-color: #334155 !important;
    color: #f1f5f9 !important;
    -webkit-text-fill-color: #f1f5f9 !important;
    opacity: 1 !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #f5a623 !important;
    box-shadow: 0 0 0 1px rgba(245,166,35,0.4) !important;
}
.stSelectbox > div > div,
.stMultiSelect > div > div {
    background-color: #1e293b !important;
    border-color: #334155 !important;
    color: #f1f5f9 !important;
}
[data-baseweb="select"] { background-color: #1e293b !important; }
[data-baseweb="menu"] {
    background-color: #1e293b !important;
    border: 1px solid #334155 !important;
}
[data-baseweb="option"] {
    background-color: #1e293b !important;
    color: #f1f5f9 !important;
}
[data-baseweb="option"]:hover { background-color: #293548 !important; }

/* ── Labels ── */
.stTextInput label, .stTextArea label, .stSelectbox label,
.stSlider label, .stCheckbox label, .stRadio label,
.stMultiSelect label, .stNumberInput label {
    color: #94a3b8 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.85rem !important;
}

/* ── Checkboxes ── */
.stCheckbox > label { color: #cbd5e1 !important; }

/* ── Expanders ── */
.streamlit-expanderHeader {
    background-color: #1e293b !important;
    border: 1px solid #334155 !important;
    color: #e2e8f0 !important;
    font-family: 'Rajdhani', sans-serif !important;
    letter-spacing: 0.05em !important;
}
.streamlit-expanderContent {
    background-color: #1e293b !important;
    border: 1px solid #334155 !important;
    border-top: none !important;
}

/* ── Containers with border ── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 6px !important;
}

/* ── Alert boxes ── */
[data-testid="stInfo"] {
    background: rgba(96,165,250,0.08) !important;
    border: 1px solid rgba(96,165,250,0.25) !important;
    color: #93c5fd !important;
}
[data-testid="stWarning"] {
    background: rgba(245,166,35,0.09) !important;
    border: 1px solid rgba(245,166,35,0.28) !important;
    color: #fcd34d !important;
}
[data-testid="stSuccess"] {
    background: rgba(52,211,153,0.08) !important;
    border: 1px solid rgba(52,211,153,0.22) !important;
    color: #6ee7b7 !important;
}
[data-testid="stError"] {
    background: rgba(248,113,113,0.08) !important;
    border: 1px solid rgba(248,113,113,0.25) !important;
    color: #fca5a5 !important;
}

/* ── Progress bar ── */
.stProgress > div > div > div { background-color: #f5a623 !important; }

/* ── Slider ── */
.stSlider [data-baseweb="slider"] [role="slider"] {
    background-color: #f5a623 !important;
    border-color: #f5a623 !important;
}
.stSlider [data-baseweb="slider"] [data-testid="stThumbValue"] {
    color: #f5a623 !important;
}

/* ── Dataframes / tables ── */
[data-testid="stDataFrame"] { border: 1px solid #334155 !important; }
.dvn-scroller { background-color: #1e293b !important; }

/* ── Code blocks ── */
.stCode {
    background-color: #1e293b !important;
    border: 1px solid #334155 !important;
    color: #e2e8f0 !important;
}

/* ── Captions ── */
.stCaption { color: #64748b !important; }

/* ── Forms ── */
[data-testid="stForm"] {
    background-color: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 6px !important;
    padding: 1.5rem !important;
}

/* ── Status containers ── */
[data-testid="stStatusWidget"] {
    background-color: #1e293b !important;
    border: 1px solid #334155 !important;
}

/* ── Radio buttons ── */
.stRadio > div { color: #cbd5e1 !important; }
</style>
"""


# ─── Currency helper ──────────────────────────────────────────────────────────

USD_TO_INR: int = 95


def format_cost_inr(usd: float) -> str:
    """Convert a USD API cost to a formatted INR display string.

    Example: format_cost_inr(0.027) → '₹2.57'
    Used by all pages that display API costs.
    """
    return f"₹{usd * USD_TO_INR:.2f}"


# ─── Page initialiser ─────────────────────────────────────────────────────────

def init_page() -> None:
    """Call immediately after st.set_page_config() on every inner page.

    Handles:
    - Database initialisation (once per server lifecycle, cached)
    - Warm slate theme CSS injection (consistent across all pages)
    """
    _init_db_once()
    st.markdown(_DARK_THEME_CSS, unsafe_allow_html=True)