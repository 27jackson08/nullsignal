"""Load a snapshot into per-zone evidence, then run both engines over it.

Both engines receive the identical ZoneEvidence objects, so any difference in
the scoreboard is attributable to reasoning rather than to inputs.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from .. import config
from ..heat import heat_index_f
from ..store import connect
from ..types import Reliability, Zone
from .evidence import ZoneEvidence

# 311 has no per-tract heartbeat, so freshness decays over a window long enough
# that an ordinary quiet week does not read as a dead feed.
REPORT_FRESHNESS_HORIZON = timedelta(days=7)


def load_evidence(db_path: Path, *, observed_at: datetime | None = None) -> list[ZoneEvidence]:
    now = observed_at or datetime.now(UTC)
    con = connect(db_path, read_only=True)
    try:
        rows = con.execute(
            """
            SELECT
                z.geoid, z.neighbourhood, z.borough, z.population,
                z.svi_overall, z.pct_no_vehicle, z.pct_age_65_plus,
                z.pct_limited_english, z.pct_poverty, z.pct_minority,
                COALESCE(r.report_count, 0)      AS report_count,
                r.latest_report_at,
                w.temperature_f, w.relative_humidity,
                f.feed_age_seconds, f.alerts
            FROM zones z
            LEFT JOIN reports_by_zone r USING (geoid)
            LEFT JOIN (
                SELECT borough,
                       MAX(temperature_f)                                  AS temperature_f,
                       AVG(relative_humidity)                              AS relative_humidity
                FROM weather_forecast
                WHERE valid_at BETWEEN now() AND now() + INTERVAL 24 HOUR
                GROUP BY borough
            ) w ON w.borough = z.borough
            LEFT JOIN (
                SELECT AVG(feed_age_seconds) AS feed_age_seconds,
                       SUM(alerts)           AS alerts
                FROM feed_health WHERE ok
            ) f ON TRUE
            """
        ).fetchall()
    finally:
        con.close()

    return [_to_evidence(row, now) for row in rows]


def _to_evidence(row: tuple, now: datetime) -> ZoneEvidence:
    (geoid, neighbourhood, borough, population, svi, no_veh, age65,
     limeng, poverty, minority, report_count, latest_report_at,
     temp_f, humidity, feed_age, alerts) = row

    zone = Zone(
        geoid=geoid,
        name=neighbourhood or "Unnamed tract",
        borough=borough or "Unknown",
        population=int(population or 0),
        svi_overall=svi,
        pct_no_vehicle=no_veh,
        pct_age_65_plus=age65,
        pct_limited_english=limeng,
        pct_poverty=poverty,
        pct_minority=minority,
    )

    latest = _as_utc(latest_report_at)
    return ZoneEvidence(
        zone=zone,
        report_count=int(report_count or 0),
        latest_report_at=latest,
        heat_index_f=heat_index_f(temp_f, humidity),
        transit_feed_age_seconds=feed_age,
        transit_alerts=int(alerts or 0),
        source_reliability=_reliability(zone, latest, temp_f, feed_age, now),
        observed_at=now,
    )


def _reliability(
    zone: Zone,
    latest_report_at: datetime | None,
    temperature_f: float | None,
    feed_age_seconds: float | None,
    now: datetime,
) -> dict[str, Reliability]:
    """Day 1 reliability. Freshness and coverage are real; liveness is a
    placeholder until the silent-failure detectors land on day 2."""
    return {
        "311": Reliability(
            freshness=_decay(
                (now - latest_report_at).total_seconds() if latest_report_at else None,
                REPORT_FRESHNESS_HORIZON.total_seconds(),
            ),
            coverage=1.0 if latest_report_at else 0.0,
        ),
        "nws": Reliability(
            freshness=1.0 if temperature_f is not None else 0.0,
            coverage=1.0 if temperature_f is not None else 0.0,
        ),
        "gtfs_rt": Reliability(
            freshness=_decay(feed_age_seconds,
                             config.SOURCE_CADENCE_SECONDS["gtfs_rt"] * 20),
            coverage=1.0 if feed_age_seconds is not None else 0.0,
        ),
        # The vulnerability layer itself has holes. CDC suppresses estimates for
        # small-population tracts, so for those we do not know who lives there
        # or how exposed they are -- which must lower sufficiency, not be
        # rounded to "average" and forgotten.
        "cdc_svi": Reliability(
            freshness=1.0 if zone.svi_overall is not None else 0.0,
            coverage=1.0 if zone.svi_overall is not None else 0.0,
        ),
    }


def _decay(age_seconds: float | None, horizon_seconds: float) -> float:
    if age_seconds is None:
        return 0.0
    from math import exp
    return max(0.0, min(1.0, exp(-max(age_seconds, 0.0) / horizon_seconds)))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)
