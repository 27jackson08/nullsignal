"""Repeated polling of volatile feeds.

The snapshot captures one moment; this captures change over time, which is the
only thing that distinguishes a live feed from a frozen one.
"""
from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from google.transit import gtfs_realtime_pb2

from ..reliability.observations import Observation, append, now_iso
from .base import DEFAULT_TIMEOUT, USER_AGENT
from .transit import FEEDS, MTA_FEED_BASE
from .weather import BOROUGH_CENTROIDS, NWS_HOST

DEFAULT_ROUNDS = 1
DEFAULT_INTERVAL_SECONDS = 30


def run_poll(
    raw_dir: Path,
    *,
    rounds: int = DEFAULT_ROUNDS,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    quiet: bool = False,
) -> list[Observation]:
    """Poll every volatile feed `rounds` times, appending each result."""
    collected: list[Observation] = []

    with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        for round_number in range(1, rounds + 1):
            if not quiet:
                print(f"  round {round_number}/{rounds}", flush=True)

            for observation in _poll_once(client):
                append(raw_dir, observation)
                collected.append(observation)
                if not quiet:
                    print(f"    {observation.source_id:20} {observation.content_hash} "
                          f"{observation.byte_count:>8,}B  {observation.note}", flush=True)

            if round_number < rounds:
                time.sleep(interval_seconds)

    return collected


def _poll_once(client: httpx.Client) -> list[Observation]:
    return [*_poll_transit(client), *_poll_weather(client)]


def _poll_transit(client: httpx.Client) -> list[Observation]:
    observations: list[Observation] = []

    for name, path in FEEDS.items():
        source_id = f"gtfs_rt:{name}"
        try:
            response = client.get(f"{MTA_FEED_BASE}{path}",
                                  headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as exc:
            # A failed poll is itself an observation. Dropping it would hide
            # precisely the outage this system exists to notice.
            observations.append(Observation(
                source_id=source_id, polled_at=now_iso(), http_status=0,
                content_hash="", byte_count=0, note=f"request failed: {exc}"[:120],
            ))
            continue

        payload = response.content
        feed_timestamp, entity_count = _decode_header(payload)

        observations.append(Observation(
            source_id=source_id,
            polled_at=now_iso(),
            http_status=response.status_code,
            content_hash=hashlib.sha256(payload).hexdigest()[:16],
            byte_count=len(payload),
            feed_timestamp=feed_timestamp,
            entity_count=entity_count,
            # Entity count is the sensor-like scalar here: it should drift as
            # trains enter and leave the feed, so a pinned value is suspicious.
            numeric_value=float(entity_count) if entity_count is not None else None,
            note=f"{entity_count} entities" if entity_count is not None else "undecodable",
        ))

    return observations


def _decode_header(payload: bytes) -> tuple[str | None, int | None]:
    if not payload:
        return None, None
    try:
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(payload)
    except Exception:  # noqa: BLE001 - malformed protobuf is a real observation
        return None, None

    epoch = feed.header.timestamp
    stamp = datetime.fromtimestamp(epoch, UTC).isoformat() if epoch else None
    return stamp, len(feed.entity)


def _poll_weather(client: httpx.Client) -> list[Observation]:
    """One representative gridpoint. Heat is a regional field, so polling all
    five boroughs every round would add cost without adding signal."""
    latitude, longitude = BOROUGH_CENTROIDS["Manhattan"]
    source_id = "nws"
    headers = {"User-Agent": USER_AGENT}

    try:
        point = client.get(f"{NWS_HOST}/points/{latitude},{longitude}", headers=headers)
        if point.status_code != 200:
            return [Observation(source_id=source_id, polled_at=now_iso(),
                                http_status=point.status_code, content_hash="",
                                byte_count=0, note="points lookup failed")]
        response = client.get(point.json()["properties"]["forecastHourly"], headers=headers)
    # TypeError included deliberately: an upstream returning an unexpected JSON
    # shape subscripts None, and without it one malformed weather response
    # aborted the whole poll round -- losing that round's transit observations
    # too, which is far worse than a single missing reading.
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        return [Observation(source_id=source_id, polled_at=now_iso(), http_status=0,
                            content_hash="", byte_count=0,
                            note=f"request failed: {exc}"[:120])]

    payload = response.content
    updated, temperature = None, None
    try:
        properties = response.json()["properties"]
        updated = properties.get("updated") or properties.get("updateTime")
        temperature = float(properties["periods"][0]["temperature"])
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        # An unreadable forecast is still an observation: we polled, it
        # answered, and what came back was not usable.
        pass

    return [Observation(
        source_id=source_id,
        polled_at=now_iso(),
        http_status=response.status_code,
        content_hash=hashlib.sha256(payload).hexdigest()[:16],
        byte_count=len(payload),
        feed_timestamp=updated,
        numeric_value=temperature,
        note=f"{temperature}F next hour" if temperature is not None else "no reading",
    )]
