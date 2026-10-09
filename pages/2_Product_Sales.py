"""Product Sales — units sold by shop and product, masterfile vs off-catalog,
plus a wide by-category x store breakdown."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import (auth, charts, combos, db, deals, deals_sync, filters, grid, pricelists, queries,
                 sheets_sync, taxonomy, theme)

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

# Page level, deliberately NOT inside any of the tab fragments below. Every tab
# here is its own st.fragment, and a button inside one only reruns that one —
# so refreshing from By Shop cleared the cache but left Offer Types showing
# whatever it last drew, which is exactly how it went stale. At page level the
# click reruns the whole script and all five tabs re-read Postgres.
with col_refresh:
    if db.refresh_button(key="products_refresh"):
        # Offer Types is classified against the deal definitions, which are
        # cached with no TTL — clear those too, or a refresh re-reads the
        # sales but still classifies them against last hour's offers.
        deals._load_power_deals.clear()
        deals._load_deals_of_week.clear()

TOTAL_LABELS = ("MASTERFILE TOTAL", "NON-MASTERFILE TOTAL")
MAX_TABLE_ROWS = 5000
OFFER_COLORS = {
    "Power Deal": theme.CATEGORICAL[0],
    "Deal of the Week": theme.CATEGORICAL[2],
    "Singles": theme.CATEGORICAL[3],
    "Special Offers": theme.CATEGORICAL[6],
    "Combo": theme.CATEGORICAL[4],
    # A short dated pricelist rule running beside the tier ("300 off" and the
    # like) — its own label so it no longer inflates Deal of the Week.
    deals.TIMED_OFFER: theme.CATEGORICAL[5],
    # Sold below its usual price but on no list — amber, because it is a
    # discount that was given without being recorded, not a clean category.
    deals.UNLISTED: theme.STATUS["warning"],
    "Regular": theme.TEXT_MUTED,
}

# One section at a time, not st.tabs: Streamlit runs every tab's body on every
# rerun, hidden or not, so a date change on this page ran all six sections'
# queries (~26s for a month) to show one. Only the chosen section loads now.
SECTIONS = ["By Shop & Category", "By Location", "Sales Value", "Offer Types",
            "Self/Running Combos", "New Products"]
section = st.segmented_control("Section", SECTIONS, default=SECTIONS[0],
                               key="products_section", label_visibility="collapsed")
section = section if section in SECTIONS else SECTIONS[0]


@st.fragment()
def render_by_shop_category(start_date: date, end_date: date) -> None:
    """By Shop and By Category in one: every bag, its category and its sales
    at each shop, from the single Bags Sold query.

    The masterfile/off-catalog split is worked out here from the bag names
    rather than from a second query, so the merged section costs no more than
    By Category did on its own.
    """
    df = db.run_query(queries.BAGS_SOLD_BY_CATEGORY,
                      {"start_date": start_date, "end_date": end_date})
    if df.empty:
        st.info("No bags sold for this date range yet.")
        return

    detail = df[df["sort_priority"] == 0].copy()
    shop_cols = [c for c in df.columns
                 if c not in ("Bag", "TOTAL", "Category", "sort_priority")]
    sold_at = [c for c in shop_cols if detail[c].sum() != 0]

    shop = st.selectbox("Shop", ["All Shops"] + sold_at, key="products_shop_filter")
    detail["Qty"] = detail["TOTAL"] if shop == "All Shops" else detail[shop]
    shown = detail[detail["Qty"] != 0]
    shown = shown.assign(Masterfile=shown["Bag"].map(
        lambda b: taxonomy.family_of(b) != taxonomy.UNMAPPED))

    total = shown["Qty"].sum()
    masterfile = shown.loc[shown["Masterfile"], "Qty"].sum()
    by_cat = shown.groupby("Category", as_index=False)["Qty"].sum().sort_values("Qty")
    items = [
        ("Total Bags Sold", f"{total:,.0f}", shop),
        ("Masterfile", f"{masterfile / total * 100:.1f}%" if total else "—",
         f"{total - masterfile:,.0f} off-catalog bags"),
        ("Categories Sold", f"{len(by_cat):,}", None),
        ("Top Category", by_cat["Category"].iloc[-1] if not by_cat.empty else "—",
         f"{by_cat['Qty'].iloc[-1]:,.0f} bags" if not by_cat.empty else None),
        ("Bag Styles Sold", f"{len(shown):,}", None),
    ]
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")
    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · bags and gift bags, refunds "
        "netted, combos counted as the bags inside them · grouped by Odoo's bag category · "
        "a bag counts as masterfile when its family is in the masterfile, with style-code "
        "variants (\"Zula Black 018\") counted as their bag."
    )
    if shown.empty:
        return

    col_cat, col_prod = st.columns(2)
    with col_cat, st.container(border=True):
        top_cat = by_cat.tail(15)
        fig = go.Figure()
        fig.add_bar(y=top_cat["Category"], x=top_cat["Qty"], orientation="h",
                    marker=dict(color=theme.sequential_colors(len(top_cat)), cornerradius=4),
                    hovertemplate="<b>%{y}</b><br>%{x:,.0f} bags<extra></extra>")
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title=f"Bags Sold by Category — {shop}", hovermode="closest",
                          height=max(360, 28 * len(top_cat) + 80))
        theme.show(fig)
    with col_prod, st.container(border=True):
        top = shown.nlargest(15, "Qty").sort_values("Qty")
        fig = go.Figure()
        fig.add_bar(y=top["Bag"], x=top["Qty"], orientation="h",
                    marker=dict(color=theme.CATEGORICAL[0], cornerradius=4),
                    customdata=top[["Category"]],
                    hovertemplate="<b>%{y}</b><br>%{x:,.0f} bags · %{customdata[0]}<extra></extra>")
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title=f"Top Bags — {shop}", hovermode="closest",
                          height=max(360, 28 * len(top) + 80))
        theme.show(fig)

    with st.container(border=True):
        if shop == "All Shops":
            st.caption("Every bag by shop. Rows ending in \"Total\" are category subtotals.")
            table = df.drop(columns=["sort_priority"])
            table = table[["Bag", "Category"] + sold_at + ["TOTAL"]]
        else:
            st.caption(f"Bags sold at {shop}, by category.")
            table = (shown[["Bag", "Category", "Qty", "Masterfile"]]
                     .sort_values(["Category", "Qty"], ascending=[True, False])
                     .rename(columns={"Qty": "Qty Sold"}))
            table["Masterfile"] = table["Masterfile"].map({True: "Yes", False: "No"})
        grid.filterable_table(table, pinned_columns=("Bag",))

    off = shown[~shown["Masterfile"]]
    if not off.empty:
        with st.container(border=True):
            st.caption(f"Off-catalog bags — sold but not in the masterfile ({off['Qty'].sum():,.0f} bags).")
            grid.filterable_table(off[["Bag", "Category", "Qty"]].sort_values("Qty", ascending=False)
                                  .rename(columns={"Qty": "Qty Sold"}), height=260)


@st.fragment()
def render_combos(start_date: date, end_date: date) -> None:
    """Running combos against self-made ones, and what customers ask to combine."""
    raw = db.run_query(queries.COMBO_SALES, {"start_date": start_date, "end_date": end_date})
    if raw.empty:
        st.info("No combos sold in this date range.")
        return
    df = combos.classify(raw)

    locations = sorted(df["Location"].unique())
    location = st.selectbox("Location", ["All Locations"] + locations, key="combos_location")
    if location != "All Locations":
        df = df[df["Location"] == location]
    if df.empty:
        st.info("No combos sold at this location in this range.")
        return

    running = df[df["Type"] == combos.RUNNING]
    selfmade = df[df["Type"] == combos.SELF_MADE]
    total_rev = df["Revenue"].sum()
    items = [
        ("Running Combos", f"KES {running['Revenue'].sum():,.0f}",
         f"{running['Bundles'].sum():,.0f} bundles · {running['Combo'].nunique()} combos"),
        ("Self-made Combos", f"KES {selfmade['Revenue'].sum():,.0f}",
         f"{selfmade['Bundles'].sum():,.0f} bundles · {selfmade['Combo'].nunique()} combos"),
        ("Self-made Share", f"{selfmade['Revenue'].sum() / total_rev * 100:.1f}%" if total_rev else "—",
         "of combo revenue"),
        ("Avg Bundle Price", f"KES {total_rev / max(df['Bundles'].sum(), 1):,.0f}",
         f"running KES {running['Revenue'].sum() / max(running['Bundles'].sum(), 1):,.0f} · "
         f"self-made KES {selfmade['Revenue'].sum() / max(selfmade['Bundles'].sum(), 1):,.0f}"),
    ]
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")
    st.caption(
        "Running combos are the catalogue offers (\"Jumbo + Standard or Liam Travel + …\"). "
        "Self-made combos are put together for a customer: the name says \"Combo\" and usually "
        "gives each bag's colour (\"Mega Green + Man Bag Brown Combo\"). Bundles and revenue "
        "are net of refunds."
    )

    st.subheader("Running Combos")
    if running.empty:
        st.info("No running combos sold in this range.")
    else:
        perf = (running.groupby("Combo", as_index=False)
                .agg(Bundles=("Bundles", "sum"), Revenue=("Revenue", "sum"),
                     Locations=("Location", "nunique"))
                .sort_values("Revenue", ascending=False))
        perf["Avg Price"] = (perf["Revenue"] / perf["Bundles"]).round(0)
        perf["Share %"] = (perf["Revenue"] / perf["Revenue"].sum() * 100).round(1)
        with st.container(border=True):
            top = perf.head(12).sort_values("Revenue")
            fig = go.Figure()
            fig.add_bar(y=top["Combo"], x=top["Revenue"], orientation="h",
                        marker=dict(color=theme.CATEGORICAL[4], cornerradius=4),
                        customdata=top[["Bundles"]],
                        hovertemplate="<b>%{y}</b><br>KES %{x:,.0f}<br>%{customdata[0]:,.0f} bundles"
                                      "<extra></extra>")
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="Running Combos by Revenue", hovermode="closest",
                              height=max(360, 30 * len(top) + 80))
            fig.update_yaxes(automargin=True)
            theme.show(fig)
        with st.container(border=True):
            grid.filterable_table(perf, currency_columns=("Revenue", "Avg Price"),
                                  pinned_columns=("Combo",), height=320)

    st.subheader("Self-made Combos")
    if selfmade.empty:
        st.info("No self-made combos sold in this range.")
        return
    patterns = combos.self_made_patterns(selfmade)
    st.caption("What customers ask to have combined. Each pairing groups every self-made combo "
               "that put those two bags together, whatever the colours — a pairing that keeps "
               "coming back is a candidate for a future running combo.")
    col_pairs, col_bags = st.columns(2)
    with col_pairs, st.container(border=True):
        top = patterns["pairs"].head(12).sort_values("Bundles")
        fig = go.Figure()
        fig.add_bar(y=top["Pairing"], x=top["Bundles"], orientation="h",
                    marker=dict(color=theme.CATEGORICAL[2], cornerradius=4),
                    customdata=top[["Revenue", "Versions"]],
                    hovertemplate="<b>%{y}</b><br>%{x:,.0f} bundles · KES %{customdata[0]:,.0f}"
                                  "<br>%{customdata[1]} colour versions<extra></extra>")
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="Most-Requested Pairings", hovermode="closest",
                          height=max(360, 30 * len(top) + 80))
        theme.show(fig)
    with col_bags, st.container(border=True):
        top = patterns["bags"].head(12).sort_values("Bundles")
        fig = go.Figure()
        fig.add_bar(y=top["Bag"], x=top["Bundles"], orientation="h",
                    marker=dict(color=theme.CATEGORICAL[6], cornerradius=4),
                    hovertemplate="<b>%{y}</b><br>in %{x:,.0f} self-made bundles<extra></extra>")
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="Bags Most Often in a Self-made Combo", hovermode="closest",
                          height=max(360, 30 * len(top) + 80))
        theme.show(fig)

    col_colours, col_where = st.columns(2)
    with col_colours, st.container(border=True):
        colours = patterns["colours"]
        if not colours.empty:
            data = charts.fold_other(colours["Colour"], colours["Bundles"])
            charts.share_chart(data, title="Colours Requested", key="combos_colour_kind",
                               unit="bags", default="Bar")
    with col_where, st.container(border=True):
        where = (selfmade.groupby("Location", as_index=False)["Bundles"].sum())
        charts.share_chart(charts.fold_other(where["Location"], where["Bundles"]),
                           title="Self-made Combos by Location", key="combos_location_kind",
                           unit="bundles", default="Bar")

    with st.container(border=True):
        st.caption("Pairings, with how many different colour versions were made.")
        grid.filterable_table(patterns["pairs"], currency_columns=("Revenue",),
                              pinned_columns=("Pairing",), height=300)
    with st.container(border=True):
        st.caption("Every self-made combo sold in the range.")
        each = (selfmade.groupby(["Combo"], as_index=False)
                .agg(Bundles=("Bundles", "sum"), Revenue=("Revenue", "sum"),
                     Locations=("Location", lambda v: ", ".join(sorted(set(v)))),
                     **{"First Sold": ("First Sold", "min"), "Last Sold": ("Date", "max")})
                .sort_values(["Bundles", "Revenue"], ascending=False))
        grid.filterable_table(each, currency_columns=("Revenue",), pinned_columns=("Combo",),
                              height=360)


def _with_family_subtotals(rows: pd.DataFrame, shops: list[str]) -> pd.DataFrame:
    """Rows alphabetical, with a subtotal line after each bag family.

    "Ace Black TT", "Ace Chocolate", "Ace Cracked", then "ACE Total" — the
    colours of one bag read as a block and the block carries its own number,
    which is what anyone counting stock actually wants.
    """
    value_columns = shops + ["TOTAL"]
    rows = rows.assign(
        _family=[taxonomy.group_of(bag) for bag in rows["Bag"]]
    ).sort_values(["_family", "Bag"], key=lambda col: col.str.upper())

    out = []
    for family, group in rows.groupby("_family", sort=False):
        out.append(group.drop(columns="_family"))
        out.append(pd.DataFrame([{
            "Bag": f"{family.upper()} Total",
            **{c: group[c].sum() for c in value_columns},
        }]))
    out.append(pd.DataFrame([{
        "Bag": "GRAND TOTAL",
        **{c: rows[c].sum() for c in value_columns},
    }]))
    return pd.concat(out, ignore_index=True)


@st.fragment()
def render_by_location(start_date: date, end_date: date) -> None:
    """Two plain quantity tables: the bags counted, and everything left out.

    The second exists so the excluded lines are still watchable — a strap, a
    delivery fee or a combo bundle does not count as a bag sold, but it still
    moved through the till and someone has to be able to see it.
    """
    params = {"start_date": start_date, "end_date": end_date}
    bags = db.run_query(queries.BAGS_SOLD_BY_CATEGORY, params)
    excluded = db.run_query(queries.EXCLUDED_FROM_BAGS_SOLD, params)

    st.subheader("Bags Sold by Location")
    if bags.empty:
        st.info("No bags sold in this date range yet.")
    else:
        rows = bags[bags["sort_priority"] == 0].drop(
            columns=["sort_priority", "Category"])
        shops = [c for c in rows.columns if c not in ("Bag", "TOTAL")]
        # Only the shops that actually sold something, so the table is not
        # mostly zeros.
        shops = [c for c in shops if rows[c].sum() != 0]
        rows = rows[["Bag"] + shops + ["TOTAL"]]
        st.caption(
            f"{len(rows):,} bags across {len(shops)} locations · alphabetical, with "
            "a subtotal after each bag's colours · quantities only, a refunded bag "
            "counted as a movement, combo contents counted as the bags they are."
        )
        with st.container(border=True):
            grid.filterable_table(_with_family_subtotals(rows, shops),
                                  pinned_columns=("Bag",))

    st.subheader("Excluded from Bags Sold")
    if excluded.empty:
        st.info("Nothing was excluded in this date range.")
        return
    wide = excluded.pivot_table(index=["Item", "Reason"], columns="Shop",
                                values="Qty", aggfunc="sum", fill_value=0).reset_index()
    shop_cols = [c for c in wide.columns if c not in ("Item", "Reason")]
    wide["TOTAL"] = wide[shop_cols].sum(axis=1)
    wide = wide.sort_values(["Reason", "TOTAL"], ascending=[True, False])
    by_reason = (excluded.groupby("Reason")
                 .agg(Items=("Qty", "sum"), KES=("KES", "sum"))
                 .sort_values("Items", ascending=False).reset_index())
    cols = st.columns(min(len(by_reason), 4) or 1)
    for col, (_, row) in zip(cols, by_reason.iterrows()):
        with col.container(border=True):
            st.metric(row["Reason"], f"{row['Items']:,.0f}",
                      f"KES {row['KES']:,.0f}", delta_color="off")
    st.caption(
        "Why each line is out of the bag count: straps and accessories are not "
        "bags, and delivery fees and order-level discounts are money rather than "
        "stock. They still count towards revenue. Combo bundles are not listed — "
        "the bags inside them are already counted in Bags Sold."
    )
    with st.container(border=True):
        grid.filterable_table(wide, pinned_columns=("Item",))


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
        theme.show(fig, width="stretch")

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

    # The curated lists only describe promotions somebody wrote down, and most
    # are not: over Sept 1-14 2026, 627 of the 747 sales made below their usual
    # price appeared on no list at all. Comparing each sale against what that
    # bag normally fetches at that shop catches the discount either way, so the
    # tab stops reporting discounted trade as full-price Regular.
    usual = db.run_query(queries.USUAL_PRICES, {"end_date": end_date})
    df = deals.apply_usual_prices(df, usual)

    # The spreadsheet is a hand-transcription of what Odoo already holds as
    # dated pricelist rules, and it is an incomplete one: for the 12-26
    # September tier Odoo carries 37 bag families across 18 shops where the
    # sheet recorded 31 across 14. Reading the archived rules alongside it
    # recovers the deals nobody wrote down.
    df = deals.apply_pricelist_deals(df, pricelists.deals_in_window(start_date, end_date))

    # A month with no recorded offer list reports zero deals, which reads as
    # "nothing was on promotion" rather than "we don't know what was". Say so.
    missing = deals.periods_without_definitions(start_date, end_date)
    if missing:
        shown = missing[:6]
        more = f"\n\n…and {len(missing) - 6} more month(s)." if len(missing) > 6 else ""
        st.warning(
            "Offer records are missing for part of this range, so sales there "
            "fall through to Regular — a zero below is a gap in the records, "
            "not a month without promotions:\n\n"
            + "\n".join(f"- {m}" for m in shown)
            + more,
            icon="⚠️",
        )

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

    unlisted_revenue = by_offer_revenue.get(deals.UNLISTED, 0.0)
    unlisted_qty = by_offer_qty.get(deals.UNLISTED, 0.0)
    discount_given = df["Discount Value"].sum() if "Discount Value" in df.columns else 0.0

    k1, k2, k3, k4, k5, k6 = st.columns(6)
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
        st.metric(
            "Unlisted Discounts", f"KES {unlisted_revenue:,.0f}",
            f"{unlisted_qty:,.0f} bags sold", delta_color="off",
            help="Sold below what that bag normally fetches at that shop, but on "
                 "no Power Deal, Deal of the Week, Singles or Special Offers "
                 "list. Either a promotion nobody recorded, or a discount given "
                 "at the till.",
        )
    with k6.container(border=True):
        st.metric(
            "% of Sales on Offer", f"{pct_on_offer:,.1f}%",
            f"KES {discount_given:,.0f} off list", delta_color="off",
            help="Counts every sale made below full price, whether or not the "
                 "promotion was written down. The figure underneath is the total "
                 "given away against the usual price.",
        )

    # Deal of the Week rotates weekly, so the sheet gains products through the
    # month and the stored lists drift out of date within days. When that goes
    # unnoticed the tab quietly under-reports — August 2026 lost 740 bags to
    # Regular that way — so say plainly how old these lists are.
    synced = deals.last_synced()
    if synced is None:
        st.info(
            "These offer lists came from the repository, not from a sync on this "
            "deployment — click **Sync Offers from Sheet** to confirm they match "
            "the spreadsheet.",
            icon="ℹ️",
        )
    else:
        age = datetime.now() - synced
        days = age.days
        when = ("today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago")
        if days >= deals.SYNC_STALE_AFTER_DAYS:
            st.warning(
                f"Offers last synced **{when}** ({synced:%d %b %Y, %H:%M}). Deal of "
                "the Week rotates weekly, so the sheet has probably moved on — "
                "sales matching newer offers are being counted as Regular until "
                "you sync.",
                icon="⚠️",
            )
        else:
            st.caption(f"🔄 Offers last synced {when} · {synced:%d %b %Y, %H:%M}")

    col_caption, col_sync_offers, col_sync = st.columns([2.2, 1.4, 1])
    with col_caption:
        st.caption(
            f"Last updated {datetime.now().strftime('%H:%M:%S')} · "
            "a sale only counts under an offer if the price actually charged is below "
            "that offer's original price — full-price sales of the same product are "
            "correctly excluded. Power Deals apply to Kenya-side shops only; Deals of "
            "the Week vary by shop and run in two-week cycles, Sunday to the Saturday after "
            "next (27 Sep - 10 Oct 2026, 11 - 24 Oct, …), counted from 27 Sep 2026. Uganda and Sinza use "
            "their own sheets' category names — Singles and Special Offers — rather "
            "than Deal of the Week."
        )
    with col_sync_offers:
        if st.button("📥 Sync Offers from Sheet", key="sync_offers_from_sheet", width="stretch",
                      help="Pulls the latest Power Deal / Deal of the Week / Singles / Special Offers "
                           "definitions from the deals spreadsheet (Kenya, Uganda, Tanzania tabs). "
                           "Updates local files only — still needs review and a push to reach the "
                           "deployed app."):
            with st.spinner("Pulling offers from the deals spreadsheet…"):
                try:
                    # Archive Odoo's dated pricelist rules in the same breath.
                    # Odoo keeps only a rule's current state — they get edited,
                    # deactivated and replaced each tier, and the 1-11 Sept
                    # window had already vanished before this was written — so
                    # each snapshot appends what is true now to a history that
                    # survives the next edit.
                    snap = pricelists.snapshot()
                    if snap["new"]:
                        st.info(
                            f"Archived {snap['new']} new pricelist rule(s) from Odoo "
                            f"({snap['total']} on record).", icon="🗄️",
                        )
                    result = deals_sync.sync()
                    st.success(
                        f"Kenya: {result['kenya_power']} Power Deal row(s) (Deal of the Week "
                        f"comes from each cycle's posters, not the sheet). Uganda: {result['uganda']} row(s). Sinza: "
                        f"{result['tanzania']} row(s). Written: {result['dow_rows_written']} "
                        f"Deal-of-the-Week-style + {result['power_rows_written']} Power Deal product(s)."
                    )
                    if result["unresolved"]:
                        st.warning(
                            f"{len(result['unresolved'])} product name(s) couldn't be auto-matched "
                            "and were skipped — add these to MANUAL_ALIASES in lib/deals_sync.py:"
                        )
                        st.dataframe(pd.DataFrame(result["unresolved"]), width="stretch", hide_index=True)
                    st.info("Local files updated — review the diff (git diff lib/data/) and push to ship this.")
                except Exception as exc:
                    st.error(f"Sync failed: {exc}")
    with col_sync:
        if st.button("📤 Sync to Sheet", key="sync_deals_sheet", width="stretch",
                      help="Syncs the whole current year, regardless of the date filter above — "
                           "not just prior years' matches, deals.classify() matches by month name "
                           "only (no year), so this stays capped to this year rather than pulling "
                           "in every year that ever had a July/August."):
            with st.spinner("Writing to the deals tracker sheet…"):
                try:
                    # Always the full current year, independent of the page's date
                    # filter — deals.classify() matches by month name only, not
                    # year, so widening this to all-time would relabel prior
                    # years' July/August sales as this year's promotions too.
                    sync_start = date(date.today().year, 1, 1)
                    sync_end = date(date.today().year, 12, 31)
                    full_df = db.run_query(
                        queries.PRODUCT_LINE_ITEMS,
                        {"start_date": sync_start, "end_date": sync_end},
                    )
                    classified_full = deals.classify(full_df)
                    written = sheets_sync.sync(classified_full, sync_start, sync_end)
                    st.success(
                        f"Synced {sync_start:%b %d} – {sync_end:%b %d}: "
                        f"{written['Power Deal']} Power Deal row(s), "
                        f"{written['Deal of the Week']} Deal of the Week row(s)."
                    )
                except Exception as exc:
                    st.error(f"Sync failed: {exc}")

    # Every label classify can give, so the bars add up to the tab's revenue.
    order = ["Power Deal", "Deal of the Week", "Singles", "Special Offers",
             deals.TIMED_OFFER, "Combo", deals.UNLISTED, "Regular"]
    ordered = by_offer_revenue.reindex(order).fillna(0)

    with st.container(border=True):
        fig = go.Figure()
        fig.add_bar(
            x=ordered.index, y=ordered.values,
            marker=dict(color=[OFFER_COLORS[o] for o in ordered.index], cornerradius=4),
        )
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="Revenue by Offer Type", height=360)
        theme.show(fig, width="stretch")

    # Order-level promotions ride as their own line ("300.0 KES discount on
    # total amount") rather than as a product price, so they are invisible to
    # everything above — which left a promotion running since April 2026 out of
    # a page whose job is reporting offers.
    order_offers = db.run_query(
        queries.ORDER_DISCOUNTS, {"start_date": start_date, "end_date": end_date}
    )
    if not order_offers.empty:
        st.subheader("Order-Level Offers")
        st.caption(
            "Discounts applied to a whole order rather than by repricing a bag — "
            "they sit outside the categories above, so they are counted here "
            "instead of being double-counted there."
        )
        by_offer = (
            order_offers.groupby("Offer", as_index=False)
            .agg(Times=("Times Given", "sum"), Value=("Value", "sum"))
            .sort_values("Value")
        )
        cols = st.columns(min(len(by_offer), 4) or 1)
        for col, (_, row) in zip(cols, by_offer.iterrows()):
            with col.container(border=True):
                st.metric(
                    row["Offer"][:34], f"KES {abs(row['Value']):,.0f}",
                    f"{int(row['Times']):,} times", delta_color="off",
                )
        with st.container(border=True):
            grid.filterable_table(order_offers, height=260)

    col_offer, col_country, col_location = st.columns(3)
    with col_offer:
        offer_choice = st.selectbox(
            "Offer Type",
            ["All Offer Types", "Power Deal", "Deal of the Week", "Singles",
             "Special Offers", deals.TIMED_OFFER, deals.UNLISTED, "Combo", "Regular"],
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

    if offer_choice == deals.DOW and not filtered.empty:
        # Each two-week cycle by its dates ("27 Sep - 10 Oct").
        tier_labels = (filtered["Tier"].fillna("").astype(str).str.strip() + " · "
                       + filtered["Deal Window"].fillna("").astype(str).str.strip())
        tier_labels = tier_labels.str.strip(" ·").replace("", "No period recorded")
        options = sorted(tier_labels.unique(),
                         key=lambda label: (label == "No period recorded", label))
        tier_choice = st.selectbox(
            "Deal Period", ["All Periods"] + options, key="offer_type_tier_filter",
            help="Deal of the Week runs in two-week cycles, Sunday to the Saturday after next.",
        )
        if tier_choice != "All Periods":
            filtered = filtered[tier_labels == tier_choice]

    if offer_choice == "Combo" and "Bundles" in filtered.columns:
        # The combos themselves, not the bags packed inside them: one row per
        # bundle sold, its Quantity the number of combos.
        filtered = filtered[filtered["Bundles"] > 0].assign(Quantity=lambda f: f["Bundles"])
    unit = "combo" if offer_choice == "Combo" else "bag"

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
                hovertemplate="<b>%{y}</b><br>KES %{x:,.0f}<extra></extra>",
            )
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(
                hovermode="closest",
                title=f"Top Products — {offer_choice}",
                height=max(360, 28 * len(top_products)),
            )
            theme.show(fig, width="stretch")

    if not filtered.empty:
        with st.container(border=True):
            st.caption(
                f"{unit.title()}s sold — {offer_choice} · {country_choice} · {location_choice} — "
                f"with total quantity and revenue per {unit}."
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
        display_df = filtered.drop(columns=["Bundles"], errors="ignore").sort_values("Date", ascending=False)
        if len(display_df) > MAX_TABLE_ROWS:
            st.caption(f"Showing first {MAX_TABLE_ROWS:,} of {len(display_df):,} rows.")
            display_df = display_df.head(MAX_TABLE_ROWS)
        st.caption("Click a column header's filter icon to search or narrow that column.")
        grid.filterable_table(display_df, currency_columns=("Price", "Total"))


NEW_PRODUCTS_FILE = "new_products.csv"


def _tracked_new_products() -> list[str]:
    """The collections the team is tracking as new, one per line in the file."""
    path = Path(__file__).resolve().parent.parent / "lib" / "data" / NEW_PRODUCTS_FILE
    try:
        names = pd.read_csv(path)["product"].dropna().astype(str).str.strip()
    except (FileNotFoundError, KeyError, pd.errors.EmptyDataError):
        return []
    return [n for n in dict.fromkeys(names) if n]


@st.fragment()
def render_new_products(start_date: date, end_date: date) -> None:
    families = _tracked_new_products()
    if not families:
        st.info(f"No new collections listed — add them to lib/data/{NEW_PRODUCTS_FILE}.")
        return

    df = db.run_query(
        queries.NEW_PRODUCTS,
        {"start_date": start_date, "end_date": end_date, "families": families},
    )

    total_revenue = df["Revenue"].sum()
    total_qty = df["Quantity Sold"].sum()

    k1, k2, k3 = st.columns(3)
    with k1.container(border=True):
        selling = int((df["Quantity Sold"] > 0).sum())
        st.metric("New Collections", f"{len(df):,}", f"{selling} selling in this range",
                  delta_color="off")
    with k2.container(border=True):
        st.metric("Revenue", f"KES {total_revenue:,.0f}")
    with k3.container(border=True):
        st.metric("Units Sold", f"{total_qty:,.0f}")

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · the collections listed in "
        f"lib/data/{NEW_PRODUCTS_FILE} — edit that file to add or retire one. Each covers "
        "every colour and variant of the bag (Loop BP includes Loop BP CN and reject stock). "
        "Quantity Sold and Revenue follow the date range above; Units Since Launch does not. "
        "Bags are counted the way Bags Sold counts them, and revenue nets refunds."
    )

    selling_rows = df[df["Revenue"] > 0]
    if not selling_rows.empty:
        with st.container(border=True):
            top = selling_rows.sort_values("Revenue", ascending=True)
            fig = go.Figure()
            fig.add_bar(
                y=top["Product"], x=top["Revenue"], orientation="h",
                marker=dict(color=theme.sequential_colors(len(top)), cornerradius=4),
                customdata=top[["Quantity Sold"]],
                hovertemplate=("<b>%{y}</b><br>KES %{x:,.0f}<br>"
                               "%{customdata[0]:,.0f} bags<extra></extra>"),
            )
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="New Collections by Revenue",
                              height=max(360, 32 * len(top) + 80), hovermode="closest")
            theme.show(fig, width="stretch")

    with st.container(border=True):
        st.caption("Click a column header's filter icon to search or narrow that column.")
        grid.filterable_table(df, currency_columns=("Revenue",))

RENDERERS = {
    "By Shop & Category": render_by_shop_category,
    "By Location": render_by_location,
    "Sales Value": render_by_value,
    "Offer Types": render_by_offer,
    "Self/Running Combos": render_combos,
    "New Products": render_new_products,
}
RENDERERS[section](start_date, end_date)
