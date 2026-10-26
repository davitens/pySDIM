# Changelog

All notable changes to pySDIM are documented here.

## [Unreleased]

### Added

- `river_biology`, `lake_biology`, `reservoir_biology` and `coastal_biology`
  water types for the biological-index targets ("Índexs biològics").
- `groups=[...]` (CLI `--group`) to select variables by group or family name,
  e.g. `"Índexs biològics"`, `"Invertebrats"`, `"Nutrients"`.
- Biological targets in `scripts/verify_targets.py`, which now also flags
  exports with no rows or an empty `station_code` column.
- `get_data()` splits reports SDIM refuses as too large (by stations, then by
  date range; `split=`, `max_requests=`) and joins the parts.
- `get_data()` returns an `SDIMResult` (still a dict of DataFrames) with
  `quality`, `quantity`, `provenance` and `save()`; each DataFrame carries
  `attrs["provenance"]` (source, URL, access time, target, range, version,
  citation).
- Catalog station context on every row: `station_id`, `station_name`,
  `target_id`, `network`, `network_name`, `subnetwork`, `subnetwork_name`
  (`station_context=False` skips it).
- Output checks: `SDIMParseError` when a key column parses empty, and
  `SDIMWarning` for empty reports, bad dates or uncatalogued stations
  (`validate_output=False` skips them).
- Quality columns that were dropped: `depth_m`, `well_depth_m`,
  `piezometric_level_masl`; unknown export columns are kept by header name.
- CLI commands `sdim get` (parsed CSVs + provenance JSON), `sdim targets` and
  `sdim describe`.
- `water_type` accepts any `targets.csv` category and Catalan aliases
  (`cabals`, `volums`, `estany`, ...).

### Changed

- **`date` is now `datetime64`** and `utm_x` / `utm_y` are floats (they were
  strings).
- **Quantity sheets:** the export's `Estació` column (a station *name*) is now
  `station_name`; `station_code` holds the station code taken from the series
  name (`EA010_Girona_Cabal riu Ter` -> `EA010`).
- One `max_stations` default (200) across the API and CLI; water types live in
  a single `WATER_TYPES` table in `sdim/resolver.py`.

### Fixed

- `station_code` was always empty for live exports: SDIM now sends headers
  as mis-decoded UTF-8 (`Codi EstaciÃ³`), which the parser did not match.
  Affected text is repaired on load.

## [1.0.1] - 2026-09-08

### Changed

- Publish the distribution under the independent `pysdim` package name.
- Improve package metadata, documentation discoverability, and release automation.
- Make the existing test modules discoverable by pytest.

## [1.0.0] - 2026-09-04

### Added

- Python client and command-line interface for ACA SDIM data.
- Name-based queries for rivers, basins, comarques, municipalities, aquifers,
  reservoirs, stations, and variables.
- Parsers for quality and quantity Excel exports.
- Generated metadata catalogs and station-variable mappings.
- Examples, tests, citation metadata, and legal attribution guidance.
