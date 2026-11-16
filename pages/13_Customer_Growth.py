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


@st.fragment()
def render_overview(start_date, end_date) -> None:
    with st.spinner("Reading this period and the same period last year…"):
        r = cg.build(start_date, end_date)
    (ly_start, ly_end) = r["last_year"]
    older, older_ly = r["older"]
    new_shops, new_shops_ly = r["new_shops"]
    kenya, kenya_ly = r["kenya"]
    shops = r["shops"]
    old = shops[shops["Group"] == cg.OLDER].copy()
    new = shops[shops["Group"] == cg.NEW_SHOP].copy()
    if not kenya["Revenue"]:
        st.info("No sales in Kenya in this period.")
        return

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
    c1, c2 = st.columns([2, 3])
    with c1, st.container(border=True):
        ranked = old.sort_values("Change")
        fig = go.Figure(go.Bar(
            y=ranked["Location"], x=ranked["Change"], orientation="h",
            marker=dict(color=[RED if v < 0 else GREEN for v in ranked["Change"]], cornerradius=4),
            text=[_money(v) for v in ranked["Change"]], textposition="outside", cliponaxis=False,
            customdata=ranked[["Revenue LY", "Revenue", "Change %"]],
            hovertemplate="<b>%{y}</b><br>KSh %{customdata[0]:,.0f} → KSh %{customdata[1]:,.0f}"
                          "<br>%{customdata[2]:+.1f}%<extra></extra>"))
        theme.apply_layout(fig, show_legend=False)
        fig.update_layout(title="Revenue change vs last year", height=max(380, 30 * len(ranked) + 100))
        theme.show(fig)
    with c2, st.container(border=True):
        grid.filterable_table(
            old.sort_values("Change")[["Location", "Opened", "Revenue LY", "Revenue", "Change",
                                       "Change %", "Orders LY", "Orders"]]
            .rename(columns={"Revenue LY": "Revenue (LY)", "Orders LY": "Orders (LY)"}),
            currency_columns=("Revenue (LY)", "Revenue", "Change"), pinned_columns=("Location",),
            height=max(380, 30 * len(ranked) + 100))

    # -------------------------------------- new-customer change by older shop ---
    st.subheader("New-customer change by older shop")
    old["New Change"] = old["New Customers"] - old["New Customers LY"]
    old["New Change %"] = (old["New Change"] / old["New Customers LY"].where(old["New Customers LY"] > 0)
                           * 100).round(1)
    old["Returning Change"] = old["Returning Customers"] - old["Returning Customers LY"]
    c1, c2 = st.columns([2, 3])
    with c1, st.container(border=True):
        ranked = old.sort_values("New Change")
        fig = go.Figure()
        fig.add_bar(y=ranked["Location"], x=ranked["New Customers LY"], orientation="h",
                    name="Last year", marker=dict(color=theme.OTHER, cornerradius=3))
        fig.add_bar(y=ranked["Location"], x=ranked["New Customers"], orientation="h",
                    name="This period", marker=dict(color=theme.CATEGORICAL[0], cornerradius=3))
        theme.apply_layout(fig, show_legend=True)
        fig.update_layout(title="New customers: last year and this period", barmode="group",
                          height=max(420, 40 * len(ranked) + 100))
        theme.show(fig)
    with c2, st.container(border=True):
        grid.filterable_table(
            ranked[["Location", "New Customers LY", "New Customers", "New Change", "New Change %",
                    "Returning Customers LY", "Returning Customers", "Returning Change"]]
            .rename(columns={"New Customers LY": "New (LY)", "New Customers": "New",
                             "New Change": "Change", "New Change %": "Change %",
                             "Returning Customers LY": "Returning (LY)",
                             "Returning Customers": "Returning"}),
            pinned_columns=("Location",), height=max(420, 40 * len(ranked) + 100))

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


render_overview(start_date, end_date)
