from __future__ import annotations

from datetime import UTC, datetime



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


def make_evidence(*, zone: Zone | None = None, sources: dict | None = None,
                  heat_index_f: float | None = 95.0, report_count: int = 50,
                  latest_report_at: datetime | None = None,
                  transit_feed_age_seconds: float | None = 20.0) -> ZoneEvidence:
    if sources is None:
        sources = {
            "311": Reliability(), "nws": Reliability(),
            "gtfs_rt": Reliability(), "cdc_svi": Reliability(),
        }
    return ZoneEvidence(
        zone=zone or make_zone(),
        report_count=report_count,
        latest_report_at=latest_report_at if latest_report_at is not None else NOW,
        heat_index_f=heat_index_f,
        transit_feed_age_seconds=transit_feed_age_seconds,
        transit_alerts=0,
        source_reliability=sources,
        observed_at=NOW,
    )


