"""Shop Attendants — who served and who ran the till, for every POS session."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, feedback, filters, grid, queries, scorecards, targets, theme

st.set_page_config(page_title="Shop Attendants · Denri Executive Dashboard",
                   page_icon="🧑‍💼", layout="wide")

auth.require_login()

st.title("🧑‍💼 Shop Attendants")
st.caption("Every POS session with its shop attendants, brand ambassadors and cashier — "
           "live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_refresh = st.columns([3, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("attendants", default="Yesterday")
with col_refresh:
    db.refresh_button(key="attendants_refresh")

# The headers asked for, in the order asked, with the brand ambassador beside the
# attendant; Session and Orders follow so a row can be traced back in Odoo.
COLUMNS = ["Date", "Location", "Sales Made", "Shop Attendant", "Brand Ambassador (BA)",
           "Cashier", "Session", "Orders"]
NOT_RECORDED = "Not recorded"
BA_SUFFIX = " (BA)"
ALL_PEOPLE = "All Shop Attendants & BAs"


def _served_by(df: pd.DataFrame) -> pd.Series:
    """Who made each row's sales: the attendant, or the BA labelled as one.

    An order carries one or the other, never both.
    """
    ba = df["Brand Ambassador (BA)"].fillna("")
    return df["Shop Attendant"].where(ba == "", ba + BA_SUFFIX)


@st.fragment()
def render_attendants(start_date: date, end_date: date) -> None:
    df = db.run_query(queries.SHOP_ATTENDANT_SESSIONS,
                      {"start_date": start_date, "end_date": end_date})
    if df.empty:
        st.info("No POS sessions with sales in this date range.")
        return
    df = df.assign(**{"Served By": _served_by(df)})

    col_loc, col_person = st.columns(2)
    with col_loc:
        location = st.selectbox("Location", ["All Locations"] + sorted(df["Location"].unique()),
                                key="attendants_location")
    shown = df if location == "All Locations" else df[df["Location"] == location]
    with col_person:
        people = sorted(p for p in shown["Served By"].unique() if p != NOT_RECORDED)
        person = st.selectbox("Shop Attendant / BA", [ALL_PEOPLE] + people,
                              key="attendants_person")
    shown = shown if person == ALL_PEOPLE else shown[shown["Served By"] == person]

    unrecorded = shown[shown["Served By"] == NOT_RECORDED]
    bas = shown[shown["Brand Ambassador (BA)"] != ""]
    items = [
        ("Sales Made", f"KES {shown['Sales Made'].sum():,.0f}", None),
        ("POS Sessions", f"{shown['Session'].nunique():,}", f"{shown['Location'].nunique()} locations"),
        ("Attendants & BAs", f"{len(set(shown['Served By']) - {NOT_RECORDED}):,}",
         f"{bas['Brand Ambassador (BA)'].nunique()} BAs, KES {bas['Sales Made'].sum():,.0f}"),
        ("Nobody Recorded", f"KES {unrecorded['Sales Made'].sum():,.0f}",
         f"{int(unrecorded['Orders'].sum()):,} orders"),
    ]
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")

    st.caption(
        f"Last updated {datetime.now().strftime('%H:%M:%S')} · one row per session for each "
        "shop attendant or brand ambassador who served in it — an order carries one or the "
        "other. Cashier is the person who opened the session in Odoo; Sales Made is counted "
        "like the Sales page (delivery fees out, refunds netted, in KES)."
    )

    # One section at a time: the feedback section reads the Google Sheet and
    # every converted customer, which is slow, so it only runs when opened.
    sections = ["Sessions", "Score Cards", "Customer Feedback"]
    if person != ALL_PEOPLE:
        sections.insert(1, "Sales Breakdown")
    section = st.segmented_control("Section", sections, default=sections[0],
                                   key="attendants_section", label_visibility="collapsed")
    section = section if section in sections else sections[0]

    if section == "Sessions":
        if person == ALL_PEOPLE:
            _by_person_chart(shown)
        with st.container(border=True):
            st.caption(f"{len(shown):,} rows · click a column header's filter icon to search or "
                       "narrow it. The last row is the total for the range.")
            sessions = shown[COLUMNS].copy()
            total = {c: "" for c in COLUMNS}
            total.update({"Date": "TOTAL", "Sales Made": round(sessions["Sales Made"].sum(), 2),
                          "Session": f"{shown['Session'].nunique():,} sessions",
                          "Orders": int(sessions["Orders"].sum())})
            grid.filterable_table(pd.concat([sessions, pd.DataFrame([total])], ignore_index=True),
                                  currency_columns=("Sales Made",), height=440)

        st.subheader("By Shop Attendant / BA")
        with st.container(border=True):
            st.caption("Each attendant's and BA's sales for the whole range, highest first, "
                       "with the total at the bottom.")
            per = (shown.groupby("Served By", as_index=False)
                   .agg(Locations=("Location", lambda v: ", ".join(sorted(set(v)))),
                        Sessions=("Session", "nunique"), Orders=("Orders", "sum"),
                        **{"Sales Made": ("Sales Made", "sum")})
                   .rename(columns={"Served By": "Shop Attendant / BA"})
                   .sort_values("Sales Made", ascending=False))
            per["Share %"] = (per["Sales Made"] / per["Sales Made"].sum() * 100).round(1)
            per["Avg Sale"] = (per["Sales Made"] / per["Orders"].where(per["Orders"] > 0)).round(0)
            per["Sales Made"] = per["Sales Made"].round(2)
            total = {"Shop Attendant / BA": "TOTAL",
                     "Locations": f"{shown['Location'].nunique()} locations",
                     "Sessions": shown["Session"].nunique(), "Orders": int(per["Orders"].sum()),
                     "Sales Made": round(per["Sales Made"].sum(), 2), "Share %": 100.0,
                     "Avg Sale": round(per["Sales Made"].sum() / max(per["Orders"].sum(), 1), 0)}
            grid.filterable_table(pd.concat([per, pd.DataFrame([total])], ignore_index=True),
                                  currency_columns=("Sales Made", "Avg Sale"),
                                  pinned_columns=("Shop Attendant / BA",), height=440)
    elif section == "Score Cards":
        _score_cards(start_date, end_date, location, person)
    elif section == "Sales Breakdown":
        _person_sales(person, start_date, end_date, location)
    else:
        _feedback_table(start_date, end_date, location, person)


def _by_person_chart(shown: pd.DataFrame) -> None:
    by_person = (shown[shown["Served By"] != NOT_RECORDED]
                 .groupby("Served By", as_index=False)
                 .agg(Sales=("Sales Made", "sum"), Orders=("Orders", "sum"),
                      Sessions=("Session", "nunique"))
                 .sort_values("Sales", ascending=True))
    if by_person.empty:
        return
    top = by_person.tail(20)
    with st.container(border=True):
        fig = go.Figure()
        fig.add_bar(
            y=top["Served By"], x=top["Sales"], orientation="h",
            marker=dict(color=theme.sequential_colors(len(top)), cornerradius=4),
            customdata=top[["Orders", "Sessions"]],
            hovertemplate=("<b>%{y}</b><br>KES %{x:,.0f}<br>%{customdata[0]:,} orders"
                           " · %{customdata[1]:,} sessions<extra></extra>"),
        )
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="Sales Made by Shop Attendant / BA", hovermode="closest",
                          height=max(360, 28 * len(top) + 80))
        fig.update_xaxes(showgrid=True, gridcolor=theme.GRIDLINE)
        fig.update_yaxes(showgrid=False)
        theme.show(fig)


def _feedback_table(start_date: date, end_date: date, location: str, person: str) -> None:
    """How many of each person's converted customers then left feedback."""
    st.subheader("Customer Feedback by Shop Attendant / BA")
    try:
        responses = feedback.load()
    except feedback.FeedbackUnavailable as exc:
        st.warning(
            f"{exc} The feedback lives in the Google Sheet the POS Request Hub reads "
            f"(\"{feedback.WORKSHEET}\" tab). Share that sheet with "
            f"**{feedback.service_account_email()}** as a Viewer and this table fills in "
            "on the next refresh.",
            icon="🔒",
        )
        return

    customers = db.run_query(queries.SHOP_ATTENDANT_CUSTOMERS,
                             {"start_date": start_date, "end_date": end_date})
    if location != "All Locations":
        customers = customers[customers["Location"] == location]
    if person != ALL_PEOPLE:
        customers = customers[customers["Served By"] == person]
    customers = customers[customers["Served By"] != NOT_RECORDED]
    if customers.empty:
        st.info("No converted customers in this range.")
        return

    # Feedback counts if it came in during the range, on or after the day the
    # customer bought — feedback given before the purchase is about an earlier
    # visit, not this attendant's sale.
    window = responses[(responses["Submitted"].dt.date >= start_date)
                       & (responses["Submitted"].dt.date <= end_date)
                       & responses["Phone Key"].notna()]
    first_feedback = window.groupby("Phone Key")["Submitted"].min()

    # One customer per person, however many shops or orders they bought across.
    per_customer = (customers.assign(Key=customers["Phone Key"].fillna(
                        "name:" + customers["Customer"]))
                    .groupby(["Served By", "Key"], as_index=False)
                    .agg(Customer=("Customer", "first"), Phone=("Phone", "first"),
                         Locations=("Location", lambda v: ", ".join(sorted(set(v)))),
                         Bought=("First Purchase", "min"), Orders=("Orders", "sum")))
    fed = per_customer["Key"].map(first_feedback)
    per_customer["Feedback On"] = fed.dt.date
    per_customer["Gave Feedback"] = fed.notna() & (fed.dt.date >= pd.to_datetime(per_customer["Bought"]).dt.date)

    table = (per_customer.groupby("Served By")
             .agg(Location=("Locations", lambda v: ", ".join(sorted({x for s in v for x in s.split(", ")}))),
                  **{"Customers Converted": ("Key", "size"),
                     "Gave Feedback": ("Gave Feedback", "sum")})
             .reset_index().rename(columns={"Served By": "Shop Attendant / BA"}))
    table["Feedback Rate"] = (table["Gave Feedback"] / table["Customers Converted"] * 100).round(1)
    table = table.sort_values(["Feedback Rate", "Customers Converted"], ascending=[False, False])

    converted, gave = int(table["Customers Converted"].sum()), int(table["Gave Feedback"].sum())
    items = [
        ("Customers Converted", f"{converted:,}", None),
        ("Gave Feedback", f"{gave:,}", f"{gave / converted * 100:.1f}% of converted" if converted else None),
        ("Feedback Received", f"{len(window):,}", "all responses in this range"),
    ]
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")
    st.caption(
        "A converted customer counts as giving feedback when a response with their phone "
        "number (matched on the last nine digits) came in during this range, on or after the "
        "day they bought. Each customer counts once per attendant or BA, however many orders "
        "they placed."
    )
    with st.container(border=True):
        grid.filterable_table(table, pinned_columns=("Shop Attendant / BA",), height=420)

    if person != ALL_PEOPLE:
        # A section, not an expander: the grid draws inside an iframe, and in a
        # collapsed expander it sizes itself to nothing and stays blank when
        # the expander is opened.
        st.markdown(f"**{person}'s customers and their feedback**")
        detail = per_customer[["Customer", "Phone", "Locations", "Bought", "Orders",
                               "Gave Feedback", "Feedback On"]].copy()
        detail["Gave Feedback"] = detail["Gave Feedback"].map({True: "Yes", False: "No"})
        with st.container(border=True):
            grid.filterable_table(detail.sort_values(["Gave Feedback", "Bought"],
                                                     ascending=[False, False]),
                                  pinned_columns=("Customer",), height=420)


def _person_sales(person: str, start_date: date, end_date: date, location: str) -> None:
    """Everything one attendant or BA sold: customer, number and products."""
    name = person[: -len(BA_SUFFIX)] if person.endswith(BA_SUFFIX) else person
    st.subheader(f"Sales by {person}")
    sales = db.run_query(queries.SHOP_ATTENDANT_SALES,
                         {"start_date": start_date, "end_date": end_date, "person": name})
    if location != "All Locations":
        sales = sales[sales["Location"] == location]
    if sales.empty:
        st.info("No product sales recorded for this person in this range.")
        return

    orders = {o.strip() for refs in sales["Orders"] for o in str(refs).split(",")}
    named = sales[sales["Customer"] != "Walk-in (no name)"]
    items = [
        ("Sales Converted", f"{len(orders):,}", "orders"),
        ("Customers", f"{named['Customer'].nunique():,}",
         f"{len(sales) - len(named):,} lines with no customer name"),
        ("Units Sold", f"{sales['Quantity'].sum():,.0f}", None),
        ("Value", f"KES {sales['Total'].sum():,.0f}", None),
    ]
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")

    st.caption(
        "One line per customer and product each day — several units of the same bag read as "
        "one line with its quantity. A combo shows as its own line with the price, beside the "
        "bags inside it at no charge. Refunded items are netted out; delivery fees and order "
        "discounts are not products, so they are left out."
    )
    with st.container(border=True):
        grid.filterable_table(
            sales[["Date", "Customer", "Phone", "Product", "Quantity", "Total", "Location",
                   "Orders"]],
            currency_columns=("Total",), pinned_columns=("Customer",), height=480)


def _card(title: str, row: pd.Series, items: list[tuple[str, str, str | None]]) -> None:
    """One score card: the cumulative score, the measures, then each
    measure's own score."""
    with st.container(border=True):
        badge = "—" if pd.isna(row["Score"]) else f"{row['Score']:.0f}/100"
        st.markdown(f"**{title}** &nbsp; · &nbsp; Cumulative score **{badge}**")
        for start in range(0, len(items), 4):
            for col, (label, value, note) in zip(st.columns(4), items[start:start + 4]):
                col.metric(label, value, note, delta_color="off")
        parts = [f"{name.replace(' Score', '')} **{row[name]:.0f}**"
                 for name in scorecards.SCORE_COLUMNS if pd.notna(row[name])]
        st.caption("Scores out of 100 — " + " · ".join(parts))


def _money(v) -> str:
    return "—" if pd.isna(v) else f"KES {v:,.0f}"


def _pct(v) -> str:
    return "—" if pd.isna(v) else f"{v:.1f}%"


SCORE_COLORS = dict(zip(scorecards.SCORE_COLUMNS, [theme.CATEGORICAL[i] for i in (0, 1, 3, 4, 6, 5)]))


def _cumulative_chart(table: pd.DataFrame, name: str, title: str) -> None:
    """The cumulative score card: each bar is the cumulative score, split
    into what each measure adds to it."""
    ranked = table.dropna(subset=["Score"]).sort_values("Score").tail(30)
    if ranked.empty:
        return
    n = len(scorecards.SCORE_COLUMNS)
    fig = go.Figure()
    for column in scorecards.SCORE_COLUMNS:
        part = ranked[column].fillna(0) / ranked[scorecards.SCORE_COLUMNS].notna().sum(axis=1)
        fig.add_bar(y=ranked[name], x=part, orientation="h",
                    name=column.replace(" Score", ""),
                    marker=dict(color=SCORE_COLORS[column],
                                line=dict(color=theme.CHART_SURFACE, width=1)),
                    customdata=ranked[[column]],
                    hovertemplate=(f"<b>%{{y}}</b><br>{column}: <b>%{{customdata[0]:.0f}}</b>/100"
                                   "<extra></extra>"))
    for label, score in zip(ranked[name], ranked["Score"]):
        fig.add_annotation(x=score, y=label, text=f"<b>{score:.0f}</b>", showarrow=False,
                           xanchor="left", xshift=6, font=dict(color=theme.TEXT_PRIMARY, size=11))
    theme.apply_layout(fig, show_legend=True)
    fig.update_layout(title=title, barmode="stack", hovermode="closest",
                      legend_traceorder="normal", height=max(400, 28 * len(ranked) + 110))
    fig.update_xaxes(range=[0, 108], showgrid=True, gridcolor=theme.GRIDLINE)
    with st.container(border=True):
        theme.show(fig)
        st.caption(f"Each bar is the cumulative score (the average of the {n} measure scores); "
                   "the coloured parts show how much each measure adds to it.")


def _score_cards(start_date: date, end_date: date, location: str, person: str) -> None:
    orders = db.run_query(queries.SCORECARD_ORDERS,
                          {"start_date": start_date, "end_date": end_date})
    if orders.empty:
        st.info("No sales in this date range.")
        return
    # The same number of days just before, for retention: 8-14 Oct is set
    # against 1-7 Oct, October 1-11 against 20-30 September.
    days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    prev_orders = db.run_query(queries.SCORECARD_ORDERS,
                               {"start_date": prev_start, "end_date": prev_end})
    not_customers = scorecards.placeholders(orders, prev_orders)
    df = scorecards.prepare(orders, not_customers)
    previous = scorecards.prepare(prev_orders, not_customers)
    try:
        responses = feedback.load()
        feedback_note = None
    except feedback.FeedbackUnavailable as exc:
        responses, feedback_note = None, str(exc)
    df["Feedback"] = scorecards.gave_feedback(df, responses)
    rows = db.run_query(queries.SALES_TARGET_ROWS,
                        {"start_date": start_date, "end_date": end_date})
    basis = targets.basis_for(start_date, end_date, rows)
    basket = f"KES {scorecards.BASKET_TARGET:,}"
    due = f"{basis.expected * 100:.0f}% due by now"

    view = st.segmented_control("Score cards", ["🏪 Shop Score Cards", "🧑‍💼 Attendant Score Cards"],
                                default="🏪 Shop Score Cards", key="score_view",
                                label_visibility="collapsed") or "🏪 Shop Score Cards"
    st.caption(
        "Every measure is scored out of 100 and the **cumulative score** is their average. "
        f"**Revenue** is scored against the part of the target due by now ({basis.label}; "
        f"{due}) and **basket value** against {basket} for every shop and attendant — 100 "
        f"means on target. **Feedback** is scored against {scorecards.FEEDBACK_TARGET}% of the "
        f"customers served sending a form ({scorecards.FEEDBACK_TARGET}% or more scores 100). Basket size, repeat "
        "purchase and retention have no target, so they are scored by rank: 100 is the best "
        "shop (or attendant). Customers are unique people, known by phone "
        "number. **Repeat Purchase** is the share of the period's customers who bought on two "
        "or more different days in it. **Retention** is the share of the previous period's "
        f"customers ({prev_start:%d %b} – {prev_end:%d %b}, the same number of days) who bought "
        "again in this one, at the same shop. **Feedback** is the share who sent a feedback "
        "form on or after the day they bought. Shop phone numbers typed in for customers who "
        "gave none are not counted as customers.")
    if feedback_note:
        st.warning(f"Feedback is left out: {feedback_note}", icon="🔒")

    if view == "🏪 Shop Score Cards":
        shops = scorecards.shop_cards(df, previous, basis.targets, basis.expected)
        shown = shops if location == "All Locations" else shops[shops["Location"] == location]
        _cumulative_chart(shown, "Location", "Cumulative Score Card — Shops")
        for _, r in shown.iterrows():
            _card(r["Location"], r, [
                ("Revenue", _money(r["Revenue"]),
                 f"{_pct(r['Target %'])} of {_money(r['Target'])} ({due})"
                 if pd.notna(r["Target %"]) else "no target"),
                ("Corporate Revenue", _money(r["Corporate Revenue"]),
                 _pct(r["Corporate Revenue"] / r["Revenue"] * 100) + " of revenue"
                 if r["Revenue"] else None),
                ("Basket Value", _money(r["Basket Value"]),
                 f"{_pct(r['Basket Value %'])} of {basket}"),
                ("Basket Size", f"{r['Basket Size']:.2f} bags", f"{int(r['Orders']):,} orders"),
                ("Revenue per Attendant", _money(r["Revenue per Attendant"]),
                 f"{int(r['Attendants'])} attendants/BAs"),
                ("Repeat Purchase", _pct(r["Repeat %"]),
                 f"of {r['Customers']:,.0f} customers" if pd.notna(r["Customers"]) else None),
                ("Retention", _pct(r["Retention %"]),
                 f"{r['Retained']:,.0f} of {r['Previous Customers']:,.0f} came back"
                 if pd.notna(r["Previous Customers"]) else None),
                ("Feedback", _pct(r["Feedback %"]),
                 f"{r['Feedback']:,.0f} customers · target {scorecards.FEEDBACK_TARGET}%"
                 if pd.notna(r["Feedback"]) else None),
            ])
        with st.container(border=True):
            st.caption("All shops side by side, best cumulative score first, with each measure's "
                       "score and the total at the bottom.")
            cols = (["Location", "Score"] + scorecards.SCORE_COLUMNS
                    + ["Revenue", "Target", "Target %", "Pace %", "Corporate Revenue", "Orders",
                       "Basket Value", "Basket Value %", "Bags", "Basket Size", "Attendants",
                       "Revenue per Attendant", "Customers", "Repeat %", "Previous Customers",
                       "Retained", "Retention %", "Feedback", "Feedback %"])
            grid.filterable_table(shops[cols], pinned_columns=("Location",),
                                  currency_columns=("Revenue", "Target", "Corporate Revenue",
                                                    "Basket Value", "Revenue per Attendant"),
                                  height=460)
        return

    people = scorecards.attendant_cards(df, previous, basis.targets, basis.expected)
    if location != "All Locations":
        people = people[people["Location"] == location]
    st.caption(
        "**Revenue** shares each shop's daily revenue equally between everyone who served "
        "there that day (attendants and BAs recorded on its orders). **Revenue target** is the "
        "shop's target for the period divided by the attendants and BAs who served there in "
        "it. **Own Sales**, basket value and basket size are from the orders the person served "
        "themselves.")
    if people.empty:
        st.info("No attendants or BAs recorded in this range.")
        return
    people = people.assign(Name=people["Attendant / BA"] + " — " + people["Location"])
    chosen = people if person == ALL_PEOPLE else people[people["Attendant / BA"] == person]
    _cumulative_chart(chosen, "Name", "Cumulative Score Card — Attendants & BAs")
    for _, r in chosen.head(12).iterrows():
        peers = people[people["Location"] == r["Location"]]
        vs = lambda c, fmt: f"shop avg {fmt(peers[c].mean())}"
        _card(r["Name"], r, [
            ("Revenue (shared)", _money(r["Revenue"]),
             f"{_pct(r['Target %'])} of {_money(r['Target'])} ({due})"
             if pd.notna(r["Target %"]) else "no target"),
            ("Revenue per Day", _money(r["Revenue per Day"]),
             f"{int(r['Days Worked'])} days worked"),
            ("Own Sales", _money(r["Own Sales"]), f"{int(r['Orders']):,} orders served"),
            ("Corporate Revenue", _money(r["Corporate Revenue"]), None),
            ("Basket Value", _money(r["Basket Value"]),
             f"{_pct(r['Basket Value %'])} of {basket}"),
            ("Basket Size", f"{r['Basket Size']:.2f} bags",
             vs("Basket Size", lambda v: f"{v:.2f}")),
            ("Repeat Purchase", _pct(r["Repeat %"]), vs("Repeat %", _pct)),
            ("Retention", _pct(r["Retention %"]),
             f"{r['Retained']:,.0f} of {r['Previous Customers']:,.0f} came back"
             if pd.notna(r["Previous Customers"]) else "no customers last period"),
            ("Feedback", _pct(r["Feedback %"]),
             f"{r['Feedback']:,.0f} customers · target {scorecards.FEEDBACK_TARGET}%"
             if pd.notna(r["Feedback"]) else None),
        ])
    if person == ALL_PEOPLE and len(people) > 12:
        st.caption(f"The 12 best cumulative scores are shown as cards; all {len(people)} are in "
                   "the table. Pick a person at the top to see their card.")
    with st.container(border=True):
        cols = (["Attendant / BA", "Location", "Score"] + scorecards.SCORE_COLUMNS
                + ["Team Size", "Target", "Revenue", "Target %", "Pace %", "Days Worked", "Revenue per Day",
                   "Own Sales", "Orders", "Corporate Revenue", "Basket Value", "Basket Value %",
                   "Bags", "Basket Size", "Customers", "Repeat %", "Previous Customers",
                   "Retained", "Retention %", "Feedback", "Feedback %"])
        grid.filterable_table(people[cols], pinned_columns=("Attendant / BA",),
                              currency_columns=("Target", "Revenue", "Revenue per Day",
                                                "Own Sales", "Corporate Revenue", "Basket Value"),
                              height=460)


render_attendants(start_date, end_date)
