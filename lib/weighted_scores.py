"""Weighted score cards for shop managers (heads) and shop attendants.

Each measure is scored out of 100 and carries a weight; a person's score is

    Σ (weight × score) ÷ Σ (weights of the measures that apply to them)

so a measure that doesn't apply in the period — someone never on WhatsApp
duty, a shop with no stock count, no training questionnaire closed — is left
out and the rest are re-weighted, rather than scoring zero. That is how the
varying roles are handled: at Hilton and KTDA one person prints at the desk
while the rest are on the floor, Starmall sometimes does the same, and the
shop manager plans who does what each morning. So:

  * Personal Target — the shop's daily target is split among the people who
    were on the floor that day (served at least one order); the person at
    the desk serving nobody takes no share that day.
  * Respond Fast — counted only on the days a person held the online role.
    The role tags (floor / online / admin) hold the current day's role, so
    past days are only known from the day each tag was set.
  * Attendance — only for days marked in the shop's attendance.

Scoring: a measure with a target is scored against it (capped at 100); a
natural rate (the customer target, customers captured, chats answered within three
minutes) is scored as the rate itself; WhatsApp-lead conversion and the share
of new products — where rates differ by nature between shops and people —
are scored against the best (best = 100).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from lib import scorecards, staff_numbers, taxonomy

# (measure, weight %, how it is scored)
MANAGER_MEASURES = [
    ("Shop Target", 30, "revenue against the shop's daily targets"),
    ("Basket Value", 10, f"average transaction value against KES {scorecards.BASKET_TARGET:,}"),
    ("Walk-in Conversion", 10, "walk-ins who bought ÷ walk-ins counted"),
    ("WhatsApp Conversion", 10, "WhatsApp leads converted, against the best shop"),
    ("Response Time", 7, f"average first WhatsApp reply against {scorecards.RESPONSE_TARGET_MIN} min"),
    ("Customer Feedback", 8, f"customers giving feedback against {scorecards.FEEDBACK_TARGET}%"),
    ("Training Plan", 10, "the team's answers to every training questionnaire due"),
    ("Stock Accuracy", 10, "100 − stock-count variance %"),
]
ATTENDANT_MEASURES = [
    ("Personal Target", 30, "own sales against their share of the daily targets"),
    ("Bulk Orders", 5, "bulk sales against 10% of their own target"),
    ("Basket Value", 10, f"average transaction value against KES {scorecards.BASKET_TARGET:,}"),
    ("New Products", 4, "share of their bags that are new styles, against the best"),
    ("Customer Target", 15, "customers served ÷ expected (their target ÷ the shop's average spend per customer)"),
    ("Respond Fast", 10, "WhatsApp chats answered within 3 min, on their online days"),
    ("Customer Service", 7, "average staff-assistance rating from their customers (of 5)"),
    ("Customer Feedback", 4, f"feedback received ÷ customers served, against {scorecards.FEEDBACK_TARGET}%"),
    ("Customer Capture", 5, "sales with the customer's own details captured in Odoo"),
    ("Training", 5, "sales training scores"),
    ("Attendance", 5, "present and on time on the days marked (late counts half)"),
]
BULK_MIN_BAGS = 5        # an order of this many bags or more, or a corporate one, is bulk
BULK_SHARE = 10.0        # bulk sales are expected to be this % of a person's own target
FEEDBACK_WINDOW_DAYS = 14
FAST_REPLY_MIN = scorecards.RESPONSE_TARGET_MIN


def weighted(table: pd.DataFrame, measures: list[tuple]) -> pd.DataFrame:
    """Add each measure's points and the weighted score."""
    out = table.copy()
    used = pd.Series(0.0, index=out.index)
    total = pd.Series(0.0, index=out.index)
    for name, weight, _ in measures:
        s = out[f"{name} Score"].clip(lower=0, upper=100)
        out[f"{name} Score"] = s.round(0)
        out[f"{name} Points"] = (s * weight / 100).round(1)
        used += np.where(s.notna(), weight, 0)
        total += (s * weight / 100).fillna(0)
    out["Weight Counted %"] = used
    out["Weighted Score"] = (total / used.where(used > 0) * 100).round(0)
    return out


def _best(values: pd.Series) -> pd.Series:
    """A rate against the best of the group: best = 100."""
    top = values.max()
    return values / top * 100 if pd.notna(top) and top > 0 else values * np.nan


# ------------------------------------------------------------- managers ---

def manager_cards(shops: pd.DataFrame, heads: pd.DataFrame, footfall: pd.DataFrame | None,
                  chats: pd.DataFrame | None, training_rows: pd.DataFrame | None,
                  stock: pd.DataFrame | None) -> pd.DataFrame:
    """One row per shop and its head: the shop's measures, weighted."""
    t = shops.set_index("Location").copy()
    head_of = {staff_numbers.shop_name(s): h for s, h in zip(heads["Shop"], heads["Head"])}
    t.insert(0, "Head", [head_of.get(loc, "—") for loc in t.index])

    t["Shop Target Score"] = t["Target %"]
    t["Basket Value Score"] = t["Basket Value %"]

    if footfall is not None and not footfall.empty:
        counted = footfall[footfall["Visitors"].fillna(0) > 0]
        g = counted.groupby("Location")
        conv = g["Walk-in Orders"].sum() / g["Visitors"].sum() * 100
        t["Walk-in Conversion %"] = conv.reindex(t.index).round(1)
    else:
        t["Walk-in Conversion %"] = np.nan
    t["Walk-in Conversion Score"] = t["Walk-in Conversion %"]

    if chats is not None and not chats.empty:
        g = chats.groupby("Branch")
        rate = g["Converted"].mean() * 100
        t["WhatsApp Chats"] = g.size().reindex(t.index)
        t["WhatsApp Conversion %"] = rate.reindex(t.index).round(1)
    else:
        t["WhatsApp Chats"] = np.nan
        t["WhatsApp Conversion %"] = np.nan
    t["WhatsApp Conversion Score"] = _best(t["WhatsApp Conversion %"])

    t["Response Time Score"] = t.get("Response vs Target %", np.nan)
    t["Customer Feedback Score"] = t["Feedback of Target %"]

    if training_rows is not None and not training_rows.empty:
        done = training_rows.groupby("Location")["Answered"].mean() * 100
        t["Training Completion %"] = done.reindex(t.index).round(1)
    else:
        t["Training Completion %"] = np.nan
    t["Training Plan Score"] = t["Training Completion %"]

    if stock is not None and not stock.empty:
        s = stock.assign(Location=stock["Shop"].map(staff_numbers.shop_name)).groupby("Location").sum(numeric_only=True)
        variance = s["Abs Difference"] / s["System Qty"].where(s["System Qty"] > 0) * 100
        t["Stock Counts"] = s["Counts"].reindex(t.index)
        t["Stock Variance %"] = variance.reindex(t.index).round(2)
    else:
        t["Stock Counts"] = np.nan
        t["Stock Variance %"] = np.nan
    t["Stock Accuracy Score"] = 100 - t["Stock Variance %"]

    t = weighted(t, MANAGER_MEASURES)
    return t.reset_index().rename(columns={"index": "Location"}).sort_values("Weighted Score", ascending=False)


# ----------------------------------------------------------- attendants ---

def _roles_by_day(roles: pd.DataFrame | None) -> pd.DataFrame:
    if roles is None or roles.empty:
        return pd.DataFrame(columns=["Person", "Role", "Date"])
    r = roles.copy()
    r["Date"] = pd.to_datetime(r["Date"]).dt.date
    return r


def attendant_cards(df: pd.DataFrame, people: pd.DataFrame, *, bag_lines: pd.DataFrame | None,
                    new_families: set[str], chats: pd.DataFrame | None,
                    roles: pd.DataFrame | None, responses: pd.DataFrame | None,
                    attendance: pd.DataFrame | None) -> pd.DataFrame:
    """One row per attendant/BA per shop: the attendant measures, weighted.

    `df` is the score cards' orders (scorecards.prepare) and `people` the
    rows from scorecards.attendant_cards (target, basket, feedback, training).
    """
    keys = ["Attendant / BA", "Location"]
    t = people.set_index(keys).copy()
    served = df[df["Served By"] != scorecards.NOT_RECORDED].rename(columns={"Served By": "Attendant / BA"})
    g = served.groupby(keys)

    t["Personal Target Score"] = t["Target %"]

    bulk = served[(served["Bags"] >= BULK_MIN_BAGS) | served["Corporate"]]
    t["Bulk Sales"] = bulk.groupby(keys)["Revenue"].sum().reindex(t.index).fillna(0).round(0)
    t["Bulk % of Target"] = (t["Bulk Sales"] / t["Target"].where(t["Target"] > 0) * 100).round(1)
    t["Bulk Orders Score"] = t["Bulk % of Target"] / BULK_SHARE * 100

    t["Basket Value Score"] = t["Basket Value %"]

    if bag_lines is not None and not bag_lines.empty:
        lines = bag_lines.merge(served[["Order ID"] + keys], on="Order ID")
        lines["New"] = lines["Product"].map(taxonomy.group_of).isin(new_families)
        lg = lines.groupby(keys)
        share = (lines[lines["New"]].groupby(keys)["Qty"].sum() / lg["Qty"].sum() * 100)
        t["New Products %"] = share.reindex(t.index).fillna(0).where(
            lg["Qty"].sum().reindex(t.index) > 0).round(1)
    else:
        t["New Products %"] = np.nan
    t["New Products Score"] = _best(t["New Products %"])

    # Customer target: the customers their share of the target needs at the
    # shop's average spend per customer (100,000 a day at 4,000 is 25
    # customers; two on the floor, 12.5 each). Their target is already the
    # sum of their daily shares, so expected = target ÷ the shop's average
    # spend over the period. Customers are counted as sales, in both.
    shop = df.groupby("Location").agg(Revenue=("Revenue", "sum"), Sales=("Order ID", "nunique"))
    avg_spend = shop["Revenue"] / shop["Sales"].where(shop["Sales"] > 0)
    t["Shop Avg Spend"] = [avg_spend.get(loc) for _, loc in t.index]
    t["Shop Avg Spend"] = t["Shop Avg Spend"].round(0)
    t["Expected Customers"] = (t["Target"] / t["Shop Avg Spend"].where(t["Shop Avg Spend"] > 0)).round(1)
    t["Customers Served"] = g["Order ID"].nunique().reindex(t.index).fillna(0).astype(int)
    t["Customer Target %"] = (t["Customers Served"] / t["Expected Customers"].where(t["Expected Customers"] > 0)
                              * 100).round(1)
    t["Customer Target Score"] = t["Customer Target %"]

    # Respond fast: the shop's chats on the days the person held the online role.
    online = _roles_by_day(roles)
    online = online[online["Role"] == "online"]
    fast = pd.Series(np.nan, index=t.index)
    if chats is not None and not chats.empty and not online.empty:
        c = chats.assign(Date=pd.to_datetime(chats["Date"]).dt.date,
                         Minutes=pd.to_numeric(chats["First Response (min)"], errors="coerce"))
        c = c.dropna(subset=["Minutes"])
        per_day = c.groupby(["Branch", "Date"]).agg(Chats=("Minutes", "size"),
                                                    Fast=("Minutes", lambda m: (m <= FAST_REPLY_MIN).sum()))
        for (person, loc) in t.index:
            days = online.loc[online["Person"] == person, "Date"]
            rows = per_day[per_day.index.isin([(loc, d) for d in days])]
            if rows["Chats"].sum():
                fast[(person, loc)] = rows["Fast"].sum() / rows["Chats"].sum() * 100
    t["Answered in 3 min %"] = fast.round(1)
    t["Respond Fast Score"] = t["Answered in 3 min %"]

    # Service: the staff-assistance rating on the feedback forms credited to
    # their sales (scorecards.match_feedback — by phone, name or till time).
    if "Feedback Rating" in served:
        service = served.groupby(keys)["Feedback Rating"].mean().reindex(t.index)
    else:
        service = pd.Series(np.nan, index=t.index)
    t["Service Rating"] = service.round(2)
    t["Customer Service Score"] = t["Service Rating"] / 5 * 100

    t["Customer Feedback Score"] = t["Feedback of Target %"]

    captured = served["Customer"].notna() & ~served["Customer"].astype(str).str.startswith("partner:")
    t["Captured %"] = (served.assign(Captured=captured).groupby(keys)["Captured"].mean() * 100
                       ).reindex(t.index).round(1)
    t["Customer Capture Score"] = t["Captured %"]

    t["Training Score"] = t["Training %"]

    att = pd.Series(np.nan, index=t.index)
    if attendance is not None and not attendance.empty:
        a = attendance.copy()
        present = a["State"].str.lower().eq("present")
        check_in = pd.to_datetime(a["Check In"])
        hours = check_in.dt.hour + check_in.dt.minute / 60
        due = pd.to_numeric(a["Shift Start"], errors="coerce") + pd.to_numeric(a["Grace"], errors="coerce").fillna(0) / 60
        late = present & due.notna() & (hours > due)
        a["Point"] = np.where(present & ~late, 1.0, np.where(late, 0.5, 0.0))
        per_person = a.groupby("Person")["Point"].mean() * 100
        att = pd.Series([per_person.get(p) for p, _ in t.index], index=t.index, dtype=float)
    t["Attendance %"] = att.round(1)
    t["Attendance Score"] = t["Attendance %"]

    t = weighted(t, ATTENDANT_MEASURES)
    return t.reset_index().sort_values("Weighted Score", ascending=False)


def measure_table(measures: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame([(m, w, how) for m, w, how in measures], columns=["Measure", "Weight %", "Scored as"])
