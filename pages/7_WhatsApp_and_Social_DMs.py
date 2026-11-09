"""WhatsApp & Social DMs — the WhatsApp Monitor, Social DMs and walk-in Leads
apps, side by side.

Three apps, one page, kept apart: each has its own tab with its own touchpoints
and its own numbers, because a WhatsApp interaction and an Instagram DM are
logged differently and convert through different routes.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, charts, db, filters, grid, queries, stock_planning, theme
from lib import lead_recycling as lr

st.set_page_config(page_title=auth.page_title("WhatsApp & Social DMs"),
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
FEEDBACK_COLORS = {
    "Purchase Link": theme.CATEGORICAL[1],      # green
    "Enquiry Link": theme.CATEGORICAL[0],       # blue
    "Walk-in Link": theme.CATEGORICAL[3],       # yellow
    "Type not recorded": theme.OTHER,
}
# The Leads module's stages, in its own order: where each lead stands.
STAGE_COLORS = {
    "Won": theme.CATEGORICAL[1],        # green
    "Working": theme.CATEGORICAL[0],    # blue
    "Waiting on Stock/Offer": theme.CATEGORICAL[5],  # orange — the module calls it Blocked
    "New": theme.CATEGORICAL[4],        # aqua
    "No Status": theme.OTHER,
    "Lost": theme.CATEGORICAL[7],       # red
}
OPEN_STAGES = ("Working", "Waiting on Stock/Offer", "New", "No Status")
LEADS_COLUMNS = {"Date": "VISIT DAY", "Captured On": "CAPTURED ON", "Reference": "REF", "Name": "NAME", "Contact": "CONTACT",
                 "Branch": "LOCATION", "Attendant": "ATTENDANT", "Bag Wanted": "BAG WANTED",
                 "Colour": "COLOUR", "Status": "STATUS", "Follow-up Date": "FOLLOW-UP",
                 "Note": "NOTE"}
# Sources as both apps name them. Fixed per source so Meta Ad - Instagram is
# the same colour on the WhatsApp tab and the Social DMs tab.
SOURCE_COLORS = {
    "Meta Ad - Facebook": theme.CATEGORICAL[0],
    "Meta Ad - Instagram": theme.CATEGORICAL[2],
    "TikTok Ad": theme.CATEGORICAL[5],
    "X Ad": theme.CATEGORICAL[3],
    "Status Ads": theme.CATEGORICAL[6],
    "Existing Direct": theme.CATEGORICAL[1],
    "New Direct": theme.CATEGORICAL[4],
    "Web Check Out": theme.CATEGORICAL[7],
}

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

def _section(options: list[str], key: str) -> str:
    """A section switcher that loads only the chosen section.

    Used instead of st.tabs, which runs every tab's body on every rerun —
    hidden ones included — so each filter change paid for all of them.
    """
    choice = st.segmented_control("Section", options, default=options[0], key=key,
                                  label_visibility="collapsed")
    return choice if choice in options else options[0]


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
    palette = charts.colors_for(data["Label"], fixed=colors) if colors else None
    charts.share_chart(data, title=title, key=key, unit=unit, colors=palette, default=default)


# ------------------------------------------------------ WhatsApp Monitor ---

@st.fragment()
def render_whatsapp(start_date: date, end_date: date) -> None:
    params = {"start_date": start_date, "end_date": end_date}
    df = db.run_query(queries.WA_INTERACTIONS, params)

    # One sub-section at a time (see _section): only its charts and queries run.
    wa_view = _section(["📊 Dashboard", "💬 Interactions", "🔁 Transfers",
                        "📭 Out of Stock", "📞 Follow-ups", "📝 Feedback"], "wa_section")
    t_dash, t_int, t_transfer, t_oos, t_follow, t_feedback = (
        wa_view == "📊 Dashboard", wa_view == "💬 Interactions", wa_view == "🔁 Transfers",
        wa_view == "📭 Out of Stock", wa_view == "📞 Follow-ups", wa_view == "📝 Feedback")

    if df.empty:
        if not t_follow:
            st.info("No WhatsApp interactions logged in this date range.")
    else:
        total = len(df)
        purchased = int(df["Converted"].sum())
        transfers = df[df["Activity"] == "Transferred"]
        oos_count = int(df["Out of Stock"].sum())

        if t_dash:
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
                       colors=SOURCE_COLORS,
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

        if t_int:
            branch = st.selectbox("Branch", ["All branches"] + sorted(df["Branch"].unique()),
                                  key="wa_int_branch")
            shown = df if branch == "All branches" else df[df["Branch"] == branch]
            with st.container(border=True):
                _table(shown, INTERACTION_COLUMNS)

        if t_transfer:
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

        if t_oos:
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

        if t_feedback:
            _render_feedback(df)

    if t_follow:
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


def _render_feedback(df: pd.DataFrame) -> None:
    """Feedback links sent from WhatsApp chats, by location and kind of link."""
    sent = df[df["Feedback Sent"]]
    total = len(df)
    kinds = sent["Feedback Link"].value_counts()
    _kpis([
        ("Feedback Links Sent", f"{len(sent):,}", f"{_pct(len(sent), total)} of interactions"),
        ("Purchase Links", f"{kinds.get('Purchase Link', 0):,}", "after a purchase"),
        ("Enquiry Links", f"{kinds.get('Enquiry Link', 0):,}", "after an enquiry"),
        ("Walk-in Links", f"{kinds.get('Walk-in Link', 0):,}", "to walk-in customers"),
        ("Locations Sending", f"{sent['Branch'].nunique():,}", f"of {df['Branch'].nunique():,}"),
    ])
    if sent.empty:
        st.info("No feedback links were sent in this date range.")
        return

    with st.container(border=True):
        theme.show(_stacked_by_branch(sent, "Feedback Link", FEEDBACK_COLORS,
                                      "Feedback Links Sent by Location"))
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        _share(sent, "Feedback Link", title="Kind of Link Sent", key="wa_feedback_kind",
               unit="links", colors=FEEDBACK_COLORS)
    with c2, st.container(border=True):
        theme.show(_daily_trend(sent, "Feedback Links per Day", split="Feedback Link",
                                colors=FEEDBACK_COLORS))

    with st.container(border=True):
        st.caption("Feedback links by location. Purchases Covered is the share of the "
                   "location's purchases that got a purchase link.")
        by_kind = (sent.pivot_table(index="Branch", columns="Feedback Link", values="ID",
                                    aggfunc="count", fill_value=0))
        order = [k for k in FEEDBACK_COLORS if k in by_kind.columns]
        table = by_kind[order].copy()
        table["Links Sent"] = table.sum(axis=1)
        base = df.groupby("Branch").agg(Interactions=("ID", "count"),
                                        Purchases=("Converted", "sum"))
        table = base.join(table, how="left").fillna(0)
        table["% of Interactions"] = (table["Links Sent"] / table["Interactions"] * 100).round(1)
        if "Purchase Link" in table.columns:
            table["Purchases Covered %"] = (table["Purchase Link"]
                                            / table["Purchases"].where(table["Purchases"] > 0)
                                            * 100).round(1).fillna(0)
        counts = ["Interactions", "Purchases"] + order + ["Links Sent"]
        table[counts] = table[counts].astype(int)
        table = (table.reset_index().rename(columns={"Branch": "Location"})
                 .sort_values("Links Sent", ascending=False))
        grid.filterable_table(table, pinned_columns=("Location",), height=420)

    with st.container(border=True):
        branch = st.selectbox("Location", ["All locations"] + sorted(sent["Branch"].unique()),
                              key="wa_feedback_branch")
        shown = sent if branch == "All locations" else sent[sent["Branch"] == branch]
        _table(shown, {"Date": "DATE", "Name": "NAME", "Contact": "CONTACT",
                       "Branch": "LOCATION", "Activity": "ACTIVITY",
                       "Feedback Link": "LINK SENT"}, pinned_columns=("NAME",))


# ------------------------------------------------------------ Social DMs ---

@st.fragment()
def render_social(start_date: date, end_date: date) -> None:
    df = db.run_query(queries.SOCIAL_DMS, {"start_date": start_date, "end_date": end_date})

    dm_view = _section(["📊 Dashboard", "📇 Leads"], "dm_section")
    t_dash, t_leads = dm_view == "📊 Dashboard", dm_view == "📇 Leads"
    if df.empty:
        st.info("No social DMs logged in this date range.")
        return

    total = len(df)
    converted = int(df["Converted"].sum())
    from_ads = int(df["From Ad"].sum())
    awaiting = df["Call Status"].isin(["Awaiting Call 1", "Awaiting Call 2"])
    overdue = awaiting & (pd.to_datetime(df["Next Call Due"]) < pd.Timestamp(date.today()))

    if t_dash:
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
            _share(df, "Source", title="Where DMs Came From", key="dm_source_kind", unit="DMs",
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

    if t_leads:
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
            _table(shown, LEAD_COLUMNS)

    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")


# ----------------------------------------------------------------- Leads ---

@st.fragment()
def render_leads(start_date: date, end_date: date) -> None:
    """Walk-in leads: customers who asked for a bag the shop could not sell
    them there and then, captured so the branch can follow up."""
    df = db.run_query(queries.WALKIN_LEADS, {"start_date": start_date, "end_date": end_date})
    view = _section(["📊 Dashboard", "📇 Leads", "📞 Follow-ups Due"], "leads_section")
    if df.empty:
        st.info("No leads captured in this date range.")
        return

    total = len(df)
    won = df[df["Converted"]]
    open_ = df[df["Stage"].isin(OPEN_STAGES)]
    stock = int((df["Status"] == "Awaiting Stock").sum())
    offer = int((df["Status"] == "Awaiting Offer").sum())
    lost = int((df["Stage"] == "Lost").sum())

    if view == "📊 Dashboard":
        _kpis([
            ("Leads Captured", f"{total:,}", f"{df['Branch'].nunique():,} locations"),
            ("Purchased", f"{len(won):,}", f"{_pct(len(won), total)} conversion"),
            ("Still Open", f"{len(open_):,}", f"{_pct(len(open_), total)} of leads"),
            ("Awaiting Stock", f"{stock:,}", f"+ {offer:,} awaiting an offer"),
            ("Lost", f"{lost:,}", "unreachable, not interested, wrong number"),
        ])
        with st.container(border=True):
            theme.show(_stacked_by_branch(df, "Stage", STAGE_COLORS,
                                          "Leads by Location and Stage"))
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            _share(df, "Status", title="Where Leads Stand", key="leads_status_kind",
                   unit="leads", default="Bar")
        with c2, st.container(border=True):
            theme.show(_ranked_bar(df["Bag Wanted"].value_counts().head(15),
                                   "Most-Requested Bags", "leads"))
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            theme.show(_daily_trend(df, "Leads Captured per Day by Stage", split="Stage",
                                    colors=STAGE_COLORS))
        with c2, st.container(border=True):
            _share(df, "Contact Method", title="How Leads Were Captured",
                   key="leads_method_kind", unit="leads", default="Pie")

        with st.container(border=True):
            st.caption("Leads by location. Conversion % is purchased leads over all leads "
                       "captured; Amount Paid is what converted leads paid where recorded.")
            g = df.groupby("Branch")
            table = pd.DataFrame({
                "Leads": g.size(),
                "Purchased": g["Converted"].sum(),
                "Awaiting Stock": g["Status"].apply(lambda v: (v == "Awaiting Stock").sum()),
                "Awaiting Offer": g["Status"].apply(lambda v: (v == "Awaiting Offer").sum()),
                "Working": g["Stage"].apply(lambda v: (v == "Working").sum()),
                "Not Started": g["Stage"].apply(lambda v: v.isin(["New", "No Status"]).sum()),
                "Lost": g["Stage"].apply(lambda v: (v == "Lost").sum()),
                "Amount Paid": g["Amount Paid"].sum(),
            }).astype({"Purchased": int})
            table.insert(2, "Conversion %", (table["Purchased"] / table["Leads"] * 100).round(1))
            table = (table.reset_index().rename(columns={"Branch": "Location"})
                     .sort_values("Leads", ascending=False))
            grid.filterable_table(table, currency_columns=("Amount Paid",),
                                  pinned_columns=("Location",), height=420)

        with st.container(border=True):
            st.caption("Leads by attendant — who captures leads, and how many of them buy.")
            g = df.groupby(["Attendant", "Branch"])
            people = pd.DataFrame({"Leads": g.size(), "Purchased": g["Converted"].sum()})
            people["Conversion %"] = (people["Purchased"] / people["Leads"] * 100).round(1)
            people = (people.reset_index().rename(columns={"Branch": "Location"})
                      .astype({"Purchased": int}).sort_values("Leads", ascending=False))
            grid.filterable_table(people, pinned_columns=("Attendant",), height=360)

    elif view == "📇 Leads":
        c1, c2 = st.columns(2)
        branch = c1.selectbox("Location", ["All locations"] + sorted(df["Branch"].unique()),
                              key="leads_branch")
        status = c2.selectbox("Status", ["All statuses"] + sorted(df["Status"].unique()),
                              key="leads_status")
        shown = df if branch == "All locations" else df[df["Branch"] == branch]
        shown = shown if status == "All statuses" else shown[shown["Status"] == status]
        with st.container(border=True):
            _table(shown, LEADS_COLUMNS, pinned_columns=("NAME",))

    else:
        today = pd.Timestamp(date.today())
        due_on = pd.to_datetime(df["Follow-up Date"])
        open_mask = df["Stage"].isin(OPEN_STAGES)
        due = df[open_mask & due_on.notna() & (due_on <= today)].copy()
        due["Days Overdue"] = (today - pd.to_datetime(due["Follow-up Date"])).dt.days
        no_date = int((open_mask & due_on.isna()).sum())
        _kpis([
            ("Follow-ups Due", f"{len(due):,}", "open leads, follow-up date reached"),
            ("Overdue a Week+", f"{int((due['Days Overdue'] >= 7).sum()):,}", None),
            ("Open, No Follow-up Date", f"{no_date:,}", "no date set to call back"),
            ("Locations", f"{due['Branch'].nunique():,}", "with follow-ups due"),
        ])
        if due.empty:
            st.success("No open leads are past their follow-up date.", icon="✅")
        else:
            with st.container(border=True):
                theme.show(_ranked_bar(due["Branch"].value_counts(),
                                       "Follow-ups Due by Location", "leads"))
            with st.container(border=True):
                _table(due.sort_values("Days Overdue", ascending=False),
                       {**LEADS_COLUMNS, "Days Overdue": "DAYS OVERDUE"},
                       pinned_columns=("NAME",))
    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')} · leads in the Leads "
               "module (walk-in, call and WhatsApp), dated by the visit day: shops enter a day's "
               "leads the next morning, so a lead captured today is yesterday's.")


# ---------------------------------------------------------- Out of Stock ---

OOS_LEADS = "Leads (walk-in)"
OOS_WHATSAPP = "WhatsApp (online)"
OOS_COLORS = {OOS_LEADS: theme.CATEGORICAL[5], OOS_WHATSAPP: theme.CATEGORICAL[1]}


def _out_of_stock_cases(start_date: date, end_date: date) -> pd.DataFrame:
    """Every out-of-stock case in the range, from both apps, one row per
    customer and bag asked for:
      Leads     — walk-in leads (Leads module) waiting for stock;
      WhatsApp  — WhatsApp Monitor chats flagged out of stock, one row per
                  product asked for, or one "Not recorded" row when the chat
                  was flagged without naming the product.
    """
    params = {"start_date": start_date, "end_date": end_date}
    frames = []
    leads = db.run_query(queries.WALKIN_LEADS, params)
    if not leads.empty:
        waiting = leads[leads["Status"] == "Awaiting Stock"]
        frames.append(pd.DataFrame({
            "Source": OOS_LEADS, "Date": waiting["Date"], "Customer": waiting["Name"],
            "Contact": waiting["Contact"], "Location": waiting["Branch"],
            "Product Wanted": waiting["Bag Wanted"], "Colour": waiting["Colour"],
            "Detail": waiting["Note"], "Served By": waiting["Attendant"]}))
    chats = db.run_query(queries.WA_INTERACTIONS, params)
    wanted = db.run_query(queries.WA_OUT_OF_STOCK, params)
    if not wanted.empty:
        frames.append(pd.DataFrame({
            "Source": OOS_WHATSAPP, "Date": wanted["Date"], "Customer": wanted["Name"],
            "Contact": wanted["Contact"], "Location": wanted["Branch"],
            "Product Wanted": wanted["Product Wanted"], "Colour": None,
            "Detail": wanted["Reason"], "Served By": None}))
    if not chats.empty:
        named = set(wanted["ID"]) if not wanted.empty else set()
        bare = chats[chats["Out of Stock"] & ~chats["ID"].isin(named)]
        frames.append(pd.DataFrame({
            "Source": OOS_WHATSAPP, "Date": bare["Date"], "Customer": bare["Name"],
            "Contact": bare["Contact"], "Location": bare["Branch"],
            "Product Wanted": "Not recorded", "Colour": None, "Detail": None, "Served By": None}))
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    cases = pd.concat(frames, ignore_index=True)
    cases["Bag"] = cases["Product Wanted"].map(
        lambda p: p if p in ("Not recorded", None) else stock_planning.family(str(p)))
    return cases.sort_values("Date", ascending=False)


def _phone_key(value) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-9:] if len(digits) >= 9 else None


def _fulfilment(cases: pd.DataFrame) -> pd.DataFrame:
    """Did each out-of-stock customer later buy the bag they asked for?

    Matched on the last nine digits of their phone: a bag of the same family
    (any colour) bought at any shop or online on or after the day they asked.
    "Several bags" requests ("Kai/Loop") are met by any bag they name.
    Requests with no phone cannot be followed and are marked so.
    """
    out = cases.copy()
    out["Phone Key"] = out["Contact"].map(_phone_key)
    out["Fulfilled"], out["Bought On"], out["Bought At"], out["Bought Other"] = False, None, None, False
    keys = sorted(k for k in out["Phone Key"].dropna().unique())
    if not keys:
        out["Trackable"] = False
        return out
    bought = db.run_query(queries.PURCHASES_BY_PHONE,
                          {"phone_keys": keys, "from_date": out["Date"].min()})
    out["Trackable"] = out["Phone Key"].notna()
    if bought.empty:
        return out
    bought["Family"] = bought["Product"].map(lambda p: stock_planning.family(str(p)).lower())
    bought["Bought On"] = pd.to_datetime(bought["Bought On"])
    by_key = {k: g.sort_values("Bought On") for k, g in bought.groupby("Phone Key")}
    for i, row in out[out["Trackable"]].iterrows():
        later = by_key.get(row["Phone Key"])
        if later is None:
            continue
        later = later[later["Bought On"] >= pd.Timestamp(row["Date"])]
        if later.empty:
            continue
        want = str(row["Bag"] or "").lower()
        text = str(row["Product Wanted"] or "").lower()
        hit = later[[f == want or (len(f) > 2 and f in text) or (want and want in f)
                     for f in later["Family"]]]
        if not hit.empty and want not in ("", "not recorded"):
            out.at[i, "Fulfilled"] = True
            out.at[i, "Bought On"] = hit["Bought On"].iloc[0].date()
            out.at[i, "Bought At"] = hit["Bought At"].iloc[0]
        else:
            out.at[i, "Bought Other"] = True
    out["Days to Fulfil"] = (pd.to_datetime(out["Bought On"]) - pd.to_datetime(out["Date"])).dt.days
    return out


@st.fragment()
def render_out_of_stock(start_date: date, end_date: date) -> None:
    """Out-of-stock demand from walk-in customers (Leads) and online customers
    (WhatsApp Monitor) together, with the stock there is to meet it."""
    cases = _out_of_stock_cases(start_date, end_date)
    if cases.empty:
        st.info("No out-of-stock requests in this date range.")
        return
    cases = _fulfilment(cases)

    c1, c2 = st.columns(2)
    source = c1.selectbox("Source", ["Both", OOS_LEADS, OOS_WHATSAPP], key="oos_source")
    where = c2.selectbox("Location", ["All locations"] + sorted(cases["Location"].dropna().unique()),
                         key="oos_location")
    shown = cases if source == "Both" else cases[cases["Source"] == source]
    shown = shown if where == "All locations" else shown[shown["Location"] == where]
    if shown.empty:
        st.info("No out-of-stock requests for this choice.")
        return

    by_source = shown["Source"].value_counts()
    named = shown[shown["Bag"] != "Not recorded"]
    top = named["Bag"].value_counts()
    _kpis([
        ("Out-of-Stock Requests", f"{len(shown):,}", f"{shown['Contact'].nunique():,} customers"),
        (OOS_LEADS, f"{by_source.get(OOS_LEADS, 0):,}", "awaiting stock"),
        (OOS_WHATSAPP, f"{by_source.get(OOS_WHATSAPP, 0):,}", "chats flagged out of stock"),
        ("Bags Asked For", f"{named['Bag'].nunique():,}",
         f"{(shown['Bag'] == 'Not recorded').sum():,} requests name no bag"),
        ("Most Wanted", top.index[0] if not top.empty else "—",
         f"{top.iloc[0]:,} requests" if not top.empty else None),
    ])
    tracked = shown[shown["Trackable"]]
    done = int(tracked["Fulfilled"].sum())
    other = int(tracked["Bought Other"].sum())
    _kpis([
        ("Fulfilled", f"{done:,}", "bought the bag they asked for"),
        ("Fulfilment Rate", _pct(done, len(tracked)), f"of {len(tracked):,} with a phone number"),
        ("Bought Something Else", f"{other:,}", _pct(other, len(tracked))),
        ("Still Waiting", f"{len(tracked) - done - other:,}", "no bag bought since"),
        ("Days to Fulfil", f"{tracked['Days to Fulfil'].median():.0f}"
         if done else "—", "median, request to purchase"),
    ])
    st.caption("**Fulfilled** means the customer (matched on the last nine digits of their "
               "phone) bought the bag they asked for — any colour, at any shop or online — on "
               "or after the day they asked; **Bought Something Else** means they bought a "
               "different bag instead. Requests with no phone number can't be followed and are "
               "left out of the rate. "
               "Every out-of-stock case in the range: walk-in customers recorded in the Leads "
               "module as **Awaiting Stock**, and WhatsApp Monitor chats flagged **out of "
               "stock** (one row per bag asked for). Bags are grouped across colours. "
               "Stock is what is on hand now — at the shops and in transit, and ready in the "
               "warehouses.")

    # What is on hand now for each bag asked for.
    position = db.run_query(queries.STOCK_POSITION)
    position = position.assign(Bag=position["SKU"].map(stock_planning.family))
    at_shops = position[position["Bucket"].isin(["Shop", "Transit"])].groupby("Bag")["Qty"].sum()
    in_wh = position[position["Bucket"] == "Warehouse"].groupby("Bag")["Qty"].sum()

    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        bags = (named.pivot_table(index="Bag", columns="Source", values="Date", aggfunc="count",
                                  fill_value=0))
        bags = bags.loc[bags.sum(axis=1).sort_values().index].tail(15)
        fig = go.Figure()
        for name in [s for s in OOS_COLORS if s in bags.columns]:
            fig.add_bar(y=bags.index, x=bags[name], orientation="h", name=name,
                        marker=dict(color=OOS_COLORS[name], line=dict(color=theme.CHART_SURFACE, width=1)),
                        text=bags[name].map(lambda n: f"{n:,.0f}" if n else ""),
                        textposition="inside", insidetextanchor="middle",
                        textfont=dict(color="white"),
                        hovertemplate=f"<b>%{{y}}</b><br>{name}: <b>%{{x:,.0f}}</b><extra></extra>")
        total = bags.sum(axis=1)
        fig.add_scatter(y=bags.index, x=total, mode="text", text=total.map("{:,.0f}".format),
                        textposition="middle right", showlegend=False, hoverinfo="skip",
                        textfont=dict(color=theme.TEXT_PRIMARY))
        theme.apply_layout(fig, show_legend=True)
        fig.update_xaxes(range=[0, total.max() * 1.12 if len(total) else 1])
        fig.update_layout(title="Most-Requested Out-of-Stock Bags", barmode="stack",
                          hovermode="closest", legend_traceorder="normal",
                          height=max(380, 28 * len(bags) + 100))
        theme.show(fig)
    with c2, st.container(border=True):
        theme.show(_stacked_by_branch(shown.assign(ID=range(len(shown)), Branch=shown["Location"]),
                                      "Source", OOS_COLORS, "Out-of-Stock Requests by Location"))
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        theme.show(_daily_trend(shown, "Out-of-Stock Requests per Day", split="Source",
                                colors=OOS_COLORS))
    with c2, st.container(border=True):
        _share(shown, "Source", title="Where the Requests Came From", key="oos_source_kind",
               unit="requests", colors=OOS_COLORS)

    with st.container(border=True):
        st.caption("Each bag asked for, with the stock on hand now to meet it.")
        table = (named.groupby("Bag")
                 .agg(Requests=("Source", "size"),
                      Leads=("Source", lambda v: int((v == OOS_LEADS).sum())),
                      WhatsApp=("Source", lambda v: int((v == OOS_WHATSAPP).sum())),
                      Customers=("Contact", "nunique"),
                      Locations=("Location", lambda v: ", ".join(sorted(set(v.dropna())))),
                      **{"Last Asked": ("Date", "max")},
                      Trackable=("Trackable", "sum"), Fulfilled=("Fulfilled", "sum")))
        table["Fulfilment %"] = (table["Fulfilled"] / table["Trackable"].where(table["Trackable"] > 0)
                                 * 100).round(1)
        table = table.drop(columns=["Trackable"])
        table["At Shops Now"] = at_shops.reindex(table.index).fillna(0).clip(lower=0)
        table["In Warehouse Now"] = in_wh.reindex(table.index).fillna(0).clip(lower=0)
        grid.filterable_table(table.reset_index().sort_values("Requests", ascending=False),
                              pinned_columns=("Bag",), height=420)
    with st.container(border=True):
        outcome = np.select([~shown["Trackable"], shown["Fulfilled"], shown["Bought Other"]],
                            ["No phone", "Fulfilled", "Bought something else"], "Still waiting")
        _table(shown.assign(Outcome=outcome),
               {"Date": "DATE", "Source": "SOURCE", "Customer": "CUSTOMER",
                "Contact": "CONTACT", "Location": "LOCATION",
                "Product Wanted": "PRODUCT WANTED", "Colour": "COLOUR",
                "Outcome": "OUTCOME", "Bought On": "BOUGHT ON", "Bought At": "BOUGHT AT",
                "Days to Fulfil": "DAYS TO FULFIL",
                "Detail": "NOTE / REASON", "Served By": "SERVED BY"},
               pinned_columns=("CUSTOMER",))
    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")


# --------------------------------------------------------- Lead Recycling ---

RECYCLE_COLORS = {
    lr.READY: theme.CATEGORICAL[5],      # orange — needs a call
    lr.SCHEDULED: theme.CATEGORICAL[0],  # blue
    lr.FRESH: theme.CATEGORICAL[4],      # aqua
    lr.NURTURE: theme.CATEGORICAL[6],    # violet
    lr.RECOVERED: theme.CATEGORICAL[1],  # green
    lr.DO_NOT: theme.OTHER,
}
POOL_WINDOWS = {"Last 30 days": 30, "Last 60 days": 60, "Last 90 days": 90, "Last 180 days": 180}


@st.cache_data(ttl=1800, show_spinner=False)
def _recycling_data(start: date, end: date) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """(every touch in the pool, bag purchases by those phones since, bags at
    the shops now by bag). All seven queries run at once — the till match
    included, which is done in the database — and the result is cached."""
    params = {"start_date": start, "end_date": end}
    with ThreadPoolExecutor(max_workers=7) as pool:
        jobs = {k: pool.submit(db.run_query, q, params) for k, q in (
            ("wa", queries.RECYCLE_WA_TOUCHES), ("names", queries.RECYCLE_WA_NAMES),
            ("wanted", queries.RECYCLE_WA_WANTED), ("dms", queries.SOCIAL_DMS),
            ("leads", queries.WALKIN_LEADS), ("bought", queries.RECYCLE_PURCHASES))}
        position_f = pool.submit(db.run_query, queries.STOCK_POSITION)
        d = {k: f.result() for k, f in jobs.items()}
        position = position_f.result()
    touches = lr.touches(d["wa"], d["names"], d["wanted"], d["dms"], d["leads"])
    shelf = position[position["Bucket"].isin(["Shop", "Transit"])]
    stock = shelf.assign(Bag=shelf["SKU"].map(stock_planning.family)).groupby("Bag")["Qty"].sum()
    return touches, d["bought"], stock


@st.cache_data(ttl=1800, show_spinner=False)
def _recycling_customers(start: date, today: date, after: int, attempts: int) -> pd.DataFrame:
    """One row per unconverted customer, cached apart from the raw data so
    the list's filters don't rebuild it and a new rule doesn't re-query."""
    touches, bought, stock = _recycling_data(start, today)
    if touches.empty:
        return pd.DataFrame()
    return lr.customers(touches, bought, stock, today=today, recycle_after=after, max_attempts=attempts)


@st.fragment()
def render_recycling() -> None:
    """Unconverted leads from all three apps, one row per customer: who has
    come back, who is due another go, and the call list to work from."""
    c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1])
    window = c1.selectbox("Leads lost in", list(POOL_WINDOWS), index=2, key="recycle_window",
                          help="The recycling pool runs to today, whatever the date range above.")
    after = c2.number_input("Recycle after (days)", 1, 60, 7, key="recycle_after",
                            help="Days since the last touch before a lead goes back into the pool.")
    attempts = c3.number_input("Max follow-ups", 1, 10, 3, key="recycle_attempts",
                               help="After this many follow-ups with no sale, offers and broadcasts only.")
    today = date.today()
    start = today - timedelta(days=POOL_WINDOWS[window])
    with st.spinner("Reading the three apps' leads and their purchases since…"):
        cust = _recycling_customers(start, today, int(after), int(attempts))
    if cust.empty:
        st.info("Every customer in this window bought.")
        return
    no_phone, same_day = cust.attrs.get("no_phone", 0), cust.attrs.get("same_day", 0)
    channel = c4.selectbox("Channel", ["All channels"] + lr.CHANNELS, key="recycle_channel")
    if channel != "All channels":
        cust = cust[cust["Channel"] == channel]

    view = _section(["📊 Tracker", "📋 Recycle List", "📖 How It Works"], "recycle_section")
    status = cust["Status"].value_counts()
    rec = cust[cust["Recovered"]]
    n = len(cust)

    if view == "📊 Tracker":
        _kpis([
            ("Unconverted Customers", f"{n:,}",
             f"{cust['Touches'].sum():,} touches · {no_phone:,} more with no phone"),
            ("Recovered", f"{len(rec):,}", f"{_pct(len(rec), n)} came back and bought"),
            ("Value Recovered", f"KES {rec['Amount'].sum():,.0f}", "their first purchase, at the tills"),
            ("After a Follow-up", f"{int(rec['After Follow-up'].sum()):,}",
             f"{_pct(rec['After Follow-up'].sum(), len(rec))} of recoveries"),
            ("Days to Recover", f"{rec['Days to Recover'].median():.0f}" if not rec.empty else "—",
             "median, first lost to bought"),
        ])
        never = int(((cust["Attempts"] == 0) & ~cust["Recovered"] & (cust["Status"] != lr.FRESH)).sum())
        _kpis([
            (lr.READY, f"{status.get(lr.READY, 0):,}", f"{_pct(status.get(lr.READY, 0), n)} · due a call now"),
            (lr.SCHEDULED, f"{status.get(lr.SCHEDULED, 0):,}", "call-back date still to come"),
            (lr.FRESH, f"{status.get(lr.FRESH, 0):,}", f"touched in the last {after} days"),
            (lr.NURTURE, f"{status.get(lr.NURTURE, 0):,}", f"{attempts}+ follow-ups, no sale"),
            ("Never Followed Up", f"{never:,}", "past the fresh window, no follow-up recorded"),
        ])
        st.caption(f"One row per customer (matched on the last nine digits of the phone) with an "
                   f"unconverted touch since {start:%d %b %Y} in the WhatsApp Monitor, Social DMs or "
                   f"Leads. **Recovered** = bought a bag at any shop or online on a later day, or a "
                   f"later touch converted. {same_day:,} customers who bought the "
                   "same day they asked were never lost and are left out.")

        with st.container(border=True):
            weeks = cust.assign(Week=cust["First Unconverted"].dt.to_period("W-SAT").dt.start_time)
            pivot = weeks.pivot_table(index="Week", columns="Status", values="Phone Key",
                                      aggfunc="count", fill_value=0)
            fig = go.Figure()
            for s in [s for s in lr.STATUSES if s in pivot.columns]:
                fig.add_bar(x=pivot.index, y=pivot[s], name=s, marker=dict(color=RECYCLE_COLORS[s]),
                            hovertemplate=f"Week of %{{x|%d %b}}<br>{s}: <b>%{{y:,.0f}}</b><extra></extra>")
            rate = (pivot.get(lr.RECOVERED, 0) / pivot.sum(axis=1) * 100).round(1)
            fig.add_scatter(x=pivot.index, y=rate, name="Recovery %", yaxis="y2", mode="lines+markers",
                            line=dict(color=theme.TEXT_PRIMARY, width=2),
                            hovertemplate="Recovery: <b>%{y:.1f}%</b><extra></extra>")
            theme.apply_layout(fig, show_legend=True)
            fig.update_layout(title="Customers lost each week (Sun–Sat) — where they stand now",
                              barmode="stack", height=420, legend_traceorder="normal",
                              yaxis2=dict(overlaying="y", side="right", ticksuffix="%", showgrid=False,
                                          rangemode="tozero", tickfont=dict(color=theme.TEXT_MUTED)))
            fig.update_xaxes(tickformat="%d %b")
            theme.show(fig)

        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            reasons = lr.by_group(cust, "Reason")
            reasons = reasons[reasons["Unconverted Customers"] >= 20].sort_values("Recovery %")
            fig = go.Figure(go.Bar(
                y=reasons["Reason"], x=reasons["Recovery %"], orientation="h",
                marker=dict(color=theme.CATEGORICAL[1], cornerradius=4),
                text=[f"{v:.1f}%" for v in reasons["Recovery %"]], textposition="outside", cliponaxis=False,
                customdata=reasons[["Recovered", "Unconverted Customers"]],
                hovertemplate=("<b>%{y}</b><br>%{customdata[0]:,} of %{customdata[1]:,} recovered"
                               "<extra></extra>")))
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="Recovery rate by why they didn't buy", hovermode="closest",
                              height=max(360, 28 * len(reasons) + 90))
            fig.update_xaxes(ticksuffix="%", showgrid=True, gridcolor=theme.GRIDLINE)
            theme.show(fig)
        with c2, st.container(border=True):
            theme.show(_stacked_by_branch(cust.assign(ID=range(n)), "Status", RECYCLE_COLORS,
                                          "Recycle status by branch"))

        with st.container(border=True):
            by = st.segmented_control("Scorecard by", ["Branch", "Channel", "Reason", "Source"],
                                      default="Branch", key="recycle_by") or "Branch"
            st.caption("**Never Followed Up** is the gap to close: customers past the fresh window "
                       "that nobody has followed up yet.")
            grid.filterable_table(lr.by_group(cust, by), currency_columns=("Value Recovered",),
                                  pinned_columns=(by,), height=420)

    elif view == "📋 Recycle List":
        c1, c2, c3, c4 = st.columns(4)
        branch = c1.selectbox("Branch", ["All branches"] + sorted(cust["Branch"].dropna().unique()),
                              key="recycle_branch")
        pick = c2.multiselect("Status", lr.STATUSES, default=[lr.READY], key="recycle_status")
        action = c3.selectbox("Action", ["All actions"] + sorted(cust["Action"].unique()),
                              key="recycle_action")
        per_branch = c4.number_input("Calls per branch", 0, 500, 30, key="recycle_per_branch",
                                     help="Today's list: the top calls for each branch, by priority. "
                                          "0 lists everyone.")
        shown = cust if branch == "All branches" else cust[cust["Branch"] == branch]
        shown = shown[shown["Status"].isin(pick or lr.STATUSES)]
        shown = shown if action == "All actions" else shown[shown["Action"] == action]
        shown = shown.sort_values(["Priority", "Last Touch"], ascending=False)
        if per_branch:
            shown = shown.groupby("Branch", dropna=False).head(int(per_branch))
        if shown.empty:
            st.info("Nobody matches this choice.")
            return
        _kpis([
            ("On the List", f"{len(shown):,}", f"{shown['Branch'].nunique():,} branches"),
            ("Stock Is Back", f"{(shown['Action'] == lr.STOCK_PLAY).sum():,}",
             "asked for a bag that is in now"),
            ("Said They'd Buy", f"{shown['Action'].str.startswith(('Reminder', 'Invite')).sum():,}",
             "purchase later or visit the shop"),
            ("Never Followed Up", f"{(shown['Attempts'] == 0).sum():,}", "first call back"),
        ])
        table = shown.assign(**{
            "Lost On": shown["First Unconverted"].dt.date, "Last Touch": shown["Last Touch"].dt.date,
            "Bag Wanted": shown["Wanted"]})
        cols = ["Priority", "Name", "Contact", "Branch", "Channel", "Source", "Reason", "Follow-up",
                "Bag Wanted", "In Stock Now", "Action", "Status", "Attempts", "Touches",
                "Lost On", "Last Touch", "Days Since Touch"]
        with st.container(border=True):
            st.caption("Highest priority first: why they didn't buy (stock back and said-they'd-buy "
                       "first), whether the bag they want is in, then the freshest — a lead cools "
                       "every week it waits. Work it, record the outcome in the app it came from, "
                       "and the customer moves out of the list.")
            grid.filterable_table(table[cols], pinned_columns=("Name",), height=520)
            st.download_button("⬇️ Download the call list (CSV)", table[cols].to_csv(index=False).encode(),
                               file_name=f"lead_recycling_{today:%Y%m%d}.csv", mime="text/csv",
                               key="recycle_download")

    else:
        st.markdown(f"""
**What gets recycled.** Every customer who got in touch and didn't buy — a WhatsApp chat
that ended as an enquiry, a promise to visit or not purchased; a social DM that didn't
convert; a walk-in lead that isn't Purchased — in the window you pick. One row per
customer, so someone who messaged three times is called once.

**Where each customer stands**, checked in this order:

| Status | Means | Do |
|---|---|---|
| 🟢 {lr.RECOVERED} | Bought a bag on a later day (any shop or online), or a later chat converted | Nothing — counted as recovered |
| ⚪ {lr.DO_NOT} | Lead marked wrong number or not interested | Leave them |
| 🔵 {lr.FRESH} | Touched in the last {after} days | Still with the team that took it |
| 🔵 {lr.SCHEDULED} | A call-back date still to come | Call on the date |
| 🟣 {lr.NURTURE} | {attempts}+ follow-ups and no sale | Offers and broadcasts only, no more calls |
| 🟠 {lr.READY} | Everyone else | On the call list now |

**What to say** follows why they didn't buy:

| Why | Action |
|---|---|
| Out of stock / awaiting stock | If the bag is in now: tell them it's back and where. If not: hold, or offer a similar bag |
| Purchase later / follow up later | Reminder call, with this week's deal |
| Visit shop / will visit | Invite them in: the nearest shop and what's in stock for them |
| Awaiting offer | Send the current Power Deal or Deal of the Week |
| Not purchased | Ask what stopped them; offer an alternative or a deal |
| Enquiry | Answer the open question, then send a deal |
| Not reachable | Try another time, or WhatsApp / SMS instead of a call |

**The weekly routine.**
1. Each morning, each branch takes its top calls from the **Recycle List** (download it as CSV).
2. Record every outcome in the app the lead came from — the WhatsApp Monitor follow-up, the
   Social DMs call status, or the lead's status in Leads. That is what moves the customer
   on: to Scheduled, Nurture Only, Do Not Recycle, or Recovered when they buy.
3. On Sunday, read the **Tracker**: the recovery % for each week's lost customers, which
   reasons recycle best, and **Never Followed Up** by branch, the gap to close.

**How recovery is measured.** A customer is recovered when their phone (last nine digits)
shows a bag bought at any till or online on a day after they were first lost, or a later
chat or lead converted. **After a Follow-up** means a follow-up was recorded before they
bought. Customers who bought the same day they asked were never lost and are left out.
This page reads the apps; it doesn't write to them.
""")

    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")


# ----------------------------------------------------- Hybrid Conversion ---

HYBRID_WINDOWS = {"Same day": 0, "Within 3 days": 3, "Within 7 days": 7, "Within 14 days": 14,
                  "Within 30 days": 30}
BUY_BANDS = [(0, "Same day"), (1, "Next day"), (3, "2–3 days"), (7, "4–7 days"),
             (14, "8–14 days"), (30, "15–30 days")]
CHANNEL_COLORS = {lr.WHATSAPP: theme.CATEGORICAL[1], lr.SOCIAL: theme.CATEGORICAL[2],
                  lr.WALKIN: theme.CATEGORICAL[3]}
# Each direction in its own words: who the customers are, what they did.
HYBRID_WORDS = {
    lr.ONLINE_TO_SHOP: {"who": "Online Customers", "how": "messaged on WhatsApp or a social DM",
                        "did": "Walked In & Bought", "where": "Shop they walked into",
                        "split": "Channel", "credit": "the chat or DM was never marked as converted"},
    lr.SHOP_TO_ONLINE: {"who": "Walk-in Leads", "how": "captured as a walk-in lead at a shop",
                        "did": "Bought Online", "where": "Shop that took the lead, by how they bought",
                        "split": "Bought Via", "credit": "the lead was never marked Purchased"},
}


@st.cache_data(ttl=1800, show_spinner=False)
def _hybrid_data(start: date, end: date, within: int,
                 direction: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(one row per customer who bought the other way, one row per customer
    who got in touch this way in the range) — read from the recycling data,
    so the two share one set of queries."""
    # The Lead Recycling tab's default 90-day load covers most ranges asked
    # for here; reading the same window shares its cache instead of moving
    # the same 40k chats across the network a second time.
    today = date.today()
    pool_start = today - timedelta(days=POOL_WINDOWS["Last 90 days"])
    touches, bought, _ = _recycling_data(min(start, pool_start), today)
    if touches.empty:
        return pd.DataFrame(), pd.DataFrame()
    return (lr.hybrid(touches, bought, start=start, end=end, within=within, direction=direction),
            lr.first_contacts(touches, start, end, direction))


def _hybrid_scorecard(conv: pd.DataFrame, base: pd.DataFrame, by: str, did: str) -> pd.DataFrame:
    g = conv.groupby(by)
    t = pd.DataFrame({
        did: g.size(),
        "Value": g["Amount"].sum().round(0),
        "Bags": g["Bags"].sum(),
        "Same Day": g["Days to Buy"].apply(lambda d: int((d == 0).sum())),
        "Median Days": g["Days to Buy"].median(),
        "Same Branch": g["Same Branch"].sum(),
        "Not Credited in App": g["Credited in App"].apply(lambda s: int((~s).sum())),
    })
    # The rate needs everyone who got in touch in that group, so only for what
    # the contact itself recorded (not for where they ended up buying).
    base_col = {"Channel": "Channel", "Source": "Source", "Contact Branch": "Branch"}.get(by)
    if base_col:
        contacts = base.groupby(base_col).size().rename_axis(by)
        t = t.join(contacts.rename("Customers"), how="outer").fillna(0)
        t.insert(0, "Customers", t.pop("Customers").astype(int))
        t["Conversion %"] = (t[did] / t["Customers"].where(t["Customers"] > 0) * 100).round(1)
    return t.reset_index().sort_values(did, ascending=False)


@st.fragment()
def render_hybrid(start_date: date, end_date: date) -> None:
    """Customers who got in touch one way and bought the other: online chats
    that ended in a shop, and shop walk-ins that ended online."""
    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        direction = st.segmented_control("Direction", lr.DIRECTIONS, default=lr.ONLINE_TO_SHOP,
                                         key="hybrid_direction") or lr.ONLINE_TO_SHOP
    words = HYBRID_WORDS[direction]
    window = c2.selectbox("Bought", list(HYBRID_WINDOWS), index=3, key="hybrid_window",
                          help="How long after their first contact a purchase the other way still "
                               "counts as coming from it.")
    within = HYBRID_WINDOWS[window]
    with st.spinner("Matching customers to their purchases…"):
        conv, base = _hybrid_data(start_date, end_date, within, direction)
    if direction == lr.ONLINE_TO_SHOP:
        channel = c3.selectbox("Channel", ["All channels"] + lr.ONLINE, key="hybrid_channel")
        if channel != "All channels":
            conv = conv[conv["Channel"] == channel] if not conv.empty else conv
            base = base[base["Channel"] == channel] if not base.empty else base
    if base.empty:
        st.info(f"Nobody {words['how']} with a phone number in this date range.")
        return
    if conv.empty:
        st.info(f"None of the {len(base):,} customers {words['how']} in this range bought the "
                f"other way ({window.lower()}).")
        return

    n, total = len(conv), len(base)
    same_day = int((conv["Days to Buy"] == 0).sum())
    uncredited = conv[~conv["Credited in App"]]
    _kpis([
        (words["who"], f"{total:,}", words["how"]),
        (words["did"], f"{n:,}", f"{_pct(n, total)} of them"),
        ("Value", f"KES {conv['Amount'].sum():,.0f}",
         f"{int(conv['Bags'].sum()):,} bags · KES {conv['Amount'].mean():,.0f} each"),
        ("Same Day", f"{same_day:,}", f"{_pct(same_day, n)} · median "
                                      f"{conv['Days to Buy'].median():.0f} days to buy"),
        ("Not Credited in App", f"{len(uncredited):,}",
         f"KES {uncredited['Amount'].sum():,.0f} the app didn't record as a sale"),
    ])
    if direction == lr.ONLINE_TO_SHOP:
        rule = ("then bought a bag at a shop till in person. The website, Jumia, the Staff POS and "
                "shop orders with a delivery fee (sent out, not walked in) don't count.")
    else:
        rule = ("then bought a bag on the website, on Jumia, or as a shop order with a delivery fee "
                "(sent out to them).")
    st.caption(f"Customers (matched on the last nine digits of the phone) first {words['how']} "
               f"between {start_date:%d %b} and {end_date:%d %b %Y}, {rule} Counted "
               f"{window.lower()} of that first contact; only their first such purchase. "
               f"**Not Credited in App** = {words['credit']}, though the customer did buy.")

    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        split = words["split"]
        rows = "Bought At" if direction == lr.ONLINE_TO_SHOP else "Contact Branch"
        pivot = conv.pivot_table(index=rows, columns=split, values="Phone Key",
                                 aggfunc="count", fill_value=0)
        pivot = pivot.loc[pivot.sum(axis=1).sort_values().index]
        keys = list(pivot.columns)
        others = [k for k in keys if k not in CHANNEL_COLORS]
        palette = {**CHANNEL_COLORS, **dict(zip(others, charts.colors_for(others)))}
        fig = go.Figure()
        for k in keys:
            fig.add_bar(y=pivot.index, x=pivot[k], orientation="h", name=k,
                        marker=dict(color=palette[k]),
                        hovertemplate=f"<b>%{{y}}</b><br>{k}: <b>%{{x:,.0f}}</b><extra></extra>")
        for shop, count in pivot.sum(axis=1).items():
            fig.add_annotation(x=count, y=shop, text=f"<b>{count:,.0f}</b>", showarrow=False,
                               xanchor="left", xshift=6, font=dict(color=theme.TEXT_PRIMARY, size=11))
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title=words["where"], barmode="stack", hovermode="closest",
                          legend_traceorder="normal", height=max(380, 28 * len(pivot) + 100))
        fig.update_xaxes(showgrid=True, gridcolor=theme.GRIDLINE)
        theme.show(fig)
    with c2, st.container(border=True):
        bands = [(d, label) for d, label in BUY_BANDS if d <= max(within, 0)]
        band = pd.cut(conv["Days to Buy"], [-1] + [d for d, _ in bands],
                      labels=[label for _, label in bands])
        counts = band.value_counts().reindex([label for _, label in bands], fill_value=0)
        fig = go.Figure(go.Bar(
            x=counts.index.astype(str), y=counts.values,
            marker=dict(color=theme.CATEGORICAL[0], cornerradius=4),
            text=[f"{v:,}" for v in counts.values], textposition="outside", cliponaxis=False,
            customdata=(counts / n * 100).round(1),
            hovertemplate="%{x}: <b>%{y:,}</b> (%{customdata:.1f}%)<extra></extra>"))
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="Time from first contact to purchase", height=380)
        fig.update_yaxes(showgrid=True, gridcolor=theme.GRIDLINE)
        theme.show(fig)

    with st.container(border=True):
        weeks = (base.assign(Week=base["Date"].dt.to_period("W-SAT").dt.start_time)
                 .groupby("Week").size().rename("Contacts"))
        came = (conv.assign(Week=conv["First Contact"].dt.to_period("W-SAT").dt.start_time)
                .groupby("Week").agg(Converted=("Phone Key", "size"), Value=("Amount", "sum")))
        weekly = pd.concat([weeks, came], axis=1).fillna(0)
        fig = go.Figure()
        fig.add_bar(x=weekly.index, y=weekly["Converted"], name=words["did"],
                    marker=dict(color=theme.CATEGORICAL[1], cornerradius=4),
                    customdata=weekly[["Contacts", "Value"]],
                    hovertemplate=("Week of %{x|%d %b}<br><b>%{y:,.0f}</b> of %{customdata[0]:,.0f} "
                                   "customers<br>KES %{customdata[1]:,.0f}<extra></extra>"))
        fig.add_scatter(x=weekly.index,
                        y=(weekly["Converted"] / weekly["Contacts"].where(weekly["Contacts"] > 0)
                           * 100).round(1),
                        name="Conversion %", yaxis="y2", mode="lines+markers",
                        line=dict(color=theme.TEXT_PRIMARY, width=2),
                        hovertemplate="Conversion: <b>%{y:.1f}%</b><extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title=f"{direction}, by the week of first contact (Sun–Sat)", height=380,
                          yaxis2=dict(overlaying="y", side="right", ticksuffix="%", showgrid=False,
                                      rangemode="tozero", tickfont=dict(color=theme.TEXT_MUTED)))
        fig.update_xaxes(tickformat="%d %b")
        theme.show(fig)

    with st.container(border=True):
        options = ["Contact Branch", "Bought At", "Bought Via", "Channel", "Source"]
        by = st.segmented_control("Scorecard by", options, default="Contact Branch",
                                  key="hybrid_by") or "Contact Branch"
        st.caption("**Contact Branch** is the branch that took the chat, DM or lead; **Bought At** "
                   "where the sale was rung. **Same Branch** = bought at (or delivered from) the "
                   "branch that took the contact. Conversion % is only shown for what the contact "
                   "recorded, against everyone who got in touch.")
        grid.filterable_table(_hybrid_scorecard(conv, base, by, words["did"]),
                              currency_columns=("Value",), pinned_columns=(by,), height=420)

    with st.container(border=True):
        only = st.toggle("Only those not credited in the app", key="hybrid_uncredited")
        shown = uncredited if only else conv
        table = shown.assign(**{"First Contact": shown["First Contact"].dt.date,
                                "Bought On": shown["Bought On"].dt.date,
                                "Credited in App": shown["Credited in App"].map({True: "Yes", False: "No"})})
        cols = ["Name", "Contact", "Channel", "Source", "Contact Branch", "First Contact", "Touches",
                "Outcome Recorded", "Bag Asked For", "Credited in App", "Bought On", "Bought At",
                "Bought Via", "Days to Buy", "Bags", "Amount"]
        st.caption(f"{len(table):,} customers, latest purchase first.")
        grid.filterable_table(table[cols], currency_columns=("Amount",), pinned_columns=("Name",),
                              height=480)
        slug = "online_to_walkin" if direction == lr.ONLINE_TO_SHOP else "walkin_to_online"
        st.download_button("⬇️ Download (CSV)", table[cols].to_csv(index=False).encode(),
                           file_name=f"{slug}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.csv",
                           mime="text/csv", key="hybrid_download")
    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')}")


app_view = _section(["💬 WhatsApp Monitor", "📱 Social DMs", "🚶 Leads", "📭 Out of Stock",
                     "🔀 Hybrid Conversion", "♻️ Lead Recycling"], "engagement_app")
if app_view == "💬 WhatsApp Monitor":
    render_whatsapp(start_date, end_date)
elif app_view == "📱 Social DMs":
    render_social(start_date, end_date)
elif app_view == "🚶 Leads":
    render_leads(start_date, end_date)
elif app_view == "📭 Out of Stock":
    render_out_of_stock(start_date, end_date)
elif app_view == "🔀 Hybrid Conversion":
    render_hybrid(start_date, end_date)
else:
    render_recycling()
