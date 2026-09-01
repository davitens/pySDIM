"""Parse SDIM report exports into tidy DataFrames.

SDIM returns files named ``.xls`` that are actually XLSX (Open XML zip)
containers. A report has two blocks:

* quality sheet  -> one row per measurement
                    (date, station/mass code, mass name, coords, variable, value, unit)
* quantity sheet -> quantity time series
                    (date, station, basin, coords, variable, mean, unit)

Detection-limit style values (``<0.01``, ``>100``, ``ND``, ``-``) are preserved
in ``value_raw`` and exposed via ``value``/``qualifier`` without silent coercion.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pandas as pd

QUALITY_WINDOW = 12
HEADER_MARK = "massa d'aigua"
QUANTITY_MARK = "mitjana"


def _load_sheets(source: str | Path | bytes) -> list[tuple[str, list[list[str]]]]:
    """Return (sheet_title, rows) for an XLSX container from path or bytes."""
    import openpyxl

    if isinstance(source, bytes):
        raw = source
    else:
        raw = Path(source).read_bytes()
    if raw[:2] != b"PK":
        raise ValueError("Unsupported SDIM export format (expected an XLSX container).")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as fh:
        fh.write(raw)
        tmp_name = fh.name
    wb = openpyxl.load_workbook(tmp_name, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = [[c if c is not None else "" for c in row] for row in ws.iter_rows(values_only=True)]
        sheets.append((ws.title, rows))
    return sheets


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    """Locate the column-header row; returns (row_index, name->column_index)."""
    for i, row in enumerate(rows):
        flat = [str(c).strip() for c in row if str(c).strip()]
        low = [c.lower() for c in flat]
        if "data" in low and ("variable" in low or "estació" in low):
            idx = {}
            for j, name in enumerate(row):
                if str(name).strip():
                    idx[str(name).strip()] = j
            return i, idx
    return None


def _metadata(rows: list[list[str]], header_idx: int) -> dict[str, str]:
    meta = {}
    for row in rows[:header_idx]:
        cells = [str(c).strip() for c in row if str(c).strip()]
        if len(cells) >= 2:
            meta[cells[0]] = cells[1]
    return meta


def parse_quality(rows: list[list[str]]) -> pd.DataFrame:
    header = _find_header(rows)
    if header is None:
        return pd.DataFrame()
    header_idx, idx = header
    meta = _metadata(rows, header_idx)

    records = []
    for row in rows[header_idx + 1:]:
        if not any(str(c).strip() for c in row):
            continue
        rec = {"network": meta.get("Xarxes de Control", "")}
        for name, j in idx.items():
            if j < len(row):
                rec[name] = row[j]
        records.append(rec)
    df = pd.DataFrame(records)
    if df.empty:
        return df

    def col(*names):
        for name in names:
            if name in idx:
                return name
        return None

    value_col = col("Valor")
    out = pd.DataFrame({
        "date": df[col("Data")] if col("Data") else None,
        "station_code": df[col("Codi Estació", "Estació")] if col("Codi Estació", "Estació") else None,
        "mass_code": df[col("Codi massa d'aigua")] if col("Codi massa d'aigua") else None,
        "mass_name": df[col("Massa d'aigua")] if col("Massa d'aigua") else None,
        "variable": df[col("Variable")] if col("Variable") else None,
        "utm_x": df[col("UTM X")] if col("UTM X") else None,
        "utm_y": df[col("UTM Y")] if col("UTM Y") else None,
        "unit": df[col("Unitat Mesura")] if col("Unitat Mesura") else None,
    })
    if value_col:
        raw_vals = df[value_col].astype(str)
        parsed = raw_vals.map(_parse_value)
        out["value_raw"] = raw_vals
        out["value"] = parsed.map(lambda v: v[0])
        out["qualifier"] = parsed.map(lambda v: v[1])
    else:
        out["value_raw"], out["value"], out["qualifier"] = None, None, None
    out["source_sheet"] = "quality"
    return out


def parse_quantity(rows: list[list[str]]) -> pd.DataFrame:
    header = _find_header(rows)
    if header is None:
        return pd.DataFrame()
    header_idx, idx = header
    meta = _metadata(rows, header_idx)

    records = []
    for row in rows[header_idx + 1:]:
        if not any(str(c).strip() for c in row):
            continue
        rec = {"network": meta.get("Xarxes de Control", "")}
        for name, j in idx.items():
            if j < len(row):
                rec[name] = row[j]
        records.append(rec)
    df = pd.DataFrame(records)
    if df.empty:
        return df

    def col(*names):
        for name in names:
            if name in idx:
                return name
        return None

    value_col = col("Mitjana")
    out = pd.DataFrame({
        "date": df[col("Data")] if col("Data") else None,
        "station_code": df[col("Estació", "Codi Estació")] if col("Estació", "Codi Estació") else None,
        "basin": df[col("Conca")] if col("Conca") else None,
        "variable": df[col("Variable")] if col("Variable") else None,
        "utm_x": df[col("UTM X")] if col("UTM X") else None,
        "utm_y": df[col("UTM Y")] if col("UTM Y") else None,
        "unit": df[col("Unitat Mesura")] if col("Unitat Mesura") else None,
    })
    if value_col:
        raw_vals = df[value_col].astype(str)
        parsed = raw_vals.map(_parse_value)
        out["value_raw"] = raw_vals
        out["value"] = parsed.map(lambda v: v[0])
        out["qualifier"] = parsed.map(lambda v: v[1])
    else:
        out["value_raw"], out["value"], out["qualifier"] = None, None, None
    out["source_sheet"] = "quantity"
    return out


def _parse_value(text: str) -> tuple[float | None, str | None]:
    """Return (numeric_value, qualifier), preserving detection-limit text."""
    text = text.strip()
    if text == "" or text == "-":
        return None, None
    match = re.fullmatch(r"([<>])?\s*([+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?)", text)
    if match:
        sign, num = match.groups()
        return float(num.replace(",", ".")), sign
    return None, text


def parse_export(source: str | Path | bytes) -> dict[str, pd.DataFrame]:
    """Parse an SDIM export into ``{"quality": DF, "quantity": DF}``."""
    sheets = _load_sheets(source)
    result: dict[str, pd.DataFrame] = {}
    for _title, rows in sheets:
        window = " ".join(str(c).lower() for row in rows[:QUALITY_WINDOW] for c in row if isinstance(c, str))
        is_quality = HEADER_MARK in window
        is_quantity = QUANTITY_MARK in window
        if is_quantity and not is_quality:
            result["quantity"] = parse_quantity(rows)
        elif is_quality:
            result["quality"] = parse_quality(rows)
    return result