"""Tunable constants. No magic numbers anywhere else in the engine."""
from __future__ import annotations

# --- Decision thresholds (the 2x2) -------------------------------------------
# A zone is only called CONFIRMED_LOW when risk is low AND sufficiency is high.
RISK_THRESHOLD = 0.45
SUFFICIENCY_THRESHOLD = 0.55

# --- Reliability --------------------------------------------------------------
# Declared update cadence per source, in seconds. Freshness decays as
# exp(-dt / tau), so a feed silent for several multiples of tau scores ~0.
SOURCE_CADENCE_SECONDS = {
    "gtfs_rt": 30,
    "nws": 3600,
    "311": 900,
    "airquality": 3600,
    "cooling_centers": 86400,
}

# A feed whose payload has not changed across this many consecutive polls is
# treated as semantically dead even while it returns HTTP 200.
FLATLINE_POLL_COUNT = 4

# dt beyond this multiple of the declared cadence is a cadence violation.
CADENCE_VIOLATION_FACTOR = 3.0

# Reliability floor: a source is never *perfectly* trusted.
MAX_SOURCE_ACCURACY = 0.97

# --- Sufficiency weights (must sum to 1.0) ------------------------------------
SUFFICIENCY_WEIGHTS = {
    "entropy": 0.35,
    "coverage": 0.35,
    "contradiction": 0.20,
    "staleness": 0.10,
}

# --- Evidence coverage --------------------------------------------------------
# Sources are not interchangeable. Averaging them flat would let an abundance of
# cheap evidence paper over the absence of the evidence a decision actually
# turns on, so each carries a weight reflecting how load-bearing it is for a
# heat-and-transit call.
SOURCE_DECISION_WEIGHT = {
    "nws": 0.35,       # the hazard itself
    "cdc_svi": 0.30,   # who is standing in it
    "gtfs_rt": 0.25,   # whether they can leave
    "311": 0.10,       # corroboration only -- never the basis of a safe call
}

# Sources without which a zone cannot be called safe at all. If any is missing,
# sufficiency is capped below threshold no matter how good the rest looks.
CRITICAL_SOURCES = frozenset({"nws", "cdc_svi"})

# The cap applied when a critical source is absent. Deliberately below
# SUFFICIENCY_THRESHOLD: a zone missing decision-critical evidence must land in
# UNKNOWN, never in CONFIRMED_LOW.
CRITICAL_GAP_CEILING = 0.40

# --- Harm model ---------------------------------------------------------------
# Vulnerability multiplier spans this range as SVI goes 0 -> 1. Verification in
# the most vulnerable tracts is worth ~3x the same check in the least.
VULNERABILITY_MULTIPLIER_RANGE = (1.0, 3.0)

# --- Geography ----------------------------------------------------------------
NYC_COUNTY_FIPS = {
    "005": "Bronx",
    "047": "Brooklyn",
    "061": "Manhattan",
    "081": "Queens",
    "085": "Staten Island",
}
