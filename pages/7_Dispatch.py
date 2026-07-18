"""Dispatch — combined stock moves and sales-order dispatch by destination."""
from __future__ import annotations

from datetime import date, datetime

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, filters, grid, queries, theme

st.set_page_config(page_title="Dispatch · Denri Executive Dashboard", page_icon="🚛", layout="wide")

auth.require_login()

st.title("🚛 Dispatch")
st.caption("Combined stock moves + sales-order dispatch by destination, live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_refresh = st.columns([3, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("dispatch")

DEST_COLUMNS = [
    "STARMALL", "MOMBASA", "NAKURU", "ELDORET", "KISUMU", "MERU", "THIKA", "HAZINA",
    "KITENGELA", "WEBSITE", "NANYUKI", "KAKAMEGA", "HILTON", "SINZA", "UGANDA",
    "KISII", "KTDA", "KTDA NEW", "BUSIA", "RONGAI",
]


@st.fragment()
def render_dispatch(start_date: date, end_date: date) -> None:
    with col_refresh:
        db.refresh_button(key="dispatch_refresh")

    df = db.run_query(
        queries.DISPATCH_COMBINED,
        {"start_date": start_date, "end_date": end_date},
    )

    detail_rows = df[df["sort_order"] == 0].copy()
    if df.empty or detail_rows.empty:
        st.info("No dispatch activity for this date range yet.")
        return

    family_rows = df[df["sort_order"] == 1].copy()
    grand_total = df[df["sort_order"] == 2].iloc[0].fillna(0)

    dest_totals = grand_total[DEST_COLUMNS].astype(float)
    top_destination = dest_totals.idxmax() if dest_totals.max() > 0 else "—"

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Total Dispatched", f"{grand_total['TOTAL']:,.0f}")
    with k2.container(border=True):
        st.metric("Product Families", f"{len(family_rows):,}")
    with k3.container(border=True):
        st.metric("Bag Styles Dispatched", f"{len(detail_rows):,}")
    with k4.container(border=True):
        st.metric("Top Destination", top_destination)

    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")

    col_dest, col_family = st.columns(2)

    with col_dest:
        with st.container(border=True):
            dest_df = dest_totals[dest_totals > 0].sort_values(ascending=True)
            fig = go.Figure()
            fig.add_bar(
                y=dest_df.index, x=dest_df.values, orientation="h",
                marker=dict(color=theme.sequential_colors(len(dest_df)), cornerradius=4),
            )
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="Dispatched by Destination", height=max(360, 24 * len(dest_df)))
            st.plotly_chart(fig, width="stretch")

    with col_family:
        with st.container(border=True):
            top_families = family_rows.nlargest(15, "TOTAL").sort_values("TOTAL", ascending=True)
            fig = go.Figure()
            fig.add_bar(
                y=top_families["Family"], x=top_families["TOTAL"], orientation="h",
                marker=dict(color=theme.CATEGORICAL[0], cornerradius=4),
            )
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="Top Product Families Dispatched", height=max(360, 28 * len(top_families)))
            st.plotly_chart(fig, width="stretch")

    with st.container(border=True):
        st.caption("Click a column header's filter icon to search or narrow that column. Rows ending in \"TOTAL\" are family subtotals.")
        grid.filterable_table(df.drop(columns=["sort_order"]), pinned_columns=("Product",))


render_dispatch(start_date, end_date)
