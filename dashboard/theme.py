"""Dashboard theme: colors, CSS, and styling.

Dark mode control-center theme for monitoring dashboards.
"""

import streamlit as st

# === Color Palette (Dark Mode) ===

COLORS = {
    # Base
    "bg_primary": "#0d1117",
    "bg_secondary": "#161b22",
    "bg_card": "#21262d",
    "bg_card_hover": "#292e36",
    "border": "#30363d",
    "border_subtle": "#21262d",
    "text_primary": "#e6edf3",
    "text_secondary": "#8b949e",
    "text_muted": "#6e7681",
    # Semantic
    "success": "#3fb950",
    "warning": "#d29922",
    "error": "#f85149",
    "info": "#58a6ff",
    # Accents
    "accent_teal": "#39d98a",
    "accent_blue": "#58a6ff",
    "accent_purple": "#a371f7",
    "accent_coral": "#ff7b72",
    "accent_yellow": "#e3b341",
    "accent_cyan": "#56d4dd",
}

# Model-specific colors (consistent across all charts)
MODEL_COLORS = {
    "kokoro": "#39d98a",
    "inworld-1.5-max": "#58a6ff",
    "inworld-1.5": "#ff7b72",
}

# Queue type colors
QUEUE_COLORS = {
    "tts": "#58a6ff",
    "detection": "#a371f7",
}

# Cache type colors
CACHE_COLORS = {
    "audio": "#39d98a",
    "document": "#58a6ff",
    "extraction": "#a371f7",
}


def get_model_color(model_slug: str) -> str:
    """Get color for a model. Checks prefixes for partial matches."""
    if not model_slug:
        return COLORS["text_muted"]
    model_lower = model_slug.lower()
    for key in ["inworld-1.5-max", "kokoro", "inworld-1.5"]:
        if key in model_lower:
            return MODEL_COLORS[key]
    return COLORS["text_secondary"]


# === Plotly Theme ===

PLOTLY_TEMPLATE = {
    "layout": {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"color": COLORS["text_primary"], "family": "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace"},
        "title": {"font": {"size": 14, "color": COLORS["text_secondary"]}},
        "xaxis": {
            "gridcolor": "rgba(48, 54, 61, 0.5)",
            "linecolor": COLORS["border"],
            "tickcolor": COLORS["text_muted"],
            "tickfont": {"size": 11},
            "title": {"font": {"color": COLORS["text_muted"], "size": 11}},
        },
        "yaxis": {
            "gridcolor": "rgba(48, 54, 61, 0.5)",
            "linecolor": COLORS["border"],
            "tickcolor": COLORS["text_muted"],
            "tickfont": {"size": 11},
            "title": {"font": {"color": COLORS["text_muted"], "size": 11}},
        },
        "legend": {
            "bgcolor": "rgba(0,0,0,0)",
            "font": {"color": COLORS["text_secondary"], "size": 11},
        },
        "margin": {"l": 50, "r": 16, "t": 36, "b": 36},
    }
}


def apply_plotly_theme(fig):
    """Apply dark theme to a plotly figure."""
    fig.update_layout(**PLOTLY_TEMPLATE["layout"])
    return fig


# === Streamlit CSS ===

CUSTOM_CSS = f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap');

    /* Dark background */
    .stApp {{
        background-color: {COLORS["bg_primary"]};
    }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background-color: {COLORS["bg_secondary"]};
        border-right: 1px solid {COLORS["border"]};
    }}

    section[data-testid="stSidebar"] .stButton button {{
        background: linear-gradient(135deg, {COLORS["accent_blue"]}22, {COLORS["accent_teal"]}22);
        border: 1px solid {COLORS["border"]};
        color: {COLORS["text_primary"]};
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.8rem;
        transition: all 0.2s ease;
    }}

    section[data-testid="stSidebar"] .stButton button:hover {{
        border-color: {COLORS["accent_blue"]}88;
        background: linear-gradient(135deg, {COLORS["accent_blue"]}33, {COLORS["accent_teal"]}33);
    }}

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 4px;
        background-color: {COLORS["bg_secondary"]};
        padding: 6px 12px;
        border-radius: 8px;
        border: 1px solid {COLORS["border"]};
    }}

    .stTabs [data-baseweb="tab"] {{
        background-color: transparent;
        color: {COLORS["text_muted"]};
        border-radius: 6px;
        padding: 6px 14px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.8rem;
        font-weight: 500;
        letter-spacing: 0.02em;
        transition: all 0.15s ease;
    }}

    .stTabs [data-baseweb="tab"]:hover {{
        color: {COLORS["text_secondary"]};
        background-color: {COLORS["bg_card"]}88;
    }}

    .stTabs [aria-selected="true"] {{
        background-color: {COLORS["bg_card"]} !important;
        color: {COLORS["accent_teal"]} !important;
        border: 1px solid {COLORS["border"]};
        box-shadow: 0 0 8px {COLORS["accent_teal"]}15;
    }}

    /* Hide default tab underline */
    .stTabs [data-baseweb="tab-highlight"] {{
        display: none;
    }}

    /* Metric cards */
    [data-testid="stMetric"] {{
        background: linear-gradient(135deg, {COLORS["bg_card"]}, {COLORS["bg_secondary"]});
        border: 1px solid {COLORS["border"]};
        border-radius: 8px;
        padding: 14px 16px;
        transition: border-color 0.2s ease;
    }}

    [data-testid="stMetric"]:hover {{
        border-color: {COLORS["text_muted"]};
    }}

    [data-testid="stMetricLabel"] {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.7rem !important;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        color: {COLORS["text_muted"]} !important;
    }}

    [data-testid="stMetricValue"] {{
        font-family: 'JetBrains Mono', monospace;
        font-weight: 600;
        color: {COLORS["text_primary"]};
    }}

    [data-testid="stMetricDelta"] {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.75rem;
    }}

    [data-testid="stMetricDelta"] svg {{
        display: none;
    }}

    /* Tables / dataframes */
    .stDataFrame {{
        border: 1px solid {COLORS["border"]};
        border-radius: 8px;
    }}

    /* Dividers */
    hr {{
        border-color: {COLORS["border"]};
        opacity: 0.5;
    }}

    /* Expanders */
    .streamlit-expanderHeader {{
        background-color: {COLORS["bg_card"]};
        border-radius: 8px;
        font-family: 'JetBrains Mono', monospace;
    }}

    /* Section headers */
    h1 {{
        color: {COLORS["text_primary"]} !important;
        font-family: 'JetBrains Mono', monospace;
        font-weight: 600;
        font-size: 1.5rem !important;
        letter-spacing: -0.02em;
    }}

    h2, h3 {{
        color: {COLORS["text_primary"]} !important;
        font-family: 'JetBrains Mono', monospace;
        font-weight: 500;
    }}

    h3 {{
        font-size: 1rem !important;
        color: {COLORS["text_secondary"]} !important;
    }}

    h4, h5, h6 {{
        color: {COLORS["text_secondary"]} !important;
        font-family: 'JetBrains Mono', monospace;
    }}

    /* Regular text */
    p, span, label {{
        color: {COLORS["text_secondary"]};
    }}

    /* Captions */
    .stCaption, [data-testid="stCaptionContainer"] {{
        color: {COLORS["text_muted"]} !important;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.7rem !important;
    }}

    /* Quick toggle buttons (sidebar) */
    .stRadio > div {{
        gap: 4px;
    }}

    .stRadio label {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.8rem;
    }}

    /* Plotly chart containers — tighter */
    [data-testid="stPlotlyChart"] {{
        padding: 0 !important;
    }}

    /* Column gaps */
    [data-testid="stHorizontalBlock"] {{
        gap: 12px;
    }}

    /* Title area */
    .stApp header {{
        background-color: {COLORS["bg_primary"]};
    }}
</style>
"""


def inject_css():
    """Inject custom CSS into Streamlit."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
