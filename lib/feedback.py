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
# Experience is the overall rating (1-5), Assistance the rating of the
# staff's help (1-5, reported as Professionalism), Source how the customer
# came (Walk-In / Online). A tab without a column leaves it blank.
_TABS = {
    WORKSHEET: {"Submitted": ["timestamp"], "Name": ["first name"],
                "Phone": ["phone number"], "Branch": ["which of our branches"],
                "Experience": ["overall, how would you rate"],
                "Assistance": ["assistance you received from our staff"],
                "Source": ["source"]},
    "Uganda":  {"Submitted": ["timestamp"], "Name": ["first name"],
                "Phone": ["phone"], "Branch": ["branch"],
                "Experience": ["satisfied were you with your overall experience"],
                "Assistance": ["assistance you received"], "Source": ["source"]},
    "Kampala": {"Submitted": ["timestamp"], "Name": ["first name"],
                "Phone": ["phone"], "Branch": ["branch"],
                "Experience": ["satisfied were you with your overall experience"],
                "Assistance": ["assistance you received"], "Source": ["source"]},
    "Sinza":   {"Submitted": ["timestamp"], "Name": ["jina la kwanza"],
                "Phone": ["nambari ya simu"], "Branch": ["tawi"],
                "Experience": ["kuridhika na uzoefu"], "Assistance": ["msaada uliopokea"],
                "Source": ["aina ya mteja"]},
    # Walk-in inquiry forms: no ratings, but the sheet's own Report counts
    # them among the day's feedback responses, so they are read too.
    "Inquiries": {"Submitted": ["timestamp"], "Name": ["first name"], "Phone": ["phone"],
                  "Branch": ["branch"], "Experience": ["\x00"], "Assistance": ["\x00"],
                  "Source": ["\x00"]},
}
# The sheet's Report tab rates Overall Experience and Professionalism from the
# main form only; the response counts take every form above.
RATED_FORM = WORKSHEET
_FIELDS = ["Submitted", "Name", "Phone", "Branch", "Experience", "Assistance", "Source"]
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


def _column_letter(index: int) -> str:
    letters, n = "", index + 1
    while n:
        n, r = divmod(n - 1, 26)
        letters = chr(65 + r) + letters
    return letters


def _read_forms(sheet) -> list[pd.DataFrame]:
    """Each form's responses, only the columns the dashboard uses.

    The forms ask a dozen-odd questions, and 20,000+ responses of all of
    them is most of the download; so the header rows come first (one
    request), then just the needed columns of every tab (one more)."""
    existing = {ws.title.strip().lower(): ws.title for ws in sheet.worksheets()}
    tabs = [(existing[t.lower()], words) for t, words in _TABS.items() if t.lower() in existing]
    if not tabs:
        return []
    quote = lambda t: "'" + t.replace("'", "''") + "'"
    headers = sheet.values_batch_get([f"{quote(t)}!1:1" for t, _ in tabs]).get("valueRanges", [])
    wanted = []                                   # (tab, field, column letter)
    for (title, words), block in zip(tabs, headers):
        header = [str(h).strip().lower() for h in (block.get("values") or [[]])[0]]
        for field in _FIELDS:
            position = next((i for i, h in enumerate(header)
                             if any(w in h for w in words[field])), None)
            if position is not None:
                wanted.append((title, field, _column_letter(position)))
    columns = sheet.values_batch_get(
        [f"{quote(t)}!{c}2:{c}" for t, _, c in wanted],
        params={"majorDimension": "COLUMNS"}).get("valueRanges", []) if wanted else []
    found: dict[str, dict[str, list]] = {}
    for (title, field, _), block in zip(wanted, columns):
        found.setdefault(title, {})[field] = [str(v) for v in (block.get("values") or [[]])[0]]
    frames = []
    for title, _ in tabs:
        cols = found.get(title, {})
        n = max((len(v) for v in cols.values()), default=0)
        if not n:
            continue
        out = pd.DataFrame({f: pd.Series(cols.get(f, []) + [""] * (n - len(cols.get(f, []))))
                            .astype(str).str.strip().astype(object) for f in _FIELDS})
        out["Form"] = title
        out["Form"] = out["Form"].astype(object)
        frames.append(out)
    return frames


@st.cache_data(ttl=600, show_spinner="Reading customer feedback…")
def load() -> pd.DataFrame:
    """Every feedback response: Submitted, Name, Phone, Branch, Form, Phone Key."""
    try:
        sheet = _with_retries(lambda: sheets_sync._client().open_by_key(SPREADSHEET_ID))
        # Three requests in all: the tab list, the header rows, the needed
        # columns (it was a tab list and a full read per tab, four times over).
        frames = _with_retries(lambda: _read_forms(sheet))
    except PermissionError as exc:
        raise FeedbackUnavailable(
            f"The feedback sheet is not shared with {service_account_email()}."
        ) from exc
    except Exception as exc:  # quota, a missing tab, Google being unavailable
        raise FeedbackUnavailable(f"Could not read the feedback sheet: {exc}") from exc

    if not frames:
        raise FeedbackUnavailable("The feedback sheet has none of the expected form tabs.")
    out = pd.concat(frames, ignore_index=True)
    out = out[out["Submitted"].ne("")]
    out["Submitted"] = _parse_timestamps(out["Submitted"])
    out["Phone Key"] = out["Phone"].map(phone_key)
    return out.reset_index(drop=True)
