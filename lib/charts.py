"""Share-of-total charts that the viewer can switch between forms.

One set of numbers, four ways to draw it: Pie, Doughnut, Bar and Polar area.
Colours follow the entity, not the form, so a branch keeps its colour when the
viewer switches from a pie to a bar.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import theme

KINDS = ["Doughnut", "Pie", "Bar", "Polar area"]

# Past this many slices the smallest fold into "Other": eight named hues is
# as many as can be told apart, and a ninth generated colour would not be.
MAX_NAMED = len(theme.CATEGORICAL)

# Slices smaller than this carry no in-slice label; the legend and the hover
# still name them.
_MIN_LABEL_SHARE = 4.0


def fold_other(labels, values, max_named: int = MAX_NAMED) -> pd.DataFrame:
    """Largest-first, with everything past max_named summed into "Other"."""
    df = pd.DataFrame({"Label": list(labels), "Value": list(values)})
    df = df[df["Value"] > 0].sort_values("Value", ascending=False)
    if len(df) > max_named:
        rest = df.iloc[max_named:]
        df = pd.concat([
            df.iloc[:max_named],
            pd.DataFrame([{"Label": f"Other ({len(rest)})", "Value": rest["Value"].sum()}]),
        ], ignore_index=True)
    total = df["Value"].sum()
    df["Share"] = df["Value"] / total * 100 if total else 0.0
    return df.reset_index(drop=True)


def colors_for(labels, fixed: dict[str, str] | None = None) -> list[str]:
    """Categorical hues in fixed order, grey for Other; `fixed` pins an
    entity to a colour so it matches the same entity in other charts."""
    out, i = [], 0
    for label in labels:
        if fixed and label in fixed:
            out.append(fixed[label])
        elif str(label).startswith("Other"):
            out.append(theme.OTHER)
        else:
            out.append(theme.CATEGORICAL[i % len(theme.CATEGORICAL)])
            i += 1
    return out


def share_figure(data: pd.DataFrame, kind: str, *, title: str, unit: str = "KES",
                 colors: list[str] | None = None) -> go.Figure:
    """Build the chart for `data` (columns Label, Value, Share) in form `kind`."""
    colors = colors or colors_for(data["Label"])
    fmt = (lambda v: f"KES {v:,.0f}") if unit == "KES" else (lambda v: f"{v:,.0f} {unit}")
    custom = [[fmt(v), s] for v, s in zip(data["Value"], data["Share"])]
    hover = ("<b>%{customdata[0]}</b><br>"
             "%{customdata[1]:.1f}% of the total<extra></extra>")
    fig = go.Figure()

    if kind in ("Pie", "Doughnut"):
        text = [f"{s:.0f}%" if s >= _MIN_LABEL_SHARE else "" for s in data["Share"]]
        fig.add_pie(
            labels=data["Label"], values=data["Value"],
            hole=0.55 if kind == "Doughnut" else 0,
            sort=False, direction="clockwise", rotation=0,
            marker=dict(colors=colors, line=dict(color=theme.CHART_SURFACE, width=2)),
            text=text, textinfo="text", textposition="inside",
            insidetextorientation="horizontal",
            textfont=dict(color=theme.TEXT_PRIMARY, size=12),
            customdata=custom,
            hovertemplate="<b>%{label}</b><br>" + hover,
        )
        if kind == "Doughnut":
            total = data["Value"].sum()
            fig.add_annotation(
                text=f"<b>{fmt(total)}</b><br><span style='font-size:11px'>total</span>",
                showarrow=False, font=dict(color=theme.TEXT_PRIMARY, size=14),
            )
    elif kind == "Polar area":
        fig.add_barpolar(
            theta=data["Label"], r=data["Value"], showlegend=False,
            marker=dict(color=colors, line=dict(color=theme.CHART_SURFACE, width=2)),
            customdata=custom,
            hovertemplate="<b>%{theta}</b><br>" + hover,
        )
        # One trace, so the legend is drawn from invisible per-slice entries.
        for label, color in zip(data["Label"], colors):
            fig.add_scatterpolar(r=[None], theta=[label], mode="markers", name=label,
                                 marker=dict(color=color, size=10, symbol="square"),
                                 hoverinfo="skip")
        fig.update_layout(polar=dict(
            bgcolor=theme.CHART_SURFACE,
            radialaxis=dict(showticklabels=False, gridcolor=theme.GRIDLINE,
                            linecolor=theme.AXIS_LINE, ticks=""),
            angularaxis=dict(showticklabels=False, gridcolor=theme.GRIDLINE,
                             linecolor=theme.AXIS_LINE, direction="clockwise"),
        ))
    else:  # Bar
        ranked = data.iloc[::-1]  # largest at the top
        fig.add_bar(
            y=ranked["Label"], x=ranked["Value"], orientation="h",
            marker=dict(color=colors[::-1], cornerradius=4),
            text=[f"{s:.1f}%" for s in ranked["Share"]], textposition="outside",
            textfont=dict(color=theme.TEXT_SECONDARY, size=12), cliponaxis=False,
            customdata=[[fmt(v), s] for v, s in zip(ranked["Value"], ranked["Share"])],
            hovertemplate="<b>%{y}</b><br>" + hover,
        )

    theme.apply_layout(fig, show_legend=kind != "Bar")
    fig.update_layout(title=title, height=400, hovermode="closest")
    if kind != "Bar":
        # Beside the chart, one entry per line: a round chart has room at its
        # side and none above it.
        fig.update_layout(legend=dict(
            orientation="v", x=1.02, xanchor="left", y=0.5, yanchor="middle",
            font=dict(color=theme.TEXT_SECONDARY, size=12),
        ), margin=dict(r=8))
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
    else:
        fig.update_xaxes(showgrid=True, gridcolor=theme.GRIDLINE, tickformat="~s")
        fig.update_yaxes(showgrid=False)
    return fig


def share_chart(data: pd.DataFrame, *, title: str, key: str, unit: str = "KES",
                colors: list[str] | None = None, default: str = "Doughnut") -> None:
    """A share chart with a form picker above it, like the dashboard's other
    switchable visuals."""
    _, pick = st.columns([3, 1])
    with pick:
        kind = st.selectbox("Chart type", KINDS, index=KINDS.index(default),
                            key=key, label_visibility="collapsed")
    if data.empty:
        st.info("Nothing to show for this range.")
        return
    theme.show(share_figure(data, kind, title=title, unit=unit, colors=colors))
