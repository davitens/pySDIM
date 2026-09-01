"""Target-first example: download groundwater levels for a chosen target.

The SDIM web app asks for a *target* first (period + network + subnetwork),
because each target has its own stations. This example:

1. lists targets,
2. picks the piezometry target,
3. picks one station + its level series from the catalog,
4. downloads and prints the levels.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdim import Catalog, Query, SDIM

TARGET = "after_2007:0005:0011"  # groundwater levels (piezometry)

cat = Catalog("metadata")

target = cat.target(TARGET) if TARGET else None
if target is None:
    print("targets:")
    print(cat.targets(period="after_2007")[["id", "subnetwork_name", "category",
                                           "station_count"]].to_string(index=False))
    raise SystemExit(1)

print(f"target: {target['id']} — {target['subnetwork_name']} ({target['category']})")

series = cat.target_station_variables(TARGET)
station = series.iloc[0]
print(f"station {station['station']} ({station['station_name']}), "
      f"series {station['variable_id']} = {station['variable_name']}")

# g/f/v kinds for the target (needed in the report payload)
variables = cat.table("variables")
tv = variables[(variables.period == "after_2007")
               & (variables.network == "0005") & (variables.subnetwork == "0011")]
kinds = [("g", x) for x in tv.g.unique()] + [("f", x) for x in tv.f.unique()] \
    + [("v", x) for x in tv.v.unique()]

query = Query(
    period="after_2007",
    networks=["0005"],
    subnetworks=["0011"],
    variable_kinds=kinds,
    ambit="catalunya",
    stations={station["station"]: [station["variable_id"]]},
    start="2007-01-01",
    end="2010-12-31",
)

aca = SDIM(delay=0.5)
try:
    parsed = aca.get_data(query)
finally:
    aca.close()

df = parsed["quality"]
print(df[["date", "station_code", "variable", "value", "unit"]].head(10).to_string(index=False))
print(f"\n{len(df)} readings")