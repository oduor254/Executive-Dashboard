"""Footfall history from the Reporting Google Sheet ("Footfall" tab), frozen.

Walk-ins are now keyed into the Footfall module in Odoo every day, so the
sheet is no longer read. Its counts (1 Jan - 21 Oct 2026) were saved once to
lib/data/footfall_history.csv, and fill the days the module has no count for
— the import ran up to 5 Oct 2026 and till entry started on 9 Oct, so the
history covers that gap and the days shops missed. The module's count wins
wherever both have one.

The CSV has one row per shop and day: Location, Date, Visitors (the sheet's
TOTAL walk-ins) and Purchased (its WALKINS PURCHASED).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

HISTORY = Path(__file__).parent / "data" / "footfall_history.csv"


@st.cache_data(show_spinner=False)
def load() -> pd.DataFrame:
    """One row per shop and day with a count: Location, Date, Visitors,
    Purchased (as the sheet recorded them). A 0 is kept: a day with no
    walk-ins is a real count — whether it can stand is judged in daily()."""
    try:
        df = pd.read_csv(HISTORY, parse_dates=["Date"])
    except FileNotFoundError:
        return pd.DataFrame(columns=["Location", "Date", "Visitors", "Purchased"])
    return df


def daily(start_date, end_date) -> tuple[pd.DataFrame, int, bool]:
    """Every shop-day in the range: walk-ins counted beside the day's orders,
    ready for the Footfall Traffic page and the Reports page alike.

    Returns (frame, shop-days filled from the sheet, whether today was in the
    range and left out). Rules:
      * the Footfall module's count first; a missing one from the sheet history;
      * a history 0 on a day the shop sold nothing is dropped (not open);
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
        df.loc[gap, "Entered"] = "Sheet history"
        df = df.drop(columns="Sheet")
    for col in ("Orders", "Walk-in Orders", "Online Orders", "Other Orders", "Refunds",
                "Revenue", "Walk-in Revenue"):
        df[col] = df[col].fillna(0)
    closed = (df["Entered"] == "Sheet history") & (df["Visitors"] == 0) & (df["Orders"] == 0)
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
