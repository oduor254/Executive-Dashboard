"""New or repeat: whether a converted customer had bought from Denri before.

A customer is their phone number (last nine digits), as on Shop Performance.
On a given day they are a Repeat customer if their first purchase anywhere in
the company was before that day, and New if it was that day or later, or if
there is no purchase on record under that number at all. Without a usable
phone number (blank, or a shop's or attendant's own number) nobody can say,
and the row is counted as No Phone.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

NEW, REPEAT, NO_PHONE = "New", "Repeat", "No Phone"

# Each customer's first paid order, dated in Kenya time like the POS dashboard.
FIRST_PURCHASES = """
SELECT RIGHT(REGEXP_REPLACE(COALESCE(rp.phone, rp.mobile, ''), '[^0-9]', '', 'g'), 9) AS key,
       MIN((po.date_order AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Nairobi')::DATE) AS first_day
FROM pos_order po
JOIN res_partner rp ON rp.id = po.partner_id
WHERE po.state IN ('done', 'paid', 'invoiced') AND po.amount_total > 0
GROUP BY 1
HAVING LENGTH(RIGHT(REGEXP_REPLACE(COALESCE(rp.phone, rp.mobile, ''), '[^0-9]', '', 'g'), 9)) = 9
"""


# shortcut: cached six hours (the query takes ~12s), so a customer whose first
# purchase is newer than the cache shows as New on a conversion a later day;
# shorten the cache if that ever matters.
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def first_purchases() -> pd.Series:
    """Phone key -> the day of that customer's first purchase."""
    from lib import db
    rows = db.run_query(FIRST_PURCHASES)
    return pd.to_datetime(rows.set_index("key")["first_day"])


def phone_key(value) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-9:] if len(digits) >= 9 else None


def kind(phones: pd.Series, days: pd.Series) -> pd.Series:
    """New, Repeat or No Phone for each (phone, day): Repeat when the
    customer's first purchase was before that day."""
    from lib import staff_numbers
    # a shop's or an attendant's own number, typed in place of the customer's, is nobody's history
    not_customers = staff_numbers.store_keys() | staff_numbers.attendant_keys()
    keys = phones.map(phone_key).where(lambda k: ~k.isin(not_customers))
    before = keys.map(first_purchases()) < pd.to_datetime(days).dt.normalize()
    return before.map({True: REPEAT, False: NEW}).where(keys.notna(), NO_PHONE)


def split(df: pd.DataFrame, phone: str, day: str, by: str | None = None) -> pd.DataFrame:
    """New, Repeat and No Phone counts of df's rows, overall (one row,
    "All") or per `by`."""
    k = kind(df[phone], df[day])
    t = pd.crosstab(df[by] if by else pd.Series("All", index=df.index), k)
    return t.reindex(columns=[NEW, REPEAT, NO_PHONE], fill_value=0)


if __name__ == "__main__":   # python -m lib.customer_kind
    from lib import staff_numbers
    staff_numbers.store_keys = staff_numbers.attendant_keys = lambda: {"700000001"}
    first_purchases = lambda: pd.Series(pd.to_datetime(["2026-01-05"]), index=["712345678"])
    got = kind(pd.Series(["+254 712 345 678", "0712345678", "0712345678", "0799999999", "", "0700000001"]),
               pd.Series(pd.to_datetime(["2026-01-06", "2026-01-05", "2026-01-04", "2026-01-06",
                                         "2026-01-06", "2026-01-06"])))
    assert got.tolist() == [REPEAT, NEW, NEW, NEW, NO_PHONE, NO_PHONE], got.tolist()
    print("customer_kind ok")
