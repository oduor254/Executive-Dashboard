"""Feedback — what customers said on the feedback forms, as the CRM module's
Feedback page holds it: complaints, appraisals (compliments) and ratings, by
location and by attendant."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from lib import auth, db, filters, grid, queries

st.set_page_config(page_title=auth.page_title("Feedback"), page_icon="💬", layout="wide")

auth.require_login()

st.title("💬 Feedback")
st.caption("Customer feedback from the CRM module's Feedback page — live from Postgres. "
           "Weeks run Sunday to Saturday.")

connected, detail = db.check_connection()
if not connected:
    st.error(f"Could not connect to Postgres: {detail}", icon="🚫")
    st.stop()

col_picker, col_location, col_refresh = st.columns([2, 1, 1])
with col_picker:
    start_date, end_date = filters.date_range_control("feedback", default="This Week")
feedback = db.run_query(queries.CRM_FEEDBACK, {"start_date": start_date, "end_date": end_date})
with col_location:
    location = st.selectbox("Location", ["All Locations"] + sorted(feedback["Location"].unique()),
                            key="feedback_location")
with col_refresh:
    db.refresh_button(key="feedback_refresh")

BEST_MIN_FEEDBACKS = 5   # fewer than this and one 5-star form would top the list
FEEDBACK_TARGET = 0.30   # share of a location's customers expected to leave feedback
TOP_MIN_CUSTOMERS = 10   # fewer than this and two forms would make a location the best

# Every column a keyword is looked for in.
SEARCHED = ["Feedback", "Customer", "Phone", "Location", "Bag Purchased", "Attendant", "Order",
            "Resolution"]


def _summary(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Counts and average ratings per group, most feedback first."""
    g = df.groupby(by)
    t = pd.DataFrame({
        "Feedbacks": g.size(),
        "Appraisals": g["Type"].agg(lambda s: (s == "Appraisal").sum()),
        "Complaints": g["Type"].agg(lambda s: (s == "Complaint").sum()),
        "Other Feedback": g["Type"].agg(lambda s: (s == "Feedback").sum()),
        "Avg. Rating": g["Rating"].mean().round(2),
        "Avg. Staff Rating": g["Staff Rating"].mean().round(2),
    })
    return t.sort_values("Feedbacks", ascending=False).reset_index()


def _best_location(df: pd.DataFrame) -> tuple[str, str]:
    """(location with the highest average rating, "its feedback count · rating").
    Locations with fewer than BEST_MIN_FEEDBACKS rated feedbacks are left out
    unless none has that many; a tie goes to the one with more feedbacks."""
    t = df.groupby("Location")["Rating"].agg(["count", "mean"]).dropna()
    if t.empty:
        return "—", "no rated feedback"
    enough = t[t["count"] >= BEST_MIN_FEEDBACKS]
    best = (enough if not enough.empty else t).sort_values(["mean", "count"], ascending=False).iloc[0]
    received = (df["Location"] == best.name).sum()
    return best.name, f"{received:,} feedbacks · avg rating {best['mean']:.2f} / 5"


def _busiest_location(df: pd.DataFrame) -> tuple[str, str]:
    """(location with the most feedback, "its feedback count · rating")."""
    name = df["Location"].value_counts().index[0]
    mine = df[df["Location"] == name]
    rating = f"avg rating {mine['Rating'].mean():.2f} / 5" if mine["Rating"].notna().any() else "not rated"
    return name, f"{len(mine):,} feedbacks · {rating}"


@st.fragment()
def render_feedback(df: pd.DataFrame, start_date: date, end_date: date, location: str) -> None:
    if location != "All Locations":
        df = df[df["Location"] == location]
    if df.empty:
        st.info("No feedback was submitted in this date range.")
        return

    complaints = df[df["Type"] == "Complaint"]
    appraisals = df[df["Type"] == "Appraisal"]
    still_open = (complaints["Status"] == "Open").sum()
    tiles = [
        ("Total Feedbacks", f"{len(df):,}", f"{start_date:%a %d %b} – {end_date:%a %d %b %Y}"),
        ("Complaints", f"{len(complaints):,}",
         f"{len(complaints) / len(df) * 100:.1f}% of feedback · {still_open:,} still open"),
        ("Appraisals", f"{len(appraisals):,}", f"{len(appraisals) / len(df) * 100:.1f}% of feedback"),
        ("Avg. Rating", f"{df['Rating'].mean():.2f} / 5" if df["Rating"].notna().any() else "—",
         f"staff {df['Staff Rating'].mean():.2f} / 5" if df["Staff Rating"].notna().any() else None),
        ("Best Rated Location", *_best_location(df)),
        ("Most Feedback", *_busiest_location(df)),
    ]
    for row in (tiles[:3], tiles[3:]):
        for col, (label, value, note) in zip(st.columns(3), row):
            with col.container(border=True):
                st.metric(label, value, note, delta_color="off")

    # ------------------------------------------------------------ search ---
    st.subheader("Search feedback")
    keyword = st.text_input(
        "Keyword", key="feedback_keyword", label_visibility="collapsed",
        placeholder="Search any keyword: a bag, a complaint, a customer, an attendant, a phone number...")
    found = df
    for word in keyword.split():   # every word must appear somewhere in the row
        found = found[found[SEARCHED].fillna("").astype(str)
                      .apply(lambda c: c.str.contains(word, case=False, regex=False)).any(axis=1)]
    if keyword.strip():
        st.caption(f"{len(found):,} of {len(df):,} feedbacks mention “{keyword.strip()}”: "
                   f"{(found['Type'] == 'Complaint').sum():,} complaints, "
                   f"{(found['Type'] == 'Appraisal').sum():,} appraisals"
                   + (f", average rating {found['Rating'].mean():.2f}" if found["Rating"].notna().any() else "")
                   + ".")
    if found.empty:
        st.info("No feedback in this period mentions that.")
    else:
        grid.filterable_table(   # as text, or the grid shows the date without the time
            found.assign(Submitted=found["Submitted"].dt.strftime("%Y-%m-%d %H:%M"))[["Submitted", "Customer", "Phone", "Location", "Type", "Rating", "Staff Rating",
                 "Feedback", "Bag Purchased", "Attendant", "Order", "Status", "Resolution"]],
            pinned_columns=("Submitted",), height=420, total=False,
            tooltip_columns=("Feedback", "Bag Purchased", "Resolution"))

    # ------------------------------------------------------- by location ---
    left, right = st.columns(2)
    with left:
        st.subheader("Feedback by location")
        grid.filterable_table(_summary(df, ["Location"]), pinned_columns=("Location",), height=460)
    with right:
        st.subheader("Staff appraisals")
        staffed = df[df["Attendant"].notna()]
        if staffed.empty:
            st.info("No feedback in this period is linked to an attendant.")
        else:
            staff = (_summary(staffed, ["Attendant", "Location"])
                     .sort_values(["Appraisals", "Avg. Staff Rating"], ascending=False))
            grid.filterable_table(
                staff[["Attendant", "Location", "Appraisals", "Complaints", "Feedbacks",
                       "Avg. Staff Rating", "Avg. Rating"]],
                pinned_columns=("Attendant",), height=460)
        st.caption(f"{len(staffed):,} of {len(df):,} feedbacks are linked to the attendant who "
                   "served the customer; the rest couldn't be matched to a sale.")


@st.fragment()
def render_targets(df: pd.DataFrame, start_date: date, end_date: date, location: str) -> None:
    """Feedback received against the customers served, per location: 30% of
    customers are expected to leave feedback."""
    st.divider()
    st.header("🎯 Feedback Target Performance")
    customers = db.run_query(queries.SHOP_ATTENDANT_CUSTOMERS,
                             {"start_date": start_date, "end_date": end_date})
    # The shops spell a few names differently from the CRM (Ktda / KTDA); tills
    # that aren't a feedback branch (Staff POS) are left out.
    branches = {b.lower(): b for b in db.run_query("SELECT name FROM denri_crm_branch")["name"]}
    customers = customers.assign(
        Location=customers["Location"].str.lower().map(branches),
        Key=customers["Phone Key"].fillna("name:" + customers["Customer"])).dropna(subset=["Location"])
    t = pd.concat([customers.groupby("Location")["Key"].nunique().rename("Customers"),
                   df.groupby("Location").size().rename("Feedbacks")], axis=1).fillna(0)
    if location != "All Locations":
        t = t[t.index == location]
    if t.empty or not t["Customers"].sum():
        st.info("No customers were served in this date range.")
        return

    t["Target"] = (t["Customers"] * FEEDBACK_TARGET).round()
    t["Feedback %"] = (t["Feedbacks"] / t["Customers"].where(t["Customers"] > 0) * 100).round(1)
    t["Target Achieved %"] = (t["Feedbacks"] / t["Target"].where(t["Target"] > 0) * 100).round(1)
    t["Short of Target"] = (t["Target"] - t["Feedbacks"]).clip(lower=0)
    t["Status"] = (t["Feedback %"] >= FEEDBACK_TARGET * 100).map({True: "Target met", False: "Below target"})
    t = t.reset_index(names="Location").sort_values("Feedback %", ascending=False)

    served = t[t["Customers"] > 0]
    customers_n, received = served["Customers"].sum(), served["Feedbacks"].sum()
    rate = received / customers_n * 100
    enough = served[served["Customers"] >= TOP_MIN_CUSTOMERS]
    top = (enough if not enough.empty else served).iloc[0]
    target = round(customers_n * FEEDBACK_TARGET)
    tiles = [
        ("Customers", f"{customers_n:,.0f}", f"{start_date:%a %d %b} – {end_date:%a %d %b %Y}"),
        (f"Feedback Target ({FEEDBACK_TARGET:.0%})", f"{target:,}", "feedbacks expected"),
        ("Feedbacks Received", f"{received:,.0f}",
         f"{max(target - received, 0):,.0f} short of target" if received < target else "target met"),
        ("Feedback % of Customers", f"{rate:.1f}%",
         f"{received / target * 100:.0f}% of the {FEEDBACK_TARGET:.0%} target" if target else None),
        ("Top Location", top["Location"],
         f"{top['Feedback %']:.1f}% · {top['Feedbacks']:,.0f} feedbacks from {top['Customers']:,.0f} customers"),
        ("Locations on Target", f"{(served['Feedback %'] >= FEEDBACK_TARGET * 100).sum()} of {len(served)}",
         f"at or above {FEEDBACK_TARGET:.0%}"),
    ]
    for row in (tiles[:3], tiles[3:]):
        for col, (label, value, note) in zip(st.columns(3), row):
            with col.container(border=True):
                st.metric(label, value, note, delta_color="off")

    st.subheader("Feedback target by location")
    grid.filterable_table(
        t[["Location", "Customers", "Target", "Feedbacks", "Feedback %", "Target Achieved %",
           "Short of Target", "Status"]], pinned_columns=("Location",), height=560)
    st.caption(
        f"Customers are the distinct people who bought at the location in the period; the target is "
        f"{FEEDBACK_TARGET:.0%} of them. Feedback % is the feedbacks received at the location over "
        "its customers: the two are counted separately, not matched person by person. Feedback with "
        "no location recorded has no customers to set it against.")


render_feedback(feedback, start_date, end_date, location)
render_targets(feedback, start_date, end_date, location)
