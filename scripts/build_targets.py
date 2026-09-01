"""Build per-target metadata: targets.csv + station_variables.csv.

A SDIM *target* is a (period, network, subnetwork) combination — it defines
which monitoring stations exist and which parameters (variable series) each
station exposes there. The browser requires choosing a target first.

This script:

1. For every target, downloads ``serveiDetallSeleccio.do`` (completa mode,
   catalunya ambit) and records each station's available variable series
   into ``metadata/station_variables/<period>_<network>_<subnetwork>.csv``.
2. Probes the 7 spatial providers per network to record which spatial
   filters (rivers, basins, comarcas, ...) a target supports.
3. Writes ``metadata/targets.csv`` (the inventory) and a merged
   ``metadata/station_variables.csv``.

Run:  python3 scripts/build_targets.py [--refresh] [--target period:net:sub]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from sdim.discovery import SPATIAL_PROVIDERS, Discovery, parse_detall_completa, _parse_elements

BASE = "https://aplicacions.aca.gencat.cat/sdim21"
META = ROOT / "metadata"
SV_DIR = META / "station_variables"
RAW_DIR = META / "raw"


def target_id(period: str, network: str, subnetwork: str) -> str:
    return f"{period}:{network}:{subnetwork}"


def iter_targets(variables: pd.DataFrame) -> list[tuple[str, str, str, str]]:
    """(period, network, subnetwork, subnetwork_name) with variables present."""
    subs = pd.read_csv(META / "subnetworks.csv", dtype=str)
    targets = []
    for period in sorted(variables.period.unique()):
        for (net, sub), g in variables[variables.period == period].groupby(["network", "subnetwork"]):
            name = subs[(subs.period == period) & (subs.network == net) & (subs.code == sub)].iloc[0]["name"]
            targets.append((period, net, sub, name))
    return sorted(targets)


def fetch_detall(discovery: Discovery, period, network, subnetwork, variables: pd.DataFrame) -> str:
    tv = variables[(variables.period == period) & (variables.network == network)
                   & (variables.subnetwork == subnetwork)]
    body = [("periodeXarxaControl", period), ("xarxaControl", network),
            ("subXarxaControl", subnetwork)]
    body += [("v", x) for x in tv.v] + [("f", x) for x in tv.f] + [("g", x) for x in tv.g]
    body += [("massaAmbit", ""), ("AquiferAmbit", ""), ("municipiAmbit", ""),
             ("comarcaAmbit", ""), ("ambit", "catalunya"), ("concaAmbit", ""),
             ("riuAmbit", ""), ("embassamentAmbit", ""), ("modoConsultaDetall", "completa")]
    return discovery.session.post(BASE + "/serveis/serveiDetallSeleccio.do", data=body).text


def build_station_variables(refresh: bool, only: str | None) -> list[dict]:
    variables = pd.read_csv(META / "variables.csv", dtype=str)
    discovery = Discovery(delay=0.3, timeout=300)
    stats = []
    for target in iter_targets(variables):
        period, net, sub, name = target
        tid = target_id(period, net, sub)
        if only and tid != only and only != "*":
            continue
        out_csv = SV_DIR / f"{period}_{net}_{sub}.csv"
        if out_csv.exists() and not refresh:
            print(f"[skip] {tid} ({name}) — cached")
            continue
        try:
            html = fetch_detall(discovery, period, net, sub, variables)
            stations = parse_detall_completa(html)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] {tid} ({name}) — {exc}")
            continue
        rows = []
        for st in stations:
            for vid, vname in st["variables"]:
                rows.append({"period": period, "network": net, "subnetwork": sub,
                             "station": st["station"], "station_name": st["name"],
                             "x": st["x"], "y": st["y"],
                             "variable_id": vid, "variable_name": vname})
        df = pd.DataFrame(rows)
        df.to_csv(out_csv, index=False)
        n_stations = len(df.drop_duplicates("station")) if len(df) else 0
        print(f"[ok]   {tid} ({name}) — {n_stations} stations, {len(rows)} series "
              f"({len(html)//1024} KB)")
        stats.append({**dict(zip(("period", "network", "subnetwork"), (period, net, sub))),
                      "stations": n_stations, "series": len(rows)})
    discovery.close()
    # merged csv
    frames = []
    for f in sorted(SV_DIR.glob("*.csv")):
        frames.append(pd.read_csv(f, dtype=str))
    if frames:
        merged = pd.concat(frames, ignore_index=True)
        merged.to_csv(META / "station_variables.csv", index=False)
        print(f"\nmerged station_variables.csv: {len(merged)} rows")
    return stats


def probe_spatial(discovery: Discovery, period: str, network: str,
                  subnetworks: list[str], refresh: bool = False) -> dict[str, bool]:
    flags = {}
    for provider, (endpoint, field) in SPATIAL_PROVIDERS.items():
        key = f"{period}/target_spatial/{network}/{provider}"
        path = RAW_DIR / f"{key}.html"
        if path.exists() and not refresh:
            body = path.read_text(encoding="utf-8")
        else:
            data = [("periodeXarxaControl", period), ("xarxaControl", network)]
            data += [("subXarxaControl", s) for s in subnetworks]
            body = discovery.session.post(BASE + "/serveis/" + endpoint, data=data).text
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        flags[f"has_{provider}"] = len(_parse_elements(body, field)) > 0
    return flags


def build_targets(refresh_space: bool = False) -> pd.DataFrame:
    variables = pd.read_csv(META / "variables.csv", dtype=str)
    subs = pd.read_csv(META / "subnetworks.csv", dtype=str)
    networks = pd.read_csv(META / "networks.csv", dtype=str)
    discovery = Discovery(delay=0.3, timeout=120)
    rows = []
    net_space_cache: dict[tuple[str, str], dict[str, bool]] = {}
    for target in iter_targets(variables):
        period, net, sub, name = target
        g = variables[(variables.period == period) & (variables.network == net)
                      & (variables.subnetwork == sub)]
        gnames = g.g_name.dropna().unique().tolist()
        fams = g.f_name.dropna().unique().tolist()
        category = _category(gnames)
        sv = SV_DIR / f"{period}_{net}_{sub}.csv"
        if sv.exists():
            sv_df = pd.read_csv(sv, dtype=str)
            station_count = len(sv_df.drop_duplicates("station")) if len(sv_df) else 0
            series_count = len(sv_df)
        else:
            station_count = series_count = 0
        netname = networks[(networks.period == period) & (networks.code == net)].iloc[0]["name"]

        key = (period, net)
        if key not in net_space_cache:
            net_subs = subs[(subs.period == period) & (subs.network == net)]["code"].tolist()
            net_space_cache[key] = probe_spatial(discovery, period, net, net_subs,
                                                 refresh=refresh_space)
        boundaries = net_space_cache[key]

        rows.append({
            "id": target_id(period, net, sub), "period": period,
            "network": net, "network_name": netname,
            "subnetwork": sub, "subnetwork_name": name,
            "category": category,
            "groups": "|".join(sorted(set(gnames))),
            "families": "|".join(sorted(set(fams))),
            "branch_count": len(g),
            "station_count": station_count,
            "series_count": series_count,
            **boundaries,
        })
        print(f"[target] {target_id(period, net, sub)} {name} — "
              f"{station_count} stations, {series_count} series, {category}")
    discovery.close()
    df = pd.DataFrame(rows)
    df.to_csv(META / "targets.csv", index=False)
    return df


def _category(gnames: list[str]) -> str:
    parts = []
    mapping = [
        ("Piezometria", "groundwater levels"),
        ("Quantitat", "quantity"),
        ("Índexs biològics", "biological"),
        ("Índexs hidromorfològics", "hydromorphological"),
        ("Microcontaminants orgànics", "priority substances"),
        ("Metalls", "metals"),
    ]
    matched = [label for g, label in mapping if g in gnames]
    if "Fisicoquímics" in gnames or not matched:
        matched.append("physical-chemical")
    return "; ".join(matched)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-fetch station/variable sweep")
    ap.add_argument("--space", action="store_true", help="(re)probe per-network spatial providers")
    ap.add_argument("--target", default=None,
                    help="only build one target, e.g. after_2007:0005:0010 (or '*' for all)")
    args = ap.parse_args()

    SV_DIR.mkdir(parents=True, exist_ok=True)
    build_station_variables(refresh=args.refresh, only=args.target)
    build_targets(refresh_space=args.space)
    print("\nWrote metadata/targets.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())