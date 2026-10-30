"""Customer Sales — who's buying, what they're buying, and where."""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, charts, db, filters, gender, grid, names, phones, queries, theme

st.set_page_config(page_title="Customers · Denri Executive Dashboard", page_icon="🧑‍🤝‍🧑", layout="wide")

auth.require_login()

st.title("🧑‍🤝‍🧑 Customer Sales")
st.caption("Customer-level transactions — revenue, gender split, and top spenders, live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_refresh = st.columns([3, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("customers")

MAX_TABLE_ROWS = 5000
GENDER_COLORS = {
    "Male": theme.CATEGORICAL[0],
    "Female": theme.CATEGORICAL[2],
    "Corporate": theme.CATEGORICAL[3],
}


@st.fragment()
def render_customers(start_date: date, end_date: date) -> None:
    with col_refresh:
        db.refresh_button(key="customers_refresh")

    df = db.run_query(
        queries.CUSTOMER_SALES,
        {"start_date": start_date, "end_date": end_date},
    )

    if df.empty:
        st.info("No customer transactions for this date range yet.")
        return

    # Gender comes straight from the system (staff have entered it directly
    # since 2026-07-22). For records with nothing recorded, fall back to the
    # name-based lookup as before; where something IS recorded, cross-check it
    # against the name-based lookup to catch likely data-entry errors.
    # Payment notes and banks typed into the name ("Ali(KCB)", "Anne -PDQ"),
    # and names that only appear in brackets ("KCB (Emily)"), sorted out here.
    df["Name"] = df["Raw Name"].map(names.clean)
    # Sales whose customer record holds no name at all — only a bank or payment
    # note ("KCB", "Co-op", "I&M", "Stanbic") or nothing. Listed at the bottom
    # of the page so they can be put right in Odoo before an export.
    to_fix = df[df["Name"] == "N/A"].copy()
    df = df.drop(columns=["Raw Name"])
    df["First Name"] = df["Name"].str.split().str[0].fillna("")
    # Slips at the till ("Meercy", "Briyan") corrected first, so the gender
    # check below reads the real name. Then a gender recorded against an
    # obvious name ("John" as Female) is corrected for the dashboard; both
    # are listed at the bottom of the page to put right in Odoo.
    df, misspelt = names.fix_spelling(df)
    mismatches = gender.find_mismatches(df)
    df = gender.correct_recorded(df).drop(columns=["Recorded Gender"])
    df = gender.apply_gender_fallback(df)

    total_revenue = df["Total"].sum()
    # Phone, not cleaned first Name, is the reliable identity key — many different
    # customers share a first name only (e.g. several distinct "Caroline"s with
    # different phone numbers), which undercounts if grouped by Name alone.
    identified = df[df["Phone"] != "N/A"]
    unique_customers = identified["Phone"].nunique()
    avg_spend = (total_revenue / unique_customers) if unique_customers else 0.0
    gender_known = (df["Gender"] != "N/A").sum()
    pct_identified = (gender_known / len(df) * 100) if len(df) else 0.0

    k1, k2, k3, k4 = st.columns(4)
    with k1.container(border=True):
        st.metric("Revenue", f"KES {total_revenue:,.0f}")
    with k2.container(border=True):
        st.metric("Unique Customers", f"{unique_customers:,}")
    with k3.container(border=True):
        st.metric("Avg Spend / Customer", f"KES {avg_spend:,.0f}")
    with k4.container(border=True):
        st.metric(
            "Gender Identified", f"{pct_identified:,.1f}%",
            help="Recorded directly by staff since 2026-07-22; older/blank records "
                 "fall back to a name-based guess.",
        )

    st.caption(f"Last updated {datetime.now().strftime('%H:%M:%S')} · {len(df):,} line items")

    unmapped = gender.top_unmapped_names(df)
    if not unmapped.empty:
        with st.expander(f"{len(unmapped)} first names still unresolved (most frequent shown) — tell me new ones to add"):
            st.dataframe(
                unmapped.rename("Occurrences").rename_axis("First Name").reset_index(),
                width="stretch",
                hide_index=True,
            )

    df = df.drop(columns=["First Name"])  # internal-only, used above for gender matching

    locations = sorted(df["Location"].dropna().unique())
    selected_location = st.selectbox("Location", ["All Locations"] + locations, key="customers_location_filter")
    filtered = df if selected_location == "All Locations" else df[df["Location"] == selected_location]

    col_gender, col_top = st.columns([1, 2])

    with col_gender:
        with st.container(border=True):
            # Corporate orders carry "Corporate" as their gender in Odoo.
            gender_counts = filtered["Gender"].value_counts().reindex(list(GENDER_COLORS)).fillna(0)
            gender_pct = (gender_counts / gender_counts.sum() * 100) if gender_counts.sum() else gender_counts
            fig = go.Figure()
            fig.add_bar(
                x=gender_counts.index, y=gender_counts.values,
                text=[f"{v:,.0f} ({p:.0f}%)" for v, p in zip(gender_counts.values, gender_pct.values)],
                textposition="outside",
                marker=dict(
                    color=[GENDER_COLORS[g] for g in gender_counts.index],
                    cornerradius=4,
                ),
            )
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(title="Customers by Gender", height=360)
            theme.show(fig, width="stretch")

    with col_top:
        with st.container(border=True):
            # Group by Phone, not Name — several distinct customers can share a
            # cleaned first name (see Unique Customers above), which would merge
            # their spend into one misleading bar if grouped by Name alone.
            identified = filtered[filtered["Phone"] != "N/A"]

            by_customer_location = identified.groupby(["Phone", "Location"], as_index=False)["Total"].sum()
            primary_location = (
                by_customer_location.sort_values("Total", ascending=False)
                .drop_duplicates(subset="Phone", keep="first")
                .set_index("Phone")["Location"]
            )
            display_name = (
                identified.drop_duplicates(subset="Phone", keep="first").set_index("Phone")["Name"]
            )

            top_customers = identified.groupby("Phone", as_index=False)["Total"].sum().nlargest(15, "Total")
            top_customers["Name"] = top_customers["Phone"].map(display_name)
            top_customers["Location"] = top_customers["Phone"].map(primary_location)
            top_customers = top_customers.sort_values("Total", ascending=True)
            top_customers["Label"] = top_customers["Name"] + " (" + top_customers["Phone"] + ")"

            fig = go.Figure()
            fig.add_bar(
                y=top_customers["Label"], x=top_customers["Total"], orientation="h",
                marker=dict(color=theme.sequential_colors(len(top_customers)), cornerradius=4),
                customdata=top_customers["Location"],
                hovertemplate="%{y}<br>%{customdata}<br>KES %{x:,.0f}<extra></extra>",
            )
            theme.apply_layout(fig, show_legend=False)
            fig.update_layout(
                title=f"Top Customers by Spend — {selected_location}",
                height=max(360, 28 * len(top_customers)),
            )
            theme.show(fig, width="stretch")

    with st.container(border=True):
        display_df = filtered.sort_values("Date", ascending=False)
        if len(display_df) > MAX_TABLE_ROWS:
            st.caption(f"Showing first {MAX_TABLE_ROWS:,} of {len(display_df):,} rows.")
            display_df = display_df.head(MAX_TABLE_ROWS)
        st.caption("Click a column header's filter icon to search or narrow that column.")
        grid.filterable_table(display_df)

    _names_to_fix(to_fix)
    _genders_to_fix(mismatches)
    _spelling_to_fix(misspelt)
    _phones_to_fix(start_date, end_date)


def _names_to_fix(rows) -> None:
    """Customer records with no usable name, one row per record, to fix in Odoo."""
    st.subheader("Customer Names to Fix in Odoo")
    if rows.empty:
        st.success("Every customer in this range has a name recorded.", icon="✅")
        return
    rows["Name in Odoo"] = rows["Raw Name"].fillna("").str.strip().replace("", "(blank)")
    fix = (rows.groupby(["Name in Odoo", "Phone"], as_index=False)
           .agg(Locations=("Location", lambda v: ", ".join(sorted(set(v)))),
                Orders=("Date", "size"), Total=("Total", "sum"),
                **{"First Seen": ("Date", "min"), "Last Seen": ("Date", "max")})
           .sort_values("Last Seen", ascending=False))
    st.caption(
        f"{len(fix):,} customer records whose name is only a bank or payment note (KCB, NCBA, "
        "Co-op, I&M, Stanbic, PDQ…) or is blank. They show as N/A above. Search Odoo by the "
        "phone number and enter the customer's name; the page picks it up on the next refresh."
    )
    with st.container(border=True):
        grid.filterable_table(fix, currency_columns=("Total",), pinned_columns=("Name in Odoo",),
                              height=320)



def _genders_to_fix(rows) -> None:
    """Customers whose recorded gender contradicts their name."""
    st.subheader("Gender Corrections to Make in Odoo")
    if rows.empty:
        st.success("Every recorded gender in this range matches the customer's name.", icon="✅")
        return
    st.caption(
        f"{len(rows):,} customer records where the gender entered at the till contradicts a "
        "name that is clearly one gender (e.g. John saved as Female). The dashboard already "
        "counts them under the Name-Implied Gender; change the gender in Odoo (search by phone) "
        "so exports agree. Names staff record both ways (Valentine, Terry…) are never flagged."
    )
    with st.container(border=True):
        grid.filterable_table(rows, pinned_columns=("Name",), height=320)


def _spelling_to_fix(rows) -> None:
    """Customers whose first name looks like a typing slip of a common name."""
    st.subheader("Misspelt Names to Fix in Odoo")
    if rows.empty:
        st.success("No likely misspelt first names in this range.", icon="✅")
        return
    st.caption(
        f"{len(rows):,} customer records whose first name is one letter off a common name "
        "(missing, extra, swapped or mistyped — \"Meercy\" for Mercy, \"Briyan\" for Brian). "
        "The dashboard already shows the corrected name. Only rare spellings close to exactly "
        "one common name are corrected, and never a real name in its own right (Gary, Merry) "
        "or against the recorded gender (Alfreda stays Alfreda)."
    )
    with st.container(border=True):
        grid.filterable_table(rows, pinned_columns=("Name as Typed",), height=320)



def _phones_to_fix(start_date: date, end_date: date) -> None:
    """Customer phone numbers that can't be a valid East African mobile number."""
    st.subheader("Phone Numbers to Check with Attendants")
    orders = db.run_query(queries.CUSTOMER_PHONES, {"start_date": start_date, "end_date": end_date})
    rows = phones.to_check(orders)
    if rows.empty:
        st.success("Every customer phone number in this range has 10 digits starting "
                   "07, 01 or 06.", icon="✅")
        return
    st.caption(
        f"{len(rows):,} customers served in this range whose number is not 10 digits starting "
        "07, 01 or 06 (+254, +255 and +256 numbers are read as their 0 form). Numbers from "
        "other countries, with or without the + (91…, 90…, 211…), are accepted as "
        "international when they have 8 to 15 digits. Numbers starting 00 are always listed "
        "as typing mistakes. Ask the attendant "
        "in Served By for the right number, or the customer on their next visit, and update it "
        "in Odoo. Likely Number is filled where only the leading 0 is missing. Customers with "
        "no number saved are not listed."
    )
    with st.container(border=True):
        grid.filterable_table(rows, pinned_columns=("Name",), height=360)


TYPE_COLORS = {"Individual": theme.CATEGORICAL[1], "Shop Corporate": theme.CATEGORICAL[2],
               "Corporate Sales": theme.CATEGORICAL[0]}


def _corporate_customers(lines: pd.DataFrame) -> pd.DataFrame:
    """One row per corporate customer and type."""
    if lines.empty:
        return pd.DataFrame(columns=["Customer", "Type", "Phone", "Orders", "Bags", "Revenue",
                                     "First Order", "Last Order", "Where", "Served By"])
    return (lines.groupby(["Customer", "Channel"], as_index=False)
            .agg(Phone=("Phone", "first"), Orders=("Order", "nunique"), Bags=("Bags", "sum"),
                 Revenue=("Revenue", "sum"), **{"First Order": ("Date", "min"),
                                                "Last Order": ("Date", "max")},
                 Where=("Location", lambda v: ", ".join(sorted(set(v)))),
                 **{"Served By": ("Sold By", lambda v: ", ".join(sorted(set(v))))})
            .rename(columns={"Channel": "Type"})
            .assign(Revenue=lambda f: f["Revenue"].round(2))
            .sort_values("Revenue", ascending=False))


@st.fragment()
def render_corporate(start_date: date, end_date: date) -> None:
    """Corporate customers, both kinds: Corporate Sales (the Sales module) and
    Shop Corporate (customers recorded as Corporate, buying at the tills)."""
    lines = db.run_query(queries.CORPORATE_LINES, {"start_date": start_date, "end_date": end_date})
    kind = st.selectbox("Corporate type", ["All Corporate", "Corporate Sales", "Shop Corporate"],
                        key="customers_corporate_type")
    st.caption("**Corporate Sales** are customers on confirmed orders in Odoo's Sales module — "
               "the corporate team's orders. **Shop Corporate** are customers recorded as "
               "Corporate who bought at a shop till. Revenue in KES, VAT included.")
    customers = _corporate_customers(lines)
    shown = customers if kind == "All Corporate" else customers[customers["Type"] == kind]
    by_type = customers.groupby("Type").agg(Revenue=("Revenue", "sum"), Customers=("Customer", "size"))
    items = [("Corporate Revenue", f"KES {shown['Revenue'].sum():,.0f}",
              f"{len(shown):,} customers · {shown['Orders'].sum():,} orders")]
    for name in ("Corporate Sales", "Shop Corporate"):
        row = by_type.loc[name] if name in by_type.index else None
        items.append((name, f"KES {row['Revenue']:,.0f}" if row is not None else "KES 0",
                      f"{int(row['Customers']):,} customers" if row is not None else "no customers"))
    items.append(("Average per Customer",
                  f"KES {shown['Revenue'].sum() / len(shown):,.0f}" if len(shown) else "—", None))
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")
    if shown.empty:
        st.info("No corporate customers in this date range.")
        return
    with st.container(border=True):
        top = shown.head(20).sort_values("Revenue")
        fig = go.Figure()
        for name, color in TYPE_COLORS.items():
            part = top[top["Type"] == name]
            if part.empty:
                continue
            fig.add_bar(y=part["Customer"], x=part["Revenue"], orientation="h", name=name,
                        marker=dict(color=color, cornerradius=4),
                        customdata=part[["Orders", "Where"]],
                        hovertemplate="<b>%{y}</b><br>KES %{x:,.0f} · %{customdata[0]} orders"
                                      "<br>%{customdata[1]}<extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title="Top Corporate Customers", barmode="stack", hovermode="closest",
                          height=max(380, 28 * len(top) + 100))
        theme.show(fig)
    with st.container(border=True):
        st.caption("Every corporate customer in the range, by type, with the total at the bottom.")
        grid.filterable_table(shown, currency_columns=("Revenue",), pinned_columns=("Customer",),
                              height=440)


@st.fragment()
def render_all_customers(start_date: date, end_date: date) -> None:
    """Individual and corporate customers together."""
    params = {"start_date": start_date, "end_date": end_date}
    # Totals are counted the Sales page's way, so the two pages agree: every
    # till order (refunds included as the negative orders they are), every line
    # except delivery and customization fees, and corporate as the payments
    # received on corporate invoices.
    orders = db.run_query(queries.CUSTOMER_ORDERS, params)
    payments = db.run_query(queries.CORPORATE_PAYMENTS, params)
    pos = orders  # the purchases table below only needs to know there were sales
    lines = db.run_query(queries.CORPORATE_LINES, params)
    cols = ["Customer", "Type", "Phone", "Orders", "Bags", "Revenue", "First Order",
            "Last Order", "Where"]
    frames = []
    if not orders.empty:
        o = orders.assign(
            Type=np.where(orders["Corporate"], "Shop Corporate", "Individual"),
            Name=orders["Raw Name"].map(lambda n: names.clean(n) if isinstance(n, str) else "N/A"),
            Key=orders["Phone"].map(lambda v: (lambda d: d[-9:] if len(d) >= 9 else None)(
                "".join(ch for ch in str(v) if ch.isdigit()))))
        # One row per customer, known by phone; till sales with no phone
        # recorded are one row of their own, so nothing drops out of the total.
        o["Key"] = o["Key"].where(o["Key"].notna(),
                                  np.where(o["Corporate"], "name:" + o["Name"], "no phone"))
        o.loc[o["Key"] == "no phone", "Name"] = "Walk-in (no phone recorded)"
        frames.append(o.groupby(["Key", "Type"], as_index=False)
                      .agg(Customer=("Name", "first"), Phone=("Phone", "first"),
                           Orders=("Order ID", "nunique"), Bags=("Bags", "sum"),
                           Revenue=("Revenue", "sum"),
                           **{"First Order": ("Date", "min"), "Last Order": ("Date", "max")},
                           Where=("Location", lambda v: ", ".join(sorted(set(v)))))
                      .reindex(columns=cols))
    if not payments.empty:
        frames.append(payments.groupby("Customer", as_index=False)
                      .agg(Phone=("Phone", "first"), Orders=("Invoice", "nunique"),
                           Revenue=("Revenue", "sum"),
                           **{"First Order": ("Date", "min"), "Last Order": ("Date", "max")})
                      .assign(Type="Corporate Sales", Bags=np.nan, Where="Corporate")
                      .reindex(columns=cols))
    everyone = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)
    if everyone.empty:
        st.info("No customers in this date range.")
        return
    everyone["Revenue"] = everyone["Revenue"].round(2)
    everyone = everyone.sort_values("Revenue", ascending=False)

    by_type = everyone.groupby("Type").agg(Revenue=("Revenue", "sum"), Customers=("Customer", "size"))
    total = everyone["Revenue"].sum()
    items = [("Revenue", f"KES {total:,.0f}", f"{len(everyone):,} customers")]
    for name in TYPE_COLORS:
        if name in by_type.index:
            r = by_type.loc[name]
            items.append((name, f"KES {r['Revenue']:,.0f}",
                          f"{int(r['Customers']):,} customers · {r['Revenue'] / total * 100:.1f}%"))
    for col, (label, value, note) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, note, delta_color="off")
    st.caption("Revenue is counted as the Sales page counts it, so the totals agree: every "
               "till order (refunds netted), every line except delivery and customization "
               "fees, and corporate as the payments received on corporate invoices. Shop "
               "customers are one row per phone number; till sales with no phone recorded "
               "are one \"Walk-in (no phone recorded)\" row. Corporate Sales customers are "
               "the companies that paid. Revenue in KES, VAT included.")

    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        data = charts.fold_other(by_type.index, by_type["Revenue"])
        charts.share_chart(data, title="Revenue by Customer Type", key="all_customers_kind",
                           colors=charts.colors_for(data["Label"], fixed=TYPE_COLORS))
    with c2, st.container(border=True):
        top = everyone.head(15).sort_values("Revenue")
        fig = go.Figure()
        for name, color in TYPE_COLORS.items():
            part = top[top["Type"] == name]
            if part.empty:
                continue
            fig.add_bar(y=part["Customer"], x=part["Revenue"], orientation="h", name=name,
                        marker=dict(color=color, cornerradius=4),
                        hovertemplate="<b>%{y}</b><br>KES %{x:,.0f}<extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title="Top Customers, All Types", barmode="stack", hovermode="closest",
                          height=max(380, 28 * len(top) + 100))
        theme.show(fig)
    with st.container(border=True):
        kind = st.selectbox("Customer type", ["All types", *TYPE_COLORS], key="all_customers_type")
        shown = everyone if kind == "All types" else everyone[everyone["Type"] == kind]
        if len(shown) > MAX_TABLE_ROWS:
            st.caption(f"Showing the top {MAX_TABLE_ROWS:,} of {len(shown):,} customers by revenue.")
            shown = shown.head(MAX_TABLE_ROWS)
        st.caption("One row per customer, best first, with the total at the bottom.")
        grid.filterable_table(shown, currency_columns=("Revenue",), pinned_columns=("Customer",),
                              height=460)

    # Every purchase by every customer, shop and corporate alike, in one table.
    st.subheader("All Customer Purchases")
    shop_rows = pd.DataFrame()
    if not pos.empty:
        everyone_pos = db.run_query(queries.CUSTOMER_SALES, params)
        shop_rows = pd.DataFrame({
            "Date": everyone_pos["Date"],
            "Customer": everyone_pos["Raw Name"].map(names.clean),
            "Type": everyone_pos["Gender"].map(lambda g: "Shop Corporate" if g == "Corporate"
                                               else "Individual"),
            "Phone": everyone_pos["Phone"],
            "Location": everyone_pos["Location"],
            "Product": everyone_pos["Product"], "Colour": everyone_pos["Color"],
            "Category": everyone_pos["Category"], "Quantity": everyone_pos["Quantity"],
            "Price": everyone_pos["Price"], "Total": everyone_pos["Total"],
        })
    corp_rows = lines[lines["Channel"] == "Corporate Sales"] if not lines.empty else lines
    corp_rows = pd.DataFrame({
        "Date": corp_rows.get("Date"), "Customer": corp_rows.get("Customer"),
        "Type": "Corporate Sales", "Phone": corp_rows.get("Phone"),
        "Location": corp_rows.get("Location"), "Product": corp_rows.get("Product"),
        "Colour": None, "Category": corp_rows.get("Category"), "Quantity": corp_rows.get("Qty"),
        "Price": (corp_rows["Revenue"] / corp_rows["Qty"].where(corp_rows["Qty"] != 0)).round(2)
                 if not corp_rows.empty else None,
        "Total": corp_rows.get("Revenue"),
    }) if not corp_rows.empty else pd.DataFrame()
    purchases = pd.concat([f for f in (shop_rows, corp_rows) if not f.empty], ignore_index=True)         if not (shop_rows.empty and corp_rows.empty) else pd.DataFrame()
    if purchases.empty:
        st.info("No purchases in this date range.")
        return
    with st.container(border=True):
        c1, c2 = st.columns(2)
        kind = c1.selectbox("Customer type", ["All types", *TYPE_COLORS], key="all_purchases_type")
        where = c2.selectbox("Location", ["All locations"] + sorted(purchases["Location"].dropna().unique()),
                             key="all_purchases_location")
        rows = purchases if kind == "All types" else purchases[purchases["Type"] == kind]
        rows = rows if where == "All locations" else rows[rows["Location"] == where]
        rows = rows.sort_values("Date", ascending=False)
        st.caption(f"{len(rows):,} purchases — shop customers (individual and corporate, from "
                   "the tills) and the corporate team's jobs, product by product, newest first. "
                   "This is the detail of what was bought: order-level discounts, gift bags and "
                   "fees are not product lines here, and corporate jobs are at their listed "
                   "price, so its total can differ slightly from the revenue above.")
        if len(rows) > MAX_TABLE_ROWS:
            st.caption(f"Showing the newest {MAX_TABLE_ROWS:,}.")
            rows = rows.head(MAX_TABLE_ROWS)
        grid.filterable_table(rows, currency_columns=("Price", "Total"),
                              pinned_columns=("Customer",), height=480)


SECTIONS = ["🧑 Customers", "🏢 Corporate", "👥 All Customers"]
section = st.segmented_control("Section", SECTIONS, default=SECTIONS[0], key="customers_section",
                               label_visibility="collapsed") or SECTIONS[0]
if section == "🏢 Corporate":
    render_corporate(start_date, end_date)
elif section == "👥 All Customers":
    render_all_customers(start_date, end_date)
else:
    render_customers(start_date, end_date)
