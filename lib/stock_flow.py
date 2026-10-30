"""Stock movement: how bags flowed through each outlet over any period.

For an outlet and a period, from Odoo's done stock moves of bags:

    opening + received − sold − transferred out ± adjustments = closing

Opening and closing are worked back from what the outlet holds now by
undoing every move since, so every row adds up. Sold is net of customer
returns; adjustments are stock-count corrections, added minus removed.
In transit and current stock are live.

An outlet is a shop's warehouse, the Website, or the CBD store (the hub that
feeds the Website and tops up the other shops).
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

HISTORY_START = date(2024, 1, 1)
CLOSED_TTL = 12 * 3600      # finished days no longer change

KINDS = ["Received", "Returns", "Sold", "Transferred Out", "Adj Added", "Adj Removed"]
IN_KINDS = ["Received", "Returns", "Adj Added"]
OUT_KINDS = ["Sold", "Transferred Out", "Adj Removed"]

NAMES = {"CBD": "CBD Stocks", "DAR": "Sinza", "WEB": "Website", "KTDA": "KTDA", "UG": "Uganda"}

# label → (pandas period, how many periods the history shows)
GRAINS = {
    "Daily": ("D", 60),
    "Weekly": ("W-SAT", 52),    # Sunday to Saturday
    "Monthly": ("M", 24),
    "Quarterly": ("Q", 12),
    "Yearly": ("Y", 10),
}


def outlet_name(code: str, warehouse: str) -> str:
    if code in NAMES:
        return NAMES[code]
    return " ".join(w for w in warehouse.title().split() if w != "Shop")


@st.cache_data(ttl=CLOSED_TTL, show_spinner=False)
def _moves_closed(start: date, end: date) -> pd.DataFrame:
    from lib import db, queries
    return db.run_query(queries.STOCK_FLOW_MOVES, {"start_date": start, "end_date": end})


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(daily moves per outlet as a Date × (Code, Kind) table, the outlets'
    live stock: Outlet, Code, Current Stock, In Transit). Finished days come
    from memory; only today is read fresh."""
    from lib import db, queries
    today = date.today()
    moves = pd.concat([_moves_closed(HISTORY_START, today - timedelta(days=1)),
                       db.run_query(queries.STOCK_FLOW_MOVES, {"start_date": today, "end_date": today})])
    now = db.run_query(queries.STOCK_FLOW_NOW)
    live = (now.pivot_table(index=["Code", "Warehouse"], columns="Kind", values="Qty",
                            aggfunc="sum", fill_value=0)
            .reindex(columns=["Current Stock", "In Transit"], fill_value=0).reset_index())
    live.insert(0, "Outlet", [outlet_name(c, w) for c, w in zip(live["Code"], live["Warehouse"])])
    live = live.drop(columns="Warehouse")
    daily = (moves.assign(Date=pd.to_datetime(moves["Date"]))
             .pivot_table(index="Date", columns=["Code", "Kind"], values="Qty",
                          aggfunc="sum", fill_value=0))
    return daily, live


def _kind(daily: pd.DataFrame, kind: str, codes: list[str]) -> pd.DataFrame:
    """Date × Code for one kind of move, zero where there was none."""
    cols = [(c, kind) for c in codes if (c, kind) in daily.columns]
    t = daily[cols] if cols else pd.DataFrame(index=daily.index)
    t.columns = [c for c, _ in cols]
    return t.reindex(columns=codes, fill_value=0)


def flows(daily: pd.DataFrame, live: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """One row per outlet for start..end (both inclusive)."""
    codes = live["Code"].tolist()
    totals = {k: _kind(daily, k, codes) for k in KINDS}
    net = sum(totals[k] for k in IN_KINDS) - sum(totals[k] for k in OUT_KINDS)
    days = daily.index.date
    current = live.set_index("Code")["Current Stock"]
    t = live.set_index("Code").copy()
    t["Opening"] = current - net[days >= start].sum()
    t["Closing"] = current - net[days > end].sum()
    within = (days >= start) & (days <= end)
    for k in KINDS:
        t[k] = totals[k][within].sum()
    t["Sold"] = t["Sold"] - t["Returns"]
    t["Adjustments"] = t["Adj Added"] - t["Adj Removed"]
    t["Stock + Transit"] = t["Current Stock"] + t["In Transit"]
    t["Sell-through %"] = (t["Sold"] / (t["Opening"] + t["Received"]).where(lambda v: v > 0) * 100)
    shown = ["Opening", "Received", "Sold", "Transferred Out", "Adjustments", "Closing",
             "In Transit", "Current Stock"]
    t = t[t[shown].abs().sum(axis=1) > 0]
    return t.reset_index().sort_values("Opening", ascending=False)


def history(daily: pd.DataFrame, live: pd.DataFrame, grain: str,
            codes: list[str] | None = None) -> pd.DataFrame:
    """One row per period, newest first, for the given outlets (all if None):
    Period, Start, End, opening to closing."""
    freq, count = GRAINS[grain]
    codes = codes or live["Code"].tolist()
    today = pd.Timestamp(date.today())
    days = pd.date_range(HISTORY_START, today)
    totals = {k: _kind(daily, k, codes).reindex(days, fill_value=0).sum(axis=1) for k in KINDS}
    net = sum(totals[k] for k in IN_KINDS) - sum(totals[k] for k in OUT_KINDS)
    current = live.loc[live["Code"].isin(codes), "Current Stock"].sum()
    # stock at the end of each day: today's is what is on hand now
    closing = current - net[::-1].cumsum()[::-1].shift(-1, fill_value=0)

    period = days.to_period(freq)
    g = pd.DataFrame({k: totals[k] for k in KINDS}).groupby(period)
    t = g.sum()
    t["Start"] = g.apply(lambda f: f.index.min()).dt.date
    t["End"] = g.apply(lambda f: f.index.max()).dt.date
    t["Closing"] = closing.groupby(period).last()
    t["Opening"] = (closing - net).groupby(period).first()
    t["Sold"] = t["Sold"] - t["Returns"]
    t["Adjustments"] = t["Adj Added"] - t["Adj Removed"]
    t["Sell-through %"] = (t["Sold"] / (t["Opening"] + t["Received"]).where(lambda v: v > 0) * 100).round(1)
    t["Period"] = [period_label(grain, s, e) for s, e in zip(t["Start"], t["End"])]
    cols = ["Period", "Start", "End", "Opening", "Received", "Sold", "Sell-through %",
            "Transferred Out", "Adj Added", "Adj Removed", "Adjustments", "Closing"]
    return t[cols].iloc[::-1].head(count).reset_index(drop=True)


def period_label(grain: str, start: date, end: date) -> str:
    if grain == "Daily":
        return f"{start:%a %d %b %Y}"
    if grain == "Weekly":
        return f"{start:%d %b} – {end:%d %b %Y}"
    if grain == "Monthly":
        return f"{start:%B %Y}"
    if grain == "Quarterly":
        return f"Q{(start.month - 1) // 3 + 1} {start:%Y}"
    return f"{start:%Y}"


# ----------------------------------------------------------------- table ---
# The outlet breakdown: grouped columns (start, during the range, end, now),
# sortable headers, a search box and a CSV export, all in the page itself.

_TABLE_CSS = """
<style>
.sf { --sf-start: rgba(148,148,170,.16);
      --sf-range: rgba(56,132,255,.16); --sf-range-ink: #7fb2ff; --sf-range-line: rgba(56,132,255,.55);
      --sf-end: rgba(139,92,246,.20); --sf-end-ink: #c4b2ff; --sf-end-line: rgba(139,92,246,.65);
      --sf-now: rgba(34,197,94,.14); --sf-now-ink: #5ee08f; --sf-now-line: rgba(34,197,94,.55);
      --sf-up: #4ade80; --sf-down: #f87171; --sf-zebra: rgba(255,255,255,.025);
      --sf-row-line: rgba(255,255,255,.06); --sf-sticky: #14141b;
      position: relative; border-radius: 22px; padding: 22px 22px 14px 24px;
      border: 1px solid var(--denri-hair, rgba(255,255,255,.08));
      border-left: 2px solid var(--sf-now-line);
      background: var(--denri-glass, rgba(255,255,255,.03)); color: var(--denri-text); }
html[data-denri-theme="light"] .sf {
      --sf-start: rgba(23,23,28,.07); --sf-range: rgba(37,99,235,.10); --sf-range-ink: #1d4ed8;
      --sf-range-line: rgba(37,99,235,.45); --sf-end: rgba(124,58,237,.11); --sf-end-ink: #6d28d9;
      --sf-end-line: rgba(124,58,237,.5); --sf-now: rgba(22,163,74,.10); --sf-now-ink: #15803d;
      --sf-now-line: rgba(22,163,74,.5); --sf-up: #15803d; --sf-down: #dc2626;
      --sf-zebra: rgba(23,23,28,.03); --sf-row-line: rgba(23,23,28,.08); --sf-sticky: #f6f7fa; }
.sf-top { display: flex; gap: 16px; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; }
.sf-title { color: var(--sf-now-ink); font-weight: 700; font-size: 1.02rem; margin: 0 0 4px; }
.sf-sub { color: var(--denri-muted); font-size: .86rem; margin: 0; max-width: 820px; }
.sf-tools { display: flex; gap: 10px; align-items: center; }
.sf-count { color: var(--denri-muted); font-size: .8rem; white-space: nowrap; }
.sf-search { width: 200px; padding: 8px 14px; border-radius: 12px; font: inherit; font-size: .84rem;
      color: var(--denri-text); background: var(--denri-field, transparent);
      border: 1px solid var(--denri-hair, rgba(128,128,140,.3)); outline: none; }
.sf-search:focus { border-color: var(--sf-range-line); }
.sf-export { padding: 8px 14px; border-radius: 12px; font: inherit; font-size: .82rem; font-weight: 700;
      cursor: pointer; color: var(--denri-text); background: var(--denri-field, transparent);
      border: 1px solid var(--denri-hair, rgba(128,128,140,.3)); transition: transform .15s; }
.sf-export:hover { transform: translateY(-1px); border-color: var(--sf-now-line); }
.sf-scroll { margin-top: 18px; max-height: 640px; overflow: auto; }
.sf table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: .86rem;
      font-variant-numeric: tabular-nums; }
.sf th, .sf td { padding: 0 10px; text-align: left; white-space: nowrap; }
.sf th:first-child, .sf td:first-child { padding-left: 4px; }
.sf thead th { position: sticky; z-index: 2; background: var(--sf-sticky); }
.sf .sf-groups th { top: 0; height: 34px; font-size: .7rem; font-weight: 800; letter-spacing: .08em;
      text-transform: uppercase; text-align: center; }
.sf .sf-cols th { top: 34px; height: 44px; font-size: .64rem; font-weight: 800; letter-spacing: .04em;
      text-transform: uppercase; color: var(--denri-text-2); cursor: pointer; user-select: none;
      border-bottom: 2px solid var(--sf-now-line); }
.sf .sf-cols th { white-space: normal; line-height: 1.25; min-width: 64px; }
.sf .sf-cols th:hover { color: var(--denri-text); }
.sf .sf-arrow { opacity: .45; margin-left: 4px; font-size: .75rem; }
.sf .sf-cols th[data-dir] .sf-arrow { opacity: 1; color: var(--sf-range-ink); }
.sf .sf-groups th.g-start { background: linear-gradient(var(--sf-start), var(--sf-start)), var(--sf-sticky);
      color: var(--denri-text); border-radius: 12px 12px 0 0; }
.sf .sf-groups th.g-range { background: linear-gradient(var(--sf-range), var(--sf-range)), var(--sf-sticky);
      color: var(--sf-range-ink); border-radius: 12px 12px 0 0; }
.sf .sf-groups th.g-end { background: linear-gradient(var(--sf-end), var(--sf-end)), var(--sf-sticky);
      color: var(--sf-end-ink); border-radius: 12px 12px 0 0; }
.sf .sf-groups th.g-now { background: linear-gradient(var(--sf-now), var(--sf-now)), var(--sf-sticky);
      color: var(--sf-now-ink); border-radius: 12px 12px 0 0; }
.sf .sf-cols th.c-start { border-bottom-color: var(--denri-text-2); }
.sf .sf-cols th.c-range { border-bottom-color: var(--sf-range-line); }
.sf .sf-cols th.c-end { border-bottom-color: var(--sf-end-line); }
.sf .sf-cols th.c-now { border-bottom-color: var(--sf-now-line); }
.sf tbody td { height: 54px; border-bottom: 1px solid var(--sf-row-line); color: var(--denri-text); }
.sf tbody tr:nth-child(even) td { background: var(--sf-zebra); }
.sf tbody tr:hover td { background: rgba(127,178,255,.08); }
.sf td.name, .sf td.bold { font-weight: 800; }
.sf .b-start { border-left: 1px solid var(--sf-row-line); }
.sf .b-range { border-left: 1px solid var(--sf-range-line); }
.sf .b-end { border-left: 1px solid var(--sf-end-line); border-right: 1px solid var(--sf-end-line); }
.sf .dash { color: var(--denri-muted); }
.sf .up { color: var(--sf-up); font-weight: 600; }
.sf .down { color: var(--sf-down); font-weight: 600; }
.sf .note { display: block; color: var(--denri-muted); font-size: .72rem; margin-top: 3px; font-weight: 500; }
.sf tfoot td { position: sticky; bottom: 0; z-index: 1; height: 48px; font-weight: 800;
      background: var(--sf-sticky); border-top: 2px solid var(--sf-now-line); color: var(--denri-text); }
.sf-empty { padding: 26px; text-align: center; color: var(--denri-muted); }
</style>
"""

# Builds nothing from markup strings: those would be stripped from the script.
_TABLE_JS = """
<script>
(() => {
  const init = (tries) => {
    const root = document.getElementById("__ID__");
    if (!root) { if (tries < 60) requestAnimationFrame(() => init(tries + 1)); return; }
    if (root.dataset.bound) return;
    root.dataset.bound = "1";
    const body = root.querySelector("tbody");
    const rows = () => Array.from(body.rows);
    const shown = () => rows().filter((r) => !r.hidden);
    const count = root.querySelector(".sf-count");
    const recount = () => { count.textContent = shown().length + " rows"; };
    const heads = Array.from(root.querySelectorAll(".sf-cols th"));
    heads.forEach((th, i) => th.addEventListener("click", () => {
      const dir = th.dataset.dir === "desc" ? "asc" : "desc";
      heads.forEach((h) => delete h.dataset.dir);
      th.dataset.dir = dir;
      rows().sort((a, b) => {
        const x = a.cells[i].dataset.v, y = b.cells[i].dataset.v;
        const c = i > 0 ? parseFloat(x) - parseFloat(y) : x.localeCompare(y);
        return dir === "asc" ? c : -c;
      }).forEach((r) => body.appendChild(r));
    }));
    root.querySelector(".sf-search").addEventListener("input", (e) => {
      const q = e.target.value.trim().toLowerCase();
      rows().forEach((r) => { r.hidden = Boolean(q) && !r.cells[0].dataset.v.toLowerCase().includes(q); });
      recount();
    });
    root.querySelector(".sf-export").addEventListener("click", () => {
      const cell = (v) => /[",]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
      const lines = [heads.map((h) => cell(h.dataset.label)).join(",")];
      shown().forEach((r) => lines.push(Array.from(r.cells).map((c) => cell(c.dataset.v)).join(",")));
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([lines.join("\\n")], { type: "text/csv" }));
      a.download = root.dataset.file;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
  };
  init(0);
})();
</script>
"""

# (label, field, group, kind)
_COLUMNS = [
    ("Outlet", "Outlet", "", "name"),
    ("Opening Stock", "Opening", "start", "num"),
    ("Received", "Received", "range", "num"),
    ("Sold", "Sold", "range", "sold"),
    ("Transferred Out", "Transferred Out", "range", "num"),
    ("Stock Adjustments", "Adjustments", "range", "adj"),
    ("Closing Stock", "Closing", "end", "bold"),
    ("In Transit", "In Transit", "now", "num"),
    ("Current Stock", "Current Stock", "now", "bold"),
    ("Stock + Transit", "Stock + Transit", "now", "num"),
]


def _cells(row: pd.Series) -> str:
    out, seen = [], set()
    for _, field, group, kind in _COLUMNS:
        cls = [f"b-{group}"] if group and group not in seen else []
        seen.add(group)
        v = row[field]
        if kind == "name":
            out.append(f'<td class="name" data-v="{escape(str(v))}">{escape(str(v))}</td>')
            continue
        value = 0.0 if pd.isna(v) else float(v)
        text = f"{value:,.0f}" if round(value) else '<span class="dash">—</span>'
        if kind == "bold":
            cls.append("bold")
        if kind == "adj" and round(value):
            text = f'<span class="{"up" if value > 0 else "down"}">{value:+,.0f}</span>'
            if row["Adj Added"] and row["Adj Removed"]:
                text += (f'<span class="note" title="added · removed">+{row["Adj Added"]:,.0f} · '
                         f'−{row["Adj Removed"]:,.0f}</span>')
        if kind == "sold" and round(value) and pd.notna(row["Sell-through %"]):
            text += f'<span class="note">{row["Sell-through %"]:.1f}% sell-through</span>'
        attr = f' class="{" ".join(cls)}"' if cls else ""
        out.append(f'<td{attr} data-v="{value:.0f}">{text}</td>')
    return "".join(out)


def table_html(t: pd.DataFrame, start: date, end: date) -> str:
    """The outlet breakdown for start..end (from flows()) as one HTML block."""
    uid = f"sf-{start:%Y%m%d}-{end:%Y%m%d}"
    groups = (f'<tr class="sf-groups"><th></th>'
              f'<th class="g-start">Start · {start:%d %b}</th>'
              f'<th class="g-range" colspan="4">During the range</th>'
              f'<th class="g-end">End · {end:%d %b}</th>'
              f'<th class="g-now" colspan="3">Now (live)</th></tr>')
    heads = "".join(f'<th class="{"c-" + group if group else ""}" data-label="{label}">'
                    f'{label}<span class="sf-arrow">↕</span></th>'
                    for label, _, group, _ in _COLUMNS)
    body = "".join(f"<tr>{_cells(row)}</tr>" for _, row in t.iterrows())
    body = body or f'<tr><td class="sf-empty" colspan="{len(_COLUMNS)}">No bags here.</td></tr>'
    total = t.select_dtypes("number").sum()
    total["Outlet"] = "Total"
    stocked = total["Opening"] + total["Received"]
    total["Sell-through %"] = total["Sold"] / stocked * 100 if stocked > 0 else float("nan")
    span = (f"on {start:%d %b}" if start == end else
            f"on {start:%d %b}, what came in and went out up to {end:%d %b %Y},")
    return _TABLE_CSS + f"""
<div class="sf" id="{uid}" data-file="stock-flow-{start:%Y-%m-%d}-to-{end:%Y-%m-%d}.csv">
  <div class="sf-top">
    <div>
      <p class="sf-title">Stock Flow by Outlet</p>
      <p class="sf-sub">Bags each outlet had {span} and what it holds today. Bags only —
        combo and bundle items aren't physical stock.</p>
    </div>
    <div class="sf-tools">
      <span class="sf-count">{len(t)} rows</span>
      <input class="sf-search" type="search" placeholder="Search outlet…" aria-label="Search outlet">
      <button class="sf-export" type="button">Export CSV</button>
    </div>
  </div>
  <div class="sf-scroll">
    <table>
      <thead>{groups}<tr class="sf-cols">{heads}</tr></thead>
      <tbody>{body}</tbody>
      <tfoot><tr>{_cells(total)}</tr></tfoot>
    </table>
  </div>
</div>""" + _TABLE_JS.replace("__ID__", uid)
