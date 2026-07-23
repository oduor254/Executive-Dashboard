"""Shared config lookup: Streamlit Cloud secrets first, local .env fallback.

st.secrets raises if no secrets.toml exists at all (not just an empty dict),
which is the normal case for local dev — caught here so callers don't have
to know about it.
"""
from __future__ import annotations

import json
import os

import streamlit as st


def get(name: str) -> str | None:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def get_gcp_service_account() -> dict | None:
    """Google service account credentials for writing to Sheets.

    On Streamlit Cloud these live in a [gcp_service_account] table in the
    app's Secrets settings. Locally, GOOGLE_SERVICE_ACCOUNT_FILE in .env
    points at the gitignored key file (see secrets/gcp_service_account.json).
    """
    try:
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:
        pass

    path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None
