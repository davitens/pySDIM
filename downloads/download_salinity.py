"""Download all salinity data (variable family 'Salinitat', f=050004) for
comarques Baix Emporda and Alt Emporda, full archive 1970-2025.

Uses M5 optimized strategy (pre-computed stations, timeout=180s, retries=1).

"Salinitat" is the SDIM variable family holding salinity-related
physico-chemical parameters: Conductivitat, Conductivitat a 20oC, Clorurs,
Sulfats, Sodi, Potassi, Bromurs, Salinitat.

Every target that carries this family is queried and merged:

* after_2007: 0001:0022, 0002:0023, 0003:0025, 0004:0008, 0005:0010,
              0006:0012, 0006:0013
* before_2007: 0000:0017, 0000:0018, 0000:0019

Output: ``downloads/salinity_emporda.csv``

Run:  python3 download_salinity.py
"""

from pathlib import Path

import pandas as pd

from common import (
    COMARCAS, SDIM, download_targets, make_sdim, discover_all_targets,
)

FAMILY = "Salinitat"   # f_name in metadata/variables.csv

OUT = Path(__file__).resolve().parent / "salinity_emporda.csv"


def family_targets() -> list[tuple[str, str, str, dict]]:
    """All (target_id, start, end, kw) jobs."""
    variables = pd.read_csv(Path(__file__).resolve().parent.parent
                            / "metadata" / "variables.csv", dtype=str)
    jobs: list[tuple[str, str, str, dict]] = []
    for period in ("before_2007", "after_2007"):
        start = "1970-01-01" if period == "before_2007" else "2007-01-01"
        end = "2006-12-31" if period == "before_2007" else "2025-12-31"
        fam = variables[(variables.period == period)
                        & (variables.f_name == FAMILY)]
        for (net, sub), _ in fam.groupby(["network", "subnetwork"]):
            target = f"{period}:{net.zfill(4)}:{sub.zfill(4)}"
            name_row = fam[(fam.network == net) & (fam.subnetwork == sub)]
            variables_names = sorted(name_row.v_name.unique().tolist())
            jobs.append((target, start, end, {"parameters": variables_names}))
    return jobs


if __name__ == "__main__":
    jobs = family_targets()
    print("Targets carrying the Salinitat (f=050004) family:")
    for target, start, end, kw in jobs:
        print(f"  {target}  {start}..{end}  -> {', '.join(kw['parameters'])}")

    print("\nPre-discovering stations...")
    discover_jobs = [(t, s, e) for t, s, e, _ in jobs]
    station_cache = discover_all_targets(COMARCAS, discover_jobs)

    aca = make_sdim()
    try:
        df = download_targets(aca, [(t, kw) for t, _s, _e, kw in jobs],
                              sheet="quality", station_cache=station_cache)
    finally:
        aca.close()

    if df.empty:
        print("\nNo Salinitat-family data found for Baix/Alt Emporda.")
        raise SystemExit(1)

    print(f"\nMerged: {len(df)} readings | {df['period'].nunique()} periods "
          f"| {df['target'].nunique()} targets")
    df.to_csv(OUT, index=False)
    print(f"Saved -> {OUT}")
    print("\ndate range:", df["date"].min(), "->", df["date"].max())
    print("variables:", ", ".join(sorted(df["variable"].unique())))
    print("stations:", df["station_code"].nunique(), "| water bodies:", df["mass_name"].nunique())
