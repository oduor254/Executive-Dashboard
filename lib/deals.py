"""Classify each sale line as a Power Deal, Deal of the Week, Combo, or
Regular sale.

Both are static, monthly-curated promotions — lib/data/power_deals.csv and
lib/data/deals_of_week.csv need a manual update each month (new products,
new prices), sourced from the shared deals spreadsheet.

A sale counts under an offer if the product matches (and, for Deals of the
Week, the location and the sale's month match too) AND the price actually
charged is clearly below the offer's recorded original price (price_then) —
not just an exact match to the promotional price_now. Real-world price
adjustments (order top-ups, partial refunds, other combo interactions) mean
the amount charged doesn't always land exactly on price_now, but it's still
a deal sale as long as it's not the full original price. A sale at (or
above) price_then is a regular, full-price sale and is excluded. A line
priced at 0 is a product folded into a combo (its price lives on the
combo's own line), not sold standalone at all, so it's always excluded
regardless of product match.

A "Combo" is a bundle line — more than one bag sold together as one
listing, e.g. "Jumbo + Prime Combo" or "Antitheft Backpack + Man Bag or
Nizana Sling". Detected the same way the rest of the app already
recognizes bundles (see queries.py): the product name contains "+", the
word "or", or "Buy...Get". Checked independently of, and takes priority
over, the Power Deal / Deal of the Week price match — a bundle name never
equals a single deal product's name, but this keeps it that way even if
one ever coincidentally did.

For a combo row, Quantity is rewritten to the actual number of bags in the
bundle rather than the number of bundles sold: each "+"-separated segment
of the name is one bag, and an "or" inside a segment is a choice of which
ONE bag fills that slot, not an addition. "Safiri Travel + Standard Travel
or Antitheft Backpack" is 2 bags — Safiri Travel, plus whichever of
Standard/Antitheft was actually chosen — not 3.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import streamlit as st

_DATA_DIR = Path(__file__).parent / "data"

# Deals of the Week: these four Nairobi CBD shops share one set of deals.
NAIROBI_TOWN_SHOPS = {"Hazina", "Hilton", "Ktda", "Starmall"}
NON_KENYA_LOCATIONS = {"Uganda", "Sinza"}

_COMBO_BUY_GET = r"buy.*get"

# Original/full prices in the sheet match the POS almost exactly (clean,
# tight clusters right at price_then for every product checked), so a small
# tolerance is enough to recognize "this is a full-price sale, not a deal."
_FULL_PRICE_TOLERANCE = 1.0  # KES


@st.cache_data(show_spinner=False)
def _load_power_deals() -> pd.DataFrame:
    return pd.read_csv(_DATA_DIR / "power_deals.csv")


@st.cache_data(show_spinner=False)
def _load_deals_of_week() -> pd.DataFrame:
    return pd.read_csv(_DATA_DIR / "deals_of_week.csv")


def _is_discounted(price: float, original: float) -> bool:
    """True if price is a real, standalone sale priced below the original."""
    return 0 < price < (original - _FULL_PRICE_TOLERANCE)


def _is_combo(product: str) -> bool:
    return "+" in product or " or " in product or bool(re.search(_COMBO_BUY_GET, product))


def _combo_bag_count(product: str) -> int:
    """How many bags one bundle actually contains — see module docstring."""
    if "+" in product:
        return len([segment for segment in product.split("+") if segment.strip()])
    if re.search(_COMBO_BUY_GET, product):
        return 2  # "Buy X Get Y Free" without a "+" is still two bags
    return 1  # a plain "X or Y" choose-one bundle


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """Add an "Offer Type" column: "Power Deal", "Deal of the Week", "Combo",
    or "Regular".

    Expects one row per sold line with Date, Product, Location, Price
    (unit price) columns — matches lib.queries.PRODUCT_LINE_ITEMS.
    """
    df = df.copy()
    if df.empty:
        df["Offer Type"] = pd.Series(dtype="object")
        return df

    power = _load_power_deals()
    dow = _load_deals_of_week()

    product_key = df["Product"].str.strip().str.lower()
    month_key = pd.to_datetime(df["Date"]).dt.strftime("%B")
    is_kenya = ~df["Location"].isin(NON_KENYA_LOCATIONS)

    power_lookup = {
        p.lower(): then for p, then in zip(power["product"], power["price_then"])
    }

    def _power_match(product: str, price: float) -> bool:
        original = power_lookup.get(product)
        return original is not None and _is_discounted(price, original)

    dow_lookup: dict[tuple[str, str, str], float] = {
        (row["month"], row["product"].lower(), row["location"]): row["price_then"]
        for _, row in dow.iterrows()
    }

    def _dow_match(month: str, product: str, location: str, price: float) -> bool:
        candidates = [location]
        if location in NAIROBI_TOWN_SHOPS:
            candidates.append("Nairobi Town")
        for loc in candidates:
            original = dow_lookup.get((month, product, loc))
            if original is not None and _is_discounted(price, original):
                return True
        return False

    is_power = pd.Series(
        [_power_match(p, price) for p, price in zip(product_key, df["Price"])],
        index=df.index,
    ) & is_kenya

    is_dow = pd.Series(
        [
            _dow_match(m, p, loc, price)
            for m, p, loc, price in zip(month_key, product_key, df["Location"], df["Price"])
        ],
        index=df.index,
    )

    is_combo = df["Product"].str.strip().str.lower().apply(_is_combo)

    offer = pd.Series("Regular", index=df.index)
    offer[is_dow] = "Deal of the Week"
    offer[is_power] = "Power Deal"  # power deal wins if a row somehow matches both
    offer[is_combo] = "Combo"  # a bundle line is never a single-product deal
    df["Offer Type"] = offer

    df.loc[is_combo, "Quantity"] = df.loc[is_combo, "Quantity"] * df.loc[is_combo, "Product"].apply(_combo_bag_count)
    return df
