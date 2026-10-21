"""Footfall Traffic — visitors counted at each shop (Footfall module), and how
many of them bought."""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, charts, db, filters, footfall, grid, queries, theme

st.set_page_config(page_title="Footfall Traffic · Denri Executive Dashboard",
                   page_icon="🚶", layout="wide")

auth.require_login()

st.title("🚶 Footfall Traffic")
st.caption("Visitors counted at each shop in Odoo's Footfall module, against the sales made "
           "the same day — live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_refresh = st.columns([3, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("footfall", default="Month to Date")
with col_refresh:
    db.refresh_button(key="footfall_refresh")

WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def _kpis(items: list[tuple[str, str, str | None]]) -> None:
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")


def _pct(part: float, whole: float) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "—"


@st.fragment()
def render_footfall(start_date: date, end_date: date) -> None:
    # Counts, sheet gap-filling and the zero/today rules live in lib.footfall,
    # shared with the Reports page.
    df, filled_from_sheet, open_today = footfall.daily(start_date, end_date)
    if df.empty:
        st.info("No footfall counted or sales made in this date range — today's footfall is "
                "entered by the shops at close of day.")
        return

    shops = sorted(df["Location"].unique())
    location = st.selectbox("Location", ["All Locations"] + shops, key="footfall_location")
    shown = df if location == "All Locations" else df[df["Location"] == location]

    # The walk-in funnel uses counted days only: a day with walk-in sales but
    # no count would add buyers with nobody counted behind them.
    counted = shown[shown["Visitors"].notna()]
    walkins = counted["Visitors"].sum()
    bought = counted["Walk-in Orders"].sum()
    didnt = counted["Didn't Buy"].sum()
    missing = shown[shown["Visitors"].isna()]
    under = counted[counted["Walk-in Orders"] > counted["Visitors"]]

    st.markdown("**Walk-ins** — the people who came into the shops")
    _kpis([
        ("Walk-ins Counted", f"{walkins:,.0f}", f"{len(counted):,} shop-days counted"),
        ("Purchased Walk-ins", f"{bought:,.0f}", "walk-in orders on the POS"),
        ("Didn't Buy", f"{didnt:,.0f}", "counted, no purchase"),
        ("Walk-in Conversion", _pct(bought, walkins), "purchased ÷ counted"),
        ("Revenue per Walk-in", f"KES {counted['Walk-in Revenue'].sum() / walkins:,.0f}"
         if walkins else "—", "walk-in revenue ÷ counted"),
    ])
    st.markdown("**Not walk-ins** — orders that are not part of the conversion")
    _kpis([
        ("Online Orders", f"{shown['Online Orders'].sum():,.0f}", "ordered online"),
        ("Activation & Employee", f"{shown['Other Orders'].sum():,.0f}", "other order types"),
        ("Refunds", f"{shown['Refunds'].sum():,.0f}", "refund orders, not purchases"),
        ("Days Not Counted", f"{len(missing):,}", "walk-ins bought, no count entered"),
        ("Undercounted Days", f"{len(under):,}", "more purchases than walk-ins counted"),
    ])
    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · **Walk-ins counted** is the "
        "total each shop enters in the Footfall module at the end of the day. **Purchased "
        "walk-ins** are the orders rung on the POS with customer type *Walk-in* — refunds, "
        "online, activation and employee orders are not. **Walk-in conversion** = purchased "
        "walk-ins ÷ walk-ins counted, on counted days only. Online orders are shown apart: "
        "they are not people through the door, so counting them as buyers (as the Footfall "
        "module's own Buyers column does) overstates conversion. Leads are in the Leads "
        "module and not counted here. A count of **0** stands only when no walk-in bought; "
        f"a missing count is taken from the Reporting sheet ({filled_from_sheet:,} shop-days "
        "here). Orders are dated in Kenya time, as on the POS dashboard."
        + (" Today is left out: its footfall is entered at close of day." if open_today else ""))

    if counted.empty:
        st.info("No footfall was counted in this range for this choice.")
    else:
        by_shop = (counted.groupby("Location")
                   .agg(Walkins=("Visitors", "sum"), Bought=("Walk-in Orders", "sum"),
                        Didnt=("Didn't Buy", "sum"), Days=("Date", "nunique"))
                   .assign(Conversion=lambda f: (f["Bought"] / f["Walkins"].where(f["Walkins"] > 0)
                                                 * 100).round(1)))
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            ranked = by_shop.sort_values("Walkins")
            fig = go.Figure()
            fig.add_bar(y=ranked.index, x=ranked["Bought"], orientation="h", name="Bought",
                        marker=dict(color=theme.CATEGORICAL[1],
                                    line=dict(color=theme.CHART_SURFACE, width=1)),
                        hovertemplate="<b>%{y}</b><br>Bought: %{x:,.0f}<extra></extra>")
            fig.add_bar(y=ranked.index, x=ranked["Didnt"], orientation="h", name="Didn't buy",
                        marker=dict(color=theme.OTHER, line=dict(color=theme.CHART_SURFACE, width=1)),
                        hovertemplate="<b>%{y}</b><br>Didn't buy: %{x:,.0f}<extra></extra>")
            for shop, total in ranked["Walkins"].items():
                fig.add_annotation(x=total, y=shop, text=f"<b>{total:,.0f}</b>", showarrow=False,
                                   xanchor="left", xshift=6,
                                   font=dict(color=theme.TEXT_PRIMARY, size=11))
            theme.apply_layout(fig, show_legend=True)
            fig.update_layout(title="Walk-ins by Shop — Bought and Didn't Buy", barmode="stack",
                              hovermode="closest", legend_traceorder="normal",
                              height=max(380, 28 * len(ranked) + 100))
            theme.show(fig)
        with c2, st.container(border=True):
            ranked = by_shop.dropna(subset=["Conversion"]).sort_values("Conversion")
            colors = [theme.STATUS["critical"] if v > 100 else theme.CATEGORICAL[1]
                      for v in ranked["Conversion"]]
            fig = go.Figure()
            fig.add_bar(y=ranked.index, x=ranked["Conversion"], orientation="h",
                        marker=dict(color=colors, cornerradius=4),
                        text=[f"{v:.0f}%" for v in ranked["Conversion"]], textposition="outside",
                        cliponaxis=False, textfont=dict(color=theme.TEXT_SECONDARY, size=11),
                        customdata=ranked[["Bought", "Walkins"]],
                        hovertemplate="<b>%{y}</b><br>%{x:.1f}% · %{customdata[0]:,.0f} purchased "
                                      "of %{customdata[1]:,.0f} walk-ins<extra></extra>")
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="Walk-in Conversion by Shop", hovermode="closest",
                              height=max(380, 28 * len(ranked) + 90))
            fig.update_xaxes(ticksuffix="%")
            theme.show(fig)
            st.caption("Red: more purchased walk-ins than walk-ins counted — the count is low.")

        daily = (counted.groupby("Date")
                 .agg(Walkins=("Visitors", "sum"), Bought=("Walk-in Orders", "sum"),
                      Didnt=("Didn't Buy", "sum"))
                 .sort_index())
        with st.container(border=True):
            fig = go.Figure()
            fig.add_bar(x=daily.index, y=daily["Bought"], name="Bought",
                        marker=dict(color=theme.CATEGORICAL[1]),
                        hovertemplate="%{x|%a %d %b}: <b>%{y:,.0f}</b> bought<extra></extra>")
            fig.add_bar(x=daily.index, y=daily["Didnt"], name="Didn't buy",
                        marker=dict(color=theme.OTHER),
                        hovertemplate="%{x|%a %d %b}: <b>%{y:,.0f}</b> didn't buy<extra></extra>")
            fig.add_scatter(x=daily.index,
                            y=(daily["Bought"] / daily["Walkins"].where(daily["Walkins"] > 0)
                               * 100).round(1),
                            name="Walk-in conversion", yaxis="y2", mode="lines+markers",
                            line=dict(color=theme.CATEGORICAL[5], width=2),
                            hovertemplate="%{x|%a %d %b}: <b>%{y:.1f}%</b> converted<extra></extra>")
            theme.apply_layout(fig, show_legend=True)
            fig.update_layout(title=f"Walk-ins and Conversion by Day — {location}", height=380,
                              barmode="stack",
                              yaxis2=dict(overlaying="y", side="right", ticksuffix="%",
                                          showgrid=False, rangemode="tozero"))
            fig.update_xaxes(tickformat="%d %b")
            theme.show(fig)

        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            week = (counted.assign(Weekday=counted["Date"].dt.day_name())
                    .groupby("Weekday")["Visitors"].mean().reindex(WEEKDAYS))
            fig = go.Figure()
            fig.add_bar(x=week.index, y=week.values,
                        marker=dict(color=theme.CATEGORICAL[2], cornerradius=4),
                        text=[f"{v:,.0f}" if pd.notna(v) else "" for v in week.values],
                        textposition="outside", cliponaxis=False,
                        hovertemplate="%{x}: <b>%{y:,.1f}</b> walk-ins a shop on average"
                                      "<extra></extra>")
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="Average Walk-ins per Shop by Day of Week", height=360)
            theme.show(fig)
        with c2, st.container(border=True):
            share = counted.groupby("Location")["Visitors"].sum()
            charts.share_chart(charts.fold_other(share.index, share.values),
                               title="Share of Walk-ins", key="footfall_share_kind",
                               unit="walk-ins", default="Doughnut")

    with st.container(border=True):
        st.caption("Each shop over the range, most walk-ins first, with the total at the bottom. "
                   "The walk-in columns use counted days only; online, other orders and refunds "
                   "cover every day in the range and are not part of the conversion.")
        g = shown.groupby("Location")
        c = counted.groupby("Location")
        table = pd.DataFrame({
            "Days Counted": c["Date"].nunique(),
            "Walk-ins Counted": c["Visitors"].sum(),
            "Purchased Walk-ins": c["Walk-in Orders"].sum(),
            "Didn't Buy": c["Didn't Buy"].sum(),
            "Walk-in Revenue": c["Walk-in Revenue"].sum(),
            "Online Orders": g["Online Orders"].sum(),
            "Other Orders": g["Other Orders"].sum(),
            "Refunds": g["Refunds"].sum(),
            "Revenue": g["Revenue"].sum(),
            "Days Not Counted": g["Visitors"].apply(lambda v: int(v.isna().sum())),
            "Undercounted Days": c.apply(lambda f: int((f["Walk-in Orders"] > f["Visitors"]).sum()),
                                         include_groups=False),
        }).fillna({"Days Counted": 0, "Walk-ins Counted": 0, "Purchased Walk-ins": 0,
                   "Didn't Buy": 0, "Walk-in Revenue": 0, "Undercounted Days": 0})
        table.insert(4, "Walk-in Conversion %",
                     (table["Purchased Walk-ins"] / table["Walk-ins Counted"]
                      .where(table["Walk-ins Counted"] > 0) * 100).round(1))
        table.insert(6, "Revenue per Walk-in",
                     (table["Walk-in Revenue"] / table["Walk-ins Counted"]
                      .where(table["Walk-ins Counted"] > 0)).round(0))
        table = table.reset_index().rename(columns={"index": "Location"})
        grid.filterable_table(table.sort_values("Walk-ins Counted", ascending=False),
                              currency_columns=("Walk-in Revenue", "Revenue per Walk-in",
                                                "Revenue"),
                              pinned_columns=("Location",), height=460)

    with st.container(border=True):
        st.caption("Every shop-day. **Check** flags days with more purchased walk-ins than "
                   "walk-ins counted (the count is low) and days with walk-in purchases but no "
                   "count.")
        detail = shown.copy()
        detail["Conversion %"] = (detail["Walk-in Orders"] / detail["Visitors"]
                                  .where(detail["Visitors"] > 0) * 100).round(1)
        detail["Check"] = np.select(
            [detail["Visitors"].isna(), detail["Walk-in Orders"] > detail["Visitors"]],
            ["Not counted", "Count low — more purchases than walk-ins"], "OK")
        detail["Date"] = detail["Date"].dt.date
        detail = detail.rename(columns={"Visitors": "Walk-ins Counted",
                                        "Walk-in Orders": "Purchased Walk-ins",
                                        "Orders": "All Orders"})
        grid.filterable_table(
            detail[["Date", "Location", "Walk-ins Counted", "Purchased Walk-ins", "Didn't Buy",
                    "Conversion %", "Online Orders", "Other Orders", "Refunds", "All Orders",
                    "Revenue", "Counted By", "Entered", "Check"]],
            currency_columns=("Revenue",), pinned_columns=("Location",), height=460)


render_footfall(start_date, end_date)
