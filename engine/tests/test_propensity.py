"""Reporting-propensity estimation."""
from __future__ import annotations

import pytest

from nullsignal.bias import propensity as prop

CATEGORIES = ["NYPD", "HPD", "DSNY", "DEP", "DOT"]
POPULATION = 4000


def city(levels: dict[str, float], base: int = 20) -> tuple[list, dict]:
    """A synthetic city where each tract reports at `level` x the base rate in
    every category -- i.e. pure propensity differences, no hazard differences."""
    counts, populations = [], {}
    for geoid, level in levels.items():
        populations[geoid] = POPULATION
        for category in CATEGORIES:
            counts.append((geoid, category, int(base * level)))
    return counts, populations


def test_a_tract_reporting_less_across_every_category_scores_below_one():
    levels = {f"t{i}": 1.0 for i in range(20)}
    levels["quiet"] = 0.25
    model = prop.fit(*city(levels))

    quiet = model.get("quiet")
    assert quiet.is_estimated
    assert quiet.index < 0.5
    assert model.get("t0").index == pytest.approx(1.0, abs=0.05)


def test_the_typical_tract_sits_at_one_by_construction():
    """The claim the index makes is relative, so the reference point must be
    the typical tract rather than wherever the log rates happen to average."""
    levels = {f"t{i}": 1.0 + i * 0.1 for i in range(21)}
    model = prop.fit(*city(levels))
    indices = sorted(p.index for p in model.by_geoid.values() if p.is_estimated)
    assert indices[len(indices) // 2] == pytest.approx(1.0, abs=0.02)


def test_one_bad_category_is_hazard_not_propensity():
    """A tract with a plumbing problem is not a tract that complains more.

    This is the whole reason the model is per-category: the tract term is the
    component common to every category, so a spike confined to one of them is
    left in the residual where it belongs.
    """
    counts, populations = city({f"t{i}": 1.0 for i in range(20)})
    counts.append(("spike", "HPD", 400))          # one category, 20x
    for category in CATEGORIES[1:]:
        counts.append(("spike", category, 20))    # the rest, ordinary
    populations["spike"] = POPULATION

    model = prop.fit(counts, populations)
    spike = model.get("spike")
    assert spike.index < 2.0, "a single-category spike must not read as high propensity"
    assert spike.standard_error > model.get("t0").standard_error


def test_silence_from_a_low_propensity_tract_carries_little_weight():
    """The point of the whole model: what a quiet tract's quiet is worth."""
    levels = {f"t{i}": 1.0 for i in range(20)}
    levels["quiet"] = 0.2
    model = prop.fit(*city(levels))

    assert model.get("quiet").evidential_weight < model.get("t0").evidential_weight
    assert model.get("quiet").evidential_weight < 0.35


def test_a_high_propensity_tract_is_capped_at_full_weight():
    """Reporting twice as readily does not buy more than complete coverage."""
    levels = {f"t{i}": 1.0 for i in range(20)}
    levels["loud"] = 4.0
    model = prop.fit(*city(levels))
    assert model.get("loud").evidential_weight <= 1.0


def test_a_tract_seen_in_too_few_categories_is_not_estimated():
    counts = [("sparse", "NYPD", 5)]
    model = prop.fit(counts, {"sparse": POPULATION})
    assert not model.get("sparse").is_estimated
    assert model.get("sparse").evidential_weight == 0.0


def test_a_tiny_population_does_not_manufacture_a_huge_index():
    """Regression: a commercial tract with a hundred residents and hundreds of
    complaints produced an index in the hundreds -- an artefact of the
    denominator, not a fact about reporting."""
    counts, populations = city({f"t{i}": 1.0 for i in range(20)})
    for category in CATEGORIES:
        counts.append(("tiny", category, 300))
    populations["tiny"] = 60

    model = prop.fit(counts, populations)
    assert model.get("tiny") is None, "sub-threshold population must be excluded"
