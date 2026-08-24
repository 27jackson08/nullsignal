"""National Weather Service.

Keyless, but api.weather.gov returns 403 without a contact in the User-Agent.
That header lives in sources.base and is easy to lose in a refactor -- if this
adapter starts 403ing, check there first.

Fetching per-tract would mean 2,325 grid lookups. Heat is a regional field, so
one gridpoint per borough is the right resolution and tracts interpolate.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from .base import (
    DEFAULT_TIMEOUT,
    USER_AGENT,
    FetchResult,
    SourceFetchError,
    write_json,
)

NWS_HOST = "https://api.weather.gov"

BOROUGH_CENTROIDS = {
    "Manhattan": (40.7831, -73.9712),
    "Brooklyn": (40.6782, -73.9442),
    "Queens": (40.7282, -73.7949),
    "Bronx": (40.8448, -73.8648),
    "Staten Island": (40.5795, -74.1502),
}


def fetch_forecasts(dest_dir: Path) -> FetchResult:
    """Hourly forecast per borough, resolved through the /points lookup."""
    records: list[dict] = []
    headers = {"User-Agent": USER_AGENT}

    with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        for borough, (lat, lon) in BOROUGH_CENTROIDS.items():
            point = client.get(f"{NWS_HOST}/points/{lat},{lon}", headers=headers)
            if point.status_code == 403:
                raise SourceFetchError(
                    "nws: 403 -- api.weather.gov requires a contact in the "
                    "User-Agent header (see sources/base.py USER_AGENT)"
                )
            if point.status_code != 200:
                raise SourceFetchError(f"nws points {borough}: HTTP {point.status_code}")

            forecast_url = point.json()["properties"]["forecastHourly"]
            hourly = client.get(forecast_url, headers=headers)
            if hourly.status_code != 200:
                raise SourceFetchError(f"nws hourly {borough}: HTTP {hourly.status_code}")

            periods = hourly.json()["properties"]["periods"]
            for period in periods[:48]:
                records.append({
                    "borough": borough,
                    "start_time": period["startTime"],
                    "temperature_f": period["temperature"],
                    "relative_humidity": (period.get("relativeHumidity") or {}).get("value"),
                    "short_forecast": period.get("shortForecast"),
                })

    if not records:
        raise SourceFetchError("nws: no forecast periods returned")
    return write_json("nws", records, dest_dir / "nws_forecast.json",
                      note=f"{len(records)} hourly periods across 5 boroughs")
