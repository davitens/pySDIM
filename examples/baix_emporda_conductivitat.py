"""Download the complete historic record of Conductivitat for comarca Baix Empordà.

SDIM splits its archive into two periods that must be queried separately:

* ``before_2007`` (pre-2007 networks/stations)
* ``after_2007``  (2007+ networks/stations)

So a "1950–2020" request becomes one query per period. Each period is wider
still: every network target that carries the *Salinitat / Conductivitat*
variable (``g=5, f=050004, v=0002``) is queried and merged, so nothing in the
comarca is missed.

Run:  python3 examples/baix_emporda_conductivitat.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from sdim import Catalog, SDIM
from sdim.exceptions import SDIMError

COMARCA = "Baix Empordà"
VARIABLE = "conductivitat"          # -> Salinitat (f=050004) / Conductivitat (v=0002)
RANGES = [
    ("before_2007", "1950-01-01", "2006-12-31"),
    ("after_2007", "2007-01-01", "2020-12-31"),
]

cat = Catalog("metadata")

# Every (period, network, subnetwork) target exposing the variable. The name
# API resolves the variable and comarca automatically; we just iterate targets.
vari = cat.table("variables")
targets: list[tuple[str, str]] = []
for period, _start, _end in RANGES:
    subtree = vari[(vari.period == period)
                   & vari.v_name.str.contains("Conductivitat", case=False, na=False)]
    for net, sub in sorted(set(zip(subtree.network, subtree.subnetwork))):
        targets.append((period, f"{period}:{net}:{sub}"))

print(f"Targets carrying {VARIABLE!r}:")
for period, target_id in targets:
    print(f"  {period}: {target_id}")

aca = SDIM(delay=0.5)
frames: list[pd.DataFrame] = []
try:
    for period, target_id in targets:
        start, end = next(r for r in RANGES if r[0] == period)[1:]
        print(f"\n[query] {target_id}  {start} .. {end}", flush=True)
        try:
            parsed = aca.get_data(
                target=target_id,
                comarcas=[COMARCA],
                parameters=[VARIABLE],
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
    print("\nNo Conductivitat data found for comarca Baix Empordà.")
    raise SystemExit(1)

out = pd.concat(frames, ignore_index=True)
print(f"\nMerged: {len(out)} readings across {out['period'].nunique()} periods "
      f"and {out['target'].nunique()} targets.")

# a few of each period for a sanity peek
for period in ["before_2007", "after_2007"]:
    sub = out[out["period"] == period]
    print(f"\n== {period} ({len(sub)} rows) ==")
    print(sub[["date", "station_code", "mass_name", "variable", "value", "unit"]]
          .head(3).to_string(index=False))

path = Path(__file__).resolve().parent / "baix_emporda_conductivitat.csv"
out.to_csv(path, index=False)
print(f"\nSaved -> {path}")