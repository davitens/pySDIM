"""ACA SDIM Python client — public API."""

from .catalog import Catalog
from .client import SDIM
from .exceptions import (
    SDIMError,
    SDIMExportError,
    SDIMNoData,
    SDIMQueryError,
    SDIMServerError,
    SDIMSessionExpired,
)
from .query import PERIOD_AFTER_2007, PERIOD_BEFORE_2007, Query
from .session import SDIMSession

__version__ = "0.4.0"

__all__ = [
    "SDIM",
    "SDIMSession",
    "Catalog",
    "Query",
    "PERIOD_AFTER_2007",
    "PERIOD_BEFORE_2007",
    "SDIMError",
    "SDIMExportError",
    "SDIMNoData",
    "SDIMQueryError",
    "SDIMServerError",
    "SDIMSessionExpired",
    "__version__",
]