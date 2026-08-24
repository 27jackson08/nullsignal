"""CDC/ATSDR Social Vulnerability Index.

The vulnerability weighting in NullSignal is not invented: it is the federal
government's own published tract-level index. That matters when someone asks
why a given neighbourhood is prioritised for verification.
"""
from __future__ import annotations

from pathlib import Path

from .base import FetchResult, fetch_to_file

SVI_URL = "https://svi.cdc.gov/Documents/Data/2022/csv/states/NewYork.csv"

# Columns kept from the ~160 the CSV ships with.
#   RPL_THEMES  overall vulnerability percentile (0-1)
#   EP_NOVEH    % households without a vehicle -- stranded by transit failure
#   EP_AGE65    % aged 65+                     -- heat-vulnerable
#   EP_LIMENG   % limited English              -- predicts low 311 reporting
COLUMNS = (
    "FIPS", "COUNTY", "LOCATION", "E_TOTPOP",
    "RPL_THEMES", "RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4",
    "EP_POV150", "EP_AGE65", "EP_LIMENG", "EP_MINRTY", "EP_NOVEH", "EP_MUNIT",
)

# CDC encodes "suppressed / not available" as -999.
MISSING_SENTINEL = -999.0


def fetch_svi(dest_dir: Path) -> FetchResult:
    return fetch_to_file(
        "cdc_svi", SVI_URL, dest_dir / "cdc_svi_ny.csv",
        note="CDC/ATSDR SVI 2022, New York State, tract level",
    )
