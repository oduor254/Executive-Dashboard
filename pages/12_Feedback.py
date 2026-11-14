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
        ("Best Location", *_best_location(df)),
    ]
    for col, (label, value, note) in zip(st.columns(len(tiles)), tiles):
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
            pinned_columns=("Submitted",), height=420, total=False)

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


render_feedback(feedback, start_date, end_date, location)
