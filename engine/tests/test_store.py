"""The ingest path, against the committed snapshot.

Every assertion here is about a join or a cast that would fail silently. A
renamed column produces nulls, not an exception; a mishandled sentinel produces
a plausible number. Those are exactly the failures this project exists to
notice, and they deserve the same scrutiny inside the pipeline as outside it.
"""
from __future__ import annotations

import pytest

from conftest import requires_snapshot

pytestmark = requires_snapshot

# NYC has 2,325 census tracts as of the 2020 redistricting.
EXPECTED_TRACTS = 2325


def test_every_tract_survives_the_svi_join(store):
    """A left join, deliberately. An inner join would silently drop tracts the
    vulnerability index does not cover -- making the least-documented places
    disappear from the map entirely rather than appear as unknown."""
    total, with_svi = store.execute(
        "SELECT COUNT(*), COUNT(svi_overall) FROM zones").fetchone()
    assert total == EXPECTED_TRACTS
    assert 0 < with_svi < total, "some tracts must be joined and some suppressed"


def test_suppressed_vulnerability_becomes_null_not_a_number(store):
    """CDC writes -999 for suppressed estimates. Read literally it makes the
    most data-poor tracts look the *least* vulnerable, which is the exact
    inversion this project exists to prevent."""
    negatives = store.execute("""
        SELECT COUNT(*) FROM zones
        WHERE svi_overall < 0 OR pct_no_vehicle < 0 OR pct_age_65_plus < 0
           OR pct_poverty < 0 OR pct_limited_english < 0
    """).fetchone()[0]
    assert negatives == 0

    suppressed = store.execute(
        "SELECT COUNT(*) FROM zones WHERE svi_overall IS NULL").fetchone()[0]
    assert suppressed > 0, "the fixture should contain suppressed tracts"


def test_percentages_are_normalised_to_fractions(store):
    """CDC publishes EP_* as 0-100 and RPL_* as 0-1. Mixing the two scales
    would silently multiply exposure by a hundred."""
    row = store.execute("""
        SELECT MAX(svi_overall), MAX(pct_no_vehicle), MAX(pct_age_65_plus),
               MAX(pct_poverty), MAX(pct_minority)
        FROM zones
    """).fetchone()
    for value in row:
        assert value is None or value <= 1.0, row


def test_reports_land_inside_the_tract_they_are_reported_from(store):
    """The spatial join is point-in-polygon, not a nearest-neighbour guess."""
    assigned, tracts = store.execute(
        "SELECT SUM(report_count), COUNT(*) FROM reports_by_zone").fetchone()
    total = store.execute("SELECT COUNT(*) FROM service_requests").fetchone()[0]

    assert tracts > EXPECTED_TRACTS * 0.9, "nearly every tract should see reports"
    assert assigned <= total, "a report cannot be assigned twice"
    assert assigned > total * 0.9, "most reports should fall inside some tract"


def test_category_totals_reconcile_with_zone_totals(store):
    """Two aggregations of the same records must agree."""
    by_zone = store.execute("SELECT SUM(report_count) FROM reports_by_zone").fetchone()[0]
    by_category = store.execute(
        "SELECT SUM(report_count) FROM reports_by_zone_category").fetchone()[0]
    assert by_category <= by_zone
    assert by_category > by_zone * 0.95, "agency should be present on nearly all"


def test_transit_coverage_is_a_fraction_and_matches_the_city(store):
    """Sanity against known geography: Manhattan is almost entirely within a
    station's walk, Staten Island is largely not. If the projection were wrong
    these would be arbitrary."""
    bounds = store.execute(
        "SELECT MIN(transit_coverage), MAX(transit_coverage) FROM zones").fetchone()
    assert bounds[0] >= 0.0 and bounds[1] <= 1.0

    by_borough = dict(store.execute("""
        SELECT borough, AVG(transit_coverage) FROM zones GROUP BY borough
    """).fetchall())
    assert by_borough["Manhattan"] > 0.85
    assert by_borough["Staten Island"] < 0.45
    assert by_borough["Manhattan"] > by_borough["Queens"] > by_borough["Staten Island"]


def test_the_recent_window_is_a_subset_of_the_whole_window(store):
    violations = store.execute(
        "SELECT COUNT(*) FROM reports_by_zone WHERE recent_report_count > report_count"
    ).fetchone()[0]
    assert violations == 0


def test_the_store_rebuilds_from_gzipped_fixtures(raw_dir):
    """Large payloads are committed compressed. The resolver must accept either
    form, or a fresh clone silently has no data."""
    from nullsignal.store import _resolve

    for name in ("311_requests.json", "nyc_tracts.json"):
        resolved = _resolve(raw_dir / name, name)
        assert resolved.exists()

    with pytest.raises(FileNotFoundError, match="snapshot missing"):
        _resolve(raw_dir / "does_not_exist.json", "phantom")


def test_heat_relief_is_measured_twice(store):
    """Once over every listed site, once over only the working ones.

    The difference is relief the city believes it has and does not -- the same
    kind of gap this system exists to surface, sitting inside the mitigation it
    would otherwise recommend.
    """
    listed, working = store.execute(
        "SELECT AVG(cooling_listed), AVG(cooling_working) FROM zones").fetchone()
    assert 0 < working < listed <= 1.0

    overstated = store.execute("""
        SELECT COUNT(*), SUM(population) FROM zones
        WHERE cooling_listed >= 0.2 AND cooling_working < 0.05 AND population > 0
    """).fetchone()
    assert overstated[0] > 0, "the fixture should contain overstated tracts"


def test_both_coordinate_systems_are_placed_in_new_york(store):
    """The two source datasets share column names and use different coordinate
    systems. Reading them the same way puts 755 sites in the Gulf of Guinea."""
    outside = store.execute("""
        SELECT COUNT(*) FROM cooling_sites
        WHERE ST_X(geom) NOT BETWEEN -74.3 AND -73.6
           OR ST_Y(geom) NOT BETWEEN 40.4 AND 41.0
    """).fetchone()[0]
    assert outside == 0

    kinds = dict(store.execute(
        "SELECT kind, COUNT(*) FROM cooling_sites GROUP BY kind").fetchall())
    assert kinds.get("spray_shower", 0) > 500, "state-plane rows must survive"
    assert kinds.get("cooling_site", 0) > 200


def test_a_broken_site_does_not_count_as_relief(store):
    listed, working = store.execute(
        "SELECT COUNT(*), SUM(CASE WHEN is_working THEN 1 ELSE 0 END) FROM cooling_sites"
    ).fetchone()
    assert working < listed, "the fixture should contain broken sites"

    statuses = dict(store.execute("""
        SELECT status, COUNT(*) FROM cooling_sites WHERE NOT is_working GROUP BY status
    """).fetchall())
    assert "Broken" in statuses
