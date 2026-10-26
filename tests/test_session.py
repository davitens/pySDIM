"""Tests for SDIMSession retry/backoff and reset (no network required).

Run:  python3 tests/test_session.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from sdim import session as session_mod
from sdim.exceptions import SDIMServerError
from sdim.session import SDIMSession


class FakeResponse:
    def __init__(self, status: int):
        self.status_code = status
        self.headers = {"content-type": "application/octet-stream"}
        self.text = ""


class FakeHTTP:
    """Plays back a script of responses/exceptions, one per request."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.closed = False
        self.headers = {}

    def request(self, method, url, **kw):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)

    def close(self):
        self.closed = True


def _session(script, **kw) -> tuple[SDIMSession, FakeHTTP, list[float]]:
    s = SDIMSession(**kw)
    fake = FakeHTTP(script)
    s.session = fake
    waits: list[float] = []
    session_mod.time.sleep = waits.append  # record instead of sleeping
    return s, fake, waits


def main() -> int:
    real_sleep = session_mod.time.sleep
    try:
        # connection errors and 5xx are retried with exponential backoff
        s, fake, waits = _session([requests.ConnectionError("down"), 503,
                                   requests.ConnectionError("down"), 200])
        assert s.get("https://x/").status_code == 200
        assert fake.calls == 4 and waits == [2.0, 4.0, 8.0], waits

        # backoff is capped
        s, _, _ = _session([], backoff=10.0, max_backoff=25.0)
        assert [s._wait(n) for n in range(4)] == [10.0, 20.0, 25.0, 25.0]

        # gives up after retries + 1 attempts, naming the count
        s, fake, waits = _session([requests.ConnectionError("down")] * 3, retries=2)
        try:
            s.get("https://x/")
            raise AssertionError("expected SDIMServerError")
        except SDIMServerError as exc:
            assert "after 3 attempts" in str(exc)
        assert fake.calls == 3 and waits == [2.0, 4.0]

        # 4xx is not retried at this level (the client regenerates the report)
        s, fake, _ = _session([400, 200])
        try:
            s.get("https://x/")
            raise AssertionError("expected SDIMServerError")
        except SDIMServerError as exc:
            assert "HTTP 400" in str(exc)
        assert fake.calls == 1

        # reset drops the old HTTP session and forces a new SDIM session
        s, fake, _ = _session([])
        s.initialized = True
        s.reset()
        assert fake.closed and s.session is not fake and not s.initialized
        assert s.session.headers["User-Agent"] == s.user_agent
    finally:
        session_mod.time.sleep = real_sleep

    print("OK: session tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def test_session():
    assert main() == 0
