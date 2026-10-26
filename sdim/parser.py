"""Parse SDIM report exports into tidy DataFrames.

SDIM returns files named ``.xls`` that are actually XLSX (Open XML zip)
containers. A report has two blocks:

* quality sheet  -> one row per measurement
                    (date, station/mass code, mass name, coords, variable, value, unit)
* quantity sheet -> quantity time series
                    (date, station code/name, basin, coords, variable, mean, unit)

Dates are parsed to ``datetime64``, coordinates and depths to floats. Columns
the client does not know yet are kept under their export header.

Live exports may carry UTF-8 text mis-decoded as Latin-1 (``Codi EstaciÃ³``);
such cells are repaired on load so column lookups match the real names.

Detection-limit style values (``<0.01``, ``>100``, ``ND``, ``-``) are preserved
in ``value_raw`` and exposed via ``value``/``qualifier`` without silent coercion.
"""

from __future__ import annotations

import re
import tempfile
import unicodedata
from pathlib import Path

import pandas as pd

QUALITY_WINDOW = 12
HEADER_MARK = "massa d'aigua"
QUANTITY_MARK = "mitjana"


def _fix_mojibake(text: str) -> str:
    """Undo UTF-8 text that was decoded as Latin-1 (``EstaciÃ³`` -> ``Estació``).

    Correctly encoded text (``índex``, ``Flaçà``) is not valid UTF-8 once
    re-encoded as Latin-1, so it is returned unchanged.
    """
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


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
        rows = [
            [_fix_mojibake(c) if isinstance(c, str) else ("" if c is None else c) for c in row]
            for row in ws.iter_rows(values_only=True)
        ]
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


# output column -> export header names (matched accent- and case-insensitively)
_QUALITY_COLUMNS = {
    "date": ("Data",),
    "station_code": ("Codi Estació", "Estació"),
    "mass_code": ("Codi massa d'aigua",),
    "mass_name": ("Massa d'aigua",),
    "variable": ("Variable",),
    "utm_x": ("UTM X",),
    "utm_y": ("UTM Y",),
    "unit": ("Unitat Mesura",),
}
_QUALITY_VALUE = ("Valor",)
# extra measurement context, kept as numbers after the value columns
_QUALITY_EXTRAS = {
    "depth_m": ("Profunditat mostra (m)",),
    "well_depth_m": ("Fondària Pou (m)",),
    "piezometric_level_masl": ("Cota del nivell piezomètric (m.s.n.m)",),
}
# the quantity "Estació" column holds the station *name*; its code is the
# prefix of the series name ("EA010_Girona_Cabal riu Ter" -> "EA010")
_QUANTITY_COLUMNS = {
    "date": ("Data",),
    "station_code": ("Codi Estació",),
    "station_name": ("Estació",),
    "basin": ("Conca",),
    "variable": ("Variable",),
    "utm_x": ("UTM X",),
    "utm_y": ("UTM Y",),
    "unit": ("Unitat Mesura",),
}
_QUANTITY_VALUE = ("Mitjana",)
_NUMERIC = ("utm_x", "utm_y", *_QUALITY_EXTRAS)


def _key(name: str) -> str:
    return unicodedata.normalize("NFD", str(name)).encode("ascii", "ignore").decode().lower().strip()


def _records(rows: list[list[str]]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Data rows below the header as a DataFrame keyed by normalized header."""
    header = _find_header(rows)
    if header is None:
        return pd.DataFrame(), {}
    header_idx, idx = header
    names = {_key(name): name for name in idx}
    records = []
    for row in rows[header_idx + 1:]:
        if not any(str(c).strip() for c in row):
            continue
        records.append({_key(name): row[j] if j < len(row) else "" for name, j in idx.items()})
    return pd.DataFrame(records, columns=list(names)), names


def _to_number(values: pd.Series) -> pd.Series:
    return values.astype(str).map(lambda v: _parse_value(v)[0]).astype(float)


def _to_datetime(values: pd.Series) -> pd.Series:
    """SDIM dates are ``YYYY/MM/DD`` (optionally with a time); other layouts
    fall back to pandas' format inference. Unparseable dates become NaT."""
    text = values.astype(str).str.strip()
    out = pd.to_datetime(text, format="%Y/%m/%d", errors="coerce")
    rest = out.isna() & (text != "")
    if rest.any():
        out[rest] = pd.to_datetime(text[rest], format="mixed", errors="coerce")
    return out


def _build(df: pd.DataFrame, names: dict[str, str], columns: dict, value: tuple,
           extras: dict, sheet: str) -> pd.DataFrame:
    used: set[str] = set()

    def pick(aliases):
        for alias in aliases:
            k = _key(alias)
            if k in df.columns:
                used.add(k)
                return df[k]
        return None

    out = pd.DataFrame(index=df.index)
    for col, aliases in columns.items():
        out[col] = pick(aliases)
    raw = pick(value)
    if raw is not None:
        raw_vals = raw.astype(str)
        parsed = raw_vals.map(_parse_value)
        out["value_raw"] = raw_vals
        out["value"] = parsed.map(lambda v: v[0]).astype(float)
        out["qualifier"] = parsed.map(lambda v: v[1])
    else:
        out["value_raw"], out["value"], out["qualifier"] = None, None, None
    for col, aliases in extras.items():
        out[col] = pick(aliases)
    # any header SDIM adds later is kept under its original name
    for k in df.columns:
        if k not in used and names[k] not in out.columns:
            out[names[k]] = df[k]
    out["date"] = _to_datetime(out["date"]) if out["date"].notna().any() else pd.NaT
    for col in _NUMERIC:
        if col in out and out[col].notna().any():
            out[col] = _to_number(out[col])
    out["source_sheet"] = sheet
    return out.reset_index(drop=True)


def parse_quality(rows: list[list[str]]) -> pd.DataFrame:
    df, names = _records(rows)
    if df.empty:
        return pd.DataFrame()
    return _build(df, names, _QUALITY_COLUMNS, _QUALITY_VALUE, _QUALITY_EXTRAS, "quality")


def parse_quantity(rows: list[list[str]]) -> pd.DataFrame:
    df, names = _records(rows)
    if df.empty:
        return pd.DataFrame()
    out = _build(df, names, _QUANTITY_COLUMNS, _QUANTITY_VALUE, {}, "quantity")
    if out["station_code"].isna().all() and out["variable"].notna().any():
        out["station_code"] = out["variable"].astype(str).str.extract(r"^([^_\s]+)_", expand=False)
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