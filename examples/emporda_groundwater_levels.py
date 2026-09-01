"""Download all groundwater-level (piezometry) data for comarques Baix and Alt Empordà.

Groundwater levels live in three SDIM targets — one per period and one pre-2007
network — all of which are queried and merged:

* ``after_2007:0005:0011``  — piezometry, 2007+ (network 0005)
* ``before_2007:0005:0011`` — piezometry, pre-2007 (network 0005)
* ``before_2007:0000:0020`` — groundwater levels, pre-2007 (network 0000)

Run:  python3 examples/emporda_groundwater_levels.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from sdim import SDIM
from sdim.exceptions import SDIMError

COMARCAS = ["Baix Empordà", "Alt Empordà"]
RANGES = [
    ("before_2007", "1950-01-01", "2006-12-31"),
    ("after_2007", "2007-01-01", "2020-12-31"),
]

# The groundwater-level targets (from targets.csv, category = groundwater levels).
TARGETS = [
    "after_2007:0005:0011",
    "before_2007:0005:0011",
    "before_2007:0000:0020",
]

aca = SDIM(delay=0.5)
frames: list[pd.DataFrame] = []
try:
    for target_id in TARGETS:
        period = target_id.split(":")[0]
        start, end = next(r for r in RANGES if r[0] == period)[1:]
        print(f"\n[query] {target_id}  {start} .. {end}", flush=True)
        try:
            parsed = aca.get_data(
                target=target_id,
                comarcas=COMARCAS,
                start=start,
                end=end,
            )
        except SDIMError as exc:
            print(f"  skipped: {exc}")
            continue
        df = parsed["quality"]
        if df.empty:
            print("  no data")
            continue
        df.insert(0, "target", target_id)
        df.insert(1, "period", period)
        frames.append(df)
        print(f"  -> {len(df)} readings | {df['station_code'].nunique()} stations "
              f"| {df['mass_name'].nunique()} water bodies")
finally:
    aca.close()

if not frames:
    print("\nNo groundwater-level data found for these comarques.")
    raise SystemExit(1)

out = pd.concat(frames, ignore_index=True)
print(f"\nMerged: {len(out)} readings across {out['period'].nunique()} periods "
      f"and {out['target'].nunique()} targets.")

for period in ["before_2007", "after_2007"]:
    sub = out[out["period"] == period]
    print(f"\n== {period} ({len(sub)} rows) ==")
    print(sub[["date", "station_code", "mass_name", "variable", "value", "unit"]]
          .head(3).to_string(index=False))

path = Path(__file__).resolve().parent / "emporda_groundwater_levels.csv"
out.to_csv(path, index=False)
print(f"\nSaved -> {path}")