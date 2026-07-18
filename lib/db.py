"""Postgres connection layer shared by every page.

Uses a cached SQLAlchemy engine (one pool per Streamlit process) and a
short-TTL query cache, so a page only hits Postgres again once the cache
expires or the viewer explicitly clicks "Refresh now" (see refresh_button).
"""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st
from pandas.errors import DatabaseError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from lib import config

# The reporting replica occasionally cancels a read with "canceling statement
# due to conflict with recovery" when a long-running query collides with WAL
# replay — transient, and gone on retry. Not a bug in any one query.
QUERY_MAX_ATTEMPTS = 3
QUERY_RETRY_BACKOFF_SECONDS = 1.5


def _require_env(name: str) -> str:
    value = config.get(name)
    if not value:
        raise RuntimeError(
            f"Missing {name}. Copy .env.example to .env and fill in your "
            "Postgres connection details (or set it in Streamlit Cloud secrets)."
        )
    return value


DEFAULT_REFRESH_SECONDS = int(config.get("REFRESH_INTERVAL_SECONDS") or "10")


@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    host = _require_env("DB_HOST")
    port = config.get("DB_PORT") or "5432"
    name = _require_env("DB_NAME")
    user = _require_env("DB_USER")
    password = _require_env("DB_PASSWORD")

    url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def check_connection() -> tuple[bool, str]:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Connected"
    except Exception as exc:  # surfaced to the UI, not swallowed
        return False, str(exc)


@st.cache_data(ttl=DEFAULT_REFRESH_SECONDS, show_spinner=False)
def run_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run a read-only query and return it as a DataFrame.

    Cached for REFRESH_INTERVAL_SECONDS so a page's autorefresh fragment
    re-runs this function on schedule but concurrent viewers within the
    same window share one round trip to Postgres. Retries a bounded number
    of times on transient replica conflicts (see QUERY_MAX_ATTEMPTS above)
    before giving up and letting the error surface to the page.
    """
    for attempt in range(1, QUERY_MAX_ATTEMPTS + 1):
        try:
            with get_engine().connect() as conn:
                return pd.read_sql(text(sql), conn, params=params or {})
        except DatabaseError:
            if attempt == QUERY_MAX_ATTEMPTS:
                raise
            time.sleep(QUERY_RETRY_BACKOFF_SECONDS * attempt)


def refresh_button(key: str, label: str = "🔄 Refresh now") -> None:
    """Manual cache-bust control. Viewer decides when to re-poll Postgres,
    instead of a timer forcing a rerun (and resetting any in-progress table
    filters) every REFRESH_INTERVAL_SECONDS."""
    if st.button(label, key=key):
        run_query.clear()
