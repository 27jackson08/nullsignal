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
    counts: dict[str, int] = {}
    try:
        counts["tracts"] = _load_tracts(con, raw_dir / "nyc_tracts.json")
        counts["svi"] = _load_svi(con, raw_dir / "cdc_svi_ny.csv")
        counts["zones"] = _build_zones(con)
        counts["reports"] = _load_service_requests(con, raw_dir / "311_requests.json")
        counts["reports_by_zone"] = _aggregate_reports(con)
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
        SELECT
            z.geoid,
            COUNT(*)                                   AS report_count,
            COUNT(DISTINCT r.complaint_type)           AS distinct_complaint_types,
            MAX(r.created_at)                          AS latest_report_at
        FROM service_requests r
        JOIN zones z
          ON ST_Within(ST_Point(r.longitude, r.latitude), z.geom)
        GROUP BY z.geoid
        """
    )
    return _count(con, "reports_by_zone")


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
