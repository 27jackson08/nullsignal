"""Silent-failure detection.

These tests describe the failure this project is named for: a feed that returns
HTTP 200 with a plausible payload while nothing behind it moves.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nullsignal import config
from nullsignal.reliability import liveness
from nullsignal.reliability.observations import Observation

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
CADENCE = 30.0


def observation(
    *,
    offset_seconds: float,
    content_hash: str = "abc",
    numeric_value: float | None = None,
    feed_offset_seconds: float | None = None,
    http_status: int = 200,
) -> Observation:
    polled = NOW - timedelta(seconds=offset_seconds)
    feed = NOW - timedelta(
        seconds=offset_seconds if feed_offset_seconds is None else feed_offset_seconds
    )
    return Observation(
        source_id="gtfs_rt:test",
        polled_at=polled.isoformat(),
        http_status=http_status,
        content_hash=content_hash,
        byte_count=100_000,
        feed_timestamp=feed.isoformat(),
        numeric_value=numeric_value,
    )


def healthy_history(count: int = 6) -> list[Observation]:
    """A live feed: fresh clock, changing payload, drifting entity count."""
    return [
        observation(offset_seconds=(count - i) * CADENCE,
                    content_hash=f"hash{i}", numeric_value=200.0 + i)
        for i in range(count)
    ]


# --- the headline case --------------------------------------------------------

def test_frozen_feed_returning_http_200_is_caught():
    """The canonical silent failure: the endpoint is up, the data is not."""
    frozen = [
        observation(offset_seconds=(6 - i) * CADENCE, content_hash="same",
                    numeric_value=248.0, feed_offset_seconds=3600)
        for i in range(6)
    ]
    verdict = liveness.assess(frozen, cadence_seconds=CADENCE, now=NOW)

    assert verdict.score < 0.2
    assert "content_flatline" in verdict.fired
    assert all(o.http_status == 200 for o in frozen), "the feed never stopped answering"


def test_healthy_feed_is_not_flagged():
    verdict = liveness.assess(healthy_history(), cadence_seconds=CADENCE, now=NOW)
    assert verdict.score == pytest.approx(1.0)
    assert verdict.fired == ()


# --- detectors individually ---------------------------------------------------

def test_cadence_violation_works_from_a_single_poll():
    """Freshness against the feed's own clock needs no history, so a brand new
    install is not blind to a feed that is already stale."""
    stale = [observation(offset_seconds=0, feed_offset_seconds=CADENCE * 20)]
    verdict = liveness.assess(stale, cadence_seconds=CADENCE, now=NOW)
    assert "cadence_violation" in verdict.fired


def test_value_flatline_catches_a_stuck_sensor():
    """Payload changes each poll -- only the reading is pinned."""
    stuck = [
        observation(offset_seconds=(6 - i) * CADENCE,
                    content_hash=f"hash{i}", numeric_value=71.0)
        for i in range(6)
    ]
    verdict = liveness.assess(stuck, cadence_seconds=CADENCE, now=NOW)
    assert "value_flatline" in verdict.fired


def test_confidence_grows_with_the_duration_of_the_flatline():
    """Confidence tracks how long the payload has been frozen, not how many
    times we happened to ask."""
    total = 12

    def score_for(run_length: int) -> float:
        hashes = [f"hash{i}" for i in range(total - run_length)] + ["same"] * run_length
        history = [
            observation(offset_seconds=(total - i) * CADENCE, content_hash=h)
            for i, h in enumerate(hashes)
        ]
        return liveness.assess(history, cadence_seconds=CADENCE, now=NOW).score

    assert score_for(7) < score_for(6) < score_for(5) < score_for(4)


def test_polling_faster_than_a_feed_publishes_is_not_a_fault():
    """The false positive that would get this switched off.

    An hourly forecast sampled every 30 seconds returns byte-identical payloads
    every time and is perfectly healthy. Counting polls flagged it; measuring
    elapsed time against the feed's own publish interval does not.
    """
    hourly_cadence = 3600.0
    rapid_polls = [
        observation(offset_seconds=(6 - i) * 30, content_hash="same", numeric_value=66.0)
        for i in range(6)
    ]
    verdict = liveness.assess(rapid_polls, cadence_seconds=hourly_cadence, now=NOW)

    assert verdict.fired == ()
    assert verdict.score == pytest.approx(1.0)


def test_the_same_feed_frozen_across_publish_intervals_does_fire():
    """Counterpart to the test above: identical payloads become damning once
    they outlast several publish intervals."""
    hourly_cadence = 3600.0
    frozen = [
        observation(offset_seconds=(6 - i) * hourly_cadence * 2, content_hash="same")
        for i in range(6)
    ]
    verdict = liveness.assess(frozen, cadence_seconds=hourly_cadence, now=NOW)
    assert "content_flatline" in verdict.fired


# --- honesty about what was not checked ---------------------------------------

def test_short_history_reports_flatline_as_unassessable():
    """With one poll we cannot know whether the payload is changing, and must
    say so rather than quietly reporting a clean bill of health."""
    verdict = liveness.assess([observation(offset_seconds=0)],
                              cadence_seconds=CADENCE, now=NOW)
    assert "content_flatline" in verdict.unassessable
    assert "value_flatline" in verdict.unassessable
    assert "cadence_violation" not in verdict.unassessable


def test_no_observations_at_all_is_not_a_clean_bill_of_health():
    verdict = liveness.assess([], cadence_seconds=CADENCE, now=NOW)
    assert verdict.unassessable == ("cadence_violation", "content_flatline",
                                    "value_flatline")


def test_correlated_detectors_are_combined_by_max_not_sum():
    """A frozen feed trips several detectors, but that is one fact seen three
    ways. Summing would manufacture certainty from a single event."""
    frozen = [
        observation(offset_seconds=(6 - i) * CADENCE, content_hash="same",
                    numeric_value=248.0, feed_offset_seconds=CADENCE * 50)
        for i in range(6)
    ]
    verdict = liveness.assess(frozen, cadence_seconds=CADENCE, now=NOW)

    fired = [d for d in verdict.detectors if d.fired]
    assert len(fired) >= 2, "expected multiple detectors on a fully frozen feed"
    assert verdict.score == pytest.approx(1.0 - max(d.confidence_dead for d in fired))
    assert verdict.score >= 0.0


# --- not-looking is not the same as not-working -------------------------------

def test_a_healthy_feed_we_stopped_polling_is_not_reported_as_dead():
    """Regression: this system's own thesis, pointed the wrong way.

    Lag was once measured against wall-clock now rather than against the poll
    that observed it, so every feed looked dead a few minutes after a poll run
    ended. Absence of observation is not evidence of failure -- that confusion
    is the whole thing NullSignal exists to prevent, and it is no more
    acceptable inside the engine than in a city's dashboard.
    """
    hours_ago = 6
    healthy_but_old = [
        Observation(
            source_id="gtfs_rt:test",
            # Polled hours ago, but the feed was current at the time.
            polled_at=(NOW - timedelta(hours=hours_ago, seconds=(6 - i) * CADENCE)).isoformat(),
            http_status=200,
            content_hash=f"hash{i}",
            byte_count=100_000,
            feed_timestamp=(
                NOW - timedelta(hours=hours_ago, seconds=(6 - i) * CADENCE + 3)
            ).isoformat(),
            numeric_value=200.0 + i,
        )
        for i in range(6)
    ]
    verdict = liveness.assess(healthy_but_old, cadence_seconds=CADENCE, now=NOW)

    assert verdict.fired == (), "stale observation must not read as a dead feed"
    assert verdict.score == pytest.approx(1.0)


def test_a_feed_lagging_its_own_clock_still_fires_however_recently_polled():
    """The counterpart: lag belongs to the feed, so polling a second ago does
    not excuse a publisher that stopped an hour ago."""
    lagging = [
        Observation(
            source_id="gtfs_rt:test",
            polled_at=(NOW - timedelta(seconds=(6 - i) * CADENCE)).isoformat(),
            http_status=200,
            content_hash=f"hash{i}",
            byte_count=100_000,
            feed_timestamp=(NOW - timedelta(hours=1)).isoformat(),
            numeric_value=200.0 + i,
        )
        for i in range(6)
    ]
    verdict = liveness.assess(lagging, cadence_seconds=CADENCE, now=NOW)
    assert "cadence_violation" in verdict.fired
