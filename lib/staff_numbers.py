"""Phone numbers that belong to Denri, not to a customer.

Two kinds, both read from Odoo so a new shop or attendant is picked up
without a code change:

  Store      — each shop's own number(s), as set in the Shop Attendants app
               (Point of Sale → shop → receipt phones), e.g. Starmall
               0703869724 and 0721994006.
  Attendant  — the mobile and work phones of the active employees under
               HR → Employees → Sales / Shop Attendants / <shop>.

A store number on a sale is always a data-quality flag: the attendant typed
the shop's number instead of the customer's. An attendant's number is a flag
too — except at the Staff POS, where staff buy for themselves under their
own number. Neither kind counts as a customer.

Numbers are matched on their last nine digits, like every customer phone.
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

STAFF_POS = "Staff POS"
STORE, ATTENDANT = "Store", "Attendant"

# The shops' numbers as they were printed on the posters — used only if Odoo
# can't be read, so the flags never silently disappear.
FALLBACK_STORE_KEYS = {
    "118753780", "714156897", "759296069", "720060705", "712532047", "745390465",
    "118753776", "715598778", "115920422", "795176310", "798219855", "707392070",
    "707722454", "790833297", "703869724", "701012197", "118753771",
}

STAFF_NUMBERS = r"""
SELECT 'Store'       AS "Kind",
       pc.name       AS "Owner",
       pc.name       AS "Shop",
       TRIM(num)     AS "Number"
FROM pos_config pc
CROSS JOIN LATERAL unnest(string_to_array(pc.receipt_phones, ',')) AS num
WHERE pc.active AND COALESCE(TRIM(pc.receipt_phones), '') <> ''
UNION ALL
SELECT 'Attendant',
       e.name,
       split_part(d.complete_name, ' / ', 3),
       TRIM(p.phone)
FROM hr_employee e
JOIN hr_department d ON d.id = e.department_id
CROSS JOIN LATERAL (VALUES (e.mobile_phone), (e.work_phone)) AS p(phone)
WHERE e.active
  AND d.complete_name ILIKE 'Sales / Shop Attendants%'
  AND COALESCE(TRIM(p.phone), '') <> ''
"""

_SHOP_NAMES = {"ktda": "Ktda", "website sales": "Website", "website": "Website", "website store": "Website",
               "dar-es-alam": "Sinza", "dar es salaam": "Sinza", "sinza": "Sinza"}


def key(phone) -> str | None:
    """The last nine digits — how every phone in the dashboard is matched."""
    digits = re.sub(r"\D", "", str(phone or ""))
    return digits[-9:] if len(digits) >= 9 else None


def shop_name(raw: str) -> str:
    """'KTDA Shop' → 'Ktda', 'HILTON SHOP' → 'Hilton', 'WEBSITE SALES' →
    'Website': the names the rest of the dashboard uses."""
    text = re.sub(r"\s*shop\s*$", "", str(raw or "").strip(), flags=re.I).strip()
    return _SHOP_NAMES.get(text.lower(), text.title())


@st.cache_data(ttl=3600, show_spinner=False)
def load() -> pd.DataFrame:
    """One row per number: Key, Number, Kind (Store / Attendant), Owner (the
    shop, or the attendant's name) and Shop. A number that is both a store's
    and an attendant's is kept as the store's."""
    from lib import db
    try:
        df = db.run_query(STAFF_NUMBERS)
    except Exception:
        df = pd.DataFrame({"Kind": STORE, "Owner": "Shop number", "Shop": "",
                           "Number": ["0" + k for k in sorted(FALLBACK_STORE_KEYS)]})
    df["Key"] = df["Number"].map(key)
    df = df.dropna(subset=["Key"])
    df["Shop"] = df["Shop"].map(shop_name)
    df["Owner"] = [shop_name(o) if k == STORE else str(o).strip().title()
                   for k, o in zip(df["Kind"], df["Owner"])]
    df["Kind"] = pd.Categorical(df["Kind"], [STORE, ATTENDANT], ordered=True)
    df = df.sort_values("Kind").drop_duplicates("Key")
    df["Kind"] = df["Kind"].astype(str)
    return df[["Key", "Number", "Kind", "Owner", "Shop"]].reset_index(drop=True)


def store_keys() -> set[str]:
    df = load()
    return set(df.loc[df["Kind"] == STORE, "Key"]) or set(FALLBACK_STORE_KEYS)


def attendant_keys() -> set[str]:
    df = load()
    return set(df.loc[df["Kind"] == ATTENDANT, "Key"])


def flagged(keys: pd.Series, locations: pd.Series) -> pd.Series:
    """Which sales carry a number that isn't the customer's: a store number
    anywhere, or an attendant's number anywhere but the Staff POS."""
    stores, attendants = store_keys(), attendant_keys()
    return keys.isin(stores) | (keys.isin(attendants) & (locations != STAFF_POS))
