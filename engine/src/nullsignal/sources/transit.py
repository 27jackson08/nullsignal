"""MTA GTFS-Realtime.

Keyless as of 2026-08. Each feed is stored as raw protobuf plus a decoded
summary; the raw bytes matter because their hash is what the flatline detector
compares across polls to catch a feed that is up but frozen.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from google.transit import gtfs_realtime_pb2

from .base import FetchResult, fetch_to_file, write_json

MTA_FEED_BASE = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2F"

# Subway feeds, grouped as the MTA publishes them.
FEEDS = {
    "ace": "gtfs-ace",
    "bdfm": "gtfs-bdfm",
    "g": "gtfs-g",
    "jz": "gtfs-jz",
    "nqrw": "gtfs-nqrw",
    "l": "gtfs-l",
    "numeric": "gtfs",
}


def fetch_realtime(dest_dir: Path) -> list[FetchResult]:
    """Snapshot every subway feed. One failing feed must not abort the rest --
    a partial snapshot is legitimate evidence, and hiding it would be the very
    failure mode this system detects."""
    results: list[FetchResult] = []
    summaries: list[dict] = []

    for name, path in FEEDS.items():
        raw_dest = dest_dir / "gtfs_rt" / f"{name}.pb"
        try:
            result = fetch_to_file(f"gtfs_rt:{name}", f"{MTA_FEED_BASE}{path}", raw_dest)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            summaries.append({"feed": name, "ok": False, "error": str(exc)[:200]})
            continue

        results.append(result)
        summaries.append({"feed": name, "ok": True, **_summarise(raw_dest, result)})

    if not results:
        from .base import SourceFetchError
        raise SourceFetchError("gtfs_rt: every subway feed failed")

    results.append(
        write_json("gtfs_rt_summary", summaries, dest_dir / "gtfs_rt_summary.json",
                   note=f"{len(results)}/{len(FEEDS)} feeds ok")
    )
    return results


def _summarise(raw_path: Path, result: FetchResult) -> dict:
    """Decode enough of the protobuf to know whether the feed is really moving."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(raw_path.read_bytes())

    header_epoch = feed.header.timestamp
    header_time = (
        datetime.fromtimestamp(header_epoch, UTC).isoformat() if header_epoch else None
    )
    age_seconds = (
        (datetime.now(UTC) - datetime.fromtimestamp(header_epoch, UTC)).total_seconds()
        if header_epoch else None
    )

    trip_updates = sum(1 for e in feed.entity if e.HasField("trip_update"))
    alerts = sum(1 for e in feed.entity if e.HasField("alert"))

    return {
        "content_hash": result.content_hash,
        "byte_count": result.byte_count,
        "header_timestamp": header_time,
        "feed_age_seconds": age_seconds,
        "entity_count": len(feed.entity),
        "trip_updates": trip_updates,
        "alerts": alerts,
    }
