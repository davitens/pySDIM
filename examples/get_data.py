"""Example: download the 11-station Ter-conductivity report and print it.

Requires network access to aplicacions.aca.gencat.cat.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdim import SDIM, Query

# station -> variables, discovered from the SDIM detail selection for
# network CONTROL RIUS (0001) / Elements fisicoquímics (0022), river Ter.
STATIONS_VARS = {
    "F007528": ["3057279"],
    "F007529": ["3049297"],
    "F007533": ["3057302"],
    "F007536": ["3049377"],
    "F007541": ["3052771"],
    "F007547": ["3052811"],
    "F007552": ["3052952"],
    "F007561": ["3053096"],
    "F007569": ["3053262"],
    "F012655": ["3272829"],
    "F012656": ["3277397"],
}

query = Query(
    period="after_2007",
    networks=["0001"],
    subnetworks=["0022"],
    variable_kinds=[("g", "5"), ("f", "050004"), ("v", "0002")],  # conductivity
    ambit="riu",
    spatial={"riuAmbit": ["200"]},  # RIU TER
    stations=STATIONS_VARS,
    start="2007-09-01",
    end="2010-01-01",
)

aca = SDIM(delay=0.5)
try:
    parsed = aca.get_data(query)
finally:
    aca.close()

df = parsed["quality"]
print(df[["date", "mass_name", "variable", "value", "unit"]].head(10).to_string(index=False))
print(f"\n{len(df)} records")