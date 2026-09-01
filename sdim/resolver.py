"""Resolve human-readable selections into SDIM codes and a Query.

Maps the user-facing concepts (targets, water types, parameter names, river /
basin / comarca names) onto the internal codes the ``consultaInforme.do``
payload needs, using the metadata catalog produced by
``scripts/build_metadata.py`` / ``scripts/build_targets.py``.
"""

from __future__ import annotations

import re

from .catalog import Catalog, _norm
from .exceptions import SDIMQueryError
from .query import PERIOD_AFTER_2007, PERIOD_BEFORE_2007, Query

# parameter aliases -> canonical Catalan term used by SDIM
ALIASES = {
    "no3": "nitrat", "nh4": "amonia", "ammonia": "amonia", "po4": "fosfat",
    "phosphate": "fosfat", "nitrate": "nitrat", "ec": "conductivitat",
    "conductivity": "conductivitat", "temp": "temperatura",
    "temperature": "temperatura", "do": "oxigen dissolt",
    "oxygen": "oxigen dissolt", "ph": "ph",
}

# semantic water-type -> candidate networks (period-specific)
_NETS_AFTER = {
    "river": ["0001"], "groundwater": ["0005"], "reservoir": ["0002"],
    "embassament": ["0002"], "lake": ["0003"], "estany": ["0003"],
    "zones humides": ["0003"], "coastal": ["0004"], "costanera": ["0004"],
    "protected": ["0006"], "zones protegides": ["0006"],
    "flow": ["0001"], "cabals": ["0001"], "levels": ["0005"],
}
_NETS_BEFORE = {
    "river": ["0000", "0001"], "groundwater": ["0000", "0005"],
    "reservoir": ["0002"], "embassament": ["0002"], "lake": ["0002"],
    "estany": ["0002"], "coastal": ["0004"], "costanera": ["0004"],
    "protected": ["0006"], "zones protegides": ["0006"],
    "flow": ["0001"], "cabals": ["0001"], "levels": ["0000", "0005"],
}

# default (network, subnetwork) per water-type per period (used when no
# parameters are given to pin the target).
_DEFAULT_AFTER = {
    "river": ("0001", "0022"), "groundwater": ("0005", "0010"),
    "levels": ("0005", "0011"), "flow": ("0001", "0301"),
    "reservoir": ("0002", "0023"), "volumes": ("0002", "0302"),
    "embassament": ("0002", "0023"), "lake": ("0003", "0025"),
    "estany": ("0003", "0025"), "coastal": ("0004", "0008"),
    "protected": ("0006", "0012"),
}
_DEFAULT_BEFORE = {
    "river": ("0000", "0017"), "groundwater": ("0000", "0019"),
    "levels": ("0000", "0020"), "flow": ("0001", "0301"),
    "reservoir": ("0002", "0302"), "volumes": ("0002", "0302"),
    "embassament": ("0002", "0302"), "coastal": ("0004", "0009"),
    "protected": ("0006", "0014"),
}

# spatial flavor -> (csv table, payload field)
SPATIAL_FLAVORS = {
    "rivers": ("rivers", "riuAmbit"),
    "basins": ("basins", "concaAmbit"),
    "comarcas": ("comarcas", "comarcaAmbit"),
    "municipis": ("municipis", "municipiAmbit"),
    "aquifers": ("aquifers", "AquiferAmbit"),
    "masses": ("masses", "massaAmbit"),
    "reservoirs": ("reservoirs", "embassamentAmbit"),
}

_AMBIT_BY_FIELD = {
    "riuAmbit": "riu", "concaAmbit": "conques", "comarcaAmbit": "comarques",
    "municipiAmbit": "municipis", "AquiferAmbit": "aquifer",
    "massaAmbit": "massa", "embassamentAmbit": "embassament",
}


def _name_series(names, term: str, ends_with: bool = False) -> list[bool]:
    """Name-match against a term.

    Priority: exact name == term (normalized), then (if ``ends_with``) a name
    ending with the term as a whole word (good for rivers), then a whole-word
    match anywhere, then a plain substring.
    """
    q = _norm(term)
    words = [_norm(str(n)) for n in names]
    exact = [w == q for w in words]
    if any(exact):
        return exact
    if ends_with:
        tail = [re.search(rf"\b{re.escape(q)}$", w) is not None for w in words]
        if any(tail):
            return tail
    boundary = [re.search(rf"\b{re.escape(q)}\b", w) is not None for w in words]
    if any(boundary):
        return boundary
    return [q in w for w in words]


class ResolvedRequest:
    """A fully-resolved request: everything needed to build a Query."""

    def __init__(self, target_id: str, networks, subnetworks, variable_kinds,
                 ambit: str, spatial: dict, stations: dict, cercador: dict,
                 start: str, end: str, period: str, series_filter: list[str] | None = None):
        self.target_id = target_id
        self.networks = networks
        self.subnetworks = subnetworks
        self.variable_kinds = variable_kinds
        self.ambit = ambit
        self.spatial = spatial
        self.stations = stations
        self.cercador = cercador
        self.start = start
        self.end = end
        self.period = period
        self.series_filter = series_filter or []

    def to_query(self) -> Query:
        return Query(
            period=self.period,
            networks=self.networks,
            subnetworks=self.subnetworks,
            variable_kinds=self.variable_kinds,
            ambit=self.ambit,
            spatial=self.spatial,
            stations=self.stations,
            cercador=self.cercador,
            start=self.start,
            end=self.end,
        )


def resolve_request(
    cat: Catalog,
    *,
    target: str | None = None,
    period: str = PERIOD_AFTER_2007,
    water_type: str | None = None,
    networks: list[str] | None = None,
    subnetworks: list[str] | None = None,
    parameters: list[str] | None = None,
    variable_kinds: list[tuple[str, str]] | None = None,
    ambit: str | None = None,
    rivers: list[str] | None = None,
    basins: list[str] | None = None,
    comarcas: list[str] | None = None,
    municipis: list[str] | None = None,
    aquifers: list[str] | None = None,
    masses: list[str] | None = None,
    reservoirs: list[str] | None = None,
    stations: dict[str, list[str]] | None = None,
    spatial_codes: dict[str, list[str]] | None = None,
    max_stations: int = 100,
    start: str = "",
    end: str = "",
    ** _extra,
) -> ResolvedRequest:
    """Resolve a semantic request into codes.

    ``parameters``, spatial names (``rivers``, ...) and ``stations`` may be
    explicit codes or human-readable names. ``stations`` may also be a plain
    list of codes (series are selected from the target's station-variable table).
    """
    if not start or not end:
        raise SDIMQueryError("start and end dates are required")
    targets = cat.targets(period)

    # --- 1. pick the target -----------------------------------------------
    if target is not None:
        if ":" in target:
            period = target.split(":")[0]  # "before_2007:0005:0011" -> period
        row = cat.target(target if ":" in target else f"{period}:{target}")
        if row is None:
            raise SDIMQueryError(f"Unknown target {target!r}; see cat.targets()")
        net, sub = row["network"], row["subnetwork"]
    else:
        candidates = targets.copy()
        if networks:
            candidates = candidates[candidates.network.isin([_zc(n) for n in networks])]
        if subnetworks:
            candidates = candidates[candidates.subnetwork.isin([_zc(n) for n in subnetworks])]
        if water_type:
            key = water_type.lower().strip()
            seeds = _NETS_BEFORE.get(key) if period == PERIOD_BEFORE_2007 else _NETS_AFTER.get(key)
            if seeds:
                candidates = candidates[candidates.network.isin(seeds)]
            elif "levels" in key:
                candidates = candidates[candidates.category.str.contains("levels")]
            elif "quant" in key or "volume" in key or "flow" in key or "cabals" in key:
                candidates = candidates[candidates.category.str.contains("quantity")]
            else:
                raise SDIMQueryError(f"Unknown water_type {water_type!r}")
        if candidates.empty:
            raise SDIMQueryError("No target matches the given selection (targets.csv is empty?).")
        # parameter coverage: candidates that contain ALL requested parameters
        if parameters:
            codes = [resolve_parameter(cat, p, period) for p in parameters]
            keep = []
            for _, cand in candidates.iterrows():
                tv = cat.variables_for(cand.network, cand.subnetwork, period=period)
                ok = all(any(c == v for v in tv.v) for c in codes)
                keep.append(ok)
            candidates = candidates[keep]
        if candidates.empty:
            raise SDIMQueryError(
                "No target in this period contains all requested parameters "
                f"{parameters!r}.")
        # prefer the default water-type seed target when it survives the filter
        if water_type:
            key = water_type.lower().strip()
            table = _DEFAULT_BEFORE if period == PERIOD_BEFORE_2007 else _DEFAULT_AFTER
            seed = table.get(key)
            if seed:
                m = (candidates.network == seed[0]) & (candidates.subnetwork == seed[1])
                if m.any():
                    candidates = candidates[m]
        candidates = candidates.sort_values("series_count") if "series_count" in candidates.columns else candidates
        row = candidates.iloc[0]
        net, sub = row["network"], row["subnetwork"]

    target_id = f"{period}:{net}:{sub}"

    # --- 2. parameter kinds ------------------------------------------------
    param_codes: list[str] = []
    param_terms: list[str] = []
    kinds = list(variable_kinds or [])
    tv = None
    if parameters:
        for p in parameters:
            param_codes.append(resolve_parameter(cat, p, period))
        tv = cat.variables_for(net, sub, period=period)
        matched = tv[tv.v.isin(param_codes)]
        if matched.empty:
            raise SDIMQueryError(
                f"Target {target_id} has none of the requested parameters "
                f"{parameters!r}")
        param_terms = [str(m) for m in matched.v_name.unique()]
        kinds = ([("g", x) for x in matched.g.unique()]
                 + [("f", x) for x in matched.f.unique()]
                 + [("v", x) for x in matched.v.unique()])
    elif not kinds:
        tv = cat.variables_for(net, sub, period=period)
        kinds = ([("g", x) for x in tv.g.unique()]
                 + [("f", x) for x in tv.f.unique()]
                 + [("v", x) for x in tv.v.unique()])

    # --- 3. spatial --------------------------------------------------------
    spatial, spatial_ambit = {}, ambit
    given = [
        (rivers, "rivers"), (basins, "basins"), (comarcas, "comarcas"),
        (municipis, "municipis"), (aquifers, "aquifers"), (masses, "masses"),
        (reservoirs, "reservoirs"),
    ]
    provided = [f for names, f in given if names]
    if len({_AMBIT_BY_FIELD[SPATIAL_FLAVORS[f][1]] for f in provided}) > 1:
        raise SDIMQueryError(
            "SDIM supports one spatial ambit per report; use a single type of "
            "spatial filter (rivers OR basins OR comarcas, ...).")
    for names, flavor in given:
        if not names:
            continue
        table, field = SPATIAL_FLAVORS[flavor][0], SPATIAL_FLAVORS[flavor][1]
        codes = []
        for n in names:
            if str(n).isdigit():
                codes.append(str(n))
                continue
            df = cat.table(table)
            if period in df.columns:
                df = df[df.period == period]
            mask = _name_series(df["name"], n, ends_with=True)
            hits = df[mask]
            if hits.empty:
                raise SDIMQueryError(f"No {flavor[:-1]} matches {n!r}.")
            codes.extend(hits["code"].unique())
        spatial.setdefault(field, []).extend(dict.fromkeys(codes))
        if spatial_ambit is None:
            spatial_ambit = _AMBIT_BY_FIELD[field]
    spatial.update(spatial_codes or {})
    # the spatial field itself dictates the ambit (rio + riuAmbit -> "riu")
    if spatial:
        ambits = {_AMBIT_BY_FIELD[f] for f in spatial if f in _AMBIT_BY_FIELD}
        if len(ambits) == 1:
            spatial_ambit = ambits.pop()
    if not spatial:
        spatial_ambit = spatial_ambit or (ambit if ambit else "catalunya")

    # --- 4. stations → variable series -------------------------------------
    if stations is None:
        station_map = None
    elif isinstance(stations, dict):
        # {code: [codes or parameter names]}: resolve each value per station
        station_map = {}
        for code, vals in stations.items():
            ids = _station_series(cat, target_id, [code], param_terms,
                                  hint_values=vals)
            if ids:
                station_map[code] = ids
    else:
        # plain list of station codes -> their series for this target
        station_map = {}
        for code in stations:
            ids = _station_series(cat, target_id, [code], param_terms)
            if ids:
                station_map[code] = ids

    resolved = ResolvedRequest(
        target_id=target_id,
        networks=[_zc(net)],
        subnetworks=[_zc(sub)],
        variable_kinds=kinds,
        ambit=spatial_ambit or "catalunya",
        spatial=spatial,
        stations=station_map or {},
        cercador={},
        start=start,
        end=end,
        period=period,
        series_filter=param_terms,
    )
    return resolved


def resolve_parameter(cat: Catalog, term: str, period: str) -> str:
    """Return the SDIM ``v`` code for a parameter name (+ alias)."""
    q = ALIASES.get(term.lower().strip(), term)
    df = cat.table("variables")
    df = df[df.period == period]
    mask = _name_series(df["v_name"], q)
    hits = df[mask]
    if hits.empty:
        raise SDIMQueryError(f"No SDIM parameter matches {term!r} (period {period}).")
    # prefer an exact v_name match over a partial one
    exact = hits[hits.v_name.map(_norm) == _norm(str(q))]
    return str((exact if len(exact) else hits).iloc[0]["v"])


def _station_series(
    cat: Catalog, target_id: str, station_codes: list[str],
    param_terms: list[str], hint_values: list[str] | None = None,
) -> list[str]:
    """Variable-series ids of ``station_codes`` in a target.

    ``param_terms`` limits series to matching names. ``hint_values`` may give
    exact series ids or extra parameter names to look up.
    """
    df = cat.target_station_variables(target_id)
    if df.empty:
        raise SDIMQueryError(f"No station-variable data for target {target_id}.")
    df = df[df.station.isin(station_codes)]
    if df.empty:
        return []

    terms = list(param_terms)
    exact_ids: list[str] = []
    for v in hint_values or []:
        vs = str(v)
        if vs.isdigit():
            exact_ids.append(vs)
        else:
            terms.append(ALIASES.get(vs.lower().strip(), vs))
    if exact_ids:
        df = df[df.variable_id.isin(exact_ids)]
    if terms:
        blob = df["variable_name"].map(_norm)
        df = df[blob.apply(lambda b: any(b.find(_norm(t)) >= 0 for t in terms))]
    return df.variable_id.unique().tolist()


def _zc(code: str) -> str:
    return str(code).zfill(4) if str(code).isdigit() else str(code)