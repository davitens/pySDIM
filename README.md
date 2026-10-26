<p align="center">
  <img src="docs/images/header.svg" alt="pySDIM" width="100%">
</p>

# pySDIM: download Catalan water data with Python

[![GitHub Release](https://img.shields.io/github/v/release/davitens/pySDIM)](https://github.com/davitens/pySDIM/releases)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-David%20Abert--Fernandez-0A66C2?logo=linkedin)](https://www.linkedin.com/in/david-abert-4171851aa/)
[![DOI](https://zenodo.org/badge/1353419139.svg)](https://doi.org/10.5281/zenodo.22661965)

pySDIM downloads river flows, water levels, groundwater, reservoir and
water-quality data for Catalonia from
[SDIM](https://aplicacions.aca.gencat.cat/sdim21/), the data service of the
**Agència Catalana de l'Aigua (ACA)**. You ask by name ("river", "biological",
"Baix Empordà") and get pandas DataFrames back; the client handles the SDIM
session, its internal codes, large requests and the Excel export.

> Not affiliated with or endorsed by the ACA or the Generalitat de Catalunya.

## Install

```bash
python -m pip install pysdim
```

Python 3.10 or newer.

## Quick start

```python
from sdim import SDIM

aca = SDIM()
df = aca.get_data(
    water_source="river",        # where the water is
    data_type="biological",      # what kind of data
    parameters=["IBMWP"],        # optional: leave out for every parameter
    area_type="comarca",         # optional: leave out for all of Catalonia
    areas=["Baix Empordà"],
    start="2008-01-01",
    end="2026-01-01",
)["quality"]                     # flows, levels and volumes are in ["quantity"]
```

The [tutorial notebook](examples/tutorial.ipynb) goes through every kind of
data with real output.

## What you can download

### Water sources and data types

Choose a `water_source` and a `data_type`. Each pair is one SDIM dataset:

| `water_source` | `data_type` | parameters (examples) | stations | before 2007 |
|---|---|---|---:|:---:|
| `river` | `physico_chemical` | nitrate, phosphate, ammonium, conductivity, pH, dissolved oxygen, temperature (37) | 446 | ✓ |
| | `biological` | IPS (diatoms), IBMWP (invertebrates), IMF (macrophytes), IBICAT-2010 (fish), chlorophyll a | 408 | ✓ |
| | `priority_substances` | metals, pesticides, PAHs, solvents, PCBs, dioxins (221) | 384 | ✓ |
| | `hydromorphological` | IHF habitat index | 366 | |
| | `flow` | daily river and canal flow | 99 | ✓ |
| | `level` | daily river and canal level | 91 | ✓ |
| `reservoir` | `physico_chemical` ⚠ | nutrients, oxygen, Secchi disc, salinity (31) | 30 | ✓ ¹ |
| | `biological` ⚠ | chlorophyll a, % cyanobacteria | 30 | ✓ ¹ |
| | `priority_substances` ⚠ | metals, pesticides, solvents (152) | 13 | ✓ ¹ |
| | `volume` | daily volume, % full, water level | 13 | ✓ |
| `groundwater` | `physico_chemical` | nitrate, conductivity, chloride, sulphate (29) | 1532 | ✓ |
| | `priority_substances` | metals, pesticides, triazines (86) | 1532 | ✓ |
| | `level` | piezometric level | 621 | ✓ |
| `lakes_and_wetlands` | `physico_chemical` | nutrients, oxygen, salinity (31) | 82 | |
| | `biological` | InClo, InGA, ACCO-2010, EQATg, QAELS, chlorophyll (13) | 81 | |
| | `priority_substances` | metals, pesticides, PAHs (131) | 56 | |
| | `hydromorphological` | ECELS index | 78 | |
| `coastal` | `physico_chemical` ⚠ | nutrients, turbidity, fluorescence, Secchi disc (21) | 174 | ✓ |
| | `biological` ⚠ | POMI, CYMOX, CARLIT, MEDOCC (EQR), chlorophyll a | 336 | ✓ |
| | `priority_substances` ⚠ | metals and organics in water and sediment (224) | 269 | ✓ |
| `protected` ² | `physico_chemical`, `biological`, `priority_substances`, `hydromorphological` | as above, for protected zones | 577 | nitrate zones |

⚠ SDIM itself currently returns no rows for these (its own web page gives the
same empty report), so pySDIM raises `SDIMNoData`.
¹ Before 2007, rivers and reservoirs share one dataset: filter by area.
² Add `protected_zone=`: `drinking_water`, `river_reserves`,
`nitrate_vulnerable` or `eutrophication_sensitive` (default: the first that has
the data type).

Without `data_type` you get `physico_chemical`, or the data type that contains
your `parameters`. Catalan names also work: `"embassaments"`, `"biològics"`,
`"cabals"`, `"comarques"`. `sdim.data_sources()` prints the full table.

### Parameters

`parameters=[...]` takes SDIM names (`"Nitrats"`, `"índex IBMWP"`), parts of
them (`"nitrat"`, `"IBMWP"`) or English aliases (`nitrate`, `phosphate`,
`ammonia`, `conductivity`, `ec`, `temperature`, `oxygen`, `ph`). Leave it out to
get every parameter of the dataset. `groups=["Invertebrats"]` selects a whole
family instead. To see what a dataset holds:

```python
from sdim import Catalog

cat = Catalog()
cat.search_variables("nitrat")         # find a parameter
cat.variables_for("0001", "0001")      # every parameter of river biology (network, subnetwork)
```

`sdim describe after_2007:0001:0001` prints the same from a terminal; target
ids are in the `target_id` column of `sdim.data_sources()`.

### Area types

`area_type` and `areas` are SDIM's "Àmbit" filter. One area type per request;
names are case- and accent-insensitive, and codes work too.

| `area_type` | SDIM menu | names in | count | example |
|---|---|---|---:|---|
| *(none)* | Catalunya | | | all of Catalonia |
| `basin` | Conques | `metadata/basins.csv` | 33 | `"Ter"`, `"Muga"` |
| `river` | Rius | `metadata/rivers.csv` | 185 | `"Ter"`, `"Fluvià"` |
| `reservoir` | Embassaments | `metadata/reservoirs.csv` | 31 | `"Sau"` |
| `water_mass` | Masses d'aigua | `metadata/masses.csv` | 581 | `"Port de Tarragona"` |
| `aquifer` | Aqüífers | `metadata/aquifers.csv` | 174 | `"Aqüífer superficial de la plana al·luvial del baix Ter i Daró"` |
| `comarca` | Comarques | `metadata/comarcas.csv` | 44 | `"Baix Empordà"` |
| `municipi` | Municipis | `metadata/municipis.csv` | 807 | `"Girona"` |

Counts are for after 2007; the pre-2007 lists are shorter. A partial name
matches every area that contains it, so give the full name to pick one.
`cat.rivers("ter")` and `sdim search ter --flavor rivers` look names up.

### Dates

`start` and `end` are ISO dates (`"2008-01-01"`). SDIM keeps data from before
2007 in a separate archive: add `period="before_2007"` and query each period
separately for longer series.

## What you get back

`get_data()` returns a dict of DataFrames: `"quality"` for samples and
`"quantity"` for daily flows, levels and volumes. Main columns: `date`
(datetime), `station_code`, `station_name`, `variable`, `value` (float),
`qualifier` (`"<"` for `<0.5`), `value_raw`, `unit`, `utm_x`, `utm_y`, plus the
water body, network and target names.

- `result.provenance` records the source, URL, access time and query, and
  `result.save("out/ter")` writes the CSVs and a provenance JSON.
- Requests SDIM refuses as too large are split and joined automatically.
- Connection errors and server outages are retried with backoff.
- `aca.download(..., output="report.xlsx")` keeps SDIM's raw Excel file.

## Command line

```bash
sdim get --water-source river --data-type biological \
    --area-type comarca --area "Baix Empordà" \
    --start 2008-01-01 --end 2026-01-01 -o out/baix_emporda_bio

sdim targets                            # every dataset, source and data type
sdim describe after_2007:0001:0001      # parameters of one dataset
```

`sdim get` saves parsed CSVs; `sdim download` saves the raw file.

## Fair use and citation

pySDIM only talks to the public SDIM website and does not redistribute ACA
data. Keep request volumes moderate. The MIT license covers the code, not the
data: when you publish data obtained with pySDIM, cite the ACA as the source
with the access date and follow the Generalitat de Catalunya's reuse
conditions.

**Data:** Agència Catalana de l'Aigua (ACA), SDIM.
https://aplicacions.aca.gencat.cat/sdim21/

**Software** (see `CITATION.cff`):

> David Abert-Fernandez, Eduard Madaula, Gisela Gonzalvo-Henry, Anna Menció, Hèctor Monclús. *pySDIM — Python client for ACA SDIM water data*. DOI: 10.5281/zenodo.22661965 · https://github.com/davitens/pySDIM
