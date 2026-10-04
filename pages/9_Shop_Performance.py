"""Shop Performance — weekly, monthly and year-on-year performance for every
location, with an improvement plan generated from the numbers."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, grid, queries, theme
from lib import shop_performance as sp

st.set_page_config(page_title="Shop Performance · Denri Executive Dashboard",
                   page_icon="🏬", layout="wide")

auth.require_login()

st.title("🏬 Shop Performance")
st.caption("Weekly, monthly and year-on-year performance for every location, with an "
           "improvement plan built from the numbers — live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

TODAY = date.today()
ALL = "All Locations"
PRIORITY_ICONS = {"High": "🔴", "Medium": "🟠", "Low": "🟡", "Note": "ℹ️",
                  "Strength": "🟢", "On track": "🟢"}

col_view, col_loc, col_refresh = st.columns([2, 2, 1])
with col_view:
    view = st.radio("View", ["Weekly", "Monthly", "Year on Year"], horizontal=True,
                    key="shopperf_view")
with col_refresh:
    db.refresh_button(key="shopperf_refresh")
grain = "week" if view == "Weekly" else "month"


def _load(grain: str) -> pd.DataFrame:
    """Enough history for the trend and its same-period-last-year comparison."""
    if grain == "week":
        start = TODAY - timedelta(days=7 * 80)
        start -= timedelta(days=start.weekday())
    else:
        start = date(TODAY.year - 2, TODAY.month, 1)
    raw = db.run_query(queries.SHOP_PERFORMANCE,
                       {"grain": grain, "start_date": start, "end_date": TODAY})
    targets = db.run_query(queries.SHOP_TARGETS, {"grain": grain})
    shops = sp.derive(raw, targets)
    return pd.concat([shops, sp.network(shops)], ignore_index=True)


with st.spinner("Loading shop performance…"):
    data = _load(grain)

locations = sorted(l for l in data["Location"].unique()
                   if l not in sp.NOT_SHOPS and l != ALL)
with col_loc:
    location = st.selectbox("Location", [ALL] + locations, key="shopperf_location")


def _row(df: pd.DataFrame, loc: str, period) -> pd.Series | None:
    hit = df[(df["Location"] == loc) & (df["Period"] == pd.Timestamp(period))]
    return hit.iloc[0] if not hit.empty else None


def _benchmark(df: pd.DataFrame, period) -> pd.Series:
    """The median shop in the period: the yardstick for "typical"."""
    shops = df[(df["Period"] == pd.Timestamp(period)) & ~df["Location"].isin(sp.NOT_SHOPS)
               & (df["Location"] != ALL) & (df["Orders"] >= sp.MIN_ORDERS)]
    return shops[list(sp.METRICS)].median(numeric_only=True)


def _scorecard(df: pd.DataFrame, loc: str, period, grain: str) -> None:
    now = _row(df, loc, period)
    if now is None:
        st.info("No sales for this location in the selected period.")
        return
    prev = _row(df, loc, sp.previous(pd.Timestamp(period), grain))
    ly = _row(df, loc, sp.last_year(pd.Timestamp(period), grain))
    share = sp.elapsed_share(pd.Timestamp(period), grain, TODAY)

    tiles = [("Revenue", "Revenue"), ("Customers", "Customers"), ("Bags Sold", "Bags"),
             ("Avg Order Value", "Avg Order Value")]
    for col, (label, metric) in zip(st.columns(len(tiles)), tiles):
        kind = sp.METRICS[metric][0]
        delta = sp.change(now[metric], ly[metric] if ly is not None else None)
        with col.container(border=True):
            st.metric(label, sp.fmt(now[metric], kind),
                      f"{delta:+.1f}% vs last year" if delta is not None else "no data last year",
                      delta_color="normal" if delta is not None else "off")
    if pd.notna(now.get("% of Target")):
        expected = share * 100
        st.progress(min(now["% of Target"] / 100, 1.0),
                    text=f"{now['% of Target']:.0f}% of target (KES {now['Target']:,.0f})"
                         + (f" · {expected:.0f}% of the period gone" if share < 1 else ""))

    rows = []
    for metric, (kind, up) in sp.METRICS.items():
        if metric == "% of Target" and pd.isna(now.get(metric)):
            continue
        p = prev[metric] if prev is not None else None
        l = ly[metric] if ly is not None else None
        rows.append({"Metric": metric, "This Period": sp.fmt(now[metric], kind),
                     "Previous Period": sp.fmt(p, kind),
                     "Change": _arrow(sp.change(now[metric], p), up),
                     "Same Period Last Year": sp.fmt(l, kind),
                     "Change vs Last Year": _arrow(sp.change(now[metric], l), up)})
    with st.container(border=True):
        st.caption("All metrics for the period, against the one before and the same period last "
                   "year." + (" This period is still running, so it is short against both."
                              if share < 1 else ""))
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _arrow(pct, higher_is_better: bool) -> str:
    if pct is None:
        return "—"
    good = (pct >= 0) == higher_is_better
    return f"{'▲' if pct >= 0 else '▼'} {abs(pct):.1f}% {'✓' if good else '✗'}"


def _trend(df: pd.DataFrame, loc: str, grain: str, metric: str, periods: int = 12) -> None:
    mine = df[df["Location"] == loc].set_index("Period").sort_index()
    if mine.empty:
        return
    recent = mine.tail(periods)
    kind = sp.METRICS[metric][0]
    last = [sp.last_year(p, grain) for p in recent.index]
    ly_values = [mine[metric].get(p) for p in last]
    labels = [sp.period_label(p, grain, TODAY).replace("Week of ", "") for p in recent.index]

    fig = go.Figure()
    fig.add_bar(x=labels, y=recent[metric], name="This year",
                marker=dict(color=theme.CATEGORICAL[0], cornerradius=4),
                hovertemplate="%{x}<br><b>%{y:,.1f}</b><extra>This year</extra>")
    if any(v is not None and pd.notna(v) for v in ly_values):
        fig.add_scatter(x=labels, y=ly_values, name="Same period last year", mode="lines+markers",
                        line=dict(color=theme.TEXT_SECONDARY, width=2, dash="dot"),
                        marker=dict(size=8),
                        hovertemplate="%{x}<br><b>%{y:,.1f}</b><extra>Last year</extra>")
    if metric == "Revenue" and recent["Target"].notna().any():
        fig.add_scatter(x=labels, y=recent["Target"], name="Target", mode="markers",
                        marker=dict(symbol="line-ew", size=26,
                                    line=dict(width=3, color=theme.STATUS["warning"])),
                        hovertemplate="%{x}<br>Target <b>KES %{y:,.0f}</b><extra></extra>")
    theme.apply_layout(fig, show_legend=True)
    fig.update_layout(title=f"{metric} — last {len(recent)} {'weeks' if grain == 'week' else 'months'}",
                      height=380, hovermode="x unified")
    if kind == "kes":
        fig.update_yaxes(tickprefix="KES ", tickformat="~s")
    theme.show(fig)


def _league(df: pd.DataFrame, period, grain: str) -> None:
    rows = []
    for loc in locations:
        now = _row(df, loc, period)
        if now is None:
            continue
        prev = _row(df, loc, sp.previous(pd.Timestamp(period), grain))
        ly = _row(df, loc, sp.last_year(pd.Timestamp(period), grain))
        vs_prev = sp.change(now["Revenue"], prev["Revenue"] if prev is not None else None)
        vs_ly = sp.change(now["Revenue"], ly["Revenue"] if ly is not None else None)
        rows.append({
            "Location": loc, "Revenue": round(now["Revenue"], 0),
            "vs Previous %": round(vs_prev, 1) if vs_prev is not None else None,
            "vs Last Year %": round(vs_ly, 1) if vs_ly is not None else None,
            "% of Target": round(now["% of Target"], 1) if pd.notna(now["% of Target"]) else None,
            "Orders": int(now["Orders"]), "Bags": int(now["Bags"]),
            "Customers": int(now["Customers"]),
            "Returning %": round(now["Returning %"], 1) if pd.notna(now["Returning %"]) else None,
            "Avg Order Value": round(now["Avg Order Value"], 0) if pd.notna(now["Avg Order Value"]) else None,
            "Bags per Order": round(now["Bags per Order"], 2) if pd.notna(now["Bags per Order"]) else None,
            "Refund Rate %": round(now["Refund Rate %"], 1) if pd.notna(now["Refund Rate %"]) else None,
        })
    if not rows:
        st.info("No shop sales in this period.")
        return
    table = pd.DataFrame(rows).sort_values("Revenue", ascending=False)
    table.insert(0, "Rank", range(1, len(table) + 1))
    grid.filterable_table(table, currency_columns=("Revenue", "Avg Order Value"),
                          pinned_columns=("Location",), height=560)


def _plan(df: pd.DataFrame, loc: str, period, grain: str) -> list[dict]:
    now = _row(df, loc, period)
    if now is None:
        return []
    return sp.improvement_plan(
        now, _row(df, loc, sp.previous(pd.Timestamp(period), grain)),
        _row(df, loc, sp.last_year(pd.Timestamp(period), grain)),
        _benchmark(df, period), sp.elapsed_share(pd.Timestamp(period), grain, TODAY))


def _show_plan(plan: list[dict]) -> None:
    if not plan:
        st.info("No sales to base a plan on in this period.")
        return
    for item in plan:
        with st.container(border=True):
            st.markdown(f"{PRIORITY_ICONS[item['Priority']]} **{item['Priority']} · {item['Area']}** — "
                        f"{item['What the numbers show']}")
            st.markdown(f"**Do:** {item['Suggested action']}  \n**Aim for:** {item['Aim for']}")


@st.fragment()
def render_period_view(grain: str, location: str) -> None:
    periods = sorted(data["Period"].dropna().unique(), reverse=True)
    periods = [p for p in periods if pd.Timestamp(p).date() <= TODAY][:26]
    labels = {sp.period_label(p, grain, TODAY): p for p in periods}
    # Default to the last finished period: a period still running reads short
    # against every comparison.
    finished = [l for l in labels if "(to date)" not in l]
    default = list(labels).index(finished[0]) if finished else 0
    choice = st.selectbox("Period", list(labels), index=default, key=f"shopperf_period_{grain}")
    period = labels[choice]

    st.subheader(f"{location} — {choice}")
    _scorecard(data, location, period, grain)

    metric = st.selectbox("Trend", [m for m in sp.METRICS if m != "% of Target"],
                          key=f"shopperf_metric_{grain}")
    with st.container(border=True):
        _trend(data, location, grain, metric)

    st.subheader("League Table")
    st.caption(f"Every location for {choice}, ranked by revenue. Changes are revenue against the "
               "previous period and the same period last year.")
    _league(data, period, grain)

    st.subheader("Improvement Plan")
    st.caption("Generated from the numbers: each location against its target, its previous "
               "period, the same period last year, and the typical (median) shop this period. "
               "Pick a location above for its full plan.")
    if location == ALL:
        summary = []
        for loc in locations:
            plan = _plan(data, loc, period, grain)
            top = next((p for p in plan if p["Priority"] in ("High", "Medium", "Low")), None)
            summary.append({
                "Location": loc,
                "High": sum(p["Priority"] == "High" for p in plan),
                "Medium": sum(p["Priority"] == "Medium" for p in plan),
                "Top Priority": f"{top['Priority']} · {top['Area']}" if top else "On track",
                "What to do first": top["Suggested action"] if top else "Keep the current routine.",
            })
        grid.filterable_table(pd.DataFrame(summary).sort_values(["High", "Medium"], ascending=False),
                              pinned_columns=("Location",), height=520)
    else:
        _show_plan(_plan(data, location, period, grain))
    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")


@st.fragment()
def render_year_on_year(location: str) -> None:
    mine = data[data["Location"] == location].set_index("Period").sort_index()
    if mine.empty:
        st.info("No sales for this location.")
        return
    # Completed months only: a month still running would make this year look short.
    this_month = pd.Timestamp(TODAY.replace(day=1))
    done = mine[mine.index < this_month]
    this_year = done[done.index.year == TODAY.year]
    months = list(this_year.index.month)
    last_year = done[(done.index.year == TODAY.year - 1) & done.index.month.isin(months)]

    st.subheader(f"{location} — {TODAY.year} vs {TODAY.year - 1}, "
                 f"January to {this_month - pd.DateOffset(months=1):%B} (completed months)")
    tiles = [("Revenue", "Revenue"), ("Orders", "Orders"), ("Bags Sold", "Bags"),
             ("Customers", "Customers")]
    for col, (label, metric) in zip(st.columns(len(tiles)), tiles):
        kind = sp.METRICS[metric][0]
        now_v, ly_v = this_year[metric].sum(), last_year[metric].sum() if not last_year.empty else None
        delta = sp.change(now_v, ly_v)
        with col.container(border=True):
            st.metric(label, sp.fmt(now_v, kind),
                      f"{delta:+.1f}% vs {TODAY.year - 1}" if delta is not None else f"no {TODAY.year - 1} data",
                      delta_color="normal" if delta is not None else "off")
    if last_year.empty:
        st.info(f"{location} has no sales recorded in {TODAY.year - 1}, so there is nothing to "
                "compare against yet.")

    metric = st.selectbox("Metric", [m for m in sp.METRICS if m != "% of Target"],
                          key="shopperf_yoy_metric")
    with st.container(border=True):
        fig = go.Figure()
        for year, color, dash in [(TODAY.year - 1, theme.TEXT_SECONDARY, "dot"),
                                  (TODAY.year, theme.CATEGORICAL[0], None)]:
            yr = mine[(mine.index.year == year) & (mine.index < this_month)]
            if yr.empty:
                continue
            fig.add_scatter(x=[f"{p:%b}" for p in yr.index], y=yr[metric], name=str(year),
                            mode="lines+markers", line=dict(color=color, width=2, dash=dash),
                            marker=dict(size=8),
                            hovertemplate=f"%{{x}} {year}<br><b>%{{y:,.1f}}</b><extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title=f"{metric} by month — {TODAY.year} against {TODAY.year - 1}",
                          height=400, hovermode="x unified")
        fig.update_xaxes(categoryorder="array", categoryarray=list(calendar_months()))
        if sp.METRICS[metric][0] == "kes":
            fig.update_yaxes(tickprefix="KES ", tickformat="~s")
        theme.show(fig)

    st.subheader("Year on Year by Location")
    rows = []
    for loc in locations:
        rows_loc = data[(data["Location"] == loc) & (data["Period"] < this_month)].set_index("Period")
        ty = rows_loc[rows_loc.index.year == TODAY.year]
        ly_ = rows_loc[(rows_loc.index.year == TODAY.year - 1) & rows_loc.index.month.isin(list(ty.index.month))]
        r_now, r_ly = ty["Revenue"].sum(), ly_["Revenue"].sum()
        rows.append({"Location": loc, f"Revenue {TODAY.year}": round(r_now, 0),
                     f"Revenue {TODAY.year - 1}": round(r_ly, 0) if r_ly else None,
                     "Change %": round(sp.change(r_now, r_ly), 1) if r_ly else None,
                     f"Customers {TODAY.year}": int(ty["Customers"].sum()),
                     f"Customers {TODAY.year - 1}": int(ly_["Customers"].sum()) if r_ly else None,
                     f"Bags {TODAY.year}": int(ty["Bags"].sum()),
                     f"Bags {TODAY.year - 1}": int(ly_["Bags"].sum()) if r_ly else None})
    table = pd.DataFrame(rows).sort_values(f"Revenue {TODAY.year}", ascending=False)
    grid.filterable_table(table, currency_columns=(f"Revenue {TODAY.year}", f"Revenue {TODAY.year - 1}"),
                          pinned_columns=("Location",), height=520)
    st.caption("Same months in both years, completed months only. A blank last-year figure means "
               "the location was not open yet.")


def calendar_months():
    import calendar
    return [calendar.month_abbr[i] for i in range(1, 13)]


if view == "Year on Year":
    if grain != "month":
        st.stop()
    render_year_on_year(location)
else:
    render_period_view(grain, location)
