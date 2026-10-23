"""New products: the bag styles added to Odoo after Lafemme ("Runway Bags").

Shared by the Product Sales page (its Runway Bags view) and the attendant
score cards (Sale of New Products), so both mean the same styles.
"""
from __future__ import annotations

import pandas as pd

from lib import db, queries, taxonomy

RUNWAY_AFTER = "Lafemme"


def runway_families() -> pd.DataFrame:
    """Bag families whose first product was added to Odoo after Lafemme's,
    each with the day it was added and its colours so far."""
    bags = db.run_query(queries.BAG_TEMPLATE_DATES)
    if bags.empty:
        return pd.DataFrame(columns=["Product", "Added", "Colours", "Category"])
    bags = bags.assign(Family=bags["Product"].map(taxonomy.group_of),
                       Created=pd.to_datetime(bags["Created"]))
    first = (bags.groupby("Family")
             .agg(Added=("Created", "min"), Colours=("Product", "nunique"),
                  Category=("Category", "first")))
    anchor = first[first.index.str.lower().str.startswith(RUNWAY_AFTER.lower())]["Added"].min()
    if pd.isna(anchor):
        return pd.DataFrame(columns=["Product", "Added", "Colours", "Category"])
    older = [f.lower() for f in first[first["Added"] <= anchor].index]
    # A custom or special version of an older bag ("Fabela Custom") is that
    # bag, not a new style.
    is_variant = [any(f.lower().startswith(o + " ") for o in older) for f in first.index]
    runway = first[(first["Added"] > anchor) & ~pd.Series(is_variant, index=first.index)
                   & ~first.index.str.lower().str.startswith(RUNWAY_AFTER.lower())]
    runway = runway.assign(Added=runway["Added"].dt.date,
                           Category=runway["Category"].str.replace("Bags / ", "", regex=False))
    return runway.reset_index().rename(columns={"Family": "Product"}).sort_values("Added")
