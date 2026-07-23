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
    df = df.copy()
    unresolved = df["Gender"] == "N/A"
    df.loc[unresolved, "Gender"] = df.loc[unresolved, "First Name"].apply(_resolve, lookup=lookup)
    return df


def top_unmapped_names(df: pd.DataFrame, n: int = 25) -> pd.Series:
    """Most frequent first names still unresolved after both lookups."""
    unresolved = df.loc[df["Gender"] == "N/A", "First Name"]
    unresolved = unresolved[unresolved.str.strip() != ""]
    return unresolved.value_counts().head(n)


def find_mismatches(df: pd.DataFrame, n: int = 25) -> pd.DataFrame:
    """Rows where the recorded Gender (keyed in by staff) disagrees with what
    the name-based lookup would predict — e.g. "John" recorded as Female.

    Only flags cases where the lookup has a confident, different opinion; a
    recorded value with no lookup match at all isn't a mismatch. Meant as a
    data-entry cross-check, not a correction — recorded values are never
    changed based on this.
    """
    lookup = _load_lookup()
    recorded = df[df["Gender"] != "N/A"].copy()
    if recorded.empty:
        return recorded.iloc[0:0][["Name", "First Name", "Gender"]].rename(
            columns={"Gender": "Recorded Gender"}
        ).assign(**{"Name-Implied Gender": [], "Occurrences": []})

    recorded["Name-Implied Gender"] = recorded["First Name"].apply(_resolve, lookup=lookup)
    mismatches = recorded[
        (recorded["Name-Implied Gender"] != "N/A")
        & (recorded["Name-Implied Gender"] != recorded["Gender"])
    ]
    if mismatches.empty:
        return mismatches[["Name", "First Name", "Gender", "Name-Implied Gender"]].rename(
            columns={"Gender": "Recorded Gender"}
        ).assign(Occurrences=[])

    summary = (
        mismatches.groupby(["Name", "First Name", "Gender", "Name-Implied Gender"])
        .size()
        .reset_index(name="Occurrences")
        .rename(columns={"Gender": "Recorded Gender"})
        .sort_values("Occurrences", ascending=False)
        .head(n)
    )
    return summary
