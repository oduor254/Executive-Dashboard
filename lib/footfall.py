"""Footfall counts kept in the Reporting Google Sheet ("Footfall" tab).

The Footfall module in Odoo is the record of walk-ins, but it has gaps: the
counts were imported up to 5 Oct 2026 and entered at the tills from 9 Oct,
and shops miss days. The Reporting sheet holds every shop's daily count, so
the Footfall Traffic page takes a shop-day's count from the sheet wherever the
module has none (1-20 Oct 2026: 139 of 144 gaps filled; where both have a
count they agree on 715 of 754 shop-days, and the module is kept).

The tab is laid out wide: a row per shop, and for each day a block of four
columns — WALKINS PURCHASED, W.NOT PURCHASED, TOTAL, C. RATE — under a date
label (dd/mm/yyyy) that sits over the block's second column; weekly totals
("WEEK n") sit between the days and are skipped.
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from lib import sheets_sync

SPREADSHEET_ID = "1S4kRCl1KWMTWKaSF8NSIXjDiJmvREzv7hm4vDnowdqs"   # "Reporting"
WORKSHEET = "Footfall"
# Sheet shop names, named as the dashboard names them.
NAMES = {"KTDA": "Ktda", "Dar es Salaam": "Sinza", "Dar-Es-Salaam": "Sinza", "Kampala": "Uganda"}
_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _number(value: str) -> float | None:
    text = str(value or "").replace(",", "").strip()
    return pd.to_numeric(text, errors="coerce") if text else None


@st.cache_data(ttl=600, show_spinner="Reading footfall from the Reporting sheet…")
def load() -> pd.DataFrame:
    """One row per shop and day with a count: Location, Date, Visitors,
    Purchased (as the sheet records them). Empty when the sheet can't be read."""
    try:
        ws = sheets_sync._client().open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET)
        values = ws.get_all_values()
    except Exception:
        return pd.DataFrame(columns=["Location", "Date", "Visitors", "Purchased"])
    if len(values) < 3:
        return pd.DataFrame(columns=["Location", "Date", "Visitors", "Purchased"])
    blocks = [(i - 1, label.strip()) for i, label in enumerate(values[0])
              if _DATE.match(label.strip()) and i > 0]
    rows = []
    for row in values[2:]:
        shop = row[0].strip() if row else ""
        if not shop or shop.lower() == "total":
            continue
        for start, label in blocks:
            cell = lambda k: row[start + k] if start + k < len(row) else ""
            total = _number(cell(2))
            if total is None or pd.isna(total) or total <= 0:
                continue
            rows.append({"Location": NAMES.get(shop, shop),
                         "Date": pd.to_datetime(label, dayfirst=True),
                         "Visitors": float(total), "Purchased": _number(cell(0))})
    return pd.DataFrame(rows)
