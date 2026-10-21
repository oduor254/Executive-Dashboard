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

from lib import auth, charts, db, filters, grid, queries, theme

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
    df = db.run_query(queries.FOOTFALL_DAILY, {"start_date": start_date, "end_date": end_date})
    if df.empty:
        st.info("No footfall counted or sales made in this date range.")
        return
    df["Date"] = pd.to_datetime(df["Date"])
    # Shops enter the day's walk-ins at close of day, so today has no count
    # yet: it is left out rather than read as a day nobody counted.
    today = pd.Timestamp(date.today())
    open_today = bool((df["Date"] == today).any())
    df = df[df["Date"] < today]
    if df.empty:
        st.info("Today's footfall is entered by the shops at close of day — pick a range that "
                "includes earlier days.")
        return

    shops = sorted(df["Location"].unique())
    location = st.selectbox("Location", ["All Locations"] + shops, key="footfall_location")
    shown = df if location == "All Locations" else df[df["Location"] == location]

    # Conversion only over days that have a count: a day with sales but no
    # count would otherwise add buyers with no visitors behind them.
    counted = shown[shown["Visitors"].notna()]
    visitors = counted["Visitors"].sum()
    walkin = counted["Walk-in Orders"].sum()
    shop_days = len(shown)
    missing = shown[shown["Visitors"].isna() & (shown["Orders"] > 0)]
    days = counted["Date"].nunique()
    _kpis([
        ("Visitors", f"{visitors:,.0f}", f"{len(counted):,} shop-days counted"),
        ("Average per Shop-Day", f"{visitors / len(counted):,.1f}" if len(counted) else "—",
         f"over {days:,} days"),
        ("Walk-in Conversion", _pct(walkin, visitors),
         f"{walkin:,.0f} purchased walk-ins of {visitors:,.0f}"),
        ("Revenue per Visitor", f"KES {counted['Walk-in Revenue'].sum() / visitors:,.0f}"
         if visitors else "—", "walk-in revenue ÷ visitors"),
        ("Days Not Counted", f"{len(missing):,}", f"of {shop_days:,} shop-days with sales"),
    ])
    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · **Visitors** are the total "
        "walk-ins each shop enters in the Footfall module at the end of the day. **Walk-in "
        "conversion** is purchased walk-ins (walk-in orders at the till) ÷ those walk-ins, on "
        "days that have a count only; online orders and leads are not walk-ins here (leads "
        "are in the Leads module). **Days Not Counted** are shop-days with sales but no "
        "footfall entered. Revenue is counted as on the Sales page."
        + (" Today is left out: its footfall is entered at close of day." if open_today else ""))

    if counted.empty:
        st.info("No footfall was counted in this range for this choice.")
    else:
        by_shop = (counted.groupby("Location")
                   .agg(Visitors=("Visitors", "sum"), Walkin=("Walk-in Orders", "sum"),
                        Days=("Date", "nunique"))
                   .assign(Conversion=lambda f: (f["Walkin"] / f["Visitors"] * 100).round(1)))
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            ranked = by_shop.sort_values("Visitors")
            fig = go.Figure()
            fig.add_bar(y=ranked.index, x=ranked["Visitors"], orientation="h",
                        marker=dict(color=theme.sequential_colors(len(ranked)), cornerradius=4),
                        text=[f"{v:,.0f}" for v in ranked["Visitors"]], textposition="outside",
                        cliponaxis=False, textfont=dict(color=theme.TEXT_SECONDARY, size=11),
                        customdata=ranked[["Days"]],
                        hovertemplate="<b>%{y}</b><br>%{x:,.0f} visitors over %{customdata[0]} "
                                      "counted days<extra></extra>")
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="Visitors by Shop", hovermode="closest",
                              height=max(380, 28 * len(ranked) + 90))
            theme.show(fig)
        with c2, st.container(border=True):
            ranked = by_shop.sort_values("Conversion")
            fig = go.Figure()
            fig.add_bar(y=ranked.index, x=ranked["Conversion"], orientation="h",
                        marker=dict(color=theme.CATEGORICAL[1], cornerradius=4),
                        text=[f"{v:.0f}%" for v in ranked["Conversion"]], textposition="outside",
                        cliponaxis=False, textfont=dict(color=theme.TEXT_SECONDARY, size=11),
                        customdata=ranked[["Walkin", "Visitors"]],
                        hovertemplate="<b>%{y}</b><br>%{x:.1f}% · %{customdata[0]:,.0f} walk-in "
                                      "orders from %{customdata[1]:,.0f} visitors<extra></extra>")
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="Walk-in Conversion by Shop", hovermode="closest",
                              height=max(380, 28 * len(ranked) + 90))
            fig.update_xaxes(ticksuffix="%")
            theme.show(fig)

        daily = (counted.groupby("Date")
                 .agg(Visitors=("Visitors", "sum"), Walkin=("Walk-in Orders", "sum"))
                 .sort_index())
        with st.container(border=True):
            fig = go.Figure()
            fig.add_bar(x=daily.index, y=daily["Visitors"], name="Visitors",
                        marker=dict(color=theme.CATEGORICAL[0], cornerradius=3),
                        hovertemplate="%{x|%a %d %b}: <b>%{y:,.0f}</b> visitors<extra></extra>")
            fig.add_scatter(x=daily.index, y=(daily["Walkin"] / daily["Visitors"] * 100).round(1),
                            name="Walk-in conversion", yaxis="y2", mode="lines+markers",
                            line=dict(color=theme.CATEGORICAL[5], width=2),
                            hovertemplate="%{x|%a %d %b}: <b>%{y:.1f}%</b> converted<extra></extra>")
            theme.apply_layout(fig, show_legend=True)
            fig.update_layout(title=f"Visitors and Conversion by Day — {location}", height=380,
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
                        hovertemplate="%{x}: <b>%{y:,.1f}</b> visitors a shop on average"
                                      "<extra></extra>")
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="Average Visitors per Shop by Day of Week", height=360)
            theme.show(fig)
        with c2, st.container(border=True):
            share = counted.groupby("Location")["Visitors"].sum()
            charts.share_chart(charts.fold_other(share.index, share.values),
                               title="Share of Visitors", key="footfall_share_kind",
                               unit="visitors", default="Doughnut")

    with st.container(border=True):
        st.caption("Each shop over the range, highest footfall first, with the total at the "
                   "bottom. Conversion and revenue per visitor use counted days only.")
        g = shown.groupby("Location")
        c = counted.groupby("Location")
        table = pd.DataFrame({
            "Visitors": c["Visitors"].sum(),
            "Days Counted": c["Date"].nunique(),
            "Days With Sales": g.apply(lambda f: int((f["Orders"] > 0).sum()), include_groups=False),
            "Walk-in Orders (Counted Days)": c["Walk-in Orders"].sum(),
            "All Orders": g["Orders"].sum(),
            "Revenue": g["Revenue"].sum(),
            "Walk-in Revenue (Counted Days)": c["Walk-in Revenue"].sum(),
        }).fillna({"Visitors": 0, "Days Counted": 0, "Walk-in Orders (Counted Days)": 0,
                   "Walk-in Revenue (Counted Days)": 0})
        table["Avg Visitors per Day"] = (table["Visitors"] / table["Days Counted"]
                                         .where(table["Days Counted"] > 0)).round(1)
        table["Walk-in Conversion %"] = (table["Walk-in Orders (Counted Days)"]
                                         / table["Visitors"].where(table["Visitors"] > 0)
                                         * 100).round(1)
        table["Revenue per Visitor"] = (table["Walk-in Revenue (Counted Days)"]
                                        / table["Visitors"].where(table["Visitors"] > 0)).round(0)
        table["Days Not Counted"] = (table["Days With Sales"] - table["Days Counted"]).clip(lower=0)
        table = table.reset_index().rename(columns={"index": "Location"})
        grid.filterable_table(table.sort_values("Visitors", ascending=False),
                              currency_columns=("Revenue", "Walk-in Revenue (Counted Days)",
                                                "Revenue per Visitor"),
                              pinned_columns=("Location",), height=460)

    with st.container(border=True):
        st.caption("Every shop-day: the count entered and the sales that day. **Check** flags "
                   "days with more walk-in orders than visitors counted (an undercount) and "
                   "days with sales but no count.")
        detail = shown.copy()
        detail["Conversion %"] = (detail["Walk-in Orders"] / detail["Visitors"]
                                  .where(detail["Visitors"] > 0) * 100).round(1)
        detail["Check"] = np.select(
            [detail["Visitors"].isna() & (detail["Orders"] > 0),
             detail["Walk-in Orders"] > detail["Visitors"]],
            ["Not counted", "More buyers than visitors"], "")
        detail["Date"] = detail["Date"].dt.date
        grid.filterable_table(
            detail[["Date", "Location", "Visitors", "Counted By", "Entered", "Walk-in Orders",
                    "Orders", "Conversion %", "Revenue", "Check"]],
            currency_columns=("Revenue",), pinned_columns=("Location",), height=460)


render_footfall(start_date, end_date)
