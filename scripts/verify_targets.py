"""Live-verify representative SDIM targets download and parse correctly.

Covers groundwater quality, groundwater piezometry, river flows (Cabals),
river levels (Nivells), reservoir volumes (Volums), and pre-2007 groundwater.

Run:  python3 scripts/verify_targets.py [--offline]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from sdim import Query, SDIM

META = ROOT / "metadata"

# representative (period, network, subnetwork) targets to verify
MAJOR = [
    ("after_2007", "0005", "0010", "groundwater quality"),
    ("after_2007", "0005", "0011", "groundwater levels (piezometry)"),
    ("after_2007", "0001", "0022", "river physico-chemical"),
    ("after_2007", "0001", "0301", "river flows (Cabals)"),
    ("after_2007", "0001", "0303", "river levels (Nivells)"),
    ("after_2007", "0002", "0302", "reservoir volumes (Volums)"),
    ("before_2007", "0000", "0019", "pre-2007 groundwater quality"),
    ("before_2007", "0005", "0011", "pre-2007 groundwater levels"),
]

# date ranges per target kind (keep reports small)
RANGES = {
    "groundwater levels": ("2007-01-01", "2010-12-31"),
    "reservoir volumes": ("2007-01-01", "2010-12-31"),
    "river levels": ("2007-01-01", "2010-12-31"),
    "river flows": ("2007-01-01", "2010-12-31"),
    "pre-2007 groundwater quality": ("1995-01-01", "2006-12-31"),
    "pre-2007 groundwater levels": ("1995-01-01", "2010-12-31"),
}
DEFAULT_RANGE = ("2007-01-01", "2015-12-31")


def pick_series(period: str, network: str, subnetwork: str, label: str):
    """Pick one station + its first variable series for a target."""
    variables = pd.read_csv(META / "variables.csv", dtype=str)
    tv = variables[(variables.period == period) & (variables.network == network)
                   & (variables.subnetwork == subnetwork)]
    kinds = ([("g", x) for x in tv.g.unique()] + [("f", x) for x in tv.f.unique()]
             + [("v", x) for x in tv.v.unique()])
    sv = pd.read_csv(META / "station_variables.csv", dtype=str)
    tsv = sv[(sv.period == period) & (sv.network == network) & (sv.subnetwork == subnetwork)]
    if tsv.empty:
        return None, None, None
    row = tsv.iloc[0]
    return kinds, row["station"], row["variable_id"]


def verify_one(aca: SDIM, target, label: str, show_sample: bool = False) -> dict:
    period, net, sub = target
    start, end = RANGES.get(label, DEFAULT_RANGE)
    kinds, station, varid = pick_series(period, net, sub, label)
    if not station:
        return {"status": "no series in catalog", "sheets": {}, "sample": None}
    q = Query(
        period=period, networks=[net], subnetworks=[sub], variable_kinds=kinds,
        ambit="catalunya", stations={station: [varid]},
        start=start, end=end,
    )
    try:
        parsed = aca.get_data(q)
        sheets = {k: (len(df), len(df.columns)) for k, df in parsed.items()}
        sample = None
        if show_sample:
            for name, df in parsed.items():
                if len(df):
                    sample = (name, list(df.columns),
                              df.head(2).to_dict("records"))
                    break
        return {"status": "ok", "station": station, "varid": varid,
                "sheets": sheets, "sample": sample}
    except Exception as exc:  # noqa: BLE001
        return {"status": f"{type(exc).__name__}: {exc}", "station": station,
                "varid": varid, "sample": None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="print first rows of each parsed sheet")
    ap.add_argument("--target", default=None, help="only verify one target, e.g. before_2007:0000:0019")
    args = ap.parse_args()

    aca = SDIM(delay=0.5, timeout=180)
    try:
        for period, net, sub, label in MAJOR:
            target = (period, net, sub)
            if args.target and f"{period}:{net}:{sub}" != args.target:
                continue
            res = verify_one(aca, target, label, show_sample=args.sample)
            line = f"{period}:{net}:{sub} {label:38s} -> {res['status']} {res.get('sheets')}"
            print(line, flush=True)
            if res.get("sample"):
                name, cols, recs = res["sample"]
                print(f"   sample[{name}] cols={cols}")
                for rec in recs:
                    print("   ", {k: v for k, v in list(rec.items())[:6]})
    finally:
        aca.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())