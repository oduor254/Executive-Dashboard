"""Daily sales training: the team's answers to the daily questionnaire.

Each month has its own Google Sheet ("October 2026 Sales Team
Questionaires"), with one tab per questionnaire ("12th October") holding the
form's responses — Timestamp, Email address, Name, Location, Score ("80 /
100") and the questions — and a team list tab (email, name, location, no
header) of everyone expected to answer.

People are matched on their email address, which the form records for them;
the team list says where they work. An answer counts for the day of the
questionnaire it was given to, whenever it was sent, and is "on time" when
sent the same day. An email a letter or two off the team list is matched to
the person it belongs to. A tab that is an exact copy of another (October's "2nd
October" repeats "3rd October" row for row) is skipped, and today's
questionnaire is still open, so nobody is counted as missing it yet.
"""
from __future__ import annotations

import difflib
import re
import time
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

from lib import feedback, sheets_sync

# One sheet per month; add each new month's sheet here.
SPREADSHEETS = [
    "1PWv6NoxgCF0bBaJZZUql0eoBiBK5E3_6nvNvzIkwJ30",   # October 2026
]
ROSTER_TAB = "Sheet1"
# Team-list and form locations, named as the rest of the dashboard names them.
LOCATION_NAMES = {"ktda": "Ktda", "ktda shop": "Ktda", "dar-es-alam": "Sinza"}

_TAB_DAY = re.compile(r"^\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)", re.IGNORECASE)
_SCORE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*$")
_META = {"timestamp", "email address", "score", "name", "location"}
_RETRIES = 4


class TrainingUnavailable(Exception):
    """The sheet could not be read; the message says what to do about it."""


def location(raw) -> str:
    text = str(raw or "").strip()
    return LOCATION_NAMES.get(text.lower(), text.title()) if text else "Not recorded"


def _with_retries(fetch):
    for attempt in range(_RETRIES):
        try:
            return fetch()
        except Exception as exc:  # Google's 429/503s pass with a pause
            if attempt == _RETRIES - 1 or "PERMISSION" in str(exc).upper():
                raise
            time.sleep(2 ** attempt)


def _tab_date(title: str, year: int) -> date | None:
    m = _TAB_DAY.match(title)
    if not m:
        return None
    try:
        return pd.Timestamp(f"{m.group(1)} {m.group(2)} {year}").date()
    except ValueError:
        return None


def _read_responses(title: str, values: list[list[str]], day: date) -> pd.DataFrame:
    header = [h.strip() for h in values[0]]
    low = [h.lower() for h in header]
    rows = pd.DataFrame([r + [""] * (len(header) - len(r)) for r in values[1:]],
                        columns=range(len(header)))
    if rows.empty:
        return pd.DataFrame()

    def find(word):
        return next((i for i, h in enumerate(low) if h == word), None)

    score_col = find("score")
    if score_col is None:  # the column whose values read "80 / 100"
        score_col = next((i for i in range(len(header))
                          if rows[i].astype(str).str.match(_SCORE).mean() > 0.5), None)
    name_col, loc_col = find("name"), find("location")
    if name_col is None or loc_col is None:
        # Unnamed columns ("Column 9", "Column 10") in the leading block are
        # the name and location, in that order.
        spare = [i for i in range(min(5, len(header)))
                 if i not in (0, 1, score_col) and low[i] not in _META]
        name_col = spare[0] if name_col is None and spare else name_col
        loc_col = spare[1] if loc_col is None and len(spare) > 1 else loc_col
    questions = [i for i in range(len(header))
                 if i not in (0, 1, score_col, name_col, loc_col)
                 and rows[i].astype(str).str.strip().ne("").any()]

    scores = rows[score_col].astype(str).str.extract(_SCORE).astype(float) \
        if score_col is not None else pd.DataFrame({0: [float("nan")] * len(rows),
                                                    1: [float("nan")] * len(rows)})
    answered = rows[questions].astype(str).apply(lambda c: c.str.strip().ne("")).sum(axis=1)
    out = pd.DataFrame({
        "Day": day,
        "Tab": title,
        "Submitted": pd.to_datetime(rows[0], dayfirst=True, errors="coerce"),
        "Email": rows[1].astype(str).str.strip().str.lower(),
        "Typed Name": rows[name_col].astype(str).str.strip() if name_col is not None else "",
        "Typed Location": rows[loc_col].map(location) if loc_col is not None else "Not recorded",
        "Score %": (scores[0] / scores[1] * 100).round(1),
        "Questions": len(questions),
        "Answered": answered,
    })
    out["Completion %"] = (out["Answered"] / out["Questions"].where(out["Questions"] > 0)
                           * 100).round(1)
    out["On Time"] = out["Submitted"].dt.date == day
    return out[out["Email"].ne("")]


@st.cache_data(ttl=600, show_spinner="Reading the sales training sheet…")
def load() -> dict:
    """{"responses": one row per answer, "roster": the team list,
    "days": every questionnaire day, "skipped": copied tabs left out}."""
    client = sheets_sync._client()
    frames, roster_rows, days, skipped = [], [], set(), []
    for sheet_id in SPREADSHEETS:
        try:
            sheet = _with_retries(lambda: client.open_by_key(sheet_id))
            tabs = {ws.title: _with_retries(ws.get_all_values) for ws in sheet.worksheets()}
        except Exception as exc:
            raise TrainingUnavailable(
                f"Could not read the sales training sheet ({exc}). Share it with "
                f"{feedback.service_account_email()} as a Viewer.") from exc
        year_match = re.search(r"(20\d\d)", sheet.title)
        year = int(year_match.group(1)) if year_match else date.today().year
        seen: dict[frozenset, str] = {}
        for title, values in tabs.items():
            if title.strip().lower() == ROSTER_TAB.lower():
                roster_rows += [r[:3] for r in values if len(r) >= 3 and "@" in r[0]]
                continue
            day = _tab_date(title, year)
            if day is None or not values:
                continue
            fingerprint = frozenset(tuple(r[:2]) for r in values[1:])
            if fingerprint and fingerprint in seen:
                skipped.append(f"{title} (a copy of {seen[fingerprint]})")
                continue
            seen[fingerprint] = title
            days.add(day)
            frames.append(_read_responses(title, values, day))

    roster = pd.DataFrame(roster_rows, columns=["Email", "Name", "Location"])
    roster["Email"] = roster["Email"].str.strip().str.lower()
    roster["Name"] = roster["Name"].str.strip().str.rstrip("-").str.title()
    roster["Location"] = roster["Location"].map(location)
    roster = roster.drop_duplicates("Email")

    responses = pd.concat([f for f in frames if not f.empty], ignore_index=True) \
        if any(not f.empty for f in frames) else pd.DataFrame()
    if not responses.empty:
        # One answer per person per questionnaire: the first sent.
        responses = (responses.sort_values("Submitted")
                     .drop_duplicates(["Day", "Email"], keep="first"))
        team = roster.set_index("Email")
        # An email typed a letter or two off the team list is that person
        # ("vivianekadesa2017@" for "viviankadesa2017@").
        known = list(team.index)
        responses["Email"] = responses["Email"].map(
            lambda e: e if e in team.index
            else next(iter(difflib.get_close_matches(e, known, n=1, cutoff=0.9)), e))
        responses = responses.drop_duplicates(["Day", "Email"], keep="first")
        responses["On List"] = responses["Email"].isin(team.index)
        responses["Name"] = responses["Email"].map(team["Name"]).fillna(
            responses["Typed Name"].str.title())
        responses["Location"] = responses["Email"].map(team["Location"]).fillna(
            responses["Typed Location"])
    return {"responses": responses, "roster": roster, "days": sorted(days),
            "skipped": skipped}


def due(data: dict, days: list[date]) -> pd.DataFrame:
    """Everyone on the team list against every questionnaire in `days`:
    whether they answered it and, if so, how they did."""
    roster, responses = data["roster"], data["responses"]
    rows = roster.assign(_k=1).merge(pd.DataFrame({"Day": days, "_k": 1}), on="_k").drop(columns="_k")
    cols = ["Score %", "Completion %", "On Time"]
    if rows.empty or responses.empty:
        return rows.assign(Answered=False, **{c: np.nan for c in cols})
    got = responses.set_index(["Email", "Day"])[cols]
    rows = rows.join(got, on=["Email", "Day"])
    rows["Answered"] = rows["Score %"].notna() | rows["Completion %"].notna()
    for c in cols:
        rows[c] = pd.to_numeric(rows[c].astype(object), errors="coerce")
    return rows


def training_score(rows: pd.DataFrame) -> float:
    """Every questionnaire due at the score it got, a missed one at 0."""
    return float(rows["Score %"].fillna(0).mean()) if len(rows) else float("nan")


def _tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", str(name).lower()) if len(t) >= 3}


def _likeness(wanted: set[str], name: str, email: str) -> int:
    """Name parts shared with a team-list entry, counting a part found inside
    the email ("tobbyogare@" holds Tobias Ogare's "ogare")."""
    local = email.split("@")[0].lower()
    return sum(1 for t in wanted if t in _tokens(name) or t in local)


def match_person(name: str, shop: str, roster: pd.DataFrame) -> str | None:
    """The team-list email of an attendant known by their Odoo name.

    The person at the same shop sharing the most name parts ("Nyangor Laura"
    is "Laura Nyangor"), counting parts found in their email ("Faith Dawe" is
    "chun", faithdawe65@). Someone serving away from their listed shop is
    found anywhere when two or more parts match. None when nothing matches
    or two people tie.
    """
    wanted = _tokens(re.sub(r"\(BA\)", "", str(name)))
    if not wanted:
        return None

    def best(frame: pd.DataFrame, minimum: int) -> str | None:
        scored = sorted(((_likeness(wanted, n, e), e) for n, e in zip(frame["Name"], frame["Email"])),
                        reverse=True)
        if not scored or scored[0][0] < minimum or (len(scored) > 1 and scored[1][0] == scored[0][0]):
            return None
        return scored[0][1]

    return best(roster[roster["Location"] == shop], 1) or best(roster, 2)
