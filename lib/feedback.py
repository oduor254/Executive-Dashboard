"""Customer feedback, read from the same Google Sheet the POS Request Hub uses.

The Request Hub looks a customer up in this sheet to decide whether they
qualify for the feedback discount; the sheet itself never reaches Odoo (only
the handful of redemptions do, in pos_feedback_redemption). So the dashboard
reads the sheet directly, finding its columns by the same header words the
Request Hub is configured with, and matches people on the last nine digits of
their phone number — the form takes the number however the customer types it.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import sheets_sync

SPREADSHEET_ID = "1gGcfdwsmjxsDz0PQlpHP_V3FEHncMpSbRzrsQ3gYdCY"
WORKSHEET = "Customer feedback"

# Header words, as configured for the Request Hub in Odoo
# (denri_pos_request_hub.sheets_col_*): a column is the first header that
# contains the word, so a form question reworded around it still matches.
_COLUMNS = {
    "Submitted": "timestamp",
    "Name": "first name",
    "Phone": "phone number",
    "Email": "email address",
    "Branch": "which of our branches",
    "Status": "status",
}


class FeedbackUnavailable(Exception):
    """The sheet could not be read; the message says what to do about it."""


def service_account_email() -> str:
    from lib import config
    info = config.get_gcp_service_account() or {}
    return info.get("client_email", "the dashboard's Google service account")


def phone_key(value) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-9:] if len(digits) >= 9 else None


def _parse_timestamps(raw: pd.Series) -> pd.Series:
    """Google Forms writes month-first; fall back to day-first if that fails."""
    first = pd.to_datetime(raw, errors="coerce")
    if first.notna().mean() >= 0.8:
        return first
    second = pd.to_datetime(raw, errors="coerce", dayfirst=True)
    return second if second.notna().sum() > first.notna().sum() else first


@st.cache_data(ttl=600, show_spinner="Reading customer feedback…")
def load() -> pd.DataFrame:
    """Every feedback response: Submitted, Name, Phone, Email, Branch, Status, Phone Key."""
    try:
        sheet = sheets_sync._client().open_by_key(SPREADSHEET_ID)
        values = sheet.worksheet(WORKSHEET).get_all_values()
    except PermissionError as exc:
        raise FeedbackUnavailable(
            f"The feedback sheet is not shared with {service_account_email()}."
        ) from exc
    except Exception as exc:  # gspread raises its own types for a missing tab, quota, etc.
        raise FeedbackUnavailable(f"Could not read the feedback sheet: {exc}") from exc

    if len(values) < 2:
        return pd.DataFrame(columns=[*_COLUMNS, "Phone Key"])
    header = [h.strip().lower() for h in values[0]]
    rows = pd.DataFrame(values[1:])

    out = pd.DataFrame(index=rows.index)
    for name, word in _COLUMNS.items():
        position = next((i for i, h in enumerate(header) if word in h), None)
        out[name] = rows[position].astype(str).str.strip() if position is not None else ""
    out["Submitted"] = _parse_timestamps(out["Submitted"])
    out["Phone Key"] = out["Phone"].map(phone_key)
    return out[out["Phone Key"].notna() | out["Name"].ne("")]
