"""Shared date-range filter: a preset row (Today, Last 7 Days, ...) with a
custom range as the fallback — reused by every domain page."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

PRESETS = ["Today", "Yesterday", "Last 7 Days", "Last 30 Days", "Month to Date", "Custom"]


def _preset_range(preset: str, today: date) -> tuple[date, date]:
    if preset == "Yesterday":
        y = today - timedelta(days=1)
        return y, y
    if preset == "Last 7 Days":
        return today - timedelta(days=6), today
    if preset == "Last 30 Days":
        return today - timedelta(days=29), today
    if preset == "Month to Date":
        return today.replace(day=1), today
    return today, today  # "Today" and the "Custom" pre-selection default


def date_range_control(key_prefix: str, default: str = "Today") -> tuple[date, date]:
    """Render the preset row (+ a custom picker when 'Custom' is chosen).

    Returns (start_date, end_date) for the caller to bind into a query.
    """
    today = date.today()

    preset = st.segmented_control(
        "Date range",
        PRESETS,
        default=default,
        key=f"{key_prefix}_preset",
    )
    preset = preset or default

    if preset != "Custom":
        return _preset_range(preset, today)

    picked = st.date_input(
        "Custom range",
        value=(today, today),
        max_value=today,
        key=f"{key_prefix}_custom",
        label_visibility="collapsed",
    )
    if isinstance(picked, tuple) and len(picked) == 2:
        return picked
    if isinstance(picked, tuple) and len(picked) == 1:
        return picked[0], picked[0]
    return picked, picked
