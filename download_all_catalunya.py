"""Download all Catalunya groundwater-level data (1970-2026).

Uses the M5 optimized strategy: pre-computed station lists with explicit
station lists for all downloads, avoiding expensive Discovery calls.

Resumable: tracks completed years in a checkpoint. Re-run to continue.
Output: downloads/catalunya_levels/{target}.csv + _checkpoint.json

Run:  python3 download_all_catalunya.py
Dedup: python3 download_all_catalunya.py --dedup
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from sdim import SDIM, Catalog
from sdim.exceptions import SDIMError, SDIMNoData

OUTPUT_DIR = Path(__file__).resolve().parent / "downloads" / "catalunya_levels"
CHECKPOINT_FILE = OUTPUT_DIR / "_checkpoint.json"

TARGETS = [
    ("before_2007:0005:0011", "1970-01-01", "2006-12-31"),
    ("after_2007:0005:0011",  "2007-01-01", "2026-12-31"),
]

# M5 optimized settings
TIMEOUT = 180.0
RETRIES = 1
DELAY = 0.1


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_checkpoint(state: dict) -> None:
    """Write checkpoint with fsync to survive SIGTERM."""
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


def get_stations(cat: Catalog, target_id: str) -> list[str]:
    sv = cat.target_station_variables(target_id)
    if sv.empty:
        return []
    return sorted(sv["station"].unique().tolist())


def make_sdim() -> SDIM:
    aca = SDIM(delay=DELAY, timeout=TIMEOUT)
    aca._session.retries = RETRIES
    return aca


def download_target(
    aca: SDIM,
    target_id: str,
    start: str,
    end: str,
    all_stations: list[str],
    done_years: set[int],
    csv_path: Path,
    checkpoint_key: str,
    prior_readings: int = 0,
) -> int:
    """Download all years for a target, one year per request.

    Progress is reported as [done/total] after each year.
    """
    start_year = int(start[:4])
    end_year = int(end[:4])
    years = list(range(start_year, end_year + 1))
    total_years = len(years)
    done_count = len(done_years)
    total_new = 0

    pending_years = [y for y in years if y not in done_years]

    print(f"\n{'='*60}")
    print(f"Target: {target_id}  |  {start} .. {end}")
    print(f"Stations: {len(all_stations)} | Years: {total_years} | "
          f"Done: {done_count} | Pending: {len(pending_years)}")
    print(f"{'='*60}")

    for year_idx, year in enumerate(pending_years, 1):
        overall_done = done_count + year_idx
        t0 = time.time()
        try:
            parsed = aca.get_data(
                target=target_id,
                stations=all_stations,
                start=f"{year}-01-01",
                end=f"{year}-12-31",
            )
            df = parsed.get("quality", pd.DataFrame())
            if df is None or df.empty:
                df = pd.DataFrame()
        except SDIMNoData:
            df = pd.DataFrame()
        except SDIMError as exc:
            elapsed = time.time() - t0
            print(f"  [{overall_done}/{total_years}] FAILED {year} ({elapsed:.1f}s): {exc}")
            time.sleep(2)
            continue
        except Exception as exc:
            elapsed = time.time() - t0
            print(f"  [{overall_done}/{total_years}] ERROR  {year} ({elapsed:.1f}s): {exc}")
            time.sleep(2)
            continue

        elapsed = time.time() - t0
        n = len(df)
        total_new += n

        # Write CSV
        if not df.empty:
            header = not csv_path.exists() or csv_path.stat().st_size == 0
            df.to_csv(csv_path, mode="a", index=False, header=header)

        # Mark year done in checkpoint
        done_years.add(year)
        save_checkpoint({
            "target_id": target_id,
            checkpoint_key: sorted(done_years),
            "total_readings": prior_readings + total_new,
        })

        print(f"  [{overall_done}/{total_years}] {year}: +{n} readings ({elapsed:.1f}s) | "
              f"total: {total_new}", flush=True)

    return total_new


def dedup_csvs() -> None:
    for csv_path in sorted(OUTPUT_DIR.glob("*.csv")):
        df = pd.read_csv(csv_path)
        before = len(df)
        df2 = df.drop_duplicates()
        after = len(df2)
        if before != after:
            df2.to_csv(csv_path, index=False)
            print(f"  {csv_path.name}: {before} -> {after} (-{before - after})")
        else:
            print(f"  {csv_path.name}: {after} (clean)")


def main() -> None:
    if "--dedup" in sys.argv:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        dedup_csvs()
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cat = Catalog()
    state = load_checkpoint()
    aca = make_sdim()
    grand_total = 0

    try:
        for target_id, start, end in TARGETS:
            all_stations = get_stations(cat, target_id)
            if not all_stations:
                print(f"No stations for {target_id}, skipping.")
                continue

            done_key = f"{target_id}_years"
            done_years = set(state.get(done_key, []))
            csv_path = OUTPUT_DIR / f"{target_id.replace(':', '_')}.csv"

            prior = state.get("total_readings", 0)
            new = download_target(aca, target_id, start, end,
                                  all_stations, done_years, csv_path, done_key, prior)
            grand_total += new

            state[done_key] = sorted(done_years)
            state["total_readings"] = grand_total
            save_checkpoint(state)
    finally:
        aca.close()

    print(f"\n{'='*60}")
    print(f"DONE. Total new readings: {grand_total}")
    print(f"Files in: {OUTPUT_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
