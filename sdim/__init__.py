"""ACA SDIM Python client — public API."""

from ._version import __version__
from .catalog import Catalog
from .client import SDIM
from .exceptions import (
    SDIMError,
    SDIMExportError,
    SDIMNoData,
    SDIMParseError,
    SDIMQueryError,
    SDIMServerError,
    SDIMSessionExpired,
    SDIMWarning,
)
from .query import PERIOD_AFTER_2007, PERIOD_BEFORE_2007, Query
from .result import SDIMResult
from .session import SDIMSession

__all__ = [
    "SDIM",
    "SDIMSession",
    "Catalog",
    "Query",
    "SDIMResult",
    "PERIOD_AFTER_2007",
    "PERIOD_BEFORE_2007",
    "SDIMError",
    "SDIMExportError",
    "SDIMNoData",
    "SDIMParseError",
    "SDIMQueryError",
    "SDIMServerError",
    "SDIMSessionExpired",
    "SDIMWarning",
    "__version__",
]
