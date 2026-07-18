"""Password gate so the dashboard isn't open to anyone with the URL.

One shared password, configured via APP_PASSWORD (Streamlit Cloud secrets or
local .env) — not a per-user login system. Persists per browser session.
"""
from __future__ import annotations

import hmac

import streamlit as st

from lib import config


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

    st.title("🔒 Denri Executive Dashboard")
    password = st.text_input("Password", type="password", key="login_password")
    if st.button("Log in", key="login_submit"):
        if hmac.compare_digest(password, expected):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()
