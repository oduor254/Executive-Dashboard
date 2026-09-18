"""Shared chart styling: the validated palette from the dataviz skill,
applied consistently across every page via one Plotly layout template.

Dark mode is the selected theme (matches .streamlit/config.toml base="dark") —
its own validated steps from the same ramps, not an automatic light flip.
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

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

# "Other" in a share chart, and anything without a target: a neutral that
# reads as "not one of the named series" rather than as a ninth hue.
OTHER = "#6f6e69"

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


# Vertical space the chart header takes, in px. The title sits at the top of
# the figure and the legend on its own row beneath it, so neither is ever
# drawn over the other or over the plot.
_TITLE_BAND = 44
_LEGEND_BAND = 34


def finalize(fig: go.Figure) -> go.Figure:
    """Lay out the chart header so titles, legends and axis labels never collide.

    This runs at draw time rather than in apply_layout because pages set their
    title AFTER apply_layout, and fig.update_layout(title="...") replaces the
    whole title object — any position set earlier is lost. That is how titles
    ended up printed on top of the legend.
    """
    title = fig.layout.title.text if fig.layout.title else None
    horizontal_legend = (fig.layout.showlegend is not False
                         and (fig.layout.legend.orientation or "h") == "h")
    legend_shown = bool(fig.layout.showlegend) and horizontal_legend

    top = (_TITLE_BAND if title else 12) + (_LEGEND_BAND if legend_shown else 0)
    margin = fig.layout.margin
    fig.update_layout(margin=dict(
        t=top if (title or legend_shown) else (margin.t if margin.t is not None else top),
        l=margin.l if margin.l is not None else 8,
        r=margin.r if margin.r is not None else 8,
        b=margin.b if margin.b is not None else 8,
    ))

    if title:
        fig.update_layout(title=dict(
            text=title, x=0, xref="container", xanchor="left",
            y=1, yref="container", yanchor="top",
            pad=dict(t=14, l=12),
            font=dict(color=TEXT_PRIMARY, size=15, family=FONT_FAMILY),
        ))
    if legend_shown:
        # Anchored to the top edge of the plot, i.e. in the band under the title.
        fig.update_layout(legend=dict(
            orientation="h", x=0, xanchor="left", y=1.0, yanchor="bottom",
            yref="paper", bgcolor="rgba(0,0,0,0)",
            font=dict(color=TEXT_SECONDARY, size=12),
        ))

    # Long branch and product names reserve the room they need instead of
    # running off the edge or under the neighbouring label.
    fig.update_xaxes(automargin=True, title_standoff=8, ticklabelstandoff=4)
    fig.update_yaxes(automargin=True, title_standoff=8, ticklabelstandoff=6)

    # "x unified" on a horizontal bar chart groups every bar at the same VALUE,
    # which is meaningless; the category runs up the y axis there.
    bars = [t for t in fig.data if t.type == "bar"]
    if (fig.layout.hovermode == "x unified" and bars
            and all(t.orientation == "h" for t in bars)):
        fig.update_layout(hovermode="y unified")
    return fig


def show(fig: go.Figure, **kwargs) -> None:
    """Draw a chart. Use this instead of st.plotly_chart so every chart gets
    the same collision-free header."""
    kwargs.setdefault("width", "stretch")
    kwargs.setdefault("config", {"displaylogo": False})
    st.plotly_chart(finalize(fig), **kwargs)
