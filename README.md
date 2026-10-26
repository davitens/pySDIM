<p align="center">
  <img src="docs/images/header.svg" alt="pySDIM" width="100%">
</p>

# Download Catalonia River Flow and Water Data with Python

[![GitHub Release](https://img.shields.io/github/v/release/davitens/pySDIM)](https://github.com/davitens/pySDIM/releases)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-David%20Abert--Fernandez-0A66C2?logo=linkedin)](https://www.linkedin.com/in/david-abert-4171851aa/)
[![DOI](https://zenodo.org/badge/1353419139.svg)](https://doi.org/10.5281/zenodo.22661965)

**pySDIM** is a lightweight Python client for downloading historical river-flow,
water-level, groundwater, reservoir, and water-quality data from Catalonia
(Catalunya). It accesses SDIM, the data consultation service operated by the
**Agència Catalana de l'Aigua (ACA)** (`aplicacions.aca.gencat.cat/sdim21`).

If you are looking for **Catalonia river flow data**, **Catalan hydrological
data**, or **ACA water data**, this project provides a reproducible Python and
command-line workflow for finding and downloading it.

> **Disclaimer:** This project is not affiliated with, endorsed by, or
> maintained by the ACA or the Generalitat de Catalunya. Use of the SDIM
> service is subject to the ACA's terms of use.

This client handles the session setup, form submission, and export parsing
that the website normally does behind the scenes, returning clean pandas
DataFrames ready for analysis.

**What it does:**
- Authenticates automatically (no browser cookies or manual login).
- Navigates the multi-step form flow (network → spatial filter → parameters →
  date range → export) using the same HTTP endpoints the web UI calls.
- Parses the exported XLSX into typed pandas DataFrames (datetime dates, float
  values and coordinates) with catalog station names, quality flags, and the
  provenance you need to cite the data.
- Splits requests that SDIM refuses as too large and joins the parts.
- Checks the parsed output, so a change in SDIM's export layout raises an error
  instead of returning empty columns.
- Resolves human-readable names (e.g. `"Baix Empordà"`, `"nitrate"`) to
  internal SDIM codes via a local metadata catalog, so you never need to
  figure out network IDs, subnetwork codes, or variable taxonomy yourself.

## Install

```bash
python -m pip install pysdim
```

Or install directly from the repository:

```bash
git clone https://github.com/davitens/pySDIM.git
cd pySDIM
python -m pip install .
```

Dependencies: `requests`, `pandas`, `openpyxl`, `lxml`. Python ≥ 3.10.

> The MIT-licensed client only talks to the public ACA website; it does not
> bundle or redistribute SDIM's data. Check the SDIM terms of use before
> using extracted data in a published work.

## Fair use, legal and attribution notes

- **Do not overload the service.** Automating access does not mean you have
  permission to send thousands of requests per second. Use rate limiting,
  moderate retries, and avoid large numbers of concurrent requests.
- **Do not bypass access controls.** SDIM is publicly accessible and the
  library simply establishes the web session required to use the service; it
  does not bypass private credentials or a paywall.
- **License scope.** The MIT license only covers the pySDIM code. It does not
  make ACA data MIT-licensed. When publishing the data or derived results,
  comply with the Generalitat's applicable data reuse conditions.
- **Attribution.** When publishing the data, cite the source, do not
  misrepresent or distort the information, and indicate the relevant update or
  access date.

## Query and download

### Minimal example

The shortest working program — groundwater levels in comarca Baix Empordà, one
year of data, nothing to configure:

```python
from sdim import SDIM

aca = SDIM()
df = aca.get_data(
    water_type="levels",
    comarcas=["Baix Empordà"],
    start="2008-01-01",
    end="2009-01-01",
)["quality"]

df.to_csv("data_example.csv")
print(df[["date", "station_code", "value", "unit"]])
```

### Tutorial

[`examples/tutorial.ipynb`](examples/tutorial.ipynb) is a Jupyter notebook,
run against live SDIM, that walks through every kind of data: river
phys-chem, biological indices, flows and river levels, groundwater quality and
piezometric levels, reservoir volumes, protected zones, pre-2007 data, explicit
queries, raw exports, and provenance and saving.

### By name (recommended) — no internal codes

```python
from sdim import SDIM

aca = SDIM()

parsed = aca.get_data(
    water_type="river",              # see targets.csv → "category" column
    rivers=["Ter"],                  # see rivers.csv → "name" column
    parameters=["nitrate", "phosphate"],  # see variables.csv → "v_name" column
    start="2007-09-01",              # ISO date, must fall within the target's period
    end="2009-12-31",
    comarcas=["Baix Empordà"],       # see comarcas.csv; or use basins, municipis, aquifers, ...
)
df = parsed["quality"]
```

Valid values for each argument come from the metadata CSVs shipped with the
package (see [Metadata CSVs](#metadata-csvs) below). For example, valid
`water_type` values are the target categories in `targets.csv` (e.g. `"river"`,
`"groundwater"`, `"levels"`, `"flow"`, `"volumes"`, `"river_biology"`), and
valid river/comarca names are in `rivers.csv` / `comarcas.csv`.

The client resolves everything from the metadata catalog: the target
(`after_2007:0001:0022`), the river code (`riuAmbit=200`), the parameter
`g/f/v` codes, and the matching stations/series automatically.

- `target="after_2007:0005:0011"` — pick an exact target (see below).
- `stations=["F007528"]` — restrict to specific stations (series auto-selected
  from the target).
- If too many stations match, an error asks you to add a spatial filter,
  explicit stations, or a higher `max_stations` (200 by default).
- Parameter aliases work: `no3`, `ec`, `temp`, …
- `groups=["Nutrients"]` — keep only the variables of a group or family
  (`g_name` / `f_name` in `variables.csv`), instead of listing parameters.
- `water_type` takes a named type (`sdim targets` lists them; Catalan names
  such as `"cabals"` or `"estany"` work too) or any `targets.csv` category,
  e.g. `"biological"`, `"metals"`, `"hydromorphological"`.
- Before 2007 there is no lake network (`lake` and `lake_biology` raise a
  clear error), and river and reservoir quality share one target: with
  `period="before_2007"`, `water_type="reservoir"` selects it, and the rows
  include river stations too. The pre-2007 catalog lists only one reservoir
  name, so narrow with `comarcas=[...]` or `basins=[...]`. Use `"volumes"`
  for reservoir volumes.
- Spatial names are looked up in the request's period: a name catalogued only
  after 2007 (most reservoirs, about 100 rivers) raises an error for
  `period="before_2007"`.

### Large requests

SDIM refuses reports above its record limit. `get_data()` then splits the
request, first by stations and then by date range, and joins the parts. Turn
this off with `split=False`, or cap the number of reports with
`max_requests` (64 by default); `result.provenance["requests"]` tells you how
many were needed. Splitting sends more requests to a public service, so keep
large jobs reasonable. `download()` returns a single raw file and cannot split.

### Temporary server errors

SDIM sometimes drops connections or refuses an export for a few minutes.
Each HTTP request is retried on connection errors and 5xx responses with
exponential backoff (`SDIM(retries=4, backoff=2.0)`: 2, 4, 8, 16 s). If a
report still fails, the client waits (`report_retry_wait=60` s, then 120 s),
starts a fresh SDIM session and regenerates the report, up to
`report_retries=2` times. A split request retries each part on its own.
Query errors and "no records" answers are never retried.

### What you get back

`get_data()` returns an `SDIMResult`. It is a dict, so `result["quality"]` and
`result["quantity"]` work as before, with `result.quality`,
`result.quantity` and `result.provenance` as shortcuts.

| column | sheet | notes |
|---|---|---|
| `date` | both | `datetime64` |
| `station_code` | both | the code in the export (`200046000`; for quantity the series prefix, `EA010`) |
| `station_id`, `station_name` | both | catalog station (`F007569`) and name, from `stations` / `station_variables` |
| `target_id`, `network`, `network_name`, `subnetwork`, `subnetwork_name` | both | the target the rows came from |
| `mass_code`, `mass_name` | quality | water body |
| `basin` | quantity | |
| `variable`, `unit` | both | |
| `utm_x`, `utm_y` | both | UTM coordinates as exported, as floats |
| `value_raw`, `value`, `qualifier` | both | `value_raw` keeps the text, so `<0.01` gives `value=0.01, qualifier="<"` |
| `depth_m`, `well_depth_m`, `piezometric_level_masl` | quality | sample depth, well depth and piezometric level when the export has them |

Columns SDIM adds in the future are kept under their export header. Pass
`station_context=False` to skip the catalog join.

**Checks.** If a sheet has rows but its date, station, variable or value column
is empty throughout, `get_data()` raises `SDIMParseError` (the export layout
changed). It warns with `SDIMWarning` when a report has no rows, when dates
fail to parse, or when stations are missing from the metadata catalog.
`validate_output=False` turns the checks off.

**Provenance.** `result.provenance` (also in each DataFrame's
`attrs["provenance"]`) records the source, URL, access time (UTC), target,
period, date range, number of stations and requests, the pySDIM version and
a citation. `result.save("out/ter")` writes `out/ter_quality.csv`,
`out/ter_quantity.csv` (non-empty sheets only) and `out/ter_provenance.json`.

### Biological indices

Without `parameters`, `water_type="river"` downloads the physico-chemical
target. Biological indices (IPS, IBMWP, IMF, IBICAT-2010, …) live in separate
"Elements biològics" targets, selected with a `*_biology` water type:

```python
df = aca.get_data(
    water_type="river_biology",      # or lake_ / reservoir_ / coastal_biology
    comarcas=["Baix Empordà"],
    start="2008-01-01",
    end="2026-01-01",
)["quality"]
df["variable"].unique()              # índex IPS, índex IBMWP, índex IMF, ...
```

| water_type | target (after 2007) | indices |
|---|---|---|
| `river_biology` | `after_2007:0001:0001` | IPS (diatoms), IBMWP (invertebrates), IMF (macrophytes), IBICAT-2010 (fish), chlorophyll a |
| `lake_biology` | `after_2007:0003:0005` | InClo, InGA, ACCO-2010, EQATg, InMacro, QAELS-e-2010, RIC, InMac, … |
| `reservoir_biology` | `after_2007:0002:0003` | chlorophyll a, % cyanobacteria |
| `coastal_biology` | `after_2007:0004:0007` | POMI, CYMOX, CARLIT, MEDOCC (EQR) |

Narrow to one biological element with `groups` (e.g. `groups=["Invertebrats"]`
for IBMWP only) or name indices directly (`parameters=["IBMWP", "IPS"]`).
With `period="before_2007"`, `river_biology` selects the index series (BMWPC,
chlorophyll) of the pre-2007 river target, which also holds phys-chem data.

> **Known issue:** reservoir and coastal quality reports (biological and
> physico-chemical) currently come back with headers but no rows; only river
> and lake biology are verified live.

### By code (explicit)

```python
from sdim import Query

q = Query(
    period="after_2007",
    networks=["0001"],              # CONTROL RIUS
    subnetworks=["0022"],           # Elements fisicoquímics
    variable_kinds=[("g", "5"), ("f", "050004"), ("v", "0002")],  # Conductivitat
    ambit="riu",
    spatial={"riuAmbit": ["200"]},  # RIU TER
    stations={"F007528": ["3057279"], "F007529": ["3049297"]},
    start="2007-09-01",
    end="2010-01-01",
)
parsed = aca.get_data(q)
```

Use `SDIM.download(..., output="report.xlsx")` to keep the raw file instead.

### Command line

```bash
sdim download --water-type river --river Ter \
    --parameter nitrate --parameter phosphate \
    --start 2007-09-01 --end 2009-12-31 -o ter.xls

sdim download --water-type river_biology --comarca "Baix Empordà" \
    --group Invertebrats --start 2008-01-01 --end 2026-01-01 -o ibmwp.xls

# parse, split if needed, and save CSVs + provenance JSON
sdim get --water-type river_biology --comarca "Baix Empordà" \
    --start 2008-01-01 --end 2026-01-01 -o out/baix_emporda_bio

sdim targets --category biological      # targets and water types
sdim describe after_2007:0001:0001      # groups, families and variables of a target
```

`download` writes the raw SDIM file; `get` writes the parsed result.

## Frequently asked questions

### Where can I download river flow data from Catalonia?

The official source is the Agència Catalana de l'Aigua (ACA) SDIM service.
This repository provides a Python client for downloading its river flows
(`Cabals`), river levels (`Nivells`), groundwater, reservoir volumes, and
water-quality data. The service remains the authoritative source; pySDIM is a
client and does not redistribute ACA data.

### Can I download data for a specific Catalan river?

Yes. Use a river name from `metadata/rivers.csv`, such as `Ter`, `Llobregat`,
or `Fluvià`, and pass it to `SDIM.get_data()` or the `sdim download` command.

### What format does pySDIM return?

`get_data()` returns an `SDIMResult` of typed pandas DataFrames plus
provenance (see [What you get back](#what-you-get-back)); `result.save(...)`
or `sdim get` writes them as CSV with a provenance JSON. Raw ACA Excel exports
can be kept with `SDIM.download(..., output="report.xlsx")` or `sdim download`.

### Is this an official ACA project?

No. pySDIM is an independent open-source client. It is not affiliated with,
endorsed by, or maintained by the ACA or the Generalitat de Catalunya.

## Metadata CSVs (generated by `scripts/build_metadata.py`)

| file | contents | key fields |
|---|---|---|
| `networks.csv` | control networks (`xarxaControl`) | code (e.g. `0001` = CONTROL RIUS) |
| `subnetworks.csv` | subnetworks (`subXarxaControl`) per network | code, network |
| `variables.csv` | parameter taxonomy | `g`/`f`/`v` codes + names per network/subnetwork |
| `rivers.csv` | rivers (`riuAmbit`) | code (e.g. `200` = RIU TER) |
| `basins.csv` | basins (`concaAmbit`) | code, name |
| `comarcas.csv` | comarques (`comarcaAmbit`) | code, name |
| `municipis.csv` | municipis (`municipiAmbit`) | code, name |
| `aquifers.csv` | aquifers (`AquiferAmbit`) | code, name |
| `masses.csv` | water bodies (`massaAmbit`) | code, name |
| `reservoirs.csv` | reservoirs (`embassamentAmbit`) | code, name |
| `stations.csv` | monitoring stations (`puntControl`) | station, name, x, y, network, period |

All tables are keyed by `period` (`after_2007` / `before_2007`). Codes are
zero-padded strings and must be passed to `Query` exactly as stored.

## Targets (what you can actually download)

A **target** is the first thing SDIM asks you to choose: a
`(period, network, subnetwork)` combination that determines which stations and
parameter series exist. `targets.csv` inventories all 34 targets; per-target
station↔variable series live in `station_variables.csv` (330k rows) and split
files under `metadata/station_variables/`.

| target id | description | stations | series |
|---|---|---|---|
| `after_2007:0005:0010` | groundwater quality | 1532 | 79 587 |
| `after_2007:0005:0011` | groundwater levels (piezometry) | 621 | 713 |
| `after_2007:0001:0022` | river physico-chemical | 446 | 10 981 |
| `after_2007:0001:0301` | river flows (Cabals) | 99 | 103 |
| `after_2007:0001:0303` | river levels (Nivells) | 91 | 92 |
| `after_2007:0002:0302` | reservoir volumes (Volums) | 13 | 36 |
| `before_2007:0000:0019` | pre-2007 groundwater quality | 2079 | 56 032 |
| `before_2007:0005:0011` | pre-2007 groundwater levels | 363 | 396 |
| `after_2007:0001:0001` | river biological indices | 408 | 1 391 |
| `after_2007:0003:0005` | lake and wetland biological indices | 81 | 503 |

```python
cat = Catalog("metadata")
cat.targets(period="after_2007")            # full inventory
cat.target("after_2007:0005:0010")          # one row (category, counts, spatial flags)
cat.target_station_variables("after_2007:0005:0011")  # station → variable series
```

> **Quantity data** (Cabals, Nivells, Volums) downloads into the *quantity*
> block of the export (date, station, basin, variable, UTM, mean, unit), while
> quality targets (phys-chem, biology, levels, priority substances) download
> into the *quality* block. Both are parsed automatically by `get_data`.

Verified live end-to-end for all of the above plus pre-2007 targets
(`scripts/verify_targets.py`).

### Lookup by name

Use the catalog to explore what names and codes are available:

```python
from sdim import Catalog

cat = Catalog("metadata")
cat.rivers("ter", period="after_2007")            # → code 200 = RIU TER
cat.search_variables("nitrat")                    # → f=050003 (Nutrients), v=0016
cat.variables_for("0001", "0022")                 # full phys-chem tree for CONTROL RIUS
```

Or on the command line:

```bash
sdim search ter --flavor rivers --period after_2007
sdim search nitrat --flavor variables --period after_2007
```

Rebuild the tables after a change in the UI or to refresh:

```bash
python3 scripts/build_metadata.py --refresh
```

## References and citation

**Original SDIM data service:** Agència Catalana de l'Aigua (ACA), SDIM — Servei de Dades i Informació Meteorològica/Mediambiental. https://aplicacions.aca.gencat.cat/sdim21/

**Citing pySDIM:** If you use this software, please cite it as below (see also `CITATION.cff`):

> David Abert-Fernandez, Eduard Madaula, Gisela Gonzalvo-Henry, Anna Menció, Hèctor Monclús. *pySDIM — Python client for ACA SDIM water data*. DOI: 10.5281/zenodo.22661965 · https://github.com/davitens/pySDIM

When publishing data or derived results obtained with pySDIM, also cite the original dataset and comply with the Generalitat de Catalunya's data reuse conditions (see [Fair use, legal and attribution notes](#fair-use-legal-and-attribution-notes)).
