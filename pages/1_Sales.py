"""Sales Performance — revenue, orders, and target attainment by branch."""
from __future__ import annotations

from datetime import date, datetime

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, filters, grid, queries, theme

st.set_page_config(page_title="Sales · Denri Executive Dashboard", page_icon="💰", layout="wide")

auth.require_login()

st.title("💰 Sales Performance")
st.caption("Revenue, orders, and target attainment by branch — live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_refresh = st.columns([3, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("sales")


@st.fragment()
def render_sales(start_date: date, end_date: date) -> None:
    with col_refresh:
        db.refresh_button(key="sales_refresh")

    df = db.run_query(
        queries.SALES_PERFORMANCE_BY_BRANCH,
        {"start_date": start_date, "end_date": end_date},
    )

    branches = df.loc[df["Branch"] != "GRAND TOTAL"].copy()
    if df.empty or branches.empty:
        st.info("No sales recorded for this date range yet.")
        return

    # SUM() over an empty group in SQL yields NULL, not 0 (e.g. a branch with no
    # matching target row) — treat that the same as zero for display.
    totals = df.loc[df["Branch"] == "GRAND TOTAL"].iloc[0].fillna(0)
    pct = totals["% Achieved"]

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Revenue", f"KES {totals['Revenue']:,.0f}")
    with k2.container(border=True):
        st.metric("Orders", f"{totals['Orders']:,.0f}")
    with k3.container(border=True):
        st.metric("Units Sold", f"{totals['Qty']:,.0f}")
    with k4.container(border=True):
        st.metric("Target Achieved", f"{pct:,.1f}%", delta=f"{pct - 100:,.1f} pts vs target")

    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")

    if branches.empty:
        with st.container(border=True):
            grid.filterable_table(df, currency_columns=("Revenue", "Target"))
        return

    branches = branches.sort_values("Revenue", ascending=True)

    col_bullet, col_mix = st.columns(2)

    with col_bullet:
        with st.container(border=True):
            bullet = go.Figure()
            bullet.add_bar(
                y=branches["Branch"], x=branches["Revenue"], orientation="h",
                name="Revenue",
                marker=dict(color=theme.CATEGORICAL[0], cornerradius=4),
            )
            bullet.add_scatter(
                y=branches["Branch"], x=branches["Target"], mode="markers",
                name="Target",
                marker=dict(symbol="line-ns", size=16, line=dict(width=2, color=theme.TEXT_PRIMARY)),
            )
            theme.apply_layout(bullet, show_legend=True)
            bullet.update_layout(
                title="Revenue vs Target by Branch",
                height=max(360, 32 * len(branches)),
            )
            st.plotly_chart(bullet, width="stretch")

    with col_mix:
        with st.container(border=True):
            mix = go.Figure()
            for col, label in [
                ("Walk-in Orders", "Walk-in"),
                ("Online Orders", "Online"),
                ("Activation Orders", "Activation"),
            ]:
                mix.add_bar(x=branches["Branch"], y=branches[col], name=label)
            mix.update_layout(barmode="stack", bargap=0.2)
            theme.apply_layout(mix, show_legend=True)
            mix.update_layout(
                title="Order Mix by Branch",
                height=max(360, 32 * len(branches)),
            )
            st.plotly_chart(mix, width="stretch")

    with st.container(border=True):
        grid.filterable_table(df, currency_columns=("Revenue", "Target"))


render_sales(start_date, end_date)
