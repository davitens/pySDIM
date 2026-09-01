"""Query model for ACA SDIM report generation.

Converts a high-level request into the ordered POST payload the SDIM
``consultaInforme.do`` endpoint expects (repeated form fields preserved).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .exceptions import SDIMQueryError

PERIOD_AFTER_2007 = "after_2007"
PERIOD_BEFORE_2007 = "before_2007"

VALID_PERIODS = (PERIOD_AFTER_2007, PERIOD_BEFORE_2007)

# Nominal ambits ('checkBoxAmbit') accepted by the filter page.
VALID_AMBITS = ("catalunya", "conques", "massa", "embassament", "riu", "aquifer",
                "comarques", "municipis")

# Ambits whose spatial selector is a set of river checkboxes.
_RIU_AMBITS = ("riu", "massa")


def _fmt_date(value: str) -> str:
    value = value.strip()
    if "-" in value:
        y, m, d = value.split("-")
        return f"{d}/{m}/{y}"
    if "/" in value:
        return value
    raise SDIMQueryError(
        f"Unsupported date format {value!r}; use YYYY-MM-DD or DD/MM/YYYY."
    )


@dataclass
class Query:
    """A request for an SDIM report.

    Parameters
    ----------
    period:
        ``"after_2007"`` or ``"before_2007"``.
    networks:
        Network codes (``xarxaControl``), e.g. ``["0001"]`` for CONTROL RIUS.
    subnetworks:
        Subnetwork codes (``subXarxaControl``), e.g. ``["0022"]`` for physico-chemical.
    variable_kinds:
        The selected variable-type branches (``g``/``f``/``v``) as name/value pairs,
        e.g. ``[("g","5"), ("f","050004"), ("v","0002")]``.
    ambit:
        Geographic ambit radio value (``riu``, ``conques``, ...).
    spatial:
        Spatial filter fields, e.g. ``{"riuAmbit": ["200"]}`` or
        ``{"riuAmbit": ["200"], "concaAmbit": ["..."], ...}``.
    stations:
        Mapping station code -> list of variable ids to include, e.g.
        ``{"F007528": ["3057279"]}``. The selection is submitted as repeated
        ``puntControl``/``variable`` fields preserving order.
    cercador:
        Optional search-box text (e.g. ``{"riu": "RIU TER"}``).
    start, end:
        Report interval (ISO ``YYYY-MM-DD`` or ``DD/MM/YYYY``).
    """

    period: str = PERIOD_AFTER_2007
    networks: list[str] = field(default_factory=list)
    subnetworks: list[str] = field(default_factory=list)
    variable_kinds: list[tuple[str, str]] = field(default_factory=list)
    ambit: str = "catalunya"
    spatial: dict[str, list[str]] = field(default_factory=dict)
    stations: dict[str, list[str]] = field(default_factory=dict)
    cercador: dict[str, str] = field(default_factory=dict)
    start: str = ""
    end: str = ""

    def __post_init__(self) -> None:
        if self.period not in VALID_PERIODS:
            raise SDIMQueryError(f"period must be one of {VALID_PERIODS}, got {self.period!r}")
        if self.ambit not in VALID_AMBITS:
            raise SDIMQueryError(f"ambit must be one of {VALID_AMBITS}, got {self.ambit!r}")
        if not self.start or not self.end:
            raise SDIMQueryError("start and end dates are required")
        if not self.networks:
            raise SDIMQueryError("at least one network is required")
        if not self.subnetworks:
            raise SDIMQueryError("at least one subnetwork is required")
        if not any(self.stations.values()):
            raise SDIMQueryError("at least one station with a variable is required")

    def to_sdim_payload(self) -> list[tuple[str, str]]:
        """Return the ordered form fields for ``consultaInforme.do``."""
        payload: list[tuple[str, str]] = [
            ("modo", "rest"),
            ("periodeXarxaControl", self.period),
            ("modoConsultaDetall", "completa"),
        ]
        for net in self.networks:
            payload.append(("xarxaControl", net))
        for sub in self.subnetworks:
            payload.append(("subXarxaControl", sub))
        payload.extend(self.variable_kinds)
        payload.append(("ambit", self.ambit))
        for name, values in self.spatial.items():
            if isinstance(values, str):
                values = [values]
            for value in values:
                payload.append((name, value))
        for name, value in self.cercador.items():
            payload.append((name, value))
        payload.append(("consultaDetallRealitzada", "completa"))
        for station, variables in self.stations.items():
            if not variables:
                continue
            payload.append(("puntControl", station))
            for variable in variables:
                payload.append(("variable", variable))
        payload.extend([
            ("dataIniciInforme", _fmt_date(self.start)),
            ("dataFinalInforme", _fmt_date(self.end)),
            ("informeEjecutar", "0"),
        ])
        return payload


def pairs_to_map(pairs: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """Convert repeated (name, value) pairs into a {name: [values...]} mapping."""
    result: dict[str, list[str]] = {}
    for name, value in pairs:
        result.setdefault(name, []).append(value)
    return result