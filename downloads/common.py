"""Shared helpers for the bulk-download scripts in this folder.

Implements the M5 optimized download strategy: pre-computed station lists
(one-time Discovery call) with explicit station lists for all subsequent
downloads, avoiding the expensive live ``serveiDetallSeleccio.do`` call
on every request.

Settings: timeout=180s, retries=1, delay=0.1s.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from sdim import SDIM, Catalog
from sdim.discovery import Discovery
from sdim.exceptions import SDIMError, SDIMNoData

COMARCAS = ["Baix Empordà", "Alt Empordà"]

# SDIM splits its archive at 2007: before_2007 and after_2007 are queried
# separately, then merged.
DEFAULT_PERIODS = [
    ("before_2007", "1970-01-01", "2006-12-31"),
    ("after_2007", "2007-01-01", "2025-12-31"),
]

# M5 optimized settings
M5_TIMEOUT = 180.0
M5_RETRIES = 1
M5_DELAY = 0.1

# Cache file for discovered stations
_STATION_CACHE_FILE = Path(__file__).resolve().parent / ".station_cache.json"


def period_dates(periods, period: str) -> tuple[str, str]:
    for p, start, end in periods:
        if p == period:
            return start, end
    raise ValueError(f"no date range for period {period!r}")


def _load_station_cache() -> dict[str, list[str]]:
    """Load cached station→variable_ids mapping from disk."""
    if _STATION_CACHE_FILE.exists():
        try:
            return json.loads(_STATION_CACHE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_station_cache(cache: dict[str, list[str]]) -> None:
    """Persist station→variable_ids mapping to disk."""
    _STATION_CACHE_FILE.write_text(json.dumps(cache, indent=2))


def discover_stations(
    aca: SDIM,
    comarcas: list[str],
    target_id: str,
) -> dict[str, list[str]]:
    """One-time Discovery call: get station→variable_ids for comarcas.

    Checks the on-disk cache first. Returns {station_code: [variable_id, ...]}.
    """
    cache_key = f"{target_id}:{':'.join(sorted(comarcas))}"
    cache = _load_station_cache()
    if cache_key in cache:
        print(f"  Using cached station list ({len(cache[cache_key])} stations)")
        return cache[cache_key]

    period, network, subnetworks_str = target_id.split(":")
    subnetworks = [subnetworks_str]

    cat = Catalog()
    tv = cat.variables_for(network, subnetworks_str, period=period)
    variable_kinds = (
        [("g", x) for x in tv.g.unique()]
        + [("f", x) for x in tv.f.unique()]
        + [("v", x) for x in tv.v.unique()]
    )

    comarca_df = cat.table("comarcas")
    period_df = comarca_df[comarca_df.period == period] if "period" in comarca_df.columns else comarca_df

    comarca_codes = []
    for comarca in comarcas:
        import unicodedata
        def _norm(t):
            return unicodedata.normalize("NFD", t).encode("ascii", "ignore").decode().lower()
        q = _norm(comarca)
        mask = period_df["name"].map(lambda n: _norm(str(n))).str.contains(q, case=False, na=False)
        hits = period_df[mask]
        if not hits.empty:
            comarca_codes.extend(hits["code"].unique().tolist())

    if not comarca_codes:
        raise ValueError(f"No comarca codes found for {comarcas}")

    print(f"  Discovering stations via Discovery call... ", end="", flush=True)
    t0 = time.time()
    d = Discovery(session=aca._session, delay=0.4, timeout=aca._session.timeout)
    d._bootstrap(period)
    records = d.detail_select(
        period,
        network,
        subnetworks,
        variable_kinds=variable_kinds,
        ambit="comarques",
        spatial={"comarcaAmbit": comarca_codes},
    )

    station_map: dict[str, list[str]] = {}
    for rec in records:
        vids = [vid for vid, _vname in rec["variables"]]
        if vids:
            station_map[rec["station"]] = vids
    elapsed = time.time() - t0
    print(f"{len(station_map)} stations in {elapsed:.1f}s")

    cache[cache_key] = station_map
    _save_station_cache(cache)
    return station_map


def make_sdim(delay: float = M5_DELAY, timeout: float = M5_TIMEOUT,
              retries: int = M5_RETRIES) -> SDIM:
    """Create a SDIM instance with M5 optimized settings."""
    aca = SDIM(delay=delay, timeout=timeout)
    aca._session.retries = retries
    return aca


def download_targets(
    aca: SDIM,
    jobs: list[tuple[str, dict]],
    *,
    sheet: str = "quality",
    periods=None,
    station_cache: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """Run a list of ``(target_id, kwargs)`` queries and merge the sheet rows.

    Uses pre-computed station lists when available (M5 strategy).
    Each failed/skipped target is reported on stderr but does not abort the run.
    """
    periods = periods or DEFAULT_PERIODS
    frames: list[pd.DataFrame] = []
    total_jobs = len(jobs)

    for job_idx, (target_id, kw) in enumerate(jobs, 1):
        period = target_id.split(":")[0]
        start, end = period_dates(periods, period)
        print(f"\n[{job_idx}/{total_jobs}] {target_id}  {start} .. {end}", flush=True)

        # Use pre-computed stations if available (skip Discovery)
        station_codes = None
        if station_cache and target_id in station_cache:
            station_codes = station_cache[target_id]
            print(f"  Using pre-computed stations ({len(station_codes)} stations)")

        try:
            if station_codes:
                parsed = aca.get_data(target=target_id, stations=station_codes,
                                      start=start, end=end, **kw)
            else:
                parsed = aca.get_data(target=target_id, comarcas=COMARCAS,
                                      start=start, end=end, **kw)
        except SDIMNoData:
            print("  no data", flush=True)
            continue
        except SDIMError as exc:
            print(f"  skipped: {exc}", flush=True)
            continue

        df = parsed.get(sheet, pd.DataFrame())
        if df is None or df.empty:
            print("  no data", flush=True)
            continue
        df.insert(0, "target", target_id)
        df.insert(1, "period", period)
        frames.append(df)
        stations = df["station_code"].nunique()
        print(f"  -> {len(df)} readings | {stations} stations "
              f"| {df.iloc[:, 6].nunique() if len(df) else 0} water bodies", flush=True)
        time.sleep(0.3)

    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame()


def discover_all_targets(
    comarcas: list[str],
    targets: list[tuple[str, str, str]],
) -> dict[str, list[str]]:
    """Pre-discover stations for all targets. Returns {target_id: [station_codes]}.

    Run this once before the main download loop.
    """
    aca = make_sdim()
    cache: dict[str, list[str]] = {}
    try:
        for target_id, _start, _end in targets:
            try:
                station_map = discover_stations(aca, comarcas, target_id)
                cache[target_id] = sorted(station_map.keys())
            except Exception as e:
                print(f"  WARNING: Could not discover stations for {target_id}: {e}")
    finally:
        aca.close()
    return cache
