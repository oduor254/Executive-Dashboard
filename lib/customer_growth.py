"""Customer Growth: are the older shops still growing, or are the new ones
carrying the business?

For a period and the same period last year (lib.filters.last_year), Kenya only:

  * Older shops — open before last year's period started, so both periods
    can be compared like for like. New shops — opened since then, i.e. in the
    last twelve months or so. A shop "opens" on its first sale in Odoo.
  * Online — the Website and Jumia; neither an older nor a new shop.
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
ONLINE_LOCATIONS = {"Website", "Jumia"}
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
        "Orders": sales.groupby("Location")["Order ID"].nunique(),
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
    }
