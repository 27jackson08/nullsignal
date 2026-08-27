"""What 311 can and cannot tell you.

The reporting-propensity model in `bias/` measures a tract against its own
long-run rate rather than against the city, and that choice is usually
explained as statistical hygiene. It is not. It is forced by two properties of
the data, both measurable here.

**Volume barely moves.** Calls per thousand residents run 21.5 in the least
vulnerable fifth of New York and 25.3 in the most. Anyone treating 311 volume
as a hardship signal is reading a channel that is close to flat in the
dimension they care about.

**The mix moves enormously.** At near-identical volume, the most vulnerable
fifth spends its calls on the inside of the home -- appliances, plaster,
plumbing, elevators -- and the least vulnerable fifth on the public realm
outside it: street trees, sidewalks, taxis. Same number of calls, categorically
different content.

**And there is no channel for the hazard.** In an August window the only
heat-related complaint type is HEAT/HOT WATER, which is the winter complaint
about a landlord failing to *supply* heat. A resident who is dangerously hot
has nowhere to file it. A heat-response system reading 311 for distress is
reading a form with no box for the thing it is looking for.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

# Below this a type's share is too noisy to compare between quintiles.
MIN_REPORTS_TO_COMPARE = 900

# How many types the surface names at each end.
FACES_SHOWN = 8

# Complaint types the taxonomy offers for anything heat-adjacent, with what
# each one actually means. Quoted rather than inferred: the descriptors on
# HEAT/HOT WATER are ENTIRE BUILDING and APARTMENT ONLY, which is a landlord
# failing to supply heating, and Cooling Tower is a Legionella inspection.
HEAT_ADJACENT = {
    "HEAT/HOT WATER": "a landlord failing to supply heating or hot water",
    "Cooling Tower": "a building's cooling plant, inspected for legionella",
}


SOURCES = (
    {"label": "NYC 311 service requests",
     "url": "https://data.cityofnewyork.us/d/erm2-nwe9",
     "note": "complaint_type and descriptor, geocoded to tracts"},
    {"label": "CDC/ATSDR Social Vulnerability Index 2022",
     "url": "https://www.atsdr.cdc.gov/place-health/php/svi/",
     "note": "the quintiles everything here is grouped by"},
)


@dataclass(frozen=True, slots=True)
class ReportingFinding:
    window_start: str | None
    window_end: str | None
    total_reports: int
    volume_by_quintile: tuple[dict, ...]
    over_represented: tuple[dict, ...]
    under_represented: tuple[dict, ...]
    heat_channels: tuple[dict, ...]

    @property
    def volume_ratio(self) -> float:
        if not self.volume_by_quintile:
            return 0.0
        first = self.volume_by_quintile[0]["per_thousand"]
        last = self.volume_by_quintile[-1]["per_thousand"]
        return 0.0 if not first else last / first

    def as_dict(self) -> dict:
        return {
            "window": {"start": self.window_start, "end": self.window_end},
            "total_reports": self.total_reports,
            "volume_by_quintile": list(self.volume_by_quintile),
            "volume_ratio": self.volume_ratio,
            "over_represented": list(self.over_represented),
            "under_represented": list(self.under_represented),
            "heat_channels": list(self.heat_channels),
            "sources": list(SOURCES),
        }


def analyse(db_path: Path) -> ReportingFinding:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        con.execute("INSTALL spatial; LOAD spatial;")
        return _analyse(con)
    finally:
        con.close()


def _analyse(con: duckdb.DuckDBPyConnection) -> ReportingFinding:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _located AS
        SELECT z.svi_overall AS svi, s.complaint_type AS kind
        FROM service_requests s
        JOIN zones z ON ST_Within(ST_Point(s.longitude, s.latitude), z.geom)
        WHERE s.latitude IS NOT NULL
          AND z.svi_overall IS NOT NULL
          AND z.population > 0
        """
    )
    cuts = con.execute(
        "SELECT quantile_cont(svi_overall, [0.2, 0.4, 0.6, 0.8]) FROM zones "
        "WHERE svi_overall IS NOT NULL"
    ).fetchone()[0]
    bucket = " + ".join(f"CASE WHEN {{col}} >= {c} THEN 1 ELSE 0 END" for c in cuts)

    volume = [
        {"quintile": q + 1, "reports": int(reports), "residents": int(residents),
         "per_thousand": round(reports / residents * 1000, 1) if residents else 0.0}
        for q, reports, residents in con.execute(
            f"""
            WITH calls AS (
                SELECT {bucket.format(col='svi')} AS q, COUNT(*) AS n
                FROM _located GROUP BY 1
            ),
            people AS (
                SELECT {bucket.format(col='svi_overall')} AS q,
                       SUM(population) AS pop
                FROM zones WHERE svi_overall IS NOT NULL AND population > 0
                GROUP BY 1
            )
            SELECT c.q, c.n, p.pop FROM calls c JOIN people p USING (q) ORDER BY c.q
            """
        ).fetchall()
    ]

    rows = con.execute(
        f"""
        WITH tagged AS (
            SELECT kind, {bucket.format(col='svi')} AS q FROM _located
        ),
        per_quintile AS (SELECT q, COUNT(*) AS n FROM tagged GROUP BY 1)
        SELECT t.kind,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE t.q = 0) AS low_n,
               COUNT(*) FILTER (WHERE t.q = 4) AS high_n,
               MAX((SELECT n FROM per_quintile WHERE q = 0)) AS low_total,
               MAX((SELECT n FROM per_quintile WHERE q = 4)) AS high_total
        FROM tagged t
        GROUP BY t.kind
        HAVING COUNT(*) >= ?
        """,
        [MIN_REPORTS_TO_COMPARE],
    ).fetchall()

    compared = []
    for kind, total, low_n, high_n, low_total, high_total in rows:
        if not low_n or not high_n:
            continue
        low = low_n / low_total
        high = high_n / high_total
        compared.append({
            "kind": kind,
            "least_vulnerable_share": round(low, 5),
            "most_vulnerable_share": round(high, 5),
            # Three places, not two: a type at 0.10 loses three percent of its
            # value to rounding at two, which is more than the figure it is
            # being compared against moves in total.
            "ratio": round(high / low, 3),
            "reports": int(total),
        })

    ranked = sorted(compared, key=lambda r: r["ratio"], reverse=True)

    heat = [
        {"kind": kind, "reports": int(n), "means": HEAT_ADJACENT[kind]}
        for kind, n in con.execute(
            "SELECT complaint_type, COUNT(*) FROM service_requests "
            "WHERE complaint_type IN ? GROUP BY 1 ORDER BY 2 DESC",
            [list(HEAT_ADJACENT)],
        ).fetchall()
    ]

    start, end, total = con.execute(
        "SELECT MIN(created_at), MAX(created_at), COUNT(*) FROM service_requests"
    ).fetchone()

    return ReportingFinding(
        window_start=None if start is None else start.isoformat(),
        window_end=None if end is None else end.isoformat(),
        total_reports=int(total),
        volume_by_quintile=tuple(volume),
        over_represented=tuple(ranked[:FACES_SHOWN]),
        under_represented=tuple(reversed(ranked[-FACES_SHOWN:])),
        heat_channels=tuple(heat),
    )
