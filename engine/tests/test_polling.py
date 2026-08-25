"""Polling, paging, and scenario parsing — the failure paths especially."""
from __future__ import annotations

import httpx
import pytest

from nullsignal.sources import poll, snapshot, socrata
from nullsignal.sources.base import SourceFetchError


class FakeResponse:
    def __init__(self, status_code=200, content=b"", payload=None):
        self.status_code = status_code
        self.content = content
        self.text = ""
        self._payload = payload

    def json(self):
        return self._payload


# --- polling ------------------------------------------------------------------

def test_a_failed_request_is_recorded_rather_than_dropped(tmp_path, monkeypatch):
    """The most important line in the poller.

    Dropping a failed poll would hide precisely the outage this system exists
    to notice, and would leave the flatline detectors reading a gap as
    continuity.
    """
    def boom(self, url, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx.Client, "get", boom)
    recorded = poll.run_poll(tmp_path, rounds=1, quiet=True)

    assert recorded, "a failed poll is still an observation"
    assert all(o.http_status == 0 for o in recorded)
    assert all("request failed" in o.note for o in recorded)


def test_an_undecodable_payload_still_yields_an_observation(tmp_path, monkeypatch):
    """Garbage from a feed is a fact about the feed."""
    monkeypatch.setattr(httpx.Client, "get",
                        lambda self, url, **kw: FakeResponse(content=b"not a protobuf"))
    recorded = poll.run_poll(tmp_path, rounds=1, quiet=True)

    transit = [o for o in recorded if o.source_id.startswith("gtfs_rt")]
    assert transit
    assert all(o.content_hash for o in transit), "hash the bytes regardless"
    assert all(o.feed_timestamp is None for o in transit)


def test_the_header_decoder_survives_empty_bytes():
    assert poll._decode_header(b"") == (None, None)
    assert poll._decode_header(b"\xff\xff\xff") == (None, None)


def test_polls_accumulate_across_rounds(tmp_path, monkeypatch):
    from nullsignal.reliability import observations

    monkeypatch.setattr(httpx.Client, "get",
                        lambda self, url, **kw: FakeResponse(content=b"x"))
    monkeypatch.setattr(poll.time, "sleep", lambda seconds: None)
    poll.run_poll(tmp_path, rounds=3, interval_seconds=0, quiet=True)

    history = observations.read(tmp_path, "gtfs_rt:ace")
    assert len(history) == 3


# --- socrata paging -----------------------------------------------------------

def test_paging_stops_on_a_short_page(monkeypatch):
    pages = [[{"i": n} for n in range(socrata.PAGE_SIZE)], [{"i": "last"}]]

    def get(self, url, **kwargs):
        return FakeResponse(payload=pages.pop(0) if pages else [])

    monkeypatch.setattr(httpx.Client, "get", get)
    rows = socrata._paged_get("ds", {}, max_records=socrata.PAGE_SIZE * 4)
    assert len(rows) == socrata.PAGE_SIZE + 1


def test_paging_respects_the_record_ceiling(monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: FakeResponse(payload=[{"i": n} for n in range(10)]))
    assert len(socrata._paged_get("ds", {}, max_records=10)) == 10


def test_a_rejected_query_is_raised_with_its_reason(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get",
                        lambda self, url, **kw: FakeResponse(status_code=400))
    with pytest.raises(SourceFetchError, match="HTTP 400"):
        socrata._paged_get("ds", {}, max_records=10)


# --- snapshot orchestration ---------------------------------------------------

def test_one_failing_source_does_not_abort_the_others(tmp_path, monkeypatch):
    """A partial snapshot is legitimate evidence. Aborting the run would
    discard what did arrive and tell us less than nothing."""
    from nullsignal.sources import base as base_module

    def only_svi_fails(dest_dir):
        raise SourceFetchError("svi: HTTP 500")

    monkeypatch.setattr(snapshot.svi, "fetch_svi", only_svi_fails)
    monkeypatch.setattr(snapshot.socrata, "fetch_tracts",
                        lambda d: base_module.write_json("nyc_tracts", [{"a": 1}],
                                                         d / "nyc_tracts.json"))

    report = snapshot.run_snapshot(
        tmp_path, skip=frozenset({"311", "weather", "transit", "gtfs_static"}))

    assert not report.ok
    assert [name for name, _ in report.failures] == ["svi"]
    assert any(r.source_id == "nyc_tracts" for r in report.results)
    assert snapshot.load_manifest(tmp_path)["failures"][0]["source"] == "svi"


def test_a_malformed_weather_response_does_not_abort_the_round(tmp_path, monkeypatch):
    """Regression: an upstream returning an unexpected JSON shape subscripted
    None and killed the whole poll, taking the transit observations with it.
    One unusable reading must not cost us the rest."""
    monkeypatch.setattr(httpx.Client, "get",
                        lambda self, url, **kw: FakeResponse(content=b"x", payload=None))
    recorded = poll.run_poll(tmp_path, rounds=1, quiet=True)

    sources = {o.source_id for o in recorded}
    assert any(s.startswith("gtfs_rt") for s in sources), "transit must survive"
    assert "nws" in sources, "the failed weather poll is itself an observation"
