"""DuckDB analytics store.

DuckDB rather than Postgres because there is no Docker on the target machine:
this ships as a single file inside the repo, so a reviewer can run the whole
system with one command and no service to stand up.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from . import config

DB_FILENAME = "nullsignal.duckdb"

# CDC suppresses small-cell estimates with this sentinel rather than NULL.
SVI_MISSING_SENTINEL = -999

# CDC publishes EP_* as percentages (0-100) and RPL_* as percentiles (0-1).
# Everything downstream wants 0-1, so normalisation happens once, here.
PERCENT_SCALE = 100.0

# Recent-activity window. Anchored to the newest record in the snapshot rather
# than to wall-clock now, so a snapshot taken last week still yields a
# meaningful "recently" and the comparison stays reproducible.
RECENT_WINDOW_HOURS = 48

# Standard transit-access buffer: the distance people will walk to a station.
TRANSIT_WALK_BUFFER_METRES = 800

# How far someone will walk to heat relief in dangerous heat. Shorter than the
# transit buffer on purpose: the people who most need a misting station are the
# ones least able to walk half a mile to reach it.
COOLING_WALK_BUFFER_METRES = 500

# UTM zone 18N covers New York. Buffering in degrees would be anisotropic --
# 800 "metres" of longitude is a quarter shorter than 800 of latitude here.
PROJECTED_CRS = "EPSG:32618"
# NY State Plane Long Island (feet) -- one of the two systems the cooling
# datasets arrive in, despite sharing column names with the other.
PROJECTED_STATE_PLANE = "EPSG:2263"
GEOGRAPHIC_CRS = "EPSG:4326"


def connect(db_path: Path, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db_path), read_only=read_only)
    con.execute("INSTALL spatial; LOAD spatial;")
    return con


def build_store(raw_dir: Path, db_path: Path) -> dict[str, int]:
    """Build zones and evidence tables from a snapshot directory."""
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = connect(db_path)
    _register_district_crosswalk(con)
    counts: dict[str, int] = {}
    try:
        counts["tracts"] = _load_tracts(con, raw_dir / "nyc_tracts.json")
        counts["svi"] = _load_svi(con, raw_dir / "cdc_svi_ny.csv")
        counts["zones"] = _build_zones(con)
        counts["reports"] = _load_service_requests(con, raw_dir / "311_requests.json")
        counts["reports_by_zone"] = _aggregate_reports(con)
        counts["reports_by_category"] = _aggregate_reports_by_category(con)
        counts["stations"] = _load_stations(con, raw_dir / "gtfs_stations.json")
        counts["cooling_sites"] = _load_cooling(con, raw_dir / "cooling_sites.json")
        counts["air_quality"] = _load_air_quality(con, raw_dir / "air_quality.json")
        counts["climatology"] = _load_climatology(con, raw_dir / "climatology.json")
        counts["ems"] = _load_ems(con, raw_dir / "ems_dispatches.json")
        counts["alerts"] = _load_alerts(con, raw_dir / "nws_alerts.json")
        counts["cooling_access"] = _compute_cooling_access(con)
        counts["transit_coverage"] = _compute_transit_coverage(con)
        counts["weather"] = _load_weather(con, raw_dir / "nws_forecast.json")
        counts["feeds"] = _load_feed_health(con, raw_dir / "gtfs_rt_summary.json")
    finally:
        con.close()
    return counts


def _load_tracts(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    path = _resolve(path, "tracts")
    con.execute(
        """
        CREATE OR REPLACE TABLE tracts AS
        SELECT
            geoid,
            ntaname                       AS neighbourhood,
            boroname                      AS borough,
            cdta2020                      AS community_district,
            ST_GeomFromGeoJSON(the_geom::JSON::VARCHAR) AS geom
        FROM read_json_auto(?, maximum_object_size=200000000)
        WHERE geoid IS NOT NULL
        """,
        [str(path)],
    )
    return _count(con, "tracts")


def _load_svi(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Load SVI, restricted to the five NYC counties, sentinels nulled out."""
    path = _resolve(path, "svi")
    county_list = ", ".join(f"'{fips}'" for fips in config.NYC_COUNTY_FIPS)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE svi AS
        SELECT
            CAST(FIPS AS VARCHAR)                    AS geoid,
            CAST(E_TOTPOP AS INTEGER)                AS population,
            {_nullify('RPL_THEMES')}                 AS svi_overall,
            {_nullify('EP_NOVEH')}  / {PERCENT_SCALE} AS pct_no_vehicle,
            {_nullify('EP_AGE65')}  / {PERCENT_SCALE} AS pct_age_65_plus,
            {_nullify('EP_LIMENG')} / {PERCENT_SCALE} AS pct_limited_english,
            {_nullify('EP_POV150')} / {PERCENT_SCALE} AS pct_poverty,
            {_nullify('EP_MINRTY')} / {PERCENT_SCALE} AS pct_minority
        FROM read_csv_auto(?, header=true, all_varchar=true)
        WHERE substr(CAST(FIPS AS VARCHAR), 3, 3) IN ({county_list})
        """,
        [str(path)],
    )
    return _count(con, "svi")


def _nullify(column: str) -> str:
    """CDC's -999 means 'suppressed', not 'zero'. Treating it as zero would
    make the most data-poor tracts look the least vulnerable -- the exact
    inversion this project exists to prevent."""
    return (
        f"NULLIF(TRY_CAST({column} AS DOUBLE), {SVI_MISSING_SENTINEL})"
    )


def _build_zones(con: duckdb.DuckDBPyConnection) -> int:
    """Join geometry to vulnerability. An inner join would silently drop tracts
    the SVI does not cover; a left join keeps them visible with NULL
    vulnerability, which the engine must then treat as unknown, not as safe."""
    con.execute(
        """
        CREATE OR REPLACE TABLE zones AS
        SELECT
            t.geoid,
            t.neighbourhood,
            t.borough,
            t.community_district,
            t.geom,
            ST_AsGeoJSON(ST_Simplify(t.geom, 0.0001)) AS geom_simplified,
            COALESCE(s.population, 0)        AS population,
            s.svi_overall,
            s.pct_no_vehicle,
            s.pct_age_65_plus,
            s.pct_limited_english,
            s.pct_poverty,
            s.pct_minority,
            (s.geoid IS NULL)                AS svi_missing
        FROM tracts t
        LEFT JOIN svi s USING (geoid)
        """
    )
    return _count(con, "zones")


def _load_service_requests(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    path = _resolve(path, "311")
    con.execute(
        """
        CREATE OR REPLACE TABLE service_requests AS
        SELECT
            unique_key,
            CAST(created_date AS TIMESTAMP) AS created_at,
            complaint_type,
            descriptor,
            agency,
            TRY_CAST(latitude AS DOUBLE)  AS latitude,
            TRY_CAST(longitude AS DOUBLE) AS longitude
        FROM read_json_auto(?, maximum_object_size=400000000)
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """,
        [str(path)],
    )
    return _count(con, "service_requests")


def _aggregate_reports(con: duckdb.DuckDBPyConnection) -> int:
    """Point-in-polygon 311 -> tract. This count is the raw reporting signal;
    the bias layer later divides it by an estimated propensity to recover an
    incident estimate."""
    con.execute(
        """
        CREATE OR REPLACE TABLE reports_by_zone AS
        WITH anchor AS (SELECT MAX(created_at) AS newest FROM service_requests)
        SELECT
            z.geoid,
            COUNT(*)                                   AS report_count,
            COUNT(DISTINCT r.complaint_type)           AS distinct_complaint_types,
            MAX(r.created_at)                          AS latest_report_at,
            SUM(CASE WHEN r.created_at
                     > (SELECT newest FROM anchor) - INTERVAL {hours} HOUR
                     THEN 1 ELSE 0 END)                AS recent_report_count,
            date_diff('hour', MIN(r.created_at),
                      (SELECT newest FROM anchor))     AS window_hours
        FROM service_requests r
        JOIN zones z
          ON ST_Within(ST_Point(r.longitude, r.latitude), z.geom)
        GROUP BY z.geoid
        """.format(hours=RECENT_WINDOW_HOURS)
    )
    return _count(con, "reports_by_zone")


def _aggregate_reports_by_category(con: duckdb.DuckDBPyConnection) -> int:
    """Reports per tract per category, using the city's own agency taxonomy.

    Category matters because reporting bias lives in the *mix*, not the volume:
    per-capita 311 volume is nearly flat across vulnerability quintiles in NYC,
    while composition differs sharply. A single per-tract propensity scalar
    would average that structure away and find nothing.
    """
    con.execute(
        """
        CREATE OR REPLACE TABLE reports_by_zone_category AS
        SELECT
            z.geoid,
            r.agency                     AS category,
            COUNT(*)                     AS report_count,
            MAX(r.created_at)            AS latest_report_at
        FROM service_requests r
        JOIN zones z
          ON ST_Within(ST_Point(r.longitude, r.latitude), z.geom)
        WHERE r.agency IS NOT NULL
        GROUP BY z.geoid, r.agency
        """
    )
    return _count(con, "reports_by_zone_category")


def _load_stations(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    path = _resolve(path, "gtfs_stations")
    con.execute(
        """
        CREATE OR REPLACE TABLE transit_stations AS
        SELECT stop_id, stop_name,
               ST_Point(longitude, latitude) AS geom
        FROM read_json_auto(?)
        """,
        [str(path)],
    )
    return _count(con, "transit_stations")


def _load_cooling(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Heat-relief sites, normalised to lon/lat.

    The two source datasets share column names and use different coordinate
    systems, so each row carries the system it was read in and is transformed
    accordingly. `always_xy` for the same reason as everywhere else: without it
    EPSG:4326's declared axis order silently swaps the pair.
    """
    path = _resolve(path, "cooling_sites")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cooling_sites AS
        SELECT
            kind, name, status,
            CAST(is_working AS BOOLEAN) AS is_working,
            CASE
                WHEN crs = '{PROJECTED_STATE_PLANE}'
                THEN ST_Transform(ST_Point(x, y),
                                  '{PROJECTED_STATE_PLANE}', '{GEOGRAPHIC_CRS}', true)
                ELSE ST_Point(x, y)
            END AS geom
        FROM read_json_auto(?)
        """,
        [str(path)],
    )
    return _count(con, "cooling_sites")


def _load_air_quality(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Chronic air burden, joined to tracts through their community district.

    Annual means. They describe what these residents breathe year after year,
    not what is in the air this afternoon, and the engine is only permitted to
    use them as a prior for that reason.
    """
    path = _resolve(path, "air_quality")
    con.execute(
        """
        CREATE OR REPLACE TABLE air_quality AS
        SELECT district_id, district_name, indicator,
               TRY_CAST(value AS DOUBLE) AS value, period
        FROM read_json_auto(?)
        """,
        [str(path)],
    )

    # "BK10" -> "310": borough letters become the leading digit.
    con.execute(
        """
        ALTER TABLE zones ADD COLUMN IF NOT EXISTS ozone_ppb DOUBLE;
        ALTER TABLE zones ADD COLUMN IF NOT EXISTS pm25_ugm3 DOUBLE;
        UPDATE zones SET
            ozone_ppb = (
                SELECT a.value FROM air_quality a
                WHERE a.indicator = 'ozone_ppb'
                  AND a.district_id = _district_id(zones.community_district)
            ),
            pm25_ugm3 = (
                SELECT a.value FROM air_quality a
                WHERE a.indicator = 'pm25_ugm3'
                  AND a.district_id = _district_id(zones.community_district)
            );
        """
    )
    return _count(con, "air_quality")


def _load_climatology(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Day-of-year normals -- the reference no instrument fault can move."""
    path = _resolve(path, "climatology")
    con.execute(
        """
        CREATE OR REPLACE TABLE climate_normals AS
        SELECT CAST(day_of_year AS INTEGER) AS day_of_year,
               TRY_CAST(mean_max_f AS DOUBLE) AS mean_max_f,
               TRY_CAST(stdev_f AS DOUBLE)    AS stdev_f,
               CAST(samples AS INTEGER)       AS samples
        FROM read_json_auto(?)
        """,
        [str(path)],
    )
    return _count(con, "climate_normals")


# A rate needs a denominator big enough to carry it. Citywide the heat share
# is 0.0029, so in a district with six dispatches a single heat call reads as
# 0.33 -- and that was the largest value in the whole dataset. Twelve of the
# 71 district codes are low-volume special areas of that kind. Below this floor
# the share is not measured, which is not the same as being zero.
MIN_EMS_DISPATCHES = 200


def _load_ems(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Heat-related ambulance dispatches, joined through community district.

    An independent read on the same harm 311 describes. Someone calling an
    ambulance is not filing a complaint: it does not depend on knowing the 311
    number, on speaking English, or on expecting a response. Where the
    propensity model has to discount what a tract says, this speaks about the
    same tract through a channel that bias does not run through.
    """
    path = _resolve(path, "ems_dispatches")
    con.execute(
        """
        CREATE OR REPLACE TABLE ems_dispatches AS
        SELECT district_id,
               CAST(heat_dispatches AS INTEGER)   AS heat_dispatches,
               CAST(health_dispatches AS INTEGER) AS health_dispatches
        FROM read_json_auto(?)
        """,
        [str(path)],
    )
    con.execute(
        f"""
        ALTER TABLE zones ADD COLUMN IF NOT EXISTS ems_heat_share DOUBLE;
        UPDATE zones SET ems_heat_share = (
            SELECT CASE WHEN e.health_dispatches >= {MIN_EMS_DISPATCHES}
                        THEN e.heat_dispatches * 1.0 / e.health_dispatches END
            FROM ems_dispatches e
            WHERE e.district_id = _district_id(zones.community_district)
        );
        """
    )
    return _count(con, "ems_dispatches")


def _load_alerts(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Active watches and warnings.

    Usually empty, and the empty state is the useful one: "our data says
    extreme heat and the weather service has issued nothing" is a contradiction
    that only exists because the absence was recorded rather than skipped.
    """
    path = _resolve(path, "nws_alerts")

    # The empty file is the *normal* state and must not be an error. DuckDB
    # cannot infer a schema from `[]`, so the table is declared explicitly and
    # only filled when there is something to fill it with. Letting an absence
    # of alerts crash the build would be a peculiar failure for a system whose
    # subject is the meaning of absence.
    con.execute(
        """
        CREATE OR REPLACE TABLE nws_alerts (
            event VARCHAR, severity VARCHAR, urgency VARCHAR,
            area VARCHAR, is_heat BOOLEAN
        )
        """
    )
    import json as _json

    if _json.loads(path.read_text() or "[]"):
        con.execute(
            """
            INSERT INTO nws_alerts
            SELECT event, severity, urgency, area, CAST(is_heat AS BOOLEAN)
            FROM read_json_auto(?)
            """,
            [str(path)],
        )
    return _count(con, "nws_alerts")


def _register_district_crosswalk(con: duckdb.DuckDBPyConnection) -> None:
    from .sources.air_quality import district_id_for

    con.create_function("_district_id", district_id_for,
                        ["VARCHAR"], "VARCHAR", null_handling="special")


def _compute_cooling_access(con: duckdb.DuckDBPyConnection) -> int:
    """Share of each tract within walking distance of heat relief.

    Computed twice: once over every listed site, once over only the working
    ones. The difference is the relief a city believes it has and does not --
    and it is the same kind of gap this whole system exists to surface, sitting
    inside the mitigation we would otherwise recommend.
    """
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cooling_access AS
        WITH listed AS (
            SELECT ST_Union_Agg(ST_Buffer(
                ST_Transform(geom, '{GEOGRAPHIC_CRS}', '{PROJECTED_CRS}', true),
                {COOLING_WALK_BUFFER_METRES})) AS area
            FROM cooling_sites
        ),
        working AS (
            SELECT ST_Union_Agg(ST_Buffer(
                ST_Transform(geom, '{GEOGRAPHIC_CRS}', '{PROJECTED_CRS}', true),
                {COOLING_WALK_BUFFER_METRES})) AS area
            FROM cooling_sites WHERE is_working
        ),
        projected AS (
            SELECT geoid,
                   ST_Transform(geom, '{GEOGRAPHIC_CRS}', '{PROJECTED_CRS}', true) AS geom
            FROM zones
        )
        SELECT
            p.geoid,
            LEAST(1.0, GREATEST(0.0, ST_Area(ST_Intersection(p.geom, l.area))
                                     / NULLIF(ST_Area(p.geom), 0))) AS cooling_listed,
            LEAST(1.0, GREATEST(0.0, ST_Area(ST_Intersection(p.geom, w.area))
                                     / NULLIF(ST_Area(p.geom), 0))) AS cooling_working
        FROM projected p CROSS JOIN listed l CROSS JOIN working w
        """
    )
    con.execute(
        """
        ALTER TABLE zones ADD COLUMN IF NOT EXISTS cooling_listed DOUBLE;
        ALTER TABLE zones ADD COLUMN IF NOT EXISTS cooling_working DOUBLE;
        UPDATE zones SET
            cooling_listed = (SELECT c.cooling_listed FROM cooling_access c
                              WHERE c.geoid = zones.geoid),
            cooling_working = (SELECT c.cooling_working FROM cooling_access c
                               WHERE c.geoid = zones.geoid);
        """
    )
    return _count(con, "cooling_access")


def _compute_transit_coverage(con: duckdb.DuckDBPyConnection) -> int:
    """Fraction of each tract within walking distance of a subway station.

    This is coverage in the literal sense: how much of the tract the realtime
    transit feed could ever tell us anything about. A tract at zero is not
    thereby safe -- it is a tract where transit evidence does not exist, which
    is a gap to be surfaced rather than a clean bill of health.

    `always_xy` is not optional. Without it DuckDB honours EPSG:4326's declared
    (latitude, longitude) axis order, the transform silently returns nonsense
    coordinates, and every buffer lands in the wrong hemisphere.
    """
    con.execute(
        f"""
        CREATE OR REPLACE TABLE transit_coverage AS
        WITH walkable AS (
            SELECT ST_Union_Agg(
                       ST_Buffer(
                           ST_Transform(geom, '{GEOGRAPHIC_CRS}', '{PROJECTED_CRS}', true),
                           {TRANSIT_WALK_BUFFER_METRES}
                       )
                   ) AS area
            FROM transit_stations
        ),
        projected AS (
            SELECT geoid,
                   ST_Transform(geom, '{GEOGRAPHIC_CRS}', '{PROJECTED_CRS}', true) AS geom
            FROM zones
        )
        SELECT
            p.geoid,
            LEAST(1.0, GREATEST(0.0,
                ST_Area(ST_Intersection(p.geom, w.area))
                / NULLIF(ST_Area(p.geom), 0)
            )) AS transit_coverage
        FROM projected p CROSS JOIN walkable w
        """
    )
    con.execute(
        """
        ALTER TABLE zones ADD COLUMN IF NOT EXISTS transit_coverage DOUBLE;
        UPDATE zones SET transit_coverage = (
            SELECT tc.transit_coverage FROM transit_coverage tc WHERE tc.geoid = zones.geoid
        );
        """
    )
    return _count(con, "transit_coverage")


def _load_weather(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    path = _resolve(path, "weather")
    con.execute(
        """
        CREATE OR REPLACE TABLE weather_forecast AS
        SELECT
            borough,
            CAST(start_time AS TIMESTAMP)          AS valid_at,
            TRY_CAST(temperature_f AS DOUBLE)      AS temperature_f,
            TRY_CAST(relative_humidity AS DOUBLE)  AS relative_humidity,
            short_forecast
        FROM read_json_auto(?)
        """,
        [str(path)],
    )
    return _count(con, "weather_forecast")


def _load_feed_health(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Transit feed provenance: hash, age, entity counts. The raw material for
    silent-failure detection."""
    path = _resolve(path, "gtfs_rt_summary")
    con.execute(
        """
        CREATE OR REPLACE TABLE feed_health AS
        SELECT
            feed,
            ok,
            content_hash,
            TRY_CAST(byte_count AS BIGINT)        AS byte_count,
            TRY_CAST(feed_age_seconds AS DOUBLE)  AS feed_age_seconds,
            TRY_CAST(entity_count AS BIGINT)      AS entity_count,
            TRY_CAST(trip_updates AS BIGINT)      AS trip_updates,
            TRY_CAST(alerts AS BIGINT)            AS alerts
        FROM read_json_auto(?)
        """,
        [str(path)],
    )
    return _count(con, "feed_health")


def _resolve(path: Path, label: str) -> Path:
    """Accept either the plain or the gzipped snapshot file.

    Large payloads (311 is ~47MB raw, ~6.6MB gzipped) are committed compressed
    so the offline demo stays cloneable. DuckDB reads gzip transparently, so
    only path resolution differs.
    """
    if path.exists():
        return path
    compressed = path.with_suffix(path.suffix + ".gz")
    if compressed.exists():
        return compressed
    raise FileNotFoundError(
        f"snapshot missing {label} at {path} (or {compressed.name}). "
        "Run: uv run nullsignal snapshot"
    )


def _count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
