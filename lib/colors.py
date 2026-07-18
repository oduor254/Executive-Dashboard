"""Strip a trailing color name off a product name, to roll color variants up
into their base product (e.g. "Ace Black TT" / "Ace Grey" -> "Ace").

Same color list as the color_list CTE in queries.CUSTOMER_SALES, so a name
resolves to the same base product whether matched in SQL or here in pandas.
"""
from __future__ import annotations

COLORS = [
    "Black TT", "Grey TT", "Beige TT", "Green TT",
    "Wooven Black", "Wooven Maroon", "Wooven Mustard", "Wooven Purple",
    "Wooven Cream", "Wooven Brown", "Wooven Lilac",
    "Croc Black", "Croc Brown", "Croc Mustard", "Croc Orange", "Croc Pink",
    "Dark Brown", "Mint Green", "Yellow Brown", "Yellow Dotted", "Navy Blue",
    "Antelope Brown",
    "Red.Pattern", "Red Pattern",
    "Pattern Pink", "Pattern Blue", "Pattern Red",
    "Amapiano Black", "Amapiano Brown", "Amapiano Grey", "Amapiano Nude",
    "Ankara Black", "Ankara Brown", "Ankara Grey", "Ankara Nude",
    "Black X Red",
    "Beige/Red", "Black/Cracked", "Black/Red", "Green/Red", "Maroon/Red",
    "Black/Beige", "Black/Choco", "Black/D.Brown", "Black/Grey", "Black/Spice",
    "Red/Black", "Grey/Black", "Spice/Black", "Cracked/Black", "Chocolate/Black",
    "Black 018", "Beige 018", "Dark Brown 018", "Maroon 018",
    "Titan 1", "Titan 3", "Titan 5", "Titan 6", "Titan 11", "Titan 14", "Titan 15",
    "Goyard 5",
    "Start 20", "Start 4", "Start 8",
    "Red P", "Black B", "N.Blue", "D.Brown",
    "Manyatta Dark Brown", "Manyatta Dark Green", "Manyatta Green", "Manyatta Yellow",
    "CN Black", "CN Grey", "CN Dark Brown",
    "A3 Red", "A3 Pink",
    "A4 Red", "A4 Pink",
    "A5 Red", "A5 Pink",
    "A3", "A4", "A5",
    "Crimson",
    "Beige", "Black", "Blue", "Brown", "Chocolate", "Choco",
    "Cracked", "Green", "Grey", "Gold", "Lilac", "Maroon",
    "Mustard", "Nude", "Orange", "Pink", "Purple",
    "Red", "Spice", "White", "Yellow",
]

# Longest match wins — check multi-word colors ("Dark Brown") before the
# single-word colors they contain ("Brown"), same as the SQL's ORDER BY
# LENGTH(cl.color) DESC.
_SORTED_COLORS = sorted({c.lower(): c for c in COLORS}.values(), key=len, reverse=True)


def strip_color(product_name: str) -> str:
    """Return the base product name with its trailing color removed."""
    name = str(product_name).strip()
    lower = name.lower()
    for color in _SORTED_COLORS:
        if lower == color.lower():
            return name  # the whole name IS a color, nothing to strip
        suffix = " " + color
        if lower.endswith(suffix.lower()):
            return name[: -len(suffix)].strip()
    return name
