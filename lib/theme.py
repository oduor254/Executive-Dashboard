"""Shared chart styling: the validated palette from the dataviz skill,
applied consistently across every page via one Plotly layout template.

Dark mode is the selected theme (matches .streamlit/config.toml base="dark") —
its own validated steps from the same ramps, not an automatic light flip.
"""
from __future__ import annotations

import plotly.graph_objects as go

FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Fixed hue order — never cycle past what's assigned, never reorder per-chart.
# Same eight hues as light mode, re-stepped for the dark surface.
CATEGORICAL = [
    "#3987e5",  # 1 blue
    "#008300",  # 2 green
    "#d55181",  # 3 magenta
    "#c98500",  # 4 yellow
    "#199e70",  # 5 aqua
    "#d95926",  # 6 orange
    "#9085e9",  # 7 violet
    "#e66767",  # 8 red
]

# Reserved for state, never reused as series colors. Same steps in both modes.
STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

# Sequential blue ramp, light -> dark, for magnitude/heatmap encoding.
SEQUENTIAL_BLUE = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef",
    "#6da7ec", "#5598e7", "#3987e5", "#2a78d6",
    "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]

DIVERGING = {"cool": "#2a78d6", "warm": "#e34948", "mid": "#383835"}

# Dark chart chrome
CHART_SURFACE = "#1a1a19"
PAGE_PLANE = "#0d0d0d"
TEXT_PRIMARY = "#ffffff"
TEXT_SECONDARY = "#c3c2b7"
TEXT_MUTED = "#898781"
GRIDLINE = "#2c2c2a"
AXIS_LINE = "#383835"
BORDER = "rgba(255,255,255,0.10)"


def apply_layout(fig: go.Figure, *, show_legend: bool | None = None) -> go.Figure:
    """Apply consistent chrome: fonts, gridlines, hover, margins, colorway."""
    n_series = sum(1 for _ in fig.data)
    if show_legend is None:
        show_legend = n_series >= 2

    fig.update_layout(
        colorway=CATEGORICAL,
        font=dict(family=FONT_FAMILY, color=TEXT_SECONDARY, size=13),
        title_font=dict(color=TEXT_PRIMARY, size=15),
        paper_bgcolor=CHART_SURFACE,
        plot_bgcolor=CHART_SURFACE,
        showlegend=show_legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=8, r=8, t=40 if show_legend else 24, b=8),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=CHART_SURFACE, font=dict(color=TEXT_PRIMARY)),
    )
    fig.update_xaxes(
        showgrid=False, linecolor=AXIS_LINE, tickfont=dict(color=TEXT_MUTED),
    )
    fig.update_yaxes(
        showgrid=True, gridcolor=GRIDLINE, zeroline=False,
        tickfont=dict(color=TEXT_MUTED),
    )
    return fig


def sequential_colors(n: int) -> list[str]:
    """n colors sampled evenly across the sequential ramp, light (low) -> dark (high).

    For ranking bars by magnitude — e.g. top performers by spend — so color
    reinforces the same ordering the bar length already shows, rather than
    carrying its own unrelated meaning.
    """
    if n <= 1:
        return [SEQUENTIAL_BLUE[-1]]
    step = (len(SEQUENTIAL_BLUE) - 1) / (n - 1)
    return [SEQUENTIAL_BLUE[round(i * step)] for i in range(n)]


def status_color(value: float, warn_at: float, critical_at: float, higher_is_worse: bool = True) -> str:
    """Map a value to a status color for a KPI delta/badge, never as the only cue."""
    if higher_is_worse:
        if value >= critical_at:
            return STATUS["critical"]
        if value >= warn_at:
            return STATUS["warning"]
        return STATUS["good"]
    if value <= critical_at:
        return STATUS["critical"]
    if value <= warn_at:
        return STATUS["warning"]
    return STATUS["good"]
