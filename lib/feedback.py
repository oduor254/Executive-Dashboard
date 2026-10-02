"""Customer feedback, read from the same Google Sheet the POS Request Hub uses.

The Request Hub looks a customer up in this sheet to decide whether they
qualify for the feedback discount; the sheet itself never reaches Odoo (only
the redemptions do, in pos_feedback_redemption). So the dashboard reads the
sheet directly and matches people on the last nine digits of their phone
number — the form takes the number however the customer types it.

Besides the main "Customer Feedback" form (Kenya), the sheet carries its own
forms for Uganda, Kampala and Sinza (the Sinza one in Swahili). They are read
too, so an attendant at those shops is credited for their customers' feedback.
"""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from lib import sheets_sync

SPREADSHEET_ID = "1gGcfdwsmjxsDz0PQlpHP_V3FEHncMpSbRzrsQ3gYdCY"
WORKSHEET = "Customer Feedback"

# Each tab and the header words its columns are found by: the first header
# containing any of the words, so a form question reworded around it still
# matches. The main tab's words are the ones the Request Hub is configured
# with in Odoo (denri_pos_request_hub.sheets_col_*).
_TABS = {
    WORKSHEET: {"Submitted": ["timestamp"], "Name": ["first name"],
                "Phone": ["phone number"], "Branch": ["which of our branches"]},
    "Uganda":  {"Submitted": ["timestamp"], "Name": ["first name"],
                "Phone": ["phone"], "Branch": ["branch"]},
    "Kampala": {"Submitted": ["timestamp"], "Name": ["first name"],
                "Phone": ["phone"], "Branch": ["branch"]},
    "Sinza":   {"Submitted": ["timestamp"], "Name": ["jina la kwanza"],
                "Phone": ["nambari ya simu"], "Branch": ["tawi"]},
}
_FIELDS = ["Submitted", "Name", "Phone", "Branch"]
_RETRIES = 4


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
    """The forms write day-first (02/10/2026 is 2 October); anything that
    does not fit that is tried as a general date."""
    parsed = pd.to_datetime(raw, format="%d/%m/%Y %H:%M:%S", errors="coerce")
    rest = parsed.isna() & raw.str.strip().ne("")
    if rest.any():
        parsed[rest] = pd.to_datetime(raw[rest], errors="coerce", dayfirst=True)
    return parsed


def _with_retries(fetch):
    """Google answers the odd read with a temporary 5xx; try again before giving up."""
    for attempt in range(_RETRIES):
        try:
            return fetch()
        except PermissionError:
            raise
        except Exception:
            if attempt == _RETRIES - 1:
                raise
            time.sleep(3 * (attempt + 1))


def _read_tab(sheet, title: str, words: dict[str, list[str]]) -> pd.DataFrame:
    tabs = {ws.title.strip().lower(): ws for ws in sheet.worksheets()}
    ws = tabs.get(title.lower())
    if ws is None:
        return pd.DataFrame(columns=_FIELDS + ["Form"])
    values = _with_retries(ws.get_all_values)
    if len(values) < 2:
        return pd.DataFrame(columns=_FIELDS + ["Form"])
    header = [h.strip().lower() for h in values[0]]
    rows = pd.DataFrame(values[1:])
    out = pd.DataFrame(index=rows.index)
    for field in _FIELDS:
        position = next((i for i, h in enumerate(header)
                         if any(w in h for w in words[field])), None)
        out[field] = rows[position].astype(str).str.strip() if position is not None else ""
    out["Form"] = ws.title
    return out


@st.cache_data(ttl=600, show_spinner="Reading customer feedback…")
def load() -> pd.DataFrame:
    """Every feedback response: Submitted, Name, Phone, Branch, Form, Phone Key."""
    try:
        sheet = _with_retries(lambda: sheets_sync._client().open_by_key(SPREADSHEET_ID))
        frames = [_read_tab(sheet, title, words) for title, words in _TABS.items()]
    except PermissionError as exc:
        raise FeedbackUnavailable(
            f"The feedback sheet is not shared with {service_account_email()}."
        ) from exc
    except Exception as exc:  # quota, a missing tab, Google being unavailable
        raise FeedbackUnavailable(f"Could not read the feedback sheet: {exc}") from exc

    out = pd.concat(frames, ignore_index=True)
    out = out[out["Submitted"].ne("")]
    out["Submitted"] = _parse_timestamps(out["Submitted"])
    out["Phone Key"] = out["Phone"].map(phone_key)
    return out.reset_index(drop=True)
