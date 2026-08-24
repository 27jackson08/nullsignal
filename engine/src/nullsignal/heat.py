"""Heat index (NWS Rothfusz regression).

Temperature alone understates heat danger: humidity is what defeats sweating,
so the exposure that matters to a body is the heat index, not the thermometer.
"""
from __future__ import annotations

# Below this, the regression is not meaningful and the index is just the temp.
ROTHFUSZ_MIN_F = 80.0

_C = (-42.379, 2.04901523, 10.14333127, -0.22475541,
      -6.83783e-3, -5.481717e-2, 1.22874e-3, 8.5282e-4, -1.99e-6)


def heat_index_f(temperature_f: float | None, relative_humidity: float | None) -> float | None:
    """Apparent temperature in degrees F, or None when inputs are missing.

    Returning None rather than falling back to the dry-bulb temperature is
    deliberate: a missing humidity reading must propagate as missing evidence,
    not be quietly papered over with a number that looks like a measurement.
    """
    if temperature_f is None or relative_humidity is None:
        return None
    if temperature_f < ROTHFUSZ_MIN_F:
        return temperature_f

    t, r = temperature_f, relative_humidity
    c = _C
    return (
        c[0] + c[1] * t + c[2] * r + c[3] * t * r
        + c[4] * t * t + c[5] * r * r + c[6] * t * t * r
        + c[7] * t * r * r + c[8] * t * t * r * r
    )
