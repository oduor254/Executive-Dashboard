"""Denri Sales Operations Dashboard — open (no password) entrypoint.

Runs four of the executive dashboard's pages as their own app, so the sales
manager sees only Sales, Shop Attendants, Shop Performance and WhatsApp &
Social DMs. The page files under pages/ are shared, not copied: any fix made
there shows up in both dashboards.

st.navigation replaces Streamlit's automatic pages/ discovery, so the other
executive pages (Products, Customers, Production, ...) aren't reachable here.

Run locally:   streamlit run sales_operations_app.py
Streamlit Cloud: deploy this repo again with "Main file path" set to
sales_operations_app.py (same secrets as the executive app; APP_PASSWORD unused).
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

from lib import auth

APP_NAME = "Denri Sales Operations Dashboard"

auth.open_access(APP_NAME)

nav = st.navigation([
    st.Page("pages/1_Sales.py", title="Sales", icon="💰", default=True),
    st.Page("pages/8_Shop_Attendants.py", title="Shop Attendants", icon="🧑‍💼"),
    st.Page("pages/9_Shop_Performance.py", title="Shop Performance", icon="🏬"),
    st.Page("pages/7_WhatsApp_and_Social_DMs.py", title="WhatsApp & Social DMs", icon="💬"),
])

with st.sidebar:
    st.caption(APP_NAME)

nav.run()
