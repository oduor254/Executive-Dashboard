"""Customer Growth — are the older shops still growing, or are the new shops
carrying the business? Older shops against the same period last year, new and
returning customers, Kenya only (lib/customer_growth.py)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, filters, grid, theme
from lib import customer_growth as cg

st.set_page_config(page_title=auth.page_title("Customer Growth"), page_icon="📈", layout="wide")

auth.require_login()

st.title("📈 Customer Growth")
st.caption("Older shops against the same period last year, new and returning customers, and what "
           "the new shops add. Live from the POS, Kenya only.")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_refresh = st.columns([3, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("growth", default="Month to Date", compare=False)
with col_refresh:
    db.refresh_button(key="growth_refresh")

RED, GREEN = theme.STATUS["critical"], theme.CATEGORICAL[1]


def _money(v: float) -> str:
    """KSh 263.7M, KSh 845K, KSh 950."""
    a = abs(v)
    text = f"{a / 1e6:,.1f}M" if a >= 1e6 else f"{a / 1e3:,.0f}K" if a >= 1e4 else f"{a:,.0f}"
    return f"{'-' if v < 0 else ''}KSh {text}"


def _signed(v: float, money: bool) -> str:
    if money:
        a = abs(v)
        text = f"{a / 1e6:,.1f}M" if a >= 1e6 else f"{a / 1e3:,.0f}K" if a >= 1e4 else f"{a:,.0f}"
    else:
        text = f"{abs(v):,.0f}"
    return ("+" if v > 0 else "−" if v < 0 else "") + text


def _pct(now, then) -> float | None:
    return (now - then) / then * 100 if then else None


def _change_tile(col, label: str, now, then, money: bool) -> None:
    """The change as the headline, 'from → to (±x%)' underneath, red when down."""
    now, then = now or 0, then or 0
    pct = _pct(now, then)
    show = _money if money else (lambda v: f"{v:,.0f}")
    note = (f"{pct:+.1f}% · " if pct is not None else "new · ") + f"{show(then)} → {show(now)}"
    with col.container(border=True):
        st.metric(label, _signed(now - then, money), note,
                  delta_color="normal" if now != then else "off")


def _dumbbell(df: pd.DataFrame, before: str, after: str, title: str, money: bool) -> go.Figure:
    """Each shop as a line from last year (hollow dot) to this period (filled
    dot, red when down), biggest fall first, the change written at the end."""
    t = df.assign(_chg=df[after] - df[before]).sort_values("_chg")
    t["_pct"] = t["_chg"] / t[before].where(t[before] > 0) * 100
    show = _money if money else (lambda v: f"{v:,.0f}")
    colours = [RED if v < 0 else GREEN for v in t["_chg"]]
    fig = go.Figure()
    xs, ys = [], []
    for loc, a, b in zip(t["Location"], t[before], t[after]):
        xs += [a, b, None]
        ys += [loc, loc, None]
    fig.add_scatter(x=xs, y=ys, mode="lines", line=dict(color=theme.OTHER, width=3),
                    hoverinfo="skip", showlegend=False)
    fig.add_scatter(x=t[before], y=t["Location"], mode="markers", name="Last year",
                    marker=dict(size=11, color="rgba(0,0,0,0)", line=dict(color=theme.OTHER, width=2)),
                    hovertemplate="%{y} last year: <b>%{text}</b><extra></extra>",
                    text=[show(v) for v in t[before]])
    fig.add_scatter(x=t[after], y=t["Location"], mode="markers", name="This period",
                    marker=dict(size=12, color=colours),
                    customdata=list(zip([show(v) for v in t[before]], [show(v) for v in t[after]],
                                        t["_pct"].fillna(0))),
                    hovertemplate="<b>%{y}</b><br>%{customdata[0]} → %{customdata[1]}"
                                  "<br>%{customdata[2]:+.1f}%<extra></extra>")
    for loc, chg, pct, colour in zip(t["Location"], t["_chg"], t["_pct"], colours):
        label = (("+" if chg > 0 else "−") + show(abs(chg))).replace("−-", "−")
        label += f"  ({pct:+.0f}%)" if pd.notna(pct) else ""
        fig.add_annotation(x=1, xref="paper", xanchor="left", xshift=10, y=loc, yref="y",
                           text=f"<b>{label}</b>", showarrow=False, font=dict(color=colour, size=12))
    theme.apply_layout(fig, show_legend=True)
    fig.update_layout(title=title, height=max(360, 34 * len(t) + 110), hovermode="closest",
                      margin=dict(r=150))
    fig.update_yaxes(autorange="reversed", showgrid=True)
    fig.update_xaxes(showgrid=True, gridcolor=theme.GRIDLINE, rangemode="tozero",
                     tickprefix="KSh " if money else "")
    return fig


@st.fragment()
def render_overview(r: dict, start_date, end_date) -> None:
    (ly_start, ly_end) = r["last_year"]
    older, older_ly = r["older"]
    new_shops, new_shops_ly = r["new_shops"]
    kenya, kenya_ly = r["kenya"]
    shops = r["shops"]
    old = shops[shops["Group"] == cg.OLDER].copy()
    new = shops[shops["Group"] == cg.NEW_SHOP].copy()
    st.caption(f"**{start_date:%d %b %Y} – {end_date:%d %b %Y}** against the same period last year, "
               f"**{ly_start:%d %b %Y} – {ly_end:%d %b %Y}**. Older shops: the {len(old)} shops already "
               f"open then. New shops: the {len(new)} opened since.")

    # ------------------------------------------------------------- tiles ---
    row = st.columns(4)
    _change_tile(row[0], "Older shops, revenue", older["Revenue"], older_ly["Revenue"], True)
    _change_tile(row[1], "Older shops, new customers", older["New Customers"],
                 older_ly["New Customers"], False)
    _change_tile(row[2], "Older shops, returning-customer revenue",
                 older["Returning-Customer Revenue"], older_ly["Returning-Customer Revenue"], True)
    _change_tile(row[3], "All Kenya, first-time Denri buyers", kenya["New Customers"],
                 kenya_ly["New Customers"], False)
    row = st.columns(4)
    _change_tile(row[0], "Older shops, returning customers", older["Returning Customers"],
                 older_ly["Returning Customers"], False)
    _change_tile(row[1], "Older shops, avg spend per customer", older["Avg Spend / Customer"],
                 older_ly["Avg Spend / Customer"], True)
    with row[2].container(border=True):
        share = new_shops["Revenue"] / kenya["Revenue"] * 100
        st.metric("New shops, revenue", _money(new_shops["Revenue"]),
                  f"{share:.1f}% of Kenya revenue · {len(new)} shops", delta_color="off")
    _change_tile(row[3], "All Kenya, revenue", kenya["Revenue"], kenya_ly["Revenue"], True)

    # ---------------------------------------------- what the numbers say ---
    d_rev = older["Revenue"] - older_ly["Revenue"]
    d_new_rev = older["New-Customer Revenue"] - older_ly["New-Customer Revenue"]
    d_ret_rev = older["Returning-Customer Revenue"] - older_ly["Returning-Customer Revenue"]
    kenya_ex_new = kenya["Revenue"] - new_shops["Revenue"]
    old["Change"] = old["Revenue"] - old["Revenue LY"]
    old["Change %"] = (old["Change"] / old["Revenue LY"].where(old["Revenue LY"] > 0) * 100).round(1)
    falling = old.sort_values("Change").head(3)
    growing = old[old["Change"] > 0].sort_values("Change", ascending=False)
    word = lambda v: "fell" if v < 0 else "grew"

    points = [
        f"**Older shops' revenue {word(d_rev)} {abs(_pct(older['Revenue'], older_ly['Revenue']) or 0):.1f}%**, "
        f"from {_money(older_ly['Revenue'])} to {_money(older['Revenue'])}. New customers account for "
        f"{_money(d_new_rev)} of the change and returning customers for {_money(d_ret_rev)}.",
        f"**New customers at older shops**: {older_ly['New Customers']:,} → {older['New Customers']:,} "
        f"({_pct(older['New Customers'], older_ly['New Customers']) or 0:+.1f}%). Returning customers: "
        f"{older_ly['Returning Customers']:,} → {older['Returning Customers']:,} "
        f"({_pct(older['Returning Customers'], older_ly['Returning Customers']) or 0:+.1f}%).",
        f"**New shops brought in {_money(new_shops['Revenue'])}**, {share:.1f}% of Kenya's revenue. "
        f"Kenya as a whole is {_pct(kenya['Revenue'], kenya_ly['Revenue']) or 0:+.1f}% on last year; "
        f"without the new shops it would be {_pct(kenya_ex_new, kenya_ly['Revenue']) or 0:+.1f}%.",
        f"**First-time Denri buyers across Kenya**: {kenya_ly['New Customers']:,} → "
        f"{kenya['New Customers']:,}. {new_shops['New Customers']:,} of this period's came through a new shop.",
        "**Biggest falls**: " + ", ".join(
            f"{loc} ({_money(chg)}, {pct:+.0f}%)" for loc, chg, pct in
            zip(falling["Location"], falling["Change"], falling["Change %"].fillna(0))) + "."
        + (f" Growing: {', '.join(growing['Location'])}." if not growing.empty else
           " No older shop is ahead of last year."),
        f"**Average spend per customer** at older shops: {_money(older_ly['Avg Spend / Customer'] or 0)} → "
        f"{_money(older['Avg Spend / Customer'] or 0)}.",
    ]
    with st.container(border=True):
        st.markdown("#### What the numbers say")
        st.markdown("\n".join(f"- {p}" for p in points))

    # ------------------------------------------ revenue change by older shop ---
    st.subheader("Revenue change by older shop")
    with st.container(border=True):
        theme.show(_dumbbell(old, "Revenue LY", "Revenue", "Revenue: last year → this period", True))
    with st.container(border=True):
        grid.filterable_table(
            old.sort_values("Change")[["Location", "Opened", "Revenue LY", "Revenue", "Change",
                                       "Change %", "Orders LY", "Orders"]]
            .rename(columns={"Revenue LY": "Revenue (LY)", "Orders LY": "Orders (LY)"}),
            currency_columns=("Revenue (LY)", "Revenue", "Change"), pinned_columns=("Location",),
            height=min(520, 34 * len(old) + 120))

    # -------------------------------------- new-customer change by older shop ---
    st.subheader("New-customer change by older shop")
    old["New Change"] = old["New Customers"] - old["New Customers LY"]
    old["New Change %"] = (old["New Change"] / old["New Customers LY"].where(old["New Customers LY"] > 0)
                           * 100).round(1)
    old["Returning Change"] = old["Returning Customers"] - old["Returning Customers LY"]
    ranked = old.sort_values("New Change")
    with st.container(border=True):
        theme.show(_dumbbell(old, "New Customers LY", "New Customers",
                             "New customers: last year → this period", False))
    with st.container(border=True):
        grid.filterable_table(
            ranked[["Location", "New Customers LY", "New Customers", "New Change", "New Change %",
                    "Returning Customers LY", "Returning Customers", "Returning Change"]]
            .rename(columns={"New Customers LY": "New (LY)", "New Customers": "New",
                             "New Change": "Change", "New Change %": "Change %",
                             "Returning Customers LY": "Returning (LY)",
                             "Returning Customers": "Returning"}),
            pinned_columns=("Location",), height=min(520, 34 * len(ranked) + 120))

    # ------------------------------------ where the older shops' change came from ---
    st.subheader("Where the older shops' revenue change came from")
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        unknown_ly = older_ly["Revenue"] - older_ly["New-Customer Revenue"] - older_ly["Returning-Customer Revenue"]
        unknown = older["Revenue"] - older["New-Customer Revenue"] - older["Returning-Customer Revenue"]
        fig = go.Figure(go.Waterfall(
            x=["Last year", "New customers", "Returning customers", "No phone", "This period"],
            measure=["absolute", "relative", "relative", "relative", "total"],
            y=[older_ly["Revenue"], d_new_rev, d_ret_rev, unknown - unknown_ly, 0],
            text=[_money(older_ly["Revenue"]), _money(d_new_rev), _money(d_ret_rev),
                  _money(unknown - unknown_ly), _money(older["Revenue"])], textposition="outside",
            increasing=dict(marker=dict(color=GREEN)), decreasing=dict(marker=dict(color=RED)),
            totals=dict(marker=dict(color=theme.CATEGORICAL[0])),
            connector=dict(line=dict(color=theme.OTHER))))
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="Older shops' revenue, last year to this period", height=420)
        theme.show(fig)
    with c2, st.container(border=True):
        mix = pd.DataFrame({
            "Group": ["Older shops", "New shops", "Online"],
            "Last year": [older_ly["Revenue"], new_shops_ly["Revenue"], r["online"][1]["Revenue"]],
            "This period": [older["Revenue"], new_shops["Revenue"], r["online"][0]["Revenue"]],
        })
        fig = go.Figure()
        for i, g in enumerate(mix["Group"]):
            fig.add_bar(x=["Last year", "This period"], y=mix.loc[i, ["Last year", "This period"]],
                        name=g, marker=dict(color=theme.CATEGORICAL[i]),
                        hovertemplate=f"{g}: KSh %{{y:,.0f}}<extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title="Kenya revenue: older shops, new shops and online", barmode="stack",
                          height=420)
        theme.show(fig)

    st.subheader("Revenue by customer type, older shops")
    by_type = old.assign(**{
        "New-Customer Change": old["New-Customer Revenue"] - old["New-Customer Revenue LY"],
        "Returning-Customer Change": old["Returning-Customer Revenue"] - old["Returning-Customer Revenue LY"],
    }).sort_values("Returning-Customer Change")
    by_type = by_type[["Location", "New-Customer Revenue LY", "New-Customer Revenue", "New-Customer Change",
                       "Returning-Customer Revenue LY", "Returning-Customer Revenue",
                       "Returning-Customer Change"]].rename(columns=lambda c: c.replace(" LY", " (LY)"))
    grid.filterable_table(by_type, currency_columns=tuple(by_type.columns[1:]),
                          pinned_columns=("Location",), height=420)

    st.subheader("New shops")
    if new.empty:
        st.info("No shop has opened since last year's period.")
    else:
        new["Share of Kenya Revenue %"] = (new["Revenue"] / kenya["Revenue"] * 100).round(1)
        new["Avg Spend / Customer"] = (new["Revenue"] / new["Customers"].where(new["Customers"] > 0)).round(0)
        grid.filterable_table(
            new.sort_values("Revenue", ascending=False)[
                ["Location", "Opened", "Revenue", "Share of Kenya Revenue %", "Orders", "Customers",
                 "New Customers", "Returning Customers", "Avg Spend / Customer"]],
            currency_columns=("Revenue", "Avg Spend / Customer"), pinned_columns=("Location",),
            height=300)

    st.caption("**(LY)**: the same period last year. **New customer**: their first Denri purchase anywhere falls in the period. **Returning "
               "customer**: they had bought from Denri before it. Customers are counted by phone number; "
               "orders with no phone, or a shop's or attendant's own number, are under **No phone**. "
               "A shop opens on its first sale in Odoo, which began in December 2023. Online is the "
               "Website and Jumia; Sinza, Uganda and staff or stock tills are left out.")


def _change_note(row: pd.Series) -> str:
    """One line on what moved a shop's revenue, for the summary table."""
    rev = row["Revenue Δ%"]
    if pd.isna(rev):
        return "No sales last year to compare with."
    d_new = row["New-Customer Revenue"] - row["New-Customer Revenue LY"]
    d_ret = row["Returning-Customer Revenue"] - row["Returning-Customer Revenue LY"]
    driver = ("fewer new customers" if d_new < 0 and d_new <= d_ret else
              "lower returning-customer spend" if d_ret < 0 else
              "more new customers" if d_new > 0 and d_new >= d_ret else "returning customers")
    spend = row["Avg Spend / Customer Δ%"]
    spend_text = (f"; each customer spends {abs(spend):.0f}% {'more' if spend > 0 else 'less'}"
                  if pd.notna(spend) and abs(spend) >= 3 else "")
    return (f"Revenue {'down' if rev < 0 else 'up'} {abs(rev):.0f}%, mainly {driver} "
            f"(new {_money(d_new)}, returning {_money(d_ret)}){spend_text}.")


@st.fragment()
def render_older_shops(r: dict, start_date, end_date) -> None:
    ly_start, ly_end = r["last_year"]
    card = cg.scorecard(r["shops"][r["shops"]["Group"] == cg.OLDER])
    if card.empty:
        st.info("No shop was open in last year's period to compare with.")
        return
    st.caption(f"The {len(card)} shops already open on {ly_start:%d %b %Y}: "
               f"**{start_date:%d %b %Y} – {end_date:%d %b %Y}** against "
               f"**{ly_start:%d %b %Y} – {ly_end:%d %b %Y}**.")

    pick = st.selectbox("Shop", ["All older shops"] + sorted(card["Location"]), key="growth_older_shop")
    if pick == "All older shops":
        older, older_ly = r["older"]
        one = cg.with_ratios(cg.with_ratios(pd.DataFrame([{
            **older, **{k + " LY": v for k, v in older_ly.items()},
            "Identified Revenue": (older["Avg Spend / Customer"] or 0) * older["Customers"],
            "Identified Revenue LY": (older_ly["Avg Spend / Customer"] or 0) * older_ly["Customers"],
        }])), " LY").iloc[0]
    else:
        one = card[card["Location"] == pick].iloc[0]
    tiles = ["Revenue", "Orders", "Bags", "Customers", "New Customers", "Returning Customers",
             "Returning-Customer Revenue", "Avg Spend / Customer"]
    for row in (tiles[:4], tiles[4:]):
        for col, m in zip(st.columns(4), row):
            _change_tile(col, m, one[m], one[m + " LY"], cg.METRICS[m])

    # --------------------------------------------------- notable changes ---
    def worst(metric: str, n: int = 2) -> pd.DataFrame:
        return card.dropna(subset=[metric + " Δ%"]).sort_values(metric + " Δ%").head(n)

    notes = []
    for _, x in worst("Revenue").iterrows():
        notes.append(f":red[**{x['Location']}**] revenue {x['Revenue Δ%']:+.0f}% "
                     f"({_money(x['Revenue LY'])} → {_money(x['Revenue'])}).")
    for _, x in worst("New Customers").iterrows():
        notes.append(f":red[**{x['Location']}**] new customers {x['New Customers Δ%']:+.0f}% "
                     f"({x['New Customers LY']:,.0f} → {x['New Customers']:,.0f}).")
    for _, x in worst("Returning Customers", 1).iterrows():
        if x["Returning Customers Δ%"] < 0:
            notes.append(f":red[**{x['Location']}**] lost the most returning customers: "
                         f"{x['Returning Customers Δ%']:+.0f}%.")
    up = card[card["Revenue Δ%"] > 0].sort_values("Revenue Δ%", ascending=False)
    for _, x in up.iterrows():
        notes.append(f":green[**{x['Location']}**] is ahead of last year: revenue "
                     f"{x['Revenue Δ%']:+.0f}% ({_money(x['Revenue LY'])} → {_money(x['Revenue'])}).")
    ret_up = card[card["Returning-Customer Revenue Δ%"] >= 10].sort_values(
        "Returning-Customer Revenue Δ%", ascending=False).head(3)
    if not ret_up.empty:
        notes.append(":green[Returning customers are spending more at] " + ", ".join(
            f"**{loc}** ({v:+.0f}%)" for loc, v in
            zip(ret_up["Location"], ret_up["Returning-Customer Revenue Δ%"])) + ".")
    spend_up = card[card["Avg Spend / Customer Δ%"] >= 5]
    if len(spend_up):
        notes.append(f"Average spend per customer is up at {len(spend_up)} of {len(card)} shops, "
                     "so the fall is in how many people buy, not how much each spends."
                     if len(spend_up) > len(card) / 2 else
                     f"Average spend per customer is up at {', '.join(spend_up['Location'])}.")
    with st.container(border=True):
        st.markdown("#### Notable changes")
        st.markdown("\n".join(f"- {n}" for n in notes))

    # --------------------------------------------------- change heatmap ---
    shown = ["Revenue", "Orders", "Customers", "New Customers", "Returning Customers",
             "Returning-Customer Revenue", "Avg Spend / Customer", "Avg Order Value"]
    heat = card.set_index("Location").sort_values("Revenue Δ%")[[m + " Δ%" for m in shown]]
    z = heat.clip(-60, 60)
    with st.container(border=True):
        fig = go.Figure(go.Heatmap(
            z=z.values, x=[m.replace("-Customer ", "-customer<br>").replace(" Customers", "<br>customers")
                           .replace(" / ", "<br>per ").replace("Avg Order", "Avg order<br>")
                           .replace("<br> ", "<br>") for m in shown], y=heat.index, zmid=0, zmin=-60, zmax=60,
            colorscale=[[0, theme.DIVERGING["warm"]], [0.5, theme.DIVERGING["mid"]],
                        [1, theme.DIVERGING["cool"]]],
            text=[[f"{v:+.0f}%" if pd.notna(v) else "—" for v in row] for row in heat.values],
            texttemplate="%{text}", textfont=dict(size=12), xgap=3, ygap=3,
            hovertemplate="<b>%{y}</b> · %{x}<br>%{text} vs last year<extra></extra>",
            colorbar=dict(title="vs LY", ticksuffix="%", thickness=10)))
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="Change vs last year, every figure (red down, blue up)",
                          height=max(380, 34 * len(heat) + 140), hovermode="closest")
        fig.update_yaxes(autorange="reversed", showgrid=False)
        fig.update_xaxes(side="bottom", tickangle=0, showgrid=False)
        theme.show(fig)

    # ------------------------------------------------- summary per shop ---
    st.subheader("Summary notes by shop")
    summary = card.sort_values("Revenue Δ%").assign(Note=lambda t: t.apply(_change_note, axis=1))
    grid.filterable_table(
        summary[["Location", "Revenue Δ%", "New Customers Δ%", "Returning Customers Δ%",
                 "Avg Spend / Customer Δ%", "Note"]].round(1)
        .rename(columns=lambda c: c.replace(" Δ%", " Change %")),
        pinned_columns=("Location",), height=min(520, 34 * len(card) + 120), total=False,
        tooltip_columns=("Note",))

    # --------------------------------------------------- full scorecard ---
    st.subheader("Every figure, every older shop")
    cols = ["Location"]
    for m in cg.METRICS:
        cols += [m + " LY", m, m + " Δ%"]
    full = card[cols].copy()
    for m in ("Avg Spend / Customer", "Avg Order Value", "Bags per Order"):
        full[[m + " LY", m]] = full[[m + " LY", m]].round(2 if m == "Bags per Order" else 0)
    full = full.round({c: 1 for c in full.columns if c.endswith("Δ%")})
    full = full.rename(columns=lambda c: c.replace(" LY", " (LY)").replace(" Δ%", " Change %"))
    grid.filterable_table(
        full, pinned_columns=("Location",), height=min(520, 34 * len(card) + 120),
        currency_columns=tuple(c for c in full.columns
                               if any(c.startswith(m) for m, money in cg.METRICS.items() if money)
                               and not c.endswith("Change %")))
    st.caption("**(LY)**: the same period last year. **Change %** is this period against it. "
               "Avg spend per customer counts the sales with a customer's phone number; avg order "
               "value and bags per order count every sale.")


SECTIONS = ["Overview", "Older shops"]
section = st.segmented_control("Section", SECTIONS, default=SECTIONS[0], key="growth_section",
                               label_visibility="collapsed") or SECTIONS[0]
with st.spinner("Reading this period and the same period last year…"):
    report = cg.build(start_date, end_date)
if not report["kenya"][0]["Revenue"]:
    st.info("No sales in Kenya in this period.")
elif section == "Overview":
    render_overview(report, start_date, end_date)
else:
    render_older_shops(report, start_date, end_date)
