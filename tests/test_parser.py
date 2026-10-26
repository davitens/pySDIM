"""Unit tests for the SDIM export parser (no network required).

Run:  python3 tests/test_parser.py
"""

import io
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdim.parser import (
    parse_export, parse_quality, parse_quantity, _fix_mojibake, _parse_value,
)

FIXTURE = Path(__file__).parent / "data" / "ter_conductivity.xlsx"


def main() -> int:
    # openpyxl's "no default style" warning on SDIM exports is silenced
    import warnings
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        parse_export(FIXTURE)
    assert not [w for w in caught if "default style" in str(w.message)], caught

    parsed = parse_export(FIXTURE)
    assert "quality" in parsed, "expected a quality sheet"
    df = parsed["quality"]
    assert not df.empty, "quality sheet should not be empty"
    assert len(df) == 18, f"expected 18 rows, got {len(df)}"
    assert list(df.columns) == [
        "date", "station_code", "mass_code", "mass_name", "variable", "utm_x",
        "utm_y", "unit", "value_raw", "value", "qualifier", "depth_m",
        "well_depth_m", "piezometric_level_masl", "source_sheet",
    ]
    assert df["value"].notna().all(), "expected numeric values"
    assert str(df["date"].dtype).startswith("datetime64"), df["date"].dtype
    assert str(df["date"].iloc[0].date()) == "2007-09-17"
    assert df["utm_x"].dtype == float and df["utm_x"].iloc[0] == 446469.0
    assert "Conductivitat" in str(df["variable"].iloc[0])
    assert df["unit"].iloc[0] == "µS/cm"

    # detection-limit / qualifier parsing
    assert _parse_value("-") == (None, None)
    assert _parse_value("<0.01") == (0.01, "<")
    assert _parse_value(">100") == (100.0, ">")
    assert _parse_value("ND") == (None, "ND")
    assert _parse_value("0,5") == (0.5, None)

    check_mojibake_headers()

    print("OK: all parser tests passed (%d rows)" % len(df))
    return 0


def _mojibake(text: str) -> str:
    """Mis-decode UTF-8 as Latin-1, as live SDIM exports do."""
    return text.encode("utf-8").decode("latin-1")


def _live_like_export() -> bytes:
    """Two-sheet export shaped like a live SDIM report, with mojibake headers."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Programa de Seguiment i Control"
    ws.append([None, _mojibake("Resultats analítics de qualitat de les masses d'aigua")])
    ws.append([None, "Xarxes de Control", None, "Elements biològics"])
    ws.append([None, "Data", _mojibake("Codi Estació"), "Codi massa d'aigua",
               "Massa d'aigua", "UTM X", "UTM Y", "Variable",
               "Profunditat mostra (m)", "Valor", "Unitat Mesura",
               _mojibake("Fondària Pou (m)"),
               _mojibake("Cota del nivell piezomètric (m.s.n.m)"), "Columna nova"])
    ws.append([None, "2008/11/06", "200046000", "2000460",
               "El Ter des de Flaçà fins al mar", "512618.00", "4652593.00",
               "índex IPS", "-", "9.300000000", "Sense unitats", "45.5", "12.25", "x"])
    wq = wb.create_sheet("Quantitat d'aigua disponible")
    wq.append([None, "Dades de quantitat d'aigua del medi"])
    wq.append([None, "Data", _mojibake("Estació"), "Conca", "UTM X", "UTM Y",
               "Variable", "Mitjana", "Unitat Mesura"])
    wq.append([None, "2020/01/01", "Aforament - Girona (Ter)", "Ter", "1", "2",
               "EA010_Girona_Cabal riu Ter", "3.5", "m3/s"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def check_mojibake_headers() -> None:
    assert _fix_mojibake(_mojibake("Codi Estació")) == "Codi Estació"
    # correctly encoded text is left alone
    for text in ("índex IPS", "El Ter des de Flaçà fins al mar", "µS/cm"):
        assert _fix_mojibake(text) == text

    parsed = parse_export(_live_like_export())
    q = parsed["quality"]
    assert q["station_code"].tolist() == ["200046000"], q["station_code"].tolist()
    assert q["variable"].iloc[0] == "índex IPS"
    assert q["mass_name"].iloc[0] == "El Ter des de Flaçà fins al mar"
    assert q["value"].iloc[0] == 9.3
    # columns the parser used to drop
    assert pd.isna(q["depth_m"].iloc[0])  # "-"
    assert q["well_depth_m"].iloc[0] == 45.5
    assert q["piezometric_level_masl"].iloc[0] == 12.25
    assert q["Columna nova"].iloc[0] == "x", "unknown headers are kept"
    assert list(q.columns)[-1] == "source_sheet"
    # quantity "Estació" is a name; the code is the series prefix
    qq = parsed["quantity"]
    assert qq["station_code"].tolist() == ["EA010"], qq["station_code"].tolist()
    assert qq["station_name"].tolist() == ["Aforament - Girona (Ter)"]
    assert qq["value"].iloc[0] == 3.5


if __name__ == "__main__":
    sys.exit(main())


def test_parser():
    assert main() == 0
