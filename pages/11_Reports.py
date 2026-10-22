"""Reports — the daily, weekly and monthly sales performance reports, laid out
like the ones the team circulates, on one page from 1.0 Executive Summary to
9.0 Summary & Key Notes, with Excel, Word and PowerPoint downloads."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, charts, db, grid, report_export, reports, theme

st.set_page_config(page_title="Reports · Denri Executive Dashboard", page_icon="📑", layout="wide")

auth.require_login()

st.title("📑 Reports")
st.caption("Daily, weekly and monthly sales performance reports — each period against the one "
           "before it, live from Postgres")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

today = date.today()
c1, c2, c3 = st.columns([1.2, 1.6, 1])
kind = c1.segmented_control("Report", [reports.DAILY, reports.WEEKLY, reports.MONTHLY],
                            default=reports.DAILY, key="report_kind") or reports.DAILY
if kind == reports.DAILY:
    picked = c2.date_input("Day", value=today - timedelta(days=1), max_value=today, key="report_day")
elif kind == reports.WEEKLY:
    last_sunday = today - timedelta(days=(today.weekday() + 1) % 7 + 7)
    picked = c2.date_input("Week (Sunday to Saturday) — pick any day in it", value=last_sunday,
                           max_value=today, key="report_week")
else:
    months = []
    m = today.replace(day=1)
    for _ in range(18):
        months.append(m)
        m = (m - timedelta(days=1)).replace(day=1)
    picked = c2.selectbox("Month", months, index=1 if len(months) > 1 else 0,
                          format_func=lambda d: d.strftime("%B %Y")
                          + (" (to date)" if d == today.replace(day=1) else ""),
                          key="report_month")
with c3:
    refreshed = db.refresh_button(key="reports_refresh")

period = reports.period_for(kind, picked)


@st.cache_data(ttl=reports.CLOSED_TTL, show_spinner=False, max_entries=60)
def _build_closed(kind: str, start: date) -> dict:
    """A finished day, week or month: built once, then shared for 12 hours."""
    return reports.build(reports.period_for(kind, start))


@st.cache_data(ttl=reports.OPEN_TTL, show_spinner=False, max_entries=10)
def _build_open(kind: str, start: date) -> dict:
    return reports.build(reports.period_for(kind, start))


if refreshed:
    # Finished periods are otherwise kept for 12 hours; Refresh rebuilds them too.
    _build_closed.clear()
    _build_open.clear()
    reports._orders_closed.clear()

with st.spinner(f"Preparing the {kind.lower()} report…"):
    report = (_build_closed if period.end < today else _build_open)(kind, period.start)
sections = report_export.outline(report)

st.subheader(reports.title_for(period))
st.caption(f"{period.label} · compared to {period.prev_label} · generated "
           f"{report['generated']:%d %b %Y, %H:%M}")
if period.end >= today:
    st.info("This period is not over yet — its figures cover the days so far.", icon="⏳")
if report.get("missing_spans"):
    st.warning("The database was too busy to return "
               + ", ".join(sorted(report["missing_spans"]))
               + " for the revenue bridge; press Refresh to try again.", icon="⚠️")

# --- downloads: each file is built only when its button is clicked ---
stem = (f"Denri_{ {'Daily': 'Day', 'Weekly': 'Week', 'Monthly': 'Month'}[kind] }_"
        f"{period.start:%Y-%m-%d}_to_{period.end:%Y-%m-%d}").replace(" ", "")
d1, d2, d3, _ = st.columns([1, 1, 1, 2])
d1.download_button("⬇️ Excel (.xlsx)", lambda: reports.to_xlsx(report), file_name=f"{stem}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                   on_click="ignore", width="stretch", key="report_xlsx")
d2.download_button("⬇️ Word (.docx)", lambda: report_export.to_docx(report), file_name=f"{stem}.docx",
                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                   on_click="ignore", width="stretch", key="report_docx")
d3.download_button("⬇️ PowerPoint (.pptx)", lambda: report_export.to_pptx(report),
                   file_name=f"{stem}.pptx",
                   mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                   on_click="ignore", width="stretch", key="report_pptx")

# --- key performance indicators (the Summary sheet) ---
kpis = reports.summary_rows(report)
for row_items in (kpis.iloc[:4], kpis.iloc[4:]):
    for col, (_, r) in zip(st.columns(4), row_items.iterrows()):
        with col.container(border=True):
            arrow = r["Change"].split(" ")[0]
            st.metric(r["Label"], r["Value"], r["Change"],
                      delta_color="normal" if arrow in ("▲", "▼") else "off")

# --- contents: jump links to each section ---
st.markdown('<div id="contents"></div>', unsafe_allow_html=True)
with st.container(border=True):
    st.markdown("**Contents** &nbsp;·&nbsp; " + " &nbsp;·&nbsp; ".join(
        f"<a href='#{s.anchor}' target='_self'>{s.heading}</a>" for s in sections),
        unsafe_allow_html=True)


# --- rendering ---
def _table(block: report_export.Block) -> None:
    frame = block.frame
    if frame is None or frame.empty:
        st.info("No data for this period.")
        return
    with st.container(border=True):
        grid.filterable_table(
            frame, currency_columns=block.money, total=block.total,
            pinned_columns=(frame.columns[0],) if block.pinned else (),
            height=min(46 + 34 * (len(frame) + (2 if block.total else 1)), 560))


def _chart(block: report_export.Block) -> None:
    data = report_export.chart_data(report, block.chart)
    if data is None or data.empty:
        return
    if block.chart == "gender":
        with st.container(border=True):
            charts.share_chart(charts.fold_other(data["Gender"], data["Count"]), title="Gender Split",
                               key="report_gender_kind", unit="customers")
        return
    fig = go.Figure()
    if block.chart == "shops":
        fig.add_bar(y=data["Shop"], x=data["Previous"], orientation="h", name=period.prev_label,
                    marker=dict(color=theme.OTHER))
        fig.add_bar(y=data["Shop"], x=data["Current"], orientation="h", name=period.label,
                    marker=dict(color=theme.CATEGORICAL[0]))
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(barmode="group", hovermode="closest",
                          height=max(420, 30 * len(data) + 120))
    elif block.chart == "frequency":
        fig.add_bar(x=data["Purchase Frequency"], y=data["Customer Count"],
                    marker=dict(color=theme.CATEGORICAL[0], cornerradius=4),
                    text=[f"{v:,}" for v in data["Customer Count"]], textposition="outside",
                    hovertemplate="%{x}<br>%{y:,} customers<extra></extra>")
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(height=360)
    elif block.chart == "conversion":
        colours = [theme.CATEGORICAL[7] if v < reports.LOW_CONVERSION else theme.CATEGORICAL[0]
                   for v in data["Conv. Rate %"]]
        fig.add_bar(y=data["Shop"], x=data["Conv. Rate %"], orientation="h",
                    marker=dict(color=colours), text=[f"{v:.1f}%" for v in data["Conv. Rate %"]],
                    textposition="outside", hovertemplate="%{y}: %{x:.1f}%<extra></extra>")
        fig.add_vline(x=reports.LOW_CONVERSION, line_dash="dash", line_color=theme.TEXT_SECONDARY,
                      annotation_text=f"{reports.LOW_CONVERSION:.0f}% coaching line",
                      annotation_position="top")
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(height=max(380, 26 * len(data) + 120), xaxis_ticksuffix="%")
    elif block.chart == "bridge":
        fig.add_bar(x=data["Label"], y=data["Revenue"], name="Revenue",
                    marker=dict(color=theme.CATEGORICAL[0], cornerradius=4),
                    hovertemplate="%{x}<br>KES %{y:,.0f}<extra></extra>")
        fig.add_scatter(x=data["Label"], y=data["Avg Spend"], name="Avg spend / customer",
                        yaxis="y2", mode="lines+markers",
                        line=dict(color=theme.CATEGORICAL[5], width=2),
                        hovertemplate="%{x}<br>KES %{y:,.0f} a customer<extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(height=380, yaxis2=dict(overlaying="y", side="right", showgrid=False))
    fig.update_layout(title=block.title)
    with st.container(border=True):
        theme.show(fig)


def _flags(items: list[str]) -> None:
    if not items:
        st.caption("No changes large enough to flag.")
    for f in items:
        tag, body = report_export.tag_of(f)
        box = st.error if tag in ("CRITICAL",) else st.warning if tag in ("RISK", "HIGH", "MEDIUM") \
            else st.success
        box(f"**{tag}** · {body}" if tag else body)


def _narrow(b: report_export.Block) -> bool:
    if b.kind in ("chart", "flags"):
        return True
    return (b.kind == "table" and b.frame is not None and len(b.frame.columns) <= 5
            and len(b.frame) <= report_export.NARROW_ROWS)


def _render(b: report_export.Block, show_title: bool) -> None:
    if show_title and b.title and b.kind != "chart":
        st.markdown(f"**{b.title}**")
    if b.kind == "table":
        _table(b)
    elif b.kind == "chart":
        _chart(b)
    elif b.kind == "flags":
        _flags(b.items)


for s in sections:
    st.header(s.heading, anchor=s.anchor, divider="gray")
    blocks, i = s.blocks, 0
    shown_titles: set[str] = set()
    while i < len(blocks):
        b = blocks[i]
        if b.kind == "text":
            if b.text:
                st.caption(b.text)
            i += 1
            continue
        if b.kind == "notes":
            for team, items in b.notes.items():
                st.markdown(f"#### {team}")
                if items:
                    _flags(items)
                else:
                    st.caption(f"No {team.lower()} flags this period.")
            i += 1
            continue
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if nxt is not None and nxt.kind != "text" and _narrow(b) and _narrow(nxt):
            # Two narrow pieces (a chart and its table, a table and its flags) side by side.
            left, right = st.columns(2, gap="medium")
            for col, piece in ((left, b), (right, nxt)):
                with col:
                    _render(piece, piece.title not in shown_titles)
                    shown_titles.add(piece.title)
            i += 2
            continue
        _render(b, b.title not in shown_titles)
        shown_titles.add(b.title)
        i += 1
    st.markdown("<div style='text-align:right; font-size:0.85rem'>"
                "<a href='#contents' target='_self'>↑ Back to contents</a></div>",
                unsafe_allow_html=True)
