"""Snapshot orchestrator.

Snapshot-first is a deliberate choice, not a shortcut. Committed fixtures mean
the demo never depends on conference wifi, and -- more importantly -- they make
the evaluation reproducible, which is the only way the scoreboard means anything.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import cooling, gtfs_static, socrata, svi, transit, weather
from .base import FetchResult, SourceFetchError

MANIFEST_NAME = "manifest.json"

DEFAULT_311_DAYS = 60
DEFAULT_311_MAX_RECORDS = 200_000


@dataclass(frozen=True, slots=True)
class SnapshotReport:
    results: tuple[FetchResult, ...]
    failures: tuple[tuple[str, str], ...]

    @property
    def ok(self) -> bool:
        return not self.failures


def run_snapshot(
    dest_dir: Path,
    *,
    days: int = DEFAULT_311_DAYS,
    max_requests: int = DEFAULT_311_MAX_RECORDS,
    skip: frozenset[str] = frozenset(),
) -> SnapshotReport:
    """Pull every source into dest_dir and write a provenance manifest.

    Sources are independent, so one failure is recorded and the rest continue.
    The manifest records exactly which ones succeeded -- a snapshot that
    silently omitted a dead feed would be self-refuting.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    tasks = {
        "tracts": lambda: [socrata.fetch_tracts(dest_dir)],
        "svi": lambda: [svi.fetch_svi(dest_dir)],
        "311": lambda: [socrata.fetch_service_requests(
            dest_dir, days=days, max_records=max_requests)],
        "weather": lambda: [weather.fetch_forecasts(dest_dir)],
        "transit": lambda: transit.fetch_realtime(dest_dir),
        "gtfs_static": lambda: gtfs_static.fetch_stations(dest_dir),
        "cooling": lambda: [cooling.fetch_cooling_sites(dest_dir)],
    }

    results: list[FetchResult] = []
    failures: list[tuple[str, str]] = []

    for name, task in tasks.items():
        if name in skip:
            continue
        print(f"  fetching {name} ...", flush=True)
        try:
            fetched = task()
        except SourceFetchError as exc:
            failures.append((name, str(exc)))
            print(f"    FAILED: {exc}", flush=True)
            continue
        results.extend(fetched)
        for item in fetched:
            print(f"    ok {item.source_id:22} {item.byte_count:>10,}B  {item.note}",
                  flush=True)

    _write_manifest(dest_dir, results, failures)
    return SnapshotReport(tuple(results), tuple(failures))


def _write_manifest(
    dest_dir: Path,
    results: list[FetchResult],
    failures: list[tuple[str, str]],
) -> None:
    """Merge into any existing manifest rather than replacing it.

    A partial re-run (`skip=...`) refreshes some sources and leaves others on
    disk untouched. Overwriting the manifest wholesale would erase the
    provenance of files that are still present and still valid -- losing our
    own audit trail, in a project premised on noticing when data goes missing.
    """
    path = dest_dir / MANIFEST_NAME
    existing: dict[str, dict] = {}
    previous_failures: dict[str, dict] = {}
    if path.exists():
        try:
            prior = json.loads(path.read_text())
            existing = {e["source_id"]: e for e in prior.get("sources", [])}
            previous_failures = {f["source"]: f for f in prior.get("failures", [])}
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"    warning: unreadable manifest at {path} ({exc}); rebuilding",
                  flush=True)

    for result in results:
        existing[result.source_id] = result.as_manifest_entry()

    # A source that just succeeded is no longer failing.
    refreshed = {r.source_id for r in results}
    for name, err in failures:
        previous_failures[name] = {"source": name, "error": err}
    for name in list(previous_failures):
        if name in refreshed:
            del previous_failures[name]

    manifest = {
        "snapshot_at": datetime.now(UTC).isoformat(),
        "sources": sorted(existing.values(), key=lambda e: e["source_id"]),
        "failures": sorted(previous_failures.values(), key=lambda f: f["source"]),
    }
    path.write_text(json.dumps(manifest, indent=2))


def load_manifest(dest_dir: Path) -> dict:
    path = dest_dir / MANIFEST_NAME
    if not path.exists():
        raise FileNotFoundError(
            f"no snapshot manifest at {path}. Run: uv run nullsignal snapshot"
        )
    return json.loads(path.read_text())
