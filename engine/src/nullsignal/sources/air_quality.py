"""NYC Community Air Survey: chronic air burden by community district.

Ozone earns its place in a heat system: ozone formation is temperature-driven,
so hot days are also bad-air days, and the same residents absorb both.

**This data is an annual mean, and that governs how it may be used.** It is not
evidence about today. Treating a 2024 average as a current reading would be
precisely the error this project exists to prevent -- a stale number wearing
the clothes of a measurement. It therefore informs the *prior* on how much harm
a heat event does to these residents, and never the likelihood of any
observation. There is a test asserting it cannot move the posterior.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from .base import DEFAULT_TIMEOUT, USER_AGENT, FetchResult, SourceFetchError, write_json

SOCRATA_HOST = "https://data.cityofnewyork.us"
DATASET = "c3uy-2p5r"

# Indicators kept. Ozone because heat drives it; PM2.5 because it is the
# standard chronic burden measure and the two do not always coincide.
INDICATORS = {
    "Ozone (O3)": "ozone_ppb",
    "Fine particles (PM 2.5)": "pm25_ugm3",
}

# Community district IDs are borough digit + district number; tracts carry the
# same district as letters. This is the whole crosswalk.
BOROUGH_DIGIT = {"MN": "1", "BX": "2", "BK": "3", "QN": "4", "SI": "5"}


def fetch_air_quality(dest_dir: Path) -> FetchResult:
    """Most recent annual value per community district, per indicator."""
    latest: dict[tuple[str, str], dict] = {}

    with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        for indicator, column in INDICATORS.items():
            response = client.get(
                f"{SOCRATA_HOST}/resource/{DATASET}.json",
                params={
                    "$where": f"name='{indicator}' AND geo_type_name='CD'",
                    "$order": "start_date DESC",
                    "$limit": 5000,
                },
                headers={"User-Agent": USER_AGENT},
            )
            if response.status_code != 200:
                raise SourceFetchError(
                    f"air quality {indicator}: HTTP {response.status_code}")

            for row in response.json():
                district = str(row.get("geo_join_id") or "").strip()
                value = _number(row.get("data_value"))
                if not district or value is None:
                    continue
                # Ordered newest first, so the first sighting wins.
                latest.setdefault((district, column), {
                    "district_id": district,
                    "district_name": row.get("geo_place_name", ""),
                    "indicator": column,
                    "value": value,
                    "period": row.get("time_period", ""),
                })

    if not latest:
        raise SourceFetchError("air quality: no district values returned")

    records = sorted(latest.values(), key=lambda r: (r["indicator"], r["district_id"]))
    periods = sorted({r["period"] for r in records})
    return write_json(
        "air_quality", records, dest_dir / "air_quality.json",
        note=f"{len(records)} district-indicator values, periods {', '.join(periods)}",
    )


def district_id_for(cdta: str | None) -> str | None:
    """Map a tract's community district code ("BK10") to the air survey's
    numeric id ("310")."""
    if not cdta or len(cdta) < 3:
        return None
    digit = BOROUGH_DIGIT.get(cdta[:2].upper())
    if digit is None:
        return None
    try:
        number = int(cdta[2:])
    except ValueError:
        return None
    return f"{digit}{number:02d}"


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
