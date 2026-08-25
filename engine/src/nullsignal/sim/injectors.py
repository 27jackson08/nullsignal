"""Failure injection.

Each injector corrupts what the system *sees* while leaving the world alone.
That separation is the point of the whole simulation: ground truth is held
elsewhere, so a run can ask whether an engine recovered the situation or was
fooled by its instruments.

The failure modes here are the ones that defeat uptime monitoring. A dropped
connection is easy -- something obviously broke. What is dangerous is the feed
that keeps answering: HTTP 200, correct content type, plausible payload, and
nothing behind it moving.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from ..types import Reliability
from ..inference.evidence import ZoneEvidence


class FailureMode(StrEnum):
    STALE_BUT_200 = "STALE_BUT_200"        # answering, frozen at last good state
    FLATLINE = "FLATLINE"                  # payload byte-identical poll to poll
    DROPOUT = "DROPOUT"                    # feed gone entirely
    SLOW_DRIFT = "SLOW_DRIFT"              # readings drift away from truth
    SUPPRESS = "SUPPRESS"                  # reports fall without incidents falling
    CONTRADICT = "CONTRADICT"              # source flips to the opposite of truth
    LATENCY = "LATENCY"                    # data arrives, but hours late
    PARTIAL_COVERAGE = "PARTIAL_COVERAGE"  # part of the zone goes dark


@dataclass(frozen=True, slots=True)
class Injection:
    """One active fault, as declared in a scenario."""

    source: str
    mode: FailureMode
    factor: float = 0.2          # SUPPRESS: share of reports that still arrive
    drift_f: float = 8.0         # SLOW_DRIFT: degrees per tick, away from truth
    latency_hours: float = 4.0   # LATENCY
    coverage: float = 0.25       # PARTIAL_COVERAGE: fraction still observable
    borough: str | None = None   # scope the fault to one station, not the city

    def describe(self) -> str:
        scope = f"@{self.borough}" if self.borough else ""
        return f"{self.source}:{self.mode}{scope}"


def apply(
    evidence: ZoneEvidence,
    injections: tuple[Injection, ...],
    *,
    last_good: ZoneEvidence | None,
    ticks_active: dict[str, int],
) -> ZoneEvidence:
    """Corrupt an evidence record according to every active injection."""
    corrupted = evidence
    for injection in injections:
        # A calibration fault lives in one station. Applying it citywide models
        # the worst case -- every source wrong the same way -- which no
        # cross-source check can catch, by construction.
        if injection.borough and injection.borough != evidence.zone.borough:
            continue
        corrupted = _apply_one(corrupted, injection, last_good, ticks_active)
    return corrupted


def _apply_one(
    evidence: ZoneEvidence,
    injection: Injection,
    last_good: ZoneEvidence | None,
    ticks_active: dict[str, int],
) -> ZoneEvidence:
    handler = _HANDLERS.get(injection.mode)
    if handler is None:
        raise ValueError(f"unknown failure mode {injection.mode}")
    return handler(evidence, injection, last_good, ticks_active.get(injection.describe(), 0))


# --- individual modes ---------------------------------------------------------

def _stale_but_200(evidence, injection, last_good, ticks):
    """The canonical silent failure.

    The feed keeps serving its last good payload, so the *value* is whatever
    was true before the fault -- which is why a dashboard reading it at face
    value stays calm. Liveness drops to zero because the content has stopped
    changing, which is the only trace the fault leaves.
    """
    frozen = _carry_forward(evidence, last_good, injection.source)
    return _with_reliability(frozen, injection.source, liveness=0.0)


def _flatline(evidence, injection, last_good, ticks):
    """Payload identical poll to poll. Same signature as STALE_BUT_200 for a
    consumer; kept distinct because it is what the detector actually sees."""
    return _with_reliability(evidence, injection.source, liveness=0.0)


def _dropout(evidence, injection, last_good, ticks):
    """The honest failure: the feed is simply gone. Easy to notice, which is
    exactly why it is not the dangerous case."""
    return _with_reliability(evidence, injection.source,
                             freshness=0.0, coverage=0.0, liveness=0.0)


def _slow_drift(evidence, injection, last_good, ticks):
    """A miscalibrating sensor. Every reading is plausible; the sequence is
    wrong, and it reads *cooler* than reality, which is the dangerous direction
    during a heatwave."""
    if evidence.heat_index_f is None:
        return evidence
    drifted = evidence.heat_index_f - injection.drift_f * max(1, ticks)
    return replace(evidence, heat_index_f=max(60.0, drifted))


def _suppress(evidence, injection, last_good, ticks):
    """Reports fall while incidents do not.

    Models a collapse in reporting -- fear, distrust, a language barrier, a
    broken phone line. The tract's own history is untouched, so its reporting
    tempo drops sharply, which is precisely the signal the contradiction rule
    is looking for.
    """
    return replace(
        evidence,
        recent_report_count=int(evidence.recent_report_count * injection.factor),
    )


def _contradict(evidence, injection, last_good, ticks):
    """A source that reports the opposite of the truth. Rarer than freezing,
    and far more visible, because other sources start disagreeing with it."""
    if injection.source == "gtfs_rt":
        return replace(evidence, transit_alerts=0 if evidence.transit_alerts else 3)
    if injection.source == "nws" and evidence.heat_index_f is not None:
        return replace(evidence, heat_index_f=max(60.0, 170.0 - evidence.heat_index_f))
    return evidence


def _latency(evidence, injection, last_good, ticks):
    """Correct data, hours late. The value is real but stale, so freshness --
    not liveness -- is what should fall."""
    decay = 0.15 ** max(1, ticks)
    carried = _carry_forward(evidence, last_good, injection.source)
    return _with_reliability(carried, injection.source, freshness=decay)


def _partial_coverage(evidence, injection, last_good, ticks):
    """Part of the zone stops being observable. The feed is healthy; it simply
    no longer speaks for everyone in the tract."""
    return _with_reliability(evidence, injection.source, coverage=injection.coverage)


_HANDLERS = {
    FailureMode.STALE_BUT_200: _stale_but_200,
    FailureMode.FLATLINE: _flatline,
    FailureMode.DROPOUT: _dropout,
    FailureMode.SLOW_DRIFT: _slow_drift,
    FailureMode.SUPPRESS: _suppress,
    FailureMode.CONTRADICT: _contradict,
    FailureMode.LATENCY: _latency,
    FailureMode.PARTIAL_COVERAGE: _partial_coverage,
}


# --- helpers ------------------------------------------------------------------

def _carry_forward(evidence: ZoneEvidence, last_good, source: str) -> ZoneEvidence:
    """Replay the last value this source reported before it failed."""
    if last_good is None:
        return evidence
    if source == "nws":
        return replace(evidence, heat_index_f=last_good.heat_index_f)
    if source == "gtfs_rt":
        return replace(evidence, transit_alerts=last_good.transit_alerts)
    if source == "311":
        return replace(evidence, recent_report_count=last_good.recent_report_count)
    return evidence


def _with_reliability(
    evidence: ZoneEvidence,
    source: str,
    *,
    freshness: float | None = None,
    coverage: float | None = None,
    liveness: float | None = None,
) -> ZoneEvidence:
    current = evidence.source_reliability.get(source)
    if current is None:
        return evidence
    updated = Reliability(
        freshness=current.freshness if freshness is None else freshness,
        coverage=current.coverage if coverage is None else coverage,
        liveness=current.liveness if liveness is None else liveness,
        accuracy=current.accuracy,
    )
    return replace(
        evidence,
        source_reliability={**evidence.source_reliability, source: updated},
    )
