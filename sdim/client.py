"""High-level ACA SDIM client."""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .exceptions import (
    SDIMError,
    SDIMExportError,
    SDIMNoData,
    SDIMQueryError,
    SDIMServerError,
)
from .parser import parse_export
from .query import Query
from .result import SDIMResult, add_station_context, provenance, validate
from .session import SDIMSession
from .catalog import _norm

SDIM_BASE = "https://aplicacions.aca.gencat.cat/sdim21"

# HTTP status meanings of consultaInforme.do (server uses non-standard codes):
# 200 = report generated, 201 = no records, 202 = too many records (truncated).
_STAT_200 = 200
_STAT_NO_DATA = 201
_STAT_TRUNCATED = 202

# most stations a name-based request may select before asking for a filter
DEFAULT_MAX_STATIONS = 200
# most reports one get_data() call may generate when splitting a large request
DEFAULT_MAX_REQUESTS = 64


def _iso_date(value: str) -> date:
    value = value.strip()
    if "/" in value:  # DD/MM/YYYY
        d, m, y = value.split("/")
        return date(int(y), int(m), int(d))
    return date.fromisoformat(value)


def split_query(query: Query) -> list[Query] | None:
    """Halve a query SDIM refused as too large: by stations while there is more
    than one, then by date range (SDIM's end date is inclusive, so the halves
    do not overlap). Returns ``None`` when it cannot be split further."""
    stations = list(query.stations.items())
    if len(stations) > 1:
        mid = len(stations) // 2
        return [dataclasses.replace(query, stations=dict(stations[:mid])),
                dataclasses.replace(query, stations=dict(stations[mid:]))]
    start, end = _iso_date(query.start), _iso_date(query.end)
    if end <= start:
        return None
    mid = start + (end - start) // 2
    return [dataclasses.replace(query, start=start.isoformat(), end=mid.isoformat()),
            dataclasses.replace(query, start=(mid + timedelta(days=1)).isoformat(),
                                end=end.isoformat())]


class SDIM:
    """Programmatic access to ACA SDIM data.

    The session is bootstrapped automatically (``GET /sdim21/`` sets the
    ``JSESSIONID``), so no manual cookie copying is required.

    ``get_data``/``download`` accept either a :class:`~sdim.query.Query` or
    semantic keyword arguments (``target``, ``water_type``, ``parameters``,
    ``rivers``, ...) that are resolved to codes via the metadata catalog.
    """

    def __init__(self, *, delay: float = 0.6, timeout: float = 90.0,
                 metadata_dir: str | Path | None = None):
        self._session = SDIMSession(delay=delay, timeout=timeout)
        self._periods_ready: set[str] = set()
        self._catalog = None
        self._metadata_dir = metadata_dir

    # -- low level ---------------------------------------------------------

    def _bootstrap(self, period: str) -> None:
        """Create the session and walk the SDIM entry forms so the server-side
        session is ready to generate reports for ``period``."""
        if period in self._periods_ready:
            return
        self._session.initialize()
        self._session.post(
            SDIM_BASE + "/seleccioXarxes.do",
            data={"accio": "seleccioXarxa", "page": "inici"},
        )
        r = self._session.post(
            SDIM_BASE + "/filtre.do",
            data={
                "accio": "puntsDeControl",
                "page": "periodeControl",
                "periodeXarxaControl": period,
            },
        )
        if r.status_code != 200:
            raise SDIMServerError(f"filtre.do -> HTTP {r.status_code}")
        self._periods_ready.add(period)

    def _generate(self, query: Query) -> int:
        self._bootstrap(query.period)
        headers = {"Referer": SDIM_BASE + "/filtre.do"}
        r = self._session.post(
            SDIM_BASE + "/consultaInforme.do",
            params={"format": "excel"},
            data=query.to_sdim_payload(),
            headers=headers,
        )
        return r.status_code

    def _download(self) -> bytes:
        headers = {"Referer": SDIM_BASE + "/consultaInforme.do"}
        r = self._session.get(
            SDIM_BASE + "/exportar.do",
            params={"format": "XLS"},
            headers=headers,
        )
        if r.status_code != 200 or not r.content:
            raise SDIMExportError(f"exportar.do -> HTTP {r.status_code}")
        return r.content

    # -- public API --------------------------------------------------------

    @property
    def catalog(self):
        if self._catalog is None:
            from .catalog import Catalog
            self._catalog = Catalog(self._metadata_dir) if self._metadata_dir else Catalog()
        return self._catalog

    def _build_query(self, kw: dict) -> Query:
        """Resolve semantic kwargs into a Query (auto-selecting stations)."""
        from . import resolver

        self.catalog  # ensure metadata is available
        res = resolver.resolve_request(self.catalog, **kw)
        station_map = res.stations
        if not station_map:
            station_map = self._resolve_stations(res)
        if not station_map:
            raise SDIMQueryError(
                f"No station in target {res.target_id} matches the request; "
                "loosen parameters or spatial filter.")
        limit = kw.get("max_stations", DEFAULT_MAX_STATIONS)
        if len(station_map) > limit:
            raise SDIMQueryError(
                f"Request selects {len(station_map)} stations (limit "
                f"{limit}). Add a spatial filter, explicit stations, or "
                "raise max_stations.")
        res.stations = station_map
        return res.to_query()

    def _resolve_stations(self, res) -> dict[str, list[str]]:
        """Get station→series for a resolved request (live for spatial filters)."""
        catalog = self.catalog
        terms = res.series_filter

        def keep(name) -> bool:
            if not terms:
                return True
            n = _norm(str(name))
            return any(n.find(_norm(t)) >= 0 for t in terms)

        if res.spatial:
            # spatial selection needs the live station layer for this target
            from .discovery import Discovery
            d = Discovery(session=self._session, delay=0.4, timeout=self._session.timeout)
            d._bootstrap(res.period)
            records = d.detail_select(
                res.period, res.networks[0], res.subnetworks,
                variable_kinds=res.variable_kinds,
                ambit=res.ambit, spatial=res.spatial,
            )
            out: dict[str, list[str]] = {}
            for rec in records:
                ids = [vid for vid, vname in rec["variables"] if keep(vname)]
                if ids:
                    out[rec["station"]] = ids
            return out

        # offline per-target table (no spatial filter)
        df = catalog.target_station_variables(res.target_id)
        if df.empty:
            return {}
        if terms:
            blob = df["variable_name"].map(lambda n: _norm(str(n)))
            df = df[blob.apply(lambda b: any(b.find(_norm(t)) >= 0 for t in terms))]
        out: dict[str, list[str]] = {}
        for st, g in df.groupby("station"):
            out[st] = g["variable_id"].unique().tolist()
        return out

    def download(self, query: Query | None = None, output: str | Path | None = None,
                 **kw) -> bytes:
        """Generate and download a report.

        ``query`` is a :class:`~sdim.query.Query`; alternatively pass semantic
        keyword arguments (``target``, ``water_type``, ``parameters``,
        ``rivers``, ...) that get resolved automatically.
        """
        if query is None:
            query = self._build_query(kw)
        status = self._generate(query)
        if status == _STAT_TRUNCATED:
            raise SDIMError(
                "The report exceeds SDIM's maximum number of records. download() "
                "returns one raw file and cannot split it; use get_data(), which "
                "splits large requests automatically, or narrow the query.")
        self._raise_for_status(status)
        data = self._download()
        if output is not None:
            Path(output).write_bytes(data)
        return data

    def get_data(self, query: Query | None = None, *, split: bool = True,
                 max_requests: int = DEFAULT_MAX_REQUESTS, station_context: bool = True,
                 validate_output: bool = True, **kw) -> SDIMResult:
        """Download a report and parse it into DataFrames.

        Accepts a :class:`~sdim.query.Query` or semantic keyword arguments
        (``target``, ``water_type``, ``parameters``, ``groups``, ``rivers``, ...).

        Returns an :class:`~sdim.result.SDIMResult` (a dict of ``"quality"`` /
        ``"quantity"`` DataFrames with ``provenance``).

        ``split``: when SDIM refuses a report as too large, split it by
        stations and then by date range (at most ``max_requests`` reports) and
        concatenate the parts. ``station_context``: add catalog station ids,
        names and target names. ``validate_output``: raise
        :class:`~sdim.exceptions.SDIMParseError` on broken parses and warn
        on empty or partly unresolved reports.
        """
        if query is None:
            query = self._build_query(kw)
        parts: list[dict[str, pd.DataFrame]] = []
        requests = self._fetch(query, parts, split=split, budget=[max_requests])
        if not parts:
            raise SDIMNoData("The SDIM report contains no records for this query.")
        sheets: dict[str, pd.DataFrame] = {}
        for name in ("quality", "quantity"):
            frames = [p[name] for p in parts if name in p and len(p[name])]
            if frames:
                sheets[name] = pd.concat(frames, ignore_index=True)
            elif any(name in p for p in parts):
                sheets[name] = pd.DataFrame()
        if station_context:
            sheets = {k: add_station_context(df, self.catalog, query)
                      for k, df in sheets.items()}
        for df in sheets.values():
            df.attrs["query"] = query
        result = SDIMResult(sheets, provenance(query, requests=requests))
        if validate_output:
            validate(result)
        return result

    def _fetch(self, query: Query, parts: list, *, split: bool, budget: list[int]) -> int:
        """Generate/download ``query`` into ``parts``, splitting truncated
        reports; returns the number of reports requested."""
        if budget[0] <= 0:
            raise SDIMError(
                "Splitting this request needs more reports than max_requests "
                "allows; narrow the query or raise max_requests.")
        budget[0] -= 1
        status = self._generate(query)
        if status == _STAT_TRUNCATED and split:
            halves = split_query(query)
            if halves is None:
                raise SDIMError(
                    "SDIM refuses even a one-station, one-day report as too large.")
            return 1 + sum(self._fetch(h, parts, split=split, budget=budget) for h in halves)
        if status == _STAT_NO_DATA:
            return 1
        self._raise_for_status(status)
        parts.append(parse_export(self._download()))
        return 1

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if status == _STAT_NO_DATA:
            raise SDIMNoData("The SDIM report contains no records for this query.")
        if status == _STAT_TRUNCATED:
            raise SDIMError(
                "The report exceeds SDIM's maximum number of records; "
                "narrow the query or reduce the date range."
            )
        if status != _STAT_200:
            raise SDIMServerError(f"consultaInforme.do -> HTTP {status}")

    def close(self) -> None:
        self._session.close()
        self._periods_ready.clear()