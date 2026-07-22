"""Classify each sale line as a Power Deal, Deal of the Week, or Regular sale.

Both are static, monthly-curated promotions — lib/data/power_deals.csv and
lib/data/deals_of_week.csv need a manual update each month (new products,
new prices). A sale only counts under an offer if its actual unit price
matches that offer's price exactly, within the given date's month for
Deals of the Week — a full-price sale of the same product during the same
window, or a leftover sale after the offer ends, is correctly excluded.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

_DATA_DIR = Path(__file__).parent / "data"

# Deals of the Week: these four Nairobi CBD shops share one set of deals.
NAIROBI_TOWN_SHOPS = {"Hazina", "Hilton", "Ktda", "Starmall"}
NON_KENYA_LOCATIONS = {"Uganda", "Sinza"}

_PRICE_TOLERANCE = 0.5  # KES, to absorb rounding


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
        target = power_lookup.get(product)
        return target is not None and abs(price - target) <= _PRICE_TOLERANCE

    dow_lookup: dict[tuple[str, str, str], float] = {
        (row["month"], row["product"].lower(), row["location"]): row["price_now"]
        for _, row in dow.iterrows()
    }

    def _dow_match(month: str, product: str, location: str, price: float) -> bool:
        candidates = [location]
        if location in NAIROBI_TOWN_SHOPS:
            candidates.append("Nairobi Town")
        for loc in candidates:
            target = dow_lookup.get((month, product, loc))
            if target is not None and abs(price - target) <= _PRICE_TOLERANCE:
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
