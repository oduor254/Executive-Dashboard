"""Pull Power Deal / Deal of the Week definitions from the shared deals
spreadsheet's Kenya/Uganda/Tanzania tabs and rebuild the local CSV files
lib/deals.py classifies sales against.

Runs locally only — rewrites lib/data/*.csv on disk but doesn't commit or
push. Review the diff (git diff lib/data/) and ship it the same way as any
other code change; the deployed app only picks this up once that's pushed
and it redeploys.

Product names on the sheet don't always match the catalog's family name
exactly — abbreviations, suffix words the catalog doesn't use ("handbag",
"travel", ...), the reverse, or no relationship at all (e.g. "Laptop
Backpack" -> "Code 3"). Resolution order for each raw sheet name:
  1. MANUAL_ALIASES — pure business-knowledge mappings no algorithm could
     guess, accumulated here as they get discovered.
  2. Exact case-insensitive match against the live catalog's product
     families (same color-stripping logic as PRODUCT_LINE_ITEMS).
  3. Prefix match against the live catalog, either direction, word-
     boundary only, and only kept if there's exactly one candidate —
     ambiguous matches are left unresolved rather than guessed.
Anything still unresolved is skipped and reported back to the caller,
never silently guessed — a wrong product match would misclassify real
revenue.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from lib import db, deals, sheets_sync

SHEET_ID = "1TAGv9bGnE88nEjn2d0QvBkRhKiK3E42VI2GfU-MmJEY"
_DATA_DIR = Path(__file__).parent / "data"

# Pure business-knowledge mappings, keyed lowercase. Add to this as new
# ones get discovered (a sync run reports anything it can't resolve).
MANUAL_ALIASES = {
    # Kenya Deal of the Week
    "cairo backpack": "Cairo Bp", "college handbag": "College Hb", "mandy handbag": "Mandy Hb",
    "ovalhandbag": "Oval Handbag", "wash bag": "Washbag", "zipped lunch bag": "Zipped Lunchset",
    "zipped lunchbag": "Zipped Lunchset", "laptop backpack": "Code 3",
    "amaya handbag": "Amaya", "antitheft backpack": "Antitheft", "aurora handbag": "Aurora",
    "avana sling": "Avana", "bonita travel": "Bonita", "don man bag": "Don",
    "elyse handbag": "Elyse", "fayola messenger": "Fayola", "imani handbag": "Imani",
    "jade briefcase": "Jade", "jamela handbag": "Jamela", "kai backpack": "Kai",
    "kate sling": "Kate", "kaz travel": "Kaz", "liam travel": "Liam", "lola handbag": "Lola",
    "mega backpack": "Mega", "neo man bag": "Neo Man", "prime backpack": "Prime",
    "remi backpack": "Remi", "taji travel": "Taji", "zoezi bag": "Zoezi",
    "zuri handbag": "Zuri", "pocket travel": "Pocket Travel", "reo travel": "Reo Travel",
    "safiri travel": "Safiri Travel", "sierra handbag": "Sierra Handbag",
    "standard travel": "Standard Travel",
    "aria sling": "Aria Sling", "cess handbag": "Cess HB", "karina handbag": "Karina",
    "luna man bag": "Luna", "sarai travel": "Sarai", "sky handbag": "Skye HB",
    "zane man bag": "Zane Man",
    # Kenya Power Deals
    "aria": "Aria Sling", "big man": "Big Man Bag", "cathy": "Cathy Handbag",
    "claire": "Claire Handbag", "monah": "Monah Bp", "zane": "Zane Man",
    # Uganda
    "avana hb": "Avana HB", "big man bag": "Big Man Bag", "man bag": "Man Bag",
    "mandy hb": "Mandy HB", "mini school": "Mini School", "skye hb": "Skye HB",
    "zane man": "Zane Man",
    # Tanzania
    "avanna": "Avana HB", "avana": "Avana HB", "briefcase": "Brief Case",
    "butterfly": "Butterfly Sling", "gymbag": "Gym Bag", "mandy": "Mandy HB",
    "mini man": "Mini Manbag", "minizuri": "Mini Zuri", "monah": "Monah BP",
    "sleeves": "Sleeve 2", "sleeve": "Sleeve 2", "sleeve 2": "Sleeve 2",
    "wanderluxe": "Wander Luxe", "cairo": "Cairo BP", "celine": "Celine Sling Bag",
    "cess": "Cess HB", "reo": "Reo Travel", "splash": "Splash Backpack",
    "standard": "Standard Travel",
}

_FAMILIES_QUERY = """
WITH color_list(color) AS (
    VALUES
        ('Black TT'),('Grey TT'),('Beige TT'),('Green TT'),
        ('Wooven Black'),('Wooven Maroon'),('Wooven Mustard'),('Wooven Purple'),
        ('Wooven Cream'),('Wooven Brown'),('Wooven Lilac'),
        ('Croc Black'),('Croc Brown'),('Croc Mustard'),('Croc Orange'),('Croc Pink'),
        ('Dark Brown'),('Mint Green'),('Yellow Brown'),('Yellow Dotted'),('Navy Blue'),
        ('Antelope Brown'),
        ('Red.Pattern'),('Red Pattern'),
        ('Pattern Pink'),('Pattern Blue'),('Pattern Red'),
        ('Amapiano Black'),('Amapiano Brown'),('Amapiano Grey'),('Amapiano Nude'),
        ('Ankara Black'),('Ankara Brown'),('Ankara Grey'),('Ankara Nude'),
        ('Black X Red'),
        ('Beige/Red'),('Black/Cracked'),('Black/Red'),('Green/Red'),('Maroon/Red'),
        ('Black/Beige'),('Black/Choco'),('Black/D.Brown'),('Black/Grey'),('Black/Spice'),
        ('Red/Black'),('Grey/Black'),('Spice/Black'),('Cracked/Black'),('Chocolate/Black'),
        ('Black 018'),('Beige 018'),('Dark Brown 018'),('Maroon 018'),
        ('Titan 1'),('Titan 3'),('Titan 5'),('Titan 6'),('Titan 11'),('Titan 14'),('Titan 15'),
        ('Goyard 5'),
        ('Start 20'),('Start 4'),('Start 8'),
        ('Red P'),('Black B'),('N.Blue'),('D.Brown'),
        ('Manyatta Dark Brown'),('Manyatta Dark Green'),('Manyatta Green'),('Manyatta Yellow'),
        ('CN Black'),('CN Grey'),('CN Dark Brown'),
        ('A3 Red'),('A3 Pink'),
        ('A4 Red'),('A4 Pink'),
        ('A5 Red'),('A5 Pink'),
        ('A3'),('A4'),('A5'),
        ('Crimson'),
        ('Beige'),('Black'),('Blue'),('Brown'),('Chocolate'),('Choco'),
        ('Cracked'),('Green'),('green'),('GREEN'),('Grey'),('Gold'),('Lilac'),('Maroon'),
        ('Mustard'),('Nude'),('Orange'),('Pink'),('Purple'),
        ('Red'),('Spice'),('White'),('Yellow')
),
product_color_split AS (
    SELECT
        pt.id AS product_tmpl_id,
        pt.name AS full_name,
        (
            SELECT cl.color FROM color_list cl
            WHERE pt.name LIKE '% ' || cl.color OR pt.name = cl.color
            ORDER BY LENGTH(cl.color) DESC LIMIT 1
        ) AS matched_color
    FROM product_template pt
    WHERE pt.name NOT ILIKE '%+%'
      AND pt.name NOT ILIKE '% or %'
      AND pt.name NOT ILIKE '%Combo%'
      AND pt.name NOT ILIKE '%Sample%'
      AND pt.name NOT ILIKE '%Delivery Fee%'
      AND pt.name NOT ILIKE '%Gift Bag%'
)
SELECT DISTINCT
    CASE
        WHEN matched_color IS NULL THEN full_name
        WHEN full_name = matched_color THEN full_name
        ELSE TRIM(LEFT(full_name, LENGTH(full_name) - LENGTH(matched_color)))
    END AS family
FROM product_color_split;
"""


def _live_families_lower() -> dict[str, str]:
    """{lowercased family: canonical family}, from the live catalog."""
    df = db.run_query(_FAMILIES_QUERY)
    return {f.strip().lower(): f.strip() for f in df["family"].dropna()}


def resolve(raw_name: str, families_lower: dict[str, str]) -> tuple[str | None, str]:
    """Returns (resolved_family_or_None, method) — method is 'manual',
    'exact', 'prefix', or 'unresolved'."""
    key = raw_name.strip().lower()
    if not key:
        return None, "unresolved"
    if key in MANUAL_ALIASES:
        return MANUAL_ALIASES[key], "manual"
    if key in families_lower:
        return families_lower[key], "exact"

    candidates = {
        fam for fam_lower, fam in families_lower.items()
        if fam_lower != key and (key.startswith(fam_lower + " ") or fam_lower.startswith(key + " "))
    }
    if len(candidates) == 1:
        return candidates.pop(), "prefix"
    return None, "unresolved"


def _clean_price(v) -> float:
    return float(str(v).replace("Ksh.", "").replace(",", "").strip())


def _parse_kenya(sh, families_lower: dict[str, str], unresolved: list[dict]) -> tuple[list[dict], list[dict]]:
    values = sh.worksheet("Kenya").get_all_values()
    kdf = pd.DataFrame(values[1:], columns=values[0])
    kdf = kdf[kdf["Month"].str.strip() != ""].copy()

    dow_rows: list[dict] = []
    power_rows: list[dict] = []
    for _, row in kdf.iterrows():
        product, method = resolve(row["Product Name"], families_lower)
        if product is None:
            unresolved.append({"Country": "Kenya", "Type": row["Type"], "Sheet Name": row["Product Name"]})
            continue
        price_then = _clean_price(row["Original Price (Ksh)"])
        price_now = _clean_price(row["Current Price (Ksh)"])
        offer_type = row["Type"].strip().lower()
        if offer_type == "deal of the week":
            dow_rows.append({
                "month": row["Month"].strip(), "product": product, "location": row["Location"].strip(),
                "price_then": price_then, "price_now": price_now, "type": "Deal of the Week",
            })
        elif offer_type == "power deals":
            power_rows.append({
                "month": row["Month"].strip(), "product": product,
                "price_then": price_then, "price_now": price_now,
            })
    return dow_rows, power_rows


def _parse_uganda(sh, families_lower: dict[str, str], unresolved: list[dict]) -> list[dict]:
    values = sh.worksheet("Uganda").get_all_values()
    udf = pd.DataFrame(values[1:], columns=values[0])
    udf = udf[udf["MONTH"].str.strip() != ""].copy()

    rows: list[dict] = []
    for _, row in udf.iterrows():
        product, method = resolve(row["JANUARY COMBOS"], families_lower)
        if product is None:
            unresolved.append({"Country": "Uganda", "Type": "Singles", "Sheet Name": row["JANUARY COMBOS"]})
            continue
        rows.append({
            "month": row["MONTH"].strip(), "product": product, "location": "Uganda",
            "price_then": round(_clean_price(row["PRICE WAS"]) / 29, 2),
            "price_now": round(_clean_price(row["PRICE NOW"]) / 29, 2),
            "type": "Singles",
        })
    return rows


def _parse_tanzania(sh, families_lower: dict[str, str], unresolved: list[dict]) -> list[dict]:
    values = sh.worksheet("Tanzania").get_all_values()
    data_rows = values[4:]

    def parse_section(month_col, product_col, before_ksh_col, offer_ksh_col, offer_type) -> list[dict]:
        rows: list[dict] = []
        for r in data_rows:
            if len(r) <= offer_ksh_col:
                continue
            month, raw_name = r[month_col].strip(), r[product_col].strip()
            if not month or not raw_name:
                continue
            product, method = resolve(raw_name, families_lower)
            if product is None:
                unresolved.append({"Country": "Tanzania", "Type": offer_type, "Sheet Name": raw_name})
                continue
            rows.append({
                "month": month, "product": product, "location": "Sinza",
                "price_then": _clean_price(r[before_ksh_col]), "price_now": _clean_price(r[offer_ksh_col]),
                "type": offer_type,
            })
        return rows

    return parse_section(0, 1, 2, 4, "Singles") + parse_section(7, 8, 9, 11, "Special Offers")


def _merge_with_existing(fresh: pd.DataFrame, filename: str, key: list[str]) -> pd.DataFrame:
    """Fresh rows layered over whatever the file already holds.

    A period the sheet still carries is refreshed from the sheet; a period it
    has rolled past is kept as previously recorded. This is what makes past
    months answerable at all — the sheet is a working document for the current
    month, so it is the CSV, not the sheet, that has to be the archive.
    """
    path = _DATA_DIR / filename
    if not path.exists():
        return fresh

    # Repaired the same way deals._load_* repairs it: a file written before the
    # year column existed is still an archive worth keeping, and dropping it
    # for want of one column would quietly discard the history this merge
    # exists to protect.
    existing = deals._with_year(pd.read_csv(path))
    if existing.empty or not set(key).issubset(existing.columns):
        return fresh

    # Only whole periods the sheet re-stated are replaced — dropping a single
    # product from a month the sheet still lists means it stopped being on
    # offer, and that should be reflected rather than kept alive forever.
    restated = set(zip(*(fresh[c] for c in ("year", "month"))))
    kept = existing[
        ~existing.apply(lambda r: (r["year"], r["month"]) in restated, axis=1)
    ]

    merged = pd.concat([kept, fresh], ignore_index=True)
    return merged.drop_duplicates(subset=key, keep="last").sort_values(key)


def sync() -> dict:
    """Fetch the sheet, resolve product names, and rewrite
    lib/data/power_deals.csv and deals_of_week.csv. Returns a summary for
    the UI to display — row counts per country/type, and anything that
    couldn't be auto-resolved and was skipped."""
    sh = sheets_sync._client().open_by_key(SHEET_ID)
    families_lower = _live_families_lower()
    unresolved: list[dict] = []

    kenya_dow, kenya_power = _parse_kenya(sh, families_lower, unresolved)
    uganda_rows = _parse_uganda(sh, families_lower, unresolved)
    tanzania_rows = _parse_tanzania(sh, families_lower, unresolved)

    # The sheet's sections are month names with no year on them, so the year
    # is stamped here from the calendar: it is the current year's tracker
    # being read. Without it every past year gets scored against this year's
    # offers — see deals.classify.
    sheet_year = date.today().year

    all_dow = pd.DataFrame(kenya_dow + uganda_rows + tanzania_rows)
    all_dow["year"] = sheet_year
    all_dow = (
        all_dow.groupby(["year", "month", "product", "location", "type"], as_index=False)
        .agg(price_then=("price_then", "first"), price_now=("price_now", "first"))
        .sort_values(["year", "month", "location", "product"])
    )
    power_df = pd.DataFrame(kenya_power)
    power_df["year"] = sheet_year
    power_df = (
        power_df
        .groupby(["year", "month", "product"], as_index=False)
        .agg(price_then=("price_then", "first"), price_now=("price_now", "first"))
        .sort_values(["year", "month", "product"])
    )

    # Merged with what is already on disk, not written over it. A sync used to
    # replace both files wholesale, so the moment the sheet rolled forward and
    # dropped an old month, that month's history disappeared from the
    # dashboard and past periods retroactively changed. Existing rows for a
    # period the sheet still carries are refreshed; periods it no longer
    # carries are kept.
    all_dow = _merge_with_existing(
        all_dow, "deals_of_week.csv", ["year", "month", "product", "location", "type"])
    power_df = _merge_with_existing(
        power_df, "power_deals.csv", ["year", "month", "product"])

    all_dow.to_csv(_DATA_DIR / "deals_of_week.csv", index=False)
    power_df.to_csv(_DATA_DIR / "power_deals.csv", index=False)

    # Stamped in a file of its own rather than read off the CSVs' modification
    # time, which a git checkout resets — on a deployment that would report
    # the last deploy as the last sync, and the whole point is to notice when
    # the sheet has moved on and this has not.
    (_DATA_DIR / deals.SYNCED_AT_FILE).write_text(json.dumps({
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "dow_rows": int(len(all_dow)),
        "power_rows": int(len(power_df)),
    }), encoding="utf-8")

    # Pick up the new files immediately in this session, without a restart.
    deals._load_power_deals.clear()
    deals._load_deals_of_week.clear()

    return {
        "kenya_dow": len(kenya_dow),
        "kenya_power": len(kenya_power),
        "uganda": len(uganda_rows),
        "tanzania": len(tanzania_rows),
        "dow_rows_written": len(all_dow),
        "power_rows_written": len(power_df),
        "unresolved": unresolved,
    }
