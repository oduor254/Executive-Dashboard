"""Customer Growth: are the older shops still growing, or are the new ones
carrying the business?

For a period and the same period last year (lib.filters.last_year), Kenya only:

  * Older shops — open before last year's period started, so both periods
    can be compared like for like. New shops — opened since then, i.e. in the
    last twelve months or so. A shop "opens" on its first sale in Odoo.
  * The Website counts as an older location (it has sold since 2023); Jumia
    is Online, apart from both.
  * A customer is their phone number (last nine digits). Shop and attendant
    numbers typed in place of the customer's are nobody, as on the rest of the
    dashboard (lib.customer_kind).
  * New customer — their first Denri purchase anywhere falls inside the period.
    Returning customer — they had bought from Denri before the period began.

Revenue is counted as the Reports page counts it (lib.queries.REPORT_ORDERS).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from lib import customer_kind, filters, reports, staff_numbers

OLDER, NEW_SHOP, ONLINE = "Older shop", "New shop", "Online"
ONLINE_LOCATIONS = {"Jumia"}
NOT_KENYA = {"Sinza", "Uganda"}
# Tills that sell but aren't a shop customers walk into.
NOT_SHOPS = {"Staff POS", "Marketing", "Rejects", "Flash Sale Warehouse", "Loop",
             "Accessories & Materials Store"}

# Each location's first sale, named as REPORT_ORDERS names it.
OPENED = r"""
SELECT CASE
        WHEN lower(pconf.name) = 'jumia' THEN 'Jumia'
        WHEN lower(pconf.name) IN ('website sales', 'website') OR po.session_id IS NULL THEN 'Website'
        WHEN lower(pconf.name) = 'staff pos' THEN 'Staff POS'
        WHEN COALESCE(sw.name, sl.complete_name) ILIKE '%Dar-Es-Alam%' THEN 'Sinza'
        ELSE INITCAP(TRIM(REGEXP_REPLACE(COALESCE(sw.name, sl.complete_name, 'N/A'), '\s*Shop\s*', '', 'gi')))
       END AS "Location",
       MIN(po.date_order)::DATE AS "Opened"
FROM pos_order po
LEFT JOIN pos_session ps ON ps.id = po.session_id
LEFT JOIN pos_config pconf ON pconf.id = ps.config_id
LEFT JOIN stock_picking_type spt ON spt.id = pconf.picking_type_id
LEFT JOIN stock_warehouse sw ON sw.id = spt.warehouse_id
LEFT JOIN stock_location sl ON sl.id = spt.default_location_src_id
WHERE po.state IN ('done', 'paid', 'invoiced') AND po.amount_total > 0
GROUP BY 1
"""


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def opened() -> pd.Series:
    """Location -> the day of its first sale."""
    from lib import db
    t = db.run_query(OPENED)
    return pd.to_datetime(t.set_index("Location")["Opened"])


def group_of(location: str, opened_on, older_before: date) -> str | None:
    """Older shop, New shop, Online, or None for what isn't counted (outside
    Kenya, staff and stock tills)."""
    if location in NOT_KENYA or location in NOT_SHOPS:
        return None
    if location in ONLINE_LOCATIONS:
        return ONLINE
    if pd.isna(opened_on):
        return NEW_SHOP
    return OLDER if opened_on.date() <= older_before else NEW_SHOP


def _orders(start: date, end: date, older_before: date) -> pd.DataFrame:
    """The period's Kenya orders, each with its group and customer kind."""
    df = reports._orders(start, end).copy()
    df["Revenue"] = pd.to_numeric(df["Revenue"], errors="coerce").fillna(0)
    df["Bags"] = pd.to_numeric(df["Bags"], errors="coerce").fillna(0)
    df["Units"] = pd.to_numeric(df["Units"], errors="coerce").fillna(0)
    opened_on = opened()
    df["Group"] = [group_of(loc, opened_on.get(loc), older_before) for loc in df["Location"]]
    df = df[df["Group"].notna()]
    keys = df["Phone"].map(customer_kind.phone_key)
    not_customers = staff_numbers.store_keys() | staff_numbers.attendant_keys()
    df["Key"] = keys.where(~keys.isin(not_customers))
    first = df["Key"].map(customer_kind.first_purchases())
    df["Kind"] = "Unknown"
    df.loc[df["Key"].notna(), "Kind"] = "Returning"
    df.loc[df["Key"].notna() & (first.isna() | (first >= pd.Timestamp(start))), "Kind"] = "New"
    return df


def _per_location(df: pd.DataFrame) -> pd.DataFrame:
    sales = df[df["Revenue"] > 0]
    g = df.groupby("Location")
    known = sales[sales["Key"].notna()]
    out = pd.DataFrame({
        "Revenue": g["Revenue"].sum(),
        "Bags": g["Bags"].sum(),
        "Orders": sales.groupby("Location")["Order ID"].nunique(),
        "Identified Revenue": known.groupby("Location")["Revenue"].sum(),
        "Customers": known.groupby("Location")["Key"].nunique(),
        "New Customers": known[known["Kind"] == "New"].groupby("Location")["Key"].nunique(),
        "Returning Customers": known[known["Kind"] == "Returning"].groupby("Location")["Key"].nunique(),
        "New-Customer Revenue": df[df["Kind"] == "New"].groupby("Location")["Revenue"].sum(),
        "Returning-Customer Revenue": df[df["Kind"] == "Returning"].groupby("Location")["Revenue"].sum(),
    }).fillna(0)
    out["Group"] = df.groupby("Location")["Group"].first()
    return out


def _totals(df: pd.DataFrame) -> dict:
    sales = df[(df["Revenue"] > 0) & df["Key"].notna()]
    customers = sales["Key"].nunique()
    return {
        "Revenue": df["Revenue"].sum(),
        "Bags": df["Bags"].sum(),
        "Orders": df.loc[df["Revenue"] > 0, "Order ID"].nunique(),
        "Customers": customers,
        "New Customers": sales.loc[sales["Kind"] == "New", "Key"].nunique(),
        "Returning Customers": sales.loc[sales["Kind"] == "Returning", "Key"].nunique(),
        "New-Customer Revenue": df.loc[df["Kind"] == "New", "Revenue"].sum(),
        "Returning-Customer Revenue": df.loc[df["Kind"] == "Returning", "Revenue"].sum(),
        "Avg Spend / Customer": sales["Revenue"].sum() / customers if customers else None,
    }


def build(start: date, end: date) -> dict:
    """Everything the Overview shows, for the period and the same period last year."""
    ly_start, ly_end = filters.last_year(start, end)
    now = _orders(start, end, ly_start)
    then = _orders(ly_start, ly_end, ly_start)
    # A shop older than last year's period may still show up as new there if it
    # sold nothing then; group by this period's view so both sides match.
    groups = now.groupby("Location")["Group"].first()
    then["Group"] = then["Location"].map(groups).fillna(then["Group"])

    loc_now, loc_then = _per_location(now), _per_location(then)
    shops = loc_now.join(loc_then.drop(columns="Group"), how="outer", rsuffix=" LY").fillna(0)
    shops["Group"] = loc_now["Group"].reindex(shops.index).fillna(loc_then["Group"])
    shops["Opened"] = opened().reindex(shops.index).dt.date

    def part(df, group=None):
        return _totals(df if group is None else df[df["Group"] == group])

    return {
        "period": (start, end), "last_year": (ly_start, ly_end),
        "older": (part(now, OLDER), part(then, OLDER)),
        "new_shops": (part(now, NEW_SHOP), part(then, NEW_SHOP)),
        "online": (part(now, ONLINE), part(then, ONLINE)),
        "kenya": (part(now), part(then)),
        "shops": shops.reset_index(names="Location"),
        "orders": (now, then),
    }


# The older shops' scorecard: each figure last year, this period and the change.
METRICS = {   # figure -> written as money?
    "Revenue": True, "Orders": False, "Bags": False, "Customers": False,
    "New Customers": False, "Returning Customers": False,
    "New-Customer Revenue": True, "Returning-Customer Revenue": True,
    "Avg Spend / Customer": True, "Avg Order Value": True, "Bags per Order": False,
}


def with_ratios(t: pd.DataFrame, suffix: str = "") -> pd.DataFrame:
    """Add the per-customer and per-order figures for one side (suffix "" or " LY")."""
    t = t.copy()
    pos = lambda c: t[c + suffix].where(t[c + suffix] > 0)
    t["Avg Spend / Customer" + suffix] = t["Identified Revenue" + suffix] / pos("Customers")
    t["Avg Order Value" + suffix] = t["Revenue" + suffix] / pos("Orders")
    t["Bags per Order" + suffix] = t["Bags" + suffix] / pos("Orders")
    return t


def scorecard(shops: pd.DataFrame) -> pd.DataFrame:
    """One row per shop: every METRICS figure last year, now, and the % change."""
    t = with_ratios(with_ratios(shops), " LY")
    for m in METRICS:
        t[m + " Δ%"] = (t[m] - t[m + " LY"]) / t[m + " LY"].where(t[m + " LY"] > 0) * 100
    return t


# ------------------------------------------------------ customer behaviour ---
# Bulk and corporate orders would skew what an ordinary customer does, so the
# behaviour figures leave them out: an order of more than BULK_UNITS items, or
# one whose customer is recorded as Corporate (on gender or customer type).
BULK_UNITS = 15
WALK_IN, ONLINE_CH = "Walk-in", "Online"
# Activation customers are walk-ins met where the activation was held.
CHANNEL = {"Walk-in": WALK_IN, "Activation": WALK_IN, "Online": ONLINE_CH}


def split_bulk(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(ordinary customer orders, bulk and corporate orders)."""
    corporate = df["Gender"].eq("Corporate") | df["Channel"].eq("Corporate")
    out = (df["Units"] > BULK_UNITS) | corporate
    kept = df[~out].copy()
    kept["Sales Channel"] = kept["Channel"].map(CHANNEL).fillna("Other")
    kept["Gender"] = kept["Gender"].where(kept["Gender"].isin(["Female", "Male"]), "Not recorded")
    return kept, df[out]


def behaviour(df: pd.DataFrame, before: pd.DataFrame) -> dict:
    """How the period's customers bought. `before` is the month ahead of the
    period, for who came back from it."""
    sales = df[(df["Revenue"] > 0) & df["Key"].notna()].copy()
    sales["Month"] = pd.to_datetime(sales["Date"]).dt.to_period("M")
    days = sales.groupby("Key")["Date"].nunique()
    customers = len(days)
    orders = df.loc[df["Revenue"] > 0, "Order ID"].nunique()
    # bought on two or more days of the same calendar month
    month_days = sales.groupby(["Month", "Key"])["Date"].nunique()
    # of each month's buyers, how many had bought the month before
    prev = pd.concat([before[(before["Revenue"] > 0) & before["Key"].notna()], sales])
    prev_month = pd.to_datetime(prev["Date"]).dt.to_period("M")
    buyers = prev.assign(Month=prev_month).groupby("Month")["Key"].apply(set)
    came, base = 0, 0
    for m in sales["Month"].unique():
        if m - 1 in buyers.index:
            came += len(buyers[m - 1] & buyers[m])
            base += len(buyers[m - 1])
    return {
        "Customers": customers,
        "Orders": orders,
        "Revenue": df["Revenue"].sum(),
        "Average Order Value": df["Revenue"].sum() / orders if orders else None,
        "Items per Order": df.loc[df["Revenue"] > 0, "Units"].sum() / orders if orders else None,
        "Repeat Customers %": (days >= 2).mean() * 100 if customers else None,
        "Came Back Next Month %": came / base * 100 if base else None,
        "Bought Twice in a Month %": (month_days >= 2).mean() * 100 if len(month_days) else None,
        "Revenue per Customer": sales["Revenue"].sum() / customers if customers else None,
        "Orders per Customer": sales["Order ID"].nunique() / customers if customers else None,
        "New Customers %": sales.loc[sales["Kind"] == "New", "Key"].nunique() / customers * 100
        if customers else None,
    }


def by(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Customers, revenue and how they buy, per value of `col` (Gender, Sales Channel)."""
    sales = df[(df["Revenue"] > 0) & df["Key"].notna()]
    g = sales.groupby(col)
    days = sales.groupby([col, "Key"])["Date"].nunique()
    t = pd.DataFrame({
        "Customers": g["Key"].nunique(),
        "Orders": df[df["Revenue"] > 0].groupby(col)["Order ID"].nunique(),
        "Revenue": df.groupby(col)["Revenue"].sum(),
        "Identified Revenue": g["Revenue"].sum(),
        "Repeat %": (days >= 2).groupby(level=0).mean() * 100,
    }).fillna(0)
    t["Customer Share %"] = t["Customers"] / t["Customers"].sum() * 100
    t["Revenue Share %"] = t["Revenue"] / t["Revenue"].sum() * 100
    t["Average Order Value"] = t["Revenue"] / t["Orders"].where(t["Orders"] > 0)
    t["Revenue per Customer"] = t["Identified Revenue"] / t["Customers"].where(t["Customers"] > 0)
    return t.drop(columns="Identified Revenue")


def visit_gaps(df: pd.DataFrame) -> pd.Series:
    """Days between one purchase day and a customer's next, within the period."""
    days = (df[(df["Revenue"] > 0) & df["Key"].notna()][["Key", "Date"]].drop_duplicates()
            .assign(Date=lambda t: pd.to_datetime(t["Date"])).sort_values(["Key", "Date"]))
    return days.groupby("Key")["Date"].diff().dt.days.dropna()


def tenure(df: pd.DataFrame, start: date) -> pd.Series:
    """For each returning customer, months since their first Denri purchase."""
    keys = df.loc[(df["Revenue"] > 0) & (df["Kind"] == "Returning"), "Key"].unique()
    first = pd.Series(keys).map(customer_kind.first_purchases())
    return ((pd.Timestamp(start) - first).dt.days / 30.44).dropna()


# ------------------------------------------------------------- new shops ---
_LOCATION = OPENED.split("SELECT ", 1)[1].split(' AS "Location"')[0]
_FROM = OPENED.split("FROM pos_order po", 1)[1].split("WHERE")[0]

# Where each customer (phone, last nine digits) made their very first purchase.
# Each customer record's first order is found first (materialized, or the
# planner nests loops over every order), then the earliest per phone. Only the
# phones asked about come back: the query takes seconds, sending every phone minutes.
FIRST_SHOP = r"""
WITH first_order AS MATERIALIZED (
    SELECT DISTINCT ON (po.partner_id) po.partner_id, po.session_id, po.date_order
    FROM pos_order po
    WHERE po.state IN ('done', 'paid', 'invoiced') AND po.amount_total > 0 AND po.partner_id IS NOT NULL
    ORDER BY po.partner_id, po.date_order
), keyed AS MATERIALIZED (
    SELECT RIGHT(REGEXP_REPLACE(COALESCE(rp.phone, rp.mobile, ''), '[^0-9]', '', 'g'), 9) AS key,
           fo.session_id, fo.date_order
    FROM first_order fo
    JOIN res_partner rp ON rp.id = fo.partner_id
)
SELECT DISTINCT ON (po.key) po.key, """ + _LOCATION + r""" AS location
FROM keyed po""" + _FROM + r"""
WHERE po.key = ANY(:keys)
ORDER BY po.key, po.date_order
"""


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def first_shop(keys: tuple[str, ...]) -> pd.Series:
    """Phone key -> the location of that customer's first Denri purchase."""
    from lib import db
    return db.run_query(FIRST_SHOP, {"keys": list(keys)}).set_index("key")["location"]


def came_from(df: pd.DataFrame) -> pd.DataFrame:
    """For each new shop, its period customers split by where they first bought:
    the shop itself (new to Denri there) or an older location."""
    sales = df[(df["Group"] == NEW_SHOP) & (df["Revenue"] > 0) & df["Key"].notna()]
    people = sales[["Location", "Key"]].drop_duplicates()
    first = first_shop(tuple(sorted(people["Key"].unique())))
    people["First Bought At"] = people["Key"].map(first).fillna(people["Location"])
    return people


def verdict(rev_per_day: float, benchmark: float, trend: float | None, new_share: float,
            days_open: int) -> tuple[str, str]:
    """(Success / On track / Watch / Struggling / Too early, why) for a new shop."""
    if days_open < 45:
        return "Too early", f"open {days_open} days"
    pace = rev_per_day / benchmark * 100 if benchmark else 0
    if pace >= 80 and (trend is None or trend >= 0) and new_share >= 50:
        return "Success", f"sells at {pace:.0f}% of an older shop's daily pace and mostly brings new buyers"
    if pace < 40 or (trend is not None and trend <= -25):
        return "Struggling", (f"sells at {pace:.0f}% of an older shop's daily pace"
                              + (f", last 3 months {trend:+.0f}% on the 3 before" if trend is not None else ""))
    if new_share < 50:
        return "Watch", f"{100 - new_share:.0f}% of its customers already bought at another Denri shop"
    return "On track", f"sells at {pace:.0f}% of an older shop's daily pace"


if __name__ == "__main__":   # python -m lib.customer_growth
    assert verdict(1, 1, None, 90, 10)[0] == "Too early"
    assert verdict(90, 100, 5, 70, 200)[0] == "Success"
    assert verdict(30, 100, 5, 70, 200)[0] == "Struggling"
    assert verdict(70, 100, -30, 70, 200)[0] == "Struggling"
    assert verdict(90, 100, 5, 30, 200)[0] == "Watch"
    assert verdict(60, 100, 5, 70, 200)[0] == "On track"
    assert "LEFT JOIN stock_location sl" in FIRST_SHOP and "FROM keyed po" in FIRST_SHOP
    print("customer_growth ok")
