"""WhatsApp & Social DMs — the WhatsApp Monitor, Social DMs and walk-in Leads
apps, side by side.

Three apps, one page, kept apart: each has its own tab with its own touchpoints
and its own numbers, because a WhatsApp interaction and an Instagram DM are
logged differently and convert through different routes.
"""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, charts, db, filters, grid, queries, stock_planning, theme

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
LEADS_COLUMNS = {"Date": "DATE", "Reference": "REF", "Name": "NAME", "Contact": "CONTACT",
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
    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')} · leads captured in the "
               "Leads module (walk-in, call and WhatsApp), by the date they were captured.")


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
                        hovertemplate=f"<b>%{{y}}</b><br>{name}: <b>%{{x:,.0f}}</b><extra></extra>")
        theme.apply_layout(fig, show_legend=True)
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


app_view = _section(["💬 WhatsApp Monitor", "📱 Social DMs", "🚶 Leads", "📭 Out of Stock"],
                    "engagement_app")
if app_view == "💬 WhatsApp Monitor":
    render_whatsapp(start_date, end_date)
elif app_view == "📱 Social DMs":
    render_social(start_date, end_date)
elif app_view == "🚶 Leads":
    render_leads(start_date, end_date)
else:
    render_out_of_stock(start_date, end_date)
