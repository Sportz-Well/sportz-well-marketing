"""Shared page utilities — dark theme CSS + cached database initialisation.

Every inner page calls init_page() immediately after st.set_page_config().

Usage in any inner page:
    from services.page_utils import init_page

    st.set_page_config(page_title="...", page_icon="...", layout="wide")
    init_page()

This ensures:
  1. Database is initialised exactly once per server lifecycle (not on every page load).
  2. Premium dark theme matches the home page on every inner page.
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

/* ── Hide Streamlit chrome — header, toolbar, footer ── */
#MainMenu { visibility: hidden; }
header[data-testid="stHeader"] {
    background-color: #080810 !important;
    border-bottom: 1px solid #1e1e35 !important;
}
[data-testid="stToolbar"] { display: none !important; }
footer { visibility: hidden; }

/* ── Core background ── */
.stApp { background-color: #080810; color: #e8e8f0; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: #0d0d1a !important;
    border-right: 1px solid #1e1e35;
}
[data-testid="stSidebar"] * { color: #c8c8e0 !important; }
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
    color: #ffffff !important;
    letter-spacing: 0.04em !important;
}

/* ── Metrics ── */
.stMetric {
    background: #0d0d1a !important;
    border: 1px solid #1e1e35 !important;
    border-radius: 4px !important;
    padding: 1rem !important;
}
[data-testid="stMetricValue"] { color: #ffffff !important; }
[data-testid="stMetricLabel"] { color: #6868a0 !important; }

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
    color: #080810 !important;
}
/* ── Buttons — primary ── */
.stButton > button[kind="primary"] {
    background: #f5a623 !important;
    color: #080810 !important;
    border-color: #f5a623 !important;
}
.stButton > button[kind="primary"]:hover {
    background: #e09520 !important;
    border-color: #e09520 !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid #1e1e35 !important;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Rajdhani', sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    color: #6868a0 !important;
    background: transparent !important;
}
.stTabs [aria-selected="true"] {
    color: #f5a623 !important;
    border-bottom: 2px solid #f5a623 !important;
}

/* ── Divider ── */
[data-testid="stDivider"] { border-color: #1a1a2e !important; }

/* ── Input fields — ALL states including disabled and read-only ── */
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
    background-color: #0d0d1a !important;
    border-color: #2a2a4a !important;
    color: #e8e8f0 !important;
    /* Chrome overrides color on disabled — this forces it */
    -webkit-text-fill-color: #e8e8f0 !important;
    opacity: 1 !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #f5a623 !important;
    box-shadow: 0 0 0 1px rgba(245,166,35,0.4) !important;
}
.stSelectbox > div > div,
.stMultiSelect > div > div {
    background-color: #0d0d1a !important;
    border-color: #2a2a4a !important;
    color: #e8e8f0 !important;
}
[data-baseweb="select"] { background-color: #0d0d1a !important; }
[data-baseweb="menu"] { background-color: #0d0d1a !important; border: 1px solid #2a2a4a !important; }
[data-baseweb="option"] { background-color: #0d0d1a !important; color: #e8e8f0 !important; }
[data-baseweb="option"]:hover { background-color: #12122a !important; }

/* ── Labels ── */
.stTextInput label, .stTextArea label, .stSelectbox label,
.stSlider label, .stCheckbox label, .stRadio label,
.stMultiSelect label, .stNumberInput label {
    color: #a0a0c8 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.85rem !important;
}

/* ── Checkboxes ── */
.stCheckbox > label { color: #c8c8e0 !important; }

/* ── Expanders ── */
.streamlit-expanderHeader {
    background-color: #0d0d1a !important;
    border: 1px solid #1e1e35 !important;
    color: #d0d0f0 !important;
    font-family: 'Rajdhani', sans-serif !important;
    letter-spacing: 0.05em !important;
}
.streamlit-expanderContent {
    background-color: #0d0d1a !important;
    border: 1px solid #1e1e35 !important;
    border-top: none !important;
}

/* ── Alert boxes ── */
[data-testid="stInfo"] {
    background: rgba(80,120,255,0.07) !important;
    border: 1px solid rgba(80,120,255,0.2) !important;
    color: #90a8f8 !important;
}
[data-testid="stWarning"] {
    background: rgba(245,166,35,0.08) !important;
    border: 1px solid rgba(245,166,35,0.22) !important;
    color: #e8c87a !important;
}
[data-testid="stSuccess"] {
    background: rgba(0,200,100,0.07) !important;
    border: 1px solid rgba(0,200,100,0.18) !important;
    color: #70e8a8 !important;
}
[data-testid="stError"] {
    background: rgba(232,80,80,0.08) !important;
    border: 1px solid rgba(232,80,80,0.22) !important;
    color: #f08080 !important;
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
[data-testid="stDataFrame"] {
    border: 1px solid #1e1e35 !important;
}
.dvn-scroller { background-color: #0d0d1a !important; }

/* ── Code blocks ── */
.stCode { background-color: #0d0d1a !important; border: 1px solid #1e1e35 !important; }

/* ── Captions ── */
.stCaption { color: #585890 !important; }

/* ── Forms ── */
[data-testid="stForm"] {
    background-color: #0d0d1a !important;
    border: 1px solid #1e1e35 !important;
    border-radius: 4px !important;
    padding: 1.5rem !important;
}
</style>
"""


def init_page() -> None:
    """Call immediately after st.set_page_config() on every inner page.

    Handles:
    - Database initialisation (once per server lifecycle, cached)
    - Dark theme CSS injection (matches home page exactly)
    """
    _init_db_once()
    st.markdown(_DARK_THEME_CSS, unsafe_allow_html=True)