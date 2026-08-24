"""Append-only poll log.

A single snapshot cannot reveal a frozen feed: "HTTP 200, 103KB of protobuf"
looks identical whether the data is live or stuck. Only a *sequence* of polls
shows that nothing is changing, so every poll is recorded here and the liveness
detectors read the history rather than the moment.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

POLL_DIRNAME = "polls"


@dataclass(frozen=True, slots=True)
class Observation:
    """One poll of one source."""

    source_id: str
    polled_at: str            # ISO-8601, UTC
    http_status: int
    content_hash: str
    byte_count: int
    feed_timestamp: str | None = None   # the feed's own clock, when it has one
    entity_count: int | None = None
    numeric_value: float | None = None  # a sensor-like scalar, for value flatline
    note: str = ""

    @property
    def polled_at_dt(self) -> datetime:
        return _parse(self.polled_at)

    @property
    def feed_timestamp_dt(self) -> datetime | None:
        return _parse(self.feed_timestamp) if self.feed_timestamp else None


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def log_path(raw_dir: Path, source_id: str) -> Path:
    """One file per source. Colons are legal on POSIX but awkward, so they are
    flattened for filenames only."""
    safe = source_id.replace(":", "__").replace("/", "_")
    return raw_dir / POLL_DIRNAME / f"{safe}.jsonl"


def append(raw_dir: Path, observation: Observation) -> None:
    path = log_path(raw_dir, observation.source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(observation), separators=(",", ":")) + "\n")


def read(raw_dir: Path, source_id: str, *, limit: int | None = None) -> list[Observation]:
    """Observations oldest-first. A malformed line is reported and skipped
    rather than aborting the read: losing the whole history because one write
    was truncated would be its own silent failure."""
    path = log_path(raw_dir, source_id)
    if not path.exists():
        return []

    observations: list[Observation] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            observations.append(Observation(**json.loads(line)))
        except (json.JSONDecodeError, TypeError) as exc:
            print(f"    warning: {path.name} line {number} unreadable ({exc}); skipped",
                  flush=True)

    return observations[-limit:] if limit else observations


def read_all(raw_dir: Path) -> dict[str, list[Observation]]:
    directory = raw_dir / POLL_DIRNAME
    if not directory.exists():
        return {}
    histories: dict[str, list[Observation]] = {}
    for path in sorted(directory.glob("*.jsonl")):
        source_id = path.stem.replace("__", ":")
        histories[source_id] = read(raw_dir, source_id)
    return histories


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
