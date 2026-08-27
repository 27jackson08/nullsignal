"""The heat-relief audit.

New York publishes its cooling sites and spray showers with an operational
`status` field. Most maps plot the locations and drop the status, which turns a
broken spray shower into a dot that looks exactly like a working one. That is
this project's thesis in physical form: the absence of relief is rendered as
the presence of relief.

The audit is deliberately conservative about what it claims. It does not assert
that anyone was harmed, or that the city is negligent, or that the status field
is current. It reports what the city itself published, and who lives inside the
gap between the two coverage maps.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

# A tract counts as overstated when meaningfully more of it is covered by
# listed relief than by working relief. Below this the difference is a sliver
# of geometry at a buffer edge rather than a claim worth making.
OVERSTATEMENT_FLOOR = 0.05

# How many tracts the surface names individually.
WORST_LIMIT = 12

# The headline counts every status the city does not call operational, and the
# obvious objection is that some of those are softer than others -- a site not
# yet activated is not a broken one. So the claim is also reported under
# progressively stricter readings, ending with the one nobody can argue with.
# Each row drops the categories above it.
SENSITIVITY_LADDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("every status the city does not call operational",
     ("Broken", "Under Construction", "Not Yet Activated", "Unknown")),
    ("excluding sites whose status is unknown",
     ("Broken", "Under Construction", "Not Yet Activated")),
    ("excluding those not yet activated",
     ("Broken", "Under Construction")),
    ("counting only sites the city calls broken",
     ("Broken",)),
)


# Where a reader goes to check this themselves. A finding nobody can verify is
# an assertion, and this project has no standing to make those.
SOURCES = (
    {"label": "Cool It! NYC — cooling sites",
     "url": "https://data.cityofnewyork.us/d/h2bn-gu9k",
     "note": "carries the status field this audit reads"},
    {"label": "Cool It! NYC — spray showers",
     "url": "https://data.cityofnewyork.us/d/tzuk-eq2f",
     "note": "same status field, different coordinate system"},
    {"label": "CDC/ATSDR Social Vulnerability Index 2022",
     "url": "https://www.atsdr.cdc.gov/place-health/php/svi/",
     "note": "tract-level vulnerability, unmodified"},
)


@dataclass(frozen=True, slots=True)
class CoolingAudit:
    site_total: int
    site_working: int
    by_status: tuple[dict, ...]
    by_borough: tuple[dict, ...]
    tracts_overstated: int
    residents_overstated: int
    residents_without_relief: int
    overstated_top_quintile_share: float
    citywide_top_quintile_share: float
    worst: tuple[dict, ...]
    sensitivity: tuple[dict, ...]

    @property
    def site_broken(self) -> int:
        return self.site_total - self.site_working

    @property
    def concentration(self) -> float:
        if self.citywide_top_quintile_share <= 0:
            return 0.0
        return self.overstated_top_quintile_share / self.citywide_top_quintile_share

    def as_dict(self) -> dict:
        return {
            "sites": {
                "total": self.site_total,
                "working": self.site_working,
                "not_working": self.site_broken,
                "by_status": list(self.by_status),
                "by_borough": list(self.by_borough),
            },
            "impact": {
                "tracts_overstated": self.tracts_overstated,
                "residents_overstated": self.residents_overstated,
                "residents_without_relief": self.residents_without_relief,
            },
            "equity": {
                "overstated_top_quintile_share": self.overstated_top_quintile_share,
                "citywide_top_quintile_share": self.citywide_top_quintile_share,
                "concentration": self.concentration,
            },
            "worst": list(self.worst),
            "sensitivity": list(self.sensitivity),
            "sources": list(SOURCES),
        }


def audit(db_path: Path) -> CoolingAudit:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        con.execute("INSTALL spatial; LOAD spatial;")
        return _audit(con)
    finally:
        con.close()


def _audit(con: duckdb.DuckDBPyConnection) -> CoolingAudit:
    total, working = con.execute(
        "SELECT COUNT(*), COUNT(*) FILTER (WHERE is_working) FROM cooling_sites"
    ).fetchone()

    by_status = [
        {"kind": kind, "status": status, "count": count}
        for kind, status, count in con.execute(
            """
            SELECT kind, status, COUNT(*) AS n
            FROM cooling_sites
            WHERE NOT is_working
            GROUP BY kind, status
            ORDER BY n DESC
            """
        ).fetchall()
    ]

    # Sites carry no borough of their own; the tract they fall in supplies it.
    by_borough = [
        {"borough": borough, "not_working": count}
        for borough, count in con.execute(
            """
            SELECT COALESCE(z.borough, 'Unlocated') AS borough, COUNT(*) AS n
            FROM cooling_sites s
            LEFT JOIN zones z ON ST_Within(s.geom, z.geom)
            WHERE NOT s.is_working
            GROUP BY 1
            ORDER BY n DESC
            """
        ).fetchall()
    ]

    quintile = con.execute(
        "SELECT quantile_cont(svi_overall, 0.8) FROM zones WHERE svi_overall IS NOT NULL"
    ).fetchone()[0]

    tracts, residents = con.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(population), 0)
        FROM zones
        WHERE cooling_listed - cooling_working > ?
        """,
        [OVERSTATEMENT_FLOOR],
    ).fetchone()

    without = con.execute(
        "SELECT COALESCE(SUM(population), 0) FROM zones WHERE cooling_working <= 0"
    ).fetchone()[0]

    overstated_share = _top_quintile_share(
        con, quintile, "cooling_listed - cooling_working > ?", [OVERSTATEMENT_FLOOR]
    )
    citywide_share = _top_quintile_share(con, quintile, "TRUE", [])

    worst = [
        {
            "geoid": geoid, "name": name, "borough": borough,
            "population": int(population or 0),
            "listed": round(listed or 0.0, 3),
            "working": round(work or 0.0, 3),
            "gap": round((listed or 0.0) - (work or 0.0), 3),
            "svi_overall": None if svi is None else round(svi, 3),
        }
        for geoid, name, borough, population, listed, work, svi in con.execute(
            """
            SELECT geoid, neighbourhood, borough, population,
                   cooling_listed, cooling_working, svi_overall
            FROM zones
            WHERE cooling_listed - cooling_working > ?
              AND population > 0
            ORDER BY (cooling_listed - cooling_working) * population DESC
            LIMIT ?
            """,
            [OVERSTATEMENT_FLOOR, WORST_LIMIT],
        ).fetchall()
    ]

    sensitivity = tuple(
        {"label": label, "statuses": list(statuses), **_gap_excluding(con, statuses)}
        for label, statuses in SENSITIVITY_LADDER
    )

    return CoolingAudit(
        site_total=int(total), site_working=int(working),
        by_status=tuple(by_status), by_borough=tuple(by_borough),
        tracts_overstated=int(tracts), residents_overstated=int(residents),
        residents_without_relief=int(without),
        overstated_top_quintile_share=overstated_share,
        citywide_top_quintile_share=citywide_share,
        worst=tuple(worst),
        sensitivity=sensitivity,
    )


def _gap_excluding(
    con: duckdb.DuckDBPyConnection, statuses: tuple[str, ...]
) -> dict:
    """Coverage lost when only `statuses` are treated as not working.

    Recomputed from geometry rather than scaled from the headline: the buffers
    overlap, so a subset of the sites does not remove a proportional share of
    the coverage, and any arithmetic shortcut here would be a guess wearing a
    number.
    """
    from ..store import COOLING_WALK_BUFFER_METRES, GEOGRAPHIC_CRS, PROJECTED_CRS

    quoted = ", ".join(f"'{s}'" for s in statuses)
    tracts, residents = con.execute(
        f"""
        WITH listed AS (
            SELECT ST_Union_Agg(ST_Buffer(
                ST_Transform(geom, '{GEOGRAPHIC_CRS}', '{PROJECTED_CRS}', true),
                {COOLING_WALK_BUFFER_METRES})) AS area FROM cooling_sites
        ),
        kept AS (
            SELECT ST_Union_Agg(ST_Buffer(
                ST_Transform(geom, '{GEOGRAPHIC_CRS}', '{PROJECTED_CRS}', true),
                {COOLING_WALK_BUFFER_METRES})) AS area FROM cooling_sites
            WHERE status NOT IN ({quoted})
        ),
        projected AS (
            SELECT geoid, population,
                   ST_Transform(geom, '{GEOGRAPHIC_CRS}', '{PROJECTED_CRS}', true) AS geom
            FROM zones
        ),
        gaps AS (
            SELECT p.population,
                   LEAST(1.0, GREATEST(0.0, ST_Area(ST_Intersection(p.geom, l.area))
                                            / NULLIF(ST_Area(p.geom), 0)))
                 - LEAST(1.0, GREATEST(0.0, ST_Area(ST_Intersection(p.geom, k.area))
                                            / NULLIF(ST_Area(p.geom), 0))) AS gap
            FROM projected p CROSS JOIN listed l CROSS JOIN kept k
        )
        SELECT COUNT(*) FILTER (WHERE gap > ?),
               COALESCE(SUM(population) FILTER (WHERE gap > ?), 0)
        FROM gaps
        """,
        [OVERSTATEMENT_FLOOR, OVERSTATEMENT_FLOOR],
    ).fetchone()

    sites = con.execute(
        f"SELECT COUNT(*) FROM cooling_sites WHERE status IN ({quoted})"
    ).fetchone()[0]

    return {"sites": int(sites), "tracts": int(tracts), "residents": int(residents)}


def _top_quintile_share(
    con: duckdb.DuckDBPyConnection, quintile: float, where: str, params: list
) -> float:
    """Share of residents in the most vulnerable fifth of the city.

    Measured over population rather than over tracts: a tract is not a unit of
    exposure, a person is.
    """
    total, top = con.execute(
        f"""
        SELECT COALESCE(SUM(population), 0),
               COALESCE(SUM(population) FILTER (WHERE svi_overall >= ?), 0)
        FROM zones WHERE {where}
        """,
        [quintile, *params],
    ).fetchone()
    return 0.0 if not total else top / total
