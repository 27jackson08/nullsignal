"""Cross-source agreement: catching the fault that leaves no trace in one feed."""
from __future__ import annotations

import pytest

from nullsignal.reliability import consistency
from nullsignal.reliability.consistency import apply_to_cohort, assess
from nullsignal.types import Reliability

from helpers import make_evidence, make_zone

CITY = {"Manhattan": 94.0, "Brooklyn": 93.0, "Queens": 95.0,
        "Bronx": 94.5, "Staten Island": 92.5}


def test_stations_that_agree_are_left_alone():
    """Real NYC gridpoints spread about 2F and never more than 3F, so ordinary
    weather variation across the city must not read as a fault."""
    for borough in CITY:
        agreement = assess(CITY, borough)
        assert not agreement.is_outlier, borough
        assert agreement.score == 1.0


def test_a_station_drifting_alone_is_caught():
    """The fault every liveness detector misses by construction: the payload
    changes, the clock advances, and each reading is defensible. Only the
    disagreement gives it away."""
    drifting = {**CITY, "Bronx": 82.0}
    agreement = assess(drifting, "Bronx")

    assert agreement.is_outlier
    assert agreement.score < 0.2
    assert "no weather pattern" in agreement.detail


def test_confidence_grows_with_the_size_of_the_disagreement():
    scores = [assess({**CITY, "Bronx": 94.5 - gap}, "Bronx").score
              for gap in (0, 4, 7, 10, 14)]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 1.0 and scores[-1] == 0.0


def test_too_few_peers_reports_unchecked_rather_than_clean():
    """A check that could not run must never read as a pass."""
    agreement = assess({"Manhattan": 94.0, "Brooklyn": 93.0}, "Manhattan")
    assert not agreement.assessable
    assert agreement.score == 1.0, "unassessable must not be punished either"
    assert "needs" in agreement.detail


def test_a_fault_that_moves_every_station_together_is_not_detectable():
    """The honest limit, asserted so it is not quietly assumed away.

    When every source is wrong in the same direction there is nothing left to
    disagree with. Catching it needs an external reference this system does not
    have, and the scenario suite keeps it as a documented loss.
    """
    uniformly_wrong = {borough: value - 12.0 for borough, value in CITY.items()}
    for borough in uniformly_wrong:
        assert not assess(uniformly_wrong, borough).is_outlier


# --- applied across a cohort --------------------------------------------------

def cohort():
    return [
        make_evidence(zone=make_zone(geoid=f"3606100{i:04d}", borough=borough),
                      heat_index_f=temperature)
        for i, (borough, temperature) in enumerate(CITY.items())
    ]


def test_only_the_outlier_station_loses_reliability():
    drifted = [
        e if e.zone.borough != "Bronx"
        else __import__("dataclasses").replace(e, heat_index_f=82.0)
        for e in cohort()
    ]
    adjusted = {e.zone.borough: e.source_reliability["nws"].score
                for e in apply_to_cohort(drifted)}

    assert adjusted["Bronx"] < 0.1
    for borough in ("Manhattan", "Brooklyn", "Queens", "Staten Island"):
        assert adjusted[borough] == pytest.approx(Reliability().score)


def test_agreement_is_a_relation_not_a_property():
    """A single zone cannot be assessed alone: being an outlier is defined
    against the others, which is why this runs over the whole cohort."""
    alone = apply_to_cohort([cohort()[0]])
    assert alone[0].source_reliability["nws"].score == pytest.approx(Reliability().score)


def test_the_threshold_sits_above_real_city_wide_variation():
    """Guard on the calibration itself, against the observed forecast spread."""
    observed_p95_spread = 3.0
    assert consistency.OUTLIER_THRESHOLD_F > observed_p95_spread
