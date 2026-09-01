"""Tests for the targets inventory + station-variable tables (no network).

Run:  python3 tests/test_targets.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from sdim.catalog import Catalog

META = Path(__file__).resolve().parent.parent / "metadata"


def main() -> int:
    cat = Catalog(META)
    targets = cat.targets(period="after_2007")
    assert len(targets) == len(targets.drop_duplicates("id"))

    gw = cat.target("after_2007:0005:0010")
    assert gw is not None
    assert gw["subnetwork_name"] == "Elements fisicoquímics"
    assert int(gw["station_count"]) > 0 and int(gw["series_count"]) > 0

    piezo = cat.target("after_2007:0005:0011")
    assert "groundwater levels" in piezo["category"]

    cabals = cat.target("after_2007:0001:0301")
    assert "quantity" in cabals["category"]

    sv = cat.target_station_variables("after_2007:0005:0011")
    assert not sv.empty
    assert {"station", "variable_id", "variable_name", "x", "y"} <= set(sv.columns)

    merged = cat.station_variables()
    assert len(merged) > 300_000
    assert {"period", "network", "subnetwork"} <= set(merged.columns)

    # a variable series resolvable for an actual download
    row = sv.iloc[0]
    assert row["variable_name"] == "Nivell piezomètric"

    print(f"OK: targets tests passed ({targets.shape[0]} after-2007 targets, "
          f"{len(merged)} series)")
    return 0


if __name__ == "__main__":
    sys.exit(main())