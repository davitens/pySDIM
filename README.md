<p align="center">
  <img src="docs/images/header.svg" alt="pySDIM" width="100%">
</p>

# ACA SDIM Python client

[![GitHub Release](https://img.shields.io/github/v/release/davitens/pySDIM)](https://github.com/davitens/pySDIM/releases)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-David%20Abert--Fernandez-0A66C2?logo=linkedin)](https://www.linkedin.com/in/david-abert-4171851aa/)
[![DOI](https://zenodo.org/badge/1353419139.svg)](https://doi.org/10.5281/zenodo.22302220)

A lightweight Python client for downloading historical water-quality and
water-quantity data from SDIM, the data consultation service operated by the
**Agència Catalana de l'Aigua (ACA)** (`aplicacions.aca.gencat.cat/sdim21`).

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
- Parses the exported XLSX into a pandas DataFrame with date, station, value,
  quality flags, and metadata columns.
- Resolves human-readable names (e.g. `"Baix Empordà"`, `"nitrate"`) to
  internal SDIM codes via a local metadata catalog, so you never need to
  figure out network IDs, subnetwork codes, or variable taxonomy yourself.

## Install

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
`"groundwater"`, `"levels"`, `"flow"`, `"volumes"`), and valid river/comarca
names are in `rivers.csv` / `comarcas.csv`.

The client resolves everything from the metadata catalog: the target
(`after_2007:0001:0022`), the river code (`riuAmbit=200`), the parameter
`g/f/v` codes, and the matching stations/series automatically.

- `target="after_2007:0005:0011"` — pick an exact target (see below).
- `stations=["F007528"]` — restrict to specific stations (series auto-selected
  from the target).
- If too many stations match, an error asks you to add a spatial filter or
  explicit stations (`max_stations=200` by default).
- Parameter aliases work: `no3`, `ec`, `temp`, …

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
```

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

## Tests

```bash
python3 tests/test_parser.py     # offline XLSX parsing
python3 tests/test_catalog.py    # offline metadata lookup
python3 tests/test_targets.py    # offline targets + station-variable tables
python3 tests/test_resolver.py   # offline name -> code resolution
```