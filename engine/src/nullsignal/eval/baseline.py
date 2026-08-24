"""The baseline engine: a conventional threshold dashboard.

This is deliberately not a straw man. It is a faithful implementation of how
monitoring dashboards actually decide -- thresholds on report volume and sensor
readings -- and it is the thing NullSignal has to beat on the scoreboard. A
baseline rigged to look stupid would make the comparison worthless.

Its defining weakness is structural, not a matter of tuning: it has no
representation for "not enough evidence". Every zone it sees comes back either
safe or unsafe, because two-valued output is all a threshold can produce.
Silence therefore resolves to safe, every time, by construction. Calibrating it
well makes that point sharper, not weaker.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import quantiles

from ..inference.evidence import ZoneEvidence
from ..types import DecisionState, Sufficiency, ZoneAssessment

# Real operations teams tune alerting to a workable caseload. A dashboard that
# lit up three quarters of the city would be turned off within a week, so the
# report threshold is calibrated to the top decile rather than fixed.
REPORT_ALERT_PERCENTILE = 90

# NWS issues heat advisories around this heat index.
HEAT_ALERT_THRESHOLD_F = 95.0

# Used only when a distribution is unavailable (single-zone unit tests).
FALLBACK_REPORT_THRESHOLD = 40


@dataclass(frozen=True, slots=True)
class BaselineThresholds:
    report_count: float
    heat_index_f: float = HEAT_ALERT_THRESHOLD_F


def calibrate(evidence: list[ZoneEvidence]) -> BaselineThresholds:
    """Set the report threshold from the observed distribution.

    An absolute count cannot transfer between cities, or even between seasons:
    at a fixed threshold of 40 reports, 77% of NYC tracts alert simultaneously.
    """
    counts = [item.report_count for item in evidence if item.zone.population > 0]
    if len(counts) < 10:
        return BaselineThresholds(report_count=FALLBACK_REPORT_THRESHOLD)

    cutoffs = quantiles(counts, n=100, method="inclusive")
    return BaselineThresholds(report_count=cutoffs[REPORT_ALERT_PERCENTILE - 1])


def assess(
    evidence: ZoneEvidence,
    thresholds: BaselineThresholds | None = None,
) -> ZoneAssessment:
    """Threshold logic. Note there is no branch that can return UNKNOWN."""
    limits = thresholds or BaselineThresholds(report_count=FALLBACK_REPORT_THRESHOLD)

    reports_are_elevated = evidence.report_count >= limits.report_count
    heat_is_elevated = (
        evidence.heat_index_f is not None
        and evidence.heat_index_f >= limits.heat_index_f
    )
    is_alerting = reports_are_elevated or heat_is_elevated

    # A dashboard reports confidence it has not earned: thresholds are
    # deterministic, so the output always looks certain regardless of what
    # evidence was actually available to produce it.
    return ZoneAssessment(
        geoid=evidence.zone.geoid,
        risk=1.0 if is_alerting else 0.0,
        sufficiency=Sufficiency(entropy=1.0, coverage=1.0, contradiction=1.0,
                                staleness=1.0),
        state=DecisionState.CONFIRMED_HIGH if is_alerting else DecisionState.CONFIRMED_LOW,
        posterior={},
        contributing={},
        contradictions=(),
    )
