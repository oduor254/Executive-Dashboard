"""Classify each sale line as a Power Deal, Deal of the Week, Singles,
Special Offers, Combo, or Regular sale.

Both are monthly-curated promotions — lib/data/power_deals.csv and
lib/data/deals_of_week.csv need a manual update each month (new products,
new prices), sourced from the shared deals spreadsheet's Kenya, Uganda, and
Tanzania tabs. Power Deals are Kenya-only, and — like Deal of the Week —
month-specific: the sheet re-lists Power Deals every month (sometimes the
same products at the same price, sometimes not), so a product only counts
as a Power Deal in the months it's actually listed for, not forever once
seen. Uganda/Tanzania have no separate Power Deal list at all — every one
of their rows is itself month-specific, so it's shaped like Deal of the
Week even though it isn't labeled that. deals_of_week.csv carries its
own "type" per row so the output label matches each country's own naming
rather than being forced into "Deal of the Week": Kenya rows are "Deal of
the Week"; Uganda rows (its sheet has one undifferentiated list) and
Tanzania's "Singles" section are "Singles"; Tanzania's "Special Offers"
section is "Special Offers". Uganda/Tanzania prices are already converted
to KES-equivalent — Uganda ÷29, Tanzania ÷25 — matching the same
conversion PRODUCT_LINE_ITEMS applies to the actual sale price, so the
comparison in _is_discounted stays apples to apples regardless of country.

A sale counts under an offer if the product matches, the sale's month
matches (and, for Deals of the Week, the location too), AND the price actually
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

# When each list started being kept, as (year, month). Before its start date a
# list has no records because the tracking did not exist yet — zero deals is
# the fact of the matter, not a gap, so periods_without_definitions stays quiet
# rather than crying wolf on every historical range.
#
# The two started at different times, so this is per list rather than one
# programme-wide date: Kenya's Power Deal and Deal of the Week sections began
# in July 2026, while Sinza's Singles and Special Offers were already being
# kept from January — its Jan-Jun sections hold a genuinely different product
# list each month, not one list repeated.
#
# Combos are deliberately absent here. They are recognised from the product
# name itself (see _is_combo), never from these files, so they classify for
# every period on record and can never be missing a definition.
_POWER_DEALS_START = (2026, 7)
_DEALS_OF_WEEK_START = (2026, 1)

# What year to assume for a CSV written before the year column existed — see
# _with_year. Tracking began in 2026, so that is the only year such a file
# can hold.
_LEGACY_YEAR = 2026


def _with_year(frame: pd.DataFrame) -> pd.DataFrame:
    """Backfill "year" on a file written before that column existed.

    These CSVs are rewritten in place by deals_sync.sync(), so the copy on a
    running deployment is not necessarily the copy in git — a sync run before
    the year column was added leaves an old-format file sitting next to new
    code, and reading it blew the Offer Types tab up with a bare KeyError.
    The schema this code needs can't be assumed of a file the app itself
    writes, so a missing column is repaired rather than fatal.

    2026 is the right fill: a file with no year column can only have been
    written by the version that predates it, and that version only ever ran
    against the 2026 sheet.
    """
    if "year" in frame.columns:
        return frame
    return frame.assign(year=_LEGACY_YEAR)


@st.cache_data(show_spinner=False)
def _load_power_deals() -> pd.DataFrame:
    return _with_year(pd.read_csv(_DATA_DIR / "power_deals.csv"))


@st.cache_data(show_spinner=False)
def _load_deals_of_week() -> pd.DataFrame:
    return _with_year(pd.read_csv(_DATA_DIR / "deals_of_week.csv"))


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


def periods_without_definitions(start_date, end_date) -> list[str]:
    """Months in [start_date, end_date] missing an offer list, as readable
    strings: "March 2026 — no Power Deal list recorded".

    Without this, a month the sheet never covered reports zero Power Deals and
    zero Deals of the Week — which reads as "we ran no promotions that month"
    when it actually means "we have no record of what was on promotion". A
    zero that looks like a fact is worse than an obvious gap, so the page says
    which months it is blind to rather than quietly showing them as nothing.

    Each list is only checked from its own start date (see _POWER_DEALS_START
    / _DEALS_OF_WEEK_START), and checked separately rather than across both:
    they are curated apart, started at different times, and a month can easily
    have Sinza's Singles recorded while Kenya's Power Deal section for the
    same month was never captured. Treating "some list exists" as coverage
    would hide exactly that.
    """
    def recorded(frame: pd.DataFrame) -> set[tuple[int, str]]:
        return {(int(r["year"]), r["month"]) for _, r in frame.iterrows()}

    has_power = recorded(_load_power_deals())
    has_dow = recorded(_load_deals_of_week())

    out: list[str] = []
    for p in pd.period_range(pd.Timestamp(start_date), pd.Timestamp(end_date), freq="M"):
        period = (p.year, p.strftime("%B"))
        label = f"{p.strftime('%B')} {p.year}"
        tracked = (p.year, p.month)

        missing_power = tracked >= _POWER_DEALS_START and period not in has_power
        missing_dow = tracked >= _DEALS_OF_WEEK_START and period not in has_dow

        if missing_power and missing_dow:
            out.append(f"{label} — no offer lists recorded")
        elif missing_power:
            out.append(f"{label} — no Power Deal list recorded")
        elif missing_dow:
            out.append(f"{label} — no Deal of the Week list recorded")
    return out


def country_of(location: str) -> str:
    # Uganda and Sinza are each their own single-shop country label; every
    # other location rolls up into "Kenya". "Sinza" (not "Tanzania") for
    # uniformity with how Goods in Transit already labels this channel.
    return location if location in NON_KENYA_LOCATIONS else "Kenya"


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """Add "Offer Type" ("Power Deal", "Deal of the Week", "Singles",
    "Special Offers", "Combo", or "Regular") and "Country" ("Kenya",
    "Uganda", or "Sinza") columns.

    Expects one row per sold line with Date, Product, Location, Price
    (unit price) columns — matches lib.queries.PRODUCT_LINE_ITEMS.
    """
    df = df.copy()
    if df.empty:
        df["Offer Type"] = pd.Series(dtype="object")
        df["Country"] = pd.Series(dtype="object")
        return df

    power = _load_power_deals()
    dow = _load_deals_of_week()

    product_key = df["Product"].str.strip().str.lower()
    sold_on = pd.to_datetime(df["Date"])
    month_key = sold_on.dt.strftime("%B")
    # Matching on month name alone scored every past year against the current
    # year's offer list — August 2024's sales came back with 3,068 "Power
    # Deals" taken from the August 2026 sheet, for promotions that never ran
    # that year. The period is (year, month), never the month by itself.
    year_key = sold_on.dt.year
    is_kenya = ~df["Location"].isin(NON_KENYA_LOCATIONS)

    power_lookup: dict[tuple[int, str, str], float] = {
        (int(row["year"]), row["month"], row["product"].lower()): row["price_then"]
        for _, row in power.iterrows()
    }

    def _power_match(year: int, month: str, product: str, price: float) -> bool:
        original = power_lookup.get((year, month, product))
        return original is not None and _is_discounted(price, original)

    dow_lookup: dict[tuple[int, str, str, str], tuple[float, str]] = {
        (int(row["year"]), row["month"], row["product"].lower(), row["location"]):
            (row["price_then"], row["type"])
        for _, row in dow.iterrows()
    }

    def _dow_match(year: int, month: str, product: str, location: str, price: float) -> str | None:
        candidates = [location]
        if location in NAIROBI_TOWN_SHOPS:
            candidates.append("Nairobi Town")
        for loc in candidates:
            entry = dow_lookup.get((year, month, product, loc))
            if entry is not None and _is_discounted(price, entry[0]):
                return entry[1]  # the row's own type: Deal of the Week / Singles / Special Offers
        return None

    is_power = pd.Series(
        [
            _power_match(y, m, p, price)
            for y, m, p, price in zip(year_key, month_key, product_key, df["Price"])
        ],
        index=df.index,
    ) & is_kenya

    dow_type = pd.Series(
        [
            _dow_match(y, m, p, loc, price)
            for y, m, p, loc, price in zip(
                year_key, month_key, product_key, df["Location"], df["Price"])
        ],
        index=df.index,
    )
    is_dow = dow_type.notna()

    is_combo = df["Product"].str.strip().str.lower().apply(_is_combo)

    offer = pd.Series("Regular", index=df.index)
    offer[is_power] = "Power Deal"
    # Deal of the Week wins if a row matches both: it's the more specific,
    # deliberately-curated designation (a particular product at a particular
    # location for a particular month), while Power Deal is a generic
    # nationwide fallback — specific overrides general. Confirmed against a
    # real case: Meru's August Aria Sling listing shares the same price as
    # the nationwide Power Deal entry, so it matched both, and the sheet's
    # own Deal of the Week label for that row should win.
    offer[is_dow] = dow_type[is_dow]
    offer[is_combo] = "Combo"  # a bundle line is never a single-product deal
    df["Offer Type"] = offer

    if is_combo.any():
        # .apply() on an empty slice can't infer a numeric result dtype and
        # falls back to the input's (string) dtype, which then fails to
        # multiply against Quantity — guard skips that empty case entirely.
        bag_counts = df.loc[is_combo, "Product"].apply(_combo_bag_count).astype(int)
        df.loc[is_combo, "Quantity"] = df.loc[is_combo, "Quantity"] * bag_counts

    df["Country"] = df["Location"].apply(country_of)
    return df
