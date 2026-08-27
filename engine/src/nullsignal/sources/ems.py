"""Heat-related EMS dispatches, by community district.

A harm signal that owes nothing to 311. Someone calling an ambulance is not
filing a complaint: it does not depend on knowing the 311 number, on speaking
English, or on expecting a response.

**Not strong enough to validate anything against.** It was built hoping to test
the project's own claim -- do the tracts we call blind actually see more heat
emergencies? -- and it cannot answer that. The window yields roughly 286
heat-coded dispatches citywide across 59 usable districts, about five each, and
a difference between districts cannot be resolved from five events. The measure
also fails its own sanity check: heat dispatches correlate *negatively* with
vulnerability (-0.27 per capita, -0.55 as a share of health dispatches), which
is the opposite of what any account of heat mortality predicts, so the coding
is not capturing heat causation either.

It is kept because it is real data honestly described, and deliberately not
read by any assessment: `ems_heat_share` appears nowhere in the inference
layer. Presenting it as corroboration would be the exact move this project
exists to object to.

Aggregated to community district, the same geography the air survey uses, so
both cross to tracts through one crosswalk.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .base import DEFAULT_TIMEOUT, USER_AGENT, FetchResult, SourceFetchError, write_json

SOCRATA_HOST = "https://data.cityofnewyork.us"
DATASET = "76xm-jjuj"

# Dispatch codes that heat drives or worsens. HEAT is literal; the others are
# how heat actually kills -- cardiac and respiratory failure in people already
# at their limit, and collapse mistaken for something else.
HEAT_CODES = ("HEAT",)
COMPOUNDED_CODES = ("CARD", "CARDBR", "RESPIR", "DIFFBR", "UNC", "T-UNC", "SICK")

# The feed trails real time by roughly two months, so the window is generous.
LOOKBACK_DAYS = 120
MAX_RECORDS = 60_000


def fetch_ems(dest_dir: Path) -> FetchResult:
    cutoff = (datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    wanted = set(HEAT_CODES) | set(COMPOUNDED_CODES)
    quoted = ", ".join(f"'{code}'" for code in sorted(wanted))

    rows: list[dict] = []
    with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        offset = 0
        while len(rows) < MAX_RECORDS:
            response = client.get(
                f"{SOCRATA_HOST}/resource/{DATASET}.json",
                params={
                    "$select": "incident_datetime,initial_call_type,communitydistrict,borough",
                    "$where": (f"incident_datetime > '{cutoff}' "
                               f"AND initial_call_type in({quoted})"),
                    "$limit": 50_000,
                    "$offset": offset,
                },
                headers={"User-Agent": USER_AGENT},
            )
            if response.status_code != 200:
                raise SourceFetchError(
                    f"ems: HTTP {response.status_code} ({response.text[:160]})")
            batch = response.json()
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < 50_000:
                break
            offset += len(batch)

    if not rows:
        raise SourceFetchError("ems: no dispatches returned for the window")

    heat_by_district: Counter[str] = Counter()
    all_by_district: Counter[str] = Counter()
    for row in rows:
        district = _district(row.get("communitydistrict"))
        if district is None:
            continue
        all_by_district[district] += 1
        if (row.get("initial_call_type") or "").strip().upper() in HEAT_CODES:
            heat_by_district[district] += 1

    records = [
        {
            "district_id": district,
            "heat_dispatches": heat_by_district.get(district, 0),
            "health_dispatches": count,
        }
        for district, count in sorted(all_by_district.items())
    ]
    total_heat = sum(r["heat_dispatches"] for r in records)
    return write_json(
        "ems_dispatches", records, dest_dir / "ems_dispatches.json",
        note=(f"{len(records)} districts, {total_heat} heat dispatches of "
              f"{len(rows)} health dispatches over {LOOKBACK_DAYS}d"),
    )


def _district(value) -> str | None:
    """Normalise to the three-digit form the air survey uses ("310")."""
    if value is None:
        return None
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return f"{number:03d}" if 100 <= number <= 599 else None
