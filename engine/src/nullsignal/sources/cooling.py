"""NYC heat-relief infrastructure.

Misting stations and spray showers run by Parks: the outdoor cooling network
people reach on foot during a heatwave.

The reason this source is interesting is not the locations. It is the `status`
column. Of 271 listed cooling sites, 39 are marked broken and 9 were never
activated -- so a system that counts *listed* sites overstates available relief
by about a fifth, and does so invisibly, because a broken misting station looks
exactly like a working one in any dataset that does not read the field.

That is the same failure this project exists to catch, sitting inside the
mitigation we would recommend. Both counts are carried downstream so the gap
between them can be shown rather than averaged away.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from .base import DEFAULT_TIMEOUT, USER_AGENT, FetchResult, SourceFetchError, write_json

SOCRATA_HOST = "https://data.cityofnewyork.us"

# Cool It! NYC.
#
# These two datasets come from the same agency and use the same column names,
# `x` and `y`, in *different coordinate systems*: cooling sites are already
# lon/lat, spray showers are NY State Plane feet (EPSG:2263). Nothing in either
# schema says so. Reading both the same way silently places 755 sites in the
# Gulf of Guinea, which is why the CRS is detected per row rather than assumed
# per dataset.
DATASETS = {
    "cooling_site": "h2bn-gu9k",     # misting stations and cooling features
    "spray_shower": "tzuk-eq2f",     # spray showers
}

# Only this status means a site will actually cool anyone down. Everything else
# -- broken, not yet activated, under construction -- is a site that exists on
# a map and not in the world.
WORKING_STATUS = "Activated"

# NY State Plane Long Island (feet). NYC easting runs roughly 913k-1067k.
STATE_PLANE = "EPSG:2263"
GEOGRAPHIC = "EPSG:4326"
STATE_PLANE_MIN_EASTING = 100_000


def fetch_cooling_sites(dest_dir: Path) -> FetchResult:
    records: list[dict] = []

    with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        for kind, dataset in DATASETS.items():
            response = client.get(
                f"{SOCRATA_HOST}/resource/{dataset}.json",
                params={"$limit": 5000},
                headers={"User-Agent": USER_AGENT},
            )
            if response.status_code != 200:
                raise SourceFetchError(
                    f"cooling {dataset}: HTTP {response.status_code}")

            for row in response.json():
                point = _coordinates(row)
                if point is None:
                    continue
                longitude, latitude, crs = point
                status = (row.get("status") or "").strip()
                records.append({
                    "kind": kind,
                    "name": row.get("propertyname") or row.get("subpropertyname") or "",
                    "borough": row.get("borough") or "",
                    "status": status or "Unknown",
                    "is_working": status == WORKING_STATUS,
                    "x": longitude,
                    "y": latitude,
                    "crs": crs,
                })

    if not records:
        raise SourceFetchError("cooling: no usable sites returned")

    working = sum(1 for r in records if r["is_working"])
    projected = sum(1 for r in records if r["crs"] == STATE_PLANE)
    return write_json(
        "cooling_sites", records, dest_dir / "cooling_sites.json",
        note=(f"{len(records)} sites, {working} working, "
              f"{projected} in state-plane coordinates"),
    )


def _coordinates(row: dict) -> tuple[float, float, str] | None:
    """Coordinates and the system they are in, or None if unplaceable.

    Classified by magnitude rather than trusted from the schema, because the
    schema does not say. A site we cannot locate is dropped rather than
    guessed at: placing heat relief where it is not would be worse than
    admitting we do not know where it is.
    """
    try:
        x = float(row["x"])
        y = float(row["y"])
    except (KeyError, TypeError, ValueError):
        return None

    if abs(x) > STATE_PLANE_MIN_EASTING:
        return x, y, STATE_PLANE
    if -75 < x < -72 and 40 < y < 41.5:
        return x, y, GEOGRAPHIC
    return None
