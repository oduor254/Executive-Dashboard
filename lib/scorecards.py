"""Shop and shop-attendant score cards.

Built from one row per order (queries.SCORECARD_ORDERS):

  Revenue            — the shop's revenue. For an attendant it is the shop's
                       revenue shared equally between everyone who served at
                       that shop that day: a shop's sales are a team effort,
                       and whoever keyed the order is not the only one who
                       made the sale. Orders nobody was recorded on are
                       shared too. Own Sales is what the person keyed.
  Corporate Revenue  — orders for customers recorded as Corporate, against a
                       corporate target of 10% of the revenue target (for an
                       attendant, 10% of their equal share of it).
  Basket Value       — revenue per order; Basket Size — bags per order.
  Repeat Purchase    — share of the period's unique customers who bought on
                       two or more different days within the period (two
                       orders on the same day are one visit).
  Retention          — of the unique customers who bought in the previous
                       period of the same length (1-7 Oct before 8-14 Oct),
                       the share who bought again in this one. For a shop,
                       they came back to that shop; for an attendant, the
                       customers they served came back to the same shop.
  Sales Training     — the daily questionnaire (lib/training.py): every one
                       due at the score it got, a missed one at 0, against a
                       target of 100%. A shop is its whole team list; an
                       attendant is matched to the list by name at their shop.
  Response Time      — shops only: the average first response to WhatsApp
                       chats in the WhatsApp Monitor, against 3 minutes
                       (3 or quicker scores 100, 6 minutes scores 50).
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

# Basket value is held to one benchmark everywhere, and so is feedback: 70%
# of the customers served sending a form scores 100.
BASKET_TARGET = 3200
FEEDBACK_TARGET = 70
# Corporate sales are expected to be this share of the revenue target.
CORPORATE_SHARE = 0.10
# WhatsApp: the average first response, in minutes, a shop should reply within.
RESPONSE_TARGET_MIN = 3

# Each measure is scored out of 100, and the cumulative score is their
# average. Revenue and basket value are scored against their targets (100 =
# target met, capped there); the rest have no target, so they are scored by
# rank against the other shops (or attendants): 100 is the best of them.
#   (score column, measure, how it is scored)
MEASURES = [
    ("Revenue Score", "Pace %", "target"),
    ("Corporate Score", "Corporate Pace %", "target"),
    ("Basket Value Score", "Basket Value %", "target"),
    ("Basket Size Score", "Basket Size", "rank"),
    ("Repeat Score", "Repeat %", "rank"),
    ("Retention Score", "Retention %", "rank"),
    ("Feedback Score", "Feedback of Target %", "target"),
    ("Training Score", "Training %", "target"),
    ("Response Score", "Response vs Target %", "target"),
]
SCORE_COLUMNS = [m[0] for m in MEASURES]


def placeholders(*frames: pd.DataFrame) -> set[str]:
    """Phone numbers that are not a customer: the shops' own, and any shared
    by many customer records."""
    rows = pd.concat([f[["Customer", "Partner"]] for f in frames], ignore_index=True)
    shared = rows.groupby("Customer")["Partner"].nunique()
    return set(shared[shared >= PLACEHOLDER_MIN_RECORDS].index) | SHOP_NUMBERS


def prepare(orders: pd.DataFrame, not_customers: set[str]) -> pd.DataFrame:
    df = orders[~orders["Location"].isin(NOT_SHOPS)].copy()
    df["Revenue"] = pd.to_numeric(df["Revenue"], errors="coerce").fillna(0)
    df["Bags"] = pd.to_numeric(df["Bags"], errors="coerce").fillna(0)
    df.loc[df["Customer"].isin(not_customers), "Customer"] = None
    return df


def retention(current: pd.DataFrame, previous: pd.DataFrame, group: list[str]) -> pd.DataFrame:
    """Unique customers in the previous period, per group, and how many of
    them bought again in this period at the same shop."""
    prev = previous.dropna(subset=["Customer"])[group + ["Customer"]].drop_duplicates()
    if prev.empty:
        return pd.DataFrame(columns=["Previous Customers", "Retained", "Retention %"])
    back = set(zip(current.dropna(subset=["Customer"])["Location"],
                   current.dropna(subset=["Customer"])["Customer"]))
    prev["Retained"] = [(loc, c) in back for loc, c in zip(prev["Location"], prev["Customer"])]
    out = prev.groupby(group).agg(**{"Previous Customers": ("Customer", "size"),
                                     "Retained": ("Retained", "sum")})
    out["Retention %"] = (out["Retained"] / out["Previous Customers"] * 100).round(1)
    return out


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
           .agg(days=("Date", "nunique"), fed=("Feedback", "max"))
           .reset_index())
    per["repeat"] = per["days"] >= 2
    out = per.groupby(group).agg(Customers=("Customer", "size"), Repeat=("repeat", "sum"),
                                 Fed=("fed", "sum"), FedKnown=("fed", "count"))
    out["Repeat %"] = (out["Repeat"] / out["Customers"] * 100).round(1)
    out["Feedback %"] = np.where(out["FedKnown"] > 0, out["Fed"] / out["Customers"] * 100,
                                 np.nan).round(1)
    out["Feedback"] = np.where(out["FedKnown"] > 0, out["Fed"], np.nan)
    return out[["Customers", "Repeat %", "Feedback", "Feedback %"]]


def _score(table: pd.DataFrame, expected: float) -> pd.DataFrame:
    """A score out of 100 for each measure, and the cumulative score.

    Revenue is judged against the share of the target due by now: eleven
    days into a 31-day month, 35% of the monthly target is on pace and
    scores 100.
    """
    out = table.copy()
    out["Pace %"] = (out["Target %"] / expected).round(1) if expected else np.nan
    out["Corporate Target"] = (out["Target"] * CORPORATE_SHARE).round(0)
    out["Corporate %"] = (out["Corporate Revenue"] / out["Corporate Target"] * 100).round(1)
    out["Corporate Pace %"] = ((out["Corporate %"] / expected).round(1) if expected
                               else np.nan)
    out["Feedback of Target %"] = (out["Feedback %"] / FEEDBACK_TARGET * 100).round(1)
    for column, measure, how in MEASURES:
        values = out[measure] if measure in out else pd.Series(np.nan, index=out.index)
        if how == "target":
            out[column] = values.clip(upper=100).round(0)
        else:
            out[column] = (values.rank(pct=True) * 100).round(0)
    out["Score"] = out[SCORE_COLUMNS].mean(axis=1).round(0)
    return out


def shop_cards(df: pd.DataFrame, previous: pd.DataFrame,
               targets: dict[str, float], expected: float = 1.0,
               training: pd.Series | None = None,
               response: pd.DataFrame | None = None) -> pd.DataFrame:
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
    table["Basket Value %"] = (table["Basket Value"] / BASKET_TARGET * 100).round(1)
    table["Basket Size"] = (table["Bags"] / table["Orders"]).round(2)
    table["Revenue per Attendant"] = (table["Revenue"]
                                      / table["Attendants"].where(table["Attendants"] > 0)).round(0)
    table = table.join(_customer_rates(df, ["Location"]))
    table = table.join(retention(df, previous, ["Location"]))
    table["Training %"] = (training.reindex(table.index).round(1) if training is not None
                           else np.nan)
    if response is not None and not response.empty:
        table = table.join(response)
        minutes = table["Response Time (min)"]
        table["Response vs Target %"] = np.where(
            minutes <= RESPONSE_TARGET_MIN, 100, RESPONSE_TARGET_MIN / minutes * 100).round(1)
        table.loc[minutes.isna(), "Response vs Target %"] = np.nan
    else:
        table["Response Time (min)"] = np.nan
        table["Chats"] = np.nan
    table = _score(table, expected)
    table = table.reset_index().rename(columns={"index": "Location"})
    return table.sort_values("Score", ascending=False)


def attendant_cards(df: pd.DataFrame, previous: pd.DataFrame,
                    targets: dict[str, float], expected: float = 1.0,
                    training: pd.Series | None = None) -> pd.DataFrame:
    """One row per attendant or BA (per shop they served at).

    Each person's revenue target is their shop's target for the period
    shared equally between the attendants and BAs who served there in it.
    """
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
    team_size = staffed.groupby("Location")["Served By"].nunique()
    shop = table.index.get_level_values("Location")
    table["Team Size"] = team_size.reindex(shop).to_numpy()
    table["Target"] = (pd.Series(targets).reindex(shop).to_numpy() / table["Team Size"]).round(0)
    table["Target %"] = (table["Revenue"] / table["Target"] * 100).round(1)
    table["Revenue per Day"] = (table["Revenue"] / table["Days Worked"]).round(0)
    table["Basket Value"] = (table["Own Sales"] / table["Orders"]).round(0)
    table["Basket Value %"] = (table["Basket Value"] / BASKET_TARGET * 100).round(1)
    table["Basket Size"] = (table["Bags"] / table["Orders"]).round(2)
    table = table.join(_customer_rates(staffed, keys))
    table = table.join(retention(df, previous[previous["Served By"] != NOT_RECORDED], keys))
    table["Training %"] = (training.reindex(table.index).round(1) if training is not None
                           else np.nan)
    table = _score(table, expected)
    table = table.reset_index().rename(columns={"Served By": "Attendant / BA"})
    return table.sort_values("Score", ascending=False)
