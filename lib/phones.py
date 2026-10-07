"""Checking customer phone numbers as typed at the till.

An East African mobile number written locally is 10 digits starting 07, 01
(Kenya's newer Safaricom/Airtel ranges) or 06 (Tanzania). Numbers saved with
the country code (+254, +255, +256) are read as the local form: +254 712
345 678 is 0712345678. Any other country code is an international number,
with or without the "+" (919924441799 for a customer from India, 211… South
Sudan, 90… Turkey): accepted when it has the 8 to 15 digits an international
number can have. A number starting 00 is always a typing mistake. Anything else is listed for the
shop to call the customer or check the receipt, then correct in Odoo.
"""
from __future__ import annotations

import re

import pandas as pd

VALID_STARTS = ("07", "01", "06")
_COUNTRY = re.compile(r"^(254|255|256)")
# International numbers carry at most 15 digits after the "+" (ITU E.164);
# fewer than 8 is no country's full number.
_INTL_MIN, _INTL_MAX = 8, 15


def international(raw) -> str | None:
    """The digits of a non-East-African international number, else None.

    Shops mostly save these without the "+": 91… (India), 90… (Turkey),
    211… (South Sudan). So a number counts as international when it has a
    "+", or has more than 10 digits and doesn't start with 0. A local number
    never does either. Numbers starting 00 are never read as international;
    see problem()."""
    text = str(raw or "").strip()
    digits = re.sub(r"\D", "", text)
    if digits.startswith("0"):
        return None
    if not (text.startswith("+") or len(digits) > 10):
        return None
    return None if _COUNTRY.match(digits) else digits


def local_form(raw) -> str:
    """Digits only, country code turned into the leading 0."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if _COUNTRY.match(digits) and (len(digits) > 10 or str(raw).strip().startswith("+")):
        digits = "0" + digits[3:]
    return digits


def problem(raw) -> tuple[str | None, str]:
    """(what is wrong, likely correct number or "") — (None, "") when valid
    or when no number was saved at all."""
    digits = local_form(raw)
    if not digits:
        return None, ""
    # "00…" is a slip at the till ("0070421765" for 070421765x), never a
    # dialling prefix here: always listed for correction.
    if digits.startswith("00"):
        return "Starts with 00 — typing mistake, correct the number", ""
    intl = international(raw)
    if intl is not None:
        if _INTL_MIN <= len(intl) <= _INTL_MAX:
            return None, ""
        return f"International number with {len(intl)} digits — expected 8 to 15", ""
    if len(digits) == 10 and digits.startswith(VALID_STARTS):
        return None, ""
    if len(digits) == 9 and digits[0] in "716":
        return "Missing the leading 0", "0" + digits
    if len(digits) < 10:
        return f"Too short — {len(digits)} digits", ""
    if len(digits) > 10:
        return f"Too long — {len(digits)} digits", ""
    return "Doesn't start with 07, 01 or 06", ""


def to_check(orders: pd.DataFrame) -> pd.DataFrame:
    """One row per customer record whose phone is wrong, with where and by
    whom they were served in the range."""
    if orders.empty:
        return pd.DataFrame()
    checked = orders.drop_duplicates("Customer ID")["Phone as Saved"].map(problem)
    issues = pd.DataFrame(checked.tolist(), index=checked.index, columns=["Issue", "Likely Number"])
    bad_ids = orders.loc[issues.index[issues["Issue"].notna()], "Customer ID"]
    bad = orders[orders["Customer ID"].isin(bad_ids)]
    if bad.empty:
        return pd.DataFrame()
    from lib import names
    out = (bad.groupby(["Customer ID", "Raw Name", "Phone as Saved"], as_index=False)
           .agg(**{"Served By": ("Served By", lambda v: ", ".join(sorted(set(v)))),
                   "Location": ("Location", lambda v: ", ".join(sorted(set(v)))),
                   "Orders": ("Order", "nunique"), "Last Order": ("Date", "max")}))
    found = out["Phone as Saved"].map(problem)
    out["Issue"] = found.str[0]
    out["Likely Number"] = found.str[1]
    out["Digits"] = out["Phone as Saved"].map(lambda p: len(local_form(p)))
    out["Name"] = out["Raw Name"].map(names.clean)
    return (out[["Name", "Phone as Saved", "Digits", "Issue", "Likely Number", "Location",
                 "Served By", "Orders", "Last Order"]]
            .sort_values(["Last Order", "Location"], ascending=[False, True]))
