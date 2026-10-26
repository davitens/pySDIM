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

# water_type -> period -> (candidate networks, default (network, subnetwork)).
# The default pins the target when parameters/groups do not; None means "pick
# the smallest candidate that has them". A period missing from an entry means
# SDIM has no such data for it. Any category in targets.csv ("biological",
# "metals", "quantity", ...) also works as a water_type.
# Before 2007, river and reservoir quality share one target (0000:0017), so
# "reservoir" selects it; filter with reservoirs=[...] to keep reservoirs.
_A, _B = PERIOD_AFTER_2007, PERIOD_BEFORE_2007
WATER_TYPES: dict[str, dict[str, tuple[list[str], tuple[str, str] | None]]] = {
    "river": {_A: (["0001"], ("0001", "0022")), _B: (["0000", "0001"], ("0000", "0017"))},
    "groundwater": {_A: (["0005"], ("0005", "0010")), _B: (["0000", "0005"], ("0000", "0019"))},
    "levels": {_A: (["0005"], ("0005", "0011")), _B: (["0000", "0005"], ("0000", "0020"))},
    "flow": {_A: (["0001"], ("0001", "0301")), _B: (["0001"], ("0001", "0301"))},
    "volumes": {_A: (["0002"], ("0002", "0302")), _B: (["0002"], ("0002", "0302"))},
    "reservoir": {_A: (["0002"], ("0002", "0023")), _B: (["0000"], ("0000", "0017"))},
    "lake": {_A: (["0003"], ("0003", "0025"))},
    "coastal": {_A: (["0004"], ("0004", "0008")), _B: (["0004"], ("0004", "0009"))},
    "protected": {_A: (["0006"], ("0006", "0012")), _B: (["0006"], ("0006", "0014"))},
    "river_biology": {_A: (["0001"], ("0001", "0001")), _B: (["0000"], ("0000", "0017"))},
    "lake_biology": {_A: (["0003"], ("0003", "0005"))},
    "reservoir_biology": {_A: (["0002"], ("0002", "0003")), _B: (["0000"], ("0000", "0017"))},
    "coastal_biology": {_A: (["0004"], ("0004", "0007")), _B: (["0000", "0004"], ("0004", "0007"))},
}
# Catalan and alternative names
WATER_TYPE_ALIASES = {
    "cabals": "flow", "volums": "volumes", "embassament": "reservoir",
    "estany": "lake", "zones humides": "lake", "costanera": "coastal",
    "zones protegides": "protected", "nivells": "levels",
}

# water types that select only the biological-index group by default (needed
# before 2007, where biology shares a target with physico-chemical series)
BIOLOGY_GROUP = "Índexs biològics"
_BIOLOGY_WATER_TYPES = {"river_biology", "lake_biology", "reservoir_biology",
                        "coastal_biology"}

# water_source -> data_type -> period -> (network, subnetwork, groups).
# This mirrors SDIM's own menus: a control network (rius, embassaments, ...)
# and the kind of data in it. ``groups`` narrows a target that mixes kinds
# (groundwater quality, the pre-2007 river+reservoir target, protected zones).
_PHYS, _BIO = ["Fisicoquímics"], [BIOLOGY_GROUP]
_PRIO = ["Metalls", "Microcontaminants orgànics"]
_HYDRO = ["Índexs hidromorfològics"]
DATA_SOURCES: dict[str, dict[str, dict[str, tuple[str, str, list[str] | None]]]] = {
    "river": {
        "physico_chemical": {_A: ("0001", "0022", None), _B: ("0000", "0017", _PHYS)},
        "biological": {_A: ("0001", "0001", None), _B: ("0000", "0017", _BIO)},
        "priority_substances": {_A: ("0001", "0002", None), _B: ("0000", "0017", _PRIO)},
        "hydromorphological": {_A: ("0001", "0021", None)},
        "flow": {_A: ("0001", "0301", None), _B: ("0001", "0301", None)},
        "level": {_A: ("0001", "0303", None), _B: ("0001", "0303", None)},
    },
    # before 2007 reservoirs share the river target: filter with area_type="reservoir"
    "reservoir": {
        "physico_chemical": {_A: ("0002", "0023", None), _B: ("0000", "0017", _PHYS)},
        "biological": {_A: ("0002", "0003", None), _B: ("0000", "0017", _BIO)},
        "priority_substances": {_A: ("0002", "0004", None), _B: ("0000", "0017", _PRIO)},
        "volume": {_A: ("0002", "0302", None), _B: ("0002", "0302", None)},
    },
    "groundwater": {
        "physico_chemical": {_A: ("0005", "0010", _PHYS), _B: ("0000", "0019", _PHYS)},
        "priority_substances": {_A: ("0005", "0010", _PRIO), _B: ("0000", "0019", _PRIO)},
        "level": {_A: ("0005", "0011", None), _B: ("0000", "0020", None)},
    },
    "lakes_and_wetlands": {
        "physico_chemical": {_A: ("0003", "0025", None)},
        "biological": {_A: ("0003", "0005", None)},
        "priority_substances": {_A: ("0003", "0006", None)},
        "hydromorphological": {_A: ("0003", "0024", None)},
    },
    "coastal": {
        "physico_chemical": {_A: ("0004", "0008", None), _B: ("0000", "0018", _PHYS)},
        "biological": {_A: ("0004", "0007", None), _B: ("0004", "0007", None)},
        "priority_substances": {_A: ("0004", "0009", None), _B: ("0004", "0009", None)},
    },
    # protected zones mix data kinds per zone: data_type only selects groups
    "protected": {
        "physico_chemical": {_A: ("0006", None, _PHYS), _B: ("0006", "0014", _PHYS)},
        "biological": {_A: ("0006", None, _BIO)},
        "priority_substances": {_A: ("0006", None, _PRIO)},
        "hydromorphological": {_A: ("0006", None, _HYDRO)},
    },
}
WATER_SOURCE_ALIASES = {
    "rivers": "river", "riu": "river", "rius": "river",
    "reservoirs": "reservoir", "embassament": "reservoir", "embassaments": "reservoir",
    "aigues subterranies": "groundwater", "subterranies": "groundwater",
    "lake": "lakes_and_wetlands", "lakes": "lakes_and_wetlands",
    "wetlands": "lakes_and_wetlands", "estanys": "lakes_and_wetlands",
    "estanys i zones humides": "lakes_and_wetlands", "zones humides": "lakes_and_wetlands",
    "coastal_waters": "coastal", "costaneres": "coastal",
    "aigues costaneres": "coastal", "aigues costaneres i badies": "coastal",
    "protected_areas": "protected", "protected_zones": "protected",
    "zones protegides": "protected",
}
DATA_TYPE_ALIASES = {
    "physicochemical": "physico_chemical", "phys_chem": "physico_chemical",
    "physical_chemical": "physico_chemical", "fisicoquimics": "physico_chemical",
    "fisicoquimic": "physico_chemical", "elements fisicoquimics": "physico_chemical",
    "bio": "biological", "biology": "biological", "biologic": "biological", "biologics": "biological",
    "biological_indices": "biological", "indexs biologics": "biological",
    "elements biologics": "biological",
    "priority": "priority_substances", "metals": "priority_substances",
    "substancies prioritaries": "priority_substances",
    "substancies prioritaries i preferents": "priority_substances",
    "hydromorphology": "hydromorphological", "hidromorfologics": "hydromorphological",
    "elements hidromorfologics": "hydromorphological",
    "flows": "flow", "cabal": "flow", "cabals": "flow",
    "levels": "level", "nivell": "level", "nivells": "level",
    "piezometric": "level", "nivells piezometrics": "level",
    "volumes": "volume", "volum": "volume", "volums": "volume",
}
# protected_zone -> subnetwork of CONTROL ZONES PROTEGIDES (0006)
PROTECTED_ZONES = {
    "drinking_water": "0012", "river_reserves": "0013",
    "nitrate_vulnerable": "0014", "eutrophication_sensitive": "0016",
}
PROTECTED_ZONE_ALIASES = {
    "abastament": "drinking_water", "abastament urba": "drinking_water",
    "reserves naturals fluvials": "river_reserves", "reserves fluvials": "river_reserves",
    "zones vulnerables": "nitrate_vulnerable", "nitrate": "nitrate_vulnerable",
    "zones sensibles": "eutrophication_sensitive", "eutrophication": "eutrophication_sensitive",
}

# area_type -> spatial flavor (SDIM's "Àmbit" menu); "catalunya" = no filter
AREA_TYPES = {
    "catalunya": None, "basin": "basins", "water_mass": "masses", "river": "rivers",
    "reservoir": "reservoirs", "aquifer": "aquifers", "comarca": "comarcas",
    "municipi": "municipis",
}
AREA_TYPE_ALIASES = {
    "catalonia": "catalunya", "all": "catalunya",
    "basins": "basin", "conca": "basin", "conques": "basin", "river_basin": "basin",
    "water_masses": "water_mass", "massa": "water_mass", "masses": "water_mass",
    "massa d'aigua": "water_mass", "masses d'aigua": "water_mass",
    "rivers": "river", "riu": "river", "rius": "river",
    "reservoirs": "reservoir", "embassament": "reservoir", "embassaments": "reservoir",
    "aquifers": "aquifer",
    "comarcas": "comarca", "comarques": "comarca",
    "municipis": "municipi", "municipality": "municipi", "municipalities": "municipi",
}


def _key(value: str, aliases: dict[str, str]) -> str:
    key = _norm(str(value)).strip().replace("-", "_")
    key = aliases.get(key, aliases.get(key.replace("_", " "), key))
    return key


def data_sources(period: str | None = None):
    """Table of every ``water_source`` / ``data_type`` pair and the SDIM
    target it downloads, optionally for one period."""
    import pandas as pd

    rows = []
    for source, types in DATA_SOURCES.items():
        for dtype, per_period in types.items():
            for per, (net, sub, groups) in per_period.items():
                if period is None or per == period:
                    rows.append({
                        "water_source": source, "data_type": dtype, "period": per,
                        "target_id": f"{per}:{net}:{sub}" if sub else f"{per}:{net}:*",
                        "groups": ", ".join(groups) if groups else "",
                    })
    return pd.DataFrame(rows)


def _source_target(cat: Catalog, water_source: str, data_type: str | None,
                   period: str, protected_zone: str | None,
                   parameters: list[str] | None) -> tuple[str, list[str] | None]:
    """Target id and implied groups for a ``water_source`` / ``data_type``."""
    source = _key(water_source, WATER_SOURCE_ALIASES)
    if source not in DATA_SOURCES:
        raise SDIMQueryError(
            f"Unknown water_source {water_source!r}; use one of {sorted(DATA_SOURCES)}.")
    types = DATA_SOURCES[source]
    here = [t for t, per in types.items() if period in per]
    if not here:
        raise SDIMQueryError(f"SDIM has no {source!r} data for {period}.")

    if data_type is not None:
        dtype = _key(data_type, DATA_TYPE_ALIASES)
        if dtype not in types:
            raise SDIMQueryError(
                f"{source!r} has no data_type {data_type!r}; use one of {sorted(types)}.")
        if period not in types[dtype]:
            raise SDIMQueryError(
                f"SDIM has no {source!r} {dtype!r} data for {period}; it is only "
                f"available for {', '.join(sorted(types[dtype]))}.")
    elif parameters:
        # the first data type whose target holds every requested parameter
        codes = [resolve_parameter(cat, p, period) for p in parameters]
        dtype = None
        for t in here:
            net, sub, _ = types[t][period]
            tv = cat.variables_for(net, sub or PROTECTED_ZONES["drinking_water"], period=period)
            if all((tv.v == c).any() for c in codes):
                dtype = t
                break
        if dtype is None:
            raise SDIMQueryError(
                f"No {source!r} data type has all of {parameters!r} in {period}.")
    else:
        dtype = "physico_chemical" if "physico_chemical" in here else here[0]

    net, sub, groups = types[dtype][period]
    if source == "protected":
        if protected_zone is not None:
            zone = _key(protected_zone, PROTECTED_ZONE_ALIASES)
            if zone not in PROTECTED_ZONES:
                raise SDIMQueryError(
                    f"Unknown protected_zone {protected_zone!r}; use one of "
                    f"{sorted(PROTECTED_ZONES)}.")
            sub = PROTECTED_ZONES[zone]
        elif sub is None:
            sub = PROTECTED_ZONES["drinking_water"]
    elif protected_zone is not None:
        raise SDIMQueryError("protected_zone only applies to water_source='protected'.")
    target_id = f"{period}:{net}:{sub}"
    if cat.target(target_id) is None:
        raise SDIMQueryError(f"SDIM has no {source!r} {dtype!r} data in {target_id}.")
    return target_id, groups


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


def _water_type_key(water_type: str) -> str:
    key = water_type.lower().strip().replace("-", "_")
    return WATER_TYPE_ALIASES.get(key, key)


def water_types(period: str | None = None) -> list[str]:
    """Named water types (optionally only those defined for ``period``)."""
    return sorted(k for k, v in WATER_TYPES.items() if period is None or period in v)


def _group_mask(tv, groups: list[str]):
    """Rows of a variables table whose group (``g_name``) or family
    (``f_name``) name contains any of ``groups`` (accent-insensitive)."""
    terms = [_norm(g) for g in groups]

    def hit(col: str):
        return tv[col].map(lambda n: any(t in _norm(str(n)) for t in terms))

    return hit("g_name") | hit("f_name")


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
    water_source: str | None = None,
    data_type: str | None = None,
    protected_zone: str | None = None,
    area_type: str | None = None,
    areas: list[str] | None = None,
    water_type: str | None = None,
    networks: list[str] | None = None,
    subnetworks: list[str] | None = None,
    parameters: list[str] | None = None,
    groups: list[str] | None = None,
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
    max_stations: int | None = None,
    start: str = "",
    end: str = "",
    ** _extra,
) -> ResolvedRequest:
    """Resolve a semantic request into codes.

    ``water_source`` (``river``, ``reservoir``, ``groundwater``,
    ``lakes_and_wetlands``, ``coastal``, ``protected``) and ``data_type``
    (``physico_chemical``, ``biological``, ``priority_substances``,
    ``hydromorphological``, ``flow``, ``level``, ``volume``) pick the target as
    SDIM's menus do; see :func:`data_sources`. ``area_type`` (``basin``,
    ``water_mass``, ``river``, ``reservoir``, ``aquifer``, ``comarca``,
    ``municipi`` or ``catalunya``) and ``areas`` are the spatial filter, an
    alternative to ``rivers=``, ``comarcas=``, ...

    ``parameters``, spatial names (``rivers``, ...) and ``stations`` may be
    explicit codes or human-readable names. ``groups`` limits the series to
    variable groups or families by name (``"Índexs biològics"``,
    ``"Invertebrats"``, ``"Nutrients"``); the ``*_biology`` water types imply
    ``groups=["Índexs biològics"]``. ``stations`` may also be a plain
    list of codes (series are selected from the target's station-variable table).
    """
    if not start or not end:
        raise SDIMQueryError("start and end dates are required")
    if water_source is not None:
        if target is not None or water_type is not None:
            raise SDIMQueryError("Pass water_source/data_type, water_type or target, not several.")
        target, implied = _source_target(cat, water_source, data_type, period,
                                         protected_zone, parameters)
        if not groups and not variable_kinds:
            groups = implied
    elif data_type is not None or protected_zone is not None:
        raise SDIMQueryError("data_type and protected_zone need a water_source.")
    if area_type is not None:
        kind = _key(area_type, AREA_TYPE_ALIASES)
        if kind not in AREA_TYPES:
            raise SDIMQueryError(
                f"Unknown area_type {area_type!r}; use one of {sorted(AREA_TYPES)}.")
        flavor = AREA_TYPES[kind]
        if flavor is None:
            if areas:
                raise SDIMQueryError("area_type='catalunya' takes no areas.")
        elif not areas:
            raise SDIMQueryError(f"area_type={area_type!r} needs areas=[...] names or codes.")
        else:
            given_names = {"rivers": rivers, "basins": basins, "comarcas": comarcas,
                           "municipis": municipis, "aquifers": aquifers,
                           "masses": masses, "reservoirs": reservoirs}
            merged = list(given_names[flavor] or []) + list(areas)
            rivers, basins, comarcas, municipis, aquifers, masses, reservoirs = (
                merged if f == flavor else given_names[f] for f in given_names)
    elif areas:
        raise SDIMQueryError("areas=[...] needs an area_type (comarca, basin, river, ...).")
    targets = cat.targets(period)
    if (water_type and _water_type_key(water_type) in _BIOLOGY_WATER_TYPES
            and not groups and not parameters and not variable_kinds):
        groups = [BIOLOGY_GROUP]

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
            key = _water_type_key(water_type)
            entry = WATER_TYPES.get(key, {}).get(period)
            if entry:
                candidates = candidates[candidates.network.isin(entry[0])]
            elif key in WATER_TYPES:
                periods = ", ".join(sorted(WATER_TYPES[key]))
                raise SDIMQueryError(
                    f"SDIM has no {water_type!r} data for {period}; it is only "
                    f"available for {periods}.")
            elif candidates.category.str.contains(key, regex=False).any():
                candidates = candidates[candidates.category.str.contains(key, regex=False)]
            else:
                raise SDIMQueryError(
                    f"Unknown water_type {water_type!r} for {period}; use one of "
                    f"{water_types(period)} or a targets.csv category.")
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
        if groups:
            candidates = candidates[[
                bool(_group_mask(cat.variables_for(c.network, c.subnetwork, period=period),
                                 groups).any())
                for _, c in candidates.iterrows()]]
            if candidates.empty:
                raise SDIMQueryError(
                    f"No target in this period has variable groups {groups!r}.")
        # prefer the default water-type seed target when it survives the filter
        if water_type:
            seed = WATER_TYPES.get(_water_type_key(water_type), {}).get(period, (None, None))[1]
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
    if parameters or groups:
        for p in parameters or []:
            param_codes.append(resolve_parameter(cat, p, period))
        tv = cat.variables_for(net, sub, period=period)
        matched = tv[tv.v.isin(param_codes)] if parameters else tv
        if groups:
            matched = matched[_group_mask(matched, groups)]
        if matched.empty:
            raise SDIMQueryError(
                f"Target {target_id} has none of the requested "
                + (f"parameters {parameters!r}" if parameters else "")
                + (" in " if parameters and groups else "")
                + (f"groups {groups!r}" if groups else ""))
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
            if "period" in df.columns:
                df = df[df.period == period]
            mask = _name_series(df["name"], n, ends_with=True)
            hits = df[mask]
            if hits.empty:
                raise SDIMQueryError(
                    f"No {flavor[:-1]} matches {n!r} in {period} (see {table}.csv).")
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