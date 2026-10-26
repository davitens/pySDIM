"""Tests for the name-resolution layer (offline, catalog-based).

Run:  python3 tests/test_resolver.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdim.catalog import Catalog
from sdim.exceptions import SDIMQueryError
from sdim.resolver import WATER_TYPES, resolve_parameter, resolve_request

META = Path(__file__).resolve().parent.parent / "metadata"
cat = Catalog(META)


def _raises(fn, *args, **kw) -> bool:
    try:
        fn(*args, **kw)
        return False
    except SDIMQueryError:
        return True


def main() -> int:
    assert resolve_parameter(cat, "nitrate", "after_2007") == "0016"
    assert resolve_parameter(cat, "no3", "after_2007") == "0016"
    assert resolve_parameter(cat, "phosphate", "after_2007") == "0006"

    r = resolve_request(cat, period="after_2007", water_type="groundwater",
                        parameters=["nitrate"], start="2007-01-01", end="2009-01-01")
    assert r.target_id == "after_2007:0005:0010"
    assert ("v", "0016") in r.variable_kinds

    r = resolve_request(cat, period="after_2007", water_type="river",
                        rivers=["Ter"], parameters=["nitrate"],
                        start="2007-01-01", end="2009-01-01")
    assert r.ambit == "riu" and r.spatial == {"riuAmbit": ["200"]}

    r = resolve_request(cat, period="after_2007", water_type="river",
                        rivers=["Llobregat"], parameters=["nitrate"],
                        start="2007-01-01", end="2009-01-01")
    assert r.spatial == {"riuAmbit": ["100"]}

    r = resolve_request(cat, period="after_2007", water_type="levels",
                        start="2007-01-01", end="2009-01-01")
    assert r.target_id == "after_2007:0005:0011"

    r = resolve_request(cat, period="after_2007", target="after_2007:0001:0301",
                        start="2007-01-01", end="2009-01-01")
    assert r.target_id == "after_2007:0001:0301"

    r = resolve_request(cat, period="before_2007", water_type="groundwater",
                        parameters=["nitrate"], start="1995-01-01", end="2006-12-31")
    assert r.target_id == "before_2007:0000:0019"

    # a target id that embeds its own period must win over the default period
    r = resolve_request(cat, target="before_2007:0000:0019", comarcas=["Baix Empordà"],
                        parameters=["conductivitat"], start="1950-01-01", end="2006-12-31")
    assert r.target_id == "before_2007:0000:0019"
    assert r.period == "before_2007"
    assert ("f", "050004") in r.variable_kinds and ("v", "0002") in r.variable_kinds
    assert r.spatial == {"comarcaAmbit": ["10"]} and r.ambit == "comarques"

    r = resolve_request(cat, period="after_2007", target="after_2007:0005:0011",
                        stations=["F000025"], start="2007-01-01", end="2009-01-01")
    assert r.stations and "F000025" in r.stations
    assert r.stations["F000025"] == ["F000025NPM"]

    r = resolve_request(cat, period="after_2007", target="after_2007:0005:0010",
                        stations={"F000100": ["nitrate"]},
                        start="2007-01-01", end="2009-01-01")
    assert "F000100" in r.stations and r.stations["F000100"]

    assert _raises(resolve_request, cat, period="after_2007", water_type="river",
                   rivers=["Ter"], comarcas=["Osona"],
                   start="2007-01-01", end="2009-01-01"), "expected multi-ambit error"

    r = resolve_request(cat, period="after_2007", water_type="river",
                        rivers=["Ter"], parameters=["nitrate"], stations=["F007528"],
                        start="2007-01-01", end="2009-01-01")
    q = r.to_query()
    assert q.networks == ["0001"] and q.subnetworks == ["0022"] and q.ambit == "riu"

    # biological indices: water types, implied group and explicit groups
    r = resolve_request(cat, water_type="river_biology", comarcas=["Baix Empordà"],
                        start="2008-01-01", end="2026-01-01")
    assert r.target_id == "after_2007:0001:0001"
    assert ("g", "6") in r.variable_kinds and ("v", "2049") in r.variable_kinds
    assert "índex IBMWP" in r.series_filter

    r = resolve_request(cat, water_type="river-biology",
                        start="2008-01-01", end="2026-01-01")
    assert r.target_id == "after_2007:0001:0001"

    r = resolve_request(cat, water_type="river", groups=["Índexs biològics"],
                        start="2008-01-01", end="2026-01-01")
    assert r.target_id == "after_2007:0001:0001"

    r = resolve_request(cat, water_type="river", groups=["invertebrats"],
                        start="2008-01-01", end="2026-01-01")
    assert r.target_id == "after_2007:0001:0001"
    assert r.series_filter == ["índex IBMWP"]

    r = resolve_request(cat, water_type="lake_biology", start="2008-01-01", end="2026-01-01")
    assert r.target_id == "after_2007:0003:0005"
    r = resolve_request(cat, water_type="coastal_biology", start="2008-01-01", end="2026-01-01")
    assert r.target_id == "after_2007:0004:0007"

    # before 2007 biology shares a target with phys-chem: only index series kept
    r = resolve_request(cat, period="before_2007", water_type="river_biology",
                        start="1990-01-01", end="2006-12-31")
    assert r.target_id == "before_2007:0000:0017"
    assert {k for k, _ in r.variable_kinds if k == "g"} and all(
        x == "6" for k, x in r.variable_kinds if k == "g")
    assert "índex BMWPC" in r.series_filter

    # groups narrow a physico-chemical target too
    r = resolve_request(cat, water_type="river", groups=["Nutrients"],
                        start="2008-01-01", end="2009-01-01")
    assert r.target_id == "after_2007:0001:0022" and ("v", "0016") in r.variable_kinds
    assert ("v", "0002") not in r.variable_kinds  # conductivity is "Salinitat"

    assert _raises(resolve_request, cat, target="after_2007:0001:0301",
                   groups=["Invertebrats"], start="2008-01-01", end="2009-01-01")

    # every water type points at networks and default targets that exist
    for name, per_period in WATER_TYPES.items():
        for period, (nets, seed) in per_period.items():
            assert set(nets) <= set(cat.targets(period).network), (name, period, nets)
            if seed:
                assert cat.target(f"{period}:{seed[0]}:{seed[1]}") is not None, (name, period, seed)

    # Catalan aliases and targets.csv categories work as water types
    r = resolve_request(cat, water_type="cabals", start="2020-01-01", end="2020-02-01")
    assert r.target_id == "after_2007:0001:0301"
    r = resolve_request(cat, water_type="hydromorphological", start="2020-01-01", end="2020-02-01")
    assert "hydromorphological" in cat.target(r.target_id).category
    try:
        resolve_request(cat, water_type="lava", start="2020-01-01", end="2020-02-01")
        raise AssertionError("expected unknown water_type error")
    except SDIMQueryError as exc:
        assert "river_biology" in str(exc)

    print("OK: resolver tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def test_resolver():
    assert main() == 0
