"""Evidence assembly, against the committed snapshot."""
from __future__ import annotations

import pytest

from nullsignal import config
from nullsignal.inference import engine, pipeline
from nullsignal.types import DecisionState

from conftest import requires_snapshot

pytestmark = requires_snapshot


@pytest.fixture(scope="module")
def evidence(store_path, raw_dir):
    return pipeline.load_evidence(store_path, raw_dir=raw_dir)


def test_every_tract_produces_evidence(evidence):
    assert len(evidence) == 2325
    assert len({item.zone.geoid for item in evidence}) == len(evidence)


def test_every_expected_source_is_represented(evidence):
    from nullsignal.inference.evidence import EXPECTED_SOURCES
    for item in evidence[:50]:
        assert set(item.source_reliability) == set(EXPECTED_SOURCES)


def test_reliability_components_stay_in_range(evidence):
    for item in evidence:
        for name, reliability in item.source_reliability.items():
            for component in (reliability.freshness, reliability.coverage,
                              reliability.liveness, reliability.accuracy):
                assert 0.0 <= component <= 1.0, (item.zone.geoid, name)


def test_a_tract_with_suppressed_vulnerability_is_never_confirmed_safe(evidence):
    """The headline behaviour, on real data rather than a fixture.

    CDC suppresses these estimates, so we do not know who lives there or how
    exposed they are -- and a system that calls such a tract safe has learned
    nothing from its own premise.
    """
    suppressed = [i for i in evidence if i.zone.svi_overall is None]
    assert suppressed, "the snapshot should contain suppressed tracts"

    for item in suppressed:
        assert "cdc_svi" in item.missing_critical_sources
        assert engine.assess(item).state is not DecisionState.CONFIRMED_LOW


def test_transit_is_critical_only_where_people_depend_on_it(evidence):
    dependent = [i for i in evidence
                 if (i.zone.pct_no_vehicle or 0) >= config.TRANSIT_DEPENDENCE_THRESHOLD]
    driving = [i for i in evidence
               if (i.zone.pct_no_vehicle or 1) < config.TRANSIT_DEPENDENCE_THRESHOLD]
    assert dependent and driving

    assert all("gtfs_rt" in i.critical_sources for i in dependent[:50])
    assert all("gtfs_rt" not in i.critical_sources for i in driving[:50])


def test_propensity_is_fitted_across_the_city(evidence):
    """A tract's reporting level only means anything relative to comparable
    tracts, so the model is fitted once over the whole cohort."""
    estimated = [i for i in evidence if i.propensity and i.propensity.is_estimated]
    assert len(estimated) > 2000

    indices = sorted(i.propensity.index for i in estimated)
    median = indices[len(indices) // 2]
    assert median == pytest.approx(1.0, abs=0.05), "the typical tract sits at 1.0"


def test_quiet_tracts_get_less_evidential_credit(evidence):
    """The point of the whole bias layer: 311 coverage follows how readily a
    tract reports, so its silence is not banked as reassurance."""
    quiet = [i for i in evidence
             if i.propensity and i.propensity.is_estimated and i.propensity.index < 0.4]
    loud = [i for i in evidence
            if i.propensity and i.propensity.is_estimated and i.propensity.index > 2.0]
    assert quiet and loud

    assert (max(i.source_reliability["311"].coverage for i in quiet)
            < min(i.source_reliability["311"].coverage for i in loud))


def test_assessment_runs_over_the_whole_city_without_raising(evidence):
    states = {engine.assess(item).state for item in evidence}
    assert states, "expected at least one state"
    assert states <= set(DecisionState)


def test_a_committed_snapshot_does_not_expire(evidence):
    """Regression: the weather join filtered on wall-clock `now()`.

    A snapshot stopped matching a day after it was taken, so weather became a
    missing critical source and every tract in the city fell to UNKNOWN. The
    engine's behaviour was correct -- it declined to certify safety without
    weather -- but the gap was self-inflicted, and a working directory hides it
    because the snapshot keeps being refreshed. It only surfaced in a clean
    clone.
    """
    with_weather = [item for item in evidence if item.heat_index_f is not None]
    assert len(with_weather) > 0.9 * len(evidence), (
        "committed weather must still join however old the snapshot is"
    )

    unknown = sum(1 for item in evidence
                  if engine.assess(item).state is DecisionState.UNKNOWN)
    assert unknown < 0.5 * len(evidence), (
        f"{unknown} of {len(evidence)} tracts unknown -- a source has silently "
        "stopped joining"
    )
