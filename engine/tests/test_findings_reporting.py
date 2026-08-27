"""What 311 can and cannot tell you.

These guard a published claim about a real city, so they assert the shape of
the argument rather than exact counts: the numbers move when the snapshot is
refreshed, the claim must not.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nullsignal.findings import reporting

DB = Path("data/nullsignal.duckdb")
pytestmark = pytest.mark.skipif(not DB.exists(), reason="needs a built store")


@pytest.fixture(scope="module")
def result():
    return reporting.analyse(DB)


def test_volume_is_close_to_flat_across_vulnerability(result):
    """The premise the whole propensity model rests on.

    If call volume tracked hardship, an absolute rate would be a usable
    hardship signal and measuring each tract against itself would be
    unnecessary complication. It does not.
    """
    assert len(result.volume_by_quintile) == 5
    assert 0.7 < result.volume_ratio < 1.6, (
        f"volume ratio {result.volume_ratio:.2f} across the whole vulnerability "
        f"range would make 311 volume a usable hardship signal on its own"
    )


def test_the_mix_moves_far_more_than_the_volume(result):
    """Same calls, different content. This is the actual bias."""
    assert result.over_represented and result.under_represented
    widest = result.over_represented[0]["ratio"]
    narrowest = result.under_represented[0]["ratio"]

    assert widest > 3 * result.volume_ratio, (
        "if no complaint type diverged much more than total volume does, there "
        "would be no mix effect to report"
    )
    assert narrowest < 0.5


def test_shares_are_proportions_and_the_ratio_derives_from_them(result):
    for row in (*result.over_represented, *result.under_represented):
        assert 0.0 <= row["least_vulnerable_share"] <= 1.0
        assert 0.0 <= row["most_vulnerable_share"] <= 1.0
        assert row["ratio"] == pytest.approx(
            row["most_vulnerable_share"] / row["least_vulnerable_share"], rel=1e-2
        )


def test_no_complaint_type_is_compared_on_too_few_reports(result):
    """A share computed from a handful of calls is noise wearing a percentage.

    The same failure as the EMS metric, which scored a district 0.33 on a
    denominator of six. Caught once, guarded everywhere since.
    """
    for row in (*result.over_represented, *result.under_represented):
        assert row["reports"] >= reporting.MIN_REPORTS_TO_COMPARE


def test_there_is_no_channel_for_being_dangerously_hot(result):
    """The finding that matters most for a heat-response system.

    Every heat-adjacent complaint type the taxonomy offers means something
    other than a resident overheating, and the meanings are quoted from the
    data rather than inferred.
    """
    assert result.heat_channels, "expected the heat-adjacent types to be listed"
    for channel in result.heat_channels:
        assert channel["means"], channel
        assert channel["kind"] in reporting.HEAT_ADJACENT
