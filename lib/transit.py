"""Goods-in-transit balance: a snapshot out of stock_quant, not a difference
of two date-ranged reports.

Reading transit as dispatched-minus-received over a window gave wildly
different answers depending on the window (Sinza 322 over a week, 267 over a
month, -843 over a year) against a true balance of 322 — because a window
only ever sees the dispatches and receipts that happen to fall inside it, not
the running balance those transactions actually left behind. "What is in
transit" is a question about now, so it is answered as a balance, straight
from Odoo, independent of any date range.
"""
from __future__ import annotations

import pandas as pd

# Destinations both distribution reports carry.
TRANSIT_COLUMNS = [
    "STARMALL", "MOMBASA", "NAKURU", "ELDORET", "KISUMU", "MERU", "THIKA",
    "HAZINA", "KITENGELA", "WEBSITE", "NANYUKI", "KAKAMEGA", "HILTON",
    "SINZA", "UGANDA", "KISII", "KTDA", "KTDA NEW", "BUSIA", "RONGAI",
]

# Transit nodes with no column in the distribution reports. They were left out
# when this was a difference of those two reports, since neither could source
# them — but they hold real stock (Marketing alone carries ~87 bags), and a
# balance that omitted it would not tie to Odoo.
EXTRA_TRANSIT_COLUMNS = ["MRKT", "CORPORATE", "COMPLIMENTARY", "CBD"]

BALANCE_COLUMNS = TRANSIT_COLUMNS + EXTRA_TRANSIT_COLUMNS

EXPORT_CHANNELS = ["SINZA", "UGANDA"]


def balance(long: pd.DataFrame) -> pd.DataFrame:
    """Pivot TRANSIT_BALANCE into the three-tier shape the view renders.

    Same output contract as in_transit() so the table, chart and exports below
    need no special case — only the numbers behind them change.
    """
    if long is None or long.empty:
        return pd.DataFrame(
            columns=["Product", *BALANCE_COLUMNS, "TOTAL", "Family", "sort_order"]
        )

    wide = (long.pivot_table(index="Product", columns="Destination",
                             values="Quantity", aggfunc="sum", fill_value=0.0)
            .reindex(columns=BALANCE_COLUMNS, fill_value=0.0)
            .astype("float64"))
    wide = wide.loc[(wide != 0).any(axis=1)]
    if wide.empty:
        return pd.DataFrame(
            columns=["Product", *BALANCE_COLUMNS, "TOTAL", "Family", "sort_order"]
        )
    return _tiers(wide.reset_index(), BALANCE_COLUMNS)


def unmapped_destinations(long: pd.DataFrame) -> list[str]:
    """Transit nodes this build has no column for — none expected, but a new
    node appearing in Odoo should be visible rather than silently dropped."""
    if long is None or long.empty:
        return []
    return sorted(set(long["Destination"]) - set(BALANCE_COLUMNS))


def _detail(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Bag-level rows only, indexed by product, numeric columns aligned."""
    if df is None or df.empty:
        return pd.DataFrame(columns=columns, dtype="float64")
    rows = df[df["sort_order"] == 0]
    present = [c for c in columns if c in rows.columns]
    out = rows.set_index("Product")[present].astype("float64")
    # A product can appear once per report; guard against duplicates anyway so
    # subtract() doesn't blow up on a non-unique index.
    return out.groupby(level=0).sum()


def in_transit(dispatch_df: pd.DataFrame, received_df: pd.DataFrame) -> pd.DataFrame:
    """Dispatched minus received, rebuilt into the usual three row tiers.

    A NEGATIVE cell is meaningful, not an error: the shop received more of that
    bag than was dispatched to it inside the window, which happens whenever an
    earlier dispatch lands during the range. Clipping it to zero would hide a
    real reconciliation signal, so it is left visible.
    """
    dispatched = _detail(dispatch_df, TRANSIT_COLUMNS)
    received = _detail(received_df, TRANSIT_COLUMNS)

    diff = dispatched.subtract(received, fill_value=0.0)
    diff = diff.reindex(columns=TRANSIT_COLUMNS).fillna(0.0)
    diff = diff.loc[(diff != 0).any(axis=1)]           # drop fully settled bags
    if diff.empty:
        return pd.DataFrame(
            columns=["Product", *TRANSIT_COLUMNS, "TOTAL", "Family", "sort_order"]
        )

    return _tiers(diff.reset_index().rename(columns={"index": "Product"}),
                  TRANSIT_COLUMNS)


def _tiers(detail: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Bag rows, family subtotals and a grand total, in render order."""
    detail = detail.copy()
    detail["TOTAL"] = detail[columns].sum(axis=1)
    detail["Family"] = detail["Product"].str.split(" ").str[0]
    detail["sort_order"] = 0

    value_cols = columns + ["TOTAL"]

    subtotals = detail.groupby("Family", as_index=False)[value_cols].sum()
    subtotals["Product"] = subtotals["Family"] + " TOTAL"
    subtotals["sort_order"] = 1

    grand = detail[value_cols].sum().to_frame().T
    grand["Product"] = "GRAND TOTAL"
    grand["Family"] = "~~~~"
    grand["sort_order"] = 2

    combined = pd.concat([detail, subtotals, grand], ignore_index=True)
    combined = combined.sort_values(
        ["Family", "sort_order", "Product"], kind="stable"
    ).reset_index(drop=True)
    return combined[["Product", *columns, "TOTAL", "Family", "sort_order"]]


def roll_to_bags(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Collapse colour variants into one row per bag.

    "Ace Croc Brown", "Ace Red" and "Ace Beige" become a single ACE line. The
    bag name comes from lib.taxonomy rather than the first word of the product,
    so "Man Bag Black" folds under MAN BAG instead of under MAN.
    """
    from lib import taxonomy

    if df is None or df.empty:
        return pd.DataFrame(columns=["Product", *columns, "TOTAL", "Family",
                                     "sort_order"])

    detail = df[df["sort_order"] == 0].copy()
    keep = [c for c in columns if c in detail.columns]
    if detail.empty or not keep:
        return pd.DataFrame(columns=["Product", *columns, "TOTAL", "Family",
                                     "sort_order"])

    detail["Bag"] = detail["Product"].map(
        lambda n: (taxonomy.family_of(n) or str(n).split()[0]).upper())

    rolled = detail.groupby("Bag", as_index=False)[keep].sum()
    rolled["TOTAL"] = rolled[keep].sum(axis=1)
    rolled = rolled.loc[rolled["TOTAL"] != 0].sort_values(
        "TOTAL", ascending=False, ignore_index=True)
    if rolled.empty:
        return pd.DataFrame(columns=["Product", *columns, "TOTAL", "Family",
                                     "sort_order"])

    rolled = rolled.rename(columns={"Bag": "Product"})
    rolled["Family"] = rolled["Product"]
    rolled["sort_order"] = 0

    value_columns = keep + ["TOTAL"]
    grand = rolled[value_columns].sum().to_frame().T
    grand["Product"], grand["Family"], grand["sort_order"] = (
        "GRAND TOTAL", "~~~~", 2)

    out = pd.concat([rolled, grand], ignore_index=True)
    return out[["Product", *keep, "TOTAL", "Family", "sort_order"]]


def export_channels_only(df: pd.DataFrame) -> pd.DataFrame:
    """Just the Sinza and Uganda columns, with their own totals recomputed.

    The report-wide TOTAL spans every destination, so it cannot be reused here —
    a row's Sinza/Uganda total has to be summed from those two columns alone.
    """
    if df.empty:
        return pd.DataFrame(columns=["Product", *EXPORT_CHANNELS, "TOTAL", "Family", "sort_order"])

    detail = df[df["sort_order"] == 0].copy()
    keep = [c for c in EXPORT_CHANNELS if c in detail.columns]
    detail = detail[["Product", "Family", *keep]]
    detail["TOTAL"] = detail[keep].sum(axis=1)
    detail = detail.loc[detail["TOTAL"] != 0]
    if detail.empty:
        return pd.DataFrame(columns=["Product", *EXPORT_CHANNELS, "TOTAL", "Family", "sort_order"])
    detail["sort_order"] = 0

    value_cols = keep + ["TOTAL"]
    grand = detail[value_cols].sum().to_frame().T
    grand["Product"] = "GRAND TOTAL"
    grand["Family"] = "~~~~"
    grand["sort_order"] = 2

    out = pd.concat([detail, grand], ignore_index=True)
    out = out.sort_values(["sort_order", "Product"], kind="stable").reset_index(drop=True)
    return out[["Product", *keep, "TOTAL", "Family", "sort_order"]]
