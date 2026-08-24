"""NYC Open Data (Socrata) adapters.

Both datasets used here are keyless. An app token raises rate limits but is not
required at snapshot volumes, so the demo has no credential to leak or expire.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .base import DEFAULT_TIMEOUT, USER_AGENT, FetchResult, SourceFetchError, write_json

SOCRATA_HOST = "https://data.cityofnewyork.us"

# 2020 Census Tracts. Carries `geoid`, the 11-digit FIPS that joins directly to
# the CDC SVI table, plus NTA neighbourhood names for human-readable labels.
TRACTS_DATASET = "63ge-mke6"

# 311 Service Requests -- the reporting-propensity signal.
SERVICE_REQUESTS_DATASET = "erm2-nwe9"

PAGE_SIZE = 50_000


def _paged_get(dataset: str, params: dict, *, max_records: int) -> list[dict]:
    """Page through a Socrata resource until exhausted or max_records reached."""
    collected: list[dict] = []
    with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        while len(collected) < max_records:
            page = dict(params)
            page["$limit"] = min(PAGE_SIZE, max_records - len(collected))
            page["$offset"] = len(collected)
            try:
                response = client.get(
                    f"{SOCRATA_HOST}/resource/{dataset}.json",
                    params=page,
                    headers={"User-Agent": USER_AGENT},
                )
            except httpx.HTTPError as exc:
                raise SourceFetchError(f"socrata {dataset}: {exc}") from exc

            if response.status_code != 200:
                raise SourceFetchError(
                    f"socrata {dataset}: HTTP {response.status_code} "
                    f"({response.text[:180]})"
                )

            batch = response.json()
            if not batch:
                break
            collected.extend(batch)
            if len(batch) < page["$limit"]:
                break
    return collected


def fetch_tracts(dest_dir: Path) -> FetchResult:
    """All 2,325 NYC census tracts with MultiPolygon geometry."""
    rows = _paged_get(TRACTS_DATASET, {}, max_records=5_000)
    if not rows:
        raise SourceFetchError("socrata tracts: empty response")
    return write_json("nyc_tracts", rows, dest_dir / "nyc_tracts.json",
                      note=f"{len(rows)} tracts")


def fetch_service_requests(dest_dir: Path, *, days: int, max_records: int) -> FetchResult:
    """Recent geocoded 311 requests.

    Geocoded rows only: the ~1% without coordinates cannot be assigned to a
    tract, and silently dropping them later would be exactly the kind of
    invisible data loss this project is about.

    The window is pinned to an explicit literal rather than a relative
    expression. This endpoint rejects `now() - interval`, and a fixed cutoff is
    what makes a snapshot reproducible in the first place.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    params = {
        "$where": f"created_date > '{cutoff}' AND latitude IS NOT NULL",
        "$select": "unique_key,created_date,complaint_type,descriptor,"
                   "latitude,longitude,borough,agency",
        "$order": "created_date DESC",
    }
    rows = _paged_get(SERVICE_REQUESTS_DATASET, params, max_records=max_records)
    if not rows:
        raise SourceFetchError("socrata 311: empty response")
    return write_json("311", rows, dest_dir / "311_requests.json",
                      note=f"{len(rows)} geocoded requests since {cutoff}")
