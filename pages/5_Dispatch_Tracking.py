"""Dispatch — the stock monitor (min / max per shop, with alerts and stock
health) and shop requests (opening to closing stock, stock that arrived
outside the shops' requests, and how the requests were met). See
lib/dispatch.py for how each figure is worked out."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, dispatch, filters, grid, queries, theme
from lib import stock_planning as sp

st.set_page_config(page_title="Dispatch · Denri Executive Dashboard", page_icon="🚛", layout="wide")

auth.require_login()

st.title("🚛 Dispatch")
st.caption("Stock health per shop, and how stock moves from dispatch to the shops — live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

SECTIONS = ["📦 Stock Monitor", "🧾 Shop Requests"]
section = st.segmented_control("Section", SECTIONS, default=SECTIONS[0], key="dispatch_section",
                               label_visibility="collapsed") or SECTIONS[0]

STATUS_COLORS = {sp.OUT: theme.CATEGORICAL[7], sp.BELOW: theme.CATEGORICAL[5],
                 sp.OK: theme.CATEGORICAL[1], sp.ABOVE: theme.CATEGORICAL[0]}
VIEW_BAG, VIEW_SKU = "Bag (colours combined)", "SKU (bag + colour)"


def _kpis(items: list[tuple[str, str, str | None]]) -> None:
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")


# ------------------------------------------------------------ stock monitor ---

def render_stock_monitor() -> None:
    c1, c2, c3, c4 = st.columns([1, 1, 1.2, 1.4])
    min_days = c1.number_input("Minimum — days of cover", 1, 60, 7, key="dispatch_min_days",
                               help="Enough to last until the next dispatch reaches the shop.")
    max_days = c2.number_input("Maximum — days of cover", 2, 120, 30, key="dispatch_max_days",
                               help="The most worth holding before it is better sent elsewhere.")
    level = c3.radio("Look at", [VIEW_BAG, VIEW_SKU], key="dispatch_level", horizontal=False)
    if max_days <= min_days:
        st.warning("The maximum must be more days than the minimum.")
        return

    with st.spinner("Reading stock and 90 days of sales…"):
        with ThreadPoolExecutor(max_workers=2) as pool:
            pos_f = pool.submit(db.run_query, queries.STOCK_POSITION)
            dem_f = pool.submit(db.run_query, queries.STOCK_DEMAND)
            position, demand = pos_f.result(), dem_f.result()
    shops = sorted(position.loc[position["Bucket"] == "Shop", "Location"].unique())
    base = sp.shop_sku(position, demand[demand["Location"].isin(shops)], shops)
    rows = base if level == VIEW_SKU else sp.by_bag(base)
    levels = sp.min_max(rows, int(min_days), int(max_days))
    shop = c4.selectbox("Shop", ["All shops"] + shops, key="dispatch_monitor_shop")
    scope = levels if shop == "All shops" else levels[levels["Location"] == shop]
    health = dispatch.health(levels)

    judged = scope[scope["Status"].isin(dispatch.HEALTH_STATUSES)]
    counts = judged["Status"].value_counts()
    n = max(len(judged), 1)
    _kpis([
        ("Stock Health", f"{counts.get(sp.OK, 0) / n * 100:.0f}%",
         f"{counts.get(sp.OK, 0):,} of {len(judged):,} selling lines within range"),
        (sp.OUT, f"{counts.get(sp.OUT, 0):,}", f"{counts.get(sp.OUT, 0) / n * 100:.0f}% · none on hand"),
        (sp.BELOW, f"{counts.get(sp.BELOW, 0):,}", f"{counts.get(sp.BELOW, 0) / n * 100:.0f}% · under {min_days} days"),
        ("Over Max", f"{counts.get(sp.ABOVE, 0):,}", f"{counts.get(sp.ABOVE, 0) / n * 100:.0f}% · over {max_days} days"),
        ("To Restock", f"{scope['Restock Qty'].sum():,.0f}", "bags, up to the maximum"),
        ("Excess", f"{scope['Excess Qty'].sum():,.0f}", "bags above the maximum"),
    ])
    st.caption(
        f"Daily rate = the 90-day moving average (bags sold in 90 days ÷ 90). Minimum = {min_days} "
        f"days × daily rate, maximum = {max_days} days × daily rate, checked against what the shop "
        "holds plus what is on its way to it. **Stock health** is the share of a shop's selling "
        f"lines within range; a line needs {sp.ACTIVE_MIN_SOLD}+ sales in 90 days to be judged.")

    alerts = scope[scope["Status"].isin([sp.OUT, sp.BELOW])]
    if not alerts.empty:
        st.error(f"🔔 {len(alerts):,} selling lines are below minimum"
                 + ("" if shop != "All shops" else f" across {alerts['Location'].nunique()} shops")
                 + f" — {alerts['Restock Qty'].sum():,.0f} bags to restock up to the maximum.", icon="🚨")

    st.subheader("Stock Health by Shop")
    with st.container(border=True):
        h = health.sort_values("Stock Health %")
        fig = go.Figure()
        for status in dispatch.HEALTH_STATUSES:
            fig.add_bar(y=h["Shop"], x=h[f"{status} %"], orientation="h", name=status,
                        marker=dict(color=STATUS_COLORS[status], line=dict(color=theme.CHART_SURFACE, width=1)),
                        customdata=h[[status]],
                        hovertemplate=f"<b>%{{y}}</b><br>{status}: %{{x:.1f}}% (%{{customdata[0]:,}} lines)<extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title="Share of selling lines by status — healthiest at the top", barmode="stack",
                          hovermode="closest", legend_traceorder="normal", height=max(380, 28 * len(h) + 110))
        fig.update_xaxes(range=[0, 100], ticksuffix="%")
        theme.show(fig)
        grid.filterable_table(
            health[["Shop", "Stock Health %", "Lines Judged", sp.OUT, f"{sp.OUT} %", sp.BELOW, f"{sp.BELOW} %",
                    sp.OK, sp.ABOVE, f"{sp.ABOVE} %", "Restock Qty", "Excess Qty"]],
            pinned_columns=("Shop",), height=420)

    name = "Bag" if level == VIEW_BAG else "SKU"
    shown = lambda t: t.assign(**{"Daily Rate": t["Daily Rate"].round(2)})[
        ["Location", name, "Category", "Status", "Sold 90d", "Daily Rate", "Min Level", "Max Level",
         "In Shop", "In Transit", "On Hand", "Days of Cover", "Restock Qty", "Excess Qty"]]
    st.subheader("🔔 Below Minimum — Restock")
    with st.container(border=True):
        st.caption("Selling lines out of stock or under the minimum, the biggest restock first.")
        grid.filterable_table(shown(alerts).sort_values("Restock Qty", ascending=False),
                              pinned_columns=("Location", name), height=440)
    st.subheader("Over Maximum")
    with st.container(border=True):
        st.caption("Lines holding more than the maximum — candidates to move to a shop that is short.")
        over = scope[scope["Status"] == sp.ABOVE]
        grid.filterable_table(shown(over).sort_values("Excess Qty", ascending=False),
                              pinned_columns=("Location", name), height=380)
    with st.expander("Every line and its status"):
        status = st.selectbox("Status", ["All"] + sp.STATUS_ORDER, key="dispatch_status")
        t = scope if status == "All" else scope[scope["Status"] == status]
        grid.filterable_table(shown(t).sort_values(["Location", "Restock Qty"], ascending=[True, False]),
                              pinned_columns=("Location", name), height=440)


# ------------------------------------------------------------ shop requests ---

def _load_requests(start: date, end: date) -> dict:
    """Everything the Shop Requests section reads, fetched together."""
    period = {"start_date": start, "end_date": end}
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = {
            "shops": pool.submit(db.run_query, queries.DISPATCH_SHOPS),
            "opening": pool.submit(db.run_query, queries.SHOP_STOCK_AT, {"day": start - timedelta(days=1)}),
            "closing": pool.submit(db.run_query, queries.SHOP_STOCK_AT, {"day": end}),
            "transits": pool.submit(db.run_query, queries.DISPATCH_TRANSIT_LINES, period),
            "requests": pool.submit(db.run_query, queries.SHOP_REQUEST_LINES, period),
        }
        data = {k: f.result() for k, f in jobs.items()}
    opened, closed = data["opening"]["Taken"].max(), data["closing"]["Taken"].max()
    data["opened"], data["closed"] = opened, closed
    data["moves"] = (db.run_query(queries.SHOP_STOCK_MOVES, {"start_ts": opened, "end_ts": closed})
                     if pd.notna(opened) and pd.notna(closed) and closed > opened else pd.DataFrame(
                         columns=["Shop ID", "Product ID", "SKU", "Kind", "From", "To", "Qty", "Moves"]))
    return data


def _waterfall(row: pd.Series, title: str) -> go.Figure:
    steps = [("Opening", row["Opening"], "absolute"),
             ("Received from dispatch", row["Received from Dispatch"], "relative"),
             ("Received from CBD", row["Received from CBD"], "relative"),
             ("Transfers in (outside dispatch)", row["Transfers In (outside dispatch)"], "relative"),
             ("Customer returns", row["Customer Returns"], "relative"),
             ("Adjustments in", row["Adjustments In"], "relative"),
             ("Sold", -row["Sold"], "relative"),
             ("Adjustments out", -row["Adjustments Out"], "relative"),
             ("Transfers out", -row["Transfers Out"], "relative"),
             ("Expected closing", row["Expected Closing"], "total")]
    fig = go.Figure(go.Waterfall(
        x=[s[0] for s in steps], y=[s[1] for s in steps], measure=[s[2] for s in steps],
        text=[f"{s[1]:+,.0f}" if s[2] == "relative" else f"{s[1]:,.0f}" for s in steps],
        textposition="outside",
        increasing=dict(marker=dict(color=theme.CATEGORICAL[1])),
        decreasing=dict(marker=dict(color=theme.CATEGORICAL[7])),
        totals=dict(marker=dict(color=theme.CATEGORICAL[0])),
        connector=dict(line=dict(color=theme.GRIDLINE))))
    fig.add_scatter(x=["Expected closing"], y=[row["Closing"]], mode="markers", name="Closing (snapshot)",
                    marker=dict(color=theme.TEXT_PRIMARY, size=12, symbol="diamond"))
    theme.apply_layout(fig, show_legend=True)
    fig.update_layout(title=title, height=420)
    return fig


def _bags_dispatched(shops: pd.DataFrame, transits: pd.DataFrame, shop: str, pick) -> None:
    if transits.empty:
        st.info("Nothing was dispatched to the shops in this period.")
        return
    lines = pick(transits.assign(Shop=transits["Shop ID"].map(dispatch.shop_names(shops))))
    per_bag, matrix, per_sku = dispatch.dispatched_bags(shops, lines)
    if per_sku.empty:
        st.info(f"Nothing was dispatched to {shop} in this period.")
        return
    total = per_sku[["Dispatched", "Received", "In Transit"]].sum()
    top = per_bag.iloc[0]
    _kpis([
        ("Bags Dispatched", f"{total['Dispatched']:,.0f}",
         f"in {lines['Transit'].nunique():,} dispatches to {per_sku['Shop'].nunique():,} shops"),
        ("Received", f"{total['Received']:,.0f}",
         f"{total['Received'] / total['Dispatched'] * 100:.0f}% taken into the shops" if total["Dispatched"] else None),
        ("Still in Transit", f"{total['In Transit']:,.0f}", "bags on the road"),
        ("Bag Types", f"{len(per_bag):,}", f"{per_sku['SKU'].nunique():,} SKUs (bag + colour)"),
        ("Most Dispatched", str(top["Bag"]), f"{top['Dispatched']:,.0f} bags · {top['Share %']:.0f}%"),
    ])
    st.caption("Every bag that left dispatch for the shops in the period, by dispatch date — whoever "
               "raised it (the shop, CBD, corporate, marketing, a prepayment or a redistribution). "
               "Website and Ktda take their stock straight from CBD/Stock, so they only show here "
               "when something was dispatched to them.")

    with st.container(border=True):
        b = per_bag.head(20).iloc[::-1]
        fig = go.Figure()
        for col, colour in (("Received", theme.CATEGORICAL[1]), ("In Transit", theme.CATEGORICAL[3])):
            fig.add_bar(y=b["Bag"], x=b[col], orientation="h", name=col, marker=dict(color=colour),
                        hovertemplate=f"<b>%{{y}}</b><br>{col}: %{{x:,.0f}} bags<extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title=f"Bags dispatched{'' if shop == 'All shops' else ' to ' + shop}"
                                " — top 20, received vs still in transit",
                          barmode="stack", hovermode="closest", height=max(380, 26 * len(b) + 110))
        theme.show(fig)
        grid.filterable_table(per_bag, pinned_columns=("Bag",), height=380)

    if shop == "All shops":
        st.subheader("Bags by Shop")
        with st.container(border=True):
            st.caption("Bags dispatched to each shop, bag by bag — shops with the most on the left.")
            grid.filterable_table(matrix, pinned_columns=("Bag", "Total"), height=460)

    st.subheader("By Shop, Bag and Colour")
    with st.container(border=True):
        st.caption("Each SKU sent to each shop: how many went, how many arrived, what is still in transit, "
                   "who raised the dispatches and when the first and last left.")
        grid.filterable_table(per_sku, pinned_columns=("Shop", "Bag"), height=460)


def render_shop_requests() -> None:
    c1, c2, c3 = st.columns([3, 1.4, 1])
    with c1:
        start, end = filters.date_range_control("dispatch", default="Last Week")
    with c3:
        db.refresh_button(key="dispatch_refresh")
    with st.spinner("Reading the dispatch module and stock moves…"):
        data = _load_requests(start, end)
    shops = data["shops"]
    names = sorted(set(dispatch.shop_names(shops).values()))
    shop = c2.selectbox("Shop", ["All shops"] + names, key="dispatch_request_shop")
    pick = (lambda t, col="Shop": t) if shop == "All shops" else (lambda t, col="Shop": t[t[col] == shop])

    if pd.isna(data["opened"]):
        st.warning("No end-of-day stock snapshot exists before this period, so opening stock is unknown.")
        return
    opened, closed = pd.Timestamp(data["opened"]), pd.Timestamp(data["closed"])
    st.caption(f"Opening stock: end of {opened:%a %d %b %Y}; closing stock: end of {closed:%a %d %b %Y} "
               "(the nightly snapshots)" + (" — today's closes tonight, so the period runs to last night."
                                             if closed.date() < end else "."))

    views = ["📊 Stock Movement", "🚚 Bags Dispatched", "📬 Stock Outside Requests", "✅ Request Fulfilment"]
    view = st.segmented_control("View", views, default=views[0], key="dispatch_request_view",
                                label_visibility="collapsed") or views[0]

    if view == views[0]:
        per_shop, detail = dispatch.movement(shops, data["opening"], data["closing"], data["moves"],
                                             data["transits"])
        per_shop, detail = pick(per_shop), pick(detail)
        total = per_shop.sum(numeric_only=True)
        off = detail[detail["Mismatch"].abs() > 0.001]
        _kpis([
            ("Opening", f"{total['Opening']:,.0f}", "bags"),
            ("Dispatched", f"{total['Dispatched']:,.0f}", f"{total['Still in Transit']:,.0f} still in transit"),
            ("Received", f"{total['Received from Dispatch'] + total['Received from CBD']:,.0f}",
             f"{total['Received from CBD']:,.0f} from CBD · + {total['Transfers In (outside dispatch)']:,.0f} outside dispatch"),
            ("Sold", f"{total['Net Sold']:,.0f}", f"net of {total['Customer Returns']:,.0f} returns"),
            ("Closing", f"{total['Closing']:,.0f}", f"expected {total['Expected Closing']:,.0f}"),
            ("Mismatched Lines", f"{len(off):,}", f"{off['Mismatch'].abs().sum():,.0f} bags unexplained"),
        ])
        with st.container(border=True):
            theme.show(_waterfall(total, f"Opening to closing stock — {shop.lower() if shop == 'All shops' else shop}"))
            st.caption("Every bag move recorded in Odoo's inventory between the two snapshots. Where the "
                       "expected closing (opening + moves in − moves out) and the closing snapshot differ, "
                       "stock moved without a record — see the mismatches below.")
        with st.container(border=True):
            st.caption("Per shop, in bags. Dispatched counts what left for the shop in the period (by "
                       "dispatch date); Received from Dispatch is what was taken into the shop's stock. "
                       "Website and Ktda take their stock straight from CBD/Stock, shown as Received from CBD.")
            grid.filterable_table(per_shop, pinned_columns=("Shop",), height=460)
        st.subheader("Lines That Don't Tally")
        with st.container(border=True):
            if off.empty:
                st.success("Every bag line tallies: opening + moves = closing.")
            else:
                grid.filterable_table(off.sort_values("Mismatch", key=lambda v: v.abs(), ascending=False),
                                      pinned_columns=("Shop", "SKU"), height=420)
        with st.expander("Every shop and SKU"):
            grid.filterable_table(detail, pinned_columns=("Shop", "SKU"), height=460)

    elif view == views[1]:
        _bags_dispatched(shops, data["transits"], shop, pick)

    elif view == views[2]:
        sent, direct = dispatch.outside_requests(shops, data["transits"], data["moves"])
        sent, direct = pick(sent), pick(direct)
        _kpis([
            ("Dispatched Without a Shop Request", f"{sent['Bags'].sum() if not sent.empty else 0:,.0f}",
             f"bags in {len(sent):,} dispatches"),
            ("Arrived Outside Dispatch", f"{direct['Bags'].sum() if not direct.empty else 0:,.0f}",
             "bags moved straight into a shop's stock"),
        ])
        st.subheader("Dispatches Not Raised by the Shop")
        with st.container(border=True):
            st.caption("Dispatches to a shop that didn't come from its own stock order — raised by CBD, "
                       "corporate, marketing, a prepayment or a redistribution.")
            if sent.empty:
                st.info("None in this period.")
            else:
                by = sent.groupby(["Shop", "Raised As"], as_index=False).agg(
                    Dispatches=("Transit", "nunique"), Bags=("Bags", "sum"), Received=("Received", "sum"))
                grid.filterable_table(by.sort_values("Bags", ascending=False), pinned_columns=("Shop",),
                                      height=300)
                grid.filterable_table(sent, pinned_columns=("Shop",), height=380)
        st.subheader("Stock That Arrived Outside Dispatch")
        with st.container(border=True):
            st.caption("Bags moved into a shop's stock in Odoo's inventory without passing through its "
                       "goods-in-transit location — straight from CBD, the warehouse or another shop. "
                       "Website's and Ktda's stock from CBD/Stock is their normal supply and isn't listed.")
            if direct.empty:
                st.success("None in this period.")
            else:
                grid.filterable_table(direct, pinned_columns=("Shop",), height=380)

    else:
        per_shop, per_bag = dispatch.fulfilment(shops, data["requests"])
        if per_shop.empty:
            st.info("No shop requests in this period.")
            return
        per_shop, per_bag = pick(per_shop), pick(per_bag)
        t = per_shop.sum(numeric_only=True)
        fill = t["Dispatched"] / t["Requested"] * 100 if t["Requested"] else float("nan")
        got = t["Received"] / t["Requested"] * 100 if t["Requested"] else float("nan")
        _kpis([
            ("Fill Rate", f"{fill:.1f}%", f"{t['Dispatched']:,.0f} of {t['Requested']:,.0f} bags dispatched"),
            ("Received", f"{got:.1f}%", f"{t['Received']:,.0f} bags taken into the shops"),
            ("Closed Unfilled", f"{t['Closed Unfilled']:,.0f}", "bags asked for, never sent"),
            ("Still Open", f"{t['Open Bags']:,.0f}", "bags on requests not yet dispatched"),
            ("Cancelled", f"{t['Cancelled Bags']:,.0f}", "bags on cancelled requests"),
        ])
        st.caption("The shops' own stock orders in the dispatch module, by the day they were ordered. "
                   "**Fill rate** = bags dispatched ÷ bags requested, on requests that have been dispatched "
                   "or closed; requests still submitted or approved are counted as open, and cancelled "
                   "ones apart.")
        with st.container(border=True):
            s = per_shop.sort_values("Fill Rate %")
            fig = go.Figure()
            for col, colour in (("Requested", theme.OTHER), ("Dispatched", theme.CATEGORICAL[0]),
                                ("Received", theme.CATEGORICAL[1])):
                fig.add_bar(y=s["Shop"], x=s[col], orientation="h", name=col, marker=dict(color=colour),
                            hovertemplate=f"<b>%{{y}}</b><br>{col}: %{{x:,.0f}} bags<extra></extra>")
            theme.apply_layout(fig, show_legend=True)
            fig.update_layout(title="Bags requested, dispatched and received — lowest fill rate at the top",
                              barmode="group", hovermode="closest", height=max(400, 34 * len(s) + 110))
            theme.show(fig)
            grid.filterable_table(per_shop, pinned_columns=("Shop",), height=420)
        st.subheader("By Bag")
        with st.container(border=True):
            st.caption("What each shop asked for and got, bag by bag — the biggest shortfall first.")
            grid.filterable_table(per_bag, pinned_columns=("Shop", "Bag"), height=460)


if section == SECTIONS[0]:
    render_stock_monitor()
else:
    render_shop_requests()
