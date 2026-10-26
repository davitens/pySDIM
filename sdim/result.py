"""Parsed SDIM reports: provenance, station context and output checks."""

from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ._version import __version__
from .exceptions import SDIMParseError, SDIMWarning
from .query import Query

SOURCE = "Agència Catalana de l'Aigua (ACA), SDIM"
SOURCE_URL = "https://aplicacions.aca.gencat.cat/sdim21/"
CITATION = ("Abert-Fernandez, D., Madaula, E., Gonzalvo-Henry, G., Menció, A., "
            "Monclús, H. pySDIM — Python client for ACA SDIM water data. "
            "https://doi.org/10.5281/zenodo.22661965")

# columns that must not come back all-empty from a non-empty sheet
KEY_COLUMNS = ("date", "station_code", "variable", "value_raw")

# columns added from the metadata catalog, placed after ``station_code``
CONTEXT_COLUMNS = ("station_id", "station_name", "target_id", "network",
                   "network_name", "subnetwork", "subnetwork_name")


class SDIMResult(dict):
    """A parsed report: ``{"quality": DataFrame, "quantity": DataFrame}``.

    It is still a dict, so ``result["quality"]`` keeps working; ``quality``,
    ``quantity`` and ``provenance`` are shortcuts. Each DataFrame also carries
    ``attrs["query"]`` and ``attrs["provenance"]``.
    """

    def __init__(self, sheets: dict[str, pd.DataFrame], provenance: dict):
        super().__init__(sheets)
        self.provenance = provenance
        for df in self.values():
            df.attrs["provenance"] = provenance

    @property
    def quality(self) -> pd.DataFrame:
        return self.get("quality", pd.DataFrame())

    @property
    def quantity(self) -> pd.DataFrame:
        return self.get("quantity", pd.DataFrame())

    def save(self, prefix: str | Path) -> list[Path]:
        """Write ``<prefix>_quality.csv`` / ``<prefix>_quantity.csv`` (non-empty
        sheets only) and ``<prefix>_provenance.json``; returns the paths."""
        prefix = Path(prefix)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        paths = []
        for name, df in self.items():
            if len(df):
                path = prefix.with_name(f"{prefix.name}_{name}.csv")
                df.to_csv(path, index=False)
                paths.append(path)
        path = prefix.with_name(f"{prefix.name}_provenance.json")
        path.write_text(json.dumps(self.provenance, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        paths.append(path)
        return paths


def provenance(query: Query, *, requests: int = 1) -> dict:
    """Where and when the data came from, for citation and reproducibility."""
    target_id = (f"{query.period}:{query.networks[0]}:{query.subnetworks[0]}"
                 if len(query.networks) == 1 and len(query.subnetworks) == 1 else None)
    return {
        "source": SOURCE,
        "source_url": SOURCE_URL,
        "accessed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_id": target_id,
        "period": query.period,
        "networks": list(query.networks),
        "subnetworks": list(query.subnetworks),
        "start": query.start,
        "end": query.end,
        "stations": len(query.stations),
        "requests": requests,
        "client": f"pysdim {__version__}",
        "citation": CITATION,
    }


def add_station_context(df: pd.DataFrame, catalog, query: Query) -> pd.DataFrame:
    """Join catalog station ids/names and target names onto a parsed sheet.

    Quality rows match on the export station code (the suffix of the catalog
    station name, ``"El Ter ... - 200046000"``); quantity rows match on the
    exact series name. Rows without a match keep empty context columns.
    """
    if df.empty or "station_code" not in df:
        return df
    prov = provenance(query)
    target_id = prov["target_id"]
    sv = catalog.target_station_variables(target_id) if target_id else pd.DataFrame()
    if sv.empty:
        sv = catalog.table("stations").rename(columns={"name": "station_name"})
        sv = sv[(sv.period == query.period) & sv.network.isin(query.networks)]
    sv = sv.assign(
        code=sv["station_name"].str.rsplit(" - ", n=1).str[-1].str.strip(),
        base=sv["station_name"].str.rsplit(" - ", n=1).str[0].str.strip(),
    )

    out = df.copy()
    by_code = sv.drop_duplicates("code").set_index("code")
    out["station_id"] = out["station_code"].astype(str).map(by_code["station"])
    if "variable_name" in sv and df["source_sheet"].eq("quantity").all():
        by_var = sv.drop_duplicates("variable_name").set_index("variable_name")
        out["station_id"] = out["variable"].map(by_var["station"]).fillna(out["station_id"])
    else:
        # quantity sheets already carry the export's station name
        out["station_name"] = out["station_code"].astype(str).map(by_code["base"])

    row = catalog.target(target_id) if target_id else None
    out["target_id"] = target_id
    out["network"] = ",".join(query.networks)
    out["network_name"] = row["network_name"] if row is not None else None
    out["subnetwork"] = ",".join(query.subnetworks)
    out["subnetwork_name"] = row["subnetwork_name"] if row is not None else None

    # context right after station_code, everything else in its original order
    rest = [c for c in df.columns if c not in CONTEXT_COLUMNS]
    at = rest.index("station_code") + 1
    return out[rest[:at] + list(CONTEXT_COLUMNS) + rest[at:]]


def validate(result: dict[str, pd.DataFrame]) -> None:
    """Fail loudly on broken parses instead of returning plausible-looking data.

    Raises :class:`SDIMParseError` when a non-empty sheet has a key column that
    is entirely empty (the export layout changed). Warns (:class:`SDIMWarning`)
    when the report has no rows at all, or when some dates or stations could
    not be resolved.
    """
    sheets = {k: df for k, df in result.items() if len(df)}
    if not sheets:
        warnings.warn("SDIM generated the report but it contains no data rows.",
                      SDIMWarning, stacklevel=3)
        return
    for name, df in sheets.items():
        empty = [c for c in KEY_COLUMNS if c not in df or df[c].isna().all()]
        if empty:
            raise SDIMParseError(
                f"{name} sheet: column(s) {empty} are empty in all {len(df)} rows; "
                "the SDIM export layout may have changed. Keep the raw file with "
                "SDIM.download(..., output=...) and report it.")
        bad_dates = int(df["date"].isna().sum())
        if bad_dates:
            warnings.warn(f"{name} sheet: {bad_dates} of {len(df)} dates could not be parsed.",
                          SDIMWarning, stacklevel=3)
        if "station_id" in df:
            missing = df.loc[df["station_id"].isna(), "station_code"].dropna().unique()
            if len(missing):
                warnings.warn(
                    f"{name} sheet: {len(missing)} station(s) not in the metadata catalog "
                    f"(e.g. {list(missing[:3])}); refresh it with scripts/build_metadata.py.",
                    SDIMWarning, stacklevel=3)
