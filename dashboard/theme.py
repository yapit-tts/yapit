"""Dashboard theme: colors, CSS, and styling.

Dark mode theme optimized for monitoring dashboards.
Potential improvement: Add font customization (JetBrains Mono for numbers).
"""

import streamlit as st

# === Color Palette (Dark Mode) ===

COLORS = {
    # Base
    "bg_primary": "#0d1117",  # GitHub dark
    "bg_secondary": "#161b22",
    "bg_card": "#21262d",
    "border": "#30363d",
    "text_primary": "#e6edf3",
    "text_secondary": "#8b949e",
    "text_muted": "#6e7681",
    # Semantic
    "success": "#3fb950",  # Green
    "warning": "#d29922",  # Yellow/amber
    "error": "#f85149",  # Red
    "info": "#58a6ff",  # Blue
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
    "kokoro": "#39d98a",  # Teal
    "higgs": "#a371f7",  # Purple
    "inworld-max": "#58a6ff",  # Blue
    "inworld": "#ff7b72",  # Coral
}

# Queue type colors
QUEUE_COLORS = {
    "tts": "#58a6ff",  # Blue
    "detection": "#a371f7",  # Purple
}

# Cache type colors
CACHE_COLORS = {
    "audio": "#39d98a",  # Teal
    "document": "#58a6ff",  # Blue
    "extraction": "#a371f7",  # Purple
}


def get_model_color(model_slug: str) -> str:
    """Get color for a model. Checks prefixes for partial matches."""
    if not model_slug:
        return COLORS["text_muted"]
    model_lower = model_slug.lower()
    # Check in order of specificity
    for key in ["inworld-max", "kokoro", "higgs", "inworld"]:
        if key in model_lower:
            return MODEL_COLORS[key]
    return COLORS["text_secondary"]


# === Plotly Theme ===

PLOTLY_TEMPLATE = {
    "layout": {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"color": COLORS["text_primary"], "family": "system-ui, -apple-system, sans-serif"},
        "title": {"font": {"size": 16, "color": COLORS["text_primary"]}},
        "xaxis": {
            "gridcolor": COLORS["border"],
            "linecolor": COLORS["border"],
            "tickcolor": COLORS["text_muted"],
            "title": {"font": {"color": COLORS["text_secondary"]}},
        },
        "yaxis": {
            "gridcolor": COLORS["border"],
            "linecolor": COLORS["border"],
            "tickcolor": COLORS["text_muted"],
            "title": {"font": {"color": COLORS["text_secondary"]}},
        },
        "legend": {
            "bgcolor": "rgba(0,0,0,0)",
            "font": {"color": COLORS["text_secondary"]},
        },
        "margin": {"l": 60, "r": 20, "t": 40, "b": 40},
    }
}


def apply_plotly_theme(fig):
    """Apply dark theme to a plotly figure."""
    fig.update_layout(**PLOTLY_TEMPLATE["layout"])
    return fig


# === Streamlit CSS ===

CUSTOM_CSS = f"""
<style>
    /* Dark background */
    .stApp {{
        background-color: {COLORS["bg_primary"]};
    }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background-color: {COLORS["bg_secondary"]};
        border-right: 1px solid {COLORS["border"]};
    }}

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 8px;
        background-color: {COLORS["bg_secondary"]};
        padding: 8px 16px;
        border-radius: 8px;
    }}

    .stTabs [data-baseweb="tab"] {{
        background-color: transparent;
        color: {COLORS["text_secondary"]};
        border-radius: 6px;
        padding: 8px 16px;
    }}

    .stTabs [aria-selected="true"] {{
        background-color: {COLORS["bg_card"]};
        color: {COLORS["text_primary"]};
    }}

    /* Metric cards */
    [data-testid="stMetric"] {{
        background-color: {COLORS["bg_card"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 8px;
        padding: 16px;
    }}

    [data-testid="stMetricValue"] {{
        color: {COLORS["text_primary"]};
    }}

    [data-testid="stMetricDelta"] svg {{
        display: none;
    }}

    /* Tables */
    .stDataFrame {{
        border: 1px solid {COLORS["border"]};
        border-radius: 8px;
    }}

    /* Dividers */
    hr {{
        border-color: {COLORS["border"]};
    }}

    /* Expanders */
    .streamlit-expanderHeader {{
        background-color: {COLORS["bg_card"]};
        border-radius: 8px;
    }}

    /* Headers */
    h1, h2, h3, h4, h5, h6 {{
        color: {COLORS["text_primary"]} !important;
    }}

    /* Regular text */
    p, span, label {{
        color: {COLORS["text_secondary"]};
    }}

    /* Captions */
    .stCaption {{
        color: {COLORS["text_muted"]} !important;
    }}
</style>
"""


def inject_css():
    """Inject custom CSS into Streamlit."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
