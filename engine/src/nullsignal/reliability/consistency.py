"""Cross-source agreement.

Some faults leave no trace in a single feed. A thermometer drifting a few
degrees per hour defeats every liveness detector by construction: the payload
changes, the clock advances, and each reading is individually defensible. The
only thing wrong is the *sequence*, and you cannot see that from one station.

What you can see is disagreement with the stations around it. New York's five
borough gridpoints normally agree closely -- mean spread 1.9F, 95th percentile
3.0F across the observed forecast -- so a station several degrees away from its
neighbours is anomalous rather than merely warm.

The limit is worth stating plainly: this catches a station drifting *alone*. A
fault that moves every source the same way stays invisible, because nothing is
left to disagree with it. That case needs an external reference the system does
not have, and the scenario suite keeps it as a documented loss rather than
quietly dropping it.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

# Deviation from the peer median, in degrees F, at which a station is suspect.
# Set above the observed 95th-percentile spread so ordinary weather variation
# across the city does not read as a fault.
OUTLIER_THRESHOLD_F = 5.0

# Deviation at which the station is disregarded entirely.
SATURATION_F = 12.0

# Below this many peers there is nothing to disagree with.
MIN_PEERS = 3


@dataclass(frozen=True, slots=True)
class Agreement:
    """How well one station agrees with its peers."""

    value: float | None
    peer_median: float | None
    deviation: float | None
    assessable: bool
    detail: str

    @property
    def score(self) -> float:
        """1.0 when the station agrees, falling to 0 as it diverges.

        Unassessable returns 1.0 rather than 0: too few peers means we did not
        check, and a check that could not run must not read as a failure.
        """
        if not self.assessable or self.deviation is None:
            return 1.0
        if self.deviation <= OUTLIER_THRESHOLD_F:
            return 1.0
        span = SATURATION_F - OUTLIER_THRESHOLD_F
        return max(0.0, 1.0 - (self.deviation - OUTLIER_THRESHOLD_F) / span)

    @property
    def is_outlier(self) -> bool:
        return self.assessable and self.score < 1.0


def assess(readings: dict[str, float | None], key: str) -> Agreement:
    """Compare one station's reading against the others."""
    value = readings.get(key)
    peers = [v for name, v in readings.items() if name != key and v is not None]

    if value is None:
        return Agreement(None, None, None, False, "no reading from this station")
    if len(peers) < MIN_PEERS:
        return Agreement(value, None, None, False,
                         f"needs {MIN_PEERS} peer stations, have {len(peers)}")

    peer_median = median(peers)
    deviation = abs(value - peer_median)
    if deviation <= OUTLIER_THRESHOLD_F:
        return Agreement(value, peer_median, deviation, True,
                         f"{deviation:.1f}F from the median of {len(peers)} "
                         f"neighbouring stations")

    direction = "below" if value < peer_median else "above"
    return Agreement(value, peer_median, deviation, True,
                     f"reading {deviation:.1f}F {direction} the median of "
                     f"{len(peers)} neighbouring stations, which no weather "
                     f"pattern across this city would produce")


def apply_to_cohort(cohort: list) -> list:
    """Discount each zone's weather reliability by how well its station agrees.

    Applied to a whole cohort at once because agreement is a relation, not a
    property: a station can only be an outlier relative to the others, so this
    cannot be computed one zone at a time.
    """
    from dataclasses import replace
    from ..types import Reliability

    readings: dict[str, float] = {}
    for item in cohort:
        if item.heat_index_f is not None:
            readings.setdefault(item.zone.borough, item.heat_index_f)

    agreements = {
        borough: assess(readings, borough) for borough in readings
    }

    adjusted = []
    for item in cohort:
        agreement = agreements.get(item.zone.borough)
        current = item.source_reliability.get("nws")
        if agreement is None or current is None or not agreement.is_outlier:
            adjusted.append(item)
            continue
        adjusted.append(replace(item, source_reliability={
            **item.source_reliability,
            "nws": Reliability(
                freshness=current.freshness,
                coverage=current.coverage,
                # Disagreement is a liveness problem in the broad sense: the
                # feed is up and its content is moving, but it has stopped
                # telling us about the world.
                liveness=current.liveness * agreement.score,
                accuracy=current.accuracy,
            ),
        }))
    return adjusted
