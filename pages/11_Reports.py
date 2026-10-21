"""Reports — the daily, weekly and monthly sales performance reports, laid out
like the ones the team circulates, with an Excel download."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, charts, db, grid, reports, theme

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
    db.refresh_button(key="reports_refresh")

period = reports.period_for(kind, picked)


@st.cache_data(ttl=600, show_spinner="Building the report…")
def _build(kind: str, start: date) -> dict:
    return reports.build(reports.period_for(kind, start))


report = _build(kind, period.start)
cur, prev = report["cur"], report["prev"]

st.subheader(reports.title_for(period))
st.caption(f"{period.label} · compared to {period.prev_label} · generated "
           f"{report['generated']:%d %b %Y, %H:%M}")
if period.end >= today:
    st.info("This period is not over yet — its figures cover the days so far.", icon="⏳")

st.download_button(
    "⬇️ Download report (.xlsx)", reports.to_xlsx(report),
    file_name=f"Denri_{ {'Daily': 'Day', 'Weekly': 'Week', 'Monthly': 'Month'}[kind] }_"
              f"{period.start:%Y-%m-%d}_to_{period.end:%Y-%m-%d}.xlsx".replace(" ", ""),
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    key="report_download")

# --- Key performance indicators (the Summary sheet) ---
kpis = reports.summary_rows(report)
for row_items in (kpis.iloc[:4], kpis.iloc[4:]):
    for col, (_, r) in zip(st.columns(4), row_items.iterrows()):
        with col.container(border=True):
            arrow = r["Change"].split(" ")[0]
            st.metric(r["Label"], r["Value"], r["Change"],
                      delta_color="normal" if arrow in ("▲", "▼") else "off")

SECTIONS = ["1 · Executive Summary", "2 · Customers", "3 · Stores", "4 · Gender", "5 · Traffic",
            "6 · Revenue", "7 · Data Quality", "8 · Feedback", "9 · Key Notes"]
section = st.segmented_control("Section", SECTIONS, default=SECTIONS[0], key="report_section",
                               label_visibility="collapsed") or SECTIONS[0]


def _table(frame: pd.DataFrame, **kwargs) -> None:
    if frame is None or frame.empty:
        st.info("No data for this period.")
        return
    with st.container(border=True):
        grid.filterable_table(frame, **kwargs)


if section.startswith("1"):
    st.markdown("#### 1. Executive Summary")
    _table(report["executive"], total=False, height=420)
    if report["flags"]:
        st.markdown("**Flags**")
        for f in report["flags"]:
            (st.warning if f.startswith("[RISK]") else st.success)(f)
    st.caption(report["exec_note"])

elif section.startswith("2"):
    st.markdown("#### 2. Customer Metrics")
    _table(report["cust_metrics"], total=False, height=230)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**2.1 Purchase Frequency Distribution**")
        _table(report["frequency"], height=230)
    with c2:
        st.markdown("**2.2 Channel Overview**")
        _table(report["channels"], currency_columns=("Avg Spend",), height=230)
    st.caption(report["cust_note"])

elif section.startswith("3"):
    st.markdown("#### 3. Store Performance")
    stores = report["stores"]
    if not stores.empty:
        with st.container(border=True):
            ranked = stores.sort_values("Current")
            fig = go.Figure()
            fig.add_bar(y=ranked["Shop"], x=ranked["Previous"], orientation="h",
                        name=period.prev_label, marker=dict(color=theme.OTHER))
            fig.add_bar(y=ranked["Shop"], x=ranked["Current"], orientation="h",
                        name=period.label, marker=dict(color=theme.CATEGORICAL[0]))
            theme.apply_layout(fig, show_legend=True)
            fig.update_layout(title="Revenue by Shop — this period and the last", barmode="group",
                              hovermode="closest", height=max(420, 34 * len(ranked) + 100))
            theme.show(fig)
    _table(stores, currency_columns=("Current", "Previous", "Change"), pinned_columns=("Shop",),
           height=460)
    st.markdown("**3.1 Channel Mix by Location**")
    _table(report["channel_mix"], pinned_columns=("Shop",),
           currency_columns=tuple(c for c in report["channel_mix"].columns if "(KES)" in c),
           height=460)
    if kind == reports.MONTHLY:
        st.markdown("**3.2 Monthly Customer Retention by Location**")
        st.caption("Repeat: bought on two or more days this month. Retention: also bought at the "
                   "shop last month.")
    else:
        st.markdown("**3.2 Customer Retention by Location**")
    _table(report["retention"], pinned_columns=("Shop",),
           currency_columns=tuple(c for c in report["retention"].columns if "(KES)" in c), height=460)

elif section.startswith("4"):
    st.markdown("#### 4. Gender Performance Analysis")
    st.caption(f"Ratio: {report['gender_ratio']}")
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("**4.1 Overall Gender Split**")
        _table(report["gender"], height=200)
        g = report["gender"]
        with st.container(border=True):
            charts.share_chart(charts.fold_other(g["Gender"], g["Count"]), title="Gender Split",
                               key="report_gender_kind", unit="customers")
    with c2:
        st.markdown("**4.2 Gender by Location**")
        _table(report["gender_shop"], pinned_columns=("Shop",), height=560)
    st.caption(report["gender_note"]
               + (f" {report['gender_unknown']:,} customers have no gender recorded."
                  if report["gender_unknown"] else ""))

elif section.startswith("5"):
    st.markdown("#### 5. Foot & Online Traffic Analysis")
    st.caption("Walk-in Total: walk-ins counted (Footfall module; gaps from the Reporting sheet). "
               "Walk-in Purchased: walk-in orders on the POS. Online and activation orders are "
               "not part of the conversion.")
    _table(report["traffic"], pinned_columns=("Shop",), height=560)
    st.caption(report["traffic_note"])

elif section.startswith("6"):
    st.markdown("#### 6. Revenue Analysis")
    _table(report["revenue_kpis"], total=False, height=260)
    st.markdown("**6.1 Revenue Bridge**")
    bridge = report["bridge"]
    with st.container(border=True):
        fig = go.Figure()
        fig.add_bar(x=bridge["Period"], y=bridge["Revenue"], name="Revenue",
                    marker=dict(color=theme.CATEGORICAL[0], cornerradius=4),
                    hovertemplate="%{x}<br>KES %{y:,.0f}<extra></extra>")
        fig.add_scatter(x=bridge["Period"], y=bridge["Avg Spend"], name="Avg spend", yaxis="y2",
                        mode="lines+markers", line=dict(color=theme.CATEGORICAL[5], width=2),
                        hovertemplate="%{x}<br>KES %{y:,.0f} a customer<extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title="Revenue Bridge", height=380,
                          yaxis2=dict(overlaying="y", side="right", showgrid=False))
        theme.show(fig)
    _table(bridge, currency_columns=("Revenue", "Avg Spend"), total=False, height=300)
    st.markdown("**6.2 Corporate Revenue**")
    st.caption("Payments received on corporate invoices, as Odoo's Sales & POS Dashboard shows them.")
    _table(report["corporate"], total=False, height=140)
    st.markdown("**6.3 Top Corporate Clients**")
    _table(report["corporate_clients"], currency_columns=("Revenue",), height=300)

elif section.startswith("7"):
    st.markdown("#### 7. Data Quality (KYC)")
    _table(report["quality"], total=False, height=330)
    st.markdown("**7.1 Store Numbers Used by Location**")
    _table(report["store_numbers"], height=320)
    st.caption(report["quality_note"])

elif section.startswith("8"):
    st.markdown("#### 8. Customer Feedback")
    fb = report["feedback"]
    if not fb:
        st.warning("The feedback sheet could not be read.", icon="🔒")
    else:
        _table(fb["summary"], total=False, height=170)
        st.markdown("**8.1 Store Breakdown**")
        _table(fb["by_shop"], height=460)
        if fb["targets"] is not None:
            st.markdown("**8.2 Feedback Link Targets by Location**")
            st.caption(f"Online responses against feedback links sent from the WhatsApp Monitor; "
                       f"target {reports.FEEDBACK_LINK_TARGET:.0f}%.")
            _table(fb["targets"], pinned_columns=("Shop",), height=460)

else:
    st.markdown("#### 9. Summary & Key Notes")
    for team, items in report["notes"].items():
        st.markdown(f"**{team}**")
        if not items:
            st.caption(f"No {team.lower()} flags this period.")
        for item in items:
            box = (st.error if item.startswith("[CRITICAL]") else
                   st.success if item.startswith("[WIN]") else st.warning)
            box(item)
