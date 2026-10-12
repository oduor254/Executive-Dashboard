"""Stock prediction & movement: what each shop has, what it will need, and
how ready the network is for this month's and next month's bag targets.

Demand is read from the last 90 days of sales (bags, net of refunds, bags
inside combos counted as that bag), as a moving average per shop and SKU:

    daily rate = bags sold in the last 90 days / 90

The 30-day rate is kept beside it to show whether a bag is speeding up or
slowing down.

Min and max levels are days of cover at the daily rate: min is what a shop
needs on hand to last until a dispatch reaches it (default 7 days), max is
the most worth holding (default 30 days). Below min the shop should be
restocked up to max; above max the stock is better moved elsewhere.

Targets set the volume, sales history sets the mix. Each shop's monthly bag
target (sales_pos_target.target_qty) is split across its bags in proportion
to what each sold over the 90 days, so a bag that is a fifth of a shop's
sales is expected to be a fifth of its target. Where a shop has no target,
the daily rate is used instead. Next month's target falls back to this
month's until it is set in Odoo.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from lib import taxonomy

WINDOW_DAYS = 90
SHOP_BUCKETS = ("Shop", "Transit")
# A shop has to sell a bag this often to judge it in or out of stock there:
# one or two sales in 90 days is a customer's one-off, not a line to keep.
ACTIVE_MIN_SOLD = 5

# Statuses, worst first.
OUT = "Out of Stock"
BELOW = "Below Min"
OK = "Within Range"
ABOVE = "Above Max"
SLOW = "Slow Seller"
IDLE = "No Sales in 90 Days"
STATUS_ORDER = [OUT, BELOW, OK, ABOVE, SLOW, IDLE]

TARGET_BASIS = "Targets"
CUSTOM_PERIOD = "Custom range"
PERIOD_COLUMNS = {"Last 90 days": "Sold 90d", "Last 30 days": "Sold 30d",
                  "Month to date": "Sold MTD", CUSTOM_PERIOD: "Sold"}
TREND_BASIS = "Sales trend"


@dataclass
class Calendar:
    today: date
    month_start: date
    month_end: date
    next_month: date
    days_left: int        # today included
    days_next: int

    @classmethod
    def for_today(cls, today: date | None = None) -> "Calendar":
        today = today or date.today()
        last = calendar.monthrange(today.year, today.month)[1]
        month_end = date(today.year, today.month, last)
        nxt = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
        return cls(today, today.replace(day=1), month_end, nxt,
                   (month_end - today).days + 1, calendar.monthrange(nxt.year, nxt.month)[1])


def family(sku: str) -> str:
    return taxonomy.group_of(sku)


def shop_sku(position: pd.DataFrame, demand: pd.DataFrame, shops: list[str]) -> pd.DataFrame:
    """One row per shop and SKU: stock on the shelf and on its way, and sales."""
    held = (position[position["Bucket"].isin(SHOP_BUCKETS)]
            .pivot_table(index=["Location", "Product ID", "SKU", "Category"], columns="Bucket",
                         values="Qty", aggfunc="sum", fill_value=0)
            .reindex(columns=list(SHOP_BUCKETS), fill_value=0)
            .rename(columns={"Shop": "In Shop", "Transit": "In Transit"})
            .reset_index())
    sold = demand[["Location", "Product ID", "SKU", "Category",
                   "Sold 90d", "Sold 30d", "Sold MTD", "Last Sold"]]
    df = held.merge(sold, on=["Location", "Product ID"], how="outer", suffixes=("", "_s"))
    for col in ("SKU", "Category"):
        df[col] = df[col].fillna(df[f"{col}_s"])
    df = df.drop(columns=["SKU_s", "Category_s"])
    df = df[df["Location"].isin(shops)].copy()
    for col in ("In Shop", "In Transit", "Sold 90d", "Sold 30d", "Sold MTD"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["In Shop"] = df["In Shop"].clip(lower=0)
    df["Last Sold"] = pd.to_datetime(df["Last Sold"], errors="coerce")
    df["Bag"] = df["SKU"].map(family)
    df["On Hand"] = df["In Shop"] + df["In Transit"]
    df["Daily Rate"] = df["Sold 90d"] / WINDOW_DAYS
    df["Rate 30d"] = df["Sold 30d"] / 30
    df["Trend %"] = np.where(df["Daily Rate"] > 0,
                             (df["Rate 30d"] / df["Daily Rate"] - 1) * 100, np.nan).round(0)
    return df


def by_bag(df: pd.DataFrame) -> pd.DataFrame:
    """The shop-and-SKU rows rolled up to shop and bag, colours combined."""
    sums = ["In Shop", "In Transit", "On Hand", "Sold 90d", "Sold 30d", "Sold MTD",
            "Daily Rate", "Rate 30d"]
    out = (df.groupby(["Location", "Bag"], as_index=False)
             .agg(**{c: (c, "sum") for c in sums}, Category=("Category", "first"),
                  **{"Last Sold": ("Last Sold", "max")}))
    out["SKU"] = out["Bag"]
    out["Trend %"] = np.where(out["Daily Rate"] > 0,
                              (out["Rate 30d"] / out["Daily Rate"] - 1) * 100, np.nan).round(0)
    return out


def min_max(df: pd.DataFrame, min_days: int, max_days: int) -> pd.DataFrame:
    """Min/max levels from the 90-day moving average, and where each SKU stands."""
    out = df.copy()
    out["Min Level"] = np.ceil(out["Daily Rate"] * min_days)
    out["Max Level"] = np.ceil(out["Daily Rate"] * max_days)
    out["Days of Cover"] = np.where(out["Daily Rate"] > 0,
                                    out["On Hand"] / out["Daily Rate"], np.nan).round(0)
    out["Status"] = np.select(
        [out["Daily Rate"] == 0,
         out["Sold 90d"] < ACTIVE_MIN_SOLD,
         out["On Hand"] <= 0,
         out["On Hand"] < out["Min Level"],
         out["On Hand"] > out["Max Level"]],
        [IDLE, SLOW, OUT, BELOW, ABOVE], default=OK)
    restock = out["Status"].isin([OUT, BELOW])
    out["Restock Qty"] = np.where(restock, out["Max Level"] - out["On Hand"], 0).clip(min=0)
    out["Excess Qty"] = np.where(out["Status"] == ABOVE, out["On Hand"] - out["Max Level"], 0)
    return out


def targets_by_shop(targets: pd.DataFrame, cal: Calendar) -> pd.DataFrame:
    """This month's and next month's bag target per shop; next month falls back
    to this month's where it has not been set yet."""
    t = targets.copy()
    t["Month"] = pd.to_datetime(t["Month"]).dt.date
    this = t[t["Month"] == cal.month_start].set_index("Location")["Target Bags"]
    nxt = t[t["Month"] == cal.next_month].set_index("Location")["Target Bags"]
    out = pd.DataFrame({"Target This Month": this, "Target Next Month": nxt})
    out["Next Target Set"] = out["Target Next Month"].notna()
    out["Target Next Month"] = out["Target Next Month"].fillna(out["Target This Month"])
    return out


def plan(df: pd.DataFrame, targets: pd.DataFrame, cal: Calendar,
         basis: str = TARGET_BASIS) -> pd.DataFrame:
    """Per shop and SKU: demand for the rest of the month and next month,
    the balance expected at month end, and next month's deficit.

    On the Targets basis, demand is the shop's remaining target (target less
    bags sold so far) split by each SKU's share of the shop's 90-day sales;
    a shop without a target, or the Sales trend basis, uses the daily rate
    times the days left.
    """
    out = df.copy()
    shop_sold = out.groupby("Location")["Sold 90d"].transform("sum")
    out["Mix Share"] = np.where(shop_sold > 0, out["Sold 90d"] / shop_sold, 0)
    shop_mtd = out.groupby("Location")["Sold MTD"].transform("sum")
    tgt = targets.reindex(out["Location"]).set_index(out.index)
    remaining = (tgt["Target This Month"] - shop_mtd).clip(lower=0)
    by_target = remaining * out["Mix Share"]
    by_rate = out["Daily Rate"] * cal.days_left
    use_target = tgt["Target This Month"].notna() & (basis == TARGET_BASIS)
    out["Need Rest of Month"] = np.where(use_target, by_target, by_rate)
    out["Expected Month-End"] = out["On Hand"] - out["Need Rest of Month"]
    next_by_target = tgt["Target Next Month"] * out["Mix Share"]
    out["Need Next Month"] = np.where(tgt["Target Next Month"].notna() & (basis == TARGET_BASIS),
                                      next_by_target, out["Daily Rate"] * cal.days_next)
    # What the shop must receive before next month: this month's shortfall
    # plus next month's need, less what it will still have at month end.
    out["Deficit Next Month"] = (out["Need Next Month"]
                                 - out["Expected Month-End"].clip(lower=0)).clip(lower=0)
    out["Short This Month"] = (-out["Expected Month-End"]).clip(lower=0)
    for col in ("Need Rest of Month", "Expected Month-End", "Need Next Month",
                "Deficit Next Month", "Short This Month"):
        out[col] = out[col].round(0)
    return out


def preparedness(planned: pd.DataFrame, targets: pd.DataFrame, cal: Calendar) -> pd.DataFrame:
    """Per shop: how much of the target still to sell this month its stock
    covers, and how much of next month's target it will start the month with."""
    g = planned.groupby("Location")
    shop = pd.DataFrame({
        "Sold MTD": g["Sold MTD"].sum(),
        "On Hand": g["On Hand"].sum(),
        "Expected Month-End": g["Expected Month-End"].apply(lambda v: v.clip(lower=0).sum()),
        "Short This Month": g["Short This Month"].sum(),
        "Deficit Next Month": g["Deficit Next Month"].sum(),
    }).join(targets, how="left")
    shop["Target Left"] = (shop["Target This Month"] - shop["Sold MTD"]).clip(lower=0)
    shop["Ready This Month %"] = np.where(
        shop["Target Left"] > 0,
        (shop["On Hand"] / shop["Target Left"] * 100).clip(upper=999), np.nan).round(0)
    shop["Ready Next Month %"] = np.where(
        shop["Target Next Month"] > 0,
        (shop["Expected Month-End"] / shop["Target Next Month"] * 100).clip(upper=999),
        np.nan).round(0)
    return shop.reset_index().rename(columns={"index": "Location"})


def network_report(planned: pd.DataFrame, position: pd.DataFrame, by: str = "SKU") -> pd.DataFrame:
    """What the network has, what it needs, and what is missing — one row per
    SKU (or per bag, colours combined).

    To Make is what next month's shop deficits and this month's shortfalls
    still need once the finished stock in the warehouses and the bags being
    made up are counted.
    """
    pos = position.copy()
    pos["Bag"] = pos["SKU"].map(family)
    stores = (pos[pos["Bucket"].isin(["Warehouse", "Production"])]
              .pivot_table(index=by, columns="Bucket", values="Qty", aggfunc="sum", fill_value=0)
              .reindex(columns=["Warehouse", "Production"], fill_value=0)
              .rename(columns={"Warehouse": "In Warehouse", "Production": "In Production"}))
    g = planned.groupby(by)
    shops = pd.DataFrame({
        "Category": g["Category"].first(),
        "Sold 90d": g["Sold 90d"].sum(),
        "Daily Rate": g["Daily Rate"].sum(),
        "In Shops": g["In Shop"].sum(),
        "In Transit": g["In Transit"].sum(),
        "Shops Stocking": g["In Shop"].apply(lambda v: int((v > 0).sum())),
        "Shops Out": g.apply(lambda f: int(((f["On Hand"] <= 0) & (f["Daily Rate"] > 0)).sum()),
                             include_groups=False),
        "Need Rest of Month": g["Need Rest of Month"].sum(),
        "Short This Month": g["Short This Month"].sum(),
        "Need Next Month": g["Need Next Month"].sum(),
        "Deficit Next Month": g["Deficit Next Month"].sum(),
    })
    report = shops.join(stores, how="outer").fillna({
        "In Warehouse": 0, "In Production": 0, "Sold 90d": 0, "Daily Rate": 0,
        "In Shops": 0, "In Transit": 0, "Shops Stocking": 0, "Shops Out": 0,
        "Need Rest of Month": 0, "Short This Month": 0, "Need Next Month": 0,
        "Deficit Next Month": 0})
    if by == "SKU":
        cats = pos.groupby("SKU")["Category"].first()
        report["Category"] = report["Category"].fillna(cats.reindex(report.index))
    else:
        report["Category"] = report["Category"].fillna("")
    required = report["Short This Month"] + report["Deficit Next Month"]
    report["From Warehouse"] = np.minimum(required, report["In Warehouse"])
    after_wh = required - report["From Warehouse"]
    report["From Production"] = np.minimum(after_wh, report["In Production"])
    report["To Make"] = (after_wh - report["From Production"]).round(0)
    report["Status"] = np.select(
        [(report["Daily Rate"] > 0) & (report["In Shops"] + report["In Transit"] <= 0),
         report["To Make"] > 0,
         required > 0,
         report["Daily Rate"] == 0],
        ["Missing at Shops", "Short — Make More", "Covered by Stores", "Not Selling"],
        default="Enough at Shops")
    report["Daily Rate"] = report["Daily Rate"].round(1)
    return report.reset_index().rename(columns={"index": by})


def top_sellers(demand: pd.DataFrame, period: str, by: str) -> pd.DataFrame:
    """Share of bags sold, largest first, with the running share."""
    col = PERIOD_COLUMNS.get(period, "Sold")
    d = demand.assign(Bag=demand["SKU"].map(family))
    ranked = d.groupby(by, as_index=False)[col].sum().rename(columns={col: "Bags Sold"})
    ranked = ranked[ranked["Bags Sold"] > 0].sort_values("Bags Sold", ascending=False)
    total = ranked["Bags Sold"].sum()
    ranked["Share %"] = (ranked["Bags Sold"] / total * 100).round(2) if total else 0
    ranked["Cumulative %"] = ranked["Share %"].cumsum().round(1)
    ranked.insert(0, "Rank", range(1, len(ranked) + 1))
    return ranked.reset_index(drop=True)
