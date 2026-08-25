"""Exact expected value of information.

With eight hypotheses, three decisions and five candidate checks, the value of
every check can be computed by enumerating every outcome. No sampling and no
approximation: each ranking is reproducible and every number in it can be
traced back to a probability and a cost.

The quantity is the standard one -- how much better our decision gets once we
know what the check would tell us:

    VOI(a) = E_outcome[ max_d U(d | posterior after a) ] - max_d U(d | now)

**VOI answers "which check", not "which zone".** It is deliberately not
monotone in the stakes, and cannot be: information is worth most near a
decision boundary and worth exactly nothing once one response dominates
whatever the answer turns out to be. A tract so obviously dire that crews are
going regardless does not need another phone call.

So ranking zones for attention by VOI would be perverse -- it would rank the
most clear-cut emergencies last. Zone ordering uses `unresolved_harm` below,
which is monotone in both vulnerability and doubt, and that is where equity
enters the ordering.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..inference.hypotheses import Regime, World, _parse, scaled_harm
from .actions import (
    ACTIONS,
    DECISION_COST,
    MITIGATION,
    MOBILITY_BY_WORLD,
    MOBILITY_OUTCOMES,
    Decision,
    Resolves,
    VerificationAction,
)


@dataclass(frozen=True, slots=True)
class RankedAction:
    action: VerificationAction
    value: float              # expected harm averted by knowing the answer
    value_per_cost: float

    @property
    def key(self) -> str:
        return self.action.key


def utility(decision: Decision, world: World, harm_scale: float) -> float:
    """Net outcome of a decision in a world, as a negative quantity.

    Harm not averted is a loss; effort spent is also a loss. Both are on the
    same 0..1 scale via `scaled_harm`, so the costs below can be read directly
    as "how much expected harm this response is worth spending".
    """
    residual = scaled_harm(world, harm_scale) * (1.0 - MITIGATION[decision][world])
    return -(residual + DECISION_COST[decision])


def best_decision(
    posterior: dict[str, float],
    harm_scale: float,
) -> tuple[Decision, float]:
    """The decision with the highest expected utility under a belief."""
    scores = {
        decision: sum(
            probability * utility(decision, _parse(key).world, harm_scale)
            for key, probability in posterior.items()
        )
        for decision in Decision
    }
    choice = max(scores, key=lambda d: scores[d])
    return choice, scores[choice]


def unresolved_harm(
    posterior: dict[str, float],
    sufficiency: float,
    harm_scale: float = 1.0,
) -> float:
    """Expected harm we believe in but have not settled -- how much is riding
    on a question still open.

    This is the quantity for ranking *zones*, and the one that carries equity:
    it rises with vulnerability through the harm scale and with doubt through
    the sufficiency term, so a fragile tract we cannot see clearly outranks a
    robust tract we can. Unlike VOI it is monotone in both, which is what makes
    it usable as a queue.
    """
    from ..inference.hypotheses import expected_harm
    # The vulnerability multiplier is applied *here* and nowhere else. Risk
    # answers "are people in danger", which does not depend on how fragile they
    # are; the queue answers "where should scarce effort go", which does.
    doubt = 1.0 - max(0.0, min(1.0, sufficiency))
    return expected_harm(posterior) * doubt * harm_scale


def rank(
    posterior: dict[str, float],
    *,
    harm_scale: float = 1.0,
    actions: tuple[VerificationAction, ...] = ACTIONS,
) -> tuple[RankedAction, ...]:
    """Every candidate check, ordered by how much harm knowing would avert."""
    _, baseline_utility = best_decision(posterior, harm_scale)

    ranked: list[RankedAction] = []
    for action in actions:
        expected = 0.0
        for outcome, probability in _outcome_distribution(posterior, action).items():
            if probability <= 0:
                continue
            updated = _posterior_given(posterior, action, outcome)
            _, value = best_decision(updated, harm_scale)
            expected += probability * value

        gain = max(0.0, expected - baseline_utility)
        ranked.append(RankedAction(
            action=action,
            value=gain,
            value_per_cost=gain / action.cost if action.cost > 0 else gain,
        ))

    return tuple(sorted(ranked, key=lambda r: -r.value_per_cost))


def _outcomes_for(action: VerificationAction) -> tuple[str, ...]:
    if action.resolves is Resolves.WORLD:
        return tuple(World)
    if action.resolves is Resolves.MOBILITY:
        return MOBILITY_OUTCOMES
    return tuple(Regime)


def _truth_of(key: str, action: VerificationAction) -> str:
    """What this check would see, if it read correctly."""
    hypothesis = _parse(key)
    if action.resolves is Resolves.WORLD:
        return hypothesis.world
    if action.resolves is Resolves.MOBILITY:
        return MOBILITY_BY_WORLD[hypothesis.world]
    return hypothesis.regime


def _read_probability(
    truth: str,
    outcome: str,
    action: VerificationAction,
    outcome_count: int,
) -> float:
    """A check reads the truth with its stated accuracy, and otherwise reads
    one of the remaining possibilities uniformly."""
    if outcome_count <= 1:
        return 1.0
    if truth == outcome:
        return action.accuracy
    return (1.0 - action.accuracy) / (outcome_count - 1)


def _outcome_distribution(
    posterior: dict[str, float],
    action: VerificationAction,
) -> dict[str, float]:
    outcomes = _outcomes_for(action)
    distribution = {outcome: 0.0 for outcome in outcomes}
    for key, probability in posterior.items():
        truth = _truth_of(key, action)
        for outcome in outcomes:
            distribution[outcome] += probability * _read_probability(
                truth, outcome, action, len(outcomes)
            )
    return distribution


def _posterior_given(
    posterior: dict[str, float],
    action: VerificationAction,
    outcome: str,
) -> dict[str, float]:
    outcomes = _outcomes_for(action)
    updated = {
        key: probability * _read_probability(
            _truth_of(key, action), outcome, action, len(outcomes)
        )
        for key, probability in posterior.items()
    }
    total = sum(updated.values())
    if total <= 0:
        return dict(posterior)
    return {key: value / total for key, value in updated.items()}
