"""Exceptions for the ACA SDIM client."""


class SDIMError(Exception):
    """Base class for all SDIM client errors."""


class SDIMSessionExpired(SDIMError):
    """The server-side SDIM session is missing or no longer valid."""


class SDIMQueryError(SDIMError):
    """The built query/payload is invalid."""


class SDIMNoData(SDIMError):
    """The server returned a report with no data rows."""


class SDIMServerError(SDIMError):
    """The server returned an unexpected error response."""


class SDIMExportError(SDIMError):
    """The generated report could not be downloaded or saved."""