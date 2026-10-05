"""Excel-style per-column header filtering for detail tables, via AgGrid."""
from __future__ import annotations

import datetime as dt
import json
import re

import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

_CURRENCY_FORMATTER = JsCode(
    "function(params) {"
    "  if (params.value === null || params.value === undefined) return '';"
    "  return 'KES ' + Number(params.value).toLocaleString(undefined, "
    "    {minimumFractionDigits: 2, maximumFractionDigits: 2});"
    "}"
)


def _stringify_dates(df: pd.DataFrame) -> pd.DataFrame:
    """AgGrid's JSON payload can't carry raw date/datetime objects — a column of
    Python date objects renders as "[object Object]" client-side. Convert to ISO
    strings so the grid gets a plain, filterable value."""
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
        elif df[col].dtype == "object" and df[col].map(lambda v: isinstance(v, (dt.date, dt.datetime))).any():
            df[col] = df[col].map(lambda v: v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v)
    return df


# Columns not worth adding up: shares, rates, averages, prices, positions.
_NOT_SUMMED = re.compile(r"%|rate|avg|average|price|share|rank|per order|per bag|"
                         r"\bid\b|year|month|week|phone|value$|score", re.IGNORECASE)


def _total_row_js(label_col: str | None, sum_cols: list[str]) -> JsCode:
    """Keep a TOTAL row pinned under the grid, recomputed from whatever rows
    the filters leave showing — filter Locations to Thika and the total is
    Thika's. Rows already labelled as totals (category subtotals, a GRAND
    TOTAL) are skipped, so nothing is counted twice."""
    return JsCode(
        "function(params) {"
        "  const api = params.api;"
        f"  const sumCols = {json.dumps(sum_cols)};"
        f"  const labelCol = {json.dumps(label_col)};"
        "  const isTotal = (d) => Object.values(d).some(v => typeof v === 'string' && /total/i.test(v));"
        "  const tot = {}; sumCols.forEach(c => tot[c] = 0);"
        "  let n = 0;"
        "  api.forEachNodeAfterFilter(node => {"
        "    const d = node.data; if (!d || isTotal(d)) return;"
        "    n += 1;"
        "    sumCols.forEach(c => { const v = Number(d[c]); if (!isNaN(v)) tot[c] += v; });"
        "  });"
        "  sumCols.forEach(c => tot[c] = Math.round(tot[c] * 100) / 100);"
        "  if (labelCol) tot[labelCol] = 'TOTAL (' + n.toLocaleString() + ' rows)';"
        "  if (api.setGridOption) api.setGridOption('pinnedBottomRowData', [tot]);"
        "  else api.setPinnedBottomRowData([tot]);"
        "}"
    )


def _has_total_rows(df: pd.DataFrame) -> bool:
    text = df.select_dtypes(include="object")
    return bool(text.apply(lambda col: col.astype(str).str.contains("total", case=False)).any().any())         if not text.empty else False


def filterable_table(
    df: pd.DataFrame,
    *,
    currency_columns: tuple[str, ...] = (),
    pinned_columns: tuple[str, ...] = (),
    height: int = 480,
    total: bool = True,
) -> None:
    """Render df as a grid with a filter row under every column header.

    pinned_columns stay fixed on the left as the grid scrolls horizontally —
    useful for a row-identifying column (e.g. product name) on wide tables.

    total adds a TOTAL row pinned at the bottom, summing the countable
    columns over the rows currently shown. It is left off a table that
    already carries its own total rows.
    """
    df = _stringify_dates(df)
    gb = GridOptionsBuilder.from_dataframe(df)
    # minWidth stops the grid from auto-shrinking columns (especially with a
    # pinned column) to the point headers get truncated — it scrolls
    # horizontally instead, which the toolbar/filter row already supports.
    gb.configure_default_column(filter=True, floatingFilter=True, sortable=True, resizable=True, minWidth=120)
    for col in currency_columns:
        if col in df.columns:
            gb.configure_column(col, type=["numericColumn"], filter="agNumberColumnFilter",
                                 valueFormatter=_CURRENCY_FORMATTER)
    for col in pinned_columns:
        if col in df.columns:
            gb.configure_column(col, pinned="left", minWidth=180)
    options = gb.build()
    if total and not df.empty and not _has_total_rows(df):
        numeric = [c for c in df.columns
                   if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])
                   and not _NOT_SUMMED.search(str(c))]
        text = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        label = (pinned_columns[0] if pinned_columns and pinned_columns[0] in df.columns
                 else text[0] if text else None)
        if numeric:
            js = _total_row_js(label, numeric)
            options["onFirstDataRendered"] = js
            options["onFilterChanged"] = js
            options["onRowDataUpdated"] = js
            options["getRowStyle"] = JsCode(
                "function(p) { if (p.node.rowPinned === 'bottom') "
                "return {fontWeight: 'bold', borderTop: '2px solid rgba(255,255,255,0.35)'}; }")
    AgGrid(
        df,
        gridOptions=options,
        height=height,
        allow_unsafe_jscode=True,
        show_toolbar=True,
        show_search=True,
        show_download_button=True,
    )
