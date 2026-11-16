"""Shared date-range filter: a compact PERIOD dropdown with a custom range as
the fallback — reused by every domain page."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import ui

PRESETS = ["Today", "Yesterday", "Last 7 Days", "This Week", "Last Week", "Last 30 Days",
           "Month to Date", "Year to Date",
           "Custom"]

_PERIOD_CSS = f"""
<style>
/* Compact PERIOD picker: small muted caps label over a narrow dropdown, with
   the selected option in the nav accent so it reads as current state. */
.denri-period-wrap {{ max-width: 210px; }}
.denri-period-wrap label p {{
  color: {ui.TEXT_MUTED} !important;
  font-size: 0.68rem !important;
  font-weight: 600;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  margin-bottom: 2px !important;
}}
.denri-period-wrap div[data-baseweb="select"] > div {{
  background: var(--denri-field, #10161a);
  border: 1px solid var(--denri-hair, rgba(255,255,255,0.09));
  border-radius: 9px;
  min-height: 36px;
  font-size: 0.86rem;
}}
.denri-period-wrap div[data-baseweb="select"] > div:hover {{
  border-color: rgba(165,148,249,0.55);
}}
/* dropdown menu */
ul[data-baseweb="menu"] li[aria-selected="true"] {{
  background: {ui.ACCENT_SOFT} !important;
  color: {ui.ACCENT} !important;
}}
ul[data-baseweb="menu"] li:hover {{
  background: rgba(var(--denri-ink-rgb, 255,255,255),0.05);
}}
</style>
"""


def _preset_range(preset: str, today: date) -> tuple[date, date]:
    if preset == "Yesterday":
        y = today - timedelta(days=1)
        return y, y
    if preset == "Last 7 Days":
        return today - timedelta(days=6), today
    # The business week runs Sunday to Saturday.
    this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    if preset == "This Week":
        return this_sunday, today
    if preset == "Last Week":
        return this_sunday - timedelta(days=7), this_sunday - timedelta(days=1)
    if preset == "Last 30 Days":
        return today - timedelta(days=29), today
    if preset == "Month to Date":
        return today.replace(day=1), today
    if preset == "Year to Date":
        return today.replace(month=1, day=1), today
    return today, today  # "Today" and the "Custom" pre-selection default


def resolve_range(key_prefix: str, default: str = "Today") -> tuple[date, date]:
    """The selected range, read from session state WITHOUT rendering the widget.

    Lets a page fetch its data before drawing any chrome, so the whole page —
    header and controls included — can sit behind a loading skeleton. The
    widget is rendered afterwards with the same keys, so its state carries.
    """
    today = date.today()
    preset = st.session_state.get(f"{key_prefix}_preset", default) or default

    if preset != "Custom":
        return _preset_range(preset, today)

    picked = st.session_state.get(f"{key_prefix}_custom", (today, today))
    if isinstance(picked, (tuple, list)):
        if len(picked) == 2:
            return picked[0], picked[1]
        if len(picked) == 1:
            return picked[0], picked[0]
        return today, today
    return picked, picked


def date_range_control(key_prefix: str, default: str = "Today",
                       compare: bool = True) -> tuple[date, date]:
    """Render the PERIOD dropdown (+ a custom picker when 'Custom' is chosen),
    and the COMPARE WITH picker beside it unless `compare` is False.

    Returns (start_date, end_date) for the caller to bind into a query.
    """
    today = date.today()

    st.markdown(_PERIOD_CSS, unsafe_allow_html=True)
    col_period, col_compare = st.columns([1, 2])
    with col_period:
        st.markdown('<div class="denri-period-wrap">', unsafe_allow_html=True)
        preset = st.selectbox(
            "Period",
            PRESETS,
            index=PRESETS.index(default) if default in PRESETS else 0,
            key=f"{key_prefix}_preset",
        )
        st.markdown("</div>", unsafe_allow_html=True)

        preset = preset or default

        if preset != "Custom":
            picked = _preset_range(preset, today)
        else:
            picked = st.date_input(
                "Custom range",
                value=(today, today),
                max_value=today,
                key=f"{key_prefix}_custom",
                label_visibility="collapsed",
            )
            if not isinstance(picked, tuple):
                picked = (picked, picked)
            elif len(picked) == 1:
                picked = (picked[0], picked[0])
    if compare:
        with col_compare:
            _compare_control(key_prefix, *picked)
    return picked


# ------------------------------------------------------------ comparison ---
# Beside the period: up to four other periods to set the selected one against.

COMPARE_MAX = 4
_CUSTOM = "custom"


def _unit(start: date, end: date) -> str:
    """What the selected period is: a day, a Sunday-to-Saturday week (or the
    part of one so far), a month (or month to date), or just a span of days."""
    span = (end - start).days + 1
    if span == 1:
        return "day"
    if start.weekday() == 6 and span <= 7:
        return "week"
    if start.day == 1 and end.month == start.month and end.year == start.year:
        return "month"
    if (start.month, start.day) == (1, 1) and end.year == start.year:
        return "year"
    return "span"


def _months_back(start: date, end: date, months: int) -> tuple[date, date]:
    """The same days of an earlier month; a whole month stays a whole month."""
    index = start.year * 12 + start.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    whole = end.day == calendar.monthrange(end.year, end.month)[1]
    return date(year, month, 1), date(year, month, last if whole else min(end.day, last))


def _years_back(start: date, end: date, years: int) -> tuple[date, date]:
    """The same dates of an earlier year (29 Feb becomes 28 Feb)."""
    back = lambda d: d.replace(year=d.year - years, day=min(d.day, calendar.monthrange(d.year - years, d.month)[1]))
    return back(start), back(end)


def earlier(start: date, end: date, steps: int) -> tuple[date, date]:
    """The period `steps` before the selected one: days back for a day, weeks
    for a week (so weekdays line up), months for a month."""
    unit = _unit(start, end)
    if unit == "month":
        return _months_back(start, end, steps)
    if unit == "year":
        return _years_back(start, end, steps)
    back = timedelta(days=steps * (7 if unit == "week" else (end - start).days + 1))
    return start - back, end - back


def last_year(start: date, end: date) -> tuple[date, date]:
    """The same period a year earlier: the same dates for a month, otherwise
    52 weeks back so a Sunday-to-Saturday week stays one."""
    if _unit(start, end) == "month":
        return _months_back(start, end, 12)
    if _unit(start, end) == "year":
        return _years_back(start, end, 1)
    return start - timedelta(weeks=52), end - timedelta(weeks=52)


def _span_label(start: date, end: date) -> str:
    if start == end:
        return f"{start:%a %d %b %Y}"
    return f"{start:%d %b} – {end:%d %b %Y}"


def _compare_control(key_prefix: str, start: date, end: date) -> None:
    """The COMPARE WITH picker. What was picked is left in session state for
    comparisons() to read, so date_range_control keeps returning the period."""
    unit = _unit(start, end)
    noun = {"day": "day", "week": "week", "month": "month", "year": "year"}.get(unit, "period")
    names = {"prev1": f"Previous {noun}", "prev2": f"2 {noun}s ago", "prev3": f"3 {noun}s ago",
             "year": f"Same {noun} last year", _CUSTOM: "Custom range"}
    st.markdown('<div class="denri-period-wrap">', unsafe_allow_html=True)
    picked = st.multiselect("Compare with", list(names), format_func=names.get,
                            max_selections=COMPARE_MAX, key=f"{key_prefix}_compare",
                            placeholder="No comparison")
    st.markdown("</div>", unsafe_allow_html=True)
    ranges = []
    for choice in picked:
        if choice == _CUSTOM:
            custom = st.date_input("Compare with custom range", value=earlier(start, end, 1),
                                   max_value=date.today(), key=f"{key_prefix}_compare_custom",
                                   label_visibility="collapsed")
            if not (isinstance(custom, tuple) and len(custom) == 2):
                continue                      # still picking the second date
            span = custom
        elif choice == "year":
            span = last_year(start, end)
        else:
            span = earlier(start, end, int(choice[-1]))
        ranges.append((f"{names[choice]} ({_span_label(*span)})", *span))
    st.session_state[f"{key_prefix}_comparisons"] = ranges


def comparisons(key_prefix: str) -> list[tuple[str, date, date]]:
    """(label, start, end) for each period picked under COMPARE WITH."""
    return st.session_state.get(f"{key_prefix}_comparisons", [])


def _show(value, kind: str) -> str:
    if value is None or pd.isna(value):
        return "—"
    if kind == "KES":
        return f"KES {value:,.0f}"
    if kind == "%":
        return f"{value:.1f}%"
    if kind == "decimal":
        return f"{value:,.2f}"
    return f"{value:,.0f}"


def _change(now, then, kind: str) -> str:
    """'▲ +12.0%' against the other period; percentage points for a rate."""
    if now is None or then is None or pd.isna(now) or pd.isna(then):
        return "—"
    diff = now - then
    arrow = "▲" if diff > 1e-9 else "▼" if diff < -1e-9 else "→"
    if kind == "%":
        return f"{arrow} {diff:+.1f} pts"
    return f"{arrow} {diff / then * 100:+.1f}%" if then else f"{arrow} n/a"


def comparison(key_prefix: str, start: date, end: date, headline, kinds: dict[str, str],
               note: str = "") -> None:
    """The selected period's headline figures beside each period picked under
    COMPARE WITH. `headline(start, end)` returns {figure: number}; `kinds`
    says how to write a figure ("KES", "%", "decimal"; a whole number if not
    listed). Draws nothing when no comparison is picked."""
    others = comparisons(key_prefix)
    if not others:
        return
    now = headline(start, end)
    table = pd.DataFrame({"Figure": list(now),
                          f"Selected ({_span_label(start, end)})":
                              [_show(v, kinds.get(k, "")) for k, v in now.items()]})
    for i, (label, s, e) in enumerate(others, start=1):
        then = headline(s, e)
        table[label] = [_show(then.get(k), kinds.get(k, "")) for k in now]
        table[f"Change {i}" if len(others) > 1 else "Change"] = [
            _change(v, then.get(k), kinds.get(k, "")) for k, v in now.items()]
    changes = [c for c in table.columns if c.startswith("Change")]
    colour = lambda v: ("color: #2e9e5b; font-weight: 600" if v.startswith("▲")
                        else "color: #e5534b; font-weight: 600" if v.startswith("▼") else "")
    with st.container(border=True):
        st.markdown("**Comparison** — the selected period against "
                    + ("the one picked" if len(others) == 1 else f"the {len(others)} picked"))
        st.dataframe(table.style.map(colour, subset=changes), hide_index=True, width="stretch")
        st.caption("Each Change column is the selected period against the period to its left"
                   + (f". {note}" if note else "."))


if __name__ == "__main__":   # python -m lib.filters
    d = date
    assert earlier(d(2026, 11, 17), d(2026, 11, 17), 1) == (d(2026, 11, 16), d(2026, 11, 16))
    # this week so far (Sun-Tue) against the same days of last week, not the 3 days before
    assert earlier(d(2026, 11, 15), d(2026, 11, 17), 1) == (d(2026, 11, 8), d(2026, 11, 10))
    assert earlier(d(2026, 11, 8), d(2026, 11, 14), 2) == (d(2026, 10, 25), d(2026, 10, 31))
    # month to date against the same days of last month; a whole month against a whole month
    assert earlier(d(2026, 11, 1), d(2026, 11, 17), 1) == (d(2026, 10, 1), d(2026, 10, 17))
    assert earlier(d(2026, 3, 1), d(2026, 3, 31), 1) == (d(2026, 2, 1), d(2026, 2, 28))
    assert earlier(d(2026, 1, 1), d(2026, 1, 31), 3) == (d(2025, 10, 1), d(2025, 10, 31))
    assert earlier(d(2026, 10, 19), d(2026, 11, 17), 1) == (d(2026, 9, 19), d(2026, 10, 18))
    assert last_year(d(2026, 11, 1), d(2026, 11, 17)) == (d(2025, 11, 1), d(2025, 11, 17))
    week = last_year(d(2026, 11, 8), d(2026, 11, 14))
    assert week == (d(2025, 11, 9), d(2025, 11, 15)) and week[0].weekday() == 6
    assert _change(110, 100, "") == "▲ +10.0%" and _change(40.0, 42.5, "%") == "▼ -2.5 pts"
    assert _change(5, 0, "") == "▲ n/a" and _change(None, 3, "") == "—"
    assert _preset_range("Year to Date", d(2026, 11, 16)) == (d(2026, 1, 1), d(2026, 11, 16))
    assert earlier(d(2026, 1, 1), d(2026, 11, 16), 1) == (d(2025, 1, 1), d(2025, 11, 16))
    assert last_year(d(2026, 1, 1), d(2026, 11, 16)) == (d(2025, 1, 1), d(2025, 11, 16))
    print("filters ok")
