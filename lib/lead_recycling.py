"""Lead recycling: customers who reached out and didn't buy, worked again.

The pool is every customer with an unconverted touch in the window — a
WhatsApp chat that ended as an enquiry, a visit-shop promise or not
purchased; a social DM that didn't convert; a walk-in lead that isn't
Purchased. One row per customer, matched on the last nine digits of their
phone, so someone who messaged three times is recycled once.

Each customer is in exactly one recycle status, checked in this order:

  Recovered         bought a bag (any shop, the website) on or after their
                    first unconverted touch, or a later touch converted
  Do Not Recycle    the lead was marked wrong number or not interested
  Fresh             last touched under `recycle_after` days ago — still
                    with the team that took it
  Scheduled         a call-back date still to come (Social DMs' next call,
                    the Leads module's follow-up date)
  Nurture Only      `max_attempts` follow-ups already, no sale — offers and
                    broadcasts only, no more calls
  Ready to Recycle  everyone else: due a fresh follow-up now

Customers with no usable phone can't be recycled and are counted apart.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from lib import stock_planning

WHATSAPP, SOCIAL, WALKIN = "WhatsApp", "Social DMs", "Walk-in Leads"
CHANNELS = [WHATSAPP, SOCIAL, WALKIN]

RECOVERED, DO_NOT, FRESH = "Recovered", "Do Not Recycle", "Fresh"
SCHEDULED, NURTURE, READY = "Scheduled", "Nurture Only", "Ready to Recycle"
STATUSES = [READY, SCHEDULED, FRESH, NURTURE, RECOVERED, DO_NOT]

DEAD_STATUSES = {"Wrong Number", "Not Interested"}
# Lead statuses that mean somebody has already spoken to the customer.
CONTACTED_STATUSES = {"Awaiting Reply", "Follow Up Later", "Will Visit Shop", "Awaiting Stock",
                      "Awaiting Offer", "Not Reachable"}
OPEN_LEAD_STAGES = {"Working", "Waiting on Stock/Offer", "New", "No Status"}

# Why the customer didn't buy, as the latest touch records it, and what to do
# about it now. Higher weight = call first.
_PLAYBOOK = {
    "Out of Stock":   (5, "Stock is back — tell them it's in and where"),
    "Awaiting Stock": (5, "Stock is back — tell them it's in and where"),
    "Purchase Later": (4, "Reminder call — they said they'd buy; mention this week's deal"),
    "Follow Up Later": (4, "Reminder call — they said they'd buy; mention this week's deal"),
    "Visit Shop":     (4, "Invite them in — nearest shop and what's in stock for them"),
    "Visit the Shop": (4, "Invite them in — nearest shop and what's in stock for them"),
    "Will Visit Shop": (4, "Invite them in — nearest shop and what's in stock for them"),
    "Awaiting Offer": (3, "Send the current Power Deal / Deal of the Week"),
    "Not Purchased":  (3, "Ask what stopped them; offer an alternative or a deal"),
    "Enquiries":      (2, "Answer the open question, then send a deal"),
    "Enquiry":        (2, "Answer the open question, then send a deal"),
    "Awaiting Reply": (2, "Nudge on WhatsApp — they haven't replied"),
    "Not Reachable":  (1, "Try a different time, or WhatsApp / SMS instead of a call"),
}
_DEFAULT_PLAY = (2, "Call back — find out what they need")
STOCK_PLAY = "Stock is back — tell them it's in and where"
_NO_STOCK_PLAY = "Still out — hold until restocked, or offer a similar bag"


def phone_keys(contacts: pd.Series) -> pd.Series:
    """The last nine digits of each phone, or None when it has fewer."""
    digits = contacts.fillna("").astype(str).str.replace(r"\D", "", regex=True)
    return digits.str[-9:].where(digits.str.len() >= 9)


# The WhatsApp Monitor's codes, named as the rest of the page names them.
_WA_ACTIVITY = {"enquiry": "Enquiry", "purchased": "Purchased", "not_purchased": "Not Purchased",
                "visit_shop": "Visit Shop", "transferred": "Transferred", "walk_in": "Walk-in"}
_WA_FOLLOWUP = {"already_purchased": "Already Purchased", "enquiry": "Enquiries",
                "out_of_stock": "Out of Stock", "purchase_later": "Purchase Later",
                "purchased": "Purchased", "visit_shop": "Visit the Shop",
                "not_reachable": "Not Reachable"}


def touches(wa: pd.DataFrame, wa_names: pd.DataFrame, wa_wanted: pd.DataFrame,
            dms: pd.DataFrame, leads: pd.DataFrame) -> pd.DataFrame:
    """Every touch in the window, all three apps in one shape. `wa` is
    RECYCLE_WA_TOUCHES; `wa_names` the Odoo contact names by phone, for chats
    that recorded none."""
    frames = []
    if not wa.empty:
        wanted = (wa_wanted.groupby("ID")["Product Wanted"].first()
                  if not wa_wanted.empty else pd.Series(dtype=object))
        names = (wa_names.set_index("Phone Key")["Partner Name"] if not wa_names.empty
                 else pd.Series(dtype=object))
        follow = wa["Follow-up Outcome"].map(_WA_FOLLOWUP)
        activity = wa["Activity"].map(_WA_ACTIVITY).fillna(wa["Activity"]).fillna("Not recorded")
        frames.append(pd.DataFrame({
            "Channel": WHATSAPP, "Date": wa["Date"],
            "Name": wa["Name"].fillna(phone_keys(wa["Contact"]).map(names)),
            "Contact": wa["Contact"], "Branch": wa["Branch"], "Source": wa["Source"],
            "Converted": wa["Converted"].fillna(False).astype(bool),
            "Reason": np.where(wa["Out of Stock"], "Out of Stock", activity),
            "Wanted": wa["ID"].map(wanted), "Follow-up": follow,
            "Followed Up On": wa["Followed Up On"].where(follow.notna()),
            "Attempts": follow.notna().astype(int),
            "Call Due": None, "Lead Status": None}))
    if not dms.empty:
        awaiting = dms["Call Status"].isin(["Awaiting Call 1", "Awaiting Call 2"])
        frames.append(pd.DataFrame({
            "Channel": SOCIAL, "Date": dms["Date"], "Name": dms["Name"], "Contact": dms["Contact"],
            "Branch": dms["Branch"], "Source": dms["Platform"], "Converted": dms["Converted"],
            "Reason": dms["Shop Outcome"].fillna("Enquiry"), "Wanted": dms["Product Interested In"],
            "Follow-up": dms["Call Status"], "Followed Up On": None,
            "Attempts": dms["Call Status"].map({"Awaiting Call 2": 1, "Follow-up closed": 2}).fillna(0).astype(int),
            "Call Due": dms["Next Call Due"].where(awaiting), "Lead Status": None}))
    if not leads.empty:
        open_ = leads["Stage"].isin(OPEN_LEAD_STAGES)
        frames.append(pd.DataFrame({
            "Channel": WALKIN, "Date": leads["Date"], "Name": leads["Name"], "Contact": leads["Contact"],
            "Branch": leads["Branch"], "Source": leads["Contact Method"], "Converted": leads["Converted"],
            "Reason": leads["Status"], "Wanted": leads["Bag Wanted"].replace("Not recorded", None),
            "Follow-up": leads["Status"], "Followed Up On": None,
            "Attempts": leads["Status"].isin(CONTACTED_STATUSES).astype(int),
            "Call Due": leads["Follow-up Date"].where(open_), "Lead Status": leads["Status"]}))
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    t = pd.concat(frames, ignore_index=True)
    t["Date"] = pd.to_datetime(t["Date"])
    t["Converted"] = t["Converted"].fillna(False).astype(bool)
    t["Phone Key"] = phone_keys(t["Contact"])
    return t


def customers(t: pd.DataFrame, purchases: pd.DataFrame, stock: pd.Series, *, today: date,
              recycle_after: int, max_attempts: int) -> pd.DataFrame:
    """One row per unconverted customer with a phone: where they came from,
    why they didn't buy, what has been tried, and their recycle status."""
    no_phone = int((~t["Converted"] & t["Phone Key"].isna()).sum())
    t = t[t["Phone Key"].notna()].sort_values("Date")
    lost = t[~t["Converted"]]
    if lost.empty:
        return pd.DataFrame()
    first = lost.groupby("Phone Key")["Date"].min()
    t = t[t["Phone Key"].isin(first.index)]
    g = t.groupby("Phone Key")
    last_lost = lost.groupby("Phone Key").tail(1).set_index("Phone Key")

    c = pd.DataFrame({"First Unconverted": first})
    c = c.join(last_lost[["Name", "Contact", "Channel", "Branch", "Source", "Reason", "Wanted", "Follow-up"]])
    # .last() skips blanks: the latest name / bag anyone recorded.
    c["Name"] = g["Name"].last().fillna("Unknown")
    c["Wanted"] = lost.groupby("Phone Key")["Wanted"].last()
    c["Touches"] = g.size()
    seen = pd.crosstab(t["Phone Key"], t["Channel"]).reindex(columns=CHANNELS, fill_value=0) > 0
    c["Channels"] = seen.apply(lambda col: np.where(col, col.name + ", ", "")).sum(axis=1).str[:-2]
    c["Attempts"] = g["Attempts"].sum()
    follow_on = pd.to_datetime(t["Followed Up On"])
    c["First Follow-up"] = follow_on.groupby(t["Phone Key"]).min()
    c["Last Follow-up"] = follow_on.groupby(t["Phone Key"]).max()
    c["Last Touch"] = pd.concat([g["Date"].max(), c["Last Follow-up"]], axis=1).max(axis=1)
    c["Call Due"] = pd.to_datetime(t["Call Due"]).groupby(t["Phone Key"]).max()
    c["Lead Status"] = t.dropna(subset=["Lead Status"]).groupby("Phone Key")["Lead Status"].last()

    # Converted later in one of the apps, or bought at a till / online.
    later = t[t["Converted"]].merge(first.rename("First"), left_on="Phone Key", right_index=True)
    later = later[later["Date"] >= later["First"]].groupby("Phone Key")["Date"].min()
    c["Bought On"], c["Bought At"], c["Amount"], c["Bags Bought"] = later, None, 0.0, 0
    if not purchases.empty:
        p = purchases.assign(**{"Bought On": pd.to_datetime(purchases["Bought On"])})
        p = p.merge(first.rename("First"), left_on="Phone Key", right_index=True)
        p = p[p["Bought On"] >= p["First"]]
        if not p.empty:
            # The recovery is the first day they bought; what they bought on
            # later visits is repeat business, not the lead coming back.
            day = p.groupby("Phone Key")["Bought On"].transform("min")
            p = p[p["Bought On"] == day]
            c["Bought On"] = pd.concat([c["Bought On"], p.groupby("Phone Key")["Bought On"].min()],
                                       axis=1).min(axis=1)
            c["Bought At"] = p.groupby("Phone Key")["Bought At"].first()
            c["Amount"] = p.groupby("Phone Key")["Amount"].sum().reindex(c.index).fillna(0)
            c["Bags Bought"] = p.groupby("Phone Key")["Bags"].sum().reindex(c.index).fillna(0).astype(int)
    c["Days to Recover"] = (c["Bought On"] - c["First Unconverted"]).dt.days
    # Bought the same day they asked — a chat that ended as an enquiry and a
    # sale a few hours later. Never lost, so not in the pool.
    same_day = c["Days to Recover"] == 0
    c = c[~same_day].copy()
    c["Recovered"] = c["Bought On"].notna()
    c["After Follow-up"] = c["Recovered"] & (c["Attempts"] > 0) & (
        c["First Follow-up"].isna() | (c["First Follow-up"] <= c["Bought On"]))

    now = pd.Timestamp(today)
    c["Days Since Touch"] = (now - c["Last Touch"]).dt.days
    family = c["Wanted"].map(lambda w: stock_planning.family(str(w)) if pd.notna(w) else None)
    c["Bag"] = family
    c["In Stock Now"] = family.map(stock).fillna(0).clip(lower=0).where(family.notna())

    c["Status"] = np.select(
        [c["Recovered"],
         c["Lead Status"].isin(DEAD_STATUSES),
         c["Days Since Touch"] < recycle_after,
         c["Call Due"] >= now,
         c["Attempts"] >= max_attempts],
        [RECOVERED, DO_NOT, FRESH, SCHEDULED, NURTURE], READY)

    key = c["Follow-up"].where(c["Follow-up"].isin(_PLAYBOOK.keys()), c["Reason"])
    play = key.map(lambda k: _PLAYBOOK.get(k, _DEFAULT_PLAY))
    c["Action"] = play.str[1]
    stock_case = c["Action"] == STOCK_PLAY
    c.loc[stock_case & (c["In Stock Now"].fillna(0) <= 0), "Action"] = _NO_STOCK_PLAY
    # Call order: the reason's weight, a bag that's back in stock, then the
    # freshest — a lead goes colder every week it waits.
    c["Priority"] = (play.str[0] * 10 + np.where(stock_case & (c["In Stock Now"] > 0), 5, 0)
                     - np.minimum(c["Days Since Touch"] // 7, 9)).astype(int)
    out = c.reset_index()
    out.attrs["same_day"] = int(same_day.sum())
    out.attrs["no_phone"] = no_phone
    return out


def by_group(c: pd.DataFrame, by: str) -> pd.DataFrame:
    """Recycling scorecard per branch, channel or reason."""
    g = c.groupby(by)
    t = pd.DataFrame({
        "Unconverted Customers": g.size(),
        "Recovered": g["Recovered"].sum(),
        "After Follow-up": g["After Follow-up"].sum(),
        "Value Recovered": g["Amount"].sum(),
        "Ready to Recycle": g["Status"].apply(lambda s: (s == READY).sum()),
        "Scheduled": g["Status"].apply(lambda s: (s == SCHEDULED).sum()),
        "Fresh": g["Status"].apply(lambda s: (s == FRESH).sum()),
        "Nurture Only": g["Status"].apply(lambda s: (s == NURTURE).sum()),
        "Never Followed Up": g.apply(lambda d: ((d["Attempts"] == 0) & ~d["Recovered"]
                                                & (d["Status"] != FRESH)).sum(), include_groups=False),
    })
    t.insert(2, "Recovery %", (t["Recovered"] / t["Unconverted Customers"] * 100).round(1))
    t["Days to Recover"] = g["Days to Recover"].median().round(0)
    return t.reset_index().sort_values("Unconverted Customers", ascending=False)
