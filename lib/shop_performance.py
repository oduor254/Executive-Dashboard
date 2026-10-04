"""Shop performance: per-location metrics by week or month, comparisons, and a
data-driven improvement plan.

The raw counts come from queries.SHOP_PERFORMANCE (revenue, orders, bags,
customers, new customers, refunds). Everything else here is derived from those,
so every figure on the page traces back to the same definitions as the Sales,
Product Sales and Customers pages.

The improvement plan is generated, not written by hand: each location is
compared with its own previous period, the same period last year, its sales
target, and the typical (median) shop in the same period. Where it trails one
of those clearly enough to matter, the plan says so and suggests what to do.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd

# Locations that are not shops: kept out of the league table and benchmarks.
NOT_SHOPS = {"Staff POS", "Corporate", "Marketing", "N/A"}

# Fewer sales than this in a period and the ratios swing too much to judge.
MIN_ORDERS = 20

METRICS = {
    # name: (format, higher_is_better)
    "Revenue": ("kes", True),
    "Orders": ("int", True),
    "Bags": ("int", True),
    "Customers": ("int", True),
    "New Customers": ("int", True),
    "Returning Customers": ("int", True),
    "Returning %": ("pct", True),
    "Avg Order Value": ("kes", True),
    "Bags per Order": ("dec", True),
    "Avg Price per Bag": ("kes", True),
    "Refund Rate %": ("pct", False),
    "% of Target": ("pct", True),
}


def derive(df: pd.DataFrame, targets: pd.DataFrame | None = None) -> pd.DataFrame:
    """Add the ratio metrics (and target attainment) to raw period rows."""
    out = df.copy()
    out["Period"] = pd.to_datetime(out["Period"])
    orders = out["Orders"].where(out["Orders"] > 0)
    bags = out["Bags"].where(out["Bags"] > 0)
    customers = out["Customers"].where(out["Customers"] > 0)
    out["Returning Customers"] = (out["Customers"] - out["New Customers"]).clip(lower=0)
    out["Returning %"] = out["Returning Customers"] / customers * 100
    out["Avg Order Value"] = out["Revenue"] / orders
    out["Bags per Order"] = out["Bags"] / orders
    out["Avg Price per Bag"] = out["Revenue"] / bags
    gross = (out["Revenue"] + out["Refunded"]).where(lambda s: s > 0)
    out["Refund Rate %"] = out["Refunded"] / gross * 100
    if targets is not None and not targets.empty:
        t = targets.copy()
        t["Period"] = pd.to_datetime(t["Period"])
        out = out.merge(t, on=["Location", "Period"], how="left")
        out["% of Target"] = out["Revenue"] / out["Target"].where(out["Target"] > 0) * 100
    else:
        out["Target"] = float("nan")
        out["% of Target"] = float("nan")
    return out


def network(df: pd.DataFrame) -> pd.DataFrame:
    """All shops added together, one row per period, as location "All Locations"."""
    shops = df[~df["Location"].isin(NOT_SHOPS)]
    summed = (shops.groupby("Period", as_index=False)
              [["Revenue", "Orders", "Bags", "Customers", "New Customers", "Refunded", "Target"]]
              .sum(min_count=1))
    summed["Location"] = "All Locations"
    return derive(summed.drop(columns="Target"),
                  summed[["Location", "Period", "Target"]].dropna())


def period_label(start: pd.Timestamp, grain: str, today: date) -> str:
    start = pd.Timestamp(start)
    if grain == "week":
        end = start + timedelta(days=6)
        label = f"Week of {start:%d %b %Y}"
    else:
        end = start + pd.offsets.MonthEnd(0)
        label = f"{start:%B %Y}"
    return label + (" (to date)" if end.date() >= today else "")


def previous(start: pd.Timestamp, grain: str) -> pd.Timestamp:
    return start - (timedelta(days=7) if grain == "week" else pd.DateOffset(months=1))


def last_year(start: pd.Timestamp, grain: str) -> pd.Timestamp:
    # The same weekday 52 weeks back for weeks, the same month for months.
    return start - (timedelta(days=364) if grain == "week" else pd.DateOffset(years=1))


def elapsed_share(start: pd.Timestamp, grain: str, today: date) -> float:
    """How much of the period has passed — 1.0 for a finished one."""
    start = pd.Timestamp(start).date()
    days = 7 if grain == "week" else calendar.monthrange(start.year, start.month)[1]
    end = start + timedelta(days=days - 1)
    if today > end:
        return 1.0
    return max((today - start).days + 1, 1) / days


def change(now, before) -> float | None:
    if before is None or pd.isna(before) or before == 0 or now is None or pd.isna(now):
        return None
    return (now - before) / abs(before) * 100


def fmt(value, kind: str) -> str:
    if value is None or pd.isna(value):
        return "—"
    if kind == "kes":
        return f"KES {value:,.0f}"
    if kind == "pct":
        return f"{value:.1f}%"
    if kind == "dec":
        return f"{value:.2f}"
    return f"{value:,.0f}"


def improvement_plan(row: pd.Series, prev: pd.Series | None, ly: pd.Series | None,
                     benchmark: pd.Series, share: float) -> list[dict]:
    """Findings for one location in one period, most urgent first.

    benchmark: the median shop for the same period. share: how much of the
    period has elapsed, so a month-to-date figure is judged against its pace
    rather than against a full month.
    """
    plan: list[dict] = []

    def add(priority, area, finding, action, goal):
        plan.append({"Priority": priority, "Area": area, "What the numbers show": finding,
                     "Suggested action": action, "Aim for": goal})

    if row["Orders"] < MIN_ORDERS:
        add("Note", "Data", f"Only {int(row['Orders'])} sales in this period.",
            "Read the comparisons below with care — a handful of sales swings every ratio.",
            "—")

    # Target pace
    if pd.notna(row.get("% of Target")):
        pct, expected = row["% of Target"], share * 100
        if pct < expected * 0.9:
            gap = row["Target"] - row["Revenue"]
            if share < 1:
                add("High", "Target",
                    f"At {pct:.0f}% of target with {expected:.0f}% of the period gone "
                    f"(KES {gap:,.0f} still to make).",
                    "Set daily targets per attendant, push this period's deals at the counter, "
                    "and follow up recent enquiries by phone.",
                    f"KES {gap:,.0f} more before the period ends")
            else:
                add("High", "Target", f"Finished at {pct:.0f}% of target, KES {gap:,.0f} short.",
                    "Review what held sales back (stock gaps, staffing, footfall) before setting "
                    "the next target.", "100% of next period's target")

    # Revenue trend
    yoy = change(row["Revenue"], ly["Revenue"] if ly is not None else None)
    if yoy is not None and yoy < -10 and share == 1:
        add("High", "Revenue",
            f"Revenue {abs(yoy):.0f}% below the same period last year "
            f"(KES {row['Revenue']:,.0f} vs KES {ly['Revenue']:,.0f}).",
            "Compare last year's best sellers with today's stock and deals; restock what sold "
            "then and is missing now.", f"Back to KES {ly['Revenue']:,.0f}")
    pop = change(row["Revenue"], prev["Revenue"] if prev is not None else None)
    if pop is not None and pop < -15 and share == 1:
        add("Medium", "Revenue", f"Revenue {abs(pop):.0f}% down on the previous period.",
            "Check for stock-outs and staffing gaps in the period; confirm deals were on display.",
            f"KES {prev['Revenue']:,.0f} or better")

    def below(metric, ratio):
        v, b = row.get(metric), benchmark.get(metric)
        return pd.notna(v) and pd.notna(b) and b > 0 and v < b * ratio

    if below("Avg Order Value", 0.9):
        add("Medium", "Basket value",
            f"Average order KES {row['Avg Order Value']:,.0f} against KES "
            f"{benchmark['Avg Order Value']:,.0f} at the typical shop.",
            "Lead with combos and the higher-priced bags; offer the matching second item at the "
            "counter.", f"KES {benchmark['Avg Order Value']:,.0f} per order")
    if below("Bags per Order", 0.95):
        add("Medium", "Bags per order",
            f"{row['Bags per Order']:.2f} bags per order against {benchmark['Bags per Order']:.2f} "
            "at the typical shop.",
            "Suggest a second bag on every sale — combos, gift bags, the Deal of the Week bag.",
            f"{benchmark['Bags per Order']:.2f} bags per order")
    if (pd.notna(row.get("Returning %")) and pd.notna(benchmark.get("Returning %"))
            and row["Returning %"] < benchmark["Returning %"] - 5):
        add("Medium", "Repeat customers",
            f"{row['Returning %']:.0f}% of customers are returning, against "
            f"{benchmark['Returning %']:.0f}% at the typical shop.",
            "Follow up past buyers (WhatsApp Monitor follow-ups, Social DM call lists), capture a "
            "phone number on every sale, and ask for feedback so the discount brings them back.",
            f"{benchmark['Returning %']:.0f}% returning")
    new_change = change(row["New Customers"], prev["New Customers"] if prev is not None else None)
    if new_change is not None and new_change < -15 and share == 1:
        add("Medium", "New customers", f"{abs(new_change):.0f}% fewer new customers than the previous period.",
            "Ask marketing for local ads and posters for this shop; check the shop front and deal "
            "posters are visible.", f"{int(prev['New Customers'])} new customers")
    rr, rb = row.get("Refund Rate %"), benchmark.get("Refund Rate %")
    if pd.notna(rr) and rr > max(2.0, (rb if pd.notna(rb) else 0) * 1.5):
        add("High", "Refunds", f"{rr:.1f}% of sales refunded, against {rb:.1f}% at the typical shop.",
            "Inspect the returned bags for a quality pattern, and check customers see the bag "
            "properly before paying.", f"Under {max(rb, 1.0):.1f}%")
    if below("Avg Price per Bag", 0.9):
        add("Low", "Pricing mix",
            f"Average KES {row['Avg Price per Bag']:,.0f} per bag against KES "
            f"{benchmark['Avg Price per Bag']:,.0f} at the typical shop.",
            "Check whether sales lean on deals and low-priced bags; make sure full-price bags are "
            "on show too.", f"KES {benchmark['Avg Price per Bag']:,.0f} per bag")

    strengths = [m for m, (_, up) in METRICS.items()
                 if m in ("Avg Order Value", "Bags per Order", "Returning %", "Customers")
                 and pd.notna(row.get(m)) and pd.notna(benchmark.get(m)) and benchmark[m] > 0
                 and row[m] >= benchmark[m] * 1.1]
    if strengths:
        add("Strength", "Keep doing", "Ahead of the typical shop on " + ", ".join(strengths) + ".",
            "Share what this team does with the other shops.", "—")
    if not [p for p in plan if p["Priority"] in ("High", "Medium", "Low")]:
        add("On track", "Overall", "No metric is clearly behind its target, last year or the typical shop.",
            "Keep the current routine; watch the trend charts for early slips.", "—")

    order = {"High": 0, "Medium": 1, "Low": 2, "Note": 3, "Strength": 4, "On track": 5}
    return sorted(plan, key=lambda p: order[p["Priority"]])
