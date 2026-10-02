"""Shop Attendants — who served and who ran the till, for every POS session."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, filters, grid, queries, theme

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

    if person == ALL_PEOPLE:
        _by_person_chart(shown)

    with st.container(border=True):
        st.caption(f"{len(shown):,} rows · click a column header's filter icon to search or "
                   "narrow it.")
        grid.filterable_table(shown[COLUMNS], currency_columns=("Sales Made",), height=440)

    if person != ALL_PEOPLE:
        _person_sales(person, start_date, end_date, location)


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


render_attendants(start_date, end_date)
