"""Minimal CLI for the ACA SDIM client."""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from . import __version__
from .catalog import _FLAVORS
from .client import DEFAULT_MAX_REQUESTS, DEFAULT_MAX_STATIONS, SDIM
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


def _sdim_kwargs(args: argparse.Namespace) -> dict:
    # semantic (name-level) path
    kinds = [(k.partition("=")[0], k.partition("=")[2]) for k in args.kind]
    stations = _parse_stations(args.station)
    spatial_codes: dict[str, list[str]] = {}
    for spec in args.spatial:
        name, _, value = spec.partition("=")
        spatial_codes.setdefault(name, []).append(value)
    semantics = {
        "target": args.target, "period": args.period, "water_type": args.water_type,
        "water_source": args.water_source, "data_type": args.data_type,
        "protected_zone": args.protected_zone, "area_type": args.area_type,
        "areas": args.area or None,
        "parameters": args.parameter or None, "groups": args.group or None,
        "rivers": args.river_name or None,
        "basins": args.basin or None, "comarcas": args.comarca or None,
        "municipis": args.municipi or None, "aquifers": args.aquifer or None,
        "masses": args.mass or None, "reservoirs": args.reservoir or None,
        "networks": args.network or None, "subnetworks": args.subnetwork or None,
        "variable_kinds": kinds or None, "stations": stations or None,
        "ambit": args.ambit, "spatial_codes": spatial_codes or None,
        "start": args.start, "end": args.end, "max_stations": args.max_stations,
    }
    return {k: v for k, v in semantics.items() if v not in (None, [], False, {})}


def cmd_download(args: argparse.Namespace) -> int:
    sdim_kwargs = _sdim_kwargs(args)
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


def cmd_get(args: argparse.Namespace) -> int:
    aca = SDIM()
    try:
        result = aca.get_data(split=not args.no_split, max_requests=args.max_requests,
                              **_sdim_kwargs(args))
    except SDIMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        aca.close()
    for name, df in result.items():
        print(f"{name}: {len(df)} rows")
    for path in result.save(args.output):
        print(f"wrote {path}")
    return 0


def cmd_targets(args: argparse.Namespace) -> int:
    from .catalog import Catalog
    from .resolver import data_sources, water_types

    df = Catalog().targets(args.period)
    if args.category:
        df = df[df.category.str.contains(args.category, case=False, regex=False)]
    cols = ["id", "network_name", "subnetwork_name", "category", "station_count", "series_count"]
    with pd.option_context("display.max_rows", None, "display.width", 250,
                           "display.max_colwidth", 50):
        print(df[cols].to_string(index=False))
    print()
    print("water types:", ", ".join(water_types(args.period)))
    print()
    print(data_sources(args.period).to_string(index=False))
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    from .catalog import Catalog

    cat = Catalog()
    row = cat.target(args.target)
    if row is None:
        print(f"error: unknown target {args.target!r}; see `sdim targets`", file=sys.stderr)
        return 1
    print(f"{row['id']}: {row['network_name']} / {row['subnetwork_name']}")
    print(f"category: {row['category']}")
    print(f"stations: {row['station_count']}, series: {row['series_count']}")
    tv = cat.variables_for(row["network"], row["subnetwork"], period=row["period"])
    for (g_name, f_name), part in tv.groupby(["g_name", "f_name"], sort=True):
        names = ", ".join(part.v_name.tolist()[:args.limit])
        more = f" (+{len(part) - args.limit} more)" if len(part) > args.limit else ""
        print(f"  {g_name} > {f_name}: {names}{more}")
    return 0


def _parse_stations(specs: list[str]) -> dict[str, list[str]]:
    stations = {}
    for spec in specs:
        code, _, rest = spec.partition("=")
        stations[code] = [v for v in rest.split(",") if v]
    return stations


def _add_semantic_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", help="explicit target id, e.g. after_2007:0005:0011")
    parser.add_argument("--water-source",
                        help="river | reservoir | groundwater | lakes_and_wetlands | "
                             "coastal | protected")
    parser.add_argument("--data-type",
                        help="physico_chemical | biological | priority_substances | "
                             "hydromorphological | flow | level | volume")
    parser.add_argument("--protected-zone",
                        help="drinking_water | river_reserves | nitrate_vulnerable | "
                             "eutrophication_sensitive (with --water-source protected)")
    parser.add_argument("--area-type",
                        help="catalunya | basin | water_mass | river | reservoir | "
                             "aquifer | comarca | municipi")
    parser.add_argument("--area", action="append", default=[],
                        help="area name or code for --area-type — repeatable")
    parser.add_argument("--water-type",
                        help="river | groundwater | levels | flow | volumes | "
                             "river_biology | lake_biology | ...")
    parser.add_argument("--parameter", action="append", default=[],
                        help="parameter name (nitrate, phosphate, ec, ...) — repeatable")
    parser.add_argument("--group", action="append", default=[],
                        help="variable group or family name (\"Índexs biològics\", "
                             "Invertebrats, Nutrients, ...) — repeatable")
    parser.add_argument("--river", dest="river_name", action="append", default=[],
                        help="river name (Ter, Llobregat, ...) — repeatable")
    parser.add_argument("--basin", action="append", default=[])
    parser.add_argument("--comarca", action="append", default=[])
    parser.add_argument("--municipi", action="append", default=[])
    parser.add_argument("--aquifer", action="append", default=[])
    parser.add_argument("--mass", action="append", default=[])
    parser.add_argument("--reservoir", action="append", default=[])
    parser.add_argument("--max-stations", type=int, default=DEFAULT_MAX_STATIONS)


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

    gt = sub.add_parser("get", help="download, parse and save CSVs plus provenance")
    _add_query_args(gt)
    _add_semantic_args(gt)
    gt.add_argument("--output", "-o", required=True,
                    help="file prefix: writes <prefix>_quality.csv, ..., <prefix>_provenance.json")
    gt.add_argument("--no-split", action="store_true",
                    help="fail instead of splitting reports SDIM refuses as too large")
    gt.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    gt.set_defaults(func=cmd_get)

    tg = sub.add_parser("targets", help="list downloadable targets and water types")
    tg.add_argument("--period", default=None)
    tg.add_argument("--category", default=None, help="e.g. biological, quantity, metals")
    tg.set_defaults(func=cmd_targets)

    ds = sub.add_parser("describe", help="show a target's variable groups and families")
    ds.add_argument("target", help="target id, e.g. after_2007:0001:0001")
    ds.add_argument("--limit", type=int, default=8, help="variables shown per family")
    ds.set_defaults(func=cmd_describe)

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