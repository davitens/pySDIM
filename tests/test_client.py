"""Tests for SDIM.get_data splitting, station context, provenance and output
validation, against a fake server (no network required).

Run:  python3 tests/test_client.py
"""

import io
import json
import sys
import tempfile
import warnings
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdim import SDIM, Query, SDIMResult
from sdim.client import _STAT_200, _STAT_NO_DATA, _STAT_TRUNCATED, split_query
from sdim.exceptions import (
    SDIMError, SDIMNoData, SDIMParseError, SDIMServerError, SDIMWarning,
)

META = Path(__file__).resolve().parent.parent / "metadata"

# catalog stations of after_2007:0001:0001 and their export codes
STATIONS = {"F007569": "200046000", "F007521": "160002000", "F007528": "200001000"}


def _export(rows: list[list], station_header: str = "Codi Estació") -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Programa de Seguiment i Control"
    ws.append([None, "Resultats analítics de qualitat de les masses d'aigua"])
    ws.append([None, "Data", station_header, "Codi massa d'aigua", "Massa d'aigua",
               "UTM X", "UTM Y", "Variable", "Valor", "Unitat Mesura"])
    for row in rows:
        ws.append([None, *row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class FakeSDIM(SDIM):
    """Serves one measurement per station every 10 days; refuses reports with
    more than ``limit`` rows the way SDIM does (HTTP 202)."""

    def __init__(self, limit: int = 10**9, station_header: str = "Codi Estació",
                 codes: dict[str, str] | None = None, fail_generate: int = 0,
                 fail_download: int = 0, report_retries: int = 2):
        super().__init__(metadata_dir=META, report_retries=report_retries,
                         report_retry_wait=0)
        self.limit, self.station_header = limit, station_header
        self.codes = codes or STATIONS
        self.calls: list[Query] = []
        self._rows: list[list] = []
        # how many generate/download calls fail before the server "recovers"
        self.fail_generate, self.fail_download = fail_generate, fail_download
        self.resets = 0
        self._generated = False

    def _reset(self) -> None:
        self.resets += 1
        self._generated = False  # a new session has no report to export
        super()._reset()

    def _rows_for(self, q: Query) -> list[list]:
        start, end = date.fromisoformat(q.start), date.fromisoformat(q.end)
        rows, day = [], start
        while day <= end:
            # fixed 10-day grid, so any split of the range sees the same samples
            if (day - date(2000, 1, 1)).days % 10 == 0:
                for st in q.stations:
                    rows.append([day.strftime("%Y/%m/%d"), self.codes.get(st, st), "x", "mass",
                                 "1.0", "2.0", "índex IPS", "10.5", "Sense unitats"])
            day += timedelta(days=1)
        return rows

    def _generate(self, query: Query) -> int:
        self.calls.append(query)
        if self.fail_generate:
            self.fail_generate -= 1
            raise SDIMServerError("Request failed: connection dropped")
        self._generated = True
        self._rows = self._rows_for(query)
        if not self._rows:
            return _STAT_NO_DATA
        return _STAT_TRUNCATED if len(self._rows) > self.limit else _STAT_200

    def _download(self) -> bytes:
        assert self._generated, "export requested without a generated report"
        if self.fail_download:
            self.fail_download -= 1
            raise SDIMServerError("GET exportar.do -> HTTP 400")
        return _export(self._rows, self.station_header)


def _query(**kw) -> Query:
    base = dict(period="after_2007", networks=["0001"], subnetworks=["0001"],
                variable_kinds=[("g", "6")], ambit="catalunya",
                stations={st: ["1"] for st in STATIONS},
                start="2010-01-01", end="2010-12-31")
    base.update(kw)
    return Query(**base)


def check_split() -> None:
    q = _query()
    halves = split_query(q)
    assert [len(h.stations) for h in halves] == [1, 2]
    one = _query(stations={"F007569": ["1"]})
    a, b = split_query(one)
    assert (a.start, a.end, b.start, b.end) == ("2010-01-01", "2010-07-02", "2010-07-03", "2010-12-31")
    assert split_query(_query(stations={"F007569": ["1"]}, start="2010-01-01", end="2010-01-01")) is None

    whole = FakeSDIM().get_data(q)["quality"]
    aca = FakeSDIM(limit=12)  # 36 samples x 3 stations must be split by stations and dates
    with warnings.catch_warnings():
        warnings.simplefilter("error", SDIMWarning)
        res = aca.get_data(q)
    df = res["quality"]
    assert len(aca.calls) > 3
    assert len(df) == len(whole) == 36 * 3, len(df)
    key = ["station_code", "date"]
    assert not df.duplicated(key).any(), "split parts must not overlap"
    assert sorted(map(tuple, df[key].astype(str).values)) == sorted(map(tuple, whole[key].astype(str).values))
    assert res.provenance["requests"] == len(aca.calls)

    try:
        FakeSDIM(limit=12).get_data(q, max_requests=3)
        raise AssertionError("expected max_requests to stop the split")
    except SDIMError as exc:
        assert "max_requests" in str(exc)
    try:
        FakeSDIM(limit=12).get_data(q, split=False)
        raise AssertionError("expected a truncation error without split")
    except SDIMError as exc:
        assert "maximum number of records" in str(exc)


def check_context_and_provenance() -> None:
    res = FakeSDIM().get_data(_query())
    assert isinstance(res, SDIMResult) and isinstance(res, dict)
    df = res.quality
    assert res["quality"] is df
    cols = list(df.columns)
    assert cols[:9] == ["date", "station_code", "station_id", "station_name", "target_id",
                        "network", "network_name", "subnetwork", "subnetwork_name"], cols[:9]
    row = df[df.station_code == "200046000"].iloc[0]
    assert row.station_id == "F007569"
    assert row.station_name == "El Ter des de Flaçà fins al mar"
    assert row.target_id == "after_2007:0001:0001"
    assert row.network_name == "CONTROL RIUS" and row.subnetwork_name == "Elements biològics"

    prov = res.provenance
    assert prov["target_id"] == "after_2007:0001:0001" and prov["requests"] == 1
    assert prov["source_url"].startswith("https://aplicacions.aca.gencat.cat/sdim21")
    assert prov["accessed_at"] and prov["client"].startswith("pysdim ")
    assert df.attrs["provenance"] is prov and df.attrs["query"].period == "after_2007"

    with tempfile.TemporaryDirectory() as tmp:
        paths = res.save(Path(tmp) / "bio")
        names = sorted(p.name for p in paths)
        assert names == ["bio_provenance.json", "bio_quality.csv"], names
        saved = json.loads((Path(tmp) / "bio_provenance.json").read_text(encoding="utf-8"))
        assert saved["target_id"] == "after_2007:0001:0001"

    plain = FakeSDIM().get_data(_query(), station_context=False).quality
    assert "station_id" not in plain


def check_validation() -> None:
    # a renamed station header leaves station_code empty -> loud failure
    try:
        FakeSDIM(station_header="Codi Punt").get_data(_query())
        raise AssertionError("expected SDIMParseError")
    except SDIMParseError as exc:
        assert "station_code" in str(exc)
    FakeSDIM(station_header="Codi Punt").get_data(_query(), validate_output=False)

    # stations missing from the catalog -> warning, data still returned
    aca = FakeSDIM(codes={"F007569": "999999999"})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        df = aca.get_data(_query(stations={"F007569": ["1"]})).quality
    assert len(df) and any("not in the metadata catalog" in str(w.message) for w in caught)

    # every part "no records" -> SDIMNoData, as before
    try:
        FakeSDIM().get_data(_query(stations={"F007569": ["1"]}, start="2010-01-02", end="2010-01-01"))
        raise AssertionError("expected SDIMNoData")
    except SDIMNoData:
        pass


def check_retries() -> None:
    # a refused export regenerates the report in a fresh session
    aca = FakeSDIM(fail_download=1)
    df = aca.get_data(_query()).quality
    assert len(df) == 36 * 3 and len(aca.calls) == 2 and aca.resets == 1

    # a dropped connection while generating is retried the same way
    aca = FakeSDIM(fail_generate=2)
    assert len(aca.get_data(_query()).quality) == 36 * 3
    assert len(aca.calls) == 3 and aca.resets == 2

    # download() recovers too
    aca = FakeSDIM(fail_download=1)
    assert aca.download(_query())[:2] == b"PK" and aca.resets == 1

    # a server that stays down fails after report_retries regenerations
    aca = FakeSDIM(fail_download=5, report_retries=2)
    try:
        aca.get_data(_query())
        raise AssertionError("expected SDIMServerError")
    except SDIMServerError:
        pass
    assert len(aca.calls) == 3 and aca.resets == 2

    # retries are per report: a split request recovers chunk by chunk
    aca = FakeSDIM(limit=12, fail_download=1)
    assert len(aca.get_data(_query()).quality) == 36 * 3 and aca.resets == 1

    # query problems are not retried
    aca = FakeSDIM()
    try:
        aca.get_data(_query(stations={"F007569": ["1"]}, start="2010-01-02", end="2010-01-01"))
    except SDIMNoData:
        pass
    assert aca.resets == 0


def check_reservoir_fallback() -> None:
    # SDIM's reservoir filter ignores volume gauges: match the series names
    from sdim.resolver import resolve_request

    aca = SDIM(metadata_dir=META)
    res = resolve_request(aca.catalog, water_source="reservoir", data_type="volume",
                          area_type="reservoir", areas=["Sau"],
                          start="2020-01-01", end="2020-02-01")
    out = aca._reservoir_series(res, lambda name: True)
    assert list(out) == ["L08303-72-00001"], out
    assert len(out["L08303-72-00001"]) == 3
    assert aca._reservoir_series(res, lambda name: "Volum" in name) == {
        "L08303-72-00001": ["4159510"]}


def main() -> int:
    check_reservoir_fallback()
    check_retries()
    check_split()
    check_context_and_provenance()
    check_validation()
    print("OK: client tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def test_client():
    assert main() == 0
