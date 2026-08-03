"""Dispatch Tracking — Combined Distribution, Dispatch and Goods in Transit.

One page, one date range, one menu. Only the selected view is queried, so
switching costs a single report rather than all three.
"""
from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, filters, ui, views

st.set_page_config(page_title="Dispatch Tracking · Denri Executive Dashboard", page_icon="🚛", layout="wide")

auth.require_login()


@st.fragment()
def render_tracking() -> None:
    # Menu and range are read from session state BEFORE anything is drawn, so
    # the fetch can happen behind the skeleton and the whole page — chrome
    # included — swaps in at once.
    view = st.session_state.get("tracking_view") or views.VIEWS[0]
    start_date, end_date = filters.resolve_range("tracking")

    slot = ui.loading_slot()

    connected, detail = db.check_connection()
    data = views.fetch(view, start_date, end_date) if connected else None

    with slot.container():
        st.title("🚛 Dispatch Tracking")
        st.caption("Distribution, dispatch and outstanding stock — live from Postgres")

        st.segmented_control(
            "Area",
            views.VIEWS,
            default=views.VIEWS[0],
            key="tracking_view",
        )

        col_picker, col_refresh = st.columns([3, 1])
        with col_picker:
            filters.date_range_control("tracking")
        with col_refresh:
            db.refresh_button(key="tracking_refresh")

        if not connected:
            st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
            return

        st.divider()
        views.render(view, data, start_date, end_date)


render_tracking()
