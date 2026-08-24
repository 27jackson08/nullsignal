"""MTA GTFS static -- station locations.

Realtime tells us how transit is behaving; static tells us where transit
*exists*. Without it there is no way to say whether a tract is somewhere the
realtime feed could ever have informed us about.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from .base import FetchResult, SourceFetchError, fetch_to_file, write_json

GTFS_SUBWAY_URL = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"

# location_type 1 marks a parent station; the children are individual platforms.
# Counting platforms would triple-count a single station's coverage.
PARENT_STATION = "1"


def fetch_stations(dest_dir: Path) -> list[FetchResult]:
    archive = fetch_to_file("gtfs_static", GTFS_SUBWAY_URL,
                            dest_dir / "gtfs_subway.zip",
                            note="MTA subway GTFS static")
    stations = _extract_stations(archive.path)
    if not stations:
        raise SourceFetchError("gtfs_static: no parent stations found in stops.txt")

    return [
        archive,
        write_json("gtfs_stations", stations, dest_dir / "gtfs_stations.json",
                   note=f"{len(stations)} parent stations"),
    ]


def _extract_stations(archive_path: Path) -> list[dict]:
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open("stops.txt") as handle:
            reader = csv.DictReader(io.TextIOWrapper(handle, "utf-8-sig"))
            rows = list(reader)

    stations: list[dict] = []
    for row in rows:
        if row.get("location_type") != PARENT_STATION:
            continue
        try:
            latitude = float(row["stop_lat"])
            longitude = float(row["stop_lon"])
        except (KeyError, TypeError, ValueError):
            continue
        stations.append({
            "stop_id": row.get("stop_id"),
            "stop_name": row.get("stop_name"),
            "latitude": latitude,
            "longitude": longitude,
        })
    return stations
