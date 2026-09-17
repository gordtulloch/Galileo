"""SKYMAP — Interactive Star Map / Planetarium (TC-SKYMAP-010 … TC-SKYMAP-060)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def skymap(observing_location=None):
    skymap_mod = pytest.importorskip("galileo.ui.skymap")
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    loc = sky_mod.ObservingLocation(
        name="Home", latitude=51.5, longitude=-1.0, elevation_m=100, timezone="UTC"
    )
    return skymap_mod.SkyMapView(location=loc)


# ---------------------------------------------------------------------------
# TC-SKYMAP-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_tc_skymap_010_real_time_sky_view_renders():
    """SKYMAP-010: Render an interactive, pannable, zoomable real-time sky view for the configured location/time."""
    skymap_mod = pytest.importorskip("galileo.ui.skymap")
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    loc = sky_mod.ObservingLocation(name="Home", latitude=51.5, longitude=-1.0, elevation_m=100, timezone="UTC")
    view = skymap_mod.SkyMapView(location=loc)

    frame = view.render(datetime_utc="2026-09-16T22:00:00", magnitude_limit=10.0)
    assert frame is not None
    assert hasattr(frame, "width") or isinstance(frame, (bytes, bytearray, memoryview))


# ---------------------------------------------------------------------------
# TC-SKYMAP-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKYMAP-020")
@pytest.mark.priority("MVP")
def test_tc_skymap_020_click_to_identify_double_click_to_center(skymap):
    """SKYMAP-020: Clicking an object identifies it; double-clicking centers and tracks it."""
    skymap_mod = pytest.importorskip("galileo.ui.skymap")

    skymap._objects_at = MagicMock(return_value=[MagicMock(primary_name="M42", ra=83.8, dec=-5.4)])
    identified = skymap.identify_at_pixel(x=400, y=300)
    assert identified.primary_name == "M42"

    skymap.center_and_track(identified)
    assert skymap.tracked_object is identified


# ---------------------------------------------------------------------------
# TC-SKYMAP-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKYMAP-030")
@pytest.mark.priority("MVP")
def test_tc_skymap_030_constellation_lines_and_grid_toggleable(skymap):
    """SKYMAP-030: Overlay constellation lines/art and coordinate grid, each independently toggleable."""
    skymap.set_constellation_overlay(enabled=True)
    assert skymap.show_constellations is True

    skymap.set_grid_overlay(enabled=True)
    assert skymap.show_grid is True

    skymap.set_constellation_overlay(enabled=False)
    assert skymap.show_constellations is False
    assert skymap.show_grid is True  # grid must remain independent


# ---------------------------------------------------------------------------
# TC-SKYMAP-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKYMAP-040")
@pytest.mark.priority("P2")
def test_tc_skymap_040_comets_asteroids_satellites(skymap):
    """SKYMAP-040: Display comets, asteroids, and artificial satellites from periodically updated orbital elements."""
    skymap_mod = pytest.importorskip("galileo.ui.skymap")
    skymap.load_solar_system_objects(
        comets=[{"name": "C/2023 A3", "elements": {}}],
        asteroids=[{"name": "1 Ceres", "elements": {}}],
        satellites=[{"name": "ISS", "tle_lines": ("", "", "")}],
    )
    assert any(o.name == "C/2023 A3" for o in skymap.solar_system_objects)
    assert any(o.name == "ISS" for o in skymap.solar_system_objects)


# ---------------------------------------------------------------------------
# TC-SKYMAP-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKYMAP-050")
@pytest.mark.priority("P2")
def test_tc_skymap_050_fov_and_mount_pointing_overlay(skymap, minimal_profile, mock_indi_mount):
    """SKYMAP-050: Overlay active optical train FOV rectangle and mount's live pointing on the sky map."""
    frame_mod = pytest.importorskip("galileo.planning.framing")
    fov = frame_mod.FramingAssistant.from_profile(minimal_profile).compute_fov()

    skymap.set_fov_overlay(fov)
    assert skymap.fov_overlay is not None

    skymap.set_mount(mock_indi_mount)
    assert skymap.mount_overlay_enabled is True


# ---------------------------------------------------------------------------
# TC-SKYMAP-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKYMAP-060")
@pytest.mark.priority("P2")
async def test_tc_skymap_060_slew_to_sky_map_location(skymap, mock_indi_mount):
    """SKYMAP-060: Allow slewing the connected mount directly to a location clicked on the sky map."""
    skymap.set_mount(mock_indi_mount)
    skymap._pixel_to_radec = MagicMock(return_value=(83.8221, -5.3911))

    await skymap.slew_to_pixel(x=400, y=300)
    mock_indi_mount.slew_to_coordinates.assert_called_with(ra=83.8221, dec=-5.3911)
