# ACA SDIM Python Client Project

## Project Goal

Build a reusable Python library for accessing and downloading historical water-quality and water-quantity data from the **Agència Catalana de l'Aigua (ACA)** SDIM web application for Catalunya.

The SDIM website currently requires a manual workflow:

1. Select dataset period: before 2007 or after 2007.
2. Select the main feature/data type.
3. Select a more specific feature type.
4. Select monitoring sites using the map/interface.
5. Choose a date range in a calendar/subwindow.
6. Download the result as Excel/CSV/XML.

The goal of this project is to reproduce that workflow programmatically and eventually expose a simple Python API such as:

```python
from sdim import SDIM

aca = SDIM()

df = aca.get_data(
    period="after_2007",
    water_type="river",
    rivers=["Ter", "Llobregat"],
    parameters=["nitrate", "phosphate", "conductivity"],
    start="2015-01-01",
    end="2025-12-31",
)
```

The library should eventually support filtering by multiple parameters, rivers, basins, regions, zones, stations, and other spatial or monitoring-network criteria.

---

# Usage, Fair-Use and Legal Notes

## Do not overload the service

Automating access does not mean you have permission to send thousands of requests per second.
It is good practice to use rate limiting, moderate retries, and avoid large numbers of concurrent requests.

## Do not bypass access controls

SDIM is publicly accessible and the library appears to simply establish the web session required to use the service; it does not bypass private credentials or a paywall.

## License scope

The MIT license only covers the pySDIM code. It does not make ACA data MIT-licensed.
When publishing the data or derived results, you must comply with the Generalitat's applicable data reuse conditions.

## Attribution and reuse when publishing data

Comply with attribution and reuse requirements. This includes properly citing the source, not misrepresenting or distorting the information, and indicating the relevant update or access date.

---

# What Has Been Done

## 1. Reverse-engineered the final SDIM download request

Using Firefox Developer Tools → Network, the browser request used to generate and download an SDIM report was identified.

The report-generation request is:

```text
POST
https://aplicacions.aca.gencat.cat/sdim21/consultaInforme.do?format=excel
```

The generated report is then downloaded with:

```text
GET
https://aplicacions.aca.gencat.cat/sdim21/exportar.do?format=XLS
```

This indicates that SDIM uses a two-step process:

```text
Generate report in server-side session
        ↓
Download generated report
```

The server stores part of the request/report state in the HTTP session.

---

## 2. Identified important SDIM form parameters

A working browser request contained parameters such as:

```text
modo=rest
periodeXarxaControl=after_2007
modoConsultaDetall=completa

xarxaControl=0005
subXarxaControl=0010
subXarxaControl=0011

g=5
f=050004
v=0002

ambit=riu
cercadorRiu=RIU TER
riuAmbit=200

consultaDetallRealitzada=completa
```

Dates:

```text
dataIniciInforme=01/09/2007
dataFinalInforme=01/01/2008
```

Station identifiers:

```text
puntControl=F002792
puntControl=F003126
puntControl=F003202
puntControl=F003207
puntControl=F003735
puntControl=F003748
```

Variable identifiers:

```text
variable=1657965
variable=3072539
variable=3108130
variable=1657930
variable=3055361
variable=1657791
variable=3078594
variable=1657795
variable=3985509
variable=3073024
variable=1658226
variable=3075675
```

The request uses repeated form fields, so Python must preserve duplicate keys.

Therefore this is correct:

```python
payload = [
    ("puntControl", "F002792"),
    ("variable", "1657965"),
    ("variable", "3072539"),

    ("puntControl", "F003126"),
    ("variable", "3108130"),
    ("variable", "1657930"),
]
```

A normal Python dictionary should not be used for repeated fields.

---

# Session / Cookie Discovery

## 3. The first Python request failed

A fresh `requests.Session()` produced:

```text
500 Server Error
```

from:

```text
/consultaInforme.do?format=excel
```

The SDIM page reported that the database was inaccessible.

The likely cause was not the database itself, but missing browser/session state.

The browser request included cookies such as:

```text
JSESSIONID
QueueITAccepted-SDFrts345E-V3_aetrpro
BIGipServerAPLICACIONS.ACA.CAT_444_pool
```

while the initial Python script used an empty session.

---

## 4. Reusing browser session cookies solved the problem

The Python script was updated to use the browser's current SDIM session cookies.

Example:

```python
import requests

s = requests.Session()

s.cookies.set(
    "JSESSIONID",
    "...",
    domain="aplicacions.aca.gencat.cat",
)

s.cookies.set(
    "QueueITAccepted-SDFrts345E-V3_aetrpro",
    "...",
    domain="aplicacions.aca.gencat.cat",
)

s.cookies.set(
    "BIGipServerAPLICACIONS.ACA.CAT_444_pool",
    "...",
    domain="aplicacions.aca.gencat.cat",
)
```

Tracking/analytics cookies such as `_ga`, `_gid`, `_pk_*`, etc. were not necessary for the logic of the client.

Cookies should not be committed to Git or stored in source code permanently.

---

# Working Prototype

## 5. Current working report-generation pattern

A persistent session can now send the report-generation request:

```python
r = s.post(
    "https://aplicacions.aca.gencat.cat/sdim21/consultaInforme.do",
    params={"format": "excel"},
    data=payload,
    headers=post_headers,
)
```

Then download the generated XLS:

```python
download = s.get(
    "https://aplicacions.aca.gencat.cat/sdim21/exportar.do",
    params={"format": "XLS"},
    headers=download_headers,
)
```

And save it:

```python
with open("aca_sdim.xls", "wb") as f:
    f.write(download.content)
```

This has been tested successfully.

---

# Important Finding About SDIM Architecture

The application appears to rely on **server-side session state**.

The approximate workflow is:

```text
Browser opens SDIM
    ↓
JSESSIONID/session created
    ↓
User selects period/network/type/site/etc.
    ↓
Those choices are partly stored server-side
    ↓
POST consultaInforme.do
    ↓
Report is generated
    ↓
GET exportar.do
    ↓
XLS returned
```

A long-term goal is to reproduce all earlier navigation/setup requests so that users do not need to manually copy browser cookies.

---

# Proposed Python Library Architecture

A possible package structure:

```text
sdim/
│
├── __init__.py
├── client.py
├── session.py
├── discovery.py
├── query.py
├── download.py
├── parser.py
├── models.py
├── cache.py
├── exceptions.py
│
└── metadata/
    ├── variables.json
    ├── stations.json
    ├── networks.json
    └── regions.json
```

---

# Main Components

## `session.py`

Responsible for HTTP/session handling.

Possible interface:

```python
class SDIMSession:
    def __init__(self):
        self.session = requests.Session()

    def initialize(self):
        ...

    def post(self, endpoint, **kwargs):
        ...

    def get(self, endpoint, **kwargs):
        ...
```

Temporary cookie injection may be supported initially.

Long-term goal:

```python
aca = SDIM()
```

without manually copying browser cookies.

---

## `discovery.py`

This should discover valid SDIM metadata and internal IDs.

Desired methods:

```python
aca.periods()
aca.water_types()
aca.networks()
aca.subnetworks()
aca.rivers()
aca.basins()
aca.regions()
aca.stations()
aca.variables()
```

Examples:

```python
aca.stations(river="Ter")
```

```python
aca.variables(station="F002792")
```

```python
aca.search_variables("nitrate")
```

The discovery layer is the most important next step because users should not need to know internal codes such as:

```text
200
F002792
1657965
```

---

# Metadata We Need to Discover

We need mappings for at least:

| Entity | Example known |
|---|---|
| Dataset period | `after_2007` |
| Network | `0005` |
| Subnetwork | `0010`, `0011` |
| Main feature type | not yet mapped |
| Specific feature type | not yet mapped |
| Domain | `riu` |
| River | `200` appears related to Ter |
| Monitoring site | `F002792` |
| Variable | `1657965` |
| Basin | not yet mapped |
| Sub-basin | not yet mapped |
| Region/zone | not yet mapped |
| Municipality | not yet mapped |
| Comarca | not yet mapped |

We also need to determine relationships between entities, e.g.:

```text
network
   └── subnetwork
        └── water type
             └── river / basin / region
                  └── stations
                       └── variables available at each station
```

---

# Spatial Filtering

The future API should support filtering by multiple spatial concepts.

Examples:

```python
aca.stations(river="Ter")
```

```python
aca.stations(comarca="Osona")
```

```python
aca.stations(municipality="Vic")
```

```python
aca.stations(basin="Ter")
```

Potentially:

```python
aca.stations(
    bbox=(1.8, 41.7, 2.4, 42.3)
)
```

and eventually:

```python
aca.stations(
    polygon=my_geopandas_geometry
)
```

If station coordinates can be extracted, administrative/spatial filters can also be performed locally using GeoPandas rather than relying only on SDIM's web filters.

---

# Parameter Filtering

Users should be able to write:

```python
aca.get_data(
    parameters=["nitrate", "phosphate", "ammonium", "conductivity"]
)
```

instead of internal numeric IDs.

Possible search:

```python
aca.search_variables("conduct")
```

Potential aliases:

```python
ALIASES = {
    "no3": "nitrate",
    "nh4": "ammonium",
    "po4": "phosphate",
    "ec": "conductivity",
}
```

The original Catalan SDIM parameter name should still be preserved.

---

# Query Object

Rather than building raw POST payloads throughout the code, the project should use a query object.

Example:

```python
from sdim import Query

q = Query(
    period="after_2007",
    water_type="river",
    stations=["F002792", "F003126"],
    parameters=["1657965", "3072539"],
    start="2007-09-01",
    end="2008-01-01",
)
```

Then:

```python
payload = q.to_sdim_payload()
```

This isolates SDIM-specific request formatting.

---

# Station ↔ Variable Relationship

The captured form contains ordered repeated fields such as:

```text
puntControl=F002792
variable=1657965
variable=3072539

puntControl=F003126
variable=3108130
variable=1657930
```

This may mean that variable selections are associated with each station according to request order.

The library may therefore need to represent selections as:

```python
{
    "F002792": [
        "1657965",
        "3072539",
    ],
    "F003126": [
        "3108130",
        "1657930",
    ],
}
```

rather than as two independent global lists.

This behavior needs to be tested.

---

# Download Chunking

Large requests should not be sent as one huge SDIM report.

For example, avoid:

```text
all stations × all variables × 2007–2025
```

The client should split large requests automatically.

Possible strategies:

```python
aca.get_data(
    ...,
    chunk="year"
)
```

or configurable limits:

```python
aca = SDIM(
    max_stations_per_request=20,
    max_years_per_request=5,
)
```

The exact practical limits should be determined experimentally.

Requests should be rate-limited to avoid unnecessary load on ACA servers.

---

# Data Parsing

The final public API should normally return a `pandas.DataFrame`, not only an XLS file.

Desired structure:

```text
date
station_id
station_name
variable_id
variable
value
unit
qualifier
latitude
longitude
river
network
```

Example:

```python
df = aca.get_data(...)
```

while raw downloads should still be available:

```python
aca.download(..., output="raw.xls")
```

---

# Detection Limits and Quality Flags

Environmental measurements may include values such as:

```text
<0.01
>100
ND
LOQ
LQ
NA
```

These should not be silently converted.

A safer normalized format:

```text
raw_value   value   qualifier   detection_limit
<0.01       0.01    <           0.01
```

This is important for scientific reproducibility.

---

# Local Metadata Cache

The package could maintain a local SQLite database:

```text
~/.cache/sdim/sdim.sqlite
```

Possible tables:

```text
stations
variables
networks
subnetworks
rivers
station_variables
```

Example station table:

```text
station_id
name
latitude
longitude
river_id
basin
municipality
active_from
active_to
```

Example variable table:

```text
variable_id
name_ca
name_en
unit
category
```

Example station-variable table:

```text
station_id
variable_id
first_date
last_date
```

This would allow fast local searches such as:

```python
aca.stations(
    parameters=["nitrate", "phosphate"],
    min_year=2007,
)
```

---

# Raw Download Cache

Downloaded SDIM files should be cached locally based on a query hash.

Example:

```text
~/.cache/sdim/downloads/
    7ce83d219f.xls
```

The hash could depend on:

```text
stations
variables
start
end
network
period
```

This prevents repeatedly downloading identical data.

---

# Provenance

Every dataset should retain metadata describing its origin.

Possible dataframe metadata:

```python
df.attrs["sdim_query"]
df.attrs["downloaded_at"]
df.attrs["source_url"]
df.attrs["period"]
```

Or a sidecar file:

```text
data.csv
data.metadata.json
```

Example:

```json
{
    "source": "ACA SDIM",
    "downloaded": "2026-09-01",
    "period": "after_2007",
    "stations": [],
    "variables": [],
    "start": "2007-01-01",
    "end": "2025-12-31"
}
```

---

# Error Handling

Possible custom exceptions:

```python
SDIMError
SDIMSessionExpired
SDIMQueryError
SDIMNoData
SDIMServerError
SDIMExportError
```

Instead of returning only:

```text
HTTP 500
```

the library should ideally produce errors such as:

```text
SDIMSessionExpired:
The SDIM session appears to have expired.
```

---

# Command-Line Interface

A CLI could also be added.

Examples:

```bash
sdim stations --river Ter
```

```bash
sdim variables --station F002792
```

```bash
sdim download     --river Ter     --parameter nitrate     --parameter phosphate     --start 2007-01-01     --end 2025-12-31     --output ter.csv
```

---

# Desired Final User API

A simple end-user workflow could eventually be:

```python
import sdim

aca = sdim.Client()

stations = aca.stations(
    river=["Ter", "Fluvià"],
    comarca=["Osona", "Ripollès"],
)

data = aca.data(
    stations=stations,
    parameters=[
        "nitrate",
        "phosphate",
        "ammonium",
        "conductivity",
    ],
    start="2007-01-01",
    end="2025-12-31",
)
```

Expected output:

```text
date        station   river   parameter       value   unit
2007-01-12  F002792   Ter     nitrate         4.2     mg/L
2007-01-12  F002792   Ter     conductivity    512     µS/cm
...
```

---

# Next Reverse-Engineering Tasks

Before writing much more downloader code, capture the Network requests generated by each of these interactions:

1. Select before/after 2007.
2. Select each main feature type.
3. Select each specific feature type.
4. Change river.
5. Change basin.
6. Change region/zone.
7. Load the station map.
8. Select a station.
9. Load available variables.
10. Change/select variables.
11. Submit the final report.

The most important requests are the ones that populate dropdowns, station markers, or variable lists.

We are looking for endpoints that may resemble:

```text
/getPuntsControl.do?riu=200
/getVariables.do?puntControl=F002792
```

The exact endpoint names are not yet known.

If these discovery endpoints can be identified, the library can dynamically resolve:

```text
human-readable selection
        ↓
SDIM internal ID
        ↓
query payload
        ↓
download
```

instead of relying on hard-coded IDs.

---

# Milestone 0 — Self-Contained Session + Working Downloader (DONE)

## Session bootstrap is fully automatic

A plain `GET https://aplicacions.aca.gencat.cat/sdim21/` sets both the
`JSESSIONID` and `BIGipServerAPLICACIONS.ACA.CAT_444_pool` cookies. No QueueIT
challenge is required on the entry page. The library therefore never needs
manually-copied browser cookies.

## Complete form chain (reverse-engineered)

```
GET  /sdim21/                         # landing page (creates JSESSIONID)
POST /sdim21/seleccioXarxes.do        # accio=seleccioXarxa, page=inici
POST /sdim21/filtre.do                # accio=puntsDeControl, page=periodeControl,
                                      #   periodeXarxaControl=after_2007|before_2007
      ↓  (the filter page holds the whole #filtre form → consultaInforme.do)
POST /sdim21/consultaInforme.do?format=excel   # the serialized #filtre form
GET  /sdim21/exportar.do?format=XLS            # download the generated report
```

The two entry POSTs (`seleccioXarxes.do` + `filtre.do`) are required: posting
straight to `consultaInforme.do` with a fresh session yields HTTP 500.

## Status codes of consultaInforme.do (from the page JS)

| Code | Meaning |
|---|---|
| 200 | report generated → fetch `exportar.do` |
| 201 | no records (→ `SDIMNoData`) |
| 202 | too many records, report truncated (→ warn/error) |

## Required payload fields

The minimal working payload (bisected empirically) is:

```text
modo=rest
periodeXarxaControl=<period>
modoConsultaDetall=completa
xarxaControl=...            (repeated)
subXarxaControl=...         (repeated)
g / f / v = checked branches (repeated)
ambit=riu
riuAmbit=...                (and/or other spatial fields per ambit)
consultaDetallRealitzada=completa
puntControl=... / variable=...   (repeated, station→variables grouped in order)
dataIniciInforme=DD/MM/YYYY
dataFinalInforme=DD/MM/YYYY
informeEjecutar=0           (MANDATORY — omitting it causes HTTP 500)
```

Fields such as `capas`, `cercadorVariables`, `whereActual`, `cadenaCercaToponimia`,
`cercadorRiu`, `informesTotal` are serialized by the browser but are NOT required.

## Discovery endpoints found (used by the AJAX UI)

- `POST /sdim21/serveis/serveiTipusVariables.do` — variable-type tree (`g`/`f`/`v`)
- `POST /sdim21/serveis/serveiDetallSeleccio.do` — station/variable tree
- Spatial providers: `serveiConques.do`, `serveiMasses.do`, `serveiAquifer.do`,
  `serveiMunicipis.do`, `serveiComarques.do`, `serveiRius.do`, `serveiEmbassaments.do`
- `POST /sdim21/serveis/serveiInformacioPuntControl.do` — per-point info popup

The AJAX calls are NOT needed for report generation (verified), only for
discovering IDs — which Milestone 1 will automate.

## Verified end-to-end (no browser, no manual cookies)

Network CONTROL RIUS (`0001`) / Elements fisicoquímics (`0022`), river Ter
(`riuAmbit=200`), conductivity (`g=5/f=050004/v=0002`), 2007–2010:

- 11 stations, one conductivity variable each.
- `consultaInforme.do → 200`, `exportar.do → 200`, valid XLSX (18 rows for the
  2-station variant; the exported file is an XLSX Open-XML container).
- Same payload replicated through plain `requests` produced identical bytes sizes.

## Library layout (implemented)

```text
sdim/
├── __init__.py      # public API (SDIM, Query, exceptions)
├── session.py       # automatic cookie bootstrap + error detection
├── client.py        # SDIM.download() / SDIM.get_data()
├── query.py         # Query → ordered SDIM payload
├── parser.py        # XLSX export → tidy DataFrames (value_raw/qualifier kept)
├── cli.py           # `sdim download ...`
└── exceptions.py    # SDIMError hierarchy
```

```python
from sdim import SDIM, Query

q = Query(period="after_2007", networks=["0001"], subnetworks=["0022"],
          variable_kinds=[("g","5"),("f","050004"),("v","0002")],
          ambit="riu", spatial={"riuAmbit":["200"]},
          stations={"F007528":["3057279"], "F007529":["3049297"]},
          start="2007-09-01", end="2010-01-01")

aca = SDIM()
parsed = aca.get_data(q)   # {"quality": DataFrame, "quantity": DataFrame}
```

---

# Milestone 1 — Metadata Discovery + CSV Catalog (DONE)

## Discovery layer (`sdim/discovery.py` + `scripts/build_metadata.py`)

The discovery AJAX endpoints are now automated. `scripts/build_metadata.py`
walks both periods and writes `metadata/*.csv` (raw responses cached under
`metadata/raw/` so re-runs are offline):

| CSV | counts (unique, union of periods) |
|---|---|
| `networks.csv` | 12 (2 periods × 6) |
| `subnetworks.csv` | 34 |
| `variables.csv` | 1831 parameter-branch rows (`g`/`f`/`v`) |
| `rivers.csv` | 191 |
| `basins.csv` | 33 |
| `comarcas.csv` | 44 |
| `municipis.csv` | 840 |
| `aquifers.csv` | 176 |
| `masses.csv` | 581 |
| `reservoirs.csv` | 31 |
| `stations.csv` | 6623 |

All tables carry the zero-padded internal codes as strings.

## Catalog lookups (`sdim/catalog.py`, `sdim search` CLI)

```python
cat.rivers("ter", period="after_2007")         # → code 200 = RIU TER
cat.search_variables("nitrat")                 # → g=5/f=050003/v=0016
cat.variables_for("0001", "0022")
```

```bash
sdim search ter --flavor rivers
sdim search conduct --flavor variables
```

## Relationship map (confirmed)

```
period (after_2007 | before_2007)
  └── network (xarxaControl)
       └── subnetwork (subXarxaControl)
            └── parameter types (g → f → v)
                 └── stations (puntControl, code + coords)
                      └── variable series (variable ids, per station)
```

Stations and their per-station variable IDs remain obtainable via
`serveiDetallSeleccio.do` (completa mode) — the next milestone can materialize
a `station_variables` table.

---

# Milestone 2 — Targets Inventory + Station↔Variable Tables (DONE)

SDIM's workflow asks for a **target** first (a `period × network × subnetwork`
combination), because each target has its own stations and parameter series.
All 34 targets are now mapped:

- `metadata/targets.csv` — inventory: id, names, category (groundwater levels,
  quantity, physical-chemical, biological, priority substances, metals,
  hydromorphological), parameter families, branch count, station count,
  series count, plus per-network spatial flags (`has_rivers`, `has_basins`, ...).
- `metadata/station_variables.csv` — 330 203 station↔variable-series rows
  (also split per target in `metadata/station_variables/`).

Representative targets:

| target | meaning | stations | series |
|---|---|---|---|
| `after_2007:0005:0010` | groundwater quality | 1532 | 79587 |
| `after_2007:0005:0011` | groundwater levels | 621 | 713 |
| `after_2007:0001:0301` | river flows (Cabals) | 99 | 103 |
| `after_2007:0001:0303` | river levels (Nivells) | 91 | 92 |
| `after_2007:0002:0302` | reservoir volumes (Volums) | 13 | 36 |
| `before_2007:0000:0019` | pre-2007 groundwater quality | 2079 | 56032 |
| `before_2007:0005:0011` | pre-2007 groundwater levels | 363 | 396 |

Catalog API: `cat.targets()`, `cat.target(id)`, `cat.target_station_variables(id)`,
`cat.station_variables(term)`.

## Verified live end-to-end (`scripts/verify_targets.py`)

Each representative target was downloaded and parsed successfully with a fresh
`requests` session:

- Quality targets (groundwater quality, piezometry, river phys-chem, pre-2007)
  → the **quality** block (`date, station, mass, variable, value, unit`).
- Quantity targets (Cabals, Nivells, Volums) → the **quantity** block
  (`date, station, basin, variable, UTM, mean, unit`), validating
  `parse_quantity` against real exports.

The full chain — target → station → variable series → report → tidy DataFrame —
now works for every target, with no browser and no hard-coded cookies.

---

# Milestone 3 — Name-Based Public API (DONE)

The documented end-user API is now implemented (`sdim/resolver.py` +
`SDIM.get_data/download` semantic overload). Everything resolves from the
metadata catalog — no internal codes required:

```python
aca = SDIM()
parsed = aca.get_data(
    water_type="river",           # river | groundwater | levels | flow | volumes | ...
    rivers=["Ter"],               # ... or basins / comarcas / municipis / ...
    parameters=["nitrate", "phosphate"],
    start="2007-09-01", end="2009-12-31",
)
```

Resolution steps performed automatically:

1. **Target** — pick the (period, network, subnetwork) from `targets.csv`,
   honouring `water_type`, explicit `networks/subnetworks`, or an explicit
   `target`/`period`; when `parameters` are given, targets must contain all of
   them (known by their `g/f/v` codes).
2. **Parameters** — names (with aliases `no3`, `ec`, `temp`, ...) are mapped to
   the taxonomy `g/f/v` codes for the chosen target.
3. **Spatial** — `rivers=["Ter"]` → `riuAmbit=200` etc., derived from the
   attribute tables; the SDIM `ambit` is set from the field used.
4. **Stations** — station↔series are pulled from `station_variables.csv`
   (offline) or, when a spatial filter is present, from the live
   `serveiDetallSeleccio.do` station layer for the target, filtered to the
   requested parameters.
5. A `max_stations` guard (default 200) prevents accidental massive downloads.

Verified live: Ter nitrate+phosphate (273 rows), groundwater nitrate by station
name, reservoir volumes, and river flows (`Cabals`) all download and parse.

```bash
sdim download --water-type river --river Ter \
    --parameter nitrate --parameter phosphate \
    --start 2007-09-01 --end 2009-12-31 -o ter.xls
```

---

# Current Project Status

## Working

- Final SDIM report-generation endpoint identified.
- XLS export endpoint identified.
- POST payload structure captured.
- Multiple repeated station/variable form fields understood.
- **Automatic session creation (no manually-copied cookies).**
- Full entry form chain (seleccioXarxes → filtre → consultaInforme → exportar).
- Minimal required payload established (`informeEjecutar=0` is mandatory).
- Python `requests.Session()` implementation tested.
- XLS download works from Python.
- Discovery AJAX endpoints identified (tipus, detall, spatial providers).
- XLSX export parsing into tidy DataFrames (quality + quantity blocks) — both
  verified against real exports.
- CLI (`sdim download`, `sdim search`) and examples.
- Metadata discovery automated → `metadata/*.csv`.
- Catalog lookups by name (`sdim.Catalog`, `sdim search`).
- **Targets inventory (`targets.csv`) — 34 targets.**
- **Station↔variable tables (`station_variables.csv`, 330k series).**
- **Live end-to-end downloads verified for all representative targets.**
- **Name-based public API** (`get_data(water_type=..., rivers=[...],
  parameters=[...])`) with automatic target/parameter/station resolution.

## Not Yet Solved

- Chunking/rate limiting for large downloads + automatic splitting.
- Local SQLite metadata cache + raw download cache.
- CLI polish (progress reporting), packaging/distribution (PyPI).
- Mapping of all network/subnetwork IDs.
- Mapping of all rivers/basins/regions/zones.
- Mapping of station IDs to names and coordinates.
- Mapping of variable IDs to parameter names and units.
- Understanding station-specific variable availability.
- Robust parsing of SDIM XLS output.
- Chunking/rate limiting.
- Local cache.
- CLI.
- Packaging/distribution.

---

# Immediate Next Step

The next milestone should be:

> **Reverse-engineer SDIM discovery requests.**

Specifically, inspect the browser Network tab while changing:

- river,
- network,
- region/zone,
- station,
- variable.

Save the relevant requests as cURL.

Once those are understood, the library can move from a hard-coded downloader to a true queryable SDIM Python client.

