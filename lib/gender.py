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
