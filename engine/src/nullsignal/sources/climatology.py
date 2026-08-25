"""Historical weather, reduced to day-of-year normals.

This is the external reference the system otherwise lacks.

Cross-station agreement catches one thermometer drifting away from its
neighbours. It cannot catch a fault that moves *every* station the same way,
because nothing is left to disagree with -- and that case stayed a documented
loss in the scenario suite for exactly that reason. Climatology breaks the tie
from outside: a citywide reading far from what a decade of Augusts says the day
should look like is anomalous no matter how well the stations agree with each
other.

The obvious objection is that weather deviates from normal constantly -- that
is what weather is. So the threshold is set from the observed spread rather
than picked, and it is deliberately loose. This detector exists to catch an
instrument reading impossibly, not a day being unusual.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

import httpx

from .base import DEFAULT_TIMEOUT, FetchResult, SourceFetchError, write_json

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# One representative point for the city. Climatology is a regional quantity and
# the five borough gridpoints differ by about 2F, well inside the spread.
LATITUDE, LONGITUDE = 40.7831, -73.9712

YEARS_OF_HISTORY = 10

# The archive trails real time by about a day. Requesting today returns a 400
# naming the allowed range, so the window stops short of it deliberately rather
# than failing once a day at whatever hour the boundary moves.
ARCHIVE_LAG_DAYS = 5

# Normals are smoothed across a window centred on each day, so a single
# freakish date does not become its own "normal".
SMOOTHING_WINDOW_DAYS = 7


def fetch_normals(dest_dir: Path, *, today: date | None = None) -> FetchResult:
    from datetime import timedelta

    end = (today or date.today()) - timedelta(days=ARCHIVE_LAG_DAYS)
    start = end.replace(year=end.year - YEARS_OF_HISTORY)

    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
            response = client.get(ARCHIVE_URL, params={
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": "temperature_2m_max,temperature_2m_min",
                "temperature_unit": "fahrenheit",
                "timezone": "America/New_York",
            })
    except httpx.HTTPError as exc:
        raise SourceFetchError(f"climatology: request failed: {exc}") from exc

    if response.status_code != 200:
        # The archive states its own allowed range in the body; surfacing it
        # turns a bare 400 into something diagnosable.
        raise SourceFetchError(
            f"climatology: HTTP {response.status_code} ({response.text[:180]})")

    daily = response.json().get("daily") or {}
    normals = _normals(daily.get("time") or [], daily.get("temperature_2m_max") or [])
    if not normals:
        raise SourceFetchError("climatology: no usable history returned")

    return write_json(
        "climatology", normals, dest_dir / "climatology.json",
        note=(f"{len(normals)} day-of-year normals from "
              f"{start.isoformat()} to {end.isoformat()}"),
    )


def _normals(dates: list[str], maxima: list) -> list[dict]:
    """Mean and spread of daily maximum temperature, per day of year."""
    by_day: dict[int, list[float]] = defaultdict(list)
    for stamp, value in zip(dates, maxima):
        if value is None:
            continue
        try:
            day = date.fromisoformat(stamp).timetuple().tm_yday
        except ValueError:
            continue
        by_day[day].append(float(value))

    if not by_day:
        return []

    half = SMOOTHING_WINDOW_DAYS // 2
    normals = []
    for day in sorted(by_day):
        window: list[float] = []
        for offset in range(-half, half + 1):
            neighbour = ((day - 1 + offset) % 366) + 1
            window.extend(by_day.get(neighbour, []))
        if len(window) < 10:
            continue
        normals.append({
            "day_of_year": day,
            "mean_max_f": round(statistics.fmean(window), 2),
            "stdev_f": round(statistics.pstdev(window), 2),
            "samples": len(window),
        })
    return normals
