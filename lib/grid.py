"""Excel-style per-column header filtering for detail tables, via AgGrid."""
from __future__ import annotations

import datetime as dt

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


def filterable_table(
    df: pd.DataFrame,
    *,
    currency_columns: tuple[str, ...] = (),
    pinned_columns: tuple[str, ...] = (),
    height: int = 480,
) -> None:
    """Render df as a grid with a filter row under every column header.

    pinned_columns stay fixed on the left as the grid scrolls horizontally —
    useful for a row-identifying column (e.g. product name) on wide tables.
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
    AgGrid(
        df,
        gridOptions=gb.build(),
        height=height,
        allow_unsafe_jscode=True,
        show_toolbar=True,
        show_search=True,
        show_download_button=True,
    )
