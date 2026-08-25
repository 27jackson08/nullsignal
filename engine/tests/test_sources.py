"""Source adapters: parsing, provenance, and failure handling.

Network calls are not exercised; the transforms behind them are, against the
committed fixtures. The failure paths matter as much as the happy ones -- a
snapshot that quietly omitted a dead feed would be self-refuting in a project
about noticing when data goes missing.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from nullsignal.sources import base, gtfs_static, snapshot, transit

from conftest import requires_snapshot


# --- provenance ---------------------------------------------------------------

def test_written_records_carry_a_content_hash(tmp_path):
    """The hash is what the flatline detector later compares across polls, so
    it is captured at ingest rather than bolted on."""
    result = base.write_json("test", [{"a": 1}], tmp_path / "out.json")
    assert result.content_hash and len(result.content_hash) == 16
    assert result.byte_count == (tmp_path / "out.json").stat().st_size
    assert json.loads((tmp_path / "out.json").read_text()) == [{"a": 1}]


def test_identical_payloads_hash_identically(tmp_path):
    first = base.write_json("a", [{"x": 1}], tmp_path / "a.json")
    second = base.write_json("b", [{"x": 1}], tmp_path / "b.json")
    third = base.write_json("c", [{"x": 2}], tmp_path / "c.json")
    assert first.content_hash == second.content_hash != third.content_hash


def test_a_manifest_entry_is_serialisable(tmp_path):
    entry = base.write_json("t", [], tmp_path / "t.json").as_manifest_entry()
    assert json.dumps(entry)
    assert set(entry) >= {"source_id", "fetched_at", "content_hash", "byte_count"}


def test_a_non_200_is_raised_rather_than_written(tmp_path, monkeypatch):
    class Response:
        status_code, text, content = 503, "upstream unavailable", b""

    monkeypatch.setattr(httpx.Client, "get", lambda *a, **k: Response())
    with pytest.raises(base.SourceFetchError, match="503"):
        base.fetch_to_file("x", "https://example.test/x", tmp_path / "x.json")
    assert not (tmp_path / "x.json").exists()


def test_a_transport_error_is_raised_rather_than_swallowed(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx.Client, "get", boom)
    with pytest.raises(base.SourceFetchError, match="request failed"):
        base.fetch_to_file("x", "https://example.test/x", tmp_path / "x.json")


# --- manifest merging ---------------------------------------------------------

def test_a_partial_rerun_preserves_provenance_of_untouched_sources(tmp_path):
    """Regression: a partial re-run once overwrote the manifest wholesale,
    erasing the provenance of files still on disk and still valid -- losing our
    own audit trail, in a project premised on noticing missing data."""
    first = base.write_json("tracts", [{"a": 1}], tmp_path / "tracts.json")
    snapshot._write_manifest(tmp_path, [first], [])

    second = base.write_json("311", [{"b": 2}], tmp_path / "311.json")
    snapshot._write_manifest(tmp_path, [second], [])

    sources = {e["source_id"] for e in snapshot.load_manifest(tmp_path)["sources"]}
    assert sources == {"tracts", "311"}


def test_a_source_that_recovers_stops_being_listed_as_failed(tmp_path):
    snapshot._write_manifest(tmp_path, [], [("311", "HTTP 400")])
    assert snapshot.load_manifest(tmp_path)["failures"]

    recovered = base.write_json("311", [{"b": 2}], tmp_path / "311.json")
    snapshot._write_manifest(tmp_path, [recovered], [])
    assert snapshot.load_manifest(tmp_path)["failures"] == []


def test_an_unreadable_manifest_is_rebuilt_with_a_warning(tmp_path, capsys):
    (tmp_path / snapshot.MANIFEST_NAME).write_text("{ not json")
    entry = base.write_json("svi", [], tmp_path / "svi.json")
    snapshot._write_manifest(tmp_path, [entry], [])

    assert "unreadable manifest" in capsys.readouterr().out
    assert snapshot.load_manifest(tmp_path)["sources"][0]["source_id"] == "svi"


def test_a_missing_manifest_names_the_command_that_creates_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="nullsignal snapshot"):
        snapshot.load_manifest(tmp_path)


# --- real protobuf ------------------------------------------------------------

@requires_snapshot
def test_a_real_gtfs_realtime_feed_decodes(raw_dir):
    feed_path = raw_dir / "gtfs_rt" / "ace.pb"
    if not feed_path.exists():
        pytest.skip("no committed protobuf")

    result = base.write_json("probe", [], raw_dir.parent / "probe.json")
    summary = transit._summarise(feed_path, result)

    assert summary["entity_count"] > 0
    assert summary["trip_updates"] > 0
    assert summary["header_timestamp"], "a live feed carries its own clock"
    (raw_dir.parent / "probe.json").unlink(missing_ok=True)


# --- static gtfs --------------------------------------------------------------

def build_gtfs_zip(path: Path, rows: list[dict]) -> Path:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=["stop_id", "stop_name", "stop_lat", "stop_lon",
                            "location_type", "parent_station"])
    writer.writeheader()
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("stops.txt", buffer.getvalue())
    return path


def test_only_parent_stations_are_kept(tmp_path):
    """Counting platforms instead of stations would triple-count a single
    station's walk coverage."""
    archive = build_gtfs_zip(tmp_path / "gtfs.zip", [
        {"stop_id": "101", "stop_name": "Station A", "stop_lat": "40.8",
         "stop_lon": "-73.9", "location_type": "1", "parent_station": ""},
        {"stop_id": "101N", "stop_name": "Platform", "stop_lat": "40.8",
         "stop_lon": "-73.9", "location_type": "0", "parent_station": "101"},
        {"stop_id": "102", "stop_name": "Station B", "stop_lat": "40.7",
         "stop_lon": "-74.0", "location_type": "1", "parent_station": ""},
    ])
    stations = gtfs_static._extract_stations(archive)
    assert [s["stop_id"] for s in stations] == ["101", "102"]
    assert isinstance(stations[0]["latitude"], float)


def test_a_station_with_unusable_coordinates_is_dropped(tmp_path):
    archive = build_gtfs_zip(tmp_path / "gtfs.zip", [
        {"stop_id": "1", "stop_name": "Good", "stop_lat": "40.8",
         "stop_lon": "-73.9", "location_type": "1", "parent_station": ""},
        {"stop_id": "2", "stop_name": "Bad", "stop_lat": "", "stop_lon": "",
         "location_type": "1", "parent_station": ""},
    ])
    assert [s["stop_id"] for s in gtfs_static._extract_stations(archive)] == ["1"]
