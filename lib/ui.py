"""Small shared UI helpers that don't belong to any one domain page."""
from __future__ import annotations

import streamlit as st

from lib import theme


def loading_slot():
    """An st.empty() placeholder pre-filled with a lightweight skeleton, so a
    page can fetch its data before drawing any real chrome — title, controls,
    everything — and have it all swap in at once instead of flashing empty
    chrome while the query runs.

    Usage:
        slot = ui.loading_slot()
        data = fetch_something()          # skeleton stays up while this runs
        with slot.container():            # replaces the skeleton entirely
            st.title(...)
            ...
    """
    slot = st.empty()
    with slot.container():
        st.markdown(
            f"""
            <div style="padding: 4rem 0; text-align: center; color: {theme.TEXT_MUTED};">
                <div class="denri-loading-spinner"></div>
                <div style="margin-top: 0.75rem; font-size: 0.9rem;">Loading…</div>
            </div>
            <style>
            .denri-loading-spinner {{
                width: 32px; height: 32px; margin: 0 auto;
                border: 3px solid rgba(255,255,255,0.15);
                border-top-color: {theme.CATEGORICAL[0]};
                border-radius: 50%;
                animation: denri-loading-spin 0.8s linear infinite;
            }}
            @keyframes denri-loading-spin {{ to {{ transform: rotate(360deg); }} }}
            </style>
            """,
            unsafe_allow_html=True,
        )
    return slot
