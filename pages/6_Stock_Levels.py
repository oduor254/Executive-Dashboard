"""Stock Levels — live on-hand inventory by location and product."""
from __future__ import annotations

from datetime import datetime

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, colors, db, grid, queries, theme

st.set_page_config(page_title="Stock · Denri Executive Dashboard", page_icon="📦", layout="wide")

auth.require_login()

st.title("📦 Stock Levels")
st.caption("Live on-hand inventory by location and product, straight from Postgres — no date range, this is current state")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

_, col_refresh = st.columns([3, 1])


@st.fragment()
def render_stock() -> None:
    with col_refresh:
        db.refresh_button(key="stock_refresh")

    df = db.run_query(queries.STOCK_LEVELS)

    if df.empty:
        st.info("No stock on hand right now.")
        return

    by_location = df.groupby("Location", as_index=False)["Quantity"].sum()
    top_location = by_location.nlargest(1, "Quantity")

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Total Units in Stock", f"{df['Quantity'].sum():,.0f}")
    with k2.container(border=True):
        st.metric("Locations Tracked", f"{by_location.shape[0]:,}")
    with k3.container(border=True):
        st.metric("Products Tracked", f"{df['Product'].nunique():,}")
    with k4.container(border=True):
        st.metric("Top Location", top_location["Location"].iloc[0] if not top_location.empty else "—")

    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")

    with st.container(border=True):
        ranked = by_location.sort_values("Quantity", ascending=True)
        fig = go.Figure()
        fig.add_bar(
            y=ranked["Location"], x=ranked["Quantity"], orientation="h",
            marker=dict(color=theme.sequential_colors(len(ranked)), cornerradius=4),
        )
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="Stock by Location", height=max(360, 28 * len(ranked)))
        st.plotly_chart(fig, width="stretch")

    locations = sorted(df["Location"].unique())
    selected_location = st.selectbox("Location", ["All Locations"] + locations, key="stock_location_filter")
    filtered = df if selected_location == "All Locations" else df[df["Location"] == selected_location]

    with st.container(border=True):
        top_products = (
            filtered.groupby("Product", as_index=False)["Quantity"]
            .sum()
            .nlargest(15, "Quantity")
            .sort_values("Quantity", ascending=True)
        )
        fig = go.Figure()
        fig.add_bar(
            y=top_products["Product"], x=top_products["Quantity"], orientation="h",
            marker=dict(color=theme.CATEGORICAL[0], cornerradius=4),
        )
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(
            title=f"Top Products in Stock — {selected_location}",
            height=max(360, 28 * len(top_products)),
        )
        st.plotly_chart(fig, width="stretch")

    with st.container(border=True):
        st.caption("Click a column header's filter icon to search or narrow that column.")
        grid.filterable_table(filtered)

    st.subheader("Stock by Base Product")
    st.caption("Color variants rolled up into one product — e.g. Ace Black TT + Ace Grey + Ace Cracked all count as \"Ace\".")

    with st.container(border=True):
        by_base = filtered.copy()
        by_base["Product"] = by_base["Product"].map(colors.strip_color)
        by_base = by_base.groupby(["Location", "Product"], as_index=False)["Quantity"].sum()
        grid.filterable_table(by_base)


render_stock()
