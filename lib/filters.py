"""Shared date-range filter: a compact PERIOD dropdown with a custom range as
the fallback — reused by every domain page."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from lib import ui

PRESETS = ["Today", "Yesterday", "Last 7 Days", "Last 30 Days", "Month to Date", "Custom"]

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
  background: #10161a;
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 9px;
  min-height: 36px;
  font-size: 0.86rem;
}}
.denri-period-wrap div[data-baseweb="select"] > div:hover {{
  border-color: rgba(25,195,154,0.45);
}}
/* dropdown menu */
ul[data-baseweb="menu"] li[aria-selected="true"] {{
  background: {ui.ACCENT_SOFT} !important;
  color: {ui.ACCENT} !important;
}}
ul[data-baseweb="menu"] li:hover {{
  background: rgba(255,255,255,0.05);
}}
</style>
"""


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


def date_range_control(key_prefix: str, default: str = "Today") -> tuple[date, date]:
    """Render the PERIOD dropdown (+ a custom picker when 'Custom' is chosen).

    Returns (start_date, end_date) for the caller to bind into a query.
    """
    today = date.today()

    st.markdown(_PERIOD_CSS, unsafe_allow_html=True)
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
