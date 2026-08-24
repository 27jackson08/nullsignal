"""Claim extraction and contradiction detection."""
from __future__ import annotations

import pytest

from nullsignal.claims.extract import extract
from nullsignal.claims.graph import build
from nullsignal.claims.types import Subject
from nullsignal.inference import engine
from nullsignal.types import Reliability

from helpers import make_evidence, make_propensity, make_zone

HEALTHY = {n: Reliability() for n in ("311", "nws", "gtfs_rt", "cdc_svi")}


def claims_for(**kwargs):
    propensity = kwargs.pop("propensity", make_propensity())
    evidence = make_evidence(propensity=propensity, **kwargs)
    return evidence, extract(evidence, propensity)


# --- a dead feed makes no claims ---------------------------------------------

def test_a_frozen_transit_feed_claims_nothing_rather_than_claiming_normal():
    """The single most important line in claim extraction.

    A frozen feed still returns a well-formed payload describing normal
    service. Reading that as evidence of normal service is the exact failure
    this project is named for, so an unreliable source is silent instead.
    """
    frozen = {**HEALTHY, "gtfs_rt": Reliability(liveness=0.0)}
    _, claims = claims_for(sources=frozen)
    assert not [c for c in claims if c.subject is Subject.TRANSIT_SERVICE]

    _, healthy_claims = claims_for(sources=HEALTHY)
    assert [c for c in healthy_claims if c.subject is Subject.TRANSIT_SERVICE]


# --- silence where speech was expected ----------------------------------------

def test_dangerous_heat_with_no_complaints_contradicts_in_a_vocal_tract():
    evidence, claims = claims_for(
        sources=HEALTHY, heat_index_f=104.0,
        report_count=200, recent_report_count=0,   # normal history, silent now
        propensity=make_propensity(1.5),
    )
    graph = build(claims)
    assert graph.contradictions
    assert graph.mass > 0
    assert "quieter than its own usual rate" in graph.describe()[0]


def test_the_same_silence_is_unremarkable_in_a_tract_that_rarely_reports():
    """Whether silence is surprising depends on who is silent.

    This is what the propensity model buys: without it, every quiet tract
    during a heatwave looks like a contradiction, and the signal that matters
    drowns in tracts that were never going to call.
    """
    _, claims = claims_for(
        sources=HEALTHY, heat_index_f=104.0,
        report_count=200, recent_report_count=0,
        propensity=make_propensity(0.02),
    )
    graph = build(claims)
    assert graph.contradictions == ()


def test_mild_heat_with_no_complaints_is_not_a_contradiction():
    _, claims = claims_for(sources=HEALTHY, heat_index_f=72.0,
                           report_count=200, recent_report_count=0,
                           propensity=make_propensity(1.5))
    assert build(claims).contradictions == ()


# --- the invariant: widen, never average --------------------------------------

def test_contradiction_widens_uncertainty_and_leaves_the_risk_estimate_alone():
    """Conflicting sources must not be fused into a confident midpoint.

    Averaging "halted" and "normal" into "mildly degraded" would launder a
    crisis into a shrug. A contradiction lowers sufficiency -- the decision
    becomes less supportable -- while the hazard estimate is untouched, because
    a disagreement is not a measurement.

    The second half is asserted structurally rather than by comparing two
    tracts. Risk is a pure function of the posterior, and the contradiction
    graph is not an input to it; showing that directly is stronger than
    matching two numbers that could coincide for unrelated reasons.
    """
    from nullsignal.inference.hypotheses import expected_harm

    quiet = dict(sources=HEALTHY, heat_index_f=104.0,
                 report_count=200, recent_report_count=0)
    vocal = make_evidence(propensity=make_propensity(1.5), **quiet)
    silent = make_evidence(propensity=make_propensity(0.02), **quiet)

    conflicted = engine.assess(vocal)
    unconflicted = engine.assess(silent)

    assert conflicted.contradictions, "expected a conflict in the vocal tract"
    assert unconflicted.contradictions == ()
    assert conflicted.sufficiency.contradiction < unconflicted.sufficiency.contradiction

    # Risk comes from the posterior alone -- the graph never reaches it.
    for assessment, evidence in ((conflicted, vocal), (unconflicted, silent)):
        assert assessment.risk == pytest.approx(
            expected_harm(assessment.posterior,
                          evidence.zone.vulnerability_multiplier),
            abs=1e-5,
        )


def test_a_conflict_costs_sufficiency_without_touching_the_posterior():
    """Same posterior, worse agreement, lower sufficiency -- isolated."""
    from nullsignal.types import Sufficiency

    agreed = Sufficiency(entropy=0.7, coverage=0.9, contradiction=1.0, staleness=0.9)
    disputed = Sufficiency(entropy=0.7, coverage=0.9, contradiction=0.3, staleness=0.9)
    assert disputed.score < agreed.score


def test_contradiction_mass_is_reported_not_resolved():
    """The graph exposes what conflicts, rather than silently picking a winner."""
    _, claims = claims_for(sources=HEALTHY, heat_index_f=104.0,
                           report_count=200, recent_report_count=0,
                           propensity=make_propensity(1.5))
    graph = build(claims)
    assert 0 < graph.agreement < 1
    assert graph.agreement == pytest.approx(1.0 - graph.mass)


def test_a_tract_with_no_history_at_all_makes_no_distress_claim():
    """No baseline, no tempo, no claim.

    Zero reports over the entire window is not "gone quiet" -- there is nothing
    to have gone quiet from, and inventing a comparison would put a confident
    number on an absence.
    """
    _, claims = claims_for(sources=HEALTHY, heat_index_f=104.0,
                           report_count=0, recent_report_count=0,
                           propensity=make_propensity(1.5))
    assert not [c for c in claims if c.subject is Subject.POPULATION_DISTRESS]


def test_a_tract_reporting_at_its_usual_rate_is_not_a_contradiction():
    """Only a departure from a tract's own norm counts.

    Regression: distress was once an absolute rate per 1,000 residents. The
    citywide median sits at about 20 per 60 days, so any fixed cut placed the
    whole city on one side of it and the rule fired on 94% of tracts -- a
    contradiction that fires everywhere carries no information at all.
    """
    _, claims = claims_for(sources=HEALTHY, heat_index_f=104.0,
                           report_count=200, recent_report_count=7,  # ~on pace
                           propensity=make_propensity(1.5))
    assert build(claims).contradictions == ()
