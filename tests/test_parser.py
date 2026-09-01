"""Unit tests for the SDIM export parser (no network required).

Run:  python3 tests/test_parser.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdim.parser import parse_export, parse_quality, parse_quantity, _parse_value

FIXTURE = Path(__file__).parent / "data" / "ter_conductivity.xlsx"


def main() -> int:
    parsed = parse_export(FIXTURE)
    assert "quality" in parsed, "expected a quality sheet"
    df = parsed["quality"]
    assert not df.empty, "quality sheet should not be empty"
    assert len(df) == 18, f"expected 18 rows, got {len(df)}"
    assert list(df.columns) == [
        "date", "station_code", "mass_code", "mass_name", "variable", "utm_x",
        "utm_y", "unit", "value_raw", "value", "qualifier", "source_sheet",
    ]
    assert df["value"].notna().all(), "expected numeric values"
    assert "Conductivitat" in str(df["variable"].iloc[0])
    assert df["unit"].iloc[0] == "µS/cm"

    # detection-limit / qualifier parsing
    assert _parse_value("-") == (None, None)
    assert _parse_value("<0.01") == (0.01, "<")
    assert _parse_value(">100") == (100.0, ">")
    assert _parse_value("ND") == (None, "ND")
    assert _parse_value("0,5") == (0.5, None)

    print("OK: all parser tests passed (%d rows)" % len(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())