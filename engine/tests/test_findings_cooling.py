"""The heat-relief audit.

These assertions guard a claim this project makes in public about a real city,
so they check provenance and arithmetic rather than exact counts: the numbers
move when the snapshot is refreshed, but the claim must stay honest.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nullsignal.findings import cooling

DB = Path("data/nullsignal.duckdb")
pytestmark = pytest.mark.skipif(not DB.exists(), reason="needs a built store")


@pytest.fixture(scope="module")
def result():
    return cooling.audit(DB)


def test_working_sites_never_exceed_the_total(result):
    assert 0 <= result.site_working <= result.site_total
    assert result.site_broken == result.site_total - result.site_working


def test_every_non_working_site_is_accounted_for_by_status(result):
    """The headline count must equal the sum of its parts.

    If these drift apart the surface shows a total that none of its own rows
    add up to, which is exactly the sort of unsourced number this project
    exists to object to.
    """
    assert sum(row["count"] for row in result.by_status) == result.site_broken
    assert sum(row["not_working"] for row in result.by_borough) == result.site_broken


def test_the_status_values_come_from_the_city_not_from_us(result):
    """Every reason a site is called non-working is the city's own word.

    The audit's credibility rests entirely on not having invented the
    judgement, so no status may appear that the published field did not.
    """
    published = {"Broken", "Under Construction", "Not Yet Activated", "Unknown"}
    assert {row["status"] for row in result.by_status} <= published


def test_overstated_tracts_are_covered_on_paper_and_not_in_fact(result):
    """The gap is the whole claim: listed relief exceeding working relief."""
    assert result.tracts_overstated > 0
    for row in result.worst:
        assert row["listed"] > row["working"]
        assert row["gap"] >= cooling.OVERSTATEMENT_FLOOR
        assert row["population"] > 0


def test_shares_are_proportions_and_concentration_derives_from_them(result):
    for share in (result.overstated_top_quintile_share,
                  result.citywide_top_quintile_share):
        assert 0.0 <= share <= 1.0
    assert result.concentration == pytest.approx(
        result.overstated_top_quintile_share / result.citywide_top_quintile_share
    )


def test_the_claim_survives_its_strictest_reading(result):
    """The obvious objection is that 'Not Yet Activated' is not 'Broken'.

    So the finding is reported under progressively stricter readings, and the
    last one counts only sites the city itself calls broken. If that row ever
    collapsed to nothing the headline would be resting entirely on the softer
    categories, and the ladder exists to make that visible rather than
    arguable.
    """
    assert result.sensitivity
    strictest = result.sensitivity[-1]

    assert strictest["statuses"] == ["Broken"]
    assert strictest["sites"] > 0
    assert strictest["residents"] > 50_000, (
        "the strictest reading no longer supports a claim worth making; the "
        "headline is carried by the softer statuses and should say so"
    )


def test_stricter_readings_never_grow(result):
    """Each rung drops categories, so nothing it measures may increase.

    Buffers overlap, so the residents figure is not proportional to the site
    count -- which is exactly why each rung is recomputed from geometry rather
    than scaled, and why this ordering is worth asserting.
    """
    rungs = result.sensitivity
    for tighter, looser in zip(rungs[1:], rungs):
        assert tighter["sites"] <= looser["sites"]
        assert tighter["residents"] <= looser["residents"]
        assert set(tighter["statuses"]) <= set(looser["statuses"])
