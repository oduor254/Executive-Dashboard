"""Which sales target a date range is measured against, and how far through it we are.

Odoo keeps three kinds of target per shop per month: a daily, a weekly and a
monthly amount (queries.SALES_TARGET_ROWS). The Sales page used to choose
between them by the range's length alone — seven days or fewer meant "week" —
so Month to Date in the first week of a month was judged against one week's
target: 5 Oct 2026 read 35.9% where the month was 8% done.

The basis now follows the period itself:
  * one day                       -> the daily target
  * a range inside one month that
    starts on the 1st (Month to Date, a whole month)
                                  -> the monthly target, paced by days elapsed
  * up to 7 days (Last 7 Days, a custom week)
                                  -> the weekly target, paced by days elapsed
  * anything else (Last 30 Days, a range across months)
                                  -> the monthly targets, prorated by day
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


@dataclass
class Basis:
    label: str          # e.g. "October 2026 monthly target"
    expected: float     # share of the target that should be reached by now (0-1)
    targets: dict       # location -> target amount for this basis


def _days_in_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def _amount(rows: pd.DataFrame, kind: str, on: date) -> dict:
    """Per location, the `kind` target whose month contains `on`."""
    hit = rows[(rows["Kind"] == kind) & (rows["Starts"] <= on) & (rows["Ends"] >= on)]
    return hit.groupby("Location")["Target"].sum().to_dict()


def basis_for(start: date, end: date, rows: pd.DataFrame, today: date | None = None) -> Basis:
    today = today or date.today()
    rows = rows.copy()
    rows["Starts"] = pd.to_datetime(rows["Starts"]).dt.date
    rows["Ends"] = pd.to_datetime(rows["Ends"]).dt.date
    days = (end - start).days + 1
    elapsed = max(min((min(end, today) - start).days + 1, days), 0)
    same_month = (start.year, start.month) == (end.year, end.month)

    if days == 1:
        return Basis(f"daily target for {start:%a %d %b}", 1.0, _amount(rows, "day", start))

    if same_month and start.day == 1:
        # Days covered so far out of the whole month: 5/31 on 5 Oct, 30/30 for
        # all of September.
        expected = elapsed / _days_in_month(start)
        return Basis(f"{start:%B %Y} monthly target", expected, _amount(rows, "month", start))

    if days <= 7:
        return Basis(f"weekly target ({start:%d %b} – {end:%d %b})", elapsed / 7,
                     _amount(rows, "week", start))

    # Across months or an arbitrary long range: each day takes 1/days-in-month
    # of its month's target, summed over the range.
    totals: dict = {}
    d = start
    while d <= end:
        for loc, amount in _amount(rows, "month", d).items():
            totals[loc] = totals.get(loc, 0.0) + amount / _days_in_month(d)
        d += timedelta(days=1)
    return Basis(f"monthly targets prorated to {start:%d %b} – {end:%d %b}",
                 elapsed / days, totals)
