"""The NullSignal engine.

Day 1 walking skeleton: coverage and staleness are computed for real, the
posterior-entropy term is a declared stub until the Bayesian layer lands. The
stub is named in STUBBED_TERMS rather than buried, so nobody mistakes a
placeholder for a result.
"""
from __future__ import annotations

from .. import config
from ..decision import decide
from ..types import Sufficiency, ZoneAssessment
from .evidence import ZoneEvidence

# Terms not yet backed by real inference. Emptied on day 4.
STUBBED_TERMS = ("entropy",)

# Heat risk ramps between these two heat-index values.
HEAT_ONSET_F = 85.0
HEAT_SEVERE_F = 103.0

# Weighting between hazard exposure and who is exposed to it.
HAZARD_WEIGHT = 0.6
VULNERABILITY_WEIGHT = 0.4


def assess(evidence: ZoneEvidence) -> ZoneAssessment:
    """Produce a risk estimate and a sufficiency score, then apply the 2x2."""
    risk = _risk(evidence)
    sufficiency = _sufficiency(evidence)
    state = decide(risk, sufficiency.score)

    return ZoneAssessment(
        geoid=evidence.zone.geoid,
        risk=risk,
        sufficiency=sufficiency,
        state=state,
        posterior={},
        contributing={
            name: rel.score for name, rel in evidence.source_reliability.items()
        },
        contradictions=(),
    )


def _risk(evidence: ZoneEvidence) -> float:
    """Hazard intensity scaled by who is standing in it.

    Note what is deliberately absent: report volume. Treating more complaints as
    more risk is precisely the bias that makes quiet neighbourhoods look safe,
    so raw report counts never enter the risk estimate. They inform
    *sufficiency* instead.
    """
    hazard = _heat_hazard(evidence.heat_index_f)
    exposure = _exposure(evidence)
    return _clamp(HAZARD_WEIGHT * hazard + VULNERABILITY_WEIGHT * hazard * exposure)


def _heat_hazard(heat_index_f: float | None) -> float:
    if heat_index_f is None:
        return 0.0
    span = HEAT_SEVERE_F - HEAT_ONSET_F
    return _clamp((heat_index_f - HEAT_ONSET_F) / span)


def _exposure(evidence: ZoneEvidence) -> float:
    """Who is harmed by heat plus a stalled transit system: older residents,
    households without a vehicle, and generally vulnerable tracts."""
    zone = evidence.zone
    factors = [
        zone.svi_overall,
        zone.pct_age_65_plus,
        zone.pct_no_vehicle,
    ]
    known = [f for f in factors if f is not None]
    if not known:
        # No vulnerability data is not an argument for low exposure. Assume the
        # population-weighted midpoint rather than zero.
        return 0.5
    return _clamp(sum(known) / len(known))


def _sufficiency(evidence: ZoneEvidence) -> Sufficiency:
    """Only terms this build actually measures are populated.

    entropy (day 4) and contradiction (day 3) stay None rather than 1.0. Set to
    1.0 they would contribute a fixed 0.55 of confidence out of nowhere -- more
    than the decision threshold -- so no amount of genuinely missing evidence
    could ever push a zone into UNKNOWN. A placeholder that reads as evidence
    is the precise bug this project exists to detect, and it is no more
    acceptable here than in a city's dashboard.
    """
    missing_critical = evidence.missing_critical_sources
    return Sufficiency(
        entropy=None,        # day 4
        coverage=evidence.evidence_coverage,
        contradiction=None,  # day 3
        staleness=_staleness_term(evidence),
        ceiling=config.CRITICAL_GAP_CEILING if missing_critical else 1.0,
    )


def _staleness_term(evidence: ZoneEvidence) -> float:
    """How fresh the decision-critical evidence is, worst case."""
    return _clamp(evidence.critical_freshness)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
