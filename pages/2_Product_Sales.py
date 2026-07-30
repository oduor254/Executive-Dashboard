"""Product Sales — units sold by shop and product, masterfile vs off-catalog,
plus a wide by-category x store breakdown."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, deals, filters, grid, queries, sheets_sync, theme

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
    "Singles": theme.CATEGORICAL[3],
    "Special Offers": theme.CATEGORICAL[6],
    "Combo": theme.CATEGORICAL[4],
    "Regular": theme.TEXT_MUTED,
}

tab_shop, tab_category, tab_value, tab_offers, tab_new_products = st.tabs(
    ["By Shop", "By Category", "Sales Value", "Offer Types", "New Products"]
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
    total_qty = df["Quantity"].sum()
    by_offer_revenue = df.groupby("Offer Type")["Total"].sum()
    by_offer_qty = df.groupby("Offer Type")["Quantity"].sum()
    power_revenue = by_offer_revenue.get("Power Deal", 0.0)
    power_qty = by_offer_qty.get("Power Deal", 0.0)
    dow_revenue = by_offer_revenue.get("Deal of the Week", 0.0)
    dow_qty = by_offer_qty.get("Deal of the Week", 0.0)
    combo_revenue = by_offer_revenue.get("Combo", 0.0)
    combo_qty = by_offer_qty.get("Combo", 0.0)
    regular_revenue = by_offer_revenue.get("Regular", 0.0)
    # Anything that isn't a full-price sale or a bundle counts as "on offer" —
    # covers Power Deal/Deal of the Week plus Uganda/Sinza's Singles and
    # Special Offers, without having to name every category here.
    pct_on_offer = ((total_revenue - regular_revenue - combo_revenue) / total_revenue * 100) if total_revenue else 0.0

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1.container(border=True):
        st.metric("Total Revenue", f"KES {total_revenue:,.0f}", f"{total_qty:,.0f} bags sold", delta_color="off")
    with k2.container(border=True):
        st.metric("Power Deal Revenue", f"KES {power_revenue:,.0f}", f"{power_qty:,.0f} bags sold", delta_color="off")
    with k3.container(border=True):
        st.metric("Deal of the Week Revenue", f"KES {dow_revenue:,.0f}", f"{dow_qty:,.0f} bags sold", delta_color="off")
    with k4.container(border=True):
        st.metric(
            "Combo Revenue", f"KES {combo_revenue:,.0f}", f"{combo_qty:,.0f} bags sold", delta_color="off",
            help="Bags sold counts each bag in the bundle, not each bundle — "
                 "e.g. \"Safiri Travel + Standard Travel or Antitheft Backpack\" is 2 bags.",
        )
    with k5.container(border=True):
        st.metric("% of Sales on Offer", f"{pct_on_offer:,.1f}%")

    col_caption, col_sync = st.columns([3, 1])
    with col_caption:
        st.caption(
            f"Last updated {datetime.now().strftime('%H:%M:%S')} · "
            "a sale only counts under an offer if the price actually charged is below "
            "that offer's original price — full-price sales of the same product are "
            "correctly excluded. Power Deals apply to Kenya-side shops only; Deals of "
            "the Week vary by shop and are curated monthly. Uganda and Sinza use "
            "their own sheets' category names — Singles and Special Offers — rather "
            "than Deal of the Week."
        )
    with col_sync:
        if st.button("📤 Sync to Sheet", key="sync_deals_sheet", width="stretch"):
            with st.spinner("Writing to the deals tracker sheet…"):
                try:
                    written = sheets_sync.sync(df, start_date, end_date)
                    st.success(
                        f"Synced {start_date:%b %d} – {end_date:%b %d}: "
                        f"{written['Power Deal']} Power Deal row(s), "
                        f"{written['Deal of the Week']} Deal of the Week row(s)."
                    )
                except Exception as exc:
                    st.error(f"Sync failed: {exc}")

    order = ["Power Deal", "Deal of the Week", "Singles", "Special Offers", "Combo", "Regular"]
    ordered = by_offer_revenue.reindex(order).fillna(0)

    with st.container(border=True):
        fig = go.Figure()
        fig.add_bar(
            x=ordered.index, y=ordered.values,
            marker=dict(color=[OFFER_COLORS[o] for o in ordered.index], cornerradius=4),
        )
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="Revenue by Offer Type", height=360)
        st.plotly_chart(fig, width="stretch")

    col_offer, col_country, col_location = st.columns(3)
    with col_offer:
        offer_choice = st.selectbox(
            "Offer Type",
            ["All Offer Types", "Power Deal", "Deal of the Week", "Singles", "Special Offers", "Combo", "Regular"],
            key="offer_type_filter",
        )
    with col_country:
        country_choice = st.selectbox(
            "Country", ["All Countries", "Kenya", "Uganda", "Sinza"],
            key="offer_type_country_filter",
        )
    with col_location:
        locations = sorted(df["Location"].dropna().unique())
        location_choice = st.selectbox(
            "Location", ["All Locations"] + locations, key="offer_type_location_filter",
        )

    filtered = df if offer_choice == "All Offer Types" else df[df["Offer Type"] == offer_choice]
    filtered = filtered if country_choice == "All Countries" else filtered[filtered["Country"] == country_choice]
    filtered = filtered if location_choice == "All Locations" else filtered[filtered["Location"] == location_choice]

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

    if not filtered.empty:
        with st.container(border=True):
            st.caption(
                f"Bags sold — {offer_choice} · {country_choice} · {location_choice} — "
                "with total quantity and revenue per bag."
            )
            bag_summary = (
                filtered.groupby("Product", as_index=False)
                .agg(Quantity=("Quantity", "sum"), Total=("Total", "sum"))
                .sort_values("Total", ascending=False)
            )
            totals_row = pd.DataFrame([{
                "Product": "TOTAL",
                "Quantity": bag_summary["Quantity"].sum(),
                "Total": bag_summary["Total"].sum(),
            }])
            bag_summary = pd.concat([bag_summary, totals_row], ignore_index=True)
            grid.filterable_table(bag_summary, currency_columns=("Total",))

    with st.container(border=True):
        display_df = filtered.sort_values("Date", ascending=False)
        if len(display_df) > MAX_TABLE_ROWS:
            st.caption(f"Showing first {MAX_TABLE_ROWS:,} of {len(display_df):,} rows.")
            display_df = display_df.head(MAX_TABLE_ROWS)
        st.caption("Click a column header's filter icon to search or narrow that column.")
        grid.filterable_table(display_df, currency_columns=("Price", "Total"))


@st.fragment()
def render_new_products() -> None:
    df = db.run_query(queries.NEW_PRODUCTS)

    if df.empty:
        st.info("No new collections in the last 6 months that meet the volume/price bar yet.")
        return

    total_products = len(df)
    total_revenue = df["Revenue"].sum()
    total_qty = df["Quantity Sold"].sum()

    k1, k2, k3 = st.columns(3)
    with k1.container(border=True):
        st.metric("New Collections", f"{total_products:,}")
    with k2.container(border=True):
        st.metric("Revenue So Far", f"KES {total_revenue:,.0f}")
    with k3.container(border=True):
        st.metric("Units Sold", f"{total_qty:,.0f}")

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · "
        "a product counts as a new collection once its first-ever sale falls within the "
        "last 6 months, it has sold at least 30 units, and averages at least KES 1,000/unit "
        "— separates genuine new collections from one-off corporate/custom orders and cheap "
        "accessories, picked up and aged out automatically, no list to maintain by hand. "
        "Combos and internal samples are excluded."
    )

    with st.container(border=True):
        top = df.nlargest(15, "Revenue").sort_values("Revenue", ascending=True)
        fig = go.Figure()
        fig.add_bar(
            y=top["Product"], x=top["Revenue"], orientation="h",
            marker=dict(color=theme.sequential_colors(len(top)), cornerradius=4),
        )
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="New Collections by Revenue", height=max(360, 28 * len(top)))
        st.plotly_chart(fig, width="stretch")

    with st.container(border=True):
        st.caption("Click a column header's filter icon to search or narrow that column.")
        grid.filterable_table(df, currency_columns=("Revenue",))


with tab_shop:
    render_by_shop(start_date, end_date)

with tab_category:
    render_by_category(start_date, end_date)

with tab_value:
    render_by_value(start_date, end_date)

with tab_offers:
    render_by_offer(start_date, end_date)

with tab_new_products:
    render_new_products()
