"""Tests for the metadata catalog (no network required).

Run:  python3 tests/test_catalog.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdim.catalog import Catalog

_ROOT = Path(__file__).resolve().parent.parent
META = _ROOT / "metadata"


def main() -> int:
    cat = Catalog(META)

    rivers = cat.rivers("ter", period="after_2007")
    assert not rivers.empty
    row = rivers[rivers.code == "200"]
    assert not row.empty and row.iloc[0]["name"] == "RIU TER"

    cond = cat.search_variables("conductivitat", period="after_2007")
    assert not cond.empty
    assert (cond.v == "0002").any(), "expected Conductivitat v=0002"
    assert (cond.f == "050004").any() and (cond.g == "5").any()

    nit = cat.search_variables("nitrat", period="after_2007")
    assert not nit.empty

    net = cat.table("networks")
    assert (net.code == "0001").any(), "expected CONTROL RIUS 0001"
    subs = cat.table("subnetworks")
    assert (subs.code == "0022").any()

    st = cat.station_codes()
    assert "F007528" in st

    print("OK: catalog tests passed (" + str(len(net)) + " networks, "
          + str(len(cat.table("stations"))) + " stations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())