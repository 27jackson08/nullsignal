"""Exact posterior update over the joint hypothesis space.

Eight hypotheses means the posterior can be computed by enumeration -- no
sampling, no approximation, and every number in the result traceable to a
prior, a likelihood table entry and a reliability score. For a system whose
whole claim is that its reasoning can be inspected, that matters more than
supporting a larger space would.
"""
from __future__ import annotations

from math import log

from .hypotheses import HYPOTHESES, Hypothesis
from .likelihood import Observations, likelihood


def update(prior: dict[str, float], observations: Observations) -> dict[str, float]:
    """Bayes, once, over every hypothesis."""
    unnormalised = {
        hypothesis.key: prior.get(hypothesis.key, 0.0) * likelihood(observations, hypothesis)
        for hypothesis in HYPOTHESES
    }
    total = sum(unnormalised.values())
    if total <= 0:
        # Every hypothesis was ruled impossible, which means the model is wrong
        # rather than the world is. Falling back to the prior is the honest
        # move: we have learned nothing, so we should not pretend otherwise.
        return dict(prior)
    return {key: value / total for key, value in unnormalised.items()}


def normalised_entropy(posterior: dict[str, float]) -> float:
    """Shannon entropy scaled to 0..1 across the space.

    1 means the evidence has not distinguished between the hypotheses at all;
    0 means it has settled on one.
    """
    if not posterior:
        return 1.0
    size = len(posterior)
    if size <= 1:
        return 0.0

    entropy = -sum(p * log(p) for p in posterior.values() if p > 0)
    return max(0.0, min(1.0, entropy / log(size)))


def confidence(posterior: dict[str, float]) -> float:
    """The sufficiency term: how far the evidence has narrowed things down."""
    return 1.0 - normalised_entropy(posterior)


def most_likely(posterior: dict[str, float]) -> tuple[str, float]:
    if not posterior:
        return "", 0.0
    key = max(posterior, key=lambda k: posterior[k])
    return key, posterior[key]


def kl_divergence(posterior: dict[str, float], prior: dict[str, float]) -> float:
    """How far the evidence moved us. Used to assert that unreliable
    observations leave the prior alone."""
    total = 0.0
    for key, p in posterior.items():
        q = prior.get(key, 0.0)
        if p > 0 and q > 0:
            total += p * log(p / q)
    return max(0.0, total)


def describe(posterior: dict[str, float], limit: int = 4) -> tuple[tuple[str, float], ...]:
    ranked = sorted(posterior.items(), key=lambda item: -item[1])
    return tuple(ranked[:limit])
