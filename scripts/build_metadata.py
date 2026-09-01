"""Build SDIM metadata CSVs (networks, subnetworks, parameters, rivers, …).

Runs the discovery endpoints once per period and writes the resulting
mappings under ``metadata/``. Raw server responses are cached in
``metadata/raw/`` so re-runs do not hit the server again.

Usage:
    python3 scripts/build_metadata.py [--refresh]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from sdim.discovery import PERIODS, SPATIAL_PROVIDERS, Discovery

RAW_DIR = ROOT / "metadata" / "raw"
OUT_DIR = ROOT / "metadata"


class CachedDiscovery:
    """Wrapper that persists raw responses on disk."""

    def __init__(self, discovery: Discovery, refresh: bool = False):
        self.discovery = discovery
        self.refresh = refresh

    def _load(self, key: str) -> str | None:
        path = RAW_DIR / f"{key}.html"
        if self.refresh or not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def _save(self, key: str, body: str) -> str:
        path = RAW_DIR / f"{key}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return body

    def variable_tree(self, period, network, subs):
        key = f"{period}/tipus/{network}-{'-'.join(subs)}"
        body = self._load(key)
        if body is None:
            body = self._save(key, self.discovery._post_body(
                "/serveis/serveiTipusVariables.do",
                [("periodeXarxaControl", period), ("xarxaControl", network)]
                + [("subXarxaControl", s) for s in subs],
            ))
        from sdim.discovery import _parse_tipus_tree
        return _parse_tipus_tree(body)

    def spatial(self, period, provider):
        key = f"{period}/spatial/{provider}"
        body = self._load(key)
        if body is None:
            endpoint, _ = SPATIAL_PROVIDERS[provider]
            subs = [c for c, _p, _n in self.discovery.subnetworks(period)]
            nets = [n for n, _ in self.discovery.networks(period)]
            body = self._save(key, self.discovery._post_body(
                "/serveis/" + endpoint,
                [("periodeXarxaControl", period)]
                + [("xarxaControl", n) for n in nets]
                + [("subXarxaControl", s) for s in subs],
            ))
        from sdim.discovery import _parse_elements
        return _parse_elements(body, SPATIAL_PROVIDERS[provider][1])

    def stations(self, period, network, subs):
        key = f"{period}/stations/{network}-{'-'.join(subs)}"
        body = self._load(key)
        if body is None:
            body = self._save(key, self.discovery._post_body(
                "/serveis/serveiDetallSeleccio.do",
                [("periodeXarxaControl", period), ("xarxaControl", network)]
                + [("subXarxaControl", s) for s in subs]
                + [("ambit", "catalunya"), ("modoConsultaDetall", "resumen")],
            ))
        import re
        from html import unescape
        pattern = re.compile(
            r'<input[^>]*name="puntControl"[^>]*value="([^"]*)"'
            r'[^>]*x="([^"]*)" y="([^"]*)"[^>]*>\s*<a[^>]*>\s*'
            r'<label[^>]*title="([^"]*)"',
            re.S,
        )
        return [(c, x, y, unescape(n)) for c, x, y, n in pattern.findall(body)]


def build(refresh: bool = False) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw = CachedDiscovery(Discovery(), refresh=refresh)
    d = raw.discovery

    allnets: list[dict] = []
    allsubs: list[dict] = []
    allvars: list[dict] = []
    allstations: list[dict] = []

    for period in PERIODS:
        nets = d.networks(period)
        subs = d.subnetworks(period)
        print(f"[{period}] networks={len(nets)} subnetworks={len(subs)}")

        allnets += [{"period": period, "code": c, "name": n} for c, n in nets]
        allsubs += [{"period": period, "network": p, "code": c, "name": n}
                    for c, p, n in subs]

        # variable types per subnetwork
        for code, parent, name in subs:
            tree = raw.variable_tree(period, parent, [code])
            print(f"   tipus {parent}/{code} ({name}): {len(tree)} branches")
            allvars += [{
                "period": period, "network": parent, "subnetwork": code,
                "g": g, "g_name": gn, "f": f, "f_name": fn, "v": v, "v_name": vn,
            } for g, gn, f, fn, v, vn in tree]

        # stations per network
        for net, netname in nets:
            nsubs = [c for c, p, _n in subs if p == net]
            stations = raw.stations(period, net, nsubs)
            print(f"   stations {net} ({netname}): {len(stations)}")
            allstations += [{"period": period, "network": net, "station": c,
                             "name": n, "x": x, "y": y} for c, x, y, n in stations]

    # spatial providers -> one CSV each (period, code, name), deduplicated
    # per period: the same code may map to different names in each period.
    spatial_dfs: dict[str, pd.DataFrame] = {}
    for provider in SPATIAL_PROVIDERS:
        rows: list[dict] = []
        for period in PERIODS:
            for code, name in raw.spatial(period, provider):
                rows.append({"period": period, "code": code, "name": name})
        df = pd.DataFrame(rows).drop_duplicates(["period", "code"], keep="first")
        spatial_dfs[provider] = df
        print(f"[spatial] {provider}: {len(df)} rows")

    # write CSVs
    pd.DataFrame(allnets).drop_duplicates().to_csv(OUT_DIR / "networks.csv", index=False)
    pd.DataFrame(allsubs).drop_duplicates().to_csv(OUT_DIR / "subnetworks.csv", index=False)
    pd.DataFrame(allvars).drop_duplicates().to_csv(OUT_DIR / "variables.csv", index=False)
    pd.DataFrame(allstations).drop_duplicates(["period", "station"]).to_csv(
        OUT_DIR / "stations.csv", index=False)
    for provider, df in spatial_dfs.items():
        df.to_csv(OUT_DIR / f"{provider}.csv", index=False)

    print(f"\nWrote metadata CSVs to {OUT_DIR}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch from the server (ignore raw cache)")
    args = ap.parse_args()
    build(refresh=args.refresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())