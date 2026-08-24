"""Assemble per-zone evidence from the store.

Everything the engines see about a zone arrives through this shape, so the
NullSignal engine and the baseline engine are judged on identical inputs. Any
advantage NullSignal shows in the scoreboard therefore comes from reasoning,
not from privileged data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .. import config
from ..bias.propensity import Propensity
from ..types import Reliability, Zone

# Sources we expect to inform a heat/transit decision for every zone. Coverage
# is measured against this list, so a zone missing any of them is, by
# definition, less decidable -- not safer.
EXPECTED_SOURCES = ("311", "nws", "gtfs_rt", "cdc_svi")


@dataclass(frozen=True, slots=True)
class ZoneEvidence:
    """Raw, uninterpreted evidence for one zone at one tick."""

    zone: Zone
    report_count: int
    recent_report_count: int
    report_window_hours: float
    latest_report_at: datetime | None
    heat_index_f: float | None
    transit_feed_age_seconds: float | None
    transit_alerts: int
    source_reliability: dict[str, Reliability]
    observed_at: datetime
    propensity: Propensity | None = None

    @property
    def present_sources(self) -> tuple[str, ...]:
        return tuple(
            name for name, rel in self.source_reliability.items() if rel.score > 0.0
        )

    @property
    def evidence_coverage(self) -> float:
        """Decision-weighted reliability mass, actual over ideal.

        This is the quantity that makes silence legible: a zone whose
        load-bearing sources are absent has little mass here, so its
        sufficiency falls and it lands in UNKNOWN rather than green.
        """
        weights = config.SOURCE_DECISION_WEIGHT
        ideal = sum(weights.values())
        if ideal <= 0:
            return 0.0
        actual = sum(
            weight * self.source_reliability.get(name, Reliability.absent()).score
            for name, weight in weights.items()
        )
        return min(actual / ideal, 1.0)

    @property
    def reporting_tempo(self) -> float | None:
        """Recent reporting rate against this tract's own longer-run rate.

        Self-normalising on purpose. An absolute "reports per 1,000 residents"
        cut cannot work: the citywide median is 20 per 1,000 over 60 days, so
        any fixed threshold either fires on almost every tract or on none. What
        carries information is a tract going quieter *than itself*.
        """
        if self.report_count <= 0 or self.report_window_hours <= 0:
            return None
        from .. import config as _config
        expected = self.report_count * (
            _config.RECENT_WINDOW_HOURS / self.report_window_hours
        )
        if expected <= 0:
            return None
        return self.recent_report_count / expected

    @property
    def critical_sources(self) -> frozenset[str]:
        """Which sources are decision-critical *for this zone*.

        Transit joins the set only where households lack cars. A tract where
        nearly everyone drives is not endangered by an unobservable subway
        feed; a tract where 80% have no vehicle very much is, because transit
        is how those residents would reach a cooling centre. Treating
        criticality as a fixed property of the source would either over-flag
        car-dependent suburbs or under-flag the people most exposed.
        """
        critical = set(config.ALWAYS_CRITICAL_SOURCES)
        no_vehicle = self.zone.pct_no_vehicle
        if no_vehicle is not None and no_vehicle >= config.TRANSIT_DEPENDENCE_THRESHOLD:
            critical |= config.CONDITIONALLY_CRITICAL_SOURCES
        return frozenset(critical)

    @property
    def missing_critical_sources(self) -> tuple[str, ...]:
        """Sources without which no safe call is defensible for this zone."""
        return tuple(
            sorted(
                name for name in self.critical_sources
                if self.source_reliability.get(name, Reliability.absent()).score <= 0.0
            )
        )

    @property
    def critical_freshness(self) -> float:
        """Freshness of the least-fresh decision-critical source.

        Measured per source against that source's own declared cadence, which
        `Reliability.freshness` already encodes. An earlier version took the
        worst raw *age* across every source against one global horizon; because
        311 has no per-tract heartbeat and goes quiet for days as a matter of
        course, that made almost every tract look stale and conflated "nobody
        reported anything lately" with "the feed is dead" -- two claims this
        system exists precisely to keep apart.
        """
        critical = [
            self.source_reliability.get(name, Reliability.absent()).freshness
            for name in self.critical_sources
        ]
        return min(critical) if critical else 0.0


def utc_now() -> datetime:
    return datetime.now(UTC)
