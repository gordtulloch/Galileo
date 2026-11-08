# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SKYMAP — Interactive Star Map / Planetarium (TC-SKYMAP-010 … TC-SKYMAP-060)."""

import pytest
from unittest.mock import MagicMock


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
    pytest.importorskip("galileo.ui.skymap")

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
    """SKYMAP-030: Overlay constellation lines and coordinate grid, each independently toggleable."""
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
    pytest.importorskip("galileo.ui.skymap")
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


class _Tiles:
    """Stands in for SurveyTiles: whatever tiles a test says it holds, and a note of what was asked for."""

    def __init__(self, held=None):
        self.held, self.wanted, self.generation = held or {}, [], 1

    def tile(self, order, npix):
        return self.held.get((order, npix))

    def want(self, keys):
        self.wanted = list(keys)


# From astropy_healpix (and in the shared vectors: Galileo-MobileConnect/api/vectors/sky/healpix.json).
_HEALPIX_KNOWN = [
    (0.0, 0.0, 0, 4),
    (0.0, 0.0, 6, 19456),
    (90.0, 0.0, 1, 23),
    (90.0, 0.0, 9, 1507328),
    (180.0, 0.0, 3, 432),
    (270.0, 0.0, 0, 7),
    (270.0, 0.0, 6, 31744),
    (359.999, 0.0, 1, 18),
    (359.999, 0.0, 9, 1201493),
    (45.0, 89.9, 3, 63),
    (135.0, -89.9, 0, 9),
    (135.0, -89.9, 6, 36864),
    (10.0, 41.8, 1, 2),
    (10.0, 41.8, 9, 173418),
    (200.0, -41.9, 3, 681),
    (300.0, 41.8, 0, 3),
    (300.0, 41.8, 6, 14745),
    (83.8, -5.4, 1, 20),
    (83.8, -5.4, 9, 1372138),
    (10.68, 41.27, 3, 42),
]


@pytest.mark.requirement("TC-SKYMAP-100")
@pytest.mark.priority("P2")
def test_tc_skymap_100_tiles_are_healpix_cells():
    """SKYMAP-100: a position's tile agrees with astropy_healpix, from pole to pole and at every level."""
    from galileo.planning import sky_survey as ss
    for ra, dec, order, npix in _HEALPIX_KNOWN:
        found, fx, fy = ss.tile_of(ra, dec, order)
        assert int(found) == npix, (ra, dec, order)
        assert 0.0 <= float(fx) <= 1.0 and 0.0 <= float(fy) <= 1.0


@pytest.mark.requirement("TC-SKYMAP-100")
@pytest.mark.priority("P2")
def test_tc_skymap_100_the_survey_lands_where_the_sky_says():
    """SKYMAP-100: a bright patch at a star's place in its tile is drawn where the map draws that star, off-centre."""
    from datetime import UTC, datetime

    import numpy as np
    from galileo.planning import sky_survey as ss
    from galileo.planning import star_atlas as sa
    ra, dec = 88.79, 7.41
    latitude, jd = 49.9, sa.julian_date(datetime(2026, 11, 7, 6, tzinfo=UTC))
    lst = sa.local_sidereal_deg(jd, -97.1)
    ra_date, dec_date = sa.precess_from_j2000(ra, dec, jd)
    alt, az = sa.equatorial_to_horizontal(ra_date, dec_date, lst, latitude)
    vp = sa.Viewport(az0=float(az) + 25.0, alt0=min(float(alt) + 15.0, 80.0), fov_deg=90.0, width=600, height=600)
    x, y, visible = vp.project(alt, az)
    assert visible and abs(float(x) - 300) > 60
    order = ss.order_for(np.degrees(1.0 / vp.scale))
    npix, fx, fy = ss.tile_of(ra, dec, order)
    image = np.zeros((512, 512, 3), np.uint8)
    row, col = int(float(fx) * 512), int(float(fy) * 512)                     # the measured orientation
    image[max(row - 12, 0):row + 12, max(col - 12, 0):col + 12] = 255
    tiles = _Tiles({(order, int(npix)): image})
    frame = ss.render_view(tiles, vp, lst, latitude, jd, step=2)
    assert frame.shape == (300, 300, 3)
    ys, xs = np.nonzero(frame[:, :, 0] > 200)
    assert len(xs), "the patch must be in view"
    assert abs(xs.mean() * 2 + 1 - float(x)) < 6 and abs(ys.mean() * 2 + 1 - float(y)) < 6


@pytest.mark.requirement("TC-SKYMAP-100")
@pytest.mark.priority("P2")
def test_tc_skymap_100_finer_with_zoom_and_coarser_until_it_arrives():
    """SKYMAP-100: zooming in asks for finer tiles; a tile not here yet is drawn from a coarser one, not left a hole."""
    import numpy as np
    from galileo.planning import sky_survey as ss
    from galileo.planning import star_atlas as sa
    assert ss.order_for(0.15) < ss.order_for(0.04) < ss.order_for(0.0005) == ss.MAX_ORDER
    assert ss.order_for(1.0) == 0

    vp = sa.Viewport(az0=180.0, alt0=45.0, fov_deg=4.0, width=200, height=200)
    tiles = _Tiles({(level, n): np.full((512, 512, 3), 90, np.uint8) for level in (0,) for n in range(12)})
    frame = ss.render_view(tiles, vp, 100.0, 49.9, 2461000.5, step=4)
    assert (frame == 90).all(), "every sample comes from the coarse tiles"
    orders = {order for order, _ in tiles.wanted}
    assert orders == {ss.order_for(np.degrees(1.0 / vp.scale))} and orders != {0}
    assert 0 < len(tiles.wanted) < 12


@pytest.mark.requirement("TC-SKYMAP-100")
@pytest.mark.priority("P2")
def test_tc_skymap_100_zoomed_in_past_three_degrees_fetches_nothing_new():
    """SKYMAP-100: a view narrower than 3 degrees draws what is held and asks for no more, so panning never waits."""
    import numpy as np
    from galileo.planning import sky_survey as ss
    from galileo.planning import star_atlas as sa
    held = {(0, n): np.full((512, 512, 3), 90, np.uint8) for n in range(12)}
    for fov, fetches in ((2.5, False), (3.5, True)):
        vp = sa.Viewport(az0=180.0, alt0=45.0, fov_deg=fov, width=200, height=200)
        tiles = _Tiles(dict(held))
        frame = ss.render_view(tiles, vp, 100.0, 49.9, 2461000.5, step=4)
        assert (frame == 90).all(), "still drawn, from the coarse tiles"
        assert bool(tiles.wanted) is fetches, fov


@pytest.mark.requirement("TC-SKYMAP-100")
@pytest.mark.priority("P2")
def test_tc_skymap_100_no_tile_means_no_failure_and_a_good_one_is_cached(tmp_path, monkeypatch):
    """SKYMAP-100: offline there's simply no tile; a download is cached, and something not a JPEG isn't."""
    from galileo.planning import sky_survey as ss
    monkeypatch.setattr(ss, "_cache_root", lambda: tmp_path)

    def offline(order, npix):
        raise OSError("no network")
    monkeypatch.setattr(ss, "_fetch_tile", offline)
    assert ss.tile_jpeg(3, 300) is None

    monkeypatch.setattr(ss, "_fetch_tile", lambda order, npix: b"<html>Service unavailable</html>")
    assert ss.tile_jpeg(3, 300) is None and not list(tmp_path.rglob("*.jpg"))

    monkeypatch.setattr(ss, "_fetch_tile", lambda order, npix: b"\xff\xd8tile")
    assert ss.tile_jpeg(3, 300) == b"\xff\xd8tile"
    assert (tmp_path / "Norder3" / "Dir0" / "Npix300.jpg").exists()
    monkeypatch.setattr(ss, "_fetch_tile", offline)
    assert ss.tile_jpeg(3, 300) == b"\xff\xd8tile"                          # from the cache now


@pytest.mark.requirement("TC-SKYMAP-100")
@pytest.mark.priority("P2")
def test_tc_skymap_100_a_mirror_that_fails_is_tried_last_and_none_at_all_is_not_a_crash(monkeypatch):
    """SKYMAP-100: one survey mirror being down costs nothing, as the other answers; no such tile isn't an outage."""
    import urllib.error
    import urllib.request

    from galileo.planning import sky_survey as ss
    monkeypatch.setattr(ss, "_mirrors", list(ss._MIRRORS))
    monkeypatch.setattr(ss, "_offline_until", 0.0)
    fetch = ss._unpatched_fetch_tile                                          # conftest keeps tests off the network
    tried = []

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"\xff\xd8ok"

    def down_then_up(request, timeout=0):
        tried.append(request.full_url)
        if request.full_url.startswith(ss._MIRRORS[0]):
            raise OSError("down")
        return Answer()
    monkeypatch.setattr(urllib.request, "urlopen", down_then_up)
    assert fetch(3, 300) == b"\xff\xd8ok" and len(tried) == 2
    assert tried[1].endswith("/Norder3/Dir0/Npix300.jpg")
    tried.clear()
    assert fetch(3, 300) == b"\xff\xd8ok" and len(tried) == 1, "the good one goes first now"

    def gone(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 404, "no", None, None)
    monkeypatch.setattr(urllib.request, "urlopen", gone)
    assert fetch(9, 1) is None

    def nothing(request, timeout=0):
        raise OSError("down")
    monkeypatch.setattr(urllib.request, "urlopen", nothing)
    with pytest.raises(OSError):
        fetch(3, 300)
    with pytest.raises(OSError):                                              # and it stops trying for a while
        fetch(3, 300)


@pytest.mark.requirement("TC-SKYMAP-100")
@pytest.mark.priority("P2")
def test_tc_skymap_100_the_map_paints_it_only_when_wanted():
    """SKYMAP-100: the option removes it, and the map paints whether or not any tile has come."""
    import numpy as np
    from galileo.ui.star_atlas import PERSISTED_TOGGLES, StarAtlasView
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    assert "show_background" in PERSISTED_TOGGLES
    view = StarAtlasView()
    view.resize(400, 300)
    view.show_stars = view.show_grid = view.show_ground = False
    view.grab()                                                               # no tiles: paints anyway
    assert view._background_frame is not None
    view._survey = _Tiles({(0, n): np.full((512, 512, 3), 200, np.uint8) for n in range(12)})
    view._background_frame = None
    image = view.grab().toImage()
    assert image.pixelColor(200, 150).red() > 100, "the survey is drawn"
    view._background_frame = None
    view.show_background = False
    image = view.grab().toImage()
    assert view._background_frame is None and image.pixelColor(200, 150).red() < 100


@pytest.mark.requirement("TC-SKYMAP-110")
@pytest.mark.priority("P2")
def test_tc_skymap_110_the_ground_hides_everything_below_the_horizon():
    """SKYMAP-110: below 0 degrees nothing of the sky shows through; above it, nothing changes; the option removes it."""
    import numpy as np
    from galileo.ui.star_atlas import StarAtlasView
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    view = StarAtlasView()
    view.resize(400, 400)
    view.show_stars = view.show_grid = view.show_dsos = view.show_bodies = view.show_labels = False
    view.daylight_sky = False
    view.view.alt0, view.view.fov_deg = 0.0, 60.0                             # the horizon across the middle
    above, below = (200, 60), (200, 340)

    view._survey = _Tiles({(0, n): np.full((512, 512, 3), 0, np.uint8) for n in range(12)})
    dark = view.grab().toImage()
    view._survey = _Tiles({(0, n): np.full((512, 512, 3), 200, np.uint8) for n in range(12)})
    view._background_frame = None
    bright = view.grab().toImage()
    assert bright.pixelColor(*above).red() > dark.pixelColor(*above).red() + 100, "the sky shows above"
    assert bright.pixelColor(*below) == dark.pixelColor(*below), "and not at all below"

    view.show_ground = False
    view._background_frame = None
    assert view.grab().toImage().pixelColor(*below).red() > 100, "without the ground, the sky carries on"


@pytest.mark.requirement("TC-SKYMAP-110")
@pytest.mark.priority("P2")
def test_tc_skymap_110_the_landscape_recedes_and_follows_the_daylight():
    """SKYMAP-110: patches are coarse close by and fine in the distance, there's no glitter at the horizon, and day is lighter."""
    import numpy as np
    from galileo.planning import star_atlas as sa
    az = np.linspace(0.0, 90.0, 2000)
    close = sa.landscape_rgb(np.full_like(az, -60.0), az, 0.0).astype(float)
    assert close.std(axis=0).sum() > 0.5, "it's a landscape, not a flat colour"
    edge = sa.landscape_rgb(np.full_like(az, -0.2), az, 0.0).astype(float)
    assert edge.std(axis=0).sum() < close.std(axis=0).sum(), "what's too fine to see is flat"
    assert sa.landscape_rgb(-30.0, 10.0, 1.0).sum() > 2 * sa.landscape_rgb(-30.0, 10.0, 0.0).sum()
    assert sa.landscape_rgb(-0.2, 10.0, 0.0).sum() > sa.landscape_rgb(-70.0, 10.0, 0.0).sum(), "haze at the horizon"
