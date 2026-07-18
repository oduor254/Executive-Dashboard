"""Denri Executive Dashboard — landing page.

Domain pages (Sales, Customers, Production, Dispatch) live under pages/
and are added incrementally. This page just proves the live loop works:
Streamlit fragment -> cached query -> Postgres -> chart, on demand.
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

from lib import auth, db

st.set_page_config(
    page_title="Denri Executive Dashboard",
    page_icon="📊",
    layout="wide",
)

auth.require_login()

st.title("Denri Executive Dashboard")
st.caption("Sales · Customers · Production · Dispatch — live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.info(
        "Copy .env.example to .env in the project root and fill in "
        "DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD, then rerun."
    )
    st.stop()

st.success("Connected to Postgres", icon="✅")


@st.fragment()
def live_heartbeat() -> None:
    db.refresh_button(key="home_refresh")
    row = db.run_query("SELECT NOW() AS server_time")
    server_time = row.loc[0, "server_time"]
    with st.container(border=True):
        st.metric("Postgres server time", server_time.strftime("%H:%M:%S"))


live_heartbeat()

st.divider()
st.subheader("Next up")
st.markdown(
    "- Add a page per domain under `pages/` (Sales, Customers, Production, Dispatch)\n"
    "- Each page polls Postgres on its own `st.fragment(run_every=...)` loop\n"
    "- Share query helpers from `lib/db.py` and chart styling from `lib/theme.py`"
)
