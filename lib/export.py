# Dispatch Tracking uses: combined_distribution_xlsx, dispatch_xlsx,
# transit_xlsx, hub_outflow_xlsx, and the _shape/_workbook/_style_sheet
# helpers. The rest of the module serves Product Sales and Stock Levels.

"""Excel export for the distribution reports.

Matches the shape the reports are circulated in: bag_name first, the location
columns, TOTAL, then any reference and annotation columns. The Family and
sort_order plumbing the pages use to split row tiers is dropped — it isn't
part of the report, it's how the page finds the subtotal rows.
"""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from lib import taxonomy

# Column order of the circulated Combined Distribution report. CORPORATE is
# deliberately absent — it isn't in the shared format.
COMBINED_COLUMNS = [
    "STARMALL", "MOMBASA", "NAKURU", "ELDORET", "KISUMU", "MERU", "THIKA",
    "HAZINA", "KITENGELA", "WEBSITE", "NANYUKI", "KAKAMEGA", "HILTON",
    "JUMIA", "MRKT", "SINZA", "UGANDA", "KISII", "KTDA", "KTDA NEW",
    "BUSIA", "RONGAI", "TOTAL", "DENRI SHOPS", "JUMIA SRC", "MRKT SRC",
]

DISPATCH_COLUMNS = [
    "STARMALL", "MOMBASA", "NAKURU", "ELDORET", "KISUMU", "MERU", "THIKA",
    "HAZINA", "KITENGELA", "WEBSITE", "NANYUKI", "KAKAMEGA", "HILTON",
    "SINZA", "UGANDA", "KISII", "KTDA", "KTDA NEW", "BUSIA", "RONGAI",
    "TOTAL",
]

# Bags Sold. Nineteen tills and no hub columns: this counts what was sold over
# the counter, so KTDA NEW, DENRI SHOPS and the JUMIA/MRKT source annotations —
# all distribution concepts — have nothing to say here.
BAGS_SOLD_COLUMNS = [
    "STARMALL", "MOMBASA", "NAKURU", "ELDORET", "KISUMU", "MERU", "THIKA",
    "HAZINA", "KITENGELA", "WEBSITE", "NANYUKI", "KAKAMEGA", "HILTON",
    "SINZA", "UGANDA", "KISII", "KTDA", "BUSIA", "RONGAI", "TOTAL",
]

# Kept for callers that imported the old name.
EXPORT_COLUMNS = COMBINED_COLUMNS
SHEET_NAME = "Combined Distribution"

_HEADER_FILL = PatternFill("solid", fgColor="1F3A34")
_SUBTOTAL_FILL = PatternFill("solid", fgColor="EEF3F1")
_GRAND_FILL = PatternFill("solid", fgColor="D6E8E1")
_THIN = Side(style="thin", color="D0D7D4")


def _shape(df: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    """Report-shaped frame plus the row tier, kept aside for styling.

    The 018 style code is folded away here so every matrix report — combined
    distribution, dispatch, transit, bags sold — shows one line per bag rather
    than Zula Black above Zula Black 018. Done at this shared step rather than in
    each query so the reports cannot disagree about it.

    Subtotal and grand-total rows are left out of the merge: their labels are
    "ACE TOTAL" and "GRAND TOTAL", so they carry no style code and folding them
    would double-count against the detail rows they summarise.
    """
    out = df.rename(columns={"Product": "bag_name"})
    if "sort_order" not in out.columns:
        out = taxonomy.merge_style_codes(out, "bag_name")
        out = out.assign(sort_order=0)

    # Detail rows fold; subtotal and grand-total rows pass through untouched.
    # Their sums stay right either way — merging two detail rows into one does
    # not change what the family adds up to.
    raw_detail = out[out["sort_order"] == 0]
    detail = taxonomy.merge_style_codes(raw_detail, "bag_name")

    # "JUMIA SRC" and "MRKT SRC" are text — "3 (Direct)" — so a fold sums the
    # numeric JUMIA/MRKT columns but can only keep one row's annotation, leaving
    # a count that no longer matches its own label. Blanked on the rows that
    # actually merged: no annotation is honest, a stale one is not.
    src_columns = [c for c in detail.columns if c.endswith(" SRC")]
    if src_columns:
        folded = raw_detail["bag_name"].map(taxonomy.base_name).value_counts()
        multi = set(folded[folded > 1].index)
        if multi:
            detail.loc[detail["bag_name"].isin(multi), src_columns] = None
    rest = out[out["sort_order"] != 0]
    out = pd.concat([detail, rest], ignore_index=True)
    out = out.sort_values(
        ["bag_name" if "Family" not in out.columns else "Family", "sort_order"],
        kind="stable", ignore_index=True,
    ) if "Family" in out.columns else out

    tiers = out["sort_order"]
    keep = ["bag_name"] + [c for c in columns if c in out.columns]
    return out[keep], tiers.reset_index(drop=True)


def _workbook(df: pd.DataFrame, columns: list[str], sheet_name: str) -> bytes:
    """Render a report to a styled .xlsx and return the bytes."""
    shaped, tiers = _shape(df, columns)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        shaped.to_excel(writer, sheet_name=sheet_name, index=False)
        ws = writer.sheets[sheet_name]

        n_rows, n_cols = shaped.shape
        last_col = get_column_letter(n_cols)

        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF", size=10)
            cell.fill = _HEADER_FILL
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = Border(bottom=_THIN)
        ws.row_dimensions[1].height = 28

        # Subtotal and grand-total rows carry different weight from detail rows;
        # without that the reader has to parse row labels to find the breaks.
        for offset, tier in enumerate(tiers, start=2):
            if tier == 0:
                continue
            fill = _GRAND_FILL if tier == 2 else _SUBTOTAL_FILL
            for cell in ws[offset]:
                cell.font = Font(bold=True, size=10)
                cell.fill = fill

        for idx, name in enumerate(shaped.columns, start=1):
            letter = get_column_letter(idx)
            if name == "bag_name":
                width = 30
            elif name in ("JUMIA SRC", "MRKT SRC"):
                width = 22
            else:
                width = max(11, len(str(name)) + 3)
            ws.column_dimensions[letter].width = width
            if name != "bag_name":
                for row in range(2, n_rows + 2):
                    ws.cell(row=row, column=idx).number_format = "#,##0"

        ws.freeze_panes = "B2"                       # keep bag names and header in view
        ws.auto_filter.ref = f"A1:{last_col}{n_rows + 1}"

    return buffer.getvalue()


def combined_distribution_xlsx(df: pd.DataFrame) -> bytes:
    return _workbook(df, COMBINED_COLUMNS, SHEET_NAME)


def dispatch_xlsx(df: pd.DataFrame, *, with_cbd: bool) -> bytes:
    """Dispatch report. The sheet is named for the variant, so the two files
    stay distinguishable once they're open and the filename is out of view."""
    sheet = "Dispatch with CBD" if with_cbd else "Dispatch excl CBD"
    return _workbook(df, DISPATCH_COLUMNS, sheet)


def bags_sold_xlsx(df: pd.DataFrame) -> bytes:
    return _workbook(df, BAGS_SOLD_COLUMNS, "Bags Sold")


def hub_outflow_xlsx(hub_detail: pd.DataFrame) -> bytes:
    """What HTN and CBD handed on, in the Combined Distribution shape.

    Same layout, same styling, same helper: bag down the left, destinations
    across, TOTAL, family subtotal rows and a grand total. Anyone who reads the
    combined sheet can read this one without being told how.
    """
    matrix = (
        hub_detail.pivot_table(index="Product", columns="Sent to", values="Qty",
                               aggfunc="sum", fill_value=0)
        .reset_index()
    )
    # Destinations in the circulated order where they overlap, then anything
    # else the hubs reached (CBD, CORPORATE, MRKT and the like) so nothing is
    # dropped just for being absent from the combined report's column list.
    present = [c for c in matrix.columns if c != "Product"]
    ordered = [c for c in COMBINED_COLUMNS if c in present]
    ordered += [c for c in present if c not in ordered]

    matrix = matrix[["Product", *ordered]]
    matrix["TOTAL"] = matrix[ordered].sum(axis=1)
    matrix["Family"] = matrix["Product"].str.split(" ").str[0]
    matrix["sort_order"] = 0

    value_cols = [*ordered, "TOTAL"]
    subtotals = matrix.groupby("Family", as_index=False)[value_cols].sum()
    subtotals["Product"] = subtotals["Family"] + " TOTAL"
    subtotals["sort_order"] = 1

    grand = matrix[value_cols].sum().to_frame().T
    grand["Product"] = "GRAND TOTAL"
    grand["Family"] = "~~~~"          # sorts last, as in the combined report
    grand["sort_order"] = 2

    shaped = pd.concat([matrix, subtotals, grand], ignore_index=True)
    shaped = shaped.sort_values(["Family", "sort_order", "Product"],
                                kind="stable").reset_index(drop=True)

    return _workbook(shaped, value_cols, "Hubs Gave Out")


def hub_outflow_filename(start_date, end_date) -> str:
    return f"hubs_gave_out_{_stamp(start_date, end_date)}.xlsx"


def odoo_forwarding_xlsx(forwarding: pd.DataFrame, detail: pd.DataFrame,
                         excluded: pd.DataFrame) -> bytes:
    """The sheet-versus-Odoo correction, three sheets.

    "Odoo Forwarding" is the one that gets imported and so it is kept to the
    four columns Odoo's adjustment import reads, in its order, with nothing
    else on it. "Variance Detail" carries the working — counted, system, the
    difference, and which of the two bases produced it — because anyone asked
    to approve a write-off will want to see both numbers rather than only the
    gap, and will want to know which rows clear a product the count never
    listed. "Not Compared" is what stayed out of the correction entirely.
    """
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        forwarding.to_excel(writer, sheet_name="Odoo Forwarding", index=False)
        _style_sheet(writer.sheets["Odoo Forwarding"], forwarding,
                     numeric=("Counted Quantity", "Product ID"),
                     first_width=38)

        shaped = detail.copy()
        for column in ("Sheet", "Odoo", "Variance"):
            shaped[column] = shaped[column].astype(int)
        if "Product ID" in shaped.columns:
            shaped["Product ID"] = shaped["Product ID"].astype("Int64")
        shaped = shaped.rename(columns={"Sheet": "COUNTED (SHEET)",
                                        "Odoo": "SYSTEM (ODOO)",
                                        "Variance": "VARIANCE",
                                        "Basis": "BASIS"})
        shaped.to_excel(writer, sheet_name="Variance Detail", index=False)
        _style_sheet(writer.sheets["Variance Detail"], shaped,
                     numeric=("COUNTED (SHEET)", "SYSTEM (ODOO)", "VARIANCE",
                              "Product ID"),
                     first_width=38, wide=("BASIS",))

        excluded.to_excel(writer, sheet_name="Not Compared", index=False)
        _style_sheet(writer.sheets["Not Compared"], excluded,
                     numeric=("Units",), first_width=38)

    return buffer.getvalue()


def count_aligned_xlsx(aligned: pd.DataFrame, extras: pd.DataFrame,
                       location: str, count_date, label: str) -> bytes:
    """A shop's count in the sheet's own row order, ready to paste beside it.

    No sorting, no totals inside the block, and no rows removed — the first
    sheet is a straight column-for-column companion to column A of the count
    tab. A grand total sits below the block rather than inside it, so it cannot
    push a row out of alignment.
    """
    numeric = ["SHEET", "SCANNED", "ODOO STOCKS", "DIFF"]
    body = aligned.copy()
    # A repeated name shows its real Odoo and scanned figures on both lines, the
    # way the sheet shows the name twice — but the product only holds that stock
    # once, so the totals count it once. SHEET is exempt: those values really are
    # per line, and the sheet's own column total includes both.
    repeat = body.pop("_repeat") if "_repeat" in body.columns else None
    once = body if repeat is None else body[~repeat.values]
    grand = {"PRODUCT": "GRAND TOTAL", "SHEET": body["SHEET"].sum()}
    grand.update({c: once[c].sum() for c in ("SCANNED", "ODOO STOCKS", "DIFF")})
    body = pd.concat([body, pd.DataFrame([grand])], ignore_index=True)
    tiers = pd.Series([0] * (len(body) - 1) + [2])

    shop = location.split("/")[0][:20]
    name = f"{shop} {count_date:%d %b}"[:31]

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        body = body.rename(columns={"SHEET": label})
        body.to_excel(writer, sheet_name=name, index=False)
        _style_sheet(writer.sheets[name], body, first_width=40, tiers=tiers,
                     numeric=[label, "SCANNED", "ODOO STOCKS", "DIFF"])

        spare = extras if not extras.empty else pd.DataFrame(
            [{"PRODUCT": "(nothing outside the sheet's product list)"}])
        spare.to_excel(writer, sheet_name="Not On Sheet", index=False)
        _style_sheet(writer.sheets["Not On Sheet"], spare, first_width=40,
                     numeric=[c for c in numeric if c in spare.columns])

    return buffer.getvalue()


def count_aligned_filename(location: str, count_date) -> str:
    shop = location.split("/")[0].lower()
    return f"denri_count_{shop}_aligned_{count_date:%Y%m%d}.xlsx"


def count_differences_xlsx(diff: pd.DataFrame, columns: list[str],
                           combined: pd.DataFrame, count_date, prior_date,
                           basis: str) -> bytes:
    """A day's count differences beside the distribution that preceded them.

    Both sheets are the same shape with the same shop columns, so they can be
    added cell for cell. That is the whole point: a shop counting six short on
    Tuesday when six were dispatched to it on Monday has not lost anything, it
    simply had not received them yet, and only a like-for-like layout makes
    that legible.
    """
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        name = f"Differences {count_date:%d %b}"[:31]
        shaped, tiers = _shape(diff, columns)
        shaped.to_excel(writer, sheet_name=name, index=False)
        _style_sheet(writer.sheets[name], shaped, numeric=columns,
                     first_width=34, tiers=tiers)

        prior = f"Distribution {prior_date:%d %b}"[:31]
        if combined is not None and not combined.empty:
            cshaped, ctiers = _shape(combined, columns)
            cshaped.to_excel(writer, sheet_name=prior, index=False)
            _style_sheet(writer.sheets[prior], cshaped,
                         numeric=[c for c in columns if c in cshaped.columns],
                         first_width=34, tiers=ctiers)
        else:
            blank = pd.DataFrame(
                [{"bag_name": f"(nothing distributed on {prior_date:%d %b %Y})"}])
            blank.to_excel(writer, sheet_name=prior, index=False)
            _style_sheet(writer.sheets[prior], blank, numeric=(),
                         first_width=44)

        notes = pd.DataFrame([
            {"Note": f"Count date: {count_date:%d %b %Y}"},
            {"Note": f"Distribution date: {prior_date:%d %b %Y} (count date minus one day)"},
            {"Note": f"Cells on the differences sheet are {basis} minus Odoo, "
                     "using the Odoo figure the scan session recorded."},
            {"Note": "Shop columns use the distribution reports' own names "
                     "(DAR/Stock is SINZA), so the two sheets add cell for cell."},
            {"Note": "Combos are excluded — no counted quantity, no scannable unit."},
            {"Note": "CBD has no column: it is a hub in the distribution "
                     "reports, not a destination."},
        ])
        notes.to_excel(writer, sheet_name="Notes", index=False)
        _style_sheet(writer.sheets["Notes"], notes, numeric=(), first_width=100)

    return buffer.getvalue()


def count_differences_filename(count_date) -> str:
    return f"denri_count_differences_{count_date:%Y%m%d}.xlsx"


def count_sheet_xlsx(matrix: pd.DataFrame, tiers: pd.Series, location: str,
                     label: str) -> bytes:
    """One shop's count sheet, styled with its TOTAL rows picked out.

    Kept to the five columns the team's own sheet uses, in their order, so the
    file can sit alongside it without rearranging anything.
    """
    numeric = [c for c in (label, "SCANNED", "ODOO STOCKS", "DIFF")
               if c in matrix.columns]
    sheet_name = location.split("/")[0][:28] or "Count"

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        matrix.to_excel(writer, sheet_name=sheet_name, index=False)
        _style_sheet(writer.sheets[sheet_name], matrix, numeric=numeric,
                     first_width=40, tiers=tiers)
    return buffer.getvalue()


def count_sheet_filename(location: str, count_date) -> str:
    shop = location.split("/")[0].lower()
    return f"denri_count_{shop}_{count_date:%Y%m%d}.xlsx"


def scan_counts_xlsx(by_shop: pd.DataFrame, sessions: pd.DataFrame,
                     lines: pd.DataFrame) -> bytes:
    """QR stock counts: per shop, per session, and per product.

    "By Shop" carries each shop's best-covered attempt, which is the summary
    anyone asks for. "Sessions" keeps every session including the abandoned
    ones, because the retries are themselves the finding — a shop that opened
    sixteen sessions in a day is telling you something. "Product Detail" holds
    the counted-versus-system lines with a Scanned flag, so a variance can be
    traced to the products behind it.
    """
    def _timestamps(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        for column in ("Started", "Ended"):
            if column in out.columns:
                out[column] = pd.to_datetime(
                    out[column], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
        return out

    shop = _timestamps(by_shop)
    log = _timestamps(sessions)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        shop.to_excel(writer, sheet_name="By Shop", index=False)
        _style_sheet(
            writer.sheets["By Shop"], shop, first_width=22,
            numeric=[c for c in shop.columns
                     if pd.api.types.is_numeric_dtype(shop[c])],
            wide=("Counted By", "Started"))

        log.to_excel(writer, sheet_name="Sessions", index=False)
        _style_sheet(
            writer.sheets["Sessions"], log, first_width=12,
            numeric=[c for c in log.columns
                     if pd.api.types.is_numeric_dtype(log[c])],
            wide=("Location", "Counted By", "Started", "Ended", "Reference"))

        detail = lines if lines is not None and not lines.empty else pd.DataFrame(
            [{"Product": "(no lines in this range)"}])
        detail.to_excel(writer, sheet_name="Product Detail", index=False)
        _style_sheet(
            writer.sheets["Product Detail"], detail, first_width=12,
            numeric=[c for c in detail.columns
                     if pd.api.types.is_numeric_dtype(detail[c])],
            wide=("Product", "Location", "Status"))

    return buffer.getvalue()


def scan_counts_filename(start_date, end_date) -> str:
    return f"denri_stock_counts_{_stamp(start_date, end_date)}.xlsx"


def odoo_stock_xlsx(aligned: pd.DataFrame, extras: pd.DataFrame,
                    locations: list[str]) -> bytes:
    """Odoo's on-hand stock under the sheet's product names, in sheet order.

    "Odoo Stock" holds one row per product the sheet lists, so its rows line up
    with the sheet's own and the numbers can be pasted straight across. A total
    row closes it. "Not On Sheet" carries what Odoo holds under names the sheet
    does not use — it cannot sit in the aligned block without breaking that row
    correspondence, which is the one property making the first sheet useful.
    """
    numeric = [*locations, "TOTAL"]

    body = aligned.copy()
    grand = {"Product": "GRAND TOTAL"}
    grand.update({c: body[c].sum() for c in numeric})
    body = pd.concat([body, pd.DataFrame([grand])], ignore_index=True)
    tiers = [0] * (len(body) - 1) + [2]

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        body.to_excel(writer, sheet_name="Odoo Stock", index=False)
        _style_sheet(writer.sheets["Odoo Stock"], body, numeric=numeric,
                     first_width=38, tiers=pd.Series(tiers))

        shaped = extras if not extras.empty else pd.DataFrame(
            [{"Product": "(nothing — every Odoo product is named on the sheet)"}]
        )
        shaped.to_excel(writer, sheet_name="Not On Sheet", index=False)
        _style_sheet(writer.sheets["Not On Sheet"], shaped,
                     numeric=[c for c in numeric if c in shaped.columns],
                     first_width=38)

    return buffer.getvalue()


def odoo_stock_filename(count: int) -> str:
    return f"denri_odoo_stock_{count}shops_{datetime.now():%Y%m%d_%H%M}.xlsx"


def odoo_forwarding_filename() -> str:
    return f"denri_odoo_forwarding_{datetime.now():%Y%m%d_%H%M}.xlsx"


def _style_sheet(ws, frame: pd.DataFrame, *, numeric, first_width: int,
                 tiers=None, wide=()) -> None:
    """The header, borders, widths and number formats used by _workbook.

    Split out so a sheet that is not report-shaped — no bag_name column, no row
    tiers — can still look like the rest of the exports.
    """
    n_rows, n_cols = frame.shape
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center",
                                   wrap_text=True)
        cell.border = Border(bottom=_THIN)
    ws.row_dimensions[1].height = 28

    if tiers is not None:
        for offset, tier in enumerate(tiers, start=2):
            if tier == 0:
                continue
            fill = _GRAND_FILL if tier == 2 else _SUBTOTAL_FILL
            for cell in ws[offset]:
                cell.font = Font(bold=True, size=10)
                cell.fill = fill

    numeric = set(numeric)
    # A label column sized to its header would truncate the labels themselves,
    # which is the one thing it exists to show.
    wide = set(wide)
    for idx, name in enumerate(frame.columns, start=1):
        letter = get_column_letter(idx)
        if idx == 1:
            width = first_width
        elif name in wide:
            width = max(22, int(frame[name].astype(str).str.len().max()) + 3)
        else:
            width = max(11, len(str(name)) + 3)
        ws.column_dimensions[letter].width = width
        if name in numeric:
            for row in range(2, n_rows + 2):
                ws.cell(row=row, column=idx).number_format = "#,##0"

    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(n_cols)}{n_rows + 1}"


def transit_xlsx(df: pd.DataFrame, columns: list[str], *, channels_only: bool,
                 bags_only: bool = False) -> bytes:
    if bags_only:
        sheet = "Sinza & Uganda by bag"
    else:
        sheet = "Sinza & Uganda in transit" if channels_only else "Goods in Transit"
    # Callers pass the destination columns; TOTAL is appended here so neither
    # call site can ship a sheet without it.
    cols = [*columns, "TOTAL"] if "TOTAL" not in columns else list(columns)
    return _workbook(df, cols, sheet)


def _stamp(start_date, end_date) -> str:
    now = datetime.now().strftime("%Y%m%d%H%M")
    if start_date == end_date:
        return f"{start_date:%Y%m%d}_{now}"
    return f"{start_date:%Y%m%d}-{end_date:%Y%m%d}_{now}"


def filename(start_date, end_date) -> str:
    """combined_<range>_<generated-at>.xlsx — the range is what makes two
    exports comparable, the timestamp is what keeps them from overwriting."""
    return f"combined_{_stamp(start_date, end_date)}.xlsx"


def bags_sold_filename(start_date, end_date) -> str:
    return f"bags_sold_{_stamp(start_date, end_date)}.xlsx"


def dispatch_filename(start_date, end_date, *, with_cbd: bool) -> str:
    variant = "with_cbd" if with_cbd else "no_cbd"
    return f"dispatch_{variant}_{_stamp(start_date, end_date)}.xlsx"


def transit_filename(start_date, end_date, *, channels_only: bool,
                     bags_only: bool = False) -> str:
    variant = "sinza_uganda" if channels_only else "all"
    if bags_only:
        variant += "_bags"
    return f"in_transit_{variant}_{_stamp(start_date, end_date)}.xlsx"
