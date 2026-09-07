"""The three Dispatch Tracking views, split from their fetch step.

Each view is a fetch() + render() pair rather than one function, so the page can
claim its loading slot, do the querying behind the skeleton, and only then draw.
Keeping the bodies here (instead of in pages/) lets one page host all three
without importing page scripts, which execute their chrome on import.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import db, export, grid, queries, taxonomy, theme, transit

COMBINED = "Combined Distribution"
DISPATCH = "Dispatch"
# One view, because they are two halves of one question: what has not landed
# yet, and how quickly the things that did land took to arrive. Splitting them
# meant flipping tabs to answer either, and put the two different "in transit"
# figures on separate screens where they could not be told apart.
IN_TRANSIT = "In Transit & Received"
VIEWS = [COMBINED, DISPATCH, IN_TRANSIT]

# Retired tab names, kept so a stored selection from an older session resolves
# instead of leaving the segmented control with a value it does not offer.
_RETIRED_VIEWS = {"Goods in Transit": IN_TRANSIT, "Shops Receiving": IN_TRANSIT}


def resolve_view(stored: str | None) -> str:
    """The view to render, tolerating a name this build no longer has."""
    if stored in VIEWS:
        return stored
    return _RETIRED_VIEWS.get(stored, VIEWS[0])

# How quickly a dispatch landed. Ordered best-to-worst so a stacked bar reads
# left to right as it degrades. Deliberately NOT the status palette: arriving
# next day is normal for an up-country branch, not a fault, and red would say
# otherwise.
RECEIPT_ORDER = ["Same day", "Next day", "Two days", "Later", "In transit"]
RECEIPT_COLORS = {
    "Same day": theme.CATEGORICAL[0],    # blue
    "Next day": theme.CATEGORICAL[4],    # aqua
    "Two days": theme.CATEGORICAL[6],    # violet
    "Later": theme.CATEGORICAL[7],       # red — three days or more
    "In transit": theme.TEXT_MUTED,      # grey — nothing has happened yet
}

# Combined Distribution — received-basis columns.
SHOP_COLUMNS = [
    "MOMBASA", "NAKURU", "ELDORET", "KISUMU", "MERU", "THIKA",
    "KITENGELA", "WEBSITE", "NANYUKI", "KAKAMEGA", "JUMIA", "MRKT", "SINZA", "UGANDA",
    "KISII", "BUSIA", "RONGAI",
]
# On the hub-redistribution basis instead.
V2_COLUMNS = ["STARMALL", "HAZINA", "KTDA", "HILTON"]

DEST_COLUMNS = [
    "STARMALL", "MOMBASA", "NAKURU", "ELDORET", "KISUMU", "MERU", "THIKA", "HAZINA",
    "KITENGELA", "WEBSITE", "NANYUKI", "KAKAMEGA", "HILTON", "SINZA", "UGANDA",
    "KISII", "KTDA", "KTDA NEW", "BUSIA", "RONGAI",
]

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# CSS for the two hand-rolled HTML tables below (_new_products_section's LED
# strip and _leaderboard_html/_ledger_html's scoreboard/ledger). Injected once
# at the top of render() so it is present no matter which view draws first.
_LEDGER_CSS = """
<style>
.denri-led, .denri-lb { display: flex; flex-direction: column; font-size: 0.86rem; }
.denri-led-row, .denri-lb-row {
  display: grid; align-items: center; padding: 7px 10px; gap: 8px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.denri-led-row { grid-template-columns: 4px 1.6fr 1.4fr 0.8fr 0.5fr 1.4fr; }
.denri-lb-row { grid-template-columns: 28px 1.4fr repeat(6, 0.75fr) 1.3fr; }
.denri-led-head, .denri-lb-head {
  color: var(--denri-muted, #898781); font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.04em; text-transform: uppercase; border-bottom: 1px solid rgba(255,255,255,0.14);
}
.denri-led-body:hover, .denri-lb-body:hover { background: rgba(255,255,255,0.03); }
.denri-led-spine { width: 4px; height: 22px; border-radius: 2px; }
.denri-led-shop, .denri-lb-shop { font-weight: 600; color: #ffffff; }
.denri-led-days, .denri-led-turn { color: #c3c2b7; }
.denri-led-bags { text-align: right; font-variant-numeric: tabular-nums; }
.denri-led-none { color: var(--denri-muted, #898781); font-style: italic; }
.denri-led-out { color: #e66767; font-weight: 600; }
.denri-lb-num { text-align: right; font-variant-numeric: tabular-nums; color: #c3c2b7; }
.denri-lb-rank {
  display: flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 50%; background: rgba(255,255,255,0.08);
  font-weight: 700; font-size: 0.75rem;
}
.denri-lb-rank.top { background: rgba(25,195,154,0.18); color: #19c39a; }
.denri-lb-score { display: flex; align-items: center; gap: 8px; }
.denri-lb-track {
  flex: 1; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.08); overflow: hidden;
}
.denri-lb-bar { display: block; height: 100%; border-radius: 3px; }
.denri-lb-val { font-weight: 700; font-variant-numeric: tabular-nums; width: 34px; text-align: right; }
</style>
"""


def _sources_from(breakdown: pd.DataFrame) -> pd.DataFrame:
    """Destination x source totals — the old SOURCES query, done in pandas."""
    if breakdown.empty:
        return pd.DataFrame(columns=["Destination", "Source", "Qty"])
    out = breakdown.groupby(["Destination", "Source"], as_index=False)["Qty"].sum()
    return out[out["Qty"] != 0]


def _hub_detail_from(breakdown: pd.DataFrame) -> pd.DataFrame:
    """Hub give-outs at bag grain — the old HUB_DETAIL query, done in pandas.

    Mirrors that query's two filters exactly: Hilton's outflows are also written
    back against HILTON itself as negative rows (that is how the column nets),
    and those are the deduction rather than a give-out TO Hilton.
    """
    if breakdown.empty:
        return pd.DataFrame(columns=["Product", "Sent to", "Source", "Qty"])
    out = breakdown[breakdown["Source"].isin(["CBD", "HTN"])]
    out = out[~((out["Source"] == "HTN") & (out["Destination"] == "HILTON"))]
    out = out[out["Qty"] > 0]
    return out.rename(columns={"Destination": "Sent to"})[
        ["Product", "Sent to", "Source", "Qty"]
    ]


# ---------------------------------------------------------- Receiving FIFO ---
def _settle_receiving(dispatches: pd.DataFrame, receipts: pd.DataFrame) -> pd.DataFrame:
    """Match dispatch lines against receipt lines FIFO per shop and bag.

    Exact-quantity matching (a 50-bag dispatch only "clears" against a 50-bag
    receipt) left split deliveries outstanding forever, since a consignment
    routinely lands in more than one receipt of a different size — 2,575 bags
    wrongly held out over one fortnight. Settling by running quantity instead
    means a dispatch of 50 met by receipts of 30 then 20 is fully cleared, at
    the two receipt dates each covering their share, rather than showing as
    "not received" until a single 50-bag receipt happens to appear.

    Oldest dispatch is matched against oldest receipt first: a shop cannot
    receive a bag before it was sent, so consuming receipts in date order
    against the earliest unsettled dispatch is the only ordering that can't
    match a later dispatch ahead of an earlier one still waiting.
    """
    columns = ["Shop", "Product", "Qty", "Sent", "Received", "Days", "Status", "Outstanding"]
    if dispatches is None or dispatches.empty:
        return pd.DataFrame(columns=columns)

    receipts = receipts if receipts is not None else pd.DataFrame(columns=["Shop", "Product", "Date", "Qty"])
    rows: list[dict] = []

    for (shop, product), disp_group in dispatches.groupby(["Shop", "Product"], sort=False):
        recv_group = receipts[
            (receipts["Shop"] == shop) & (receipts["Product"] == product)
        ].sort_values("Date")
        queue = [[d, float(q)] for d, q in zip(recv_group["Date"], recv_group["Qty"])]
        qi = 0

        for _, disp_row in disp_group.sort_values("Date").iterrows():
            remaining = float(disp_row["Qty"])
            sent_date = disp_row["Date"]

            while remaining > 1e-9 and qi < len(queue):
                recv_date, recv_remaining = queue[qi]
                if recv_remaining <= 1e-9:
                    qi += 1
                    continue
                take = min(remaining, recv_remaining)
                days = max((recv_date - sent_date).days, 0)
                status = (
                    "Same day" if days == 0 else
                    "Next day" if days == 1 else
                    "Two days" if days == 2 else
                    "Later"
                )
                rows.append({
                    "Shop": shop, "Product": product, "Qty": take,
                    "Sent": sent_date, "Received": recv_date,
                    "Days": days, "Status": status, "Outstanding": 0.0,
                })
                remaining -= take
                queue[qi][1] -= take
                if queue[qi][1] <= 1e-9:
                    qi += 1

            if remaining > 1e-9:
                rows.append({
                    "Shop": shop, "Product": product, "Qty": remaining,
                    "Sent": sent_date, "Received": pd.NaT,
                    "Days": None, "Status": "In transit", "Outstanding": remaining,
                })

    return pd.DataFrame(rows, columns=columns)


def fetch(view: str, start_date: date, end_date: date) -> dict:
    """Everything the chosen view needs. Only the selected view is queried."""
    params = {"start_date": start_date, "end_date": end_date}

    if view == COMBINED:
        # One breakdown query at bag grain; the destination summary and the
        # hub-only view are aggregations of it, not extra round trips.
        breakdown = db.run_query(queries.COMBINED_DISTRIBUTION_BREAKDOWN, params)
        # The hub table gets its own query rather than reusing the breakdown:
        # the breakdown drops CBD's forwards to KTDA by design, which understated
        # what the hubs handed on. See HUB_OUTFLOW.
        hub_out = db.run_query(queries.HUB_OUTFLOW, params)
        return {
            "df": db.run_query(queries.COMBINED_DISTRIBUTION, params),
            "sources": _sources_from(breakdown),
            "hub_detail": (
                hub_out[hub_out["Sent to"].notna()]
                [["Product", "Sent to", "Source", "Qty"]]
                if hub_out is not None and not hub_out.empty
                else _hub_detail_from(breakdown)
            ),
        }

    if view == DISPATCH:
        include_cbd = st.session_state.get("dispatch_cbd_mode") != "Without CBD sends"
        df = db.run_query(queries.DISPATCH_COMBINED, {**params, "include_cbd": include_cbd})
        other = not include_cbd
        other_df = (
            db.run_query(queries.DISPATCH_COMBINED, {**params, "include_cbd": other})
            if st.session_state.get(f"dispatch_prepare_{other}", False)
            else None
        )
        return {"df": df, "include_cbd": include_cbd, "other": other, "other_df": other_df}

    # A balance, not a difference of two date-ranged reports — see transit.py.
    long = db.run_query(queries.TRANSIT_BALANCE)
    df = transit.balance(long)
    dispatches = db.run_query(queries.SHOPS_RECEIVING_DISPATCHES, params)
    receipts = db.run_query(queries.SHOPS_RECEIVING_RECEIPTS, params)
    return {
        "df": df,
        "channels": transit.export_channels_only(df),
        "unmapped": transit.unmapped_destinations(long),
        # The receiving half. The balance says what has not landed; this says
        # how quickly what did land took to arrive. It honours the date range,
        # which the balance deliberately does not.
        "receiving": _settle_receiving(dispatches, receipts),
    }


def render(view: str, data: dict, start_date: date, end_date: date) -> None:
    st.markdown(_LEDGER_CSS, unsafe_allow_html=True)
    if view == COMBINED:
        _combined(data["df"], data["sources"], data["hub_detail"], start_date, end_date)
    elif view == DISPATCH:
        _dispatch(data, start_date, end_date)
    else:
        _in_transit(data["df"], data["channels"], start_date, end_date,
                    data.get("unmapped", []), data.get("receiving"))
        receiving = data.get("receiving")
        if receiving is not None and not receiving.empty:
            st.divider()
            st.subheader("Shops Receiving — how quickly it landed")
            _receiving(receiving, with_metrics=False)


# Who sent the bags. Blue/aqua/violet — never the status greens and reds, which
# would read as good/bad rather than as three neutral senders.
SOURCE_COLORS = {
    "Direct": theme.CATEGORICAL[0],
    "CBD": theme.CATEGORICAL[4],
    "HTN": theme.CATEGORICAL[6],
}
SOURCE_ORDER = ["Direct", "CBD", "HTN"]


def _hub_outflow(sources):
    """What HTN and CBD each handed on, in the SRC format: "17 (CBD: 17)".

    One annotated column rather than three numeric ones — the total and its
    split read together, and a hub contributing nothing is simply absent from
    the brackets instead of printing a 0 that has to be scanned past.
    """
    if sources is None or sources.empty:
        return None
    # Accepts either shape: the hub-outflow frame ("Sent to") or the older
    # breakdown aggregation ("Destination").
    key = "Sent to" if "Sent to" in sources.columns else "Destination"
    out = sources[sources["Source"].isin(["CBD", "HTN"]) & (sources["Qty"] > 0)]
    if out.empty:
        return None

    pivot = (
        out.pivot_table(index=key, columns="Source", values="Qty",
                        aggfunc="sum", fill_value=0)
        .reindex(columns=["CBD", "HTN"], fill_value=0)
    )
    pivot["TOTAL"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("TOTAL", ascending=False)
    pivot.loc["ALL DESTINATIONS"] = pivot.sum()

    def annotate(row) -> str:
        parts = [f"{hub}: {int(row[hub]):,}" for hub in ("CBD", "HTN") if row[hub]]
        return f"{int(row['TOTAL']):,} ({', '.join(parts)})"

    return pd.DataFrame({
        "Sent to": pivot.index,
        "GAVE OUT SRC": [annotate(r) for _, r in pivot.iterrows()],
    })


def _by_source_chart(sources, totals) -> None:
    """Each shop's bar split by who sent the bags, segments summing to its total.

    A single bar per shop answers "how many", but not "from where" — and CBD and
    Hilton forwards are exactly the part people query. Stacking keeps the total
    readable as bar length while showing the split inside it.
    """
    wanted = [d for d in totals.index if totals[d] != 0]
    rows = sources[sources["Destination"].isin(wanted)] if not sources.empty else sources

    if rows.empty:
        st.info("No arrivals to break down for this range.")
        return

    pivot = (
        rows.pivot_table(index="Destination", columns="Source", values="Qty",
                         aggfunc="sum", fill_value=0)
        .reindex(columns=SOURCE_ORDER, fill_value=0)
    )
    pivot["TOTAL"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("TOTAL", ascending=True)

    # One card per destination, not per segment: hovering any part of KISII's
    # bar should say how KISII was supplied, not just that one slice is 26.
    grand = pivot["TOTAL"].sum()
    custom = [
        [
            r["TOTAL"],
            r["Direct"], (r["Direct"] / r["TOTAL"] * 100) if r["TOTAL"] else 0,
            r["CBD"], (r["CBD"] / r["TOTAL"] * 100) if r["TOTAL"] else 0,
            r["HTN"], (r["HTN"] / r["TOTAL"] * 100) if r["TOTAL"] else 0,
            (r["TOTAL"] / grand * 100) if grand else 0,
        ]
        for _, r in pivot.iterrows()
    ]
    hover = (
        "<b>%{y}</b><br>"
        "<span style='font-size:1.35em'><b>%{customdata[0]:,.0f}</b></span> bags received<br>"
        "<br>"
        "Direct&nbsp;&nbsp;%{customdata[1]:,.0f}  (%{customdata[2]:.0f}%)<br>"
        "CBD&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;%{customdata[3]:,.0f}  (%{customdata[4]:.0f}%)<br>"
        "HTN&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;%{customdata[5]:,.0f}  (%{customdata[6]:.0f}%)<br>"
        "<br>"
        "%{customdata[7]:.1f}% of everything received"
        "<extra></extra>"
    )

    fig = go.Figure()
    for source in SOURCE_ORDER:
        if pivot[source].eq(0).all():
            continue                     # a sender with nothing to show is noise
        fig.add_bar(
            y=pivot.index, x=pivot[source], orientation="h", name=source,
            marker=dict(color=SOURCE_COLORS[source]),
            customdata=custom,
            hovertemplate=hover,
        )
    fig.update_layout(barmode="stack")
    theme.apply_layout(fig, show_legend=True)

    # The stack shows the split; the total still has to be legible as one number.
    for dest, total in pivot["TOTAL"].items():
        fig.add_annotation(
            x=total, y=dest, text=f"<b>{total:,.0f}</b>", showarrow=False,
            xanchor="left", xshift=8, font=dict(color=theme.TEXT_PRIMARY, size=11),
        )

    # No Plotly title: it renders inside the plot area and collides with the
    # centred legend. Headings are st.subheader above the container instead.
    fig.update_layout(height=max(360, 26 * len(pivot)))
    st.plotly_chart(fig, width="stretch")

    with st.expander("Exact tally by sender"):
        table = pivot.reset_index().rename(columns={"Destination": "Shop / Channel"})
        st.dataframe(table, width="stretch", hide_index=True)


# ---------------------------------------------------------------- Combined ---
def _hub_detail_table(hub_detail):
    """Which bags made up each hub give-out — the rows behind "13 to CORPORATE".

    CBD/HTN/TOTAL are computed for ordering but not shown: the annotated
    GAVE OUT SRC column already carries the split, and repeating it as three
    numeric columns just made the table wider than the screen.
    """
    if hub_detail is None or hub_detail.empty:
        return None

    pivot = (
        hub_detail.pivot_table(index=["Sent to", "Product"], columns="Source",
                               values="Qty", aggfunc="sum", fill_value=0)
        .reindex(columns=["CBD", "HTN"], fill_value=0)
        .reset_index()
    )
    pivot["TOTAL"] = pivot["CBD"] + pivot["HTN"]
    pivot = pivot[pivot["TOTAL"] != 0]
    if pivot.empty:
        return None

    def annotate(row) -> str:
        parts = [f"{hub}: {int(row[hub]):,}" for hub in ("CBD", "HTN") if row[hub]]
        return f"{int(row['TOTAL']):,} ({', '.join(parts)})"

    pivot["GAVE OUT SRC"] = [annotate(r) for _, r in pivot.iterrows()]
    return pivot.sort_values(["Sent to", "TOTAL"], ascending=[True, False])[
        ["Sent to", "Product", "GAVE OUT SRC"]
    ]


def _new_products_section(rows, noun: str = "bags") -> None:
    """Products moving through Dispatch Tracking that the master list omits.

    One helper for all four menus so the answer cannot differ between them: a
    bag unknown to the master list is unknown whether you are looking at what was
    distributed, dispatched, outstanding or received.

    `rows` is a long frame of Product / Where / Qty. Callers normalise into that
    because the four views hold their data differently — three are
    product-by-destination matrices, the fourth is one row per movement.
    """
    st.subheader("New Products — not in the master bag list")

    if rows is None or rows.empty:
        st.success(
            "Nothing unrecognised here — every product matched a known bag name.",
            icon="✅",
        )
        return

    per_product = (
        rows.groupby("Product", as_index=False)
        .agg(Qty=("Qty", "sum"), Places=("Where", "nunique"))
        .sort_values("Qty", ascending=False)
    )
    where = (
        rows[rows["Qty"] != 0].sort_values("Qty", ascending=False)
        .groupby("Product")
        .apply(lambda g: ", ".join(
            f"{escape(str(w).title())} {q:,.0f}" for w, q in zip(g["Where"], g["Qty"])
        ), include_groups=False)
    )

    st.caption(
        f"{len(per_product):,} product(s) accounting for "
        f"{per_product['Qty'].sum():,.0f} {noun} without matching any name in the "
        "master list. Each is either a line to add or a spelling to fix in Odoo. "
        "Stripe: green is moving enough to be worth adding, amber is marginal, "
        "red is a handful."
    )

    head = (
        '<div class="denri-led-row denri-led-head">'
        "<span></span><span>Product</span><span>Where</span>"
        f'<span class="denri-led-bags">{noun.title()}</span>'
        "<span>Places</span><span></span>"
        "</div>"
    )
    body = []
    for _, r in per_product.iterrows():
        qty = float(r["Qty"])
        colour = (theme.STATUS["good"] if abs(qty) >= 20
                  else theme.STATUS["warning"] if abs(qty) >= 5
                  else theme.STATUS["critical"])
        cell = where.get(r["Product"]) or (
            '<span class="denri-led-none">nowhere recorded</span>')
        body.append(
            '<div class="denri-led-row denri-led-body">'
            f'<span class="denri-led-spine" style="background:{colour}"></span>'
            f'<span class="denri-led-shop">{escape(str(r["Product"]))}</span>'
            f'<span class="denri-led-days">{cell}</span>'
            f'<span class="denri-led-bags">{qty:,.0f}</span>'
            f'<span class="denri-led-turn">{int(r["Places"]):,}</span>'
            "<span></span></div>"
        )
    with st.container(border=True):
        st.markdown(f'<div class="denri-led">{head}{"".join(body)}</div>',
                    unsafe_allow_html=True)


def _unmapped_matrix(df, columns) -> pd.DataFrame:
    """Long Product/Where/Qty rows for the products a matrix view cannot place."""
    empty = pd.DataFrame(columns=["Product", "Where", "Qty"])
    if df is None or df.empty or "sort_order" not in df.columns:
        return empty
    detail = df[df["sort_order"] == 0]
    if detail.empty:
        return empty
    unknown = detail[detail["Product"].astype(str)
                     .map(taxonomy.family_of) == taxonomy.UNMAPPED]
    if unknown.empty:
        return empty
    cols = [c for c in columns if c in unknown.columns]
    out = unknown.melt(id_vars="Product", value_vars=cols,
                       var_name="Where", value_name="Qty")
    return out[out["Qty"].fillna(0) != 0]


def _combined(df, sources, hub_detail, start_date: date, end_date: date) -> None:
    detail_rows = df[df["sort_order"] == 0].copy() if not df.empty else df
    if df.empty or detail_rows.empty:
        st.info("No distribution activity for this date range yet.")
        return

    family_rows = df[df["sort_order"] == 1].copy()
    grand_total = df[df["sort_order"] == 2].iloc[0].fillna(0)

    shop_totals = grand_total[SHOP_COLUMNS].astype(float)
    top_destination = shop_totals.idxmax() if shop_totals.max() > 0 else "—"

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Total Distributed", f"{grand_total['TOTAL']:,.0f}")
    with k2.container(border=True):
        st.metric("To Shops & Channels", f"{shop_totals.sum():,.0f}")
    with k3.container(border=True):
        st.metric("Bag Styles", f"{len(detail_rows):,}")
    with k4.container(border=True):
        st.metric("Top Destination", top_destination)

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · "
        "Sundays and combo/bundle bags excluded; only bags with a non-zero value are listed."
    )

    st.download_button(
        "⬇️  Export to Excel",
        data=export.combined_distribution_xlsx(df),
        file_name=export.filename(start_date, end_date),
        mime=_XLSX,
        key="distribution_export",
    )

    with st.expander("How each column is counted — they are not on the same basis"):
        st.markdown(
            "**STARMALL, HAZINA, KTDA and HILTON** run on the hub-redistribution basis: "
            "arrivals are counted as the bag **leaves FINWH**, and CBD forwards are added to "
            "the receiving shop and deducted from KTDA, Hilton forwards deducted from HILTON.\n\n"
            "**Every other column** is on the received basis — counted only once the move into "
            "the shop's stock is done. The two groups are **not comparable**, and TOTAL mixes them.\n\n"
            "**SINZA / UGANDA** count on arrival into their own stock, like any other shop.\n\n"
            "**CORPORATE** and **DENRI SHOPS** are reference columns, not in TOTAL."
        )

    col_dest, col_family = st.columns(2)
    with col_dest:
        st.subheader("Bags Received by Shop & Channel")
        st.caption("Split by who sent them — Direct from the warehouse, or via a hub.")
        with st.container(border=True):
            # HTN and CBD sit alongside the shops here: they receive bags too,
            # and leaving them out made the chart look like the whole story
            # when two of the biggest destinations were missing from it.
            chart_cols = SHOP_COLUMNS + ["HILTON", "KTDA"]
            _by_source_chart(sources, grand_total[chart_cols].astype(float))

    with col_family:
        st.subheader("Top Product Families Distributed")
        st.caption("The fifteen largest families by total bags.")
        with st.container(border=True):
            top_families = family_rows.nlargest(15, "TOTAL").sort_values("TOTAL", ascending=True)
            st.plotly_chart(
                _family_bar(top_families["Product"], top_families["TOTAL"]),
                width="stretch",
            )

    st.subheader("Hubs — what HTN and CBD gave out")
    st.caption(
        "Bags each hub handed on to another location, by destination. "
        "DENRI SHOPS below is the same CBD figure as a single roll-up."
    )

    # Built from hub_detail, not sources: sources comes from the breakdown, which
    # excludes CBD's forwards to KTDA and so understated the hubs.
    hub_out = _hub_outflow(hub_detail)
    col_table, col_metric = st.columns([3, 1])
    with col_table:
        with st.container(border=True):
            if hub_out is None:
                st.info("Neither hub forwarded anything on in this range.")
            else:
                st.dataframe(hub_out, width="stretch", hide_index=True)
    with col_metric:
        with st.container(border=True):
            st.metric(
                "DENRI SHOPS", f"{float(grand_total['DENRI SHOPS']):,.0f}",
                help="Total CBD forwarded on to shops — reference, not in TOTAL. "
                     "Lower than the table's total because KTDA is counted in "
                     "its own column, not here.",
            )
        if hub_detail is not None and not hub_detail.empty:
            st.download_button(
                "⬇️  Export hubs",
                data=export.hub_outflow_xlsx(hub_detail),
                file_name=export.hub_outflow_filename(start_date, end_date),
                mime=_XLSX, key="hub_export", width="stretch",
            )

    hub_rows = _hub_detail_table(hub_detail)
    if hub_rows is not None:
        with st.container(border=True):
            st.caption(
                "Which bags made up each figure above — filter \"Sent to\" to a "
                "destination to see exactly what it was given."
            )
            grid.filterable_table(hub_rows, pinned_columns=("Sent to",), height=380)

    _new_products_section(
        _unmapped_matrix(df, [*DEST_COLUMNS, "JUMIA", "MRKT", "CORPORATE"]),
        noun="bags received",
    )


# ---------------------------------------------------------------- Dispatch ---
def _dispatch(data: dict, start_date: date, end_date: date) -> None:
    df, include_cbd = data["df"], data["include_cbd"]
    other, other_df = data["other"], data["other_df"]

    st.segmented_control(
        "CBD onward sends",
        ["With CBD sends", "Without CBD sends"],
        default="With CBD sends",
        key="dispatch_cbd_mode",
    )

    col_shown, col_other, _ = st.columns([1, 1, 2])
    with col_shown:
        if not df.empty:
            st.download_button(
                "⬇️  Export with CBD" if include_cbd else "⬇️  Export without CBD",
                data=export.dispatch_xlsx(df, with_cbd=include_cbd),
                file_name=export.dispatch_filename(start_date, end_date, with_cbd=include_cbd),
                mime=_XLSX, key=f"dispatch_export_{include_cbd}", width="stretch",
            )
    with col_other:
        other_label = "with CBD" if other else "without CBD"
        if other_df is not None and not other_df.empty:
            st.download_button(
                f"⬇️  Export {other_label}",
                data=export.dispatch_xlsx(other_df, with_cbd=other),
                file_name=export.dispatch_filename(start_date, end_date, with_cbd=other),
                mime=_XLSX, key=f"dispatch_export_{other}", width="stretch",
            )
        else:
            st.button(
                f"Prepare export {other_label}",
                key=f"dispatch_prepare_btn_{other}",
                on_click=lambda k=f"dispatch_prepare_{other}": st.session_state.__setitem__(k, True),
                width="stretch",
                help="Runs the other variant of the report, then offers it as a download.",
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

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · gross dispatch, nothing netted out. "
        "Sinza and Uganda are pooled from stock moves, transit dispatches and the "
        "Tanzania/Uganda sale orders, deduped on bag + destination + quantity."
    )

    st.subheader("Top Product Families Dispatched")
    st.caption("The fifteen largest families by total bags.")
    with st.container(border=True):
        top_families = family_rows.nlargest(15, "TOTAL").sort_values("TOTAL", ascending=True)
        st.plotly_chart(
            _family_bar(top_families["Family"], top_families["TOTAL"]),
            width="stretch",
        )

    fig = _destination_bar(dest_totals, noun="bags dispatched")
    if fig is not None:
        st.subheader("Bags Dispatched by Shop & Channel")
        st.caption("Total bags sent to each destination in this range.")
        with st.container(border=True):
            st.plotly_chart(fig, width="stretch")

    rows = _rows_by_destination(df, DEST_COLUMNS, "DISPATCHED")
    if rows is not None:
        st.subheader("Dispatched by Destination")
        st.caption(
            "Every bag dispatched, by where it went — filter \"Sent to\" to a "
            "destination to see exactly what it received."
        )
        with st.container(border=True):
            grid.filterable_table(rows, pinned_columns=("Sent to",), height=420)

    _new_products_section(_unmapped_matrix(df, DEST_COLUMNS),
                          noun="bags dispatched")


def _destination_bar(totals, row_height: int = 26, noun: str = "bags"):
    """Ranked horizontal bar of a destination total per row.

    Single series, so no legend — theme.apply_layout prints the value at the
    end of each bar, which is the number people are actually after. One colour
    throughout: a sequential ramp would imply the shade carried meaning beyond
    the bar length, and it breaks down entirely once values go negative.
    """
    ranked = totals[totals != 0].sort_values(ascending=True)
    if ranked.empty:
        return None

    grand = ranked.abs().sum()
    # share and rank alongside the figure — a bar's length says "big", the card
    # should say how big, out of what, and where it places
    order = ranked.rank(ascending=False, method="min")
    custom = [
        [abs(v) / grand * 100 if grand else 0, int(order[i]), len(ranked)]
        for i, v in ranked.items()
    ]

    fig = go.Figure()
    fig.add_bar(
        y=ranked.index, x=ranked.values, orientation="h",
        marker=dict(color=theme.CATEGORICAL[0]),
        customdata=custom,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "<span style='font-size:1.35em'><b>%{x:,.0f}</b></span> " + noun + "<br>"
            "<br>"
            "%{customdata[0]:.1f}% of the total<br>"
            "rank %{customdata[1]:.0f} of %{customdata[2]:.0f}"
            "<extra></extra>"
        ),
    )
    theme.apply_layout(fig, show_legend=False)
    fig.update_layout(height=max(360, row_height * len(ranked)))
    return fig


def _family_bar(labels, values, noun: str = "bags"):
    """Top-N product families, with share and rank in the card."""
    grand = values.abs().sum()
    n = len(values)
    custom = [
        [abs(v) / grand * 100 if grand else 0, n - i, n]
        for i, v in enumerate(values)
    ]
    fig = go.Figure()
    fig.add_bar(
        y=labels, x=values, orientation="h",
        marker=dict(color=theme.CATEGORICAL[0]),
        customdata=custom,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "<span style='font-size:1.35em'><b>%{x:,.0f}</b></span> " + noun + "<br>"
            "<br>"
            "%{customdata[0]:.1f}% of the shown families<br>"
            "rank %{customdata[1]:.0f} of %{customdata[2]:.0f}"
            "<extra></extra>"
        ),
    )
    theme.apply_layout(fig, show_legend=False)
    fig.update_layout(height=max(360, 28 * n))
    return fig


def _rows_by_destination(df, columns: list[str], value_label: str):
    """One row per bag per destination, from the wide Product x destination grid.

    The wide grid is mostly zeros — every bag carries a column for every
    destination it never went to. Melting to long form keeps only the cells
    that actually say something, which is what makes it filterable down to a
    single destination.

    Every non-zero cell is kept, negatives included, so the rows still add up
    to each destination's figure. Dropping them would make the parts stop
    summing to the whole.
    """
    detail = df[df["sort_order"] == 0] if not df.empty else df
    if detail.empty:
        return None

    cols = [c for c in columns if c in detail.columns]
    long = detail.melt(
        id_vars=["Product"], value_vars=cols,
        var_name="Sent to", value_name="Qty",
    )
    long = long[long["Qty"] != 0]
    if long.empty:
        return None

    long[value_label] = long["Qty"].astype(int).map("{:,}".format)
    return (
        long.sort_values(["Sent to", "Qty"], ascending=[True, False])
        [["Sent to", "Product", value_label]]
        .reset_index(drop=True)
    )


# ------------------------------------------------------------- Receiving ----
# How each outcome is credited when scoring a shop's receiving. Same-day is the
# target, next-day is fine for an up-country branch, two days is slow, three or
# more is poor, and stock that never arrived earns nothing.
RECEIPT_WEIGHTS = {
    "Same day": 1.0,
    "Next day": 0.6,
    "Two days": 0.35,
    "Later": 0.15,
    "In transit": 0.0,
}


def _receiving_score(g: pd.DataFrame) -> float:
    """0-100 for one shop, weighted by bags rather than by lines.

    Weighting by bags, not by dispatch lines, so one 300-bag consignment
    arriving late counts for more than a single stray bag — a line-count score
    would rank a shop on paperwork volume instead of stock.
    """
    bags = g["Qty"].sum()
    if not bags:
        return 0.0
    credit = sum(
        g.loc[g["Status"] == status, "Qty"].sum() * weight
        for status, weight in RECEIPT_WEIGHTS.items()
    )
    return round(credit / bags * 100, 1)


def _score_colour(score: float) -> str:
    """Green / amber / red band. Status colours are right here: this IS a state
    judgement, which is exactly what they are reserved for."""
    if score >= 70:
        return theme.STATUS["good"]
    if score >= 40:
        return theme.STATUS["warning"]
    return theme.STATUS["critical"]


def _leaderboard_html(df: pd.DataFrame) -> str:
    """Shops ranked by receiving score, as a table with a colour-rated bar."""
    if df.empty:
        return ""

    rows = []
    for shop, g in df.groupby("Shop"):
        bags = g["Qty"].sum()
        landed = g[g["Status"] != "In transit"]
        rows.append({
            "shop": shop,
            "sent": bags,
            "same": g.loc[g["Status"] == "Same day", "Qty"].sum() / bags * 100,
            "next": g.loc[g["Status"] == "Next day", "Qty"].sum() / bags * 100,
            "two": g.loc[g["Status"] == "Two days", "Qty"].sum() / bags * 100,
            "later": g.loc[g["Status"] == "Later", "Qty"].sum() / bags * 100,
            "out": g.loc[g["Status"] == "In transit", "Qty"].sum(),
            "median": landed["Days"].median() if not landed.empty else None,
            "score": _receiving_score(g),
        })

    board = sorted(rows, key=lambda r: (-r["score"], -r["sent"]))

    head = (
        '<div class="denri-lb-row denri-lb-head">'
        "<span>#</span><span>Shop</span>"
        '<span class="denri-lb-num">Same day</span>'
        '<span class="denri-lb-num">Next day</span>'
        '<span class="denri-lb-num">Two days</span>'
        '<span class="denri-lb-num">3+ days</span>'
        '<span class="denri-lb-num">Bags</span>'
        '<span class="denri-lb-num">Median</span>'
        '<span class="denri-lb-num">Score</span>'
        "</div>"
    )

    body = []
    for i, r in enumerate(board, start=1):
        colour = _score_colour(r["score"])
        rank_cls = "denri-lb-rank top" if i <= 3 else "denri-lb-rank"
        median = "—" if r["median"] is None else f"{r['median']:,.0f}"
        shop = escape(str(r["shop"]))
        body.append(
            f'<div class="denri-lb-row denri-lb-body">'
            f'<span class="{rank_cls}">{i}</span>'
            f'<span class="denri-lb-shop">{shop}</span>'
            f'<span class="denri-lb-num">{r["same"]:.1f}%</span>'
            f'<span class="denri-lb-num">{r["next"]:.1f}%</span>'
            f'<span class="denri-lb-num">{r["two"]:.1f}%</span>'
            f'<span class="denri-lb-num">{r["later"]:.1f}%</span>'
            f'<span class="denri-lb-num">{r["sent"]:,.0f}</span>'
            f'<span class="denri-lb-num">{median}</span>'
            f'<span class="denri-lb-score">'
            f'<span class="denri-lb-track">'
            f'<span class="denri-lb-bar" style="width:{max(2, r["score"]):.0f}%;'
            f'background:{colour}"></span></span>'
            f'<span class="denri-lb-val" style="color:{colour}">{r["score"]:.1f}</span>'
            f"</span></div>"
        )

    return f'<div class="denri-lb">{head}{"".join(body)}</div>'


def _ledger_html(df: pd.DataFrame) -> str:
    """The sent/received ledger, rendered with the same colour rating.

    Built from _consignments so the figures cannot drift from the table version;
    this only adds the score stripe and colours the outstanding tail.
    """
    if df.empty:
        return ""

    cons = _consignments(df)
    bands = {shop: _score_colour(_receiving_score(g)) for shop, g in df.groupby("Shop")}

    head = (
        '<div class="denri-led-row denri-led-head">'
        "<span></span><span>Shop</span><span>Sent</span>"
        '<span class="denri-led-bags">Bags</span>'
        "<span>Days to receive</span><span>Received</span>"
        "</div>"
    )

    body = []
    for _, r in cons.iterrows():
        colour = bands.get(r["Shop"], theme.TEXT_MUTED)
        received = escape(str(r["Received"]))
        # colour only the outstanding tail, so the receipt days stay neutral
        if " — " in received:
            days, tail = received.split(" — ", 1)
            received = f'{days} <span class="denri-led-out">— {tail}</span>'
        elif received.startswith("not yet received"):
            received = f'<span class="denri-led-out">{received}</span>'
        body.append(
            '<div class="denri-led-row denri-led-body">'
            f'<span class="denri-led-spine" style="background:{colour}"></span>'
            f'<span class="denri-led-shop">{escape(str(r["Shop"]))}</span>'
            f'<span class="denri-led-days">{escape(str(r["Sent"]))}</span>'
            f'<span class="denri-led-bags">{r["Bags"]:,}</span>'
            f'<span class="denri-led-turn">{escape(str(r["Days"]))}</span>'
            f'<span class="denri-led-days">{received}</span>'
            "</div>"
        )

    return f'<div class="denri-led">{head}{"".join(body)}</div>'


def _consignments(df: pd.DataFrame) -> pd.DataFrame:
    """One row per shop for the whole range: what went out, and when it came in.

    A shop split across a row per send date made you read four lines to answer
    "how did KTDA do this week". Collapsed to one line per shop, with the send
    days and the receipt days each spelled out with their quantities, the whole
    week reads across a single row — and the two lists still reconcile against
    each other because both carry amounts.
    """
    if df.empty:
        return pd.DataFrame(columns=["Shop", "Sent", "Bags", "Days", "Received"])

    # "%-d" is POSIX, "%#d" is the Windows equivalent — both mean "day number,
    # no leading zero".
    day_fmt = "%a %#d" if os.name == "nt" else "%a %-d"

    def day_list(frame: pd.DataFrame, date_col: str) -> pd.Series:
        """"Thu 23: 100, Fri 24: 1" per shop, chronological."""
        per_day = (
            frame.groupby(["Shop", date_col], as_index=False)["Qty"].sum()
            .sort_values(["Shop", date_col])
        )
        per_day["label"] = (
            pd.to_datetime(per_day[date_col]).dt.strftime(day_fmt)
            + ": " + per_day["Qty"].astype(int).map("{:,}".format)
        )
        return per_day.groupby("Shop")["label"].apply(", ".join)

    out = df.groupby("Shop", as_index=False)["Qty"].sum().rename(columns={"Qty": "Bags"})
    out["Sent"] = out["Shop"].map(day_list(df, "Sent"))

    landed = df[df["Received"].notna()]
    received_txt = day_list(landed, "Received") if not landed.empty else pd.Series(dtype=str)
    out["received_txt"] = out["Shop"].map(received_txt)

    outstanding = df[df["Status"] == "In transit"].groupby("Shop")["Qty"].sum()
    out["out_qty"] = out["Shop"].map(outstanding).fillna(0).astype(int)

    def describe(row) -> str:
        """Receipt days, with anything still outstanding said in the same breath."""
        if pd.isna(row["received_txt"]):
            return f"not yet received — {row['out_qty']:,} still out"
        if row["out_qty"]:
            return f"{row['received_txt']} — {row['out_qty']:,} still out"
        return row["received_txt"]

    out["Received"] = out.apply(describe, axis=1)
    out["Bags"] = out["Bags"].astype(int)

    # How long the shop actually took, weighted by bags rather than by row: a
    # sixty-bag consignment sitting two days is not the same event as one bag
    # sitting two days, and an unweighted mean treats them alike.
    def turnaround(shop: str) -> str:
        rows = landed[landed["Shop"] == shop]
        if rows.empty:
            return "—"
        days = rows["Days"].astype(float)
        qty = rows["Qty"].astype(float)
        avg = (days * qty).sum() / qty.sum() if qty.sum() else days.mean()
        lo, hi = int(days.min()), int(days.max())
        # "same day" only when every bag really did land the same day. Saying it
        # whenever the average merely rounds to zero produced "same day (0–1)",
        # which contradicts itself — a shop that took a day on some of them has
        # not had a clean week, and the cell should not imply it did.
        if hi == 0:
            return "same day"
        label = "<0.1 days" if avg < 0.05 else f"{avg:.1f} days"
        # The spread is the interesting part when it is wide: "1.2 days" hides
        # a shop that takes nothing one day and four days the next.
        return label if lo == hi else f"{label} ({lo}–{hi})"

    out["Days"] = out["Shop"].map(turnaround)

    return (
        out.sort_values("Bags", ascending=False)
        [["Shop", "Sent", "Bags", "Days", "Received"]]
        .reset_index(drop=True)
    )


def _receiving_metrics(df, *, in_transit_label: str = "Still in Transit") -> None:
    """The four receiving KPIs. Shared, so the two pages carrying them cannot
    drift apart — the Goods in Transit view shows the same row as its own."""
    if df is None or df.empty:
        return

    total = df["Qty"].sum()
    same_day = df.loc[df["Status"] == "Same day", "Qty"].sum()
    # Outstanding is the unsettled remainder of each line, not the whole line —
    # a dispatch of 5 with 3 arrived leaves 2 out. Falls back to Qty so an older
    # cached frame without the column still renders.
    remainder = "Outstanding" if "Outstanding" in df.columns else "Qty"
    outstanding = df.loc[df["Status"] == "In transit", remainder].sum()

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Bags Sent", f"{total:,.0f}")
    with k2.container(border=True):
        st.metric(
            "Landed Same Day", f"{same_day:,.0f}",
            delta=f"{(same_day / total * 100) if total else 0:,.0f}% of what was sent",
            delta_color="off",
        )
    with k3.container(border=True):
        st.metric("Landed Next Day", f"{df.loc[df['Status'] == 'Next day', 'Qty'].sum():,.0f}")
    with k4.container(border=True):
        st.metric(
            in_transit_label, f"{outstanding:,.0f}",
            help="Bags dispatched inside the date range that have not landed. "
                 "Counts only this range, so it reads differently from the "
                 "In Transit Now balance, which counts everything still sitting "
                 "in a transit location however long ago it left.",
        )


def _receiving(df, *, with_metrics: bool = True) -> None:
    """How long each dispatch took to land, and what has not landed yet.

    with_metrics=False when the KPI row has already been drawn higher up the
    page, which is the case now that this shares a view with the transit
    balance — repeating the same four numbers a screen apart reads as two
    different measurements.
    """
    if df is None or df.empty:
        st.info("Nothing was dispatched to a shop in this date range.")
        return

    if with_metrics:
        _receiving_metrics(df)

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · the date range filters on "
        "when a bag was SENT, so anything dispatched inside it that has not arrived still "
        "shows here. Pick \"Last 7 Days\" for the weekly view."
    )

    by_shop = (
        df.assign(bags=df["Qty"])
        .pivot_table(index="Shop", columns="Status", values="bags", aggfunc="sum", fill_value=0)
        .reindex(columns=RECEIPT_ORDER, fill_value=0)
    )
    by_shop["TOTAL"] = by_shop.sum(axis=1)
    by_shop = by_shop[by_shop["TOTAL"] != 0].sort_values("TOTAL", ascending=True)

    if not by_shop.empty:
        st.subheader("How Quickly Each Shop Received")
        st.caption(
            "Of what was sent to each shop, how much landed same day, next day, or "
            "later. Hover a shop for its full record."
        )
        with st.container(border=True):
            # One card per shop rather than a figure per segment: hovering any
            # part of KTDA's bar should answer "how is KTDA doing", not just
            # "this segment is 579".
            scores = {shop: _receiving_score(g) for shop, g in df.groupby("Shop")}
            summary = []
            for shop in by_shop.index:
                total = by_shop.loc[shop, "TOTAL"]
                pct = (lambda v: (v / total * 100) if total else 0)
                summary.append([
                    total,
                    by_shop.loc[shop, "Same day"], pct(by_shop.loc[shop, "Same day"]),
                    by_shop.loc[shop, "Next day"], pct(by_shop.loc[shop, "Next day"]),
                    by_shop.loc[shop, "Two days"], pct(by_shop.loc[shop, "Two days"]),
                    by_shop.loc[shop, "Later"], pct(by_shop.loc[shop, "Later"]),
                    by_shop.loc[shop, "In transit"],
                    scores.get(shop, 0.0),
                ])

            hover = (
                "<b>%{y}</b><br>"
                "<span style='font-size:1.35em'><b>%{customdata[2]:.1f}%</b></span>"
                " landed same day<br>"
                "<br>"
                "Sent&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>%{customdata[0]:,.0f}</b> bags<br>"
                "Same day&nbsp;&nbsp;%{customdata[1]:,.0f}  (%{customdata[2]:.0f}%)<br>"
                "Next day&nbsp;&nbsp;%{customdata[3]:,.0f}  (%{customdata[4]:.0f}%)<br>"
                "Two days&nbsp;&nbsp;%{customdata[5]:,.0f}  (%{customdata[6]:.0f}%)<br>"
                "3+ days&nbsp;&nbsp;&nbsp;%{customdata[7]:,.0f}  (%{customdata[8]:.0f}%)<br>"
                "Still out&nbsp;%{customdata[9]:,.0f}<br>"
                "Score&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>%{customdata[10]:.1f}</b>"
                "<extra></extra>"
            )

            fig = go.Figure()
            for status in RECEIPT_ORDER:
                if by_shop[status].eq(0).all():
                    continue
                fig.add_bar(
                    y=by_shop.index, x=by_shop[status], orientation="h", name=status,
                    marker=dict(color=RECEIPT_COLORS[status]),
                    customdata=summary,
                    hovertemplate=hover,
                )
            fig.update_layout(barmode="stack")
            theme.apply_layout(fig, show_legend=True)
            for shop, total in by_shop["TOTAL"].items():
                fig.add_annotation(
                    x=total, y=shop, text=f"<b>{total:,.0f}</b>", showarrow=False,
                    xanchor="left", xshift=8,
                    font=dict(color=theme.TEXT_PRIMARY, size=11),
                )
            fig.update_layout(
                height=max(360, 26 * len(by_shop)),
                # "closest", not the theme's "x unified": unified would stack one
                # line per segment and lose the card.
                hovermode="closest",
                hoverlabel=dict(
                    bgcolor="#12181b",
                    bordercolor="rgba(255,255,255,0.14)",
                    font=dict(color=theme.TEXT_PRIMARY, size=12,
                              family=theme.FONT_FAMILY),
                    align="left",
                ),
            )
            st.plotly_chart(fig, width="stretch")

    st.subheader("Receiving Scoreboard")
    st.caption(
        "Ranked on how quickly each shop takes stock in. Score is bags weighted "
        "by outcome — same day counts full, next day 60%, later 25%, and anything "
        "still in transit nothing."
    )
    st.markdown(_leaderboard_html(df), unsafe_allow_html=True)

    st.subheader("What Was Sent, and When It Landed")
    st.caption(
        "One row per shop, biggest first. Both columns carry day and quantity, so "
        "\"Sent\" and \"Received\" read against each other; the stripe on the left "
        "is the shop's score band, and anything still outstanding is called out in red."
    )
    st.markdown(_ledger_html(df), unsafe_allow_html=True)

    # Already long: one row per movement, with the shop and the quantity.
    unknown = df[df["Product"].astype(str).map(taxonomy.family_of)
                 == taxonomy.UNMAPPED]
    _new_products_section(
        unknown.rename(columns={"Shop": "Where", "Qty": "Qty"})
        [["Product", "Where", "Qty"]] if not unknown.empty else None,
        noun="bags dispatched",
    )


# -------------------------------------------------------------- In transit ---
def _in_transit(df, channels, start_date: date, end_date: date,
                unmapped: list[str] | None = None, receiving=None) -> None:
    if df.empty:
        st.info("Nothing is standing in the transit locations right now.")
        return

    grand = df[df["sort_order"] == 2].iloc[0]
    detail_rows = df[df["sort_order"] == 0]
    totals = grand[transit.BALANCE_COLUMNS].astype(float)

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("In Transit Now", f"{float(grand['TOTAL']):,.0f}")
    with k2.container(border=True):
        st.metric("Sinza", f"{float(grand['SINZA']):,.0f}")
    with k3.container(border=True):
        st.metric("Uganda", f"{float(grand['UGANDA']):,.0f}")
    with k4.container(border=True):
        st.metric("Bag Styles Outstanding", f"{len(detail_rows):,}")

    _receiving_metrics(receiving)

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · the top row is the balance "
        "standing in the FINWH/Goods in Transit locations right now, straight from Odoo, and "
        "does not move with the date range above — what is in transit is a question about now. "
        "The receiving row underneath does follow the range."
    )
    if unmapped:
        st.warning(
            "New transit location(s) with no column here: "
            + ", ".join(unmapped)
            + ". Their stock is not in the totals above.",
            icon="⚠️",
        )

    col_all, col_channels, col_bags, _ = st.columns([1, 1, 1, 1])
    with col_all:
        st.download_button(
            "⬇️  Export in transit (all)",
            data=export.transit_xlsx(df, transit.BALANCE_COLUMNS, channels_only=False),
            file_name=export.transit_filename(start_date, end_date, channels_only=False),
            mime=_XLSX, key="transit_export_all", width="stretch",
        )
    with col_channels:
        if channels.empty:
            st.button("No Sinza/Uganda in transit", disabled=True, width="stretch")
        else:
            st.download_button(
                "⬇️  Export Sinza & Uganda",
                data=export.transit_xlsx(channels, transit.EXPORT_CHANNELS, channels_only=True),
                file_name=export.transit_filename(start_date, end_date, channels_only=True),
                mime=_XLSX, key="transit_export_channels", width="stretch",
            )
    with col_bags:
        # Same two channels, colour variants collapsed into one line per bag.
        bags = transit.roll_to_bags(channels, transit.EXPORT_CHANNELS)
        if bags.empty:
            st.button("No bags to roll up", disabled=True, width="stretch")
        else:
            st.download_button(
                "⬇️  Sinza & Uganda (bags only)",
                data=export.transit_xlsx(bags, transit.EXPORT_CHANNELS,
                                         channels_only=True, bags_only=True),
                file_name=export.transit_filename(
                    start_date, end_date, channels_only=True, bags_only=True),
                mime=_XLSX, key="transit_export_bags", width="stretch",
                help=f"{len(bags[bags['sort_order'] == 0]):,} bags instead of "
                     f"{len(channels[channels['sort_order'] == 0]):,} colour "
                     "lines — Ace Croc Brown, Ace Red and Ace Beige all roll "
                     "into one ACE row, so a shop can be told \"send back 40 "
                     "Ace\" without them having to add up three colours first.",
            )

    with st.expander("How this is worked out"):
        st.markdown(
            "**In Transit Now** is a live balance out of "
            "`FINWH/Goods in Transit/*`, straight from Odoo's own on-hand "
            "quantities — not a dispatched-minus-received calculation. A flow "
            "reading depends entirely on which window you pick and can even "
            "go negative once dispatches outside the window land inside it; "
            "a balance can't, because it is what is physically sitting there "
            "right now, independent of any date range.\n\n"
            "**Bags Sent / Landed Same Day / Landed Next Day / Still in "
            "Transit** underneath follows the date range instead, and settles "
            "each dispatch against receipts FIFO — oldest dispatch against "
            "oldest receipt — so a consignment that lands in two or three "
            "separate deliveries still counts as received rather than sitting "
            "\"outstanding\" until one delivery happens to match its full size."
        )

    fig = _destination_bar(totals, noun="bags outstanding")
    if fig is not None:
        st.subheader("Bags Still in Transit by Shop & Channel")
        st.caption(
            "What each destination is currently owed — the balance sitting in "
            "its transit location, waiting to be received."
        )
        with st.container(border=True):
            st.plotly_chart(fig, width="stretch")

    rows = _rows_by_destination(df, transit.BALANCE_COLUMNS, "OUTSTANDING")
    if rows is not None:
        st.subheader("Outstanding by Destination")
        st.caption(
            "Every bag still outstanding, by where it was sent — filter "
            "\"Sent to\" to a destination to see exactly what has not landed."
        )
        with st.container(border=True):
            grid.filterable_table(rows, pinned_columns=("Sent to",), height=420)

    _new_products_section(_unmapped_matrix(df, transit.BALANCE_COLUMNS),
                          noun="bags outstanding")
