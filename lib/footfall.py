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
            # A 0 is kept: a day with no walk-ins is a real count. Whether
            # it can stand is judged on the page (only with no walk-in sales).
            if total is None or pd.isna(total) or total < 0:
                continue
            rows.append({"Location": NAMES.get(shop, shop),
                         "Date": pd.to_datetime(label, dayfirst=True),
                         "Visitors": float(total), "Purchased": _number(cell(0))})
    return pd.DataFrame(rows)


def daily(start_date, end_date) -> tuple[pd.DataFrame, int, bool]:
    """Every shop-day in the range: walk-ins counted beside the day's orders,
    ready for the Footfall Traffic page and the Reports page alike.

    Returns (frame, shop-days filled from the sheet, whether today was in the
    range and left out). Rules:
      * the Footfall module's count first; a missing one from the sheet;
      * a sheet 0 on a day the shop sold nothing is dropped (not open);
      * today is left out — shops enter the day's walk-ins at close of day;
      * a 0 stands only when no walk-in bought; a 0 with walk-in sales is
        treated as not counted, and a day with neither a count nor a
        walk-in sale had no walk-ins (0).
    """
    import numpy as np
    from datetime import date
    from lib import db, queries

    df = db.run_query(queries.FOOTFALL_DAILY, {"start_date": start_date, "end_date": end_date})
    if df.empty:
        return df, 0, False
    df["Date"] = pd.to_datetime(df["Date"])
    sheet = load()
    filled = 0
    if not sheet.empty:
        sheet = sheet[(sheet["Date"] >= pd.Timestamp(start_date))
                      & (sheet["Date"] <= pd.Timestamp(end_date))]
        df = df.merge(sheet[["Location", "Date", "Visitors"]].rename(columns={"Visitors": "Sheet"}),
                      on=["Location", "Date"], how="outer")
        gap = df["Visitors"].isna() & df["Sheet"].notna()
        filled = int(gap.sum())
        df.loc[gap, "Visitors"] = df.loc[gap, "Sheet"]
        df.loc[gap, "Entered"] = "Reporting sheet"
        df = df.drop(columns="Sheet")
    for col in ("Orders", "Walk-in Orders", "Online Orders", "Other Orders", "Refunds",
                "Revenue", "Walk-in Revenue"):
        df[col] = df[col].fillna(0)
    closed = (df["Entered"] == "Reporting sheet") & (df["Visitors"] == 0) & (df["Orders"] == 0)
    filled -= int(closed.sum())
    df = df[~closed]
    today = pd.Timestamp(date.today())
    open_today = bool((df["Date"] == today).any())
    df = df[df["Date"] < today].copy()
    zero_with_buyers = (df["Visitors"] == 0) & (df["Walk-in Orders"] > 0)
    df.loc[zero_with_buyers, ["Visitors", "Entered"]] = [np.nan, "0 entered, walk-ins bought"]
    no_walkins = df["Visitors"].isna() & (df["Walk-in Orders"] == 0)
    df.loc[no_walkins, "Visitors"] = 0
    df.loc[no_walkins & df["Entered"].isna(), "Entered"] = "No walk-in sales"
    df["Didn't Buy"] = (df["Visitors"] - df["Walk-in Orders"]).clip(lower=0)
    return df, filled, open_today
