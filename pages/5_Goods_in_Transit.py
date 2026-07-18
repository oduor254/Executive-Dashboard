"""Goods in Transit — bags shipped to the Sinza (Tanzania) and Uganda channels."""
from __future__ import annotations

from datetime import date, datetime

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, filters, grid, queries, theme

st.set_page_config(page_title="Goods in Transit · Denri Executive Dashboard", page_icon="🚚", layout="wide")

auth.require_login()

st.title("🚚 Goods in Transit")
st.caption("Bags shipped to the Sinza (Tanzania) and Uganda channels, live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_refresh = st.columns([3, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("transit", default="Last 30 Days")


@st.fragment()
def render_transit(start_date: date, end_date: date) -> None:
    with col_refresh:
        db.refresh_button(key="transit_refresh")

    df = db.run_query(
        queries.GOODS_IN_TRANSIT,
        {"start_date": start_date, "end_date": end_date},
    )

    products = df.loc[df["Product"] != "GRAND TOTAL"].copy()
    if df.empty or products.empty:
        st.info("No shipments recorded for this date range yet.")
        return

    # SUM() over an empty group in SQL yields NULL, not 0.
    totals = df.loc[df["Product"] == "GRAND TOTAL"].iloc[0].fillna(0)

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Total Shipped", f"{totals['TOTAL']:,.0f}")
    with k2.container(border=True):
        st.metric("Sinza (Tanzania)", f"{totals['SINZA']:,.0f}")
    with k3.container(border=True):
        st.metric("Uganda", f"{totals['UGANDA']:,.0f}")
    with k4.container(border=True):
        st.metric("Bag Types Shipped", f"{len(products):,}")

    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")

    with st.container(border=True):
        top = products.nlargest(15, "TOTAL").sort_values("TOTAL", ascending=True)
        fig = go.Figure()
        fig.add_bar(y=top["Product"], x=top["SINZA"], name="Sinza", orientation="h",
                    marker=dict(color=theme.CATEGORICAL[0], cornerradius=4))
        fig.add_bar(y=top["Product"], x=top["UGANDA"], name="Uganda", orientation="h",
                    marker=dict(color=theme.CATEGORICAL[1], cornerradius=4))
        fig.update_layout(barmode="stack", bargap=0.2)
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(
            title="Top Bags Shipped by Channel",
            height=max(360, 28 * len(top)),
        )
        st.plotly_chart(fig, width="stretch")

    with st.container(border=True):
        table_df = df.copy()
        table_df["Dates"] = table_df["Dates"].fillna("")
        grid.filterable_table(table_df)


render_transit(start_date, end_date)
