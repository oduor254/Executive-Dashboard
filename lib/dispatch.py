"""Dispatch: stock health per shop, and how stock moved through each shop.

Stock monitor — min / max per shop. Uses lib.stock_planning: a 90-day moving
average of bags sold per shop and SKU sets a minimum (days of cover until a
dispatch arrives) and a maximum (the most worth holding). Each selling line
is Out of Stock, Below Min, Within Range or Above Max; a shop's stock health
is the share of its selling lines within range.

Shop requests — for a period, per shop and bag:

    opening stock (end-of-day snapshot the day before the period)
  + received from dispatch (out of the shop's own goods-in-transit location),
    or, for Website and Ktda which take their stock straight from CBD/Stock,
    received from CBD
  + transfers in that skipped dispatch (straight from CBD, the warehouse or
    another shop)
  + customer returns + inventory adjustments in
  − sold − adjustments out − transfers out
  = expected closing, against the closing snapshot → any mismatch

All from Odoo's stock moves, so opening and closing should tally; a line
that doesn't is stock that moved without a record. Beside it: what was
dispatched in the period and is still in transit, what arrived without a
shop request (dispatches raised by CBD, corporate, marketing, prepayments or
redistribution, and transfers straight into the shop), and how each shop's
requests were met — requested, dispatched, received.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from lib import staff_numbers, stock_planning as sp, taxonomy

IN_KINDS = ["Received from Dispatch", "Received from CBD", "Transfers In (outside dispatch)",
            "Customer Returns", "Adjustments In"]
# Shops that take their stock straight from CBD/Stock instead of through
# dispatch — Website picks its orders there, and Ktda is restocked from it —
# so a move from CBD into them is their supply, not stock outside dispatch.
CBD_SUPPLIED = {"Website", "Ktda"}
CBD_PREFIX = "CBD/"
OUT_KINDS = ["Sold", "Adjustments Out", "Transfers Out"]
HEALTH_STATUSES = [sp.OUT, sp.BELOW, sp.OK, sp.ABOVE]
SOURCE_NAMES = {"order": "Order", "prepayment": "Prepayment", "redistribution": "Redistribution"}
REQUEST_NAMES = {"shop": "Shop request", "cbd": "CBD", "corporate": "Corporate",
                 "marketing": "Marketing", "complimentary": "Complimentary"}


def shop_names(shops: pd.DataFrame) -> dict[int, str]:
    return {int(i): staff_numbers.shop_name(n) for i, n in zip(shops["Shop ID"], shops["Shop"])}


def classify(moves: pd.DataFrame, shops: pd.DataFrame) -> pd.DataFrame:
    """The moves with CBD's supply to the CBD-supplied shops (Website, Ktda)
    called what it is: Received from CBD, not a transfer outside dispatch."""
    names = shop_names(shops)
    m = moves.copy()
    cbd = (m["Kind"] == "Transfers In (outside dispatch)") & m["From"].fillna("").str.startswith(CBD_PREFIX)         & m["Shop ID"].map(names).isin(CBD_SUPPLIED)
    m.loc[cbd, "Kind"] = "Received from CBD"
    return m


# ---------------------------------------------------------- stock health ---

def health(levels: pd.DataFrame) -> pd.DataFrame:
    """Per shop: selling lines judged, how many are out, below min, within
    range and over max, and the health score (within range ÷ judged)."""
    judged = levels[levels["Status"].isin(HEALTH_STATUSES)]
    t = (judged.pivot_table(index="Location", columns="Status", values="Daily Rate",
                            aggfunc="count", fill_value=0)
         .reindex(columns=HEALTH_STATUSES, fill_value=0))
    t["Lines Judged"] = t.sum(axis=1)
    for status in HEALTH_STATUSES:
        t[f"{status} %"] = (t[status] / t["Lines Judged"] * 100).round(1)
    t["Stock Health %"] = t[f"{sp.OK} %"]
    restock = levels.groupby("Location")["Restock Qty"].sum()
    excess = levels.groupby("Location")["Excess Qty"].sum()
    t["Restock Qty"] = restock.reindex(t.index).fillna(0)
    t["Excess Qty"] = excess.reindex(t.index).fillna(0)
    return (t.reset_index().rename(columns={"Location": "Shop"})
            .sort_values("Stock Health %", ascending=False))


# --------------------------------------------------------- stock movement ---

def movement(shops: pd.DataFrame, opening: pd.DataFrame, closing: pd.DataFrame,
             moves: pd.DataFrame, transits: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per shop, per shop and SKU): opening, every kind of move, expected
    and actual closing, the mismatch, and what was dispatched / is in transit."""
    names = shop_names(shops)
    keys = ["Shop ID", "Product ID"]
    # Retail shops only: the snapshots also carry CBD's own stock, whose
    # moves aren't counted here.
    opening, closing, moves = (f[f["Shop ID"].isin(names)] for f in (opening, closing, classify(moves, shops)))
    frames = [opening[keys + ["SKU"]], closing[keys + ["SKU"]], moves[keys + ["SKU"]]]
    transits = transits[transits["Shop ID"].isin(names)] if not transits.empty else transits
    if not transits.empty:
        frames.append(transits[keys + ["SKU"]])
    t = pd.concat(frames).drop_duplicates(keys).set_index(keys)
    t["Opening"] = opening.groupby(keys)["Qty"].sum()
    kinds = moves.pivot_table(index=keys, columns="Kind", values="Qty", aggfunc="sum", fill_value=0)
    for k in IN_KINDS + OUT_KINDS:
        t[k] = kinds[k] if k in kinds else 0
    if not transits.empty:
        tg = transits.groupby(keys)
        t["Dispatched"] = tg["Dispatched"].sum()
        t["Still in Transit"] = tg["In Transit"].sum()
    else:
        t["Dispatched"] = t["Still in Transit"] = 0
    t["Closing"] = closing.groupby(keys)["Qty"].sum()
    t = t.fillna(0)
    t["Net Sold"] = t["Sold"] - t["Customer Returns"]
    t["Expected Closing"] = t["Opening"] + t[IN_KINDS].sum(axis=1) - t[OUT_KINDS].sum(axis=1)
    t["Mismatch"] = t["Closing"] - t["Expected Closing"]
    t = t[t[["Opening", "Closing", "Dispatched"] + IN_KINDS + OUT_KINDS].abs().sum(axis=1) > 0]
    detail = t.reset_index()
    detail.insert(0, "Shop", detail["Shop ID"].map(names))
    detail["Bag"] = detail["SKU"].map(taxonomy.group_of)
    cols = (["Opening", "Dispatched", "Received from Dispatch", "Still in Transit", "Received from CBD",
             "Transfers In (outside dispatch)", "Customer Returns", "Adjustments In", "Sold",
             "Net Sold", "Adjustments Out", "Transfers Out", "Expected Closing", "Closing", "Mismatch"])
    per_shop = detail.groupby("Shop", as_index=False)[cols].sum()
    per_shop["Lines Off"] = detail[detail["Mismatch"].abs() > 0.001].groupby("Shop").size().reindex(
        per_shop["Shop"]).fillna(0).astype(int).to_numpy()
    per_shop["Sell-through %"] = (per_shop["Net Sold"] / (per_shop["Opening"] + per_shop["Received from Dispatch"]
                                  + per_shop["Received from CBD"] + per_shop["Transfers In (outside dispatch)"]
                                  ).where(lambda v: v > 0) * 100).round(1)
    return per_shop.sort_values("Shop"), detail[["Shop", "Bag", "SKU"] + cols]


# ----------------------------------------------- stock outside requests ---

def outside_requests(shops: pd.DataFrame, transits: pd.DataFrame, moves: pd.DataFrame
                     ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(dispatches not raised by the shop, stock that arrived without a
    dispatch at all)."""
    names = shop_names(shops)
    transits = transits[transits["Shop ID"].isin(names)] if not transits.empty else transits
    if transits.empty:
        sent = transits
    else:
        not_shop = (transits["Source"] != "order") | (transits["Request Type"].fillna("") != "shop")
        sent = transits[not_shop].copy()
        sent["Raised As"] = [REQUEST_NAMES.get(r, r) if s == "order" else SOURCE_NAMES.get(s, s)
                             for s, r in zip(sent["Source"], sent["Request Type"].fillna(""))]
        sent.insert(0, "Shop", sent["Shop ID"].map(names))
        sent = (sent.groupby(["Shop", "Raised As", "Transit", "Order", "Dispatched On", "State"], dropna=False,
                             as_index=False)
                .agg(Bags=("Dispatched", "sum"), Received=("Received", "sum"), SKUs=("SKU", "nunique"))
                .sort_values(["Dispatched On", "Shop"], ascending=[False, True]))
    direct = classify(moves, shops)
    direct = direct[direct["Kind"] == "Transfers In (outside dispatch)"].copy()
    direct.insert(0, "Shop", direct["Shop ID"].map(names))
    direct = (direct.groupby(["Shop", "From"], as_index=False)
              .agg(Bags=("Qty", "sum"), Moves=("Moves", "sum"), SKUs=("SKU", "nunique"))
              .sort_values("Bags", ascending=False))
    return sent, direct


# --------------------------------------------------------- bags dispatched ---

def dispatched_bags(shops: pd.DataFrame, transits: pd.DataFrame
                    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(per bag, bag × shop, per shop / bag / SKU): the bags that left
    dispatch for the shops in the period, by dispatch date — how many went,
    how many the shops have taken in and how many are still on the road."""
    names = shop_names(shops)
    if transits.empty:
        return transits, transits, transits
    t = transits[transits["Shop ID"].isin(names)].copy()
    t["Shop"] = t["Shop ID"].map(names)
    t["Bag"] = t["SKU"].map(taxonomy.group_of)
    t["Raised As"] = [REQUEST_NAMES.get(r, r) if s == "order" else SOURCE_NAMES.get(s, s)
                      for s, r in zip(t["Source"], t["Request Type"].fillna(""))]
    sums = dict(Dispatched=("Dispatched", "sum"), Received=("Received", "sum"),
                **{"In Transit": ("In Transit", "sum")})

    per_bag = t.groupby("Bag", as_index=False).agg(
        **sums, Shops=("Shop", "nunique"), Dispatches=("Transit", "nunique"), SKUs=("SKU", "nunique"))
    per_bag["Share %"] = (per_bag["Dispatched"] / per_bag["Dispatched"].sum() * 100).round(1)
    per_bag = per_bag.sort_values("Dispatched", ascending=False)

    matrix = t.pivot_table(index="Bag", columns="Shop", values="Dispatched", aggfunc="sum", fill_value=0)
    matrix = matrix[matrix.sum().sort_values(ascending=False).index]
    matrix.insert(0, "Total", matrix.sum(axis=1))
    matrix = matrix.sort_values("Total", ascending=False).reset_index()

    per_sku = (t.groupby(["Shop", "Bag", "SKU"], as_index=False)
               .agg(**sums, Dispatches=("Transit", "nunique"),
                    **{"Raised As": ("Raised As", lambda v: ", ".join(sorted(set(v)))),
                       "First Sent": ("Dispatched On", "min"), "Last Sent": ("Dispatched On", "max")})
               .sort_values(["Shop", "Dispatched"], ascending=[True, False]))
    return per_bag, matrix, per_sku


# ------------------------------------------------------ request fulfilment ---

OPEN_STATES = {"submitted", "approved"}
CANCELLED = "cancel"


def fulfilment(shops: pd.DataFrame, requests: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per shop, per shop and bag): how the shop's own requests were met.

    A request still submitted or approved hasn't reached dispatch yet, so it
    is counted as open, not against dispatch; a cancelled one is shown apart.
    For the rest (dispatched, received or closed): Fill Rate = bags
    dispatched ÷ bags requested, Received % = bags received ÷ requested, and
    Closed Unfilled = what was asked for but never sent."""
    names = shop_names(shops)
    if requests.empty:
        return requests, requests
    r = requests.assign(Shop=requests["Shop ID"].map(names), Bag=requests["SKU"].map(taxonomy.group_of))
    r = r[r["Shop"].notna() & (r["Requested"] > 0)].copy()
    state = r["State"].fillna("")
    r["Group"] = np.where(state.isin(OPEN_STATES), "Open", np.where(state == CANCELLED, "Cancelled", "Closed"))
    closed = r["Group"] == "Closed"
    for col in ("Requested", "Dispatched", "Received"):
        r[f"{col} (closed)"] = r[col].where(closed, 0)
    r["Open Bags"] = r["Requested"].where(r["Group"] == "Open", 0)
    r["Cancelled Bags"] = r["Requested"].where(r["Group"] == "Cancelled", 0)

    def summarise(by: list[str]) -> pd.DataFrame:
        g = r.groupby(by, as_index=False).agg(
            Requests=("Order", "nunique"),
            Requested=("Requested (closed)", "sum"), Dispatched=("Dispatched (closed)", "sum"),
            Received=("Received (closed)", "sum"),
            **{"Open Bags": ("Open Bags", "sum"), "Cancelled Bags": ("Cancelled Bags", "sum")})
        g["Fill Rate %"] = (g["Dispatched"] / g["Requested"].where(g["Requested"] > 0) * 100).round(1)
        g["Received %"] = (g["Received"] / g["Requested"].where(g["Requested"] > 0) * 100).round(1)
        g["Closed Unfilled"] = (g["Requested"] - g["Dispatched"]).clip(lower=0)
        return g

    per_shop = summarise(["Shop"]).sort_values("Fill Rate %", ascending=False)
    per_bag = summarise(["Shop", "Bag"]).sort_values(["Shop", "Closed Unfilled"], ascending=[True, False])
    return per_shop, per_bag
