"""View registry for the combined Dispatch Tracking page — one query and one
render function per area, dispatched by name so the page itself doesn't need
to know any view's specifics. Ported from the former standalone Dispatch and
Goods in Transit pages with no behavior changes."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import db, grid, queries, theme

VIEWS = ["Combined Distribution", "Goods in Transit"]

DEST_COLUMNS = [
    "STARMALL", "MOMBASA", "NAKURU", "ELDORET", "KISUMU", "MERU", "THIKA", "HAZINA",
    "KITENGELA", "WEBSITE", "NANYUKI", "KAKAMEGA", "HILTON", "SINZA", "UGANDA",
    "KISII", "KTDA", "KTDA NEW", "BUSIA", "RONGAI",
]


def fetch(view: str, start_date: date, end_date: date) -> pd.DataFrame:
    query = queries.DISPATCH_COMBINED if view == "Combined Distribution" else queries.GOODS_IN_TRANSIT
    return db.run_query(query, {"start_date": start_date, "end_date": end_date})


def render(view: str, data: pd.DataFrame | None, start_date: date, end_date: date) -> None:
    if data is None:
        st.info("No data for this date range yet.")
        return
    if view == "Combined Distribution":
        _render_combined_distribution(data)
    else:
        _render_goods_in_transit(data)


def _render_combined_distribution(df: pd.DataFrame) -> None:
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


def _render_goods_in_transit(df: pd.DataFrame) -> None:
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
