"""The poll log and feed-health rollup."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nullsignal.reliability import feeds, observations
from nullsignal.reliability.observations import Observation

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def sample(source_id: str = "gtfs_rt:ace", offset: int = 0, **kwargs) -> Observation:
    defaults = dict(
        source_id=source_id,
        polled_at=(NOW - timedelta(seconds=offset)).isoformat(),
        http_status=200,
        content_hash=f"hash{offset}",
        byte_count=100_000,
        feed_timestamp=(NOW - timedelta(seconds=offset + 3)).isoformat(),
        numeric_value=200.0 + offset,
    )
    return Observation(**{**defaults, **kwargs})


def test_a_log_round_trips(tmp_path):
    for offset in (90, 60, 30, 0):
        observations.append(tmp_path, sample(offset=offset))

    loaded = observations.read(tmp_path, "gtfs_rt:ace")
    assert len(loaded) == 4
    assert loaded[0].polled_at_dt < loaded[-1].polled_at_dt, "oldest first"
    assert loaded[-1].content_hash == "hash0"


def test_a_truncated_line_is_skipped_not_fatal(tmp_path, capsys):
    """Losing an entire poll history because one write was cut short would be
    its own silent failure."""
    observations.append(tmp_path, sample(offset=60))
    path = observations.log_path(tmp_path, "gtfs_rt:ace")
    with path.open("a") as handle:
        handle.write('{"source_id": "gtfs_rt:ace", "polled_a\n')
    observations.append(tmp_path, sample(offset=0))

    loaded = observations.read(tmp_path, "gtfs_rt:ace")
    assert len(loaded) == 2
    assert "unreadable" in capsys.readouterr().out


def test_an_absent_log_reads_as_empty_rather_than_raising(tmp_path):
    assert observations.read(tmp_path, "never_polled") == []
    assert observations.read_all(tmp_path) == {}


def test_a_colon_in_a_source_id_survives_the_filename(tmp_path):
    observations.append(tmp_path, sample(source_id="gtfs_rt:nqrw"))
    assert "gtfs_rt:nqrw" in observations.read_all(tmp_path)


def test_limit_returns_the_most_recent(tmp_path):
    for offset in (120, 90, 60, 30, 0):
        observations.append(tmp_path, sample(offset=offset))
    recent = observations.read(tmp_path, "gtfs_rt:ace", limit=2)
    assert [o.content_hash for o in recent] == ["hash30", "hash0"]


# --- rollup -------------------------------------------------------------------

def test_a_group_is_only_as_live_as_its_least_live_member(tmp_path):
    """Averaging would let six healthy subway lines hide one frozen one -- and
    the riders on that line are exactly who the frozen feed makes invisible."""
    for offset in (120, 90, 60, 30, 0):
        observations.append(tmp_path, sample(source_id="gtfs_rt:healthy", offset=offset))
        observations.append(tmp_path, sample(
            source_id="gtfs_rt:frozen", offset=offset,
            content_hash="same", numeric_value=248.0,
            feed_timestamp=(NOW - timedelta(hours=2)).isoformat()))

    health = feeds.assess_feeds(tmp_path, now=NOW)
    assert "gtfs_rt" in health
    assert health["gtfs_rt"].score < 0.2
    assert health["gtfs_rt"].worst_member == "gtfs_rt:frozen"


def test_an_ungrouped_source_is_assessed_on_its_own(tmp_path):
    for offset in (7200, 3600, 0):
        observations.append(tmp_path, sample(source_id="nws", offset=offset))
    health = feeds.assess_feeds(tmp_path, now=NOW)
    assert set(health) == {"nws"}
    assert health["nws"].worst_member is None


def test_no_polls_at_all_yields_no_claims_about_health(tmp_path):
    assert feeds.assess_feeds(tmp_path, now=NOW) == {}
