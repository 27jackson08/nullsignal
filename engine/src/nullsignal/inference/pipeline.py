"""Load a snapshot into per-zone evidence, then run both engines over it.

Both engines receive the identical ZoneEvidence objects, so any difference in
the scoreboard is attributable to reasoning rather than to inputs.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from .. import config
from ..bias.propensity import Propensity, PropensityModel, fit as fit_propensity
from ..heat import heat_index_f
from ..reliability.consistency import apply_to_cohort
from ..reliability.feeds import FeedHealth, assess_feeds
from ..store import connect
from ..types import Reliability, Zone
from .evidence import ZoneEvidence

# 311 has no per-tract heartbeat, so freshness decays over a window long enough
# that an ordinary quiet week does not read as a dead feed.
REPORT_FRESHNESS_HORIZON = timedelta(days=7)


def load_evidence(
    db_path: Path,
    *,
    observed_at: datetime | None = None,
    raw_dir: Path | None = None,
) -> list[ZoneEvidence]:
    now = observed_at or datetime.now(UTC)
    # Feed liveness is a property of the feed, not of any tract, so it is
    # assessed once here and applied to every zone.
    feed_health = assess_feeds(raw_dir, now=now) if raw_dir else {}
    con = connect(db_path, read_only=True)
    try:
        rows = con.execute(
            """
            SELECT
                z.geoid, z.neighbourhood, z.borough, z.population,
                z.svi_overall, z.pct_no_vehicle, z.pct_age_65_plus,
                z.pct_limited_english, z.pct_poverty, z.pct_minority,
                z.transit_coverage,
                COALESCE(r.report_count, 0)          AS report_count,
                COALESCE(r.recent_report_count, 0)   AS recent_report_count,
                COALESCE(r.window_hours, 0)          AS window_hours,
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
        # Propensity is fitted from the whole city at once: a tract's reporting
        # level only means anything relative to comparable tracts.
        category_counts = con.execute(
            "SELECT geoid, category, report_count FROM reports_by_zone_category"
        ).fetchall()
        populations = dict(con.execute(
            "SELECT geoid, COALESCE(population, 0) FROM zones"
        ).fetchall())
    finally:
        con.close()

    propensity_model = fit_propensity(category_counts, populations)

    return apply_to_cohort([
        _to_evidence(row, now, feed_health, propensity_model.get(row[0]))
        for row in rows
    ])


def _to_evidence(
    row: tuple,
    now: datetime,
    feed_health: dict[str, FeedHealth],
    propensity: Propensity | None,
) -> ZoneEvidence:
    (geoid, neighbourhood, borough, population, svi, no_veh, age65,
     limeng, poverty, minority, transit_coverage, report_count,
     recent_report_count, window_hours, latest_report_at,
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
        recent_report_count=int(recent_report_count or 0),
        report_window_hours=float(window_hours or 0),
        latest_report_at=latest,
        heat_index_f=heat_index_f(temp_f, humidity),
        transit_feed_age_seconds=feed_age,
        transit_alerts=int(alerts or 0),
        source_reliability=_reliability(zone, latest, temp_f, feed_age, now,
                                        feed_health, transit_coverage, propensity),
        propensity=propensity,
        observed_at=now,
    )


def _reliability(
    zone: Zone,
    latest_report_at: datetime | None,
    temperature_f: float | None,
    feed_age_seconds: float | None,
    now: datetime,
    feed_health: dict[str, FeedHealth],
    transit_coverage: float | None,
    propensity: Propensity | None,
) -> dict[str, Reliability]:
    """Per-source reliability for one zone.

    Liveness comes from the silent-failure detectors; a source with no poll
    history keeps a liveness of 1.0 rather than being penalised, because the
    cadence check still runs from a single observation and "not yet polled
    repeatedly" is not evidence of a fault.
    """
    def liveness_of(source_id: str) -> float:
        health = feed_health.get(source_id)
        return health.score if health else 1.0
    return {
        "311": Reliability(
            freshness=_decay(
                (now - latest_report_at).total_seconds() if latest_report_at else None,
                REPORT_FRESHNESS_HORIZON.total_seconds(),
            ),
            # Coverage is the tract's evidential weight, not merely whether
            # any report exists. Silence from a tract that rarely calls 311 is
            # close to no information, and must not be banked as reassurance.
            coverage=(propensity.evidential_weight
                      if propensity and propensity.is_estimated
                      else (0.5 if latest_report_at else 0.0)),
            liveness=liveness_of("311"),
        ),
        "nws": Reliability(
            freshness=1.0 if temperature_f is not None else 0.0,
            coverage=1.0 if temperature_f is not None else 0.0,
            liveness=liveness_of("nws"),
        ),
        "gtfs_rt": Reliability(
            freshness=_decay(feed_age_seconds,
                             config.SOURCE_CADENCE_SECONDS["gtfs_rt"] * 20),
            # Fraction of the tract within walking distance of a station:
            # how much of it the realtime feed could ever speak to. A tract at
            # zero is not safe, it is unobserved.
            coverage=(transit_coverage or 0.0) if feed_age_seconds is not None else 0.0,
            liveness=liveness_of("gtfs_rt"),
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
