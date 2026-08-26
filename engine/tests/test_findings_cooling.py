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
