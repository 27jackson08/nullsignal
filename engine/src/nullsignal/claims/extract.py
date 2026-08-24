"""Turn per-zone evidence into typed claims."""
from __future__ import annotations

from .. import config
from ..bias.propensity import Propensity
from ..inference.evidence import ZoneEvidence
from .types import Claim, Subject

# Heat index bands, following NWS heat-advisory practice.
HEAT_BANDS = ((80.0, "low"), (90.0, "moderate"), (103.0, "high"), (float("inf"), "extreme"))

# A feed we cannot trust is not making a claim about anything.
MIN_RELIABILITY_TO_CLAIM = 0.05

# Below this share of a tract's own evidential weight, its silence is too weak
# a signal to make any claim from.
MIN_WEIGHT_TO_READ_SILENCE = 0.35


def extract(evidence: ZoneEvidence, propensity: Propensity | None) -> tuple[Claim, ...]:
    claims: list[Claim] = []
    for builder in (_transit_claim, _heat_claim):
        claim = builder(evidence)
        if claim is not None:
            claims.append(claim)

    distress = _distress_claim(evidence, propensity)
    if distress is not None:
        claims.append(distress)
    return tuple(claims)


def _transit_claim(evidence: ZoneEvidence) -> Claim | None:
    reliability = evidence.source_reliability["gtfs_rt"].score
    if reliability < MIN_RELIABILITY_TO_CLAIM:
        # A frozen or absent feed is not evidence of normal service. Emitting
        # "normal" here would be the entire bug this project exists to prevent.
        return None

    value = "degraded" if evidence.transit_alerts > 0 else "normal"
    return Claim(
        subject=Subject.TRANSIT_SERVICE,
        value=value,
        source="gtfs_rt",
        reliability=reliability,
        detail=f"{evidence.transit_alerts} active service alerts",
    )


def _heat_claim(evidence: ZoneEvidence) -> Claim | None:
    reliability = evidence.source_reliability["nws"].score
    if evidence.heat_index_f is None or reliability < MIN_RELIABILITY_TO_CLAIM:
        return None

    value = next(label for limit, label in HEAT_BANDS if evidence.heat_index_f < limit)
    return Claim(
        subject=Subject.HEAT_EXPOSURE,
        value=value,
        source="nws",
        reliability=reliability,
        detail=f"heat index {evidence.heat_index_f:.0f}F",
    )


def _distress_claim(
    evidence: ZoneEvidence,
    propensity: Propensity | None,
) -> Claim | None:
    """What residents are reporting, relative to how much they usually report.

    Two guards, both learned by getting it wrong:

    Measured as *tempo* -- recent activity against this tract's own longer-run
    rate -- rather than as an absolute rate per 1,000 residents. A fixed cut
    sits either above or below almost the whole city (the median tract files
    about 20 reports per 1,000 over 60 days), so it fires on nearly every tract
    or on none, and a contradiction that fires everywhere carries no
    information.

    And only raised for tracts whose silence is worth reading. In a tract that
    barely reports at all, quiet is the normal condition, and treating it as a
    signal would bury the tracts where quiet is genuinely surprising.
    """
    if evidence.zone.population <= 0 or propensity is None or not propensity.is_estimated:
        return None
    if propensity.evidential_weight < MIN_WEIGHT_TO_READ_SILENCE:
        return None

    tempo = evidence.reporting_tempo
    if tempo is None:
        return None

    if tempo <= config.QUIET_TEMPO:
        value = "low"
    elif tempo >= config.ELEVATED_TEMPO:
        value = "elevated"
    else:
        value = "normal"

    return Claim(
        subject=Subject.POPULATION_DISTRESS,
        value=value,
        source="311",
        reliability=propensity.evidential_weight,
        detail=(f"{evidence.recent_report_count} reports in the last "
                f"{config.RECENT_WINDOW_HOURS}h, {tempo:.2f}x this tract's own "
                f"usual rate"),
    )
