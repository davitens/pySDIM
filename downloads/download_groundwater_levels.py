"""Download all groundwater-level (piezometry) data for comarques
Baix Empordà and Alt Empordà, full archive 1970-2025.

Uses M5 optimized strategy (pre-computed stations, timeout=180s, retries=1).

Queries every SDIM target that carries groundwater levels and merges them:

* ``after_2007:0005:0011``  -- piezometry, network 0005 (2007+)
* ``before_2007:0005:0011`` -- piezometry, network 0005 (pre-2007)
* ``before_2007:0000:0020`` -- groundwater levels, network 0000 (pre-2007)

Output: ``downloads/groundwater_levels_emporda.csv``

Run:  python3 download_groundwater_levels.py
"""

from pathlib import Path

from common import (
    COMARCAS, SDIM, download_targets, make_sdim, discover_all_targets,
)

TARGETS = [
    ("after_2007:0005:0011", "2007-01-01", "2025-12-31"),
    ("before_2007:0005:0011", "1970-01-01", "2006-12-31"),
    ("before_2007:0000:0020", "1970-01-01", "2006-12-31"),
]

OUT = Path(__file__).resolve().parent / "groundwater_levels_emporda.csv"

if __name__ == "__main__":
    print("Pre-discovering stations...")
    station_cache = discover_all_targets(COMARCAS, TARGETS)

    aca = make_sdim()
    try:
        jobs = [(tid, kw) for tid, _s, _e in TARGETS for kw in [{}]]
        df = download_targets(aca, [(t, {}) for t, _, _ in TARGETS],
                              sheet="quality", station_cache=station_cache)
    finally:
        aca.close()

    if df.empty:
        print("\nNo groundwater-level data found for Baix/Alt Emporda.")
        raise SystemExit(1)

    print(f"\nMerged: {len(df)} readings | {df['period'].nunique()} periods "
          f"| {df['target'].nunique()} targets | comarcas: {COMARCAS}")
    df.to_csv(OUT, index=False)
    print(f"Saved -> {OUT}")
    print("\ndate range:", df["date"].min(), "->", df["date"].max())
    print("stations:", df["station_code"].nunique(), "| water bodies:", df["mass_name"].nunique())
