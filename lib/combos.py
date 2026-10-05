"""Running combos versus self-made (made-to-order) combos.

Odoo lists both as combo products; only the name tells them apart:
  * a running combo is the month's catalogue offer, written as a choice
    without colours — "Jumbo + Standard or Liam Travel + Pioneer or Antitheft
    Backpack", "Sarai Travel + Prime Backpack";
  * a self-made combo is put together for one customer and carries the word
    "Combo" — "Mega Green + Man Bag Brown Combo" — usually with each bag's
    colour, sometimes only the families ("Kate + Man Combo").
So a combo is self-made when its name says "combo", or when it joins bags with
"+" and names a colour on them ("Jumbo green+Jumbo black").
"""
from __future__ import annotations

import re
from itertools import combinations

import pandas as pd

from lib import taxonomy

RUNNING = "Running"
SELF_MADE = "Self-made"

_COMBO_WORD = re.compile(r"\bcombo\b", re.IGNORECASE)
_COLOURS = sorted(taxonomy._COLOR_SUFFIXES, key=len, reverse=True)


def parts(name: str) -> list[str]:
    """The bags in a combo name, "Combo" removed: ["Mega Green", "Man Bag Brown"]."""
    cleaned = _COMBO_WORD.sub("", str(name))
    return [p.strip() for p in cleaned.split("+") if p.strip()]


def colour_of(part: str) -> str | None:
    low = part.lower()
    for colour in _COLOURS:
        c = colour.lower()
        if low == c or low.endswith(" " + c):
            return colour[0].upper() + colour[1:]
    return None


def kind(name: str) -> str:
    if _COMBO_WORD.search(str(name)):
        return SELF_MADE
    bags = parts(name)
    if len(bags) > 1 and any(colour_of(b) for b in bags):
        return SELF_MADE
    return RUNNING


# Self-made combo names often shorten the bag ("Kate + Man Combo"); these are
# the short forms and the bag they mean.
_SHORT_NAMES = {"man": "Man Bag", "big": "Big Man Bag", "big man": "Big Man Bag",
                "code": "Code 3", "laptop": "Code 3", "standard": "Standard Travel",
                "baby": "Baby Bag", "reo": "Reo Travel", "safiri": "Safiri Travel",
                "aria": "Aria Sling", "oval": "Oval Handbag", "pocket": "Pocket Travel",
                "school": "School Bag", "gym": "Gym Bag", "belt": "Belt Bag",
                "moon": "Moon Bag", "butterfly": "Butterfly Sling", "lunchset": "Lunchset"}


def bag_family(part: str) -> str:
    """The bag a combo part names, colour stripped: "Man Bag Brown" -> "Man Bag"."""
    family = taxonomy.group_of(part.title() if part.islower() else part)
    return _SHORT_NAMES.get(family.lower(), family)


def classify(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Type"] = out["Combo"].map(kind)
    return out


def self_made_patterns(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """What customers ask to have combined, weighted by bundles sold.

    pairs   — two bags requested together (bag level, order ignored)
    bags    — how often each bag appears in a self-made combo
    colours — the colours asked for
    """
    pair_rows, bag_rows, colour_rows = [], [], []
    for _, r in df.iterrows():
        pieces = parts(r["Combo"])
        families = [bag_family(p) for p in pieces]
        for fam, piece in zip(families, pieces):
            bag_rows.append({"Bag": fam, "Bundles": r["Bundles"], "Revenue": r["Revenue"],
                             "Combo": r["Combo"]})
            colour = colour_of(piece)
            if colour:
                colour_rows.append({"Colour": colour, "Bundles": r["Bundles"]})
        unique = sorted(set(families))
        pairs = list(combinations(unique, 2))
        if len(unique) == 1 and len(families) > 1:   # Jumbo + Jumbo
            pairs = [(unique[0], unique[0])]
        for a, b in pairs:
            pair_rows.append({"Pairing": f"{a} + {b}", "Bundles": r["Bundles"],
                              "Revenue": r["Revenue"], "Combo": r["Combo"]})

    def summarise(rows, key):
        if not rows:
            return pd.DataFrame(columns=[key, "Bundles"])
        frame = pd.DataFrame(rows)
        agg = {"Bundles": ("Bundles", "sum")}
        if "Revenue" in frame:
            agg["Revenue"] = ("Revenue", "sum")
        if "Combo" in frame:
            agg["Versions"] = ("Combo", "nunique")
        return frame.groupby(key, as_index=False).agg(**agg).sort_values("Bundles", ascending=False)

    return {"pairs": summarise(pair_rows, "Pairing"),
            "bags": summarise(bag_rows, "Bag"),
            "colours": summarise(colour_rows, "Colour")}
