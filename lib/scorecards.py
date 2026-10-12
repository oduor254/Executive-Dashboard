"""Shop and shop-attendant score cards.

Built from one row per order (queries.SCORECARD_ORDERS):

  Revenue            — the shop's revenue. For an attendant it is the shop's
                       revenue shared equally between everyone who served at
                       that shop that day: a shop's sales are a team effort,
                       and whoever keyed the order is not the only one who
                       made the sale. Orders nobody was recorded on are
                       shared too. Own Sales is what the person keyed.
  Corporate Revenue  — orders for customers recorded as Corporate.
  Basket Value       — revenue per order; Basket Size — bags per order.
  Repeat Purchase    — share of the customers served who had bought from
                       Denri before (any shop, any time) or bought again in
                       the range.
  Feedback           — share of the customers served who sent a feedback
                       form on or after the day they bought (Google Sheet,
                       matched on the last nine digits of the phone).

Customers are known by phone number. The shops' own numbers — the ones on
the posters, typed in when a customer gives none — and any number shared by
five or more customer records are not customers, and are left out of the
repeat and feedback figures.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NOT_RECORDED = "Not recorded"
NOT_SHOPS = {"Staff POS"}

# Each shop's own number, as printed on its posters (last nine digits).
SHOP_NUMBERS = {
    "118753780", "714156897", "759296069", "720060705", "712532047", "745390465",
    "118753776", "715598778", "115920422", "795176310", "798219855", "707392070",
    "707722454", "790833297", "703869724", "701012197", "118753771",
}
PLACEHOLDER_MIN_RECORDS = 5

# What the overall score is made of: each is ranked against the other shops
# (or attendants) and the ranks averaged, so 100 is best on every measure.
SHOP_SCORE = ["Target %", "Basket Value", "Basket Size", "Repeat %", "Feedback %"]
PERSON_SCORE = ["Revenue per Day", "Basket Value", "Basket Size", "Repeat %", "Feedback %"]


def prepare(orders: pd.DataFrame) -> pd.DataFrame:
    df = orders[~orders["Location"].isin(NOT_SHOPS)].copy()
    df["Revenue"] = pd.to_numeric(df["Revenue"], errors="coerce").fillna(0)
    df["Bags"] = pd.to_numeric(df["Bags"], errors="coerce").fillna(0)
    shared = df.groupby("Customer")["Partner"].nunique()
    placeholders = set(shared[shared >= PLACEHOLDER_MIN_RECORDS].index) | SHOP_NUMBERS
    df.loc[df["Customer"].isin(placeholders), "Customer"] = None
    df["Bought Before"] = df["Bought Before"].fillna(False).astype(bool)
    return df


def gave_feedback(df: pd.DataFrame, responses: pd.DataFrame | None) -> pd.Series:
    """Per order: did its customer send feedback on or after the day they bought?"""
    if responses is None or responses.empty:
        return pd.Series(np.nan, index=df.index)
    first = (responses.dropna(subset=["Phone Key"])
             .groupby("Phone Key")["Submitted"].min().dt.normalize())
    fed_on = df["Customer"].map(first)
    return fed_on.notna() & (fed_on >= pd.to_datetime(df["Date"]))


def _customer_rates(df: pd.DataFrame, group: list[str]) -> pd.DataFrame:
    """Repeat and feedback rates over the customers in each group."""
    known = df.dropna(subset=["Customer"])
    per = (known.groupby(group + ["Customer"])
           .agg(repeat=("Bought Before", "any"), orders=("Order ID", "size"),
                fed=("Feedback", "max"))
           .reset_index())
    per["repeat"] = per["repeat"] | (per["orders"] > 1)
    out = per.groupby(group).agg(Customers=("Customer", "size"), Repeat=("repeat", "sum"),
                                 Fed=("fed", "sum"), FedKnown=("fed", "count"))
    out["Repeat %"] = (out["Repeat"] / out["Customers"] * 100).round(1)
    out["Feedback %"] = np.where(out["FedKnown"] > 0, out["Fed"] / out["Customers"] * 100,
                                 np.nan).round(1)
    out["Feedback"] = np.where(out["FedKnown"] > 0, out["Fed"], np.nan)
    return out[["Customers", "Repeat %", "Feedback", "Feedback %"]]


def _score(table: pd.DataFrame, measures: list[str]) -> pd.Series:
    ranks = [table[m].rank(pct=True) for m in measures if table[m].notna().any()]
    if not ranks:
        return pd.Series(np.nan, index=table.index)
    return (pd.concat(ranks, axis=1).mean(axis=1) * 100).round(0)


def shop_cards(df: pd.DataFrame, targets: dict[str, float]) -> pd.DataFrame:
    g = df.groupby("Location")
    staff = df[df["Served By"] != NOT_RECORDED]
    table = pd.DataFrame({
        "Revenue": g["Revenue"].sum(),
        "Corporate Revenue": g.apply(lambda f: f.loc[f["Corporate"], "Revenue"].sum(),
                                     include_groups=False),
        "Orders": g.size(),
        "Bags": g["Bags"].sum(),
        "Attendants": staff.groupby("Location")["Served By"].nunique(),
    })
    table["Attendants"] = table["Attendants"].fillna(0).astype(int)
    table["Target"] = pd.Series(targets).reindex(table.index)
    table["Target %"] = (table["Revenue"] / table["Target"] * 100).round(1)
    table["Basket Value"] = (table["Revenue"] / table["Orders"]).round(0)
    table["Basket Size"] = (table["Bags"] / table["Orders"]).round(2)
    table["Revenue per Attendant"] = (table["Revenue"]
                                      / table["Attendants"].where(table["Attendants"] > 0)).round(0)
    table = table.join(_customer_rates(df, ["Location"]))
    table["Score"] = _score(table, SHOP_SCORE)
    table = table.reset_index().rename(columns={"index": "Location"})
    return table.sort_values("Score", ascending=False)


def attendant_cards(df: pd.DataFrame) -> pd.DataFrame:
    """One row per attendant or BA (per shop they served at)."""
    staffed = df[df["Served By"] != NOT_RECORDED]
    team = staffed.groupby(["Location", "Date"])["Served By"].nunique().rename("Team")
    day_rev = df.groupby(["Location", "Date"])["Revenue"].sum().rename("Day Revenue")
    worked = (staffed[["Location", "Date", "Served By"]].drop_duplicates()
              .join(team, on=["Location", "Date"]).join(day_rev, on=["Location", "Date"]))
    worked["Share"] = worked["Day Revenue"] / worked["Team"]
    keys = ["Served By", "Location"]
    g = staffed.groupby(keys)
    table = pd.DataFrame({
        "Revenue": worked.groupby(keys)["Share"].sum(),
        "Days Worked": worked.groupby(keys)["Date"].nunique(),
        "Own Sales": g["Revenue"].sum(),
        "Orders": g.size(),
        "Bags": g["Bags"].sum(),
        "Corporate Revenue": g.apply(lambda f: f.loc[f["Corporate"], "Revenue"].sum(),
                                     include_groups=False),
    })
    table["Revenue"] = table["Revenue"].round(0)
    table["Revenue per Day"] = (table["Revenue"] / table["Days Worked"]).round(0)
    table["Basket Value"] = (table["Own Sales"] / table["Orders"]).round(0)
    table["Basket Size"] = (table["Bags"] / table["Orders"]).round(2)
    table = table.join(_customer_rates(staffed, keys))
    table["Score"] = _score(table, PERSON_SCORE)
    table = table.reset_index().rename(columns={"Served By": "Attendant / BA"})
    return table.sort_values("Score", ascending=False)
