"""Custom Streamlit styling for the local production planning UI."""

import streamlit as st


def apply_app_style() -> None:
    """Apply restrained CSS for readability and production-tool ergonomics."""
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1180px;
            padding-top: 2rem;
            padding-bottom: 4rem;
        }

        section[data-testid="stSidebar"] {
            min-width: 285px;
        }

        section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] p {
            font-size: 0.92rem;
            line-height: 1.45;
            overflow-wrap: anywhere;
        }

        h1 {
            margin-bottom: 0.15rem;
        }

        h2, h3 {
            margin-top: 1.6rem;
            margin-bottom: 0.7rem;
        }

        p, li, label, div[data-testid="stMarkdownContainer"] {
            font-size: 1rem;
            line-height: 1.55;
        }

        textarea, input, .stTextInput input, .stTextArea textarea {
            font-size: 0.98rem !important;
            line-height: 1.45 !important;
        }

        div[data-testid="stAlert"] {
            max-width: 920px;
            border-radius: 6px;
            padding: 0.65rem 0.85rem;
        }

        div[data-testid="stAlert"] p {
            font-size: 0.94rem;
            line-height: 1.4;
        }

        .scl-card {
            border: 1px solid rgba(49, 51, 63, 0.16);
            border-radius: 6px;
            padding: 0.85rem 0.95rem;
            margin: 0.45rem 0;
            background: rgba(250, 250, 250, 0.62);
            overflow-wrap: anywhere;
        }

        .scl-card-label {
            display: block;
            color: rgba(49, 51, 63, 0.7);
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            margin-bottom: 0.2rem;
        }

        .scl-card-value {
            display: block;
            font-size: 1rem;
            line-height: 1.38;
            font-weight: 600;
        }

        .scl-section {
            border: 1px solid rgba(49, 51, 63, 0.14);
            border-radius: 6px;
            padding: 1rem;
            margin: 0.85rem 0;
            background: rgba(255, 255, 255, 0.72);
        }

        .scl-copy-box {
            border: 1px solid rgba(49, 51, 63, 0.14);
            border-radius: 6px;
            padding: 0.8rem 0.9rem;
            margin: 0.5rem 0;
            background: #fbfbfb;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            font-size: 0.98rem;
            line-height: 1.48;
        }

        .scl-source-row {
            border: 1px solid rgba(49, 51, 63, 0.13);
            border-radius: 6px;
            padding: 0.75rem 0.85rem;
            margin: 0.5rem 0;
            background: rgba(255, 255, 255, 0.78);
        }

        .scl-muted {
            color: rgba(49, 51, 63, 0.68);
            font-size: 0.9rem;
        }

        .scl-sidebar-item {
            margin: 0.35rem 0 0.55rem;
            padding-bottom: 0.35rem;
            border-bottom: 1px solid rgba(49, 51, 63, 0.09);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
