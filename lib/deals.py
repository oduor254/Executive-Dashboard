"""Classify each sale line as a Power Deal, Deal of the Week, or Regular sale.

Both are static, monthly-curated promotions — lib/data/power_deals.csv and
lib/data/deals_of_week.csv need a manual update each month (new products,
new prices), sourced from the shared deals spreadsheet. A sale only counts
under an offer if its actual unit price matches that offer's price exactly,
within the given date's month for Deals of the Week — a full-price sale of
the same product during the same window, or a leftover sale after the offer
ends, is correctly excluded. A line priced at 0 is a product folded into a
combo (its price lives on the combo's own line), not a standalone offer
sale, so it's always excluded regardless of product match.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

_DATA_DIR = Path(__file__).parent / "data"

# Deals of the Week: these four Nairobi CBD shops share one set of deals.
NAIROBI_TOWN_SHOPS = {"Hazina", "Hilton", "Ktda", "Starmall"}
NON_KENYA_LOCATIONS = {"Uganda", "Sinza"}

# Deal of the Week prices in the sheet match the POS almost exactly (~99% of
# sales land within 0.01 KES), so a tight tolerance is correct there. Power
# Deal products are consistently charged about 1 KES below the sheet's round
# number (e.g. sheet says 1200, POS charges 1199 — charm pricing), so they
# need a wider tolerance or nearly every Power Deal sale is missed.
_DOW_PRICE_TOLERANCE = 0.5  # KES
_POWER_PRICE_TOLERANCE = 1.5  # KES


@st.cache_data(show_spinner=False)
def _load_power_deals() -> pd.DataFrame:
    return pd.read_csv(_DATA_DIR / "power_deals.csv")


@st.cache_data(show_spinner=False)
def _load_deals_of_week() -> pd.DataFrame:
    return pd.read_csv(_DATA_DIR / "deals_of_week.csv")


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """Add an "Offer Type" column: "Power Deal", "Deal of the Week", or "Regular".

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
        p.lower(): now for p, now in zip(power["product"], power["price_now"])
    }

    def _power_match(product: str, price: float) -> bool:
        if price <= 0:
            # Sold as part of a combo (price rolled into another line), not
            # standalone at the offer price — never counts as an offer sale.
            return False
        target = power_lookup.get(product)
        return target is not None and abs(price - target) <= _POWER_PRICE_TOLERANCE

    dow_lookup: dict[tuple[str, str, str], float] = {
        (row["month"], row["product"].lower(), row["location"]): row["price_now"]
        for _, row in dow.iterrows()
    }

    def _dow_match(month: str, product: str, location: str, price: float) -> bool:
        if price <= 0:
            # Sold as part of a combo (price rolled into another line), not
            # standalone at the offer price — never counts as an offer sale.
            return False
        candidates = [location]
        if location in NAIROBI_TOWN_SHOPS:
            candidates.append("Nairobi Town")
        for loc in candidates:
            target = dow_lookup.get((month, product, loc))
            if target is not None and abs(price - target) <= _DOW_PRICE_TOLERANCE:
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

    offer = pd.Series("Regular", index=df.index)
    offer[is_dow] = "Deal of the Week"
    offer[is_power] = "Power Deal"  # power deal wins if a row somehow matches both
    df["Offer Type"] = offer
    return df
