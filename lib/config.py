"""Shared config lookup: Streamlit Cloud secrets first, local .env fallback.

st.secrets raises if no secrets.toml exists at all (not just an empty dict),
which is the normal case for local dev — caught here so callers don't have
to know about it.
"""
from __future__ import annotations

import os

import streamlit as st


def get(name: str) -> str | None:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)
