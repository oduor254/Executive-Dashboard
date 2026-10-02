"""Shop Attendants — who served and who ran the till, for every POS session."""
from __future__ import annotations

from datetime import date, datetime

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, filters, grid, queries, theme

st.set_page_config(page_title="Shop Attendants · Denri Executive Dashboard",
                   page_icon="🧑‍💼", layout="wide")

auth.require_login()

st.title("🧑‍💼 Shop Attendants")
st.caption("Every POS session with its shop attendants and cashier — live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_refresh = st.columns([3, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("attendants", default="Yesterday")
with col_refresh:
    db.refresh_button(key="attendants_refresh")

# The headers asked for, in the order asked; Session and Orders follow so a
# row can be traced back to its till session in Odoo.
COLUMNS = ["Date", "Location", "Sales Made", "Shop Attendant", "Cashier", "Session", "Orders"]
NOT_RECORDED = "Not recorded"


@st.fragment()
def render_attendants(start_date: date, end_date: date) -> None:
    df = db.run_query(queries.SHOP_ATTENDANT_SESSIONS,
                      {"start_date": start_date, "end_date": end_date})
    if df.empty:
        st.info("No POS sessions with sales in this date range.")
        return

    col_loc, col_att = st.columns(2)
    with col_loc:
        location = st.selectbox("Location", ["All Locations"] + sorted(df["Location"].unique()),
                                key="attendants_location")
    shown = df if location == "All Locations" else df[df["Location"] == location]
    with col_att:
        people = sorted(p for p in shown["Shop Attendant"].unique() if p != NOT_RECORDED)
        attendant = st.selectbox("Shop Attendant", ["All Shop Attendants"] + people,
                                 key="attendants_person")
    shown = shown if attendant == "All Shop Attendants" else shown[shown["Shop Attendant"] == attendant]

    unrecorded = shown[shown["Shop Attendant"] == NOT_RECORDED]
    items = [
        ("Sales Made", f"KES {shown['Sales Made'].sum():,.0f}", None),
        ("POS Sessions", f"{shown['Session'].nunique():,}", f"{shown['Location'].nunique()} locations"),
        ("Shop Attendants", f"{len(set(shown['Shop Attendant']) - {NOT_RECORDED}):,}", None),
        ("No Attendant Recorded", f"KES {unrecorded['Sales Made'].sum():,.0f}",
         f"{int(unrecorded['Orders'].sum()):,} orders"),
    ]
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · one row per session for each "
        "shop attendant who served in it. Cashier is the person who opened the session in "
        "Odoo; Sales Made is that attendant's sales in the session, counted like the Sales "
        "page (delivery fees out, refunds netted, in KES)."
    )

    by_person = (shown[shown["Shop Attendant"] != NOT_RECORDED]
                 .groupby("Shop Attendant", as_index=False)
                 .agg(Sales=("Sales Made", "sum"), Orders=("Orders", "sum"),
                      Sessions=("Session", "nunique"))
                 .sort_values("Sales", ascending=True))
    if not by_person.empty:
        top = by_person.tail(20)
        with st.container(border=True):
            fig = go.Figure()
            fig.add_bar(
                y=top["Shop Attendant"], x=top["Sales"], orientation="h",
                marker=dict(color=theme.sequential_colors(len(top)), cornerradius=4),
                customdata=top[["Orders", "Sessions"]],
                hovertemplate=("<b>%{y}</b><br>KES %{x:,.0f}<br>%{customdata[0]:,} orders"
                               " · %{customdata[1]:,} sessions<extra></extra>"),
            )
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="Sales Made by Shop Attendant", hovermode="closest",
                              height=max(360, 28 * len(top) + 80))
            fig.update_xaxes(showgrid=True, gridcolor=theme.GRIDLINE)
            fig.update_yaxes(showgrid=False)
            theme.show(fig)

    with st.container(border=True):
        st.caption(f"{len(shown):,} rows · click a column header's filter icon to search or "
                   "narrow it.")
        grid.filterable_table(shown[COLUMNS], currency_columns=("Sales Made",), height=520)


render_attendants(start_date, end_date)
