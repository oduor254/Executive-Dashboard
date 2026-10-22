"""Shop attendants: achievement against individual targets, and the
downloadable report (Excel and Word) of the Shop Attendants page.

Individual target — each shop's revenue target for the period, shared
equally between the attendants and BAs who served there in it (the same rule
as the score cards). Someone who served at two shops carries a share of each.
Achievement is the person's own sales (Sales Made) against that target, and
pace compares it with the share of the target due by now.
"""
from __future__ import annotations

import io
from datetime import date, datetime

import numpy as np
import pandas as pd

NOT_RECORDED = "Not recorded"


def achievement(sessions: pd.DataFrame, served_by: pd.Series,
                day_targets: pd.DataFrame) -> pd.DataFrame:
    """One row per attendant/BA: sales, individual target, achievement %.

    The individual target is, for every day the person was on the floor,
    their shop's daily target split equally between everyone who served
    there that day — the score cards' rule (lib.scorecards.person_days)."""
    from lib import scorecards
    everyone = sessions.assign(**{"Served By": served_by})
    df = everyone[everyone["Served By"] != NOT_RECORDED]
    if df.empty:
        return pd.DataFrame()
    worked = scorecards.person_days(everyone, day_targets)
    target = worked.groupby("Served By")["Person Target"].sum(min_count=1)
    g = df.groupby("Served By")
    out = pd.DataFrame({
        "Locations": g["Location"].agg(lambda v: ", ".join(sorted(set(v)))),
        "Sessions": g["Session"].nunique(),
        "Orders": g["Orders"].sum(),
        "Sales Made": g["Sales Made"].sum().round(2),
        "Individual Target": target.round(0),
    })
    out["Achievement %"] = (out["Sales Made"] / out["Individual Target"]
                            .where(out["Individual Target"] > 0) * 100).round(1)
    out = out.reset_index().rename(columns={"Served By": "Shop Attendant / BA"})
    out.insert(0, "Rank", out["Achievement %"].rank(ascending=False, method="min")
               .astype("Int64"))
    return out.sort_values(["Achievement %", "Sales Made"], ascending=[False, False],
                           na_position="last")


# ------------------------------------------------------------------ export ---

def _sheet_name(name: str) -> str:
    return "".join(ch for ch in name if ch not in '[]:*?/\\')[:31]


def to_xlsx(title: str, summary: list[tuple[str, str]], tables: dict[str, pd.DataFrame]) -> bytes:
    """One summary sheet, then one sheet per table, columns sized to fit."""
    from openpyxl.styles import Font

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(summary, columns=["Measure", "Value"]).to_excel(
            writer, sheet_name="Summary", index=False, startrow=2)
        ws = writer.sheets["Summary"]
        ws["A1"] = title
        ws["A1"].font = Font(bold=True, size=14)
        for name, table in tables.items():
            if table is None or table.empty:
                continue
            table.to_excel(writer, sheet_name=_sheet_name(name), index=False)
        for ws in writer.book.worksheets:
            for cell in ws[3 if ws.title == "Summary" else 1]:
                cell.font = Font(bold=True)
            for column in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in column)
                ws.column_dimensions[column[0].column_letter].width = min(max(width + 2, 10), 45)
            ws.freeze_panes = "A4" if ws.title == "Summary" else "B2"
    return buffer.getvalue()


def _fmt(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)) or value is pd.NA:
        return "—"
    if isinstance(value, (float, np.floating)):
        return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.1f}"
    if isinstance(value, (int, np.integer)):
        return f"{value:,}"
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return f"{pd.Timestamp(value):%d %b %Y}"
    return str(value)


def to_docx(title: str, period: str, summary: list[tuple[str, str]],
            tables: dict[str, pd.DataFrame], notes: dict[str, str] | None = None,
            max_rows: int = 60) -> bytes:
    """A Word report: title, period, the summary, then each table."""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm, Pt

    doc = Document()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Cm(1.5))
    doc.styles["Normal"].font.size = Pt(9)

    doc.add_heading(title, level=0)
    doc.add_paragraph(f"{period} · prepared {datetime.now():%d %b %Y %H:%M}")
    doc.add_heading("Summary", level=1)
    table = doc.add_table(rows=0, cols=2)
    table.style = "Light Grid Accent 1"
    for label, value in summary:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = label, value

    for name, frame in tables.items():
        if frame is None or frame.empty:
            continue
        doc.add_heading(name, level=1)
        if notes and notes.get(name):
            doc.add_paragraph(notes[name])
        rows = frame.head(max_rows)
        t = doc.add_table(rows=1, cols=len(rows.columns))
        t.style = "Light Grid Accent 1"
        for cell, col in zip(t.rows[0].cells, rows.columns):
            cell.text = str(col)
        for _, r in rows.iterrows():
            cells = t.add_row().cells
            for cell, value in zip(cells, r.tolist()):
                cell.text = _fmt(value)
        if len(frame) > max_rows:
            doc.add_paragraph(f"First {max_rows} of {len(frame):,} rows — the Excel report has them all.")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
