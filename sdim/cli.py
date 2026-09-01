"""Minimal CLI for the ACA SDIM client."""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from . import __version__
from .catalog import _FLAVORS
from .client import SDIM
from .exceptions import SDIMError
from .query import Query


def _add_query_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--period", default="after_2007", help="after_2007 | before_2007")
    parser.add_argument("--network", action="append", default=[], help="xarxaControl code (repeatable)")
    parser.add_argument("--subnetwork", action="append", default=[], help="subXarxaControl code (repeatable)")
    parser.add_argument("--kind", action="append", default=[], metavar="NAME=VALUE",
                        help="variable-type branch g/f/v (repeatable), e.g. g=5")
    parser.add_argument("--ambit", default="catalunya",
                        help="catalunya | conques | massa | embassament | riu | aquifer | comarques | municipis")
    parser.add_argument("--spatial", action="append", default=[], metavar="NAME=VALUE",
                        help="raw spatial filter field (repeatable), e.g. riuAmbit=200")
    parser.add_argument("--station", action="append", default=[], metavar="CODE=VAR[,VAR...]",
                        help="station code followed by variable ids (repeatable)")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)


def cmd_download(args: argparse.Namespace) -> int:
    # semantic (name-level) path
    kinds = [(k.partition("=")[0], k.partition("=")[2]) for k in args.kind]
    stations = _parse_stations(args.station)
    spatial_codes: dict[str, list[str]] = {}
    for spec in args.spatial:
        name, _, value = spec.partition("=")
        spatial_codes.setdefault(name, []).append(value)
    semantics = {
        "target": args.target, "period": args.period, "water_type": args.water_type,
        "parameters": args.parameter or None, "rivers": args.river_name or None,
        "basins": args.basin or None, "comarcas": args.comarca or None,
        "municipis": args.municipi or None, "aquifers": args.aquifer or None,
        "masses": args.mass or None, "reservoirs": args.reservoir or None,
        "networks": args.network or None, "subnetworks": args.subnetwork or None,
        "variable_kinds": kinds or None, "stations": stations or None,
        "ambit": args.ambit, "spatial_codes": spatial_codes or None,
        "start": args.start, "end": args.end, "max_stations": args.max_stations,
    }
    sdim_kwargs = {k: v for k, v in semantics.items()
                   if v not in (None, [], False, {})}
    output = args.output
    aca = SDIM()
    try:
        data = aca.download(output=output, **sdim_kwargs)
        if output is None:
            sys.stdout.buffer.write(data)
        else:
            print(f"wrote {output}")
    except SDIMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        aca.close()
    return 0


def _parse_stations(specs: list[str]) -> dict[str, list[str]]:
    stations = {}
    for spec in specs:
        code, _, rest = spec.partition("=")
        stations[code] = [v for v in rest.split(",") if v]
    return stations


def _add_semantic_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", help="explicit target id, e.g. after_2007:0005:0011")
    parser.add_argument("--water-type", help="river | groundwater | levels | flow | volumes | ...")
    parser.add_argument("--parameter", action="append", default=[],
                        help="parameter name (nitrate, phosphate, ec, ...) — repeatable")
    parser.add_argument("--river", dest="river_name", action="append", default=[],
                        help="river name (Ter, Llobregat, ...) — repeatable")
    parser.add_argument("--basin", action="append", default=[])
    parser.add_argument("--comarca", action="append", default=[])
    parser.add_argument("--municipi", action="append", default=[])
    parser.add_argument("--aquifer", action="append", default=[])
    parser.add_argument("--mass", action="append", default=[])
    parser.add_argument("--reservoir", action="append", default=[])
    parser.add_argument("--max-stations", type=int, default=200)


def cmd_search(args: argparse.Namespace) -> int:
    from .catalog import Catalog

    flavors = args.flavor or [f for f in _FLAVORS if f in ("networks", "subnetworks", "variables")]
    cat = Catalog()
    for flavor in flavors:
        label = _FLAVORS[flavor][0]
        print(f"== {label}s ==")
        rows = cat.search(flavor, args.term, period=args.period)
        display = rows[["period"] + [c for c in rows.columns if c != "period"]] if "period" in rows.columns else rows
        with pd.option_context("display.max_rows", None, "display.width", 200):
            print(display.head(args.limit).to_string(index=False))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sdim", description="ACA SDIM data client")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="generate and download an SDIM report")
    _add_query_args(dl)
    _add_semantic_args(dl)
    dl.add_argument("--output", "-o")
    dl.set_defaults(func=cmd_download)

    sr = sub.add_parser("search", help="search metadata tables (rivers, variables, ...)")
    sr.add_argument("term", help="substring to search in element names")
    sr.add_argument("--flavor", action="append", default=[],
                    choices=list(_FLAVORS.keys()), help="table(s) to search (repeatable)")
    sr.add_argument("--period", default=None)
    sr.add_argument("--limit", type=int, default=25)
    sr.set_defaults(func=cmd_search)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())