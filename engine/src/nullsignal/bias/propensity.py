"""Reporting-propensity estimation.

311 report counts are not incident counts:

    expected_reports(zone, category) = incidents(...) x propensity(zone)

`propensity` is a latent per-tract willingness and ability to call 311. It
matters because the alternative -- reading low report volume as low risk -- is
the mechanism by which quiet neighbourhoods become invisible.

**Identification.** Propensity and incidence cannot be separated from report
counts alone; some structure is required. The assumption used here is that a
tract's propensity is *shared across categories* (it is a property of the
residents), while hazard is category-specific (a tract may have bad plumbing
without having bad roads). So in

    log rate(z, c) = alpha(c) + beta(z) + delta(z, c)

the tract term `beta` is the component common to every category, and `delta`
absorbs category-specific hazard. A tract that reports unusually much across
*all* categories is a high-propensity tract; one that reports unusually much in
a single category has a problem in that category.

**What this is not.** `beta` still conflates "these residents report readily"
with "this tract genuinely has more going wrong overall". Separating those needs
an independent incidence measure this project does not have. The estimate is
therefore explicitly *relative* -- a tract's reporting level against comparable
tracts -- and its uncertainty is carried forward rather than discarded.

Deliberately no vulnerability covariates. Regressing reports on SVI would let
the model absorb "high vulnerability means fewer reports" as an expected
pattern, and the residuals would go to zero -- fitting away the exact bias the
model exists to measure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Continuity correction, so a tract with zero reports in a category still
# contributes rather than producing log(0).
ZERO_CORRECTION = 0.5

# Minimum categories a tract must appear in before `beta` means anything.
MIN_CATEGORIES = 3

# Tracts below this population have report rates too noisy to interpret. Set
# low, a commercial or park tract with a hundred residents and hundreds of
# complaints produces an index in the hundreds, which is an artefact of the
# denominator rather than a fact about reporting.
MIN_POPULATION = 500

# Indices beyond this are treated as unestimated rather than believed.
IMPLAUSIBLE_INDEX = 10.0


@dataclass(frozen=True, slots=True)
class Propensity:
    """A tract's estimated reporting level relative to the city."""

    geoid: str
    log_index: float          # beta: 0 means city-average
    standard_error: float
    category_count: int
    total_reports: int

    @property
    def index(self) -> float:
        """Multiplicative propensity. 0.5 means this tract reports at about
        half the rate of an average tract with the same population."""
        return math.exp(self.log_index)

    @property
    def is_estimated(self) -> bool:
        return (
            self.category_count >= MIN_CATEGORIES
            and self.index <= IMPLAUSIBLE_INDEX
        )

    @property
    def confidence(self) -> float:
        """How firmly the index is pinned down, on 0..1.

        A tract whose categories disagree wildly, or which barely reports at
        all, yields a number we should not lean on.
        """
        if not self.is_estimated:
            return 0.0
        return 1.0 / (1.0 + self.standard_error)

    @property
    def evidential_weight(self) -> float:
        """How much a *silence* from this tract is worth as evidence.

        Capped at 1: a tract that reports twice as readily as average does not
        give more than complete coverage, but one that reports half as readily
        gives materially less. Silence from a low-propensity tract is close to
        no information at all, and must not be counted as reassurance.
        """
        if not self.is_estimated:
            return 0.0
        return min(1.0, self.index) * self.confidence


@dataclass(frozen=True, slots=True)
class PropensityModel:
    by_geoid: dict[str, Propensity]
    category_means: dict[str, float]
    category_count: int

    def get(self, geoid: str) -> Propensity | None:
        return self.by_geoid.get(geoid)


def fit(
    counts: list[tuple[str, str, int]],
    populations: dict[str, int],
) -> PropensityModel:
    """Fit the two-way decomposition.

    `counts` is (geoid, category, report_count).
    """
    observed, categories = _usable_cells(counts, populations)
    log_rates = _log_rates(observed, categories, populations)
    category_means = {
        category: _mean([rates[category] for rates in log_rates.values()])
        for category in categories
    }

    raw = {
        geoid: _tract_estimate(rates, observed[geoid], categories, category_means)
        for geoid, rates in log_rates.items()
    }
    return _recentred(raw, category_means, len(categories))


def _usable_cells(
    counts: list[tuple[str, str, int]],
    populations: dict[str, int],
) -> tuple[dict[str, dict[str, int]], list[str]]:
    observed: dict[str, dict[str, int]] = {}
    categories: set[str] = set()
    for geoid, category, count in counts:
        if populations.get(geoid, 0) < MIN_POPULATION:
            continue
        observed.setdefault(geoid, {})[category] = count
        categories.add(category)
    return observed, sorted(categories)


def _log_rates(
    observed: dict[str, dict[str, int]],
    categories: list[str],
    populations: dict[str, int],
) -> dict[str, dict[str, float]]:
    return {
        geoid: {
            category: math.log((cells.get(category, 0) + ZERO_CORRECTION)
                               / populations[geoid])
            for category in categories
        }
        for geoid, cells in observed.items()
    }


def _tract_estimate(
    rates: dict[str, float],
    cells: dict[str, int],
    categories: list[str],
    category_means: dict[str, float],
) -> tuple[float, float, int, int]:
    """One tract's level, precision-weighted by its counts.

    The log of a small count is a noisy quantity and should not sway the
    estimate as much as a large one.
    """
    weights, deviations = [], []
    for category in categories:
        weights.append(cells.get(category, 0) + ZERO_CORRECTION)
        deviations.append(rates[category] - category_means[category])

    beta = _weighted_mean(deviations, weights)
    spread = _weighted_std(deviations, weights, beta)
    present = sum(1 for category in categories if cells.get(category, 0) > 0)
    return beta, spread / math.sqrt(max(present, 1)), present, sum(cells.values())


def _recentred(
    raw: dict[str, tuple[float, float, int, int]],
    category_means: dict[str, float],
    category_count: int,
) -> PropensityModel:
    """Shift the scale so the typical tract sits at exactly 1.0.

    Without this the index is anchored to the mean of the log rates, which
    zero-report cells drag downwards -- leaving almost every tract "above
    average" and the scale meaningless. The claim this number makes is relative
    ("half as much as a comparable tract"), so the reference point has to be
    the typical tract, by construction rather than by luck.
    """
    centre = _median([value[0] for value in raw.values()
                      if value[2] >= MIN_CATEGORIES])

    return PropensityModel(
        by_geoid={
            geoid: Propensity(
                geoid=geoid,
                log_index=beta - centre,
                standard_error=standard_error,
                category_count=present,
                total_reports=total,
            )
            for geoid, (beta, standard_error, present, total) in raw.items()
        },
        category_means=category_means,
        category_count=category_count,
    )


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total


def _weighted_std(values: list[float], weights: list[float], mean: float) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.0
    variance = sum(w * (v - mean) ** 2 for v, w in zip(values, weights)) / total
    return math.sqrt(max(variance, 0.0))
