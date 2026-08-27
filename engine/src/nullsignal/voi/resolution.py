"""What a check would let you say, as opposed to what it would let you do.

`evpi` ranks checks by expected decision value: how much a result would change
whether an operator holds, advises or dispatches. That is the right question
for a tract whose risk is uncertain, and the wrong one for a tract that cannot
be called at all.

The two come apart badly. In a tract blinded by a missing transit feed, the
highest-VOI check is confirming the cooling centre -- worth doing, and it
cannot lift the evidence ceiling, so the tract stays UNKNOWN whatever it finds.
The checks that *would* lift it score a VOI of exactly zero, because knowing
mobility does not change the action from what the posterior already implies.

This project's whole claim is that risk and evidence sufficiency are orthogonal
axes. Ranking verification on decision value alone quietly collapses them
again, and sends a crew to spend twenty minutes on a question that cannot
resolve the thing that is actually blocking the call.

So a check is also scored by what it resolves: re-run the assessment with the
check's result standing in as evidence, at the accuracy the catalogue already
claims for it, and see what the tract becomes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..inference.evidence import ZoneEvidence
from ..types import DecisionState, Reliability, ZoneAssessment
from .actions import ACTIONS, VerificationAction

# The feed each check stands in for. A check is not a new sensor: calling
# transit control answers the question the realtime feed would have answered,
# so it substitutes for that feed rather than adding a source beside it.
SUBSTITUTES_FOR: dict[str, str | None] = {
    "call_transit_ops": "gtfs_rt",
    "alternate_transit_feed": "gtfs_rt",
    "resident_callback": "311",
    # Direct observation of the tract: it answers for everything.
    "field_inspection": "*",
    # About whether the mitigation exists, not about any feed. It can change
    # what you would do and cannot restore what you cannot see.
    "cooling_centre_check": None,
}


@dataclass(frozen=True, slots=True)
class Resolution:
    """What one check would leave the tract as, if it came back clear."""

    action: VerificationAction
    state: DecisionState
    sufficiency: float
    risk: float

    @property
    def resolves(self) -> bool:
        return self.state is not DecisionState.UNKNOWN


def evaluate(
    evidence: ZoneEvidence,
    action: VerificationAction,
    *,
    assess,
) -> Resolution:
    """Re-assess the tract as though `action` had been carried out and found
    nothing wrong.

    Modelled as evidence rather than as an adjustment to the score: the
    substituted source is set to the accuracy the action already declares, and
    the ordinary assessment runs over it. Nothing here invents a number, and
    every term -- ceiling, coverage, entropy, contradiction -- responds the way
    it would to any other evidence.
    """
    after = _with_result(evidence, action)
    result = assess(after, rank_checks=False)
    return Resolution(
        action=action,
        state=result.state,
        sufficiency=round(result.sufficiency.score, 4),
        risk=round(result.risk, 4),
    )


def cheapest_resolving(
    evidence: ZoneEvidence,
    *,
    assess,
    actions: tuple[VerificationAction, ...] = ACTIONS,
) -> Resolution | None:
    """The fastest check that would let this tract be called at all.

    Ordered by latency rather than by cost: a duty officer is rationing a
    shift, and three minutes that settles the question beats fifty-five that
    settles it better.
    """
    resolving = [
        resolution for resolution in
        (evaluate(evidence, action, assess=assess) for action in actions)
        if resolution.resolves
    ]
    if not resolving:
        return None
    return min(resolving, key=lambda r: (r.action.latency_minutes, r.action.cost))


def _with_result(evidence: ZoneEvidence, action: VerificationAction) -> ZoneEvidence:
    substitute = SUBSTITUTES_FOR.get(action.key)
    if substitute is None:
        return evidence

    verified = Reliability(
        freshness=1.0, coverage=1.0, liveness=1.0, accuracy=action.accuracy,
    )
    reliability = dict(evidence.source_reliability)
    if substitute == "*":
        reliability = {name: verified for name in reliability}
    else:
        reliability[substitute] = verified

    updated = replace(evidence, source_reliability=reliability)
    # "Came back clear" means the thing it asked about is not happening.
    if substitute in ("gtfs_rt", "*"):
        updated = replace(updated, transit_alerts=0)
    return updated


def unresolvable(assessment: ZoneAssessment) -> bool:
    """True when no check in the catalogue can lift this tract's ceiling."""
    return assessment.state is DecisionState.UNKNOWN
