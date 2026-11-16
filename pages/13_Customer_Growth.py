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
            "Group": ["Older locations", "New shops", "Jumia"],
            "Last year": [older_ly["Revenue"], new_shops_ly["Revenue"], r["online"][1]["Revenue"]],
            "This period": [older["Revenue"], new_shops["Revenue"], r["online"][0]["Revenue"]],
        })
        fig = go.Figure()
        for i, g in enumerate(mix["Group"]):
            fig.add_bar(x=["Last year", "This period"], y=mix.loc[i, ["Last year", "This period"]],
                        name=g, marker=dict(color=theme.CATEGORICAL[i]),
                        hovertemplate=f"{g}: KSh %{{y:,.0f}}<extra></extra>")
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title="Kenya revenue: older locations, new shops and Jumia", barmode="stack",
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
               "A shop opens on its first sale in Odoo, which began in December 2023. The Website counts "
               "as an older location; Online is Jumia. Sinza, Uganda and staff or stock tills are left out.")


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


def _rate_tile(col, label: str, now, then, suffix: str, money: bool = False, extra: str = "") -> None:
    """A level as the headline, last year and the change underneath."""
    show = (_money if money else (lambda v: f"{v:,.0f}") if suffix == "count"
            else (lambda v: f"{v:,.1f}{suffix}") if suffix else (lambda v: f"{v:,.2f}"))
    if now is None or pd.isna(now):
        value, note = "—", "no data"
    elif then is None or pd.isna(then):
        value, note = show(now), "no last year to compare"
    elif suffix == "%":
        value, note = show(now), f"{now - then:+.1f} pts · {show(then)} last yr"
    else:
        value, note = show(now), f"{(now - then) / then * 100:+.1f}% · {show(then)} last yr" if then else "—"
    with col.container(border=True):
        st.metric(label, value, note + extra, delta_color="normal" if note[:1] in "+-" else "off")


def _share_bars(now: pd.Series, then: pd.Series, title: str, colours: dict) -> go.Figure:
    """Last year and this period as two 100% bars split by category."""
    fig = go.Figure()
    for name in [c for c in colours if c in now.index or c in then.index]:
        vals = [then.get(name, 0), now.get(name, 0)]
        fig.add_bar(y=["Last year", "This period"], x=vals, orientation="h", name=name,
                    marker=dict(color=colours[name], line=dict(color=theme.CHART_SURFACE, width=1)),
                    text=[f"{v:.0f}%" if v >= 6 else "" for v in vals], textposition="inside",
                    insidetextanchor="middle", textfont=dict(color="#ffffff", size=12),
                    hovertemplate=f"{name}: <b>%{{x:.1f}}%</b><extra></extra>")
    theme.apply_layout(fig, show_legend=True)
    fig.update_layout(title=title, barmode="stack", height=240, hovermode="closest", bargap=0.35)
    fig.update_xaxes(range=[0, 100], ticksuffix="%", showgrid=False)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig


def _bucket_bars(now: pd.Series, then: pd.Series, title: str, x_title: str) -> go.Figure:
    """Share of customers in each bucket, last year beside this period."""
    fig = go.Figure()
    fig.add_bar(x=then.index, y=then.values, name="Last year",
                marker=dict(color=theme.OTHER, cornerradius=3),
                hovertemplate="%{x}: <b>%{y:.1f}%</b> last year<extra></extra>")
    fig.add_bar(x=now.index, y=now.values, name="This period",
                marker=dict(color=theme.CATEGORICAL[0], cornerradius=3),
                text=[f"{v:.0f}%" for v in now.values], textposition="outside", cliponaxis=False,
                hovertemplate="%{x}: <b>%{y:.1f}%</b> this period<extra></extra>")
    theme.apply_layout(fig, show_legend=True)
    fig.update_layout(title=title, barmode="group", height=340, hovermode="closest", bargap=0.3)
    fig.update_yaxes(ticksuffix="%", rangemode="tozero")
    fig.update_xaxes(title=x_title)
    return fig


def _buckets(values: pd.Series, edges: list, labels: list) -> pd.Series:
    """% of values in each bucket."""
    if values.empty:
        return pd.Series(0.0, index=labels)
    b = pd.cut(values, edges, labels=labels, right=True)
    return b.value_counts(normalize=True).reindex(labels).fillna(0) * 100


@st.fragment()
def render_behaviour(r: dict, start_date, end_date) -> None:
    ly_start, ly_end = r["last_year"]
    scope = st.segmented_control("Customers of", ["All Kenya", "Older locations", "New shops"],
                                 default="All Kenya", key="growth_behaviour_scope") or "All Kenya"
    group = {"Older locations": cg.OLDER, "New shops": cg.NEW_SHOP}.get(scope)

    def prepare(df, s, e):
        before_start = (s.replace(day=1) - pd.Timedelta(days=1)).replace(day=1)
        before = cg._orders(before_start, s - pd.Timedelta(days=1), ly_start)
        if group:
            groups = r["orders"][0].groupby("Location")["Group"].first()
            before = before[before["Location"].map(groups).eq(group)]
            df = df[df["Group"] == group]
        kept, out = cg.split_bulk(df)
        return kept, out, cg.split_bulk(before)[0]

    now, now_out, now_before = prepare(r["orders"][0], start_date, end_date)
    then, then_out, then_before = prepare(r["orders"][1], ly_start, ly_end)
    if now.empty:
        st.info("No customer sales here in this period.")
        return
    b, b_ly = cg.behaviour(now, now_before), cg.behaviour(then, then_before)

    st.caption(f"**{scope}**, {start_date:%d %b %Y} – {end_date:%d %b %Y} against "
               f"{ly_start:%d %b %Y} – {ly_end:%d %b %Y}. Bulk orders (more than {cg.BULK_UNITS} items) "
               "and corporate orders are left out, so these figures describe ordinary customers.")

    row = st.columns(4)
    _rate_tile(row[0], "Customers", b["Customers"], b_ly["Customers"], "count")
    _rate_tile(row[1], "Average order value", b["Average Order Value"], b_ly["Average Order Value"], "",
               money=True, extra=f" · {b['Items per Order']:.1f} items per order" if b["Items per Order"] else "")
    _rate_tile(row[2], "Repeat customers", b["Repeat Customers %"], b_ly["Repeat Customers %"], "%",
               extra=" · bought on 2+ days")
    _rate_tile(row[3], "Revenue per customer", b["Revenue per Customer"], b_ly["Revenue per Customer"], "",
               money=True)
    row = st.columns(4)
    _rate_tile(row[0], "Came back next month", b["Came Back Next Month %"], b_ly["Came Back Next Month %"],
               "%", extra=" · of the month before's buyers")
    _rate_tile(row[1], "Bought twice in the same month", b["Bought Twice in a Month %"],
               b_ly["Bought Twice in a Month %"], "%")
    _rate_tile(row[2], "New customers", b["New Customers %"], b_ly["New Customers %"], "%",
               extra=" · first Denri purchase")
    with row[3].container(border=True):
        st.metric("Bulk & corporate orders left out", f"{now_out['Order ID'].nunique():,}",
                  f"{_money(now_out['Revenue'].sum())} · {len(then_out):,} last yr", delta_color="off")

    # ------------------------------------------------- how often they come back ---
    st.subheader("How often customers come back")
    visits = now[(now["Revenue"] > 0) & now["Key"].notna()].groupby("Key")["Date"].nunique()
    visits_ly = then[(then["Revenue"] > 0) & then["Key"].notna()].groupby("Key")["Date"].nunique()
    edges, labels = [0, 1, 2, 3, 10**6], ["1 day", "2 days", "3 days", "4+ days"]
    gaps, gaps_ly = cg.visit_gaps(now), cg.visit_gaps(then)
    gap_edges, gap_labels = [0, 7, 14, 30, 60, 10**6], ["Within a week", "8–14 days", "15–30 days",
                                                         "31–60 days", "Over 60 days"]
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        theme.show(_bucket_bars(_buckets(visits, edges, labels), _buckets(visits_ly, edges, labels),
                                "Days each customer bought on", "Purchase days in the period"))
    with c2, st.container(border=True):
        theme.show(_bucket_bars(_buckets(gaps, gap_edges, gap_labels),
                                _buckets(gaps_ly, gap_edges, gap_labels),
                                "Time until the next purchase", "Gap between purchase days"))
    ten, ten_ly = cg.tenure(now, start_date), cg.tenure(then, ly_start)
    ten_edges, ten_labels = [-1, 3, 6, 12, 24, 10**6], ["Under 3 months", "3–6 months", "6–12 months",
                                                        "1–2 years", "Over 2 years"]
    c1, c2 = st.columns([3, 2])
    with c1, st.container(border=True):
        theme.show(_bucket_bars(_buckets(ten, ten_edges, ten_labels),
                                _buckets(ten_ly, ten_edges, ten_labels),
                                "Returning customers: how long since their first purchase",
                                "Time since first Denri purchase"))
    with c2, st.container(border=True):
        freq = pd.DataFrame({
            "Figure": ["Customers", "Bought on 2+ days", "Repeat customers %", "Orders per customer",
                       "Median days to next purchase", "Came back next month %"],
            "Last year": [f"{b_ly['Customers']:,}", f"{(visits_ly >= 2).sum():,}",
                          f"{b_ly['Repeat Customers %'] or 0:.1f}%", f"{b_ly['Orders per Customer'] or 0:.2f}",
                          f"{gaps_ly.median():.0f}" if len(gaps_ly) else "—",
                          f"{b_ly['Came Back Next Month %']:.1f}%" if b_ly["Came Back Next Month %"] else "—"],
            "This period": [f"{b['Customers']:,}", f"{(visits >= 2).sum():,}",
                            f"{b['Repeat Customers %'] or 0:.1f}%", f"{b['Orders per Customer'] or 0:.2f}",
                            f"{gaps.median():.0f}" if len(gaps) else "—",
                            f"{b['Came Back Next Month %']:.1f}%" if b["Came Back Next Month %"] else "—"],
        })
        st.markdown("**Coming back, in numbers**")
        st.dataframe(freq, hide_index=True, width="stretch")
        st.caption("A customer's purchase days are the different days they bought on in the period. "
                   "Came back next month: of the buyers in the month before each month of the period, "
                   "the share who bought again in that month.")

    # -------------------------------------------------------- demographics ---
    st.subheader("Demographic performance")
    g, g_ly = cg.by(now, "Gender"), cg.by(then, "Gender")
    gender_colours = {"Female": theme.CATEGORICAL[0], "Male": theme.CATEGORICAL[1],
                      "Not recorded": theme.OTHER}
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        theme.show(_share_bars(g["Customer Share %"], g_ly["Customer Share %"], "Share of customers",
                               gender_colours))
    with c2, st.container(border=True):
        theme.show(_share_bars(g["Revenue Share %"], g_ly["Revenue Share %"], "Share of revenue",
                               gender_colours))
    table = g.join(g_ly, rsuffix=" (LY)", how="outer").fillna(0)
    table["Customers Change %"] = (table["Customers"] - table["Customers (LY)"]) \
        / table["Customers (LY)"].where(table["Customers (LY)"] > 0) * 100
    table["Revenue Change %"] = (table["Revenue"] - table["Revenue (LY)"]) \
        / table["Revenue (LY)"].where(table["Revenue (LY)"] > 0) * 100
    table = table.reset_index(names="Gender")
    ly_unrecorded = g_ly["Customer Share %"].get("Not recorded", 0)
    comparable = ly_unrecorded < 30   # gender is recorded at the till only since 22 Jul 2026
    gender_cols = (["Gender", "Customers (LY)", "Customers", "Customers Change %", "Customer Share %",
                    "Revenue (LY)", "Revenue", "Revenue Change %", "Revenue Share %"] if comparable else
                   ["Gender", "Customers", "Customer Share %", "Revenue", "Revenue Share %"])
    gender_cols += ["Average Order Value", "Revenue per Customer"] + (["Repeat % (LY)"] if comparable else []) + ["Repeat %"]
    grid.filterable_table(
        table[table["Customers"] > 0][gender_cols].round(1),
        currency_columns=("Revenue (LY)", "Revenue", "Average Order Value", "Revenue per Customer"),
        pinned_columns=("Gender",), height=200, total=False)
    notes = []
    known = table[(table["Gender"] != "Not recorded") & (table["Customers"] > 0)]
    for _, x in known.iterrows():
        change = (f" Revenue {x['Revenue Change %']:+.1f}% and customers {x['Customers Change %']:+.1f}% "
                  "on last year." if comparable else "")
        tone = ("red" if x["Revenue Change %"] < 0 else "green") if comparable else "blue"
        notes.append(f":{tone}[**{x['Gender']}**]: {x['Customer Share %']:.0f}% of customers and "
                     f"{x['Revenue Share %']:.0f}% of revenue, KSh {x['Revenue per Customer']:,.0f} per "
                     f"customer, KSh {x['Average Order Value']:,.0f} per order.{change}")
    if len(known) == 2:
        hi = known.sort_values("Revenue per Customer").iloc[-1]
        lo = known.sort_values("Revenue per Customer").iloc[0]
        if lo["Revenue per Customer"]:
            notes.append(f"**{hi['Gender']}** customers spend {hi['Revenue per Customer'] / lo['Revenue per Customer'] * 100 - 100:.0f}% "
                         f"more each than {lo['Gender'].lower()} customers, and "
                         f"{hi['Repeat %']:.1f}% of them bought more than once (vs {lo['Repeat %']:.1f}%).")
    if "Not recorded" in g.index or ly_unrecorded:
        notes.append(f"Gender isn't recorded for {g['Customer Share %'].get('Not recorded', 0):.0f}% of this "
                     f"period's customers and {ly_unrecorded:.0f}% of last year's"
                     + ("." if comparable else
                        ": staff have recorded it at the till only since 22 Jul 2026, so the change on "
                        "last year by gender isn't meaningful yet. The split above is this period's."))
    with st.container(border=True):
        st.markdown("**Notable changes**")
        st.markdown("\n".join(f"- {n}" for n in notes))

    # ---------------------------------------------------- walk-in vs online ---
    st.subheader("Walk-in and online customers")
    ch, ch_ly = cg.by(now, "Sales Channel"), cg.by(then, "Sales Channel")
    ch_colours = {cg.WALK_IN: theme.CATEGORICAL[2], cg.ONLINE_CH: theme.CATEGORICAL[3], "Other": theme.OTHER}
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        theme.show(_share_bars(ch["Customer Share %"], ch_ly["Customer Share %"], "Share of customers",
                               ch_colours))
    with c2, st.container(border=True):
        theme.show(_share_bars(ch["Revenue Share %"], ch_ly["Revenue Share %"], "Share of revenue",
                               ch_colours))
    per_loc = now[(now["Revenue"] > 0) & now["Key"].notna()].pivot_table(
        index="Location", columns="Sales Channel", values="Key", aggfunc="nunique", fill_value=0)
    per_loc_ly = then[(then["Revenue"] > 0) & then["Key"].notna()].pivot_table(
        index="Location", columns="Sales Channel", values="Key", aggfunc="nunique", fill_value=0)
    per_loc = per_loc.reindex(columns=[cg.WALK_IN, cg.ONLINE_CH], fill_value=0)
    per_loc_ly = per_loc_ly.reindex(columns=[cg.WALK_IN, cg.ONLINE_CH], fill_value=0)
    loc = pd.DataFrame({"Walk-in Customers": per_loc[cg.WALK_IN],
                        "Online Customers": per_loc[cg.ONLINE_CH]})
    loc["Online Share %"] = (loc["Online Customers"]
                             / (loc["Walk-in Customers"] + loc["Online Customers"]).where(lambda v: v > 0) * 100)
    ly_share = (per_loc_ly[cg.ONLINE_CH]
                / (per_loc_ly[cg.WALK_IN] + per_loc_ly[cg.ONLINE_CH]).where(lambda v: v > 0) * 100)
    loc["Online Share % (LY)"] = ly_share.reindex(loc.index)
    loc["Change (pts)"] = loc["Online Share %"] - loc["Online Share % (LY)"]
    loc["Walk-in Revenue per Customer"] = (now[(now["Sales Channel"] == cg.WALK_IN) & now["Key"].notna()]
                                           .groupby("Location")["Revenue"].sum() / loc["Walk-in Customers"]
                                           .where(loc["Walk-in Customers"] > 0))
    loc["Online Revenue per Customer"] = (now[(now["Sales Channel"] == cg.ONLINE_CH) & now["Key"].notna()]
                                          .groupby("Location")["Revenue"].sum() / loc["Online Customers"]
                                          .where(loc["Online Customers"] > 0))
    grid.filterable_table(
        loc.reset_index(names="Location").sort_values("Online Share %", ascending=False).round(1),
        currency_columns=("Walk-in Revenue per Customer", "Online Revenue per Customer"),
        pinned_columns=("Location",), height=min(560, 32 * len(loc) + 120))
    if ch_ly["Customer Share %"].get("Other", 0) > 50:
        st.info("Last year's orders mostly carry no walk-in or online type: the till only started "
                "recording it in January 2026 (every order since February). The last-year bars and "
                "Online Share % (LY) fill in once the comparison period is from February 2026 on.",
                icon="ℹ️")
    st.caption("Activation customers are counted as walk-ins: they came to the stand where the "
               "activation was held. Online is the order's customer type, wherever it was rung up. "
               "Other is staff purchases and orders with no customer type.")


SECTIONS = ["Overview", "Older shops", "Customer behaviour"]
section = st.segmented_control("Section", SECTIONS, default=SECTIONS[0], key="growth_section",
                               label_visibility="collapsed") or SECTIONS[0]
with st.spinner("Reading this period and the same period last year…"):
    report = cg.build(start_date, end_date)
if not report["kenya"][0]["Revenue"]:
    st.info("No sales in Kenya in this period.")
elif section == "Overview":
    render_overview(report, start_date, end_date)
elif section == "Older shops":
    render_older_shops(report, start_date, end_date)
else:
    render_behaviour(report, start_date, end_date)
