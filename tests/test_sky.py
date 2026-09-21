# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SKY — Sky Atlas (TC-SKY-010 … TC-SKY-100)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def sky_atlas():
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    atlas = sky_mod.SkyAtlas()
    return atlas


@pytest.fixture
def observing_location():
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    return sky_mod.ObservingLocation(
        name="Backyard",
        latitude=51.5,
        longitude=-1.0,
        elevation_m=100,
        timezone="UTC",
    )


# ---------------------------------------------------------------------------
# TC-SKY-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-010")
@pytest.mark.priority("MVP")
def test_tc_sky_010_catalog_minimum_10k_objects(sky_atlas):
    """SKY-010: Searchable deep-sky catalog with at least 10,000 objects including common names and catalog IDs."""
    results = sky_atlas.search("")
    assert len(results) >= 10_000, "Catalog must contain at least 10 000 objects"

    m42 = sky_atlas.search("M42")
    assert any("M42" in obj.designations for obj in m42)
    ngc1976 = sky_atlas.search("NGC 1976")
    assert any("NGC 1976" in obj.designations for obj in ngc1976)


# ---------------------------------------------------------------------------
# TC-SKY-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-020")
@pytest.mark.priority("MVP")
def test_tc_sky_020_filter_by_type_magnitude_size_visibility(sky_atlas, observing_location):
    """SKY-020: Filter catalog by object type, magnitude, size, and current/tonight visibility."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")

    results = sky_atlas.filter(
        object_types=[sky_mod.ObjectType.GALAXY],
        max_magnitude=10.0,
        min_size_arcmin=5.0,
        location=observing_location,
        visible_tonight=True,
    )
    for obj in results:
        assert obj.object_type == sky_mod.ObjectType.GALAXY
        assert obj.magnitude <= 10.0
        assert obj.size_arcmin >= 5.0


# ---------------------------------------------------------------------------
# TC-SKY-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-030")
@pytest.mark.priority("MVP")
def test_tc_sky_030_altitude_plot_for_current_night(sky_atlas, observing_location):
    """SKY-030: Plot an object's altitude over the current night for the configured observing location."""
    m42 = sky_atlas.get_by_designation("M42")
    chart = sky_atlas.altitude_chart(m42, location=observing_location, date="2026-09-16")

    assert "times" in chart
    assert "altitudes" in chart
    assert len(chart["times"]) == len(chart["altitudes"])
    assert len(chart["times"]) >= 48  # at least 30-min resolution over one night


# ---------------------------------------------------------------------------
# TC-SKY-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-040")
@pytest.mark.priority("P2")
def test_tc_sky_040_custom_horizon_profile(sky_atlas, observing_location):
    """SKY-040: Allow definition of a custom horizon obstruction profile per observing location."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    horizon = sky_mod.HorizonProfile(
        points=[(0, 10), (90, 25), (180, 5), (270, 15), (360, 10)]
    )
    observing_location.set_horizon(horizon)

    # Object at az=90 with altitude 20° should be blocked by the 25° obstacle
    m42 = sky_atlas.get_by_designation("M42")
    chart = sky_atlas.altitude_chart(m42, location=observing_location, date="2026-09-16")
    assert "above_horizon" in chart
    assert isinstance(chart["above_horizon"], list)


# ---------------------------------------------------------------------------
# TC-SKY-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-050")
@pytest.mark.priority("MVP")
def test_tc_sky_050_select_object_as_sequence_target(sky_atlas):
    """SKY-050: Allow selecting an atlas object to populate it as a sequence/framing target."""
    m42 = sky_atlas.get_by_designation("M42")
    target = m42.as_sequence_target()
    assert target["name"] == m42.primary_name
    assert "ra_deg" in target
    assert "dec_deg" in target


# ---------------------------------------------------------------------------
# TC-SKY-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-060")
@pytest.mark.priority("MVP")
def test_tc_sky_060_multiple_observing_locations():
    """SKY-060: Support one or more configured observing locations each with lat/lon/elevation."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    mgr = sky_mod.LocationManager()
    mgr.add(sky_mod.ObservingLocation(name="Home", latitude=51.5, longitude=-1.0, elevation_m=100, timezone="Europe/London"))
    mgr.add(sky_mod.ObservingLocation(name="Dark Site", latitude=50.0, longitude=-2.0, elevation_m=300, timezone="Europe/London"))

    assert len(mgr.locations) == 2
    assert mgr.get("Home").latitude == 51.5
    assert mgr.get("Dark Site").elevation_m == 300


# ---------------------------------------------------------------------------
# TC-SKY-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-070")
@pytest.mark.priority("MVP")
def test_tc_sky_070_offline_operation_no_internet(sky_atlas, observing_location):
    """SKY-070: Core search/filter/chart functions operate with no internet connection (offline catalog)."""
    with patch("socket.getaddrinfo", side_effect=OSError("Network unreachable")):
        results = sky_atlas.search("M31")
        assert len(results) >= 1

        m31 = sky_atlas.get_by_designation("M31")
        chart = sky_atlas.altitude_chart(m31, location=observing_location, date="2026-09-16")
        assert "altitudes" in chart


# ---------------------------------------------------------------------------
# TC-SKY-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-080")
@pytest.mark.priority("P2")
async def test_tc_sky_080_fetch_and_cache_sky_survey_thumbnail(sky_atlas, tmp_path):
    """SKY-080: Fetch and cache a sky-survey cutout thumbnail for a catalog object when added to target list."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    sky_atlas._cache_dir = tmp_path
    m42 = sky_atlas.get_by_designation("M42")

    sky_atlas._fetch_thumbnail = AsyncMock(return_value=b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    await sky_atlas.add_to_target_list(m42)

    cached = tmp_path / f"{m42.primary_name.replace(' ', '_')}_thumbnail.jpg"
    assert cached.exists()

    # The real (unmocked) fetch — ported from Obsy's Target.save() — must
    # degrade to b"" rather than raise when the DSS cutout service is
    # unreachable, so a missing thumbnail never blocks add-to-target-list.
    with patch("socket.getaddrinfo", side_effect=OSError("Network unreachable")):
        data = await sky_mod.SkyAtlas()._fetch_thumbnail(m42)
        assert data == b""


# ---------------------------------------------------------------------------
# TC-SKY-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-090")
@pytest.mark.priority("P2")
async def test_tc_sky_090_geocode_location_name(observing_location):
    """SKY-090: Resolve a location name to lat/lon/timezone via geocoding lookup (Open-Meteo, EXT-130)."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")

    sky_mod.geocode_location = AsyncMock(return_value={
        "latitude": 51.4994,
        "longitude": -0.1248,
        "timezone": "Europe/London",
    })

    result = await sky_mod.geocode_location("Westminster, London")
    assert abs(result["latitude"] - 51.4994) < 0.01
    assert "Europe" in result["timezone"]


# ---------------------------------------------------------------------------
# TC-SKY-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-100")
@pytest.mark.priority("MVP")
async def test_tc_sky_100_simbad_first_search_with_local_fallback(sky_atlas):
    """SKY-100: Object search resolves via a live Simbad lookup first
    (ported from Obsy's target_query, ADR-005), falling back to the
    offline catalog only when Simbad is unreachable, times out, or finds
    nothing — the offline catalog is the fallback, not the primary source."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")

    simbad_hit = sky_mod.DeepSkyObject(
        primary_name="M42", designations=["M42"], ra_deg=83.8221, dec_deg=-5.3911,
        object_type=sky_mod.ObjectType.NEBULA, magnitude=4.0,
    )

    # Simbad hit -> used directly; the local catalog is never consulted.
    with patch.object(sky_mod, "_search_simbad_sync", return_value=[simbad_hit]) as mock_search:
        results = await sky_atlas.search_online("M42")
        assert results == [simbad_hit]
        mock_search.assert_called_once_with("M42")

    # Simbad unreachable (e.g. no internet) -> falls back to the local catalog.
    with patch.object(sky_mod, "_search_simbad_sync", side_effect=OSError("no network")):
        results = await sky_atlas.search_online("M31")
        assert any("M31" in obj.designations for obj in results)

    # Simbad reachable but finds nothing -> also falls back to the local catalog.
    with patch.object(sky_mod, "_search_simbad_sync", return_value=[]):
        results = await sky_atlas.search_online("M31")
        assert any("M31" in obj.designations for obj in results)

    # Empty query never touches Simbad -> returns the full local catalog directly.
    with patch.object(sky_mod, "_search_simbad_sync") as mock_search:
        results = await sky_atlas.search_online("")
        assert len(results) >= 10_000
        mock_search.assert_not_called()


@pytest.mark.requirement("TC-SKY-100")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("v_value, expected", [
    (7.5, 7.5),                    # a real magnitude passes through
    (-1.46, -1.46),                # bright objects have negative magnitudes
    (float("nan"), 99.0),          # Simbad's "no V magnitude"
    (float("inf"), 99.0),          # never let a non-finite value become a magnitude
    (float("-inf"), 99.0),
    ("masked", 99.0),              # astropy masked cell
    ("no rows", 99.0),
    ("no table", 99.0),
    ("error", 99.0),               # network failure -> unknown, not an exception
])
def test_tc_sky_100_simbad_magnitude_lookup_returns_unknown_for_anything_unusable(monkeypatch, v_value, expected):
    """SKY-100: The follow-up Simbad V-magnitude lookup returns the magnitude, or 99.0 (unknown) for NaN/infinite/masked/missing values and lookup errors, without losing the match."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    simbad_mod = pytest.importorskip("astroquery.simbad")
    np = pytest.importorskip("numpy")
    from astropy.table import MaskedColumn, Table

    if v_value == "masked":
        table = Table([MaskedColumn([1.0], name="V", mask=[True])])
    elif v_value == "no rows":
        table = Table({"V": np.array([], dtype=float)})
    elif v_value in ("no table", "error"):
        table = None
    else:
        table = Table({"V": [v_value]})

    class FakeSimbad:
        TIMEOUT = None

        def add_votable_fields(self, *fields):
            pass

        def query_object(self, name, wildcard=False):
            if v_value == "error":
                raise OSError("no network")
            return table

    monkeypatch.setattr(simbad_mod, "Simbad", FakeSimbad)

    assert sky_mod._simbad_magnitude_sync("M42") == pytest.approx(expected)
