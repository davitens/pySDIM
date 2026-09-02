"""Download all river-flowmeter (Cabals) data for comarques Baix Emporda and
Alt Emporda, full archive 1970-2025.

Uses M5 optimized strategy (pre-computed stations, timeout=180s, retries=1).

Flowmeters are quantity data (target ``0001:0301``, subnetwork Cabals) that
download into the *quantity* block of the export (daily means m3/s):

* ``after_2007:0001:0301``  -- Cabals, network CONTROL RIUS (2007+)
* ``before_2007:0001:0301`` -- Cabals (pre-2007)

Output: ``downloads/river_flows_emporda.csv``

Run:  python3 download_river_flows.py
"""

from pathlib import Path

from common import (
    COMARCAS, SDIM, download_targets, make_sdim, discover_all_targets,
)

TARGETS = [
    ("after_2007:0001:0301", "2007-01-01", "2025-12-31"),
    ("before_2007:0001:0301", "1970-01-01", "2006-12-31"),
]

OUT = Path(__file__).resolve().parent / "river_flows_emporda.csv"

if __name__ == "__main__":
    print("Pre-discovering stations...")
    station_cache = discover_all_targets(COMARCAS, TARGETS)

    aca = make_sdim()
    try:
        df = download_targets(aca, [(t, {}) for t, _, _ in TARGETS],
                              sheet="quantity", station_cache=station_cache)
    finally:
        aca.close()

    if df.empty:
        print("\nNo river-flow data found for Baix/Alt Emporda.")
        raise SystemExit(1)

    print(f"\nMerged: {len(df)} daily readings | {df['period'].nunique()} periods "
          f"| {df['target'].nunique()} targets")
    df.to_csv(OUT, index=False)
    print(f"Saved -> {OUT}")
    print("\ndate range:", df["date"].min(), "->", df["date"].max())
    print("stations:", df["station_code"].nunique(), "| variables:", ", ".join(sorted(df["variable"].unique())))
    print("units:", ", ".join(sorted(df["unit"].dropna().unique())))
