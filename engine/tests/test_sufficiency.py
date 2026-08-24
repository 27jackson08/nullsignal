"""Sufficiency arithmetic, especially the handling of unmeasured terms."""
from __future__ import annotations

import pytest

from nullsignal import config
from nullsignal.types import Sufficiency


def test_unmeasured_terms_are_excluded_not_assumed_good():
    """A None term must not contribute confidence.

    Regression guard: these terms were briefly set to 1.0 as day-1 placeholders,
    which handed every zone 0.55 of unearned sufficiency -- above the decision
    threshold, so no amount of real missing evidence could reach UNKNOWN.
    """
    placeholder_as_good = Sufficiency(entropy=1.0, coverage=0.0,
                                      contradiction=1.0, staleness=0.0)
    honestly_unmeasured = Sufficiency(entropy=None, coverage=0.0,
                                      contradiction=None, staleness=0.0)

    assert placeholder_as_good.score >= config.SUFFICIENCY_THRESHOLD
    assert honestly_unmeasured.score == 0.0


def test_score_renormalises_over_measured_terms():
    only_coverage = Sufficiency(coverage=0.8)
    assert only_coverage.score == pytest.approx(0.8)


def test_no_measured_terms_scores_zero():
    assert Sufficiency().score == 0.0


def test_ceiling_caps_an_otherwise_perfect_score():
    capped = Sufficiency(entropy=1.0, coverage=1.0, contradiction=1.0,
                         staleness=1.0, ceiling=config.CRITICAL_GAP_CEILING)
    assert capped.score == pytest.approx(config.CRITICAL_GAP_CEILING)
    assert capped.score < config.SUFFICIENCY_THRESHOLD
