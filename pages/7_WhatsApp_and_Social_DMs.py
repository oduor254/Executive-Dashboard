"""WhatsApp & Social DMs — the WhatsApp Monitor and Social DMs apps, side by side.

Two apps, one page, kept apart: each has its own tab with its own touchpoints
and its own numbers, because a WhatsApp interaction and an Instagram DM are
logged differently and convert through different routes.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, charts, db, filters, grid, queries, theme

st.set_page_config(page_title="WhatsApp & Social DMs · Denri Executive Dashboard",
                   page_icon="💬", layout="wide")

auth.require_login()

st.title("💬 WhatsApp & Social DMs")
st.caption("Customer conversations from the WhatsApp Monitor and Social DMs apps — live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_refresh = st.columns([3, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("engagement", default="Month to Date")
with col_refresh:
    # Page level, not inside a fragment: this page has one fragment per app,
    # and a button inside one would only rerun that one.
    db.refresh_button(key="engagement_refresh")

# Colours that follow the outcome across every chart on the page.
ACTIVITY_COLORS = {
    "Purchased": theme.CATEGORICAL[1],      # green
    "Enquiry": theme.CATEGORICAL[0],        # blue
    "Visit Shop": theme.CATEGORICAL[3],     # yellow
    "Transferred": theme.CATEGORICAL[6],    # violet
    "Not Purchased": theme.CATEGORICAL[7],  # red
    "Not recorded": theme.OTHER,
}
FOLLOWUP_COLORS = {
    "Purchased": theme.CATEGORICAL[1],          # green
    "Already Purchased": theme.CATEGORICAL[4],  # aqua
    "Purchase Later": theme.CATEGORICAL[0],     # blue
    "Visit the Shop": theme.CATEGORICAL[3],     # yellow
    "Enquiries": theme.CATEGORICAL[6],          # violet
    "Out of Stock": theme.CATEGORICAL[5],       # orange
    "Not Reachable": theme.CATEGORICAL[7],      # red
}
SOURCE_COLORS = {"Ad": theme.CATEGORICAL[5], "Organic": theme.CATEGORICAL[4]}

# The tables as the user asked to see them, in the order asked.
INTERACTION_COLUMNS = {"Date": "DATE", "Name": "NAME", "Contact": "CONTACT",
                       "Source": "SOURCE", "Activity": "ACTIVITY", "Branch": "BRANCH"}
LEAD_COLUMNS = {"Date": "DATE", "Contact": "CONTACT", "Name": "NAME",
                "Branch": "BRANCH", "Source": "SOURCE", "Platform": "PLATFORM"}


# ---------------------------------------------------------------- access ---

unreadable = db.run_query(queries.ENGAGEMENT_UNREADABLE,
                          {"tables": queries.ENGAGEMENT_TABLES})["Table"].tolist()
if unreadable:
    st.warning(
        "**The dashboard's database user can't read the WhatsApp Monitor and "
        "Social DMs tables yet.** The page is built and will fill in as soon as "
        "access is granted. Ask whoever administers the Odoo database to run:",
        icon="🔒",
    )
    st.code(
        "GRANT SELECT ON\n    "
        + ",\n    ".join(unreadable)
        + "\nTO reporting_reader;",
        language="sql",
    )
    st.caption("Read-only access, the same as the dashboard already has for sales, "
               "stock and dispatch. Nothing on this page writes to Odoo.")
    st.stop()


# --------------------------------------------------------------- helpers ---

def _pct(part: float, whole: float) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "—"


def _kpis(items: list[tuple[str, str, str | None]]) -> None:
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")


def _table(df: pd.DataFrame, columns: dict[str, str], **kwargs) -> None:
    shown = df[list(columns)].rename(columns=columns)
    st.caption(f"{len(shown):,} rows · click a column header's filter icon to search or narrow it.")
    grid.filterable_table(shown, **kwargs)


def _stacked_by_branch(df: pd.DataFrame, stack: str, colors: dict[str, str],
                       title: str) -> go.Figure:
    """Rows per branch, split by `stack`, largest branch at the top."""
    pivot = df.pivot_table(index="Branch", columns=stack, values="ID",
                           aggfunc="count", fill_value=0)
    pivot = pivot.loc[pivot.sum(axis=1).sort_values().index]
    totals = pivot.sum(axis=1)
    fig = go.Figure()
    for key in [k for k in colors if k in pivot.columns] + \
               [k for k in pivot.columns if k not in colors]:
        share = (pivot[key] / totals * 100).round(1)
        fig.add_bar(
            y=pivot.index, x=pivot[key], orientation="h", name=key,
            marker=dict(color=colors.get(key, theme.OTHER),
                        line=dict(color=theme.CHART_SURFACE, width=1)),
            customdata=list(zip(share, totals)),
            hovertemplate=(f"<b>%{{y}}</b><br>{key}: <b>%{{x:,.0f}}</b>"
                           " (%{customdata[0]:.1f}% of %{customdata[1]:,.0f})<extra></extra>"),
        )
    for branch, total in totals.items():
        fig.add_annotation(x=total, y=branch, text=f"<b>{total:,.0f}</b>", showarrow=False,
                           xanchor="left", xshift=6,
                           font=dict(color=theme.TEXT_PRIMARY, size=11))
    theme.apply_layout(fig, show_legend=True)
    fig.update_layout(title=title, barmode="stack", hovermode="closest",
                      legend_traceorder="normal",  # stacked bars default to reversed
                      height=max(380, 28 * len(pivot) + 100))
    fig.update_xaxes(showgrid=True, gridcolor=theme.GRIDLINE)
    fig.update_yaxes(showgrid=False)
    return fig


def _daily_trend(df: pd.DataFrame, title: str, split: str | None = None,
                 colors: dict[str, str] | None = None) -> go.Figure:
    days = pd.to_datetime(df["Date"])
    fig = go.Figure()
    if split is None:
        counts = days.dt.date.value_counts().sort_index()
        fig.add_scatter(x=counts.index, y=counts.values, mode="lines+markers", name="All",
                        line=dict(color=theme.CATEGORICAL[0], width=2),
                        marker=dict(size=8),
                        hovertemplate="%{x|%a %d %b}: <b>%{y:,.0f}</b><extra></extra>")
    else:
        grouped = (df.assign(Day=days.dt.date).groupby(["Day", split]).size()
                     .unstack(fill_value=0).sort_index())
        palette = colors or dict(zip(grouped.columns, charts.colors_for(grouped.columns)))
        for key in grouped.columns:
            fig.add_scatter(x=grouped.index, y=grouped[key], mode="lines+markers", name=key,
                            line=dict(color=palette.get(key, theme.OTHER), width=2),
                            marker=dict(size=8),
                            hovertemplate=f"{key}: <b>%{{y:,.0f}}</b><extra></extra>")
    theme.apply_layout(fig, show_legend=split is not None)
    fig.update_layout(title=title, height=360)
    fig.update_xaxes(tickformat="%d %b")
    return fig


def _ranked_bar(counts: pd.Series, title: str, noun: str) -> go.Figure:
    ranked = counts.sort_values()
    total = counts.sum()
    fig = go.Figure()
    fig.add_bar(
        y=ranked.index, x=ranked.values, orientation="h",
        marker=dict(color=theme.CATEGORICAL[0], cornerradius=4),
        text=[f"{v:,.0f}" for v in ranked.values], textposition="outside", cliponaxis=False,
        textfont=dict(color=theme.TEXT_SECONDARY, size=12),
        customdata=(ranked / total * 100).round(1) if total else None,
        hovertemplate=(f"<b>%{{y}}</b><br><b>%{{x:,.0f}}</b> {noun}"
                       "<br>%{customdata:.1f}% of the total<extra></extra>"),
    )
    theme.apply_layout(fig, show_legend=False)
    fig.update_layout(title=title, height=max(360, 28 * len(ranked) + 80), hovermode="closest")
    fig.update_xaxes(showgrid=True, gridcolor=theme.GRIDLINE)
    fig.update_yaxes(showgrid=False)
    return fig


def _share(df: pd.DataFrame, column: str, *, title: str, key: str, unit: str,
           colors: dict[str, str] | None = None, default: str = "Doughnut") -> None:
    counts = df[column].fillna("Not recorded").value_counts()
    data = charts.fold_other(counts.index, counts.values)
    palette = None
    if colors:
        palette = [colors.get(label, theme.OTHER) for label in data["Label"]]
    charts.share_chart(data, title=title, key=key, unit=unit, colors=palette, default=default)


# ------------------------------------------------------ WhatsApp Monitor ---

@st.fragment()
def render_whatsapp(start_date: date, end_date: date) -> None:
    params = {"start_date": start_date, "end_date": end_date}
    df = db.run_query(queries.WA_INTERACTIONS, params)

    t_dash, t_int, t_transfer, t_oos, t_follow = st.tabs(
        ["📊 Dashboard", "💬 Interactions", "🔁 Transfers", "📭 Out of Stock", "📞 Follow-ups"])

    if df.empty:
        for tab in (t_dash, t_int, t_transfer, t_oos):
            with tab:
                st.info("No WhatsApp interactions logged in this date range.")
    else:
        total = len(df)
        purchased = int(df["Converted"].sum())
        transfers = df[df["Activity"] == "Transferred"]
        oos_count = int(df["Out of Stock"].sum())

        with t_dash:
            _kpis([
                ("Interactions", f"{total:,}", f"{df['Contact'].nunique():,} customers"),
                ("Purchased", f"{purchased:,}", f"{_pct(purchased, total)} conversion"),
                ("Transferred", f"{len(transfers):,}", f"{_pct(len(transfers), total)} of interactions"),
                ("Out of Stock", f"{oos_count:,}", f"{_pct(oos_count, total)} of interactions"),
                ("First Response",
                 f"{df['First Response (min)'].median():,.0f} min"
                 if df["First Response (min)"].notna().any() else "—",
                 "median"),
            ])
            with st.container(border=True):
                theme.show(_stacked_by_branch(df, "Activity", ACTIVITY_COLORS,
                                              "Interactions by Branch and Outcome"))
            c1, c2 = st.columns(2)
            with c1, st.container(border=True):
                _share(df, "Activity", title="Outcome of Interactions", key="wa_activity_kind",
                       unit="interactions", colors=ACTIVITY_COLORS)
            with c2, st.container(border=True):
                _share(df, "Source", title="Where Customers Came From", key="wa_source_kind",
                       unit="interactions", default="Pie")
            with st.container(border=True):
                theme.show(_daily_trend(df, "Interactions per Day by Outcome",
                                        split="Activity", colors=ACTIVITY_COLORS))
            with st.container(border=True):
                st.caption("Conversion by branch")
                by_branch = (df.groupby("Branch")
                               .agg(Interactions=("ID", "count"), Purchased=("Converted", "sum"),
                                    Transferred=("Activity", lambda s: (s == "Transferred").sum()),
                                    **{"Out of Stock": ("Out of Stock", "sum")})
                               .reset_index())
                by_branch["Conversion %"] = (by_branch["Purchased"]
                                             / by_branch["Interactions"] * 100).round(1)
                grid.filterable_table(by_branch.sort_values("Interactions", ascending=False),
                                      height=360)

        with t_int:
            branch = st.selectbox("Branch", ["All branches"] + sorted(df["Branch"].unique()),
                                  key="wa_int_branch")
            shown = df if branch == "All branches" else df[df["Branch"] == branch]
            with st.container(border=True):
                _table(shown, INTERACTION_COLUMNS, pinned_columns=("NAME",))

        with t_transfer:
            linked = transfers[transfers["Destination Linked"]]
            converted = int(linked["Converted at Destination"].sum())
            transferred_in = df[df["Transferred In"]]
            _kpis([
                ("Transferred Out", f"{len(transfers):,}", None),
                ("Linked to Destination", f"{len(linked):,}", _pct(len(linked), len(transfers))),
                ("Needs Destination Link", f"{len(transfers) - len(linked):,}",
                 "transferred, no receiving record"),
                ("Bought at Destination", f"{converted:,}", f"{_pct(converted, len(linked))} of linked"),
                ("Transferred In", f"{len(transferred_in):,}", "received by a branch"),
            ])
            if transfers.empty:
                st.info("No transfers in this date range.")
            else:
                c1, c2 = st.columns(2)
                with c1, st.container(border=True):
                    theme.show(_ranked_bar(
                        transfers["Transferred To"].fillna("Not recorded").value_counts(),
                        "Transfers by Receiving Branch", "transfers"))
                with c2, st.container(border=True):
                    _share(transfers, "Transfer Reason", title="Why Customers Were Transferred",
                           key="wa_transfer_reason_kind", unit="transfers")
                with st.container(border=True):
                    table = transfers.rename(columns={"Branch": "From"}).assign(
                        **{"Outcome at Destination": transfers["Outcome at Destination"]
                           .fillna("Not linked yet")})
                    _table(table, {"Date": "DATE", "Name": "NAME", "Contact": "CONTACT",
                                   "From": "FROM", "Transferred To": "TO",
                                   "Transfer Reason": "REASON",
                                   "Outcome at Destination": "OUTCOME AT DESTINATION"},
                           pinned_columns=("NAME",))

        with t_oos:
            oos = db.run_query(queries.WA_OUT_OF_STOCK, params)
            flagged = df[df["Out of Stock"]]
            _kpis([
                ("Out-of-Stock Interactions", f"{len(flagged):,}", f"{_pct(len(flagged), total)} of interactions"),
                ("Products Asked For", f"{oos['Product Wanted'].nunique():,}" if not oos.empty else "0",
                 "distinct"),
                ("Most Wanted", oos["Product Wanted"].value_counts().index[0] if not oos.empty else "—",
                 f"{oos['Product Wanted'].value_counts().iloc[0]:,} requests" if not oos.empty else None),
                ("Branches Affected", f"{flagged['Branch'].nunique():,}", None),
            ])
            if oos.empty and flagged.empty:
                st.info("No out-of-stock requests in this date range.")
            else:
                c1, c2 = st.columns(2)
                if not oos.empty:
                    with c1, st.container(border=True):
                        theme.show(_ranked_bar(oos["Product Wanted"].value_counts().head(15),
                                               "Most-Requested Out-of-Stock Products", "requests"))
                with c2, st.container(border=True):
                    theme.show(_ranked_bar(flagged["Branch"].value_counts(),
                                           "Out-of-Stock Requests by Branch", "requests"))
                if not oos.empty:
                    with st.container(border=True):
                        _table(oos, {"Date": "DATE", "Name": "NAME", "Contact": "CONTACT",
                                     "Branch": "BRANCH", "Product Wanted": "PRODUCT WANTED",
                                     "Reason": "REASON"}, pinned_columns=("NAME",))

    with t_follow:
        follow = db.run_query(queries.WA_FOLLOWUPS, params)
        lists = db.run_query(queries.WA_FOLLOWUP_LISTS, params).iloc[0]
        if follow.empty:
            st.info("No follow-up outcomes were recorded in this date range.")
        else:
            n = len(follow)
            outcome = follow["Follow-up Outcome"]
            bought = int(outcome.isin(["Purchased", "Already Purchased"]).sum())
            unreachable = int((outcome == "Not Reachable").sum())
            later = int(outcome.isin(["Purchase Later", "Visit the Shop"]).sum())
            _kpis([
                ("Follow-ups Recorded", f"{n:,}",
                 f"{int(lists['Customers Listed']):,} listed in {int(lists['Lists']):,} call lists"),
                ("Bought", f"{bought:,}", f"{_pct(bought, n)} incl. already purchased"),
                ("Still Interested", f"{later:,}", "purchase later or visit shop"),
                ("Not Reachable", f"{unreachable:,}", _pct(unreachable, n)),
            ])
            c1, c2 = st.columns(2)
            with c1, st.container(border=True):
                _share(follow, "Follow-up Outcome", title="Follow-up Outcomes",
                       key="wa_follow_kind", unit="follow-ups", colors=FOLLOWUP_COLORS)
            with c2, st.container(border=True):
                theme.show(_stacked_by_branch(follow, "Follow-up Outcome", FOLLOWUP_COLORS,
                                              "Follow-ups by Branch"))
            with st.container(border=True):
                _table(follow, {"Followed Up On": "FOLLOWED UP ON", "Name": "NAME",
                                "Contact": "CONTACT", "Branch": "BRANCH",
                                "Original Date": "ORIGINAL DATE",
                                "Original Activity": "ORIGINAL ACTIVITY",
                                "Follow-up Outcome": "OUTCOME", "Note": "NOTE"},
                       pinned_columns=("NAME",))

    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")


# ------------------------------------------------------------ Social DMs ---

@st.fragment()
def render_social(start_date: date, end_date: date) -> None:
    df = db.run_query(queries.SOCIAL_DMS, {"start_date": start_date, "end_date": end_date})

    t_dash, t_leads = st.tabs(["📊 Dashboard", "📇 Leads"])
    if df.empty:
        for tab in (t_dash, t_leads):
            with tab:
                st.info("No social DMs logged in this date range.")
        return

    total = len(df)
    converted = int(df["Converted"].sum())
    from_ads = int((df["Source"] == "Ad").sum())
    awaiting = df["Call Status"].isin(["Awaiting Call 1", "Awaiting Call 2"])
    overdue = awaiting & (pd.to_datetime(df["Next Call Due"]) < pd.Timestamp(date.today()))

    with t_dash:
        _kpis([
            ("Social DMs", f"{total:,}", f"{(df['Customer'] == 'New').sum():,} new customers"),
            ("Converted", f"{converted:,}", f"{_pct(converted, total)} conversion"),
            ("From Ads", f"{from_ads:,}", f"{_pct(from_ads, total)} of DMs"),
            ("Awaiting a Call", f"{int(awaiting.sum()):,}", f"{int(overdue.sum()):,} overdue"),
            ("Sent to a Branch", f"{(df['Branch'] != 'Not transferred').sum():,}",
             _pct((df['Branch'] != 'Not transferred').sum(), total)),
        ])
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            _share(df, "Platform", title="DMs by Platform", key="dm_platform_kind", unit="DMs")
        with c2, st.container(border=True):
            _share(df, "Source", title="Ad vs Organic", key="dm_source_kind", unit="DMs",
                   colors=SOURCE_COLORS, default="Pie")
        with st.container(border=True):
            theme.show(_stacked_by_branch(
                df.assign(Outcome=df["Converted"].map({True: "Converted", False: "Not converted"})),
                "Outcome", {"Converted": theme.CATEGORICAL[1], "Not converted": theme.OTHER},
                "DMs Sent to Each Branch, and How Many Bought"))
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            _share(df[df["Converted"]], "Converted At", title="Where DMs Converted",
                   key="dm_stage_kind", unit="conversions", default="Bar")
        with c2, st.container(border=True):
            _share(df, "Call Status", title="Follow-up Call Pipeline", key="dm_calls_kind",
                   unit="DMs")
        with st.container(border=True):
            theme.show(_daily_trend(df, "DMs per Day by Platform", split="Platform"))

    with t_leads:
        c1, c2 = st.columns(2)
        with c1:
            platform = st.selectbox("Platform", ["All platforms"] + sorted(df["Platform"].unique()),
                                    key="dm_leads_platform")
        with c2:
            branch = st.selectbox("Branch", ["All branches"] + sorted(df["Branch"].unique()),
                                  key="dm_leads_branch")
        shown = df if platform == "All platforms" else df[df["Platform"] == platform]
        shown = shown if branch == "All branches" else shown[shown["Branch"] == branch]
        with st.container(border=True):
            _table(shown, LEAD_COLUMNS, pinned_columns=("NAME",))

    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")


tab_wa, tab_dm = st.tabs(["💬 WhatsApp Monitor", "📱 Social DMs"])
with tab_wa:
    render_whatsapp(start_date, end_date)
with tab_dm:
    render_social(start_date, end_date)
