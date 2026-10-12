"""Stock Levels — what the shops hold now (Shop Stocks), and what they will
need: top sellers, the stock report and min/max levels against the targets
(Stock Prediction & Movement)."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, charts, colors, db, grid, queries, theme
from lib import stock_planning as sp

st.set_page_config(page_title="Stock · Denri Executive Dashboard", page_icon="📦", layout="wide")

auth.require_login()

st.title("📦 Stock Levels")
st.caption("Live stock by location and product, and what the shops will need — straight from "
           "Postgres. No date range: stock is the current state, sales are the last 90 days.")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

_, col_refresh = st.columns([3, 1])
with col_refresh:
    db.refresh_button(key="stock_refresh")


def _section(options: list[str], key: str) -> str:
    """Only the chosen section runs (st.tabs would run them all)."""
    choice = st.segmented_control("Section", options, default=options[0], key=key,
                                  label_visibility="collapsed")
    return choice if choice in options else options[0]


def _kpis(items: list[tuple[str, str, str | None]]) -> None:
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")


# ----------------------------------------------------------- Shop Stocks ---

@st.fragment()
def render_shop_stock() -> None:
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
        theme.show(fig, width="stretch")

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
        theme.show(fig, width="stretch")

    with st.container(border=True):
        st.caption("Click a column header's filter icon to search or narrow that column.")
        grid.filterable_table(filtered)

    st.subheader("Cumulative Stock by Product")
    st.caption("Every location and color variant combined into one product — e.g. Ace Black TT + Ace Grey + Ace Cracked all count as \"Ace\" — highest quantity first.")

    with st.container(border=True):
        cumulative = df.copy()
        cumulative["Product"] = cumulative["Product"].map(colors.strip_color)
        cumulative = (
            cumulative.groupby("Product", as_index=False)["Quantity"]
            .sum()
            .sort_values("Quantity", ascending=False)
        )
        grid.filterable_table(cumulative)

    st.subheader("Stock by Product & Color")
    st.caption("Every color variant, every location combined — each product's colors followed by a TOTAL row before the next product.")

    with st.container(border=True):
        per_color = df.groupby("Product", as_index=False)["Quantity"].sum()
        per_color = per_color[per_color["Quantity"] > 0]
        per_color["Family"] = per_color["Product"].map(colors.strip_color)

        blocks = []
        for family in sorted(per_color["Family"].unique()):
            group = per_color.loc[per_color["Family"] == family, ["Product", "Quantity"]]
            blocks.append(group.sort_values("Quantity", ascending=False))
            blocks.append(pd.DataFrame([{"Product": f"{family} TOTAL", "Quantity": group["Quantity"].sum()}]))
        by_color = pd.concat(blocks, ignore_index=True)
        grid.filterable_table(by_color)

    st.subheader("Stock by Base Product")
    st.caption("Color variants rolled up into one product — e.g. Ace Black TT + Ace Grey + Ace Cracked all count as \"Ace\".")

    with st.container(border=True):
        by_base = filtered.copy()
        by_base["Product"] = by_base["Product"].map(colors.strip_color)
        by_base = by_base.groupby(["Location", "Product"], as_index=False)["Quantity"].sum()
        grid.filterable_table(by_base)


# ---------------------------------------- Stock Prediction & Movement ---

STATUS_COLORS = {
    sp.OUT: theme.CATEGORICAL[7],       # red
    sp.BELOW: theme.CATEGORICAL[5],     # orange
    sp.OK: theme.CATEGORICAL[1],        # green
    sp.ABOVE: theme.CATEGORICAL[0],     # blue
    sp.SLOW: theme.CATEGORICAL[3],      # yellow
    sp.IDLE: theme.OTHER,
}
VIEW_BAG = "Bag (colours combined)"
VIEW_SKU = "SKU (bag + colour)"


def _load():
    position = db.run_query(queries.STOCK_POSITION)
    demand = db.run_query(queries.STOCK_DEMAND)
    targets = db.run_query(queries.STOCK_TARGETS)
    cal = sp.Calendar.for_today()
    shops = sorted(position.loc[position["Bucket"] == "Shop", "Location"].unique())
    demand = demand[demand["Location"].isin(shops)]
    return position, demand, sp.targets_by_shop(targets, cal), cal, shops


def _status_by_shop(df: pd.DataFrame, title: str) -> go.Figure:
    pivot = (df.pivot_table(index="Location", columns="Status", values="Bag",
                            aggfunc="count", fill_value=0)
               .reindex(columns=[s for s in sp.STATUS_ORDER if s != sp.IDLE], fill_value=0))
    pivot = pivot.loc[pivot.sum(axis=1).sort_values().index]
    fig = go.Figure()
    for status in pivot.columns:
        fig.add_bar(y=pivot.index, x=pivot[status], orientation="h", name=status,
                    marker=dict(color=STATUS_COLORS[status],
                                line=dict(color=theme.CHART_SURFACE, width=1)),
                    hovertemplate=f"<b>%{{y}}</b><br>{status}: <b>%{{x:,.0f}}</b><extra></extra>")
    theme.apply_layout(fig, show_legend=True)
    fig.update_layout(title=title, barmode="stack", hovermode="closest",
                      legend_traceorder="normal", height=max(380, 28 * len(pivot) + 100))
    return fig


@st.fragment()
def render_prediction() -> None:
    position, demand, targets, cal, shops = _load()
    if demand.empty:
        st.info("No bag sales in the last 90 days to plan from.")
        return

    view = _section(["🏆 Top Sellers", "📋 Stock Report", "📏 Min & Max Levels"], "plan_section")
    if view == "🏆 Top Sellers":
        _top_sellers(position, demand, shops)
        return

    c1, c2 = st.columns([2, 2])
    basis = c1.radio(
        "Plan demand on", [sp.TARGET_BASIS, sp.TREND_BASIS], horizontal=True, key="plan_basis",
        help="Targets: each shop's monthly bag target, split across its bags by their share of "
             "its last 90 days of sales. Sales trend: the 90-day moving average carried forward.")
    level = c2.radio("Show by", [VIEW_BAG, VIEW_SKU], horizontal=True, key="plan_view")
    base = sp.shop_sku(position, demand, shops)
    planned_sku = sp.plan(base, targets, cal, basis)

    if not targets["Next Target Set"].all():
        st.caption(f"Next month's bag targets ({cal.next_month:%B %Y}) are not set in Odoo yet, "
                   f"so {cal.month_start:%B}'s are used for next month until they are.")

    if view == "📋 Stock Report":
        _stock_report(planned_sku, position, cal, basis, level)
    else:
        _min_max(base, planned_sku, targets, cal, basis, level)


def _top_sellers(position: pd.DataFrame, demand: pd.DataFrame, shops: list[str]) -> None:
    c1, c2, c3 = st.columns(3)
    period = c1.selectbox("Period", ["Last 90 days", "Last 30 days", "Month to date"],
                          key="top_period")
    level = c2.selectbox("Show by", [VIEW_BAG, VIEW_SKU], key="top_level")
    shop = c3.selectbox("Location", ["All locations"] + shops, key="top_location")
    by = "Bag" if level == VIEW_BAG else "SKU"

    scope = demand if shop == "All locations" else demand[demand["Location"] == shop]
    ranked = sp.top_sellers(scope, period, by)
    if ranked.empty:
        st.info("No bags sold in this period.")
        return

    pos = position.assign(Bag=position["SKU"].map(sp.family))
    held = pos[pos["Bucket"].isin(sp.SHOP_BUCKETS)]
    if shop != "All locations":
        held = held[held["Location"] == shop]
    on_hand = held.groupby(by)["Qty"].sum()
    in_wh = pos[pos["Bucket"] == "Warehouse"].groupby(by)["Qty"].sum()
    rate = scope.assign(Bag=scope["SKU"].map(sp.family)).groupby(by)["Sold 90d"].sum() / sp.WINDOW_DAYS
    ranked["On Hand at Shops"] = ranked[by].map(on_hand).fillna(0).clip(lower=0)
    ranked["In Warehouse"] = ranked[by].map(in_wh).fillna(0).clip(lower=0)
    ranked["Daily Rate (90d)"] = ranked[by].map(rate).fillna(0).round(1)
    ranked["Days of Cover"] = (ranked["On Hand at Shops"]
                               / ranked["Daily Rate (90d)"].where(ranked["Daily Rate (90d)"] > 0)
                               ).round(0)

    n80 = int((ranked["Cumulative %"] < 80).sum()) + 1
    top = lambda n: ranked["Share %"].head(n).sum()
    _kpis([
        ("Bags Sold", f"{ranked['Bags Sold'].sum():,.0f}", period.lower()),
        ("Top 5 Share", f"{top(5):.1f}%", "of bags sold"),
        ("Top 10 Share", f"{top(10):.1f}%", "of bags sold"),
        ("Top 20 Share", f"{top(20):.1f}%", "of bags sold"),
        ("Make Up 80% of Sales", f"{min(n80, len(ranked)):,}",
         f"of {len(ranked):,} {'bags' if by == 'Bag' else 'SKUs'} sold"),
    ])

    head = ranked.head(25)
    with st.container(border=True):
        fig = go.Figure()
        fig.add_bar(x=head[by], y=head["Share %"], name="Share of bags sold",
                    marker=dict(color=theme.sequential_colors(len(head))[::-1], cornerradius=4),
                    customdata=head[["Bags Sold"]],
                    hovertemplate="<b>%{x}</b><br>%{y:.1f}% · %{customdata[0]:,.0f} bags"
                                  "<extra></extra>")
        fig.add_scatter(x=head[by], y=head["Cumulative %"], name="Running share", yaxis="y2",
                        mode="lines+markers", line=dict(color=theme.CATEGORICAL[5], width=2),
                        hovertemplate="Top %{x}: <b>%{y:.1f}%</b> of bags sold<extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title=f"Share of Bags Sold — Top 25, {period.lower()} · {shop}",
                          height=440, hovermode="closest",
                          yaxis=dict(title="Share %", ticksuffix="%"),
                          yaxis2=dict(overlaying="y", side="right", range=[0, 105],
                                      ticksuffix="%", showgrid=False))
        fig.update_xaxes(tickangle=-40)
        theme.show(fig)
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        data = charts.fold_other(ranked[by], ranked["Bags Sold"], max_named=10)
        charts.share_chart(data, title="Top 10 Against the Rest", key="top_share_kind",
                           unit="bags", default="Doughnut")
    with c2, st.container(border=True):
        cats = (scope.groupby("Category")[{"Last 90 days": "Sold 90d", "Last 30 days": "Sold 30d",
                                           "Month to date": "Sold MTD"}[period]].sum())
        data = charts.fold_other(cats.index.str.replace("Bags / ", ""), cats.values)
        charts.share_chart(data, title="Share by Category", key="top_cat_kind", unit="bags",
                           default="Bar")
    with st.container(border=True):
        st.caption("Every bag ranked by its share of bags sold, with the stock behind it. Days of "
                   "Cover is how long the shops' stock lasts at the 90-day average rate.")
        grid.filterable_table(ranked, pinned_columns=(by,), height=460)


def _stock_report(planned: pd.DataFrame, position: pd.DataFrame, cal: sp.Calendar,
                  basis: str, level: str) -> None:
    by = "Bag" if level == VIEW_BAG else "SKU"
    report = sp.network_report(planned, position, by=by)
    buckets = position.groupby("Bucket")["Qty"].sum()

    _kpis([
        ("At Shops", f"{max(buckets.get('Shop', 0), 0):,.0f}",
         f"+ {buckets.get('Transit', 0):,.0f} in transit"),
        ("Ready in Warehouses", f"{buckets.get('Warehouse', 0):,.0f}", "Validation + CBD"),
        ("In Production", f"{buckets.get('Production', 0):,.0f}", "cut, being made up"),
        ("Short Before Month End", f"{report['Short This Month'].sum():,.0f}",
         f"shop stock runs out before {cal.month_end:%d %b}"),
        (f"Needed for {cal.next_month:%B}", f"{report['Deficit Next Month'].sum():,.0f}",
         "to send to shops"),
        ("Still to Make", f"{report['To Make'].sum():,.0f}", "after warehouse and production"),
    ])
    st.caption(
        f"{cal.days_left} days left in {cal.month_start:%B}. Demand on the **{basis}** basis. "
        "**Need Rest of Month** is what the shops are expected to sell by month end; "
        "**Short This Month** is how far their stock falls short of it; **Need Next Month** and "
        "**Deficit Next Month** are next month's demand and what must reach the shops for it. "
        "That is met first from the warehouses (**From Warehouse**), then from bags being made "
        "up (**From Production**); the rest is **To Make**. Hilton, KTDA, Hazina, Starmall and "
        "the Website are restocked from the CBD and Validation warehouses daily, so their own "
        "shelves read low.")

    statuses = ["All"] + sorted(report["Status"].unique())
    c1, c2 = st.columns(2)
    status = c1.selectbox("Status", statuses, key="report_status")
    cat = c2.selectbox("Category", ["All categories"] + sorted(report["Category"].dropna().unique()),
                       key="report_category")
    shown = report if status == "All" else report[report["Status"] == status]
    shown = shown if cat == "All categories" else shown[shown["Category"] == cat]

    top = shown[(shown["Short This Month"] + shown["Deficit Next Month"]) > 0].nlargest(
        15, "Deficit Next Month").sort_values("Deficit Next Month")
    if not top.empty:
        with st.container(border=True):
            fig = go.Figure()
            for col, color in (("From Warehouse", theme.CATEGORICAL[1]),
                               ("From Production", theme.CATEGORICAL[3]),
                               ("To Make", theme.CATEGORICAL[7])):
                fig.add_bar(y=top[by], x=top[col], orientation="h", name=col,
                            marker=dict(color=color, line=dict(color=theme.CHART_SURFACE, width=1)),
                            hovertemplate=f"<b>%{{y}}</b><br>{col}: <b>%{{x:,.0f}}</b><extra></extra>")
            theme.apply_layout(fig, show_legend=True)
            fig.update_layout(title=f"Biggest Needs for {cal.next_month:%B} and How They Are Met",
                              barmode="stack", hovermode="closest", legend_traceorder="normal",
                              height=max(380, 28 * len(top) + 100))
            theme.show(fig)

    with st.container(border=True):
        st.caption("What we have, what we need and what is missing, network-wide.")
        cols = [by, "Category", "Status", "Sold 90d", "Daily Rate", "In Shops", "In Transit",
                "Shops Stocking", "Shops Out", "In Warehouse", "In Production",
                "Need Rest of Month", "Short This Month", "Need Next Month",
                "Deficit Next Month", "From Warehouse", "From Production", "To Make"]
        grid.filterable_table(shown[cols].sort_values(["To Make", "Deficit Next Month"],
                                                      ascending=False),
                              pinned_columns=(by,), height=480)

    st.subheader("Missing at Shops")
    planned_view = planned if by == "SKU" else sp.by_bag(planned).merge(
        planned.groupby(["Location", "Bag"], as_index=False)[
            ["Need Rest of Month", "Expected Month-End", "Need Next Month",
             "Deficit Next Month", "Short This Month"]].sum(), on=["Location", "Bag"])
    in_wh = position[position["Bucket"] == "Warehouse"].assign(
        Bag=lambda f: f["SKU"].map(sp.family)).groupby(by)["Qty"].sum()
    missing = planned_view[(planned_view["On Hand"] <= 0)
                           & (planned_view["Sold 90d"] >= sp.ACTIVE_MIN_SOLD)].copy()
    missing["In Warehouse"] = missing[by].map(in_wh).fillna(0).clip(lower=0)
    missing["Daily Rate"] = missing["Daily Rate"].round(2)
    st.caption(f"{len(missing):,} {'bags' if by == 'Bag' else 'SKUs'} that sell at a shop "
               f"({sp.ACTIVE_MIN_SOLD}+ in 90 days) with none there or on the way. In Warehouse "
               "shows whether it can be sent now.")
    with st.container(border=True):
        shop = st.selectbox("Location", ["All locations"] + sorted(missing["Location"].unique()),
                            key="missing_location")
        m = missing if shop == "All locations" else missing[missing["Location"] == shop]
        grid.filterable_table(
            m[["Location", by, "Category", "Sold 90d", "Daily Rate", "Last Sold", "In Warehouse",
               "Need Next Month"]].sort_values("Sold 90d", ascending=False),
            pinned_columns=("Location",), height=380)

    st.subheader(f"Deficits for {cal.next_month:%B} by Shop")
    with st.container(border=True):
        shop = st.selectbox("Location", ["All locations"] + sorted(planned_view["Location"].unique()),
                            key="deficit_location")
        d = planned_view[planned_view["Deficit Next Month"] > 0]
        d = d if shop == "All locations" else d[d["Location"] == shop]
        st.caption("What each shop must receive before next month starts: next month's need "
                   "less the stock it is expected to have left at month end.")
        grid.filterable_table(
            d[["Location", by, "Category", "On Hand", "Need Rest of Month", "Expected Month-End",
               "Need Next Month", "Deficit Next Month"]].sort_values(
                ["Location", "Deficit Next Month"], ascending=[True, False]),
            pinned_columns=("Location",), height=420)


def _min_max(base: pd.DataFrame, planned_sku: pd.DataFrame, targets: pd.DataFrame,
             cal: sp.Calendar, basis: str, level: str) -> None:
    st.subheader("Preparedness Against Targets")
    prep = sp.preparedness(planned_sku, targets, cal)
    total_left = prep["Target Left"].sum()
    total_next = prep["Target Next Month"].sum()
    _kpis([
        (f"Target Left in {cal.month_start:%B}", f"{total_left:,.0f}",
         f"{prep['Sold MTD'].sum():,.0f} sold of {prep['Target This Month'].sum():,.0f}"),
        ("Stock at Shops", f"{prep['On Hand'].sum():,.0f}", "on shelves and on the way"),
        ("Ready This Month", f"{prep['On Hand'].sum() / total_left * 100:.0f}%" if total_left else "—",
         "of the target still to sell"),
        (f"Ready for {cal.next_month:%B}",
         f"{prep['Expected Month-End'].sum() / total_next * 100:.0f}%" if total_next else "—",
         f"of {total_next:,.0f} bags, from stock left at month end"),
    ])
    with st.container(border=True):
        order = prep.sort_values("Ready This Month %")
        fig = go.Figure()
        fig.add_bar(y=order["Location"], x=order["Ready This Month %"], orientation="h",
                    name=f"{cal.month_start:%B}", marker=dict(color=theme.CATEGORICAL[0]),
                    hovertemplate="<b>%{y}</b><br>This month: %{x:.0f}%<extra></extra>")
        fig.add_bar(y=order["Location"], x=order["Ready Next Month %"], orientation="h",
                    name=f"{cal.next_month:%B}", marker=dict(color=theme.CATEGORICAL[2]),
                    hovertemplate="<b>%{y}</b><br>Next month: %{x:.0f}%<extra></extra>")
        fig.add_vline(x=100, line=dict(color=theme.TEXT_SECONDARY, dash="dash"))
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title="How Much of the Target the Stock Covers", barmode="group",
                          hovermode="closest", height=max(420, 36 * len(order) + 100))
        fig.update_xaxes(ticksuffix="%")
        theme.show(fig)
        st.caption(f"This month: stock on hand against the bags still to sell to hit the target. "
                   f"Next month: stock expected to be left at month end (demand on the {basis} "
                   "basis) against next month's target. 100% means fully stocked; restocking "
                   "between now and then adds to it.")
        grid.filterable_table(
            prep[["Location", "Target This Month", "Sold MTD", "Target Left", "On Hand",
                  "Ready This Month %", "Short This Month", "Expected Month-End",
                  "Target Next Month", "Ready Next Month %", "Deficit Next Month"]]
            .sort_values("Ready This Month %"),
            pinned_columns=("Location",), height=420)

    st.subheader("Minimum and Maximum Stock Levels")
    c1, c2, c3 = st.columns(3)
    min_days = c1.number_input("Minimum — days of cover", 1, 60, 7, key="min_days",
                               help="Enough to last until the next dispatch reaches the shop.")
    max_days = c2.number_input("Maximum — days of cover", 2, 120, 30, key="max_days",
                               help="The most worth holding before it is better sent elsewhere.")
    if max_days <= min_days:
        st.warning("The maximum must be more days than the minimum.")
        return
    shop = c3.selectbox("Location", ["All locations"] + sorted(base["Location"].unique()),
                        key="minmax_location")
    rows = base if level == VIEW_SKU else sp.by_bag(base)
    levels = sp.min_max(rows, int(min_days), int(max_days))
    scope = levels if shop == "All locations" else levels[levels["Location"] == shop]

    counts = scope["Status"].value_counts()
    _kpis([
        (sp.OUT, f"{counts.get(sp.OUT, 0):,}", "selling lines with none on hand"),
        (sp.BELOW, f"{counts.get(sp.BELOW, 0):,}", f"under {min_days} days of cover"),
        (sp.OK, f"{counts.get(sp.OK, 0):,}", f"{min_days}–{max_days} days"),
        (sp.ABOVE, f"{counts.get(sp.ABOVE, 0):,}", f"over {max_days} days"),
        ("To Restock", f"{scope['Restock Qty'].sum():,.0f}", "bags, up to the maximum"),
        ("Excess", f"{scope['Excess Qty'].sum():,.0f}", "bags above the maximum"),
    ])
    st.caption(
        f"Daily rate is the 90-day moving average (bags sold in 90 days ÷ 90); Rate 30d is the "
        f"last 30 days, and Trend % compares the two. Minimum = {min_days} days × daily rate, "
        f"maximum = {max_days} days × daily rate, checked against what the shop holds plus what "
        f"is on its way. A line needs {sp.ACTIVE_MIN_SOLD}+ sales in 90 days to be judged; fewer "
        "is a Slow Seller.")
    with st.container(border=True):
        theme.show(_status_by_shop(scope.assign(Bag=scope["SKU"]),
                                   f"Stock Levels by Shop — {'bags' if level == VIEW_BAG else 'SKUs'}"))
    with st.container(border=True):
        status = st.selectbox("Status", ["All"] + sp.STATUS_ORDER, key="minmax_status")
        t = scope if status == "All" else scope[scope["Status"] == status]
        name = "Bag" if level == VIEW_BAG else "SKU"
        t = t.assign(**{"Daily Rate": t["Daily Rate"].round(2), "Rate 30d": t["Rate 30d"].round(2)})
        grid.filterable_table(
            t[["Location", name, "Category", "Status", "Sold 90d", "Daily Rate", "Rate 30d",
               "Trend %", "Min Level", "Max Level", "In Shop", "In Transit", "On Hand",
               "Days of Cover", "Restock Qty", "Excess Qty"]]
            .sort_values(["Location", "Restock Qty"], ascending=[True, False]),
            pinned_columns=("Location", name), height=480)

    st.subheader("Moving Average for One Bag")
    bags = (base.groupby("Bag")["Sold 90d"].sum().sort_values(ascending=False))
    c1, c2 = st.columns(2)
    bag = c1.selectbox("Bag", bags.index.tolist(), key="ma_bag")
    where = c2.selectbox("Location", ["All locations"] + sorted(base["Location"].unique()),
                         key="ma_location")
    ids = base.loc[base["Bag"] == bag, "Product ID"].dropna().astype(int).unique().tolist()
    daily = db.run_query(queries.STOCK_DAILY_SALES,
                         {"product_ids": ids, "location": "" if where == "All locations" else where})
    if daily.empty:
        st.info("No sales of this bag in the last 180 days.")
        return
    days = pd.date_range(end=pd.Timestamp(cal.today), periods=180)
    series = (daily.assign(Date=pd.to_datetime(daily["Date"])).set_index("Date")["Sold"]
              .reindex(days, fill_value=0))
    ma90 = series.rolling(90, min_periods=30).mean()
    ma7 = series.rolling(7, min_periods=1).mean()
    rate = ma90.iloc[-1]
    with st.container(border=True):
        fig = go.Figure()
        fig.add_bar(x=series.index, y=series.values, name="Bags sold",
                    marker=dict(color=theme.GRIDLINE),
                    hovertemplate="%{x|%a %d %b}: %{y:,.0f}<extra></extra>")
        fig.add_scatter(x=ma7.index, y=ma7.values, name="7-day average",
                        line=dict(color=theme.CATEGORICAL[0], width=1.5),
                        hovertemplate="7-day: %{y:.1f}<extra></extra>")
        fig.add_scatter(x=ma90.index, y=ma90.values, name="90-day moving average",
                        line=dict(color=theme.CATEGORICAL[5], width=3),
                        hovertemplate="90-day: %{y:.2f} a day<extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title=f"{bag} — Bags Sold per Day · {where}", height=400,
                          hovermode="x unified")
        fig.update_xaxes(tickformat="%d %b")
        theme.show(fig)
        st.caption(f"At {rate:.2f} bags a day, {bag} needs a minimum of {rate * min_days:,.0f} "
                   f"and a maximum of {rate * max_days:,.0f} on hand ({where.lower()}).")


section = _section(["🏪 Shop Stocks", "🔮 Stock Prediction & Movement"], "stock_page_section")
if section == "🏪 Shop Stocks":
    render_shop_stock()
else:
    render_prediction()
