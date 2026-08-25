"""Plausibility against a decade of the same date.

The last line of defence, and the only one that works when *every* station is
wrong the same way. Cross-station agreement compares instruments to each other,
so a uniform fault passes it unremarked -- there is nothing left to disagree
with. Climatology compares them to what the city has actually done on this day
of the year for ten years, which no instrument fault can move.

Two things keep this from firing on ordinary weather.

The threshold is set from the observed spread, not chosen: NYC daily maxima
vary about 7.7F around their day-of-year normal, so a two-sigma day is simply a
notable one and only past three does a reading stop being weather.

And the bounds are asymmetric. A heat index legitimately runs well above the
air temperature these normals are built from -- that is what humidity does --
so the upper bound is generous. The lower bound is not, because reading cool is
the direction a drifting sensor fails in and the direction that gets people
hurt during a heatwave.
"""
from __future__ import annotations

from dataclasses import dataclass

# Deviation, in standard deviations, at which a reading stops being weather.
COLD_SIGMA_LIMIT = 3.0

# Generous, because heat index exceeds air temperature whenever it is humid.
HOT_SIGMA_LIMIT = 5.0

# Deviation at which the reading is disregarded entirely.
SATURATION_SIGMA = 3.0

# Below this, the normal is built on too little history to lean on.
MIN_SAMPLES = 20


@dataclass(frozen=True, slots=True)
class Plausibility:
    observed: float | None
    normal: float | None
    sigma: float | None
    assessable: bool
    detail: str

    @property
    def score(self) -> float:
        """1.0 when the reading is possible weather, falling as it stops being.

        Unassessable returns 1.0: no history is not evidence of a fault.
        """
        if not self.assessable or self.sigma is None:
            return 1.0
        limit = COLD_SIGMA_LIMIT if self.sigma < 0 else HOT_SIGMA_LIMIT
        excess = abs(self.sigma) - limit
        if excess <= 0:
            return 1.0
        return max(0.0, 1.0 - excess / SATURATION_SIGMA)

    @property
    def is_implausible(self) -> bool:
        return self.assessable and self.score < 1.0


def assess(
    observed: float | None,
    normal_mean: float | None,
    normal_stdev: float | None,
    samples: int = 0,
) -> Plausibility:
    if observed is None or normal_mean is None or not normal_stdev:
        return Plausibility(observed, normal_mean, None, False,
                            "no normal for this day of year")
    if samples < MIN_SAMPLES:
        return Plausibility(observed, normal_mean, None, False,
                            f"normal built on {samples} samples, needs {MIN_SAMPLES}")

    sigma = (observed - normal_mean) / normal_stdev
    direction = "below" if sigma < 0 else "above"
    limit = COLD_SIGMA_LIMIT if sigma < 0 else HOT_SIGMA_LIMIT

    if abs(sigma) <= limit:
        return Plausibility(
            observed, normal_mean, sigma, True,
            f"{observed:.0f}F against a {normal_mean:.0f}F normal for this date, "
            f"{abs(sigma):.1f} sigma {direction} -- within what this city does",
        )

    return Plausibility(
        observed, normal_mean, sigma, True,
        f"{observed:.0f}F against a {normal_mean:.0f}F normal for this date, "
        f"{abs(sigma):.1f} sigma {direction} -- ten years of this date contain "
        f"nothing like it",
    )


def apply_to_cohort(cohort: list, normal: dict | None) -> list:
    """Discount weather reliability across a cohort by climatological
    plausibility.

    Applied to the whole cohort because the normal is a citywide quantity: this
    is the check that still works when every station agrees with every other
    and all of them are wrong.
    """
    if not normal:
        return cohort

    from dataclasses import replace
    from ..types import Reliability

    adjusted = []
    for item in cohort:
        verdict = assess(item.heat_index_f, normal.get("mean_max_f"),
                         normal.get("stdev_f"), normal.get("samples", 0))
        current = item.source_reliability.get("nws")
        if current is None or not verdict.is_implausible:
            adjusted.append(item)
            continue
        adjusted.append(replace(item, source_reliability={
            **item.source_reliability,
            "nws": Reliability(
                freshness=current.freshness,
                coverage=current.coverage,
                liveness=current.liveness * verdict.score,
                accuracy=current.accuracy,
            ),
        }))
    return adjusted
