"""Odoo pricelist promotions, and an archive of them.

Deals are entered in Odoo as dated pricelist rules — a fixed price for a
product, at the shops one pricelist serves, between two dates. That is a
better record than the spreadsheet in two ways: the till applies it
automatically (where a dated rule exists the deal price was charged 96.4% of
the time, against manual shops that sold 77 bags in a week at full price
despite being listed), and it needs no separate data entry to reach reporting.

But Odoo keeps only the CURRENT state of a rule. Rules get edited in place
(47 of the 63 May rules were), deactivated (47 already are), and replaced
wholesale each tier — when this module was written the only live window was
12-26 September, with no trace of the 1-11 September tier that preceded it.
Reading Odoo alone therefore answers "what is on offer now" but not "what was
on offer then", and a dashboard that reports on past months needs the second.

So every snapshot is appended to lib/data/pricelist_history.csv, keyed on the
rule and its price. An edited price appears as a new row beside the old one
rather than replacing it, so the archive accumulates what was true at each
point even as Odoo moves on.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from lib import db, queries

_DATA_DIR = Path(__file__).parent / "data"
ARCHIVE_FILE = "pricelist_history.csv"

# What identifies one rule-at-a-price. Price is part of the key deliberately:
# repricing a rule should record a new fact, not overwrite the old one.
_KEY = ["Pricelist", "Product", "Starts", "Ends", "Rule Price"]

# Deal of the Week runs in two tiers a month, one per half. The tier is read
# off the data rather than configured, so a shifted window still lands in the
# right half without anyone maintaining a calendar.
#
# Judged on the window's MIDPOINT, not its start: the live window runs 12-26
# September, which starts in the first half but plainly belongs to the second.
# The midpoint (the 19th) puts it where it actually sits.
_FIRST_HALF_ENDS = 15

# Till names as Odoo holds them -> the Location names the sales queries report.
_TILL_OVERRIDES = {
    "DAR-ES-ALAM": "Sinza",
    "SINZA": "Sinza",
    "KTDA SHOP": "Ktda",
    "WEBSITE SALES": "Website",
    "UGANDDA": "Uganda",
}


def tier_of(starts, ends=None) -> str:
    """Which half of the month a promotion window belongs to."""
    start = pd.Timestamp(starts)
    end = pd.Timestamp(ends) if ends is not None else start
    midpoint = start + (end - start) / 2
    return "First half" if midpoint.day <= _FIRST_HALF_ENDS else "Second half"


def window_label(starts, ends) -> str:
    """The window itself, e.g. "12-26 Sep" — unambiguous where a tier name
    has to round a fortnight into one half or the other."""
    start, end = pd.Timestamp(starts), pd.Timestamp(ends)
    if start.month == end.month:
        return f"{start.day}-{end.day} {start:%b}"
    return f"{start.day} {start:%b} - {end.day} {end:%b}"


def locations_of(tills: str | None) -> list[str]:
    """The Location names a pricelist's tills correspond to."""
    if not tills or pd.isna(tills):
        return []
    out = []
    for till in str(tills).split(","):
        name = till.strip()
        if not name:
            continue
        mapped = _TILL_OVERRIDES.get(name.upper())
        if mapped is None:
            # Same shape the sales queries use: drop a trailing "Shop", title-case.
            mapped = name.replace("Shop", "").replace("SHOP", "").strip().title()
        if mapped and mapped not in out:
            out.append(mapped)
    return out


def _read_archive() -> pd.DataFrame:
    path = _DATA_DIR / ARCHIVE_FILE
    if not path.exists():
        return pd.DataFrame(columns=[*_KEY, "Currency", "Active", "Tills", "First Seen"])
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def load() -> pd.DataFrame:
    """The archive, as stored."""
    return _read_archive()


def snapshot() -> dict:
    """Fold Odoo's current dated rules into the archive. Returns a summary."""
    live = db.run_query(queries.PRICELIST_RULES)
    if live.empty:
        return {"seen": 0, "new": 0, "total": 0}

    live = live.copy()
    for col in ("Starts", "Ends"):
        live[col] = pd.to_datetime(live[col]).dt.date.astype(str)
    live["First Seen"] = datetime.now().isoformat(timespec="seconds")

    keep = [*_KEY, "Currency", "Active", "Tills", "First Seen"]
    live = live[[c for c in keep if c in live.columns]]

    existing = _read_archive()
    merged = pd.concat([existing, live], ignore_index=True)
    # First Seen is when we FIRST recorded the rule, so the older row wins.
    merged = merged.drop_duplicates(subset=_KEY, keep="first")
    merged = merged.sort_values(["Starts", "Pricelist", "Product"])

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(_DATA_DIR / ARCHIVE_FILE, index=False)
    load.clear()

    return {"seen": len(live), "new": len(merged) - len(existing), "total": len(merged)}


def deals_in_window(start_date, end_date) -> pd.DataFrame:
    """Archived rules that were live at any point in [start_date, end_date],
    one row per shop the rule applied to.

    Overlap, not containment: a rule running 12-26 September is part of what
    was on offer in the first week of a "September" report even though it does
    not cover the whole month.
    """
    arc = load()
    empty = pd.DataFrame(columns=["Location", "Product", "Rule Price", "Starts",
                                  "Ends", "Tier", "Window", "Pricelist"])
    if arc.empty:
        return empty

    arc = arc.copy()
    arc["Starts"] = pd.to_datetime(arc["Starts"], errors="coerce")
    arc["Ends"] = pd.to_datetime(arc["Ends"], errors="coerce")
    window = arc[(arc["Starts"] <= pd.Timestamp(end_date))
                 & (arc["Ends"] >= pd.Timestamp(start_date))]
    if window.empty:
        return empty

    rows = []
    for _, r in window.iterrows():
        for loc in locations_of(r.get("Tills")):
            rows.append({
                "Location": loc,
                "Product": r["Product"],
                "Rule Price": r["Rule Price"],
                "Starts": r["Starts"].date(),
                "Ends": r["Ends"].date(),
                "Tier": tier_of(r["Starts"], r["Ends"]),
                "Window": window_label(r["Starts"], r["Ends"]),
                "Pricelist": r["Pricelist"],
            })
    return pd.DataFrame(rows, columns=empty.columns)
