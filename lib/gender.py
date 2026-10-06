"""Local first-name -> gender fallback, applied after the SQL-side lookup.

Grows independently of the database (lib/data/gender_names.csv) so coverage
can improve over time without needing write access to Postgres.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

CSV_PATH = Path(__file__).parent / "data" / "gender_names.csv"

# When a shop merges two names into one field with no separator (e.g. "JohnMary"),
# the SQL side's INITCAP has already flattened casing by the time it reaches us
# (both become "Johnmary"), so we can't split on a capital-letter boundary. Instead,
# treat it as merged if a known name is a prefix of the token, and use that name's
# gender. Bounds avoid matching on trivially short, coincidental substrings.
MIN_PREFIX_LEN = 3
MIN_REMAINDER_LEN = 2


@st.cache_data(show_spinner=False)
def _load_lookup() -> dict[str, str]:
    df = pd.read_csv(CSV_PATH)
    return {str(name).strip().lower(): gender for name, gender in zip(df["name"], df["gender"])}


# What staff have recorded is the better guide to a name's gender here than
# the general name list: across 28,219 customers recorded male or female (Oct
# 2026), 21 first names with 3+ consistent records disagreed with the list —
# Valentine 96% female over 48 records, Flavian and Terry female, Teddy, Sean
# and Lee male. A name needs this many records, this one-sided, to count.
LEARNED_MIN_RECORDS = 3
LEARNED_MIN_SHARE = 0.8

_RECORDED_GENDERS = """
SELECT rp.name, LOWER(TRIM(rp.gender)) AS gender
FROM res_partner rp
WHERE LOWER(TRIM(COALESCE(rp.gender, ''))) IN ('male', 'female')
"""


@st.cache_data(ttl=86400, show_spinner=False)
def _learned() -> dict[str, tuple[str | None, int]]:
    """First name -> (gender it reliably is, or None if records are split; record count)."""
    from lib import db, names
    rows = db.run_query(_RECORDED_GENDERS)
    if rows.empty:
        return {}
    rows["first"] = rows["name"].map(names.clean).str.split().str[0].str.lower()
    rows = rows[rows["first"].notna() & (rows["first"] != "n/a")]
    out = {}
    for first, g in rows.groupby("first")["gender"]:
        share = (g == "female").mean()
        sure = None
        if len(g) >= LEARNED_MIN_RECORDS:
            sure = "Female" if share >= LEARNED_MIN_SHARE else "Male" if share <= 1 - LEARNED_MIN_SHARE else None
        out[first] = (sure, len(g))
    return out


def _expected(token: str, lookup: dict[str, str], learned: dict) -> tuple[str, bool]:
    """(gender a first name implies, whether that is reliable enough to flag a
    recorded value against).

    Recorded data first; then the name list, exact matches only. A name staff
    have recorded both ways, or only once or twice, is not reliable — Yvon
    (once, female) and Flavin (twice, split) were being called male by the
    list. Prefix guesses ("Doricas" via "Doric") are never reliable.
    """
    key = str(token).strip().lower()
    if not key:
        return "N/A", False
    if key in learned:
        sure, count = learned[key]
        if sure:
            return sure, True
        if count:
            return "N/A", False
    if key in lookup:
        return lookup[key], True
    return _resolve(token, lookup), False


def _resolve(token: str, lookup: dict[str, str]) -> str:
    key = str(token).strip().lower()
    if not key:
        return "N/A"
    if key in lookup:
        return lookup[key]

    longest_prefix = len(key) - MIN_REMAINDER_LEN
    for split in range(longest_prefix, MIN_PREFIX_LEN - 1, -1):
        prefix = key[:split]
        if prefix in lookup:
            return lookup[prefix]
    return "N/A"


def apply_gender_fallback(df: pd.DataFrame) -> pd.DataFrame:
    """Fill Gender == 'N/A' rows from the local lookup, keyed on First Name.

    Tries an exact match first, then an "unmerged" prefix match for names a
    shop concatenated with a second name (see module docstring).
    """
    lookup = _load_lookup()
    learned = _learned()
    df = df.copy()
    unresolved = df["Gender"] == "N/A"
    df.loc[unresolved, "Gender"] = df.loc[unresolved, "First Name"].apply(
        lambda n: _expected(n, lookup, learned)[0])
    return df


def top_unmapped_names(df: pd.DataFrame, n: int = 25) -> pd.Series:
    """Most frequent first names still unresolved after both lookups."""
    unresolved = df.loc[df["Gender"] == "N/A", "First Name"]
    unresolved = unresolved[unresolved.str.strip() != ""]
    return unresolved.value_counts().head(n)


def find_mismatches(df: pd.DataFrame, n: int | None = None) -> pd.DataFrame:
    """Rows where the recorded Gender (keyed in by staff) disagrees with what
    the name-based lookup would predict — e.g. "John" recorded as Female.

    Only flags cases where the lookup has a confident, different opinion; a
    recorded value with no lookup match at all isn't a mismatch. The list of
    records to change in Odoo; correct_recorded applies the same rule to the
    dashboard's figures.
    """
    lookup = _load_lookup()
    learned = _learned()
    # Male/female only: "Corporate" is an account type, not a gender to check.
    recorded = df[df["Gender"].isin(["Male", "Female"])].copy()
    columns = ["Location", "Name", "Phone", "First Name", "Recorded Gender",
               "Name-Implied Gender", "Occurrences"]
    if recorded.empty:
        return pd.DataFrame(columns=columns)

    expected = recorded["First Name"].apply(lambda n: _expected(n, lookup, learned))
    recorded["Name-Implied Gender"] = expected.str[0]
    reliable = expected.str[1].astype(bool)
    mismatches = recorded[
        reliable
        & (recorded["Name-Implied Gender"] != "N/A")
        & (recorded["Name-Implied Gender"] != recorded["Gender"])
    ]
    if mismatches.empty:
        return pd.DataFrame(columns=columns)

    summary = (
        # By phone as well as name: two customers both called "Mercy" are two
        # records to check, and the phone is how they are found in Odoo.
        # Location first, so each shop can pick out its own records; a
        # customer served at several shops lists them all.
        mismatches.groupby(["Name", "Phone", "First Name", "Gender", "Name-Implied Gender"])
        .agg(Location=("Location", lambda v: ", ".join(sorted(set(v.dropna())))),
             Occurrences=("Location", "size"))
        .reset_index()
        .rename(columns={"Gender": "Recorded Gender"})
        .sort_values(["Location", "Occurrences"], ascending=[True, False])
    )[columns]
    if n is not None:
        summary = summary.head(n)
    return summary


def correct_recorded(df: pd.DataFrame) -> pd.DataFrame:
    """Use the name's gender where staff recorded the opposite one — "John"
    saved as Female counts as Male on the dashboard. Only reliable
    expectations override (see _expected), so a name staff record both ways,
    or one the list doesn't know exactly, keeps what was recorded. The
    original value is kept in "Recorded Gender" for the corrections table.
    """
    lookup = _load_lookup()
    learned = _learned()
    df = df.copy()
    df["Recorded Gender"] = df["Gender"]
    recorded = df["Gender"].isin(["Male", "Female"])
    if not recorded.any():
        return df
    expected = df.loc[recorded, "First Name"].apply(lambda n: _expected(n, lookup, learned))
    implied = expected.str[0]
    wrong = expected.str[1].astype(bool) & implied.isin(["Male", "Female"]) & (
        implied != df.loc[recorded, "Gender"])
    df.loc[wrong[wrong].index, "Gender"] = implied[wrong]
    return df
