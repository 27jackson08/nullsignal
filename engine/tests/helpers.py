from __future__ import annotations

from datetime import UTC, datetime



from nullsignal.bias.propensity import Propensity
from nullsignal.inference.evidence import ZoneEvidence
from nullsignal.types import Reliability, Zone

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def make_zone(**overrides) -> Zone:
    defaults = dict(
        geoid="36061000100", name="Test Tract", borough="Manhattan",
        population=4000, svi_overall=0.5, pct_no_vehicle=0.5,
        pct_age_65_plus=0.15, pct_limited_english=0.1,
        pct_poverty=0.2, pct_minority=0.4,
    )
    return Zone(**{**defaults, **overrides})


def make_propensity(index: float = 1.0, *, standard_error: float = 0.1,
                    geoid: str = "36061000100") -> Propensity:
    import math
    return Propensity(geoid=geoid, log_index=math.log(index),
                      standard_error=standard_error, category_count=5,
                      total_reports=100)


def make_evidence(*, zone: Zone | None = None, sources: dict | None = None,
                  heat_index_f: float | None = 95.0, report_count: int = 50,
                  recent_report_count: int | None = None,
                  report_window_hours: float = 1440.0,
                  latest_report_at: datetime | None = None,
                  transit_feed_age_seconds: float | None = 20.0,
                  transit_alerts: int = 0,
                  propensity: Propensity | None = None) -> ZoneEvidence:
    if sources is None:
        sources = {
            "311": Reliability(), "nws": Reliability(),
            "gtfs_rt": Reliability(), "cdc_svi": Reliability(),
        }
    return ZoneEvidence(
        zone=zone or make_zone(),
        report_count=report_count,
        recent_report_count=(recent_report_count if recent_report_count is not None
                             else round(report_count * 48 / 1440)),
        report_window_hours=report_window_hours,
        latest_report_at=latest_report_at if latest_report_at is not None else NOW,
        heat_index_f=heat_index_f,
        transit_feed_age_seconds=transit_feed_age_seconds,
        transit_alerts=transit_alerts,
        source_reliability=sources,
        observed_at=NOW,
        propensity=propensity,
    )


