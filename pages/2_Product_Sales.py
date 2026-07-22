"""Product Sales — units sold by shop and product, masterfile vs off-catalog,
plus a wide by-category x store breakdown."""
from __future__ import annotations

from datetime import date, datetime

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, deals, filters, grid, queries, theme

st.set_page_config(page_title="Products · Denri Executive Dashboard", page_icon="👜", layout="wide")

auth.require_login()

st.title("👜 Product Sales")
st.caption("Units sold by shop and product — masterfile catalog vs off-catalog, live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_refresh = st.columns([3, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("products")

TOTAL_LABELS = ("MASTERFILE TOTAL", "NON-MASTERFILE TOTAL")
MAX_TABLE_ROWS = 5000
OFFER_COLORS = {
    "Power Deal": theme.CATEGORICAL[0],
    "Deal of the Week": theme.CATEGORICAL[2],
    "Regular": theme.TEXT_MUTED,
}

tab_shop, tab_category, tab_value, tab_offers = st.tabs(
    ["By Shop", "By Category", "Sales Value", "Offer Types"]
)


@st.fragment()
def render_by_shop(start_date: date, end_date: date) -> None:
    with col_refresh:
        db.refresh_button(key="products_refresh")

    df = db.run_query(
        queries.PRODUCT_SALES_BY_SHOP,
        {"start_date": start_date, "end_date": end_date},
    )

    if df.empty:
        st.info("No units sold for this date range yet.")
        return

    totals = df[df["PRODUCT"].isin(TOTAL_LABELS)]
    detail = df[~df["PRODUCT"].isin(TOTAL_LABELS)].copy()

    masterfile_qty = totals.loc[totals["PRODUCT"] == "MASTERFILE TOTAL", "QTY SOLD"].sum()
    non_masterfile_qty = totals.loc[totals["PRODUCT"] == "NON-MASTERFILE TOTAL", "QTY SOLD"].sum()
    total_qty = masterfile_qty + non_masterfile_qty
    pct_masterfile = (masterfile_qty / total_qty * 100) if total_qty else 0.0

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Total Units Sold", f"{total_qty:,.0f}")
    with k2.container(border=True):
        st.metric("Masterfile Units", f"{masterfile_qty:,.0f}")
    with k3.container(border=True):
        st.metric("Off-Catalog Units", f"{non_masterfile_qty:,.0f}")
    with k4.container(border=True):
        st.metric("% Masterfile", f"{pct_masterfile:,.1f}%")

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · "
        "excludes combo/bundle products entirely, so totals here read lower than "
        "Sales Performance, which counts them."
    )

    if detail.empty:
        return

    shops = sorted(s for s in detail["SHOP"].unique() if s)
    selected_shop = st.selectbox("Shop", ["All Shops"] + shops, key="products_shop_filter")
    filtered = detail if selected_shop == "All Shops" else detail[detail["SHOP"] == selected_shop]

    top_products = (
        filtered.groupby("PRODUCT", as_index=False)["QTY SOLD"]
        .sum()
        .nlargest(15, "QTY SOLD")
        .sort_values("QTY SOLD", ascending=True)
    )

    with st.container(border=True):
        fig = go.Figure()
        fig.add_bar(
            y=top_products["PRODUCT"], x=top_products["QTY SOLD"], orientation="h",
            name="Qty Sold",
            marker=dict(color=theme.CATEGORICAL[0], cornerradius=4),
        )
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(
            title=f"Top Products — {selected_shop}",
            height=max(360, 28 * len(top_products)),
        )
        st.plotly_chart(fig, width="stretch")

    with st.container(border=True):
        grid.filterable_table(filtered)


@st.fragment()
def render_by_category(start_date: date, end_date: date) -> None:
    df = db.run_query(
        queries.BAGS_SOLD_BY_CATEGORY,
        {"start_date": start_date, "end_date": end_date},
    )

    if df.empty:
        st.info("No units sold for this date range yet.")
        return

    detail = df[df["sort_priority"] == 0].copy()
    category_totals = df[df["sort_priority"] == 1].copy()
    grand_total = df[df["sort_priority"] == 2].iloc[0].fillna(0) if (df["sort_priority"] == 2).any() else None

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Total Bags Sold", f"{grand_total['TOTAL']:,.0f}" if grand_total is not None else "0")
    with k2.container(border=True):
        st.metric("Categories Sold", f"{len(category_totals):,}")
    with k3.container(border=True):
        top_cat = category_totals.nlargest(1, "TOTAL")
        st.metric("Top Category", top_cat["Category"].iloc[0] if not top_cat.empty else "—")
    with k4.container(border=True):
        st.metric("Bag Styles Sold", f"{len(detail):,}")

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · "
        "excludes combo/bundle products, and only counts products matching a known "
        "bag category name — both make this total read lower than Sales Performance."
    )

    if category_totals.empty:
        return

    with st.container(border=True):
        top_categories = category_totals.nlargest(15, "TOTAL").sort_values("TOTAL", ascending=True)
        fig = go.Figure()
        fig.add_bar(
            y=top_categories["Category"], x=top_categories["TOTAL"], orientation="h",
            marker=dict(color=theme.sequential_colors(len(top_categories)), cornerradius=4),
        )
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(
            title="Top Categories by Bags Sold",
            height=max(360, 28 * len(top_categories)),
        )
        st.plotly_chart(fig, width="stretch")

    with st.container(border=True):
        st.caption("Click a column header's filter icon to search or narrow that column. Rows ending in \"Total\" are category subtotals.")
        grid.filterable_table(df.drop(columns=["sort_priority"]), pinned_columns=("Bag",))


@st.fragment()
def render_by_value(start_date: date, end_date: date) -> None:
    df = db.run_query(
        queries.PRODUCT_SALES_VALUE_BY_SHOP,
        {"start_date": start_date, "end_date": end_date},
    )

    if df.empty:
        st.info("No sales value recorded for this date range yet.")
        return

    totals = df[df["PRODUCT"].isin(TOTAL_LABELS)]
    detail = df[~df["PRODUCT"].isin(TOTAL_LABELS)].copy()

    masterfile_sales = totals.loc[totals["PRODUCT"] == "MASTERFILE TOTAL", "ACTUAL SALES"].sum()
    non_masterfile_sales = totals.loc[totals["PRODUCT"] == "NON-MASTERFILE TOTAL", "ACTUAL SALES"].sum()
    total_sales = masterfile_sales + non_masterfile_sales
    pct_masterfile = (masterfile_sales / total_sales * 100) if total_sales else 0.0

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Total Sales Value", f"KES {total_sales:,.0f}")
    with k2.container(border=True):
        st.metric("Masterfile Sales", f"KES {masterfile_sales:,.0f}")
    with k3.container(border=True):
        st.metric("Off-Catalog Sales", f"KES {non_masterfile_sales:,.0f}")
    with k4.container(border=True):
        st.metric("% Masterfile", f"{pct_masterfile:,.1f}%")

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · "
        "\"Actual Sales\" is KES-normalized (Uganda ÷29, Sinza ÷25) and should match "
        "Sales Performance's Revenue closely — combos only count here if flagged as a "
        "combo in Odoo. Sales Amount and Total Sales are local currency for Uganda/Sinza."
    )

    if detail.empty:
        return

    shops = sorted(s for s in detail["SHOP"].unique() if s)
    selected_shop = st.selectbox("Shop", ["All Shops"] + shops, key="products_value_shop_filter")
    filtered = detail if selected_shop == "All Shops" else detail[detail["SHOP"] == selected_shop]

    top_products = (
        filtered.groupby("PRODUCT", as_index=False)["ACTUAL SALES"]
        .sum()
        .nlargest(15, "ACTUAL SALES")
        .sort_values("ACTUAL SALES", ascending=True)
    )

    with st.container(border=True):
        fig = go.Figure()
        fig.add_bar(
            y=top_products["PRODUCT"], x=top_products["ACTUAL SALES"], orientation="h",
            marker=dict(color=theme.sequential_colors(len(top_products)), cornerradius=4),
        )
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(
            title=f"Top Products by Sales Value — {selected_shop}",
            height=max(360, 28 * len(top_products)),
        )
        st.plotly_chart(fig, width="stretch")

    with st.container(border=True):
        st.caption("Click a column header's filter icon to search or narrow that column.")
        grid.filterable_table(filtered, currency_columns=("ACTUAL SALES",))


@st.fragment()
def render_by_offer(start_date: date, end_date: date) -> None:
    df = db.run_query(
        queries.PRODUCT_LINE_ITEMS,
        {"start_date": start_date, "end_date": end_date},
    )

    if df.empty:
        st.info("No sales for this date range yet.")
        return

    df = deals.classify(df)

    total_revenue = df["Total"].sum()
    by_offer = df.groupby("Offer Type")["Total"].sum()
    power_revenue = by_offer.get("Power Deal", 0.0)
    dow_revenue = by_offer.get("Deal of the Week", 0.0)
    pct_on_offer = ((power_revenue + dow_revenue) / total_revenue * 100) if total_revenue else 0.0

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Total Revenue", f"KES {total_revenue:,.0f}")
    with k2.container(border=True):
        st.metric("Power Deal Revenue", f"KES {power_revenue:,.0f}")
    with k3.container(border=True):
        st.metric("Deal of the Week Revenue", f"KES {dow_revenue:,.0f}")
    with k4.container(border=True):
        st.metric("% of Sales on Offer", f"{pct_on_offer:,.1f}%")

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · "
        "a sale only counts under an offer if the price actually charged matches that "
        "offer's price — full-price sales of the same product are correctly excluded. "
        "Power Deals apply to Kenya-side shops only; Deals of the Week vary by shop and "
        "are curated monthly."
    )

    order = ["Power Deal", "Deal of the Week", "Regular"]
    ordered = by_offer.reindex(order).fillna(0)

    with st.container(border=True):
        fig = go.Figure()
        fig.add_bar(
            x=ordered.index, y=ordered.values,
            marker=dict(color=[OFFER_COLORS[o] for o in ordered.index], cornerradius=4),
        )
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="Revenue by Offer Type", height=360)
        st.plotly_chart(fig, width="stretch")

    offer_choice = st.selectbox(
        "Offer Type", ["All Offer Types", "Power Deal", "Deal of the Week", "Regular"],
        key="offer_type_filter",
    )
    filtered = df if offer_choice == "All Offer Types" else df[df["Offer Type"] == offer_choice]

    if not filtered.empty and offer_choice != "All Offer Types":
        with st.container(border=True):
            top_products = (
                filtered.groupby("Product", as_index=False)["Total"]
                .sum()
                .nlargest(15, "Total")
                .sort_values("Total", ascending=True)
            )
            fig = go.Figure()
            fig.add_bar(
                y=top_products["Product"], x=top_products["Total"], orientation="h",
                marker=dict(color=theme.sequential_colors(len(top_products)), cornerradius=4),
            )
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(
                title=f"Top Products — {offer_choice}",
                height=max(360, 28 * len(top_products)),
            )
            st.plotly_chart(fig, width="stretch")

    with st.container(border=True):
        display_df = filtered.sort_values("Date", ascending=False)
        if len(display_df) > MAX_TABLE_ROWS:
            st.caption(f"Showing first {MAX_TABLE_ROWS:,} of {len(display_df):,} rows.")
            display_df = display_df.head(MAX_TABLE_ROWS)
        st.caption("Click a column header's filter icon to search or narrow that column.")
        grid.filterable_table(display_df, currency_columns=("Price", "Total"))


with tab_shop:
    render_by_shop(start_date, end_date)

with tab_category:
    render_by_category(start_date, end_date)

with tab_value:
    render_by_value(start_date, end_date)

with tab_offers:
    render_by_offer(start_date, end_date)
