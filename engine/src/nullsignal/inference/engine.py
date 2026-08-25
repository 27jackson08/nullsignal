"""The NullSignal engine.

Day 1 walking skeleton: coverage and staleness are computed for real, the
posterior-entropy term is a declared stub until the Bayesian layer lands. The
stub is named in STUBBED_TERMS rather than buried, so nobody mistakes a
placeholder for a result.
"""
from __future__ import annotations

from ..claims.extract import extract as extract_claims
from ..claims.graph import build as build_contradiction_graph
from ..claims.types import Subject
from ..decision import decide
from ..types import RecommendedCheck, Sufficiency, ZoneAssessment
from ..voi import evpi
from . import bayes, hypotheses
from .evidence import ZoneEvidence
from .likelihood import Observations

# Every sufficiency term is now backed by real inference.
STUBBED_TERMS: tuple[str, ...] = ()


def assess(evidence: ZoneEvidence, *, rank_checks: bool = True) -> ZoneAssessment:
    """Infer a posterior over the hypothesis space, then apply the 2x2.

    `rank_checks=False` skips the value-of-information pass. Scenario runs
    score tens of thousands of assessments and never read the ranking, and
    enumerating it for each one dominated the runtime.
    """
    claims = extract_claims(evidence, evidence.propensity)
    graph = build_contradiction_graph(claims)

    prior = hypotheses.prior(
        transit_dependence=evidence.zone.pct_no_vehicle,
        vulnerability=evidence.zone.svi_overall,
        cooling_access=evidence.zone.cooling_working,
    )
    posterior = bayes.update(prior, _observations(evidence, claims))

    risk = hypotheses.expected_harm(
        posterior, evidence.zone.vulnerability_multiplier
    )
    sufficiency = Sufficiency(
        entropy=bayes.confidence(posterior),
        coverage=evidence.evidence_coverage,
        contradiction=graph.agreement,
        staleness=_clamp(evidence.critical_freshness),
        ceiling=_ceiling(evidence),
    )
    state = decide(risk, sufficiency.score)

    # Verification is ranked against the same posterior that produced the
    # verdict, scaled by who lives here -- so equity enters the ordering
    # through the arithmetic rather than as a later adjustment.
    harm_scale = evidence.zone.vulnerability_multiplier
    decision, _ = evpi.best_decision(posterior, harm_scale)
    checks = tuple(
        RecommendedCheck(
            key=ranked.action.key,
            label=ranked.action.label,
            value=round(ranked.value, 6),
            value_per_cost=round(ranked.value_per_cost, 4),
            cost=ranked.action.cost,
            latency_minutes=ranked.action.latency_minutes,
            detail=ranked.action.detail,
        )
        for ranked in evpi.rank(posterior, harm_scale=harm_scale)
    ) if rank_checks else ()

    return ZoneAssessment(
        geoid=evidence.zone.geoid,
        risk=risk,
        sufficiency=sufficiency,
        state=state,
        posterior={k: round(v, 6) for k, v in posterior.items()},
        contributing={
            name: rel.score for name, rel in evidence.source_reliability.items()
        },
        contradictions=graph.describe(),
        recommended_checks=checks,
        current_decision=str(decision),
        unresolved_harm=round(
            evpi.unresolved_harm(posterior, sufficiency.score, harm_scale), 6),
        unseen_danger=round(hypotheses.probability_of_unseen_danger(posterior), 6),
    )


def _observations(evidence: ZoneEvidence, claims) -> Observations:
    """Lift evidence into the vocabulary the likelihood tables speak.

    A source with nothing to say passes None, which contributes a factor of 1
    rather than zero: we did not observe it, which is not the same as having
    observed it fail to happen.
    """
    by_subject = {claim.subject: claim for claim in claims}
    heat = by_subject.get(Subject.HEAT_EXPOSURE)
    transit = by_subject.get(Subject.TRANSIT_SERVICE)
    distress = by_subject.get(Subject.POPULATION_DISTRESS)

    return Observations(
        heat_band=heat.value if heat else None,
        heat_reliability=heat.reliability if heat else 0.0,
        transit_signal=transit.value if transit else None,
        transit_reliability=transit.reliability if transit else 0.0,
        distress=distress.value if distress else None,
        distress_reliability=distress.reliability if distress else 0.0,
        critical_liveness=_critical_liveness(evidence),
        missing_critical_count=len(evidence.missing_critical_sources),
    )


def _critical_liveness(evidence: ZoneEvidence) -> float:
    """Liveness of the least-live decision-critical source."""
    scores = [
        evidence.source_reliability[name].liveness
        for name in evidence.critical_sources
        if name in evidence.source_reliability
    ]
    return min(scores) if scores else 1.0


def _ceiling(evidence: ZoneEvidence) -> float:
    from .. import config
    return (config.CRITICAL_GAP_CEILING
            if evidence.missing_critical_sources else 1.0)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
