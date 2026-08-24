"""Silent-failure detection.

A feed can be technically up and semantically dead: HTTP 200, correct
content-type, plausible payload size, and nothing behind it changing. That
failure is invisible to uptime monitoring, which is exactly why it is dangerous
-- the dashboard stays calm and the neighbourhood stays green.

Three independent detectors, because the failure modes are different:

  cadence violation  the feed's own clock has stopped advancing
  content flatline   the payload is byte-identical poll after poll
  value flatline     a sensor keeps reporting one plausible constant

They are combined with `max`, not a sum. A frozen feed trips several of these
at once, but that is one fact observed three ways, and adding the evidence up
would manufacture confidence out of a single underlying event.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .. import config
from .observations import Observation

# Past the cadence-violation point, confidence ramps to certain over this
# many further multiples of the declared cadence.
CADENCE_RAMP_MULTIPLES = 3.0


@dataclass(frozen=True, slots=True)
class DetectorResult:
    name: str
    assessable: bool         # was there enough history to run this at all?
    confidence_dead: float   # 0 = looks live, 1 = certainly frozen
    detail: str

    @property
    def fired(self) -> bool:
        return self.assessable and self.confidence_dead >= 0.5


@dataclass(frozen=True, slots=True)
class LivenessVerdict:
    score: float
    detectors: tuple[DetectorResult, ...]

    @property
    def fired(self) -> tuple[str, ...]:
        return tuple(d.name for d in self.detectors if d.fired)

    @property
    def unassessable(self) -> tuple[str, ...]:
        """Detectors that could not run. Reported rather than hidden: "we did
        not check" is a different claim from "we checked and it is fine"."""
        return tuple(d.name for d in self.detectors if not d.assessable)


def assess(
    observations: list[Observation],
    *,
    cadence_seconds: float,
    now: datetime | None = None,
    min_polls: int = config.FLATLINE_POLL_COUNT,
) -> LivenessVerdict:
    """Run every detector and take the strongest single signal."""
    moment = now or datetime.now(UTC)
    results = (
        _cadence_violation(observations, cadence_seconds, moment),
        _content_flatline(observations, cadence_seconds, min_polls),
        _value_flatline(observations, cadence_seconds, min_polls),
    )
    live_evidence = [r.confidence_dead for r in results if r.assessable]
    score = 1.0 - max(live_evidence, default=0.0)
    return LivenessVerdict(score=_clamp(score), detectors=results)


def _cadence_violation(
    observations: list[Observation],
    cadence_seconds: float,
    now: datetime,
) -> DetectorResult:
    """The feed's own clock lags its publish interval, while HTTP says 200.

    Lag is measured at the moment of observation -- `polled_at` minus the
    feed's own timestamp -- not against wall-clock now. Measuring against now
    conflates "the feed stopped publishing" with "we stopped polling", so every
    feed looked dead a few minutes after a poll run ended. That is this
    project's own thesis pointed the wrong way: absence of observation is not
    evidence of failure, and a detector that forgets it manufactures outages.

    How stale *our* copy is remains a real concern, but it belongs to
    freshness, which is measured separately and means something different.
    """
    name = "cadence_violation"
    if not observations:
        return DetectorResult(name, False, 0.0, "no observations")

    latest = observations[-1]
    if latest.feed_timestamp_dt is None:
        return DetectorResult(
            name, False, 0.0,
            "feed publishes no timestamp of its own",
        )

    lag = (latest.polled_at_dt - latest.feed_timestamp_dt).total_seconds()
    observed_ago = (now - latest.polled_at_dt).total_seconds()
    suffix = f" (as of our last poll {observed_ago / 60:.0f} min ago)" if observed_ago > 120 else ""

    threshold = cadence_seconds * config.CADENCE_VIOLATION_FACTOR
    if lag <= threshold:
        return DetectorResult(
            name, True, 0.0,
            f"feed clock {lag:.0f}s behind at poll time, within its "
            f"{cadence_seconds:.0f}s cadence{suffix}",
        )

    overshoot = (lag - threshold) / (cadence_seconds * CADENCE_RAMP_MULTIPLES)
    return DetectorResult(
        name, True, _clamp(overshoot),
        f"feed clock {lag:.0f}s behind at poll time, {lag / cadence_seconds:.1f}x "
        f"its {cadence_seconds:.0f}s cadence, while still returning HTTP 200{suffix}",
    )


def _content_flatline(
    observations: list[Observation],
    cadence_seconds: float,
    min_polls: int,
) -> DetectorResult:
    """Byte-identical payloads for longer than the feed's own update interval.

    The strongest of the three. A live feed embeds its own timestamp, so even a
    genuinely quiet period still changes the bytes.

    What matters is how *long* the payload has been unchanged, not how many
    times we asked. Counting polls instead made this fire on any feed polled
    faster than it publishes -- an hourly forecast sampled every 30 seconds is
    byte-identical every time and perfectly healthy. A detector that cries wolf
    on healthy feeds gets muted, and then catches nothing at all.
    """
    name = "content_flatline"
    if len(observations) < min_polls:
        return DetectorResult(
            name, False, 0.0,
            f"needs {min_polls} polls, have {len(observations)}",
        )

    run = _trailing_run(o.content_hash for o in reversed(observations))
    if run < 2:
        return DetectorResult(name, True, 0.0, "payload changing between polls")

    span = _run_span_seconds(observations, run)
    threshold = cadence_seconds * config.CADENCE_VIOLATION_FACTOR
    if span < threshold:
        return DetectorResult(
            name, True, 0.0,
            f"unchanged for {span:.0f}s, within its {cadence_seconds:.0f}s "
            f"publish interval",
        )

    confidence = (span - threshold) / (cadence_seconds * CADENCE_RAMP_MULTIPLES)
    return DetectorResult(
        name, True, _clamp(confidence),
        f"payload byte-identical for {span:.0f}s across {run} polls, "
        f"{span / cadence_seconds:.1f}x its {cadence_seconds:.0f}s publish interval",
    )


def _value_flatline(
    observations: list[Observation],
    cadence_seconds: float,
    min_polls: int,
) -> DetectorResult:
    """A sensor pinned to one plausible constant -- stuck rather than stable.

    Duration-gated for the same reason as content flatline: a reading that has
    not moved in less than one publish interval has simply not been republished
    yet.
    """
    name = "value_flatline"
    valued = [o for o in observations if o.numeric_value is not None]
    if len(valued) < min_polls:
        return DetectorResult(
            name, False, 0.0,
            f"needs {min_polls} numeric readings, have {len(valued)}",
        )

    run = _trailing_run(o.numeric_value for o in reversed(valued))
    if run < 2:
        return DetectorResult(name, True, 0.0, "reading varies between polls")

    span = _run_span_seconds(valued, run)
    threshold = cadence_seconds * config.CADENCE_VIOLATION_FACTOR
    if span < threshold:
        return DetectorResult(
            name, True, 0.0,
            f"steady for {span:.0f}s, within its {cadence_seconds:.0f}s "
            f"publish interval",
        )

    confidence = (span - threshold) / (cadence_seconds * CADENCE_RAMP_MULTIPLES)
    return DetectorResult(
        name, True, _clamp(confidence),
        f"reading pinned at {valued[-1].numeric_value} for {span:.0f}s, "
        f"{span / cadence_seconds:.1f}x its {cadence_seconds:.0f}s publish interval",
    )


def _run_span_seconds(observations: list[Observation], run: int) -> float:
    """Wall-clock time covered by the identical run at the end of the history."""
    if run < 2:
        return 0.0
    window = observations[-run:]
    return (window[-1].polled_at_dt - window[0].polled_at_dt).total_seconds()


def _trailing_run(values) -> int:
    """Length of the identical run at the end of a sequence (passed reversed)."""
    run = 0
    first = None
    for value in values:
        if run == 0:
            first = value
            run = 1
            continue
        if value != first:
            break
        run += 1
    return run


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
