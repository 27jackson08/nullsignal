"""Feed-level health, assessed once per source rather than per zone.

Whether the MTA's realtime feed has frozen is a fact about the feed, not about
any particular tract, so it is computed once and then combined with per-zone
coverage downstream.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import config
from .liveness import LivenessVerdict, assess as assess_liveness
from .observations import Observation, read_all

# Sub-feeds that roll up into one logical source.
FEED_GROUPS = {"gtfs_rt": "gtfs_rt:"}


@dataclass(frozen=True, slots=True)
class FeedHealth:
    source_id: str
    liveness: LivenessVerdict
    poll_count: int
    worst_member: str | None = None   # which sub-feed drove a group verdict

    @property
    def score(self) -> float:
        return self.liveness.score


def assess_feeds(
    raw_dir: Path,
    *,
    now: datetime | None = None,
) -> dict[str, FeedHealth]:
    """Liveness for every logical source we have polled."""
    histories = read_all(raw_dir)
    health: dict[str, FeedHealth] = {}

    for logical, prefix in FEED_GROUPS.items():
        members = {sid: obs for sid, obs in histories.items() if sid.startswith(prefix)}
        if members:
            health[logical] = _worst_of(logical, members, now)

    grouped_ids = {sid for prefix in FEED_GROUPS.values()
                   for sid in histories if sid.startswith(prefix)}
    for source_id, observations in histories.items():
        if source_id in grouped_ids:
            continue
        health[source_id] = _single(source_id, observations, now)

    return health


def _single(
    source_id: str,
    observations: list[Observation],
    now: datetime | None,
) -> FeedHealth:
    cadence = config.SOURCE_CADENCE_SECONDS.get(source_id, 3600)
    verdict = assess_liveness(observations, cadence_seconds=cadence, now=now)
    return FeedHealth(source_id, verdict, len(observations))


def _worst_of(
    logical: str,
    members: dict[str, list[Observation]],
    now: datetime | None,
) -> FeedHealth:
    """A group is only as live as its least live member.

    Averaging would let six healthy subway lines hide one frozen one -- and the
    riders on that line are exactly the people the frozen feed makes invisible.
    """
    cadence = config.SOURCE_CADENCE_SECONDS.get(logical, 3600)
    verdicts = {
        source_id: assess_liveness(observations, cadence_seconds=cadence, now=now)
        for source_id, observations in members.items()
    }
    worst_id = min(verdicts, key=lambda sid: verdicts[sid].score)
    return FeedHealth(
        source_id=logical,
        liveness=verdicts[worst_id],
        poll_count=min(len(o) for o in members.values()),
        worst_member=worst_id,
    )
