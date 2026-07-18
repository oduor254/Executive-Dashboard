"""Password gate so the dashboard isn't open to anyone with the URL.

One shared password, configured via APP_PASSWORD (Streamlit Cloud secrets or
local .env) — not a per-user login system. Persists per browser session.
"""
from __future__ import annotations

import base64
import hmac
from pathlib import Path

import streamlit as st

from lib import config, theme

LOGO_PATH = Path(__file__).parent.parent / "assets" / "logo.png"


def _logo_data_uri() -> str | None:
    if not LOGO_PATH.exists():
        return None
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode()
    return f"data:image/png;base64,{encoded}"


def require_login() -> None:
    """Block the rest of the page until the correct password is entered."""
    if st.session_state.get("authenticated"):
        return

    expected = config.get("APP_PASSWORD")
    if not expected:
        st.error(
            "APP_PASSWORD is not configured. Set it in .env (local) or in "
            "the Streamlit Cloud app's Settings -> Secrets (production)."
        )
        st.stop()

    st.markdown(
        f"""
        <style>
        .denri-logo-card {{
            background: #ffffff;
            border-radius: 24px;
            padding: 22px;
            width: 150px;
            margin: 6vh auto 28px auto;
            box-shadow: 0 12px 32px rgba(0,0,0,0.4);
        }}
        .denri-logo-card img {{ width: 100%; display: block; }}
        .denri-title {{
            text-align: center;
            font-family: {theme.FONT_FAMILY};
            font-size: 1.75rem;
            font-weight: 700;
            color: {theme.TEXT_PRIMARY};
            margin-bottom: 0.3rem;
            letter-spacing: 0.01em;
        }}
        .denri-subtitle {{
            text-align: center;
            font-family: {theme.FONT_FAMILY};
            color: {theme.TEXT_MUTED};
            font-size: 0.95rem;
            margin-bottom: 2rem;
        }}
        .denri-footnote {{
            text-align: center;
            font-family: {theme.FONT_FAMILY};
            color: {theme.TEXT_MUTED};
            font-size: 0.8rem;
            margin-top: 1rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        logo_uri = _logo_data_uri()
        if logo_uri:
            st.markdown(f'<div class="denri-logo-card"><img src="{logo_uri}" alt="Denri logo"></div>', unsafe_allow_html=True)
        st.markdown('<div class="denri-title">Denri Executive Dashboard</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="denri-subtitle">Sign in to view live sales, production &amp; dispatch data</div>',
            unsafe_allow_html=True,
        )

        with st.container(border=True):
            password = st.text_input(
                "Password", type="password", key="login_password",
                label_visibility="collapsed", placeholder="Dashboard password",
            )
            if st.button("Log in", key="login_submit", type="primary", width="stretch"):
                if hmac.compare_digest(password, expected):
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Incorrect password.", icon="🚫")

        st.markdown('<div class="denri-footnote">Authorized personnel only</div>', unsafe_allow_html=True)

    st.stop()
