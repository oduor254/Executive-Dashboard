"""Push classified Power Deal / Deal of the Week sales to the shared
deals-tracker Google Sheet, so the wider team can see offer performance
without opening the dashboard.

The sheet has two tables side by side on one worksheet:
  Power Deals        columns A:F (Date, Shops, Product, Quantity, Unit Price, Total)
  Deal of the Week    columns H:M (same layout)
Row 1 holds merged section titles, row 2 the column headers; data starts row 3.

Sync is manual (a button on the Offer Types tab) and replaces rows for the
dates being synced while leaving everything outside that range untouched —
re-syncing the same day is safe and self-corrects if a classification fix
changes past numbers.
"""
from __future__ import annotations

from datetime import date, datetime

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

from lib import config

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_MAX_ROWS = 5000  # generous headroom for a daily rollup table
_DATE_FMT = "%Y-%m-%d"

_TABLES = {
    "Power Deal": ("A", "F"),
    "Deal of the Week": ("H", "M"),
}
_COLUMNS = ["Date", "Shops", "Product", "Quantity", "Unit Price", "Total"]


def _require_config(name: str) -> str:
    value = config.get(name)
    if not value:
        raise RuntimeError(
            f"Missing {name}. Set it in .env (local) or Streamlit Cloud secrets."
        )
    return value


@st.cache_resource(show_spinner=False)
def _client() -> gspread.Client:
    info = config.get_gcp_service_account()
    if not info:
        raise RuntimeError(
            "Google service account not configured. Set GOOGLE_SERVICE_ACCOUNT_FILE "
            "in .env (local) or add a [gcp_service_account] table to Streamlit "
            "Cloud secrets — see .env.example / secrets.toml.example."
        )
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


def _worksheet() -> gspread.Worksheet:
    sheet_id = _require_config("DEALS_TRACKER_SHEET_ID")
    sh = _client().open_by_key(sheet_id)
    gid = config.get("DEALS_TRACKER_GID")
    if gid:
        return sh.get_worksheet_by_id(int(gid))
    return sh.sheet1


def _ensure_formatting(ws: gspread.Worksheet) -> None:
    """Force consistent number formats so the sheet reads cleanly for
    everyone, independent of whatever format a cell happened to inherit
    (Sheets otherwise displays the same underlying integer as "1" in one
    row and "1.00" in the next)."""
    ws.format(f"D3:D{_MAX_ROWS}", {"numberFormat": {"type": "NUMBER", "pattern": "0"}})
    ws.format(f"K3:K{_MAX_ROWS}", {"numberFormat": {"type": "NUMBER", "pattern": "0"}})
    for rng in (f"E3:F{_MAX_ROWS}", f"L3:M{_MAX_ROWS}"):
        ws.format(rng, {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}})


def _aggregate(df: pd.DataFrame, offer_type: str) -> pd.DataFrame:
    """One row per Date + Shop + Product for the given offer type."""
    sub = df[df["Offer Type"] == offer_type]
    if sub.empty:
        return pd.DataFrame(columns=_COLUMNS)

    agg = sub.groupby(["Date", "Location", "Product"], as_index=False).agg(
        Quantity=("Quantity", "sum"), Total=("Total", "sum")
    )
    agg["Unit Price"] = (agg["Total"] / agg["Quantity"]).round(2)
    agg["Total"] = agg["Total"].round(2)
    agg["Quantity"] = agg["Quantity"].round().astype(int)
    agg["Date"] = pd.to_datetime(agg["Date"]).dt.strftime(_DATE_FMT)
    agg = agg.rename(columns={"Location": "Shops"}).sort_values(["Date", "Shops", "Product"])
    return agg[_COLUMNS]


def _to_row_values(df: pd.DataFrame) -> list[list]:
    """Native Python types per cell — DataFrame.values.tolist() on mixed
    int/float/str columns can inconsistently render ints as e.g. "6.00"
    once round-tripped through numpy's common-dtype coercion."""
    return [
        [r["Date"], r["Shops"], r["Product"], int(r["Quantity"]), float(r["Unit Price"]), float(r["Total"])]
        for r in df.to_dict("records")
    ]


def _replace_range(
    ws: gspread.Worksheet, col_start: str, col_end: str,
    start_date: date, end_date: date, new_rows: pd.DataFrame,
) -> int:
    existing = ws.get(f"{col_start}3:{col_end}{_MAX_ROWS}") or []

    kept: list[list] = []
    for row in existing:
        if not row or not str(row[0]).strip():
            continue
        try:
            row_date = datetime.strptime(str(row[0]).strip(), _DATE_FMT).date()
        except ValueError:
            kept.append(row)  # not one of ours (or malformed) — leave it alone
            continue
        if not (start_date <= row_date <= end_date):
            kept.append(row)

    merged = kept + _to_row_values(new_rows)
    merged.sort(key=lambda r: (r[0], r[1] if len(r) > 1 else "", r[2] if len(r) > 2 else ""))

    ws.batch_clear([f"{col_start}3:{col_end}{_MAX_ROWS}"])
    if merged:
        ws.update(f"{col_start}3", merged, value_input_option="RAW")
    return len(new_rows)


def sync(classified_df: pd.DataFrame, start_date: date, end_date: date) -> dict[str, int]:
    """Write Power Deal and Deal of the Week rollups for [start_date, end_date].

    classified_df must already have gone through deals.classify() and be
    scoped to that same date range. Returns rows written per offer type.
    """
    ws = _worksheet()
    _ensure_formatting(ws)
    written: dict[str, int] = {}
    for offer_type, (col_start, col_end) in _TABLES.items():
        agg = _aggregate(classified_df, offer_type)
        written[offer_type] = _replace_range(ws, col_start, col_end, start_date, end_date, agg)
    return written
