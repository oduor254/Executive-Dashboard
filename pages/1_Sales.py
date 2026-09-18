"""Sales Performance — revenue, orders, and target attainment by branch."""
from __future__ import annotations

import calendar
from datetime import date, datetime

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, charts, db, filters, grid, queries, theme

st.set_page_config(page_title="Sales · Denri Executive Dashboard", page_icon="💰", layout="wide")

auth.require_login()

st.title("💰 Sales Performance")
st.caption("Revenue, orders, and target attainment by branch — live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_refresh = st.columns([3, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("sales")


# One colour per sales channel, the same in every chart on this page.
CHANNEL_COLORS = {
    "Walk-in": theme.CATEGORICAL[0],
    "Online": theme.CATEGORICAL[1],
    "Activation": theme.CATEGORICAL[2],
}

# Attainment against pace, from the reserved status palette. Each band also
# prints its percentage on the bar and names itself in the legend, so the
# colour is never the only cue.
PACE_BANDS = [
    (1.00, "On or ahead of pace", theme.STATUS["good"]),
    (0.90, "Slightly behind", theme.STATUS["warning"]),
    (0.75, "Behind", theme.STATUS["serious"]),
    (0.00, "Well behind", theme.STATUS["critical"]),
]
NO_TARGET = ("No target", theme.OTHER)


def _expected_share(start_date: date, end_date: date) -> float:
    """How much of its target a branch should have reached by end_date.

    Targets are set for a whole day, week or month (the query picks which from
    the length of the range). A month-to-date range is judged against the
    share of the month elapsed, otherwise every branch reads "behind" until
    the last day of the month.
    """
    span = (end_date - start_date).days
    if span > 7 and start_date.day == 1 and start_date.month == end_date.month:
        days = calendar.monthrange(end_date.year, end_date.month)[1]
        return end_date.day / days
    return 1.0


def _band(achieved: float, target: float, expected: float) -> tuple[str, str]:
    if not target:
        return NO_TARGET
    pace = (achieved / 100) / expected if expected else 0
    for floor, label, color in PACE_BANDS:
        if pace >= floor:
            return label, color
    return PACE_BANDS[-1][1:]


def _attainment_chart(branches, expected: float) -> go.Figure:
    """Revenue bar per branch against a target tick, coloured by pace."""
    rows = branches.fillna({"Target": 0, "% Achieved": 0})
    bands = [_band(a, t, expected) for a, t in zip(rows["% Achieved"], rows["Target"])]
    labels = [b[0] for b in bands]
    custom = [
        [t, a, expected * 100, t * expected - r, label]
        for r, t, a, label in zip(rows["Revenue"], rows["Target"], rows["% Achieved"], labels)
    ]
    hover = (
        "<b>%{y}</b><br>"
        "Revenue&nbsp;&nbsp;&nbsp;<b>KES %{x:,.0f}</b><br>"
        "Target&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;KES %{customdata[0]:,.0f}<br>"
        "Achieved&nbsp;&nbsp;<b>%{customdata[1]:.1f}%</b>"
        "&nbsp;(%{customdata[2]:.0f}% expected by now)<br>"
        "%{customdata[4]}"
        "<extra></extra>"
    )

    fig = go.Figure()
    fig.add_bar(
        y=rows["Branch"], x=rows["Revenue"], orientation="h", showlegend=False,
        marker=dict(color=[b[1] for b in bands], cornerradius=4),
        text=[f"{a:.0f}%" if t else "—" for a, t in zip(rows["% Achieved"], rows["Target"])],
        textposition="outside", cliponaxis=False,
        textfont=dict(color=theme.TEXT_SECONDARY, size=12),
        customdata=custom, hovertemplate=hover,
    )
    has_target = rows[rows["Target"] > 0]
    fig.add_scatter(
        y=has_target["Branch"], x=has_target["Target"], mode="markers", name="Target",
        marker=dict(symbol="line-ns", size=18, line=dict(width=2, color=theme.TEXT_PRIMARY)),
        hoverinfo="skip",
    )
    # Legend entries for the colour bands actually on the chart.
    present = set(labels)
    for _, label, color in PACE_BANDS + [(None, *NO_TARGET)]:
        if label in present:
            fig.add_bar(x=[None], y=[None], orientation="h", name=label,
                        marker=dict(color=color), hoverinfo="skip")

    theme.apply_layout(fig, show_legend=True)
    title = "Revenue vs Target by Branch"
    if expected < 1:
        title += f" · {expected:.0%} of the month elapsed"
    fig.update_layout(
        title=title, barmode="overlay", hovermode="closest",
        height=max(420, 30 * len(rows) + 90),
    )
    fig.update_xaxes(showgrid=True, gridcolor=theme.GRIDLINE, tickformat="~s")
    fig.update_yaxes(showgrid=False)
    return fig


@st.fragment()
def render_sales(start_date: date, end_date: date) -> None:
    with col_refresh:
        db.refresh_button(key="sales_refresh")

    df = db.run_query(
        queries.SALES_PERFORMANCE_BY_BRANCH,
        {"start_date": start_date, "end_date": end_date},
    )

    branches = df.loc[df["Branch"] != "GRAND TOTAL"].copy()
    if df.empty or branches.empty:
        st.info("No sales recorded for this date range yet.")
        return

    # SUM() over an empty group in SQL yields NULL, not 0 (e.g. a branch with no
    # matching target row) — treat that the same as zero for display.
    totals = df.loc[df["Branch"] == "GRAND TOTAL"].iloc[0].fillna(0)
    pct = totals["% Achieved"]

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Revenue", f"KES {totals['Revenue']:,.0f}")
    with k2.container(border=True):
        st.metric("Orders", f"{totals['Orders']:,.0f}")
    with k3.container(border=True):
        st.metric("Units Sold", f"{totals['Qty']:,.0f}")
    with k4.container(border=True):
        st.metric("Target Achieved", f"{pct:,.1f}%", delta=f"{pct - 100:,.1f} pts vs target")

    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")

    if branches.empty:
        with st.container(border=True):
            grid.filterable_table(df, currency_columns=("Revenue", "Target"))
        return

    branches = branches.sort_values("Revenue", ascending=True)
    expected = _expected_share(start_date, end_date)

    with st.container(border=True):
        theme.show(_attainment_chart(branches, expected))

    col_share, col_channel = st.columns(2)
    with col_share:
        with st.container(border=True):
            charts.share_chart(
                charts.fold_other(branches["Branch"], branches["Revenue"]),
                title="Revenue Share by Branch", key="sales_share_kind",
            )
    with col_channel:
        with st.container(border=True):
            channels = charts.fold_other(
                list(CHANNEL_COLORS),
                [totals[f"{c} Orders"] for c in CHANNEL_COLORS],
            )
            charts.share_chart(
                channels, title="Orders by Channel", key="sales_channel_kind",
                unit="orders", default="Pie",
                colors=[CHANNEL_COLORS[c] for c in channels["Label"]],
            )

    with st.container(border=True):
        mix = go.Figure()
        by_orders = branches.sort_values("Orders", ascending=False)
        for channel, color in CHANNEL_COLORS.items():
            mix.add_bar(
                x=by_orders["Branch"], y=by_orders[f"{channel} Orders"], name=channel,
                marker=dict(color=color, line=dict(color=theme.CHART_SURFACE, width=1)),
                customdata=by_orders[["Orders"]],
                hovertemplate=(f"{channel}: <b>%{{y:,.0f}}</b> of %{{customdata[0]:,.0f}} orders"
                               "<extra></extra>"),
            )
        theme.apply_layout(mix, show_legend=True)
        mix.update_layout(barmode="stack", bargap=0.25, title="Order Mix by Branch", height=420)
        mix.update_xaxes(tickangle=-40)
        theme.show(mix)

    with st.container(border=True):
        grid.filterable_table(df, currency_columns=("Revenue", "Target"))


render_sales(start_date, end_date)
