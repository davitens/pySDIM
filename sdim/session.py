"""HTTP/session handling for the ACA SDIM web application."""

from __future__ import annotations

import os
import time

import requests

from .exceptions import SDIMServerError, SDIMSessionExpired

SDIM_BASE = "https://aplicacions.aca.gencat.cat"
SDIM_ENTRY = SDIM_BASE + "/sdim21/"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

# HTTP status responses that indicate the server-side session is missing/expired.
_SESSION_EXPIRED_STATUS = {500}
# Pages that mean we were bounced out of the application.
_SESSION_EXPIRED_MARKERS = (
    "database isn't accessible",
    "base de dades no és accessible",
    "no és accessible",
    "inaccessible",
)


def _is_session_error(response: requests.Response) -> bool:
    if response.status_code in _SESSION_EXPIRED_STATUS:
        if "text/html" in response.headers.get("content-type", ""):
            body = response.text[:8192].lower()
            return any(m in body for m in _SESSION_EXPIRED_MARKERS)
        return False
    return False


class SDIMSession:
    """A persistent HTTP session against SDIM with automatic cookie bootstrap.

    The SDIM entry page sets ``JSESSIONID`` and ``BIGipServer...`` cookies
    automatically on the first GET, so no browser cookies need to be copied.
    """

    def __init__(
        self,
        *,
        timeout: float = 60.0,
        delay: float = 0.5,
        user_agent: str = USER_AGENT,
        cookie_file: str | None = None,
        retries: int = 3,
    ):
        self.timeout = timeout
        self.delay = delay
        self.retries = retries
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.initialized = False
        if cookie_file is not None:
            self._load_cookies(cookie_file)

    def _load_cookies(self, cookie_file: str) -> None:
        import json

        if not os.path.exists(cookie_file):
            return
        with open(cookie_file, encoding="utf-8") as fh:
            data = json.load(fh)
        cookies = data.get("cookies", data)
        if isinstance(cookies, dict):
            for name, value in cookies.items():
                self.session.cookies.set(name, str(value), domain="aplicacions.aca.gencat.cat")

    def initialize(self) -> None:
        """Create the JSESSIONID by visiting the SDIM entry page."""
        if self.initialized:
            return
        try:
            r = self.session.get(SDIM_ENTRY, timeout=self.timeout)
        except requests.RequestException as exc:
            raise SDIMServerError(f"Could not reach SDIM entry page: {exc}") from exc
        if r.status_code != 200:
            raise SDIMServerError(f"SDIM entry page returned HTTP {r.status_code}")
        if not self.session.cookies.get("JSESSIONID"):
            raise SDIMSessionExpired("No JSESSIONID cookie was set by the SDIM entry page.")
        self.initialized = True

    def post(self, url: str, **kwargs) -> requests.Response:
        """POST, raising on server/session-level failures."""
        return self._request("POST", url, **kwargs)

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET, raising on server/session-level failures."""
        return self._request("GET", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        if self.initialized:
            time.sleep(self.delay)
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt >= self.retries:
                    break
                time.sleep(self.delay * (attempt + 2))
                continue
            if _is_session_error(response):
                raise SDIMSessionExpired(
                    "The SDIM session appears to have expired. Re-run initialize() and retry."
                )
            if response.status_code in {500, 502, 503, 504} and attempt < self.retries:
                # transient server error (e.g. heavy report generation)
                last_exc = SDIMServerError(f"{method} {url} -> HTTP {response.status_code}")
                time.sleep(self.delay * (attempt + 3))
                continue
            if response.status_code >= 400:
                raise SDIMServerError(f"{method} {url} -> HTTP {response.status_code}")
            return response
        if isinstance(last_exc, SDIMServerError):
            raise last_exc
        raise SDIMServerError(f"Request failed for {url}: {last_exc}")

    def close(self) -> None:
        self.session.close()


def cookie_file_from_env() -> str | None:
    """Optional debug path: export SDIM_COOKIE_FILE to inject browser cookies.

    Normally not needed -- the session bootstrap obtains cookies by itself.
    """
    return os.environ.get("SDIM_COOKIE_FILE")