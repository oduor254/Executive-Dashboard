"""Product positioning: for each bag, who buys it, the problem it solves for
them, and why they would buy it — written from the sales themselves.

  Target customer  — from who actually bought it in the period: women, men or
                     corporate (the gender recorded at the till), its price
                     against the typical bag in its category, and where it
                     sells (the Nairobi CBD shops, the branches, online).
  Problem it solves — what the bag type does for its buyer (CATEGORY_NEEDS),
                     sharpened by what the name says (KEYWORD_NEEDS: an
                     Antitheft backpack also keeps valuables from
                     pickpockets).
  Why they'd buy   — the evidence: its rank in the category, value against
                     the category's typical price, this month's Power Deal,
                     the combos it is paired in, and whether demand is
                     rising or falling.

The problem statements are per bag type, not per product: edit them here as
the team learns more.
"""
from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd

MIN_UNITS = 20                      # fewer sales than this in the period: too few to read
NOT_PRODUCTS = {"Combos", "Combo", "Accessories", "Saleable", "Ankara Set"}
CBD = {"Hilton", "Ktda", "Hazina", "Starmall"}

# Bag type → (the problem it solves, the customer it is for).
CATEGORY_NEEDS = {
    "Backpacks": ("carrying a laptop, documents and the day's essentials hands-free on the commute — "
                  "matatu, boda or on foot — without shoulder strain",
                  "students and young professionals who commute"),
    "Travel Bags": ("packing for an upcountry trip, a weekend away or a holiday in one strong bag "
                    "that is easy to carry and holds a lot",
                    "travellers — upcountry trips, weekends away, holidays"),
    "Handbags": ("carrying the day's essentials to work and outings in a bag that looks good "
                 "and holds what she needs",
                 "women wanting an everyday or work handbag"),
    "Man Bags": ("keeping phone, wallet, keys and documents together in one small bag, "
                 "without carrying a full backpack",
                 "men on the move who want their essentials in one place"),
    "Sling Bags": ("keeping phone, cash and small items close and hands-free when out and about",
                   "people out in town, at the market or at events"),
    "Briefcase Bags": ("carrying a laptop and documents professionally to the office and meetings",
                       "office professionals and companies equipping staff"),
    "School Bags": ("carrying books to school in a bag that survives the whole term",
                    "parents buying for school-going children"),
    "Chest Bags": ("keeping phone and wallet in front of the body, hands-free and hard to "
                   "pickpocket in crowds",
                   "young people moving around town"),
    "Tote Bags": ("carrying a lot — laptop, shopping, extras — in one roomy, open bag",
                  "women who carry a lot through the day"),
    "Gym Bags": ("keeping gym kit and shoes apart from everyday things",
                 "gym-goers and people who play sport"),
    "Waist Bags": ("keeping essentials on the body and hands free",
                   "people who want hands free — travel, events, business on foot"),
    "Lunch Bags": ("carrying packed food to work or school, clean and kept together",
                   "workers and parents who pack lunch"),
    "Diaper Bags": ("organising a baby's diapers, bottles and wipes in one bag",
                    "new parents"),
    "Toiletries Bags": ("keeping toiletries together and spill-safe when travelling",
                        "travellers"),
}
_DEFAULT_NEED = ("carrying everyday things conveniently", "everyday shoppers")

# What a product's name adds to its bag type's problem.
KEYWORD_NEEDS = [
    (r"antitheft|anti-theft", "keeps valuables safe from pickpockets in crowded town and matatus"),
    (r"laptop|code ?\d", "protects a laptop in a padded compartment"),
    (r"\bmini\b", "in a compact size for just the essentials"),
    (r"jumbo|mega|\bbig\b|alpha", "with extra room for long trips or carrying a lot"),
]


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _who(row) -> str:
    f, m, c = row["Female %"], row["Male %"], row["Corporate %"]
    if c >= 0.3:
        return f"companies first — {_pct(c)} of units are corporate orders (staff kits and gifts)"
    if row["Category"] in ("Man Bags", "Briefcase Bags", "Chest Bags") and f >= 0.4:
        return f"men, but {_pct(f)} of it is bought by women — often as a gift for a man"
    if row["Category"] in ("Handbags", "Tote Bags") and m >= 0.3:
        return f"women, but {_pct(m)} is bought by men — likely as a gift"
    if f >= 0.65:
        return f"mainly women ({_pct(f)} of units)"
    if m >= 0.65:
        return f"mainly men ({_pct(m)} of units)"
    return f"women and men alike ({_pct(f)} women, {_pct(m)} men)"


def _price_band(row) -> str:
    ratio = row["Price"] / row["Category Price"] if row["Category Price"] else 1
    typical = f"KES {row['Category Price']:,.0f}"
    if ratio <= 0.85:
        return f"a budget pick at KES {row['Price']:,.0f} (typical {row['Category']} {typical})"
    if ratio >= 1.15:
        return f"the premium end at KES {row['Price']:,.0f} (typical {row['Category']} {typical})"
    return f"mid-priced at KES {row['Price']:,.0f}"


def _where(row) -> str:
    parts = []
    if "," not in str(row["Top Shops"]):          # one shop picked: where is a given
        parts.append(f"shoppers at {row['Top Shops']}")
    elif row["CBD %"] >= 0.6:
        parts.append(f"Nairobi CBD shoppers ({_pct(row['CBD %'])} of units at Hilton, KTDA, Hazina and Starmall)")
    elif row["CBD %"] <= 0.3:
        parts.append(f"branch shoppers outside the CBD (top: {row['Top Shops']})")
    else:
        parts.append(f"shoppers across the network (top: {row['Top Shops']})")
    if row["Online %"] >= 0.35:
        parts.append(f"strong online demand ({_pct(row['Online %'])} of units online)")
    return "; ".join(parts)


def _problem(row) -> str:
    need = CATEGORY_NEEDS.get(row["Category"], _DEFAULT_NEED)[0]
    extra = [text for pattern, text in KEYWORD_NEEDS if re.search(pattern, row["Product"], re.I)]
    return need[0].upper() + need[1:] + ("; " + "; ".join(dict.fromkeys(extra)) if extra else "") + "."


def _why(row) -> str:
    reasons = []
    if row["Rank"] == 1:
        reasons.append(f"the best seller in {row['Category']} ({row['Units']:,.0f} units) — proven demand")
    elif row["Rank"] <= 3:
        reasons.append(f"#{row['Rank']} in {row['Category']} ({row['Units']:,.0f} units)")
    ratio = row["Price"] / row["Category Price"] if row["Category Price"] else 1
    if ratio <= 0.85:
        reasons.append("value for money: it does the job for less than most bags of its kind")
    elif ratio >= 1.15:
        reasons.append("buyers pay above the usual price for it — quality and look are the draw")
    if row["Power Deal"]:
        reasons.append(f"on this month's Power Deal ({row['Power Deal']})")
    if row["Combos"]:
        reasons.append(f"customers pair it — sold in {row['Combos']} combo{'s' if row['Combos'] != 1 else ''}")
    if pd.notna(row["Trend %"]):
        if row["Trend %"] >= 100:
            reasons.append(f"demand up sharply: last 30 days selling {row['Trend %'] / 100 + 1:.1f}× the earlier rate")
        elif row["Trend %"] >= 20:
            reasons.append(f"demand rising: last 30 days selling {row['Trend %']:.0f}% faster than before")
        elif row["Trend %"] <= -20:
            reasons.append(f"demand cooling: last 30 days selling {abs(row['Trend %']):.0f}% slower than before")
    if row["Corporate %"] >= 0.3:
        reasons.append("a safe choice for company orders — bought in bulk for staff and gifts")
    text = "; ".join(reasons)
    return text[0].upper() + text[1:] + "." if text else "Steady seller in its category."


def profiles(sales: pd.DataFrame, power_deals: pd.DataFrame | None = None,
             today: date | None = None) -> pd.DataFrame:
    """One row per bag (Product as the tills name its family) with its
    numbers and the three answers. `sales` is CUSTOMER_SALES over the period."""
    today = today or date.today()
    s = sales[(sales["Quantity"] > 0) & ~sales["Category"].isin(NOT_PRODUCTS)].copy()
    if s.empty:
        return pd.DataFrame()
    s["Date"] = pd.to_datetime(s["Date"])
    keys = ["Category", "Product"]
    g = s.groupby(keys)
    units = g["Quantity"].sum()
    t = pd.DataFrame({
        "Units": units,
        "Revenue": g["Total"].sum().round(0),
        # Bags folded into a combo carry a zero price; the price is what it sells for alone.
        "Price": s[s["Price"] > 0].groupby(keys)["Price"].median().round(0),
    })
    share = lambda mask: s[mask].groupby(keys)["Quantity"].sum().reindex(t.index).fillna(0) / units
    for gender in ("Female", "Male", "Corporate"):
        t[f"{gender} %"] = share(s["Gender"] == gender)
    t["CBD %"] = share(s["Location"].isin(CBD))
    t["Online %"] = share(s["Customer Type"] == "online")
    top = s.groupby(keys + ["Location"])["Quantity"].sum().reset_index().sort_values("Quantity", ascending=False)
    t["Top Shops"] = top.groupby(keys)["Location"].apply(lambda v: ", ".join(v.head(3)))
    # Trend: units a day in the last 30 days against the days before.
    recent = s["Date"] >= pd.Timestamp(today) - pd.Timedelta(days=30)
    first = s["Date"].min()
    early_days = max((pd.Timestamp(today) - pd.Timedelta(days=30) - first).days, 1)
    r = s[recent].groupby(keys)["Quantity"].sum().reindex(t.index).fillna(0) / 30
    e = s[~recent].groupby(keys)["Quantity"].sum().reindex(t.index).fillna(0) / early_days
    t["Trend %"] = ((r / e.where(e > 0) - 1) * 100).round(0) if early_days >= 14 else np.nan

    t = t[t["Units"] >= MIN_UNITS].reset_index()
    if t.empty:
        return t
    t["Category Price"] = t.groupby("Category")["Price"].transform("median")
    t["Rank"] = t.groupby("Category")["Units"].rank(ascending=False, method="min").astype(int)
    combos = sales[sales["Category"].isin({"Combos", "Combo"})]["Product"].dropna().unique()
    # "Man Bag" is in "Big Man Bag + …" too: a name preceded by another word is a different bag.
    t["Combos"] = [sum(bool(re.search(rf"(?<!\w )\b{re.escape(p)}\b", c, re.I)) for c in combos)
                   for p in t["Product"]]
    deal = {}
    if power_deals is not None and not power_deals.empty:
        month = power_deals[(power_deals["year"] == today.year)
                            & (power_deals["month"] == today.strftime("%B"))]
        deal = {r.product: f"KES {r.price_now:,.0f}, was {r.price_then:,.0f}" for r in month.itertuples()}
    t["Power Deal"] = t["Product"].map(deal).fillna("")

    t["Target Customer"] = [
        f"{CATEGORY_NEEDS.get(r['Category'], _DEFAULT_NEED)[1].capitalize()}: {_who(r)}; "
        f"{_price_band(r)}; {_where(r)}." for _, r in t.iterrows()]
    t["Problem It Solves"] = [_problem(r) for _, r in t.iterrows()]
    t["Why They'd Buy"] = [_why(r) for _, r in t.iterrows()]
    for col in ("Female %", "Male %", "Corporate %", "CBD %", "Online %"):
        t[col] = (t[col] * 100).round(0)
    return t.sort_values(["Category", "Rank"])
