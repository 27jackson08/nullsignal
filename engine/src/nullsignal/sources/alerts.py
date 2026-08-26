"""NWS active watches, warnings and advisories.

An independent read on the same hazard the forecast describes, issued by a
different process. That independence is the point: cross-station agreement
compares thermometers to each other and climatology compares them to history,
but neither notices when a forecast is wrong in a way a *human forecaster*
would have caught. An official heat advisory is that check.

The interesting state is usually the empty one. Most days there are no alerts,
and that is unremarkable -- but "our data says extreme heat and the weather
service has issued nothing" is a genuine contradiction, and it is only visible
because the absence is recorded rather than skipped.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from .base import DEFAULT_TIMEOUT, USER_AGENT, FetchResult, SourceFetchError, write_json

ALERTS_URL = "https://api.weather.gov/alerts/active"
AREA = "NY"

# Event names that bear on heat exposure. Matched loosely because the wording
# varies by office and season.
HEAT_EVENTS = ("heat", "excessive heat", "warm")


def fetch_alerts(dest_dir: Path) -> FetchResult:
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
            response = client.get(ALERTS_URL, params={"area": AREA},
                                  headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        raise SourceFetchError(f"alerts: request failed: {exc}") from exc

    if response.status_code != 200:
        raise SourceFetchError(
            f"alerts: HTTP {response.status_code} ({response.text[:160]})")

    records = []
    for feature in response.json().get("features", []):
        properties = feature.get("properties") or {}
        event = (properties.get("event") or "").strip()
        records.append({
            "event": event,
            "severity": properties.get("severity", ""),
            "urgency": properties.get("urgency", ""),
            "certainty": properties.get("certainty", ""),
            "area": properties.get("areaDesc", ""),
            "onset": properties.get("onset") or properties.get("effective") or "",
            "expires": properties.get("expires") or "",
            "is_heat": any(term in event.lower() for term in HEAT_EVENTS),
        })

    # An empty list is a real observation, not a failure. Recording it is what
    # lets "extreme heat, and no advisory issued" become a contradiction later.
    heat = sum(1 for r in records if r["is_heat"])
    return write_json(
        "nws_alerts", records, dest_dir / "nws_alerts.json",
        note=f"{len(records)} active alerts in {AREA}, {heat} heat-related",
    )
