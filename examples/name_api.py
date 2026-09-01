"""Name-based API examples — no internal codes required.

Run:  python3 examples/name_api.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdim import SDIM

aca = SDIM(delay=0.5)

# 1) river water quality, filtered by river name + parameter names
parsed = aca.get_data(
    water_type="river",
    rivers=["Ter"],
    parameters=["nitrate", "phosphate"],
    start="2007-09-01",
    end="2009-12-31",
)
df = parsed["quality"]
print(df[["date", "station_code", "mass_name", "variable", "value", "unit"]].head(8).to_string(index=False))
print(f"-> {len(df)} readings\n")

# 2) groundwater phys-chemistry for an explicit station (by code), by name
gw = aca.get_data(
    water_type="groundwater",
    parameters=["nitrate"],
    stations=["F000100"],
    start="2007-01-01",
    end="2015-12-31",
)
print(gw["quality"][["date", "variable", "value", "unit"]].to_string(index=False))
print(
    "\nThe client resolved these automatically from the metadata catalog: "
    "target after_2007:0005:0010 (groundwater quality), "
    "nitrate -> g/f/v codes, station series ids."
)

# 3) raw bytes / explicit target (reservoir volumes), by parameter name
out = aca.download(
    target="after_2007:0002:0302",
    parameters=["volum"],
    stations=["F015082"],
    start="2007-01-01",
    end="2007-12-31",
    output="/tmp/volums.xlsx",
)
print("\nreservoir volumes saved -> /tmp/volums.xlsx", f"({len(out)} bytes)")

aca.close()