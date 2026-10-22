"""The sales performance report as one outline — 1.0 Executive Summary through
9.0 Summary & Key Notes — and its Word and PowerPoint editions.

The Reports page renders the same outline top to bottom, so the dashboard,
the .docx and the .pptx always carry the same sections, tables and notes:

  * Word: a cover with the headline figures, a clickable contents list that
    jumps to each section (and a "Back to contents" link after each one),
    headings that fill Word's navigation pane, tables whose header row repeats
    across pages, charts, and colour-coded flags and notes.
  * PowerPoint: a contents slide whose tiles jump to each section, a
    "Contents" button on every slide to jump back, native charts (hover for
    values, right-click → Edit Data in PowerPoint), and speaker notes carrying
    each section's commentary.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from lib import reports

LOGO = Path(__file__).parent.parent / "assets" / "logo.png"

INK = "1A1A19"
ACCENT = "3987E5"
UP = "0B7A3B"
DOWN = "C62828"
AMBER = "B26A00"
MUTED = "6F6E69"
BAND = "F3F5F8"
RULE = "D9DCE1"
SOFT = {UP: "E8F5EC", DOWN: "FBEAEA", AMBER: "FFF4E0", ACCENT: "EAF2FD", MUTED: "F1F1EF"}
TAGS = {"CRITICAL": DOWN, "RISK": DOWN, "HIGH": AMBER, "MEDIUM": AMBER,
        "WIN": UP, "POSITIVE": UP}
STATUS_COLOURS = {"excellent": UP, "good": UP, "on target": UP, "watch": AMBER,
                  "below target": AMBER, "critical": DOWN}

# Columns a TOTAL row adds up — the dashboard grid's rule, so totals agree.
_NOT_SUMMED = re.compile(r"%|percent|rate|avg|average|price|share|rank|per order|per bag|\bid\b|year|"
                         r"month|week|phone|digits|value$|score|size$|per day|\(min\)", re.I)


# ----------------------------------------------------------------- outline ---

@dataclass
class Block:
    kind: str                       # table | chart | text | flags | notes
    title: str = ""
    frame: pd.DataFrame | None = None
    text: str = ""
    items: list = field(default_factory=list)
    notes: dict = field(default_factory=dict)
    chart: str = ""                 # shops | frequency | gender | conversion | bridge
    money: tuple = ()               # currency columns, for the dashboard grid
    pinned: bool = False            # pin the first (Shop) column on the dashboard
    total: bool = True              # add a TOTAL row


@dataclass
class Section:
    num: int
    title: str
    blocks: list[Block]

    @property
    def heading(self) -> str:
        return f"{self.num}.0 {self.title}"

    @property
    def anchor(self) -> str:
        return f"section-{self.num}"


def outline(r: dict) -> list[Section]:
    p = r["period"]
    fb = r["feedback"]
    kes = lambda df: tuple(c for c in df.columns if "(KES)" in c) if df is not None else ()
    retention_title = ("3.2 Monthly Customer Retention by Location" if p.kind == reports.MONTHLY
                       else "3.2 Customer Retention by Location")

    sections = [
        Section(1, "Executive Summary", [
            Block("table", "Headline figures", r["executive"], total=False),
            Block("flags", "Flags", items=r["flags"]),
            Block("text", text=r["exec_note"]),
        ]),
        Section(2, "Customer Metrics", [
            Block("table", "Customers", r["cust_metrics"], total=False),
            Block("chart", "2.1 Purchase Frequency Distribution", chart="frequency"),
            Block("table", "2.1 Purchase Frequency Distribution", r["frequency"]),
            Block("table", "2.2 Channel Overview", r["channels"], money=("Avg Spend",)),
            Block("text", text=r["cust_note"]),
        ]),
        Section(3, "Store Performance", [
            Block("chart", "Revenue by shop — this period and the last", chart="shops"),
            Block("table", "Revenue by shop", r["stores"], money=("Current", "Previous", "Change"),
                  pinned=True),
            Block("table", "3.1 Channel Mix by Location", r["channel_mix"],
                  money=kes(r["channel_mix"]), pinned=True),
            Block("table", retention_title, r["retention"], money=kes(r["retention"]), pinned=True),
            Block("text", text="Repeat: bought on two or more days in the period. Retention: also "
                               "bought at the shop in the period before."),
        ]),
        Section(4, "Gender Performance Analysis", [
            Block("text", text=f"Female to male ratio: {r['gender_ratio']}."),
            Block("chart", "4.1 Overall Gender Split", chart="gender"),
            Block("table", "4.1 Overall Gender Split", r["gender"]),
            Block("table", "4.2 Gender by Location", r["gender_shop"], pinned=True),
            Block("text", text=r["gender_note"]
                  + (f" {r['gender_unknown']:,} customers have no gender recorded."
                     if r["gender_unknown"] else "")),
        ]),
        Section(5, "Foot & Online Traffic Analysis", [
            Block("text", text="Walk-in Total: walk-ins counted in the Footfall module. Walk-in "
                               "Purchased: walk-in orders on the POS. Conversion = purchased ÷ "
                               "counted; online and activation orders are shown apart."),
            Block("chart", "Walk-in conversion by shop", chart="conversion"),
            Block("table", "Traffic by shop", r["traffic"], pinned=True),
            Block("text", text=r["traffic_note"]),
        ]),
        Section(6, "Revenue Analysis", [
            Block("table", "Revenue", r["revenue_kpis"], total=False),
            Block("chart", "6.1 Revenue Bridge", chart="bridge"),
            Block("table", "6.1 Revenue Bridge",
                  r["bridge"].assign(Period=r["bridge"]["Period"].map(short_period)),
                  money=("Revenue", "Avg Spend"),
                  total=False),
            Block("table", "6.2 Corporate Revenue", r["corporate"], total=False),
            Block("text", text="Corporate revenue is payments received on corporate invoices, "
                               "as Odoo's Sales & POS Dashboard shows them."),
            Block("table", "6.3 Top Corporate Clients", r["corporate_clients"], money=("Revenue",)),
        ]),
        Section(7, "Data Quality (KYC)", [
            Block("table", "Phone number quality", r["quality"], total=False),
            Block("table", "7.1 Store & Attendant Numbers Used by Location", r["store_numbers"],
                  pinned=True),
            Block("table", "7.2 Store & Attendant Numbers on Customer Receipts", r["staff_numbers"],
                  pinned=True),
            Block("text", text=r["quality_note"]),
        ]),
    ]
    if fb:
        feedback = [Block("table", "Ratings and responses", fb["summary"], total=False),
                    Block("table", "8.1 Store Breakdown", fb["by_shop"])]
        if fb["targets"] is not None:
            feedback += [Block("table", "8.2 Feedback Link Targets by Location", fb["targets"],
                               pinned=True),
                         Block("text", text="Online responses against feedback links sent from "
                                            "the WhatsApp Monitor; target "
                                            f"{reports.FEEDBACK_LINK_TARGET:.0f}%.")]
    else:
        feedback = [Block("text", text="The feedback sheet could not be read.")]
    sections.append(Section(8, "Customer Feedback", feedback))
    sections.append(Section(9, "Summary & Key Notes", [Block("notes", notes=r["notes"])]))
    return sections


def chart_data(r: dict, chart: str) -> pd.DataFrame:
    """The rows behind each chart, the same for every edition."""
    if chart == "shops":
        return r["stores"].sort_values("Current")[["Shop", "Previous", "Current"]]
    if chart == "frequency":
        return r["frequency"][["Purchase Frequency", "Customer Count"]]
    if chart == "gender":
        g = r["gender"]
        return g[g["Count"] > 0][["Gender", "Count"]]
    if chart == "conversion":
        t = r["traffic"]
        return t.sort_values("Conv. Rate %")[["Shop", "Conv. Rate %"]] if not t.empty else t
    if chart == "bridge":
        b = r["bridge"].copy()
        b["Label"] = b["Period"].map(short_period)
        return b[["Label", "Revenue", "Avg Spend"]]
    raise KeyError(chart)


def short_period(label: str) -> str:
    """'Week of 11 Oct - 17 Oct 2026' → '11–17 Oct'; 'Tuesday, 20 October 2026'
    → 'Tue 20 Oct'; 'September 2026' → 'Sep 2026'."""
    m = re.match(r"Week of (\d+) (\w+) - (\d+) (\w+) \d{4}", label)
    if m:
        a, ma, b, mb = m.groups()
        return f"{a}–{b} {mb}" if ma == mb else f"{a} {ma}–{b} {mb}"
    m = re.match(r"(\w{3})\w*, (\d+) (\w{3})\w* \d{4}", label)
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}"
    m = re.match(r"(\w{3})\w* (\d{4})$", label)
    return f"{m.group(1)} {m.group(2)}" if m else label


def tag_of(text: str) -> tuple[str, str]:
    """'[RISK] Revenue is down…' → ('RISK', 'Revenue is down…')."""
    m = re.match(r"\[(\w+)\]\s*(.*)", text)
    return (m.group(1), m.group(2)) if m else ("", text)


# ------------------------------------------------------------- formatting ---

def _cell(col: str, v) -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return "—"
    if isinstance(v, (bool, np.bool_)):
        return "Yes" if v else "No"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    if isinstance(v, (float, np.floating)):
        v = float(v)
        if "%" in col or "(pp)" in col or "percent" in col.lower():
            return f"{v:,.1f}"
        if v.is_integer():
            return f"{int(v):,}"
        return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"
    if hasattr(v, "strftime"):
        return f"{v:%d %b %Y}"
    return str(v)


def _tone(col: str, v) -> str | None:
    """The colour a cell's value carries: green up, red down, by status."""
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("▲"):
            return UP
        if s.startswith("▼"):
            return DOWN
        return STATUS_COLOURS.get(s.lower())
    if col in ("Change", "Change %", "Gap (pp)") and isinstance(v, (int, float)) and not pd.isna(v):
        return UP if v > 0 else DOWN if v < 0 else None
    return None


def table_rows(block: Block) -> tuple[list[str], list[list[str]], list[list[str | None]], bool]:
    """Header, formatted body, per-cell colours and whether the last row is a
    TOTAL — the table as every edition prints it."""
    df = block.frame.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.date
    cols = [str(c) for c in df.columns]
    body = [[_cell(c, v) for c, v in zip(cols, row)] for row in df.itertuples(index=False)]
    tones = [[_tone(c, v) for c, v in zip(cols, row)] for row in df.itertuples(index=False)]
    has_total = False
    if block.total and len(df) > 1:
        summed = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
                  and not pd.api.types.is_bool_dtype(df[c]) and not _NOT_SUMMED.search(str(c))]
        if summed:
            row = []
            for i, c in enumerate(df.columns):
                if c in summed:
                    row.append(_cell(str(c), df[c].sum()))
                else:
                    row.append("TOTAL" if i == 0 else "")
            body.append(row)
            tones.append([None] * len(cols))
            has_total = True
    return cols, body, tones, has_total


def _numeric_column(block: Block, col: str) -> bool:
    return pd.api.types.is_numeric_dtype(block.frame[col]) if col in block.frame else False


# ------------------------------------------------------------------ charts ---

def _chart_png(r: dict, chart: str, width_in: float = 6.6, height_in: float = 3.2) -> bytes | None:
    """A chart for the Word edition, drawn with matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    data = chart_data(r, chart)
    if data is None or data.empty:
        return None
    ink, accent, grey = f"#{INK}", f"#{ACCENT}", "#B8B6AE"
    plt.rcParams.update({"font.size": 8.5, "font.family": "sans-serif",
                         "axes.edgecolor": "#BBBBBB", "axes.labelcolor": ink,
                         "xtick.color": ink, "ytick.color": ink})
    thousands = FuncFormatter(lambda v, _: f"{v / 1e6:.1f}M" if abs(v) >= 1e6
                              else f"{v / 1e3:.0f}K" if abs(v) >= 1e3 else f"{v:.0f}")
    if chart == "shops":
        height_in = max(height_in, 0.19 * len(data) + 0.8)
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=200)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

    if chart == "shops":
        y = range(len(data))
        ax.barh([i + 0.2 for i in y], data["Previous"], height=0.38, color=grey, label="Previous")
        ax.barh([i - 0.2 for i in y], data["Current"], height=0.38, color=accent, label="Current")
        ax.set_yticks(list(y), data["Shop"])
        ax.xaxis.set_major_formatter(thousands)
        ax.grid(axis="x", color="#EEEEEE")
        ax.legend(frameon=False, loc="lower right")
    elif chart == "frequency":
        bars = ax.bar(data["Purchase Frequency"], data["Customer Count"], color=accent, width=0.55)
        ax.bar_label(bars, labels=[f"{v:,}" for v in data["Customer Count"]], padding=2)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.set_ylim(0, max(data["Customer Count"].max() * 1.15, 1))
        ax.grid(axis="y", color="#EEEEEE")
    elif chart == "gender":
        colours = {"Female": "#D55181", "Male": accent, "Corporate": "#C98500"}
        ax.pie(data["Count"], labels=[f"{g}\n{c:,}" for g, c in zip(data["Gender"], data["Count"])],
               colors=[colours.get(g, grey) for g in data["Gender"]], startangle=90,
               autopct="%1.1f%%", pctdistance=0.78, wedgeprops={"width": 0.42, "edgecolor": "white"},
               textprops={"color": ink})
        ax.axis("equal")
    elif chart == "conversion":
        colours = [f"#{DOWN}" if v < reports.LOW_CONVERSION else accent for v in data["Conv. Rate %"]]
        ax.barh(data["Shop"], data["Conv. Rate %"], color=colours, height=0.6)
        ax.axvline(reports.LOW_CONVERSION, color=ink, lw=0.8, ls="--")
        ax.text(reports.LOW_CONVERSION, len(data) - 0.4, f" {reports.LOW_CONVERSION:.0f}% coaching line",
                fontsize=7.5, color=ink, va="bottom")
        ax.set_xlabel("Walk-in conversion %")
        ax.grid(axis="x", color="#EEEEEE")
    elif chart == "bridge":
        bars = ax.bar(data["Label"], data["Revenue"], color=accent, width=0.6, label="Revenue")
        ax.bar_label(bars, labels=["n/a" if pd.isna(v) else thousands(v, None) for v in data["Revenue"]],
                     padding=2, fontsize=7.5)
        ax.yaxis.set_major_formatter(thousands)
        ax.set_ylabel("Revenue (KES)")
        ax2 = ax.twinx()
        ax2.plot(data["Label"], data["Avg Spend"], color=f"#{AMBER}", marker="o", lw=1.8,
                 label="Avg spend / customer")
        ax2.spines["top"].set_visible(False)
        ax2.set_ylabel("Avg spend (KES)")
        ax2.set_ylim(0, max(data["Avg Spend"].fillna(0).max() * 1.25, 1))
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, frameon=False, loc="upper left", ncol=2)
        ax.set_ylim(0, max(data["Revenue"].fillna(0).max() * 1.2, 1))
        plt.setp(ax.get_xticklabels(), fontsize=7.5)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


# -------------------------------------------------------------------- Word ---

def to_docx(r: dict) -> bytes:
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    p = r["period"]
    title = reports.title_for(p)
    sections = outline(r)
    rgb = lambda h: RGBColor.from_string(h)

    doc = Document()
    doc.core_properties.title = f"Denri {title} — {p.label}"
    doc.core_properties.author = "Denri Executive Dashboard"
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.27), Inches(11.69)        # A4
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Inches(0.65))
    sec.top_margin, sec.bottom_margin = Inches(0.7), Inches(0.65)
    usable = sec.page_width - sec.left_margin - sec.right_margin

    styles = doc.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10)
    styles["Normal"].font.color.rgb = rgb(INK)
    for name, size, colour in (("Heading 1", 18, INK), ("Heading 2", 12.5, ACCENT), ("Heading 3", 11, INK)):
        st_ = styles[name]
        st_.font.name, st_.font.size, st_.font.bold = "Calibri", Pt(size), True
        st_.font.color.rgb = rgb(colour)
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            st_.element.rPr.rFonts.attrib.pop(qn(attr), None)   # so Calibri isn't overridden

    # --- low-level helpers ---
    def shade(cell, fill):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
        tcPr.append(shd)

    def cell_margins(table, top=50, bottom=50, left=80, right=80):
        tblPr = table._tbl.tblPr
        mar = OxmlElement("w:tblCellMar")
        for side, v in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:w"), str(v)); el.set(qn("w:type"), "dxa")
            mar.append(el)
        tblPr.append(mar)

    def borders(table, colour=RULE, inside_v=False):
        tblPr = table._tbl.tblPr
        b = OxmlElement("w:tblBorders")
        for edge in ("top", "bottom", "insideH") + (("insideV", "left", "right") if inside_v else ()):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "single"); el.set(qn("w:sz"), "4"); el.set(qn("w:color"), colour)
            b.append(el)
        for edge in (() if inside_v else ("left", "right", "insideV")):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "nil")
            b.append(el)
        tblPr.append(b)

    def repeat_header(row):
        trPr = row._tr.get_or_add_trPr()
        el = OxmlElement("w:tblHeader"); el.set(qn("w:val"), "true")
        trPr.append(el)

    def keep_row_together(row):
        trPr = row._tr.get_or_add_trPr()
        trPr.append(OxmlElement("w:cantSplit"))

    def write(cell, text, *, bold=False, colour=None, size=None, align=None):
        cell.text = ""
        para = cell.paragraphs[0]
        para.paragraph_format.space_after = Pt(0)
        if align:
            para.alignment = align
        run = para.add_run(text)
        run.bold = bold
        if colour:
            run.font.color.rgb = rgb(colour)
        if size:
            run.font.size = Pt(size)
        return run

    bookmark_id = [0]

    def bookmark(paragraph, name):
        bookmark_id[0] += 1
        start = OxmlElement("w:bookmarkStart")
        start.set(qn("w:id"), str(bookmark_id[0])); start.set(qn("w:name"), name)
        end = OxmlElement("w:bookmarkEnd"); end.set(qn("w:id"), str(bookmark_id[0]))
        paragraph._p.insert(0, start)
        paragraph._p.append(end)

    def link(paragraph, text, anchor, *, colour=ACCENT, size=None, bold=False):
        h = OxmlElement("w:hyperlink")
        h.set(qn("w:anchor"), anchor)
        run = OxmlElement("w:r")
        rPr = OxmlElement("w:rPr")
        c = OxmlElement("w:color"); c.set(qn("w:val"), colour); rPr.append(c)
        u = OxmlElement("w:u"); u.set(qn("w:val"), "none"); rPr.append(u)
        if bold:
            rPr.append(OxmlElement("w:b"))
        if size:
            sz = OxmlElement("w:sz"); sz.set(qn("w:val"), str(int(size * 2))); rPr.append(sz)
        run.append(rPr)
        t = OxmlElement("w:t"); t.text = text; t.set(qn("xml:space"), "preserve")
        run.append(t)
        h.append(run)
        paragraph._p.append(h)

    def field(paragraph, instr, size=8):
        run = paragraph.add_run()
        run.font.size = Pt(size); run.font.color.rgb = rgb(MUTED)
        for kind, text in (("begin", None), (None, instr), ("separate", None), (None, "1"), ("end", None)):
            if kind:
                el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), kind)
            elif text == instr:
                el = OxmlElement("w:instrText"); el.set(qn("xml:space"), "preserve"); el.text = f" {instr} "
            else:
                el = OxmlElement("w:t"); el.text = text
            run._r.append(el)

    def para_border(paragraph, colour, fill):
        pPr = paragraph._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        left = OxmlElement("w:left")
        left.set(qn("w:val"), "single"); left.set(qn("w:sz"), "24")
        left.set(qn("w:space"), "8"); left.set(qn("w:color"), colour)
        bdr.append(left)
        pPr.append(bdr)
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
        pPr.append(shd)

    def callout(text, colour=None):
        tag, body = tag_of(text)
        colour = colour or TAGS.get(tag, ACCENT)
        para = doc.add_paragraph()
        para.paragraph_format.space_after = Pt(5)
        para.paragraph_format.left_indent = Inches(0.08)
        para_border(para, colour, SOFT.get(colour, BAND))
        if tag:
            run = para.add_run(f"{tag}  ")
            run.bold, run.font.size = True, Pt(8.5)
            run.font.color.rgb = rgb(colour)
        para.add_run(body).font.size = Pt(9.5)

    def note(text):
        para = doc.add_paragraph()
        para.paragraph_format.space_after = Pt(6)
        run = para.add_run(text)
        run.italic, run.font.size = True, Pt(9)
        run.font.color.rgb = rgb(MUTED)

    def table(block):
        if block.frame is None or block.frame.empty:
            note("No data for this period.")
            return
        cols, body, tones, has_total = table_rows(block)
        size = 7.5 if len(cols) > 8 else 8.5 if len(cols) > 5 else 9.5
        t = doc.add_table(rows=1, cols=len(cols))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = True
        borders(t)
        cell_margins(t)
        numeric = [_numeric_column(block, c) or c in ("Current", "Previous", "Change", "Value")
                   for c in cols]
        head = t.rows[0]
        repeat_header(head)
        for i, c in enumerate(cols):
            shade(head.cells[i], INK)
            write(head.cells[i], c, bold=True, colour="FFFFFF", size=size,
                  align=WD_ALIGN_PARAGRAPH.RIGHT if numeric[i] and i else None)
        for n, (values, colours) in enumerate(zip(body, tones)):
            row = t.add_row()
            keep_row_together(row)
            total_row = has_total and n == len(body) - 1
            for i, (v, colour) in enumerate(zip(values, colours)):
                cell = row.cells[i]
                if total_row:
                    shade(cell, "E4E7EC")
                elif n % 2:
                    shade(cell, BAND)
                write(cell, v, bold=total_row or i == 0 and not numeric[0], colour=colour, size=size,
                      align=WD_ALIGN_PARAGRAPH.RIGHT if numeric[i] and i else None)
        doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def chart(block):
        png = _chart_png(r, block.chart, width_in=usable / 914400)
        if png is None:
            return
        doc.add_picture(io.BytesIO(png), width=usable)
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    # --- header and footer (not on the cover) ---
    sec.different_first_page_header_footer = True
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = hp.add_run(f"DENRI  ·  {title.upper()}  ·  {p.label}")
    run.font.size, run.font.color.rgb = Pt(7.5), rgb(MUTED)
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp.add_run("Page ").font.size = Pt(8)
    field(fp, "PAGE")
    fp.add_run(" of ").font.size = Pt(8)
    field(fp, "NUMPAGES")

    # --- cover ---
    if LOGO.exists():
        doc.add_picture(str(LOGO), width=Inches(1.15))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.LEFT
    head = doc.add_paragraph()
    head.paragraph_format.space_before = Pt(18)
    head.paragraph_format.space_after = Pt(2)
    run = head.add_run(title)
    run.bold, run.font.size, run.font.color.rgb = True, Pt(28), rgb(INK)
    sub = doc.add_paragraph()
    run = sub.add_run(p.label)
    run.font.size, run.font.color.rgb = Pt(15), rgb(ACCENT)
    meta = doc.add_paragraph()
    meta.paragraph_format.space_after = Pt(16)
    run = meta.add_run(f"Compared with {p.prev_label}   ·   {p.days} trading day{'s' if p.days > 1 else ''}"
                       f"   ·   Generated {r['generated']:%d %b %Y, %H:%M}")
    run.font.size, run.font.color.rgb = Pt(9), rgb(MUTED)

    kpis = reports.summary_rows(r)
    grid_t = doc.add_table(rows=2, cols=4)
    grid_t.alignment = WD_TABLE_ALIGNMENT.CENTER
    borders(grid_t, colour="FFFFFF", inside_v=True)
    cell_margins(grid_t, top=110, bottom=110, left=140, right=140)
    for i, k in enumerate(kpis.itertuples(index=False)):
        cell = grid_t.rows[i // 4].cells[i % 4]
        shade(cell, BAND)
        write(cell, k.Label.upper(), bold=True, colour=MUTED, size=7)
        para = cell.add_paragraph()
        para.paragraph_format.space_after = Pt(0)
        run = para.add_run(k.Value.replace("KES ", "KES "))
        run.bold, run.font.size = True, Pt(13)
        para = cell.add_paragraph()
        change_text = k.Change.split(" vs ")[0]
        run = para.add_run(change_text)
        run.font.size = Pt(8.5)
        run.font.color.rgb = rgb(UP if k.Tone == "up" else DOWN if k.Tone == "down" else MUTED)
    last = grid_t.rows[1].cells[3]
    shade(last, SOFT[ACCENT])
    write(last, "COMPARED WITH", bold=True, colour=MUTED, size=7)
    run = last.add_paragraph().add_run(p.prev_label)
    run.bold, run.font.size = True, Pt(11)

    contents = doc.add_paragraph()
    contents.paragraph_format.space_before = Pt(22)
    run = contents.add_run("Contents")
    run.bold, run.font.size = True, Pt(14)
    bookmark(contents, "contents")
    hint = doc.add_paragraph()
    run = hint.add_run("Click a section to jump to it; each section has a link back here at the top. "
                       "Open View → Navigation Pane for a side menu.")
    run.font.size, run.font.color.rgb = Pt(8.5), rgb(MUTED)
    for s in sections:
        para = doc.add_paragraph()
        para.paragraph_format.space_after = Pt(3)
        para.paragraph_format.left_indent = Inches(0.1)
        link(para, f"{s.num}.0", s.anchor, colour=ACCENT, size=11, bold=True)
        link(para, f"   {s.title}", s.anchor, colour=INK, size=11)
        subs = [b.title for b in s.blocks if b.kind == "table" and re.match(r"\d\.\d", b.title)]
        subs = list(dict.fromkeys(subs))
        if subs:
            run = para.add_run("     " + "  ·  ".join(subs))
            run.font.size, run.font.color.rgb = Pt(8), rgb(MUTED)

    # --- sections ---
    for s in sections:
        back = doc.add_paragraph()
        back.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        back.paragraph_format.page_break_before = True
        back.paragraph_format.space_after = Pt(0)
        back.paragraph_format.keep_with_next = True
        link(back, "↑ Back to contents", "contents", size=8.5)
        h = doc.add_heading(s.heading, level=1)
        h.paragraph_format.space_before = Pt(0)
        h.paragraph_format.space_after = Pt(8)
        bookmark(h, s.anchor)
        seen_titles: set[str] = set()
        for b in s.blocks:
            if b.title and b.kind in ("table", "chart", "flags") and b.title not in seen_titles:
                doc.add_heading(b.title, level=2).paragraph_format.keep_with_next = True
                seen_titles.add(b.title)
            if b.kind == "table":
                table(b)
            elif b.kind == "chart":
                chart(b)
            elif b.kind == "text" and b.text:
                note(b.text)
            elif b.kind == "flags":
                if not b.items:
                    note("No changes large enough to flag.")
                for f in b.items:
                    callout(f)
            elif b.kind == "notes":
                for team, items in b.notes.items():
                    doc.add_heading(team, level=2)
                    if not items:
                        note(f"No {team.lower()} flags this period.")
                    for item in items:
                        callout(item)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# -------------------------------------------------------------- PowerPoint ---

ROWS_PER_SLIDE = 22      # a full-width table; longer ones continue on the next slide
NARROW_ROWS = 13         # a half-width table, beside a chart or another table


def to_pptx(r: dict) -> bytes:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Inches, Pt

    p = r["period"]
    title = reports.title_for(p)
    sections = outline(r)
    rgb = lambda h: RGBColor.from_string(h)

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    W, H = prs.slide_width, prs.slide_height
    blank = prs.slide_layouts[6]
    margin = Inches(0.55)
    content_top, content_bottom = Inches(1.45), H - Inches(0.75)

    def text_box(slide, left, top, width, height, text, *, size=12, bold=False, colour=INK,
                 align=None, anchor=None, italic=False):
        box = slide.shapes.add_textbox(left, top, width, height)
        tf = box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = Inches(0.02)
        if anchor:
            tf.vertical_anchor = anchor
        para = tf.paragraphs[0]
        if align:
            para.alignment = align
        run = para.add_run()
        run.text = text
        run.font.size, run.font.bold, run.font.italic = Pt(size), bold, italic
        run.font.color.rgb = rgb(colour)
        run.font.name = "Calibri"
        return box

    def rect(slide, left, top, width, height, fill, *, shape=MSO_SHAPE.RECTANGLE, line=None):
        s = slide.shapes.add_shape(shape, left, top, width, height)
        s.fill.solid()
        s.fill.fore_color.rgb = rgb(fill)
        if line:
            s.line.color.rgb = rgb(line)
            s.line.width = Pt(0.75)
        else:
            s.line.fill.background()
        s.shadow.inherit = False
        return s

    contents_buttons = []

    def frame(kicker: str, heading: str):
        slide = prs.slides.add_slide(blank)
        rect(slide, 0, 0, Inches(0.12), H, ACCENT)
        text_box(slide, margin, Inches(0.32), Inches(9), Inches(0.3), kicker.upper(),
                 size=10.5, bold=True, colour=ACCENT)
        text_box(slide, margin, Inches(0.58), Inches(10.5), Inches(0.7), heading, size=26, bold=True)
        btn = rect(slide, W - Inches(1.95), Inches(0.4), Inches(1.4), Inches(0.38), BAND,
                   shape=MSO_SHAPE.ROUNDED_RECTANGLE, line=RULE)
        tf = btn.text_frame
        tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        run = tf.paragraphs[0].add_run()
        run.text = "☰  Contents"
        run.font.size, run.font.bold = Pt(10.5), True
        run.font.color.rgb = rgb(INK)
        contents_buttons.append(btn)
        rect(slide, margin, H - Inches(0.56), W - 2 * margin, Pt(0.75), RULE)
        text_box(slide, margin, H - Inches(0.5), Inches(9), Inches(0.3),
                 f"DENRI  ·  {title}  ·  {p.label}", size=9, colour=MUTED)
        text_box(slide, W - margin - Inches(1), H - Inches(0.5), Inches(1), Inches(0.3),
                 str(len(prs.slides)), size=9, colour=MUTED, align=PP_ALIGN.RIGHT)
        return slide

    def speaker_notes(slide, lines):
        lines = [x for x in lines if x]
        if lines:
            slide.notes_slide.notes_text_frame.text = "\n\n".join(lines)

    def takeaway(slide, text):
        top = H - Inches(1.2)
        bar = rect(slide, margin, top, W - 2 * margin, Inches(0.5), SOFT[ACCENT])
        tf = bar.text_frame
        tf.margin_left = Inches(0.2)
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.word_wrap = True
        tf.paragraphs[0].alignment = PP_ALIGN.LEFT
        run = tf.paragraphs[0].add_run()
        run.text = text
        run.font.size, run.font.italic = Pt(11.5), True
        run.font.color.rgb = rgb(INK)

    def table(slide, block, rows, left, top, width, max_height):
        cols, body, tones, has_total = rows
        left, top, width, max_height = int(left), int(top), int(width), int(max_height)
        n_rows = len(body) + 1
        row_h = int(min(Inches(0.33), max_height / n_rows))
        height = row_h * n_rows
        shape = slide.shapes.add_table(n_rows, len(cols), left, top, width, height)
        tbl = shape.table
        tbl.first_row = True
        tbl.horz_banding = False
        size = (11.5 if len(cols) <= 6 else 10) if row_h >= Inches(0.3) else 9.5 if row_h >= Inches(0.24) else 8.5
        if len(cols) > 9:
            size = min(size, 9)
        numeric = [_numeric_column(block, c) or c in ("Current", "Previous", "Change", "Value")
                   for c in cols]
        # Each column as wide as its longest entry (headers wrap, so count less).
        weights = []
        for i, c in enumerate(cols):
            longest = max([len(row[i]) for row in body] + [min(len(c), 10) * 0.8, 4])
            weights.append(min(longest, 34))
        total_w = sum(weights)
        widths = [int(width * w / total_w) for w in weights]
        widths[-1] += width - sum(widths)
        for i, w in enumerate(widths):
            tbl.columns[i].width = w

        def put(cell, text, *, bold=False, colour=INK, fill=None, right=False):
            cell.fill.solid()
            cell.fill.fore_color.rgb = rgb(fill or "FFFFFF")
            cell.margin_left = cell.margin_right = Inches(0.06)
            cell.margin_top = cell.margin_bottom = Inches(0.025)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            para = tf.paragraphs[0]
            para.alignment = PP_ALIGN.RIGHT if right else PP_ALIGN.LEFT
            run = para.add_run()
            run.text = text
            run.font.size, run.font.bold = Pt(size), bold
            run.font.color.rgb = rgb(colour)
            run.font.name = "Calibri"

        for i, c in enumerate(cols):
            put(tbl.cell(0, i), c, bold=True, colour="FFFFFF", fill=INK, right=numeric[i] and i > 0)
        for n, (values, colours) in enumerate(zip(body, tones), start=1):
            tbl.rows[n].height = row_h
            total_row = has_total and n == len(body)
            fill = "E4E7EC" if total_row else BAND if n % 2 == 0 else "FFFFFF"
            for i, (v, colour) in enumerate(zip(values, colours)):
                put(tbl.cell(n, i), v, bold=total_row or i == 0, colour=colour or INK, fill=fill,
                    right=numeric[i] and i > 0)
        tbl.rows[0].height = row_h
        return shape

    def native_chart(slide, chart_key, left, top, width, height):
        data = chart_data(r, chart_key)
        if data is None or data.empty:
            text_box(slide, left, top, width, Inches(0.4), "No data for this period.", colour=MUTED)
            return
        cd = CategoryChartData()
        if chart_key == "shops":
            cd.categories = list(data["Shop"])
            cd.add_series("Previous", [float(v) for v in data["Previous"]])
            cd.add_series("Current", [float(v) for v in data["Current"]])
            kind = XL_CHART_TYPE.BAR_CLUSTERED
        elif chart_key == "frequency":
            cd.categories = list(data["Purchase Frequency"])
            cd.add_series("Customers", [int(v) for v in data["Customer Count"]])
            kind = XL_CHART_TYPE.COLUMN_CLUSTERED
        elif chart_key == "gender":
            cd.categories = list(data["Gender"])
            cd.add_series("Customers", [int(v) for v in data["Count"]])
            kind = XL_CHART_TYPE.DOUGHNUT
        elif chart_key == "conversion":
            cd.categories = list(data["Shop"])
            cd.add_series("Conversion %", [float(v) for v in data["Conv. Rate %"]])
            kind = XL_CHART_TYPE.BAR_CLUSTERED
        else:  # bridge
            cd.categories = list(data["Label"])
            cd.add_series("Revenue (KES)", [None if pd.isna(v) else float(v) for v in data["Revenue"]])
            kind = XL_CHART_TYPE.COLUMN_CLUSTERED
        gf = slide.shapes.add_chart(kind, left, top, width, height, cd)
        ch = gf.chart
        ch.has_title = False
        ch.font.size, ch.font.name = Pt(10), "Calibri"
        ch.font.color.rgb = rgb(INK)
        plot = ch.plots[0]
        if chart_key == "gender":
            colours = {"Female": "D55181", "Male": ACCENT, "Corporate": "C98500"}
            for i, g in enumerate(data["Gender"]):
                point = plot.series[0].points[i]
                point.format.fill.solid()
                point.format.fill.fore_color.rgb = rgb(colours.get(g, MUTED))
            plot.has_data_labels = True
            dl = plot.data_labels
            dl.show_percentage, dl.show_value, dl.show_category_name = True, False, True
            dl.number_format, dl.number_format_is_linked = "0.0%", False
            dl.font.size = Pt(11)
            ch.has_legend = False
            return
        plot.gap_width = 60
        for series, colour in zip(plot.series, ["B8B6AE", ACCENT] if chart_key == "shops" else [ACCENT]):
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = rgb(colour)
        if chart_key == "conversion":
            for i, v in enumerate(data["Conv. Rate %"]):
                point = plot.series[0].points[i]
                point.format.fill.solid()
                point.format.fill.fore_color.rgb = rgb(DOWN if v < reports.LOW_CONVERSION else ACCENT)
        if chart_key in ("frequency", "conversion", "bridge"):
            plot.has_data_labels = True
            dl = plot.data_labels
            dl.font.size = Pt(9.5)
            dl.number_format = '0.0"%"' if chart_key == "conversion" else '#,##0'
            dl.number_format_is_linked = False
            dl.position = XL_LABEL_POSITION.OUTSIDE_END
        ch.has_legend = chart_key == "shops"
        if ch.has_legend:
            ch.legend.position = XL_LEGEND_POSITION.TOP
            ch.legend.include_in_layout = False
        va = ch.value_axis
        va.has_major_gridlines = True
        va.major_gridlines.format.line.color.rgb = rgb("E6E6E6")
        va.format.line.fill.background()
        va.tick_labels.font.size = Pt(9)
        va.tick_labels.number_format = '0"%"' if chart_key == "conversion" else '#,##0'
        va.tick_labels.number_format_is_linked = False
        ca = ch.category_axis
        ca.tick_labels.font.size = Pt(9.5)
        ca.format.line.color.rgb = rgb(RULE)

    def flag_cards(slide, items, left, top, width):
        if not items:
            text_box(slide, left, top, width, Inches(0.4), "No changes large enough to flag.",
                     size=11, colour=MUTED, italic=True)
        for f in items:
            tag, body = tag_of(f)
            colour = TAGS.get(tag, ACCENT)
            card = rect(slide, left, top, width, Inches(0.72), SOFT.get(colour, BAND))
            rect(slide, left, top, Inches(0.07), Inches(0.72), colour)
            tf = card.text_frame
            tf.word_wrap = True
            tf.margin_left = Inches(0.2)
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf.paragraphs[0].alignment = PP_ALIGN.LEFT
            run = tf.paragraphs[0].add_run()
            run.text = f"{tag}  "
            run.font.size, run.font.bold = Pt(10), True
            run.font.color.rgb = rgb(colour)
            run = tf.paragraphs[0].add_run()
            run.text = body
            run.font.size = Pt(12)
            run.font.color.rgb = rgb(INK)
            top += Inches(0.84)

    def panel(slide, g, left, top, width, height):
        left, top, width, height = int(left), int(top), int(width), int(height)
        if g.kind == "chart":
            native_chart(slide, g.chart, left, top, width, height)
        elif g.kind == "flags":
            flag_cards(slide, g.items, left, top, width)
        elif g.frame is None or g.frame.empty:
            text_box(slide, left, top, width, Inches(0.4), "No data for this period.",
                     colour=MUTED, italic=True)
        else:
            table(slide, g, table_rows(g), left, top, width, height)

    # --- title slide ---
    s0 = prs.slides.add_slide(blank)
    rect(s0, 0, 0, Inches(4.6), H, BAND)
    if LOGO.exists():
        s0.shapes.add_picture(str(LOGO), Inches(1.05), Inches(2.25), Inches(2.5), Inches(2.5))
    rect(s0, Inches(5.3), Inches(2.35), Inches(0.08), Inches(2.6), ACCENT)
    text_box(s0, Inches(5.65), Inches(2.25), Inches(7.2), Inches(0.4), "DENRI", size=14, bold=True,
             colour=ACCENT)
    text_box(s0, Inches(5.65), Inches(2.65), Inches(7.2), Inches(1.0), title, size=36, bold=True)
    text_box(s0, Inches(5.65), Inches(3.75), Inches(7.2), Inches(0.5), p.label, size=20, colour=ACCENT)
    text_box(s0, Inches(5.65), Inches(4.35), Inches(7.2), Inches(0.6),
             f"Compared with {p.prev_label}\nGenerated {r['generated']:%d %b %Y, %H:%M}",
             size=12, colour=MUTED)

    # --- contents slide (tiles are linked once the section slides exist) ---
    agenda = frame("Denri  ·  " + p.label, "Contents")
    text_box(agenda, margin, Inches(1.25), Inches(10), Inches(0.35),
             "Click a section to jump to it. The Contents button on every slide brings you back here.",
             size=11.5, colour=MUTED)
    tiles = []
    tile_w, tile_h, gap = Inches(3.9), Inches(1.45), Inches(0.25)
    for i, s in enumerate(sections):
        left = margin + (tile_w + gap) * (i % 3)
        top = Inches(1.85) + (tile_h + gap) * (i // 3)
        tile = rect(agenda, left, top, tile_w, tile_h, BAND, shape=MSO_SHAPE.ROUNDED_RECTANGLE,
                    line=RULE)
        tile.adjustments[0] = 0.08
        tf = tile.text_frame
        tf.margin_left = Inches(0.25)
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.word_wrap = True
        para = tf.paragraphs[0]
        para.alignment = PP_ALIGN.LEFT
        run = para.add_run()
        run.text = f"{s.num}.0"
        run.font.size, run.font.bold = Pt(22), True
        run.font.color.rgb = rgb(ACCENT)
        para2 = tf.add_paragraph()
        para2.alignment = PP_ALIGN.LEFT
        run = para2.add_run()
        run.text = s.title
        run.font.size, run.font.bold = Pt(15), True
        run.font.color.rgb = rgb(INK)
        tiles.append(tile)

    # --- headline figures ---
    kslide = frame("Key performance indicators", f"{p.label} at a glance")
    kpis = reports.summary_rows(r)
    card_w, card_h = Inches(2.9), Inches(1.85)
    for i, k in enumerate(kpis.itertuples(index=False)):
        left = margin + (card_w + Inches(0.22)) * (i % 4)
        top = Inches(1.55) + (card_h + Inches(0.3)) * (i // 4)
        colour = UP if k.Tone == "up" else DOWN if k.Tone == "down" else MUTED
        rect(kslide, left, top, card_w, card_h, BAND, shape=MSO_SHAPE.ROUNDED_RECTANGLE).adjustments[0] = 0.06
        rect(kslide, left, top + Inches(0.25), Inches(0.07), card_h - Inches(0.5), colour)
        text_box(kslide, left + Inches(0.25), top + Inches(0.18), card_w - Inches(0.4), Inches(0.3),
                 k.Label.upper(), size=9.5, bold=True, colour=MUTED)
        text_box(kslide, left + Inches(0.25), top + Inches(0.55), card_w - Inches(0.4), Inches(0.6),
                 k.Value, size=20 if len(k.Value) < 16 else 17, bold=True)
        text_box(kslide, left + Inches(0.25), top + Inches(1.2), card_w - Inches(0.4), Inches(0.5),
                 k.Change.split(" vs ")[0], size=11.5, bold=True, colour=colour)
    text_box(kslide, margin + (card_w + Inches(0.22)) * 3 + Inches(0.25), Inches(1.55) + card_h
             + Inches(0.3) + Inches(0.3), card_w, Inches(1.2),
             f"Compared with\n{p.prev_label}", size=13, colour=MUTED)
    speaker_notes(kslide, [r["exec_note"]] + r["flags"])

    # --- sections ---
    def is_narrow(b: Block) -> bool:
        if b.kind in ("chart", "flags"):
            return True
        return (b.kind == "table" and b.frame is not None and len(b.frame.columns) <= 5
                and len(b.frame) <= NARROW_ROWS)

    first_slide: dict[int, object] = {}
    for s in sections:
        texts = [b.text for b in s.blocks if b.kind == "text" and b.text]
        panels = [b for b in s.blocks if b.kind in ("table", "chart", "flags", "notes")]
        slides_made = []

        if s.num == 9:
            slide = frame(s.heading, "What to act on")
            teams = list(panels[0].notes.items())
            col_w = int((W - 2 * margin - Inches(0.5)) / max(len(teams), 1))
            for i, (team, items) in enumerate(teams):
                left = margin + (col_w + Inches(0.25)) * i
                text_box(slide, left, Inches(1.45), col_w, Inches(0.4), team, size=16, bold=True)
                top = Inches(1.95)
                if not items:
                    text_box(slide, left, top, col_w, Inches(0.4), f"No {team.lower()} flags this period.",
                             size=11, colour=MUTED, italic=True)
                for item in items:
                    tag, body = tag_of(item)
                    colour = TAGS.get(tag, ACCENT)
                    lines = max(1, len(body) // 48 + 1)
                    h = Inches(0.42 + 0.21 * lines)
                    card = rect(slide, left, top, col_w, h, SOFT.get(colour, BAND))
                    rect(slide, left, top, Inches(0.07), h, colour)
                    tf = card.text_frame
                    tf.word_wrap = True
                    tf.margin_left = Inches(0.2)
                    tf.vertical_anchor = MSO_ANCHOR.TOP
                    tf.paragraphs[0].alignment = PP_ALIGN.LEFT
                    run = tf.paragraphs[0].add_run()
                    run.text = tag
                    run.font.size, run.font.bold = Pt(9.5), True
                    run.font.color.rgb = rgb(colour)
                    body_para = tf.add_paragraph()
                    body_para.alignment = PP_ALIGN.LEFT
                    run = body_para.add_run()
                    run.text = body
                    run.font.size = Pt(11)
                    run.font.color.rgb = rgb(INK)
                    top += h + Inches(0.12)
            speaker_notes(slide, [i for _, items in teams for i in items])
            first_slide[s.num] = slide
            continue

        i = 0
        while i < len(panels):
            b = panels[i]
            pair = is_narrow(b) and i + 1 < len(panels) and is_narrow(panels[i + 1])
            group = [b, panels[i + 1]] if pair else [b]
            i += len(group)

            if len(group) == 2:
                same = group[0].title == group[1].title
                slide = frame(s.heading, group[0].title if same else s.title)
                half = int((W - 2 * margin - Inches(0.4)) / 2)
                for j, g in enumerate(group):
                    left, top = margin + (half + Inches(0.4)) * j, content_top
                    if not same:
                        text_box(slide, left, top - Inches(0.05), half, Inches(0.35), g.title,
                                 size=13, bold=True, colour=ACCENT)
                        top += Inches(0.4)
                    panel(slide, g, left, top, half, content_bottom - top - Inches(0.6))
                slides_made.append(slide)
                continue

            if b.kind != "table" or b.frame is None or b.frame.empty:
                slide = frame(s.heading, b.title or s.title)
                panel(slide, b, margin, content_top, W - 2 * margin,
                      content_bottom - content_top - Inches(0.55))
                slides_made.append(slide)
                continue
            # A long or wide table: full width, ROWS_PER_SLIDE rows a slide.
            cols, body, tones, has_total = table_rows(b)
            # A couple of rows over (often just the TOTAL) squeeze onto one slide
            # rather than sit alone on another.
            per = len(body) if len(body) <= ROWS_PER_SLIDE + 2 else ROWS_PER_SLIDE
            pages = [range(k, min(k + per, len(body))) for k in range(0, len(body), per)]
            for n, rows_ in enumerate(pages):
                heading = b.title + (f"  ({n + 1} of {len(pages)})" if len(pages) > 1 else "")
                slide = frame(s.heading, heading)
                table(slide, b, (cols, [body[k] for k in rows_], [tones[k] for k in rows_],
                                 has_total and n == len(pages) - 1),
                      margin, content_top, W - 2 * margin, content_bottom - content_top - Inches(0.55))
                slides_made.append(slide)

        if not slides_made:
            slide = frame(s.heading, s.title)
            slides_made.append(slide)
        if texts:
            takeaway(slides_made[-1], texts[-1])
            speaker_notes(slides_made[-1], texts)
        first_slide[s.num] = slides_made[0]

    # --- links: contents tiles → sections; every Contents button → contents ---
    for s, tile in zip(sections, tiles):
        tile.click_action.target_slide = first_slide[s.num]
    for btn in contents_buttons:
        btn.click_action.target_slide = agenda

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
