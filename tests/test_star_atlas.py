"""Star Atlas planetarium (``galileo.planning.star_atlas``, ``galileo.ui.star_atlas``, the Star Atlas page).

The Star Atlas sidebar section shows a basic planetarium: the sky maths is plain
numpy and is tested directly; the view and page are built offscreen. Catalog
loading is patched to the built-in offline star list so no test touches the
network. Requirement IDs are the SKYMAP ones the planetarium partly satisfies
(SKYMAP-010 render, SKYMAP-020 identify / centre-and-track, SKYMAP-030 constellation
boundaries); constellation figures/art
lines, comets/asteroids/satellites and the FOV/mount overlay are not built.
"""

from __future__ import annotations

import datetime as dt
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from galileo.planning import star_atlas as sa


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_sidereal_time_and_julian_date():
    """SKYMAP-010: the sky is computed for the configured time — J2000.0 has JD 2451545 and GMST 280.4606°."""
    assert sa.julian_date(dt.datetime(2000, 1, 1, 12)) == 2451545.0
    assert sa.local_sidereal_deg(2451545.0, 0.0) == pytest.approx(280.46061837)
    assert sa.local_sidereal_deg(2451545.0, 10.0) == pytest.approx(290.46061837)


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_horizontal_coordinates():
    """SKYMAP-010: a star on the meridian at the observer's declination is at the zenith; Polaris sits at ~latitude."""
    alt, _ = sa.equatorial_to_horizontal(np.array([120.0]), np.array([40.0]), 120.0, 40.0)
    assert alt[0] == pytest.approx(90.0)
    alt, az = sa.equatorial_to_horizontal(np.array([37.95]), np.array([89.26]), 10.0, 45.0)
    assert abs(alt[0] - 45.0) < 1.0
    assert min(az[0], 360.0 - az[0]) < 2.0          # due north
    east_alt, east_az = sa.equatorial_to_horizontal(np.array([0.0]), np.array([0.0]), 270.0, 0.0)  # H = +270 = -90°
    assert east_alt[0] == pytest.approx(0.0, abs=1e-9) and east_az[0] == pytest.approx(90.0)  # rising in the east


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_horizontal_round_trip():
    """SKYMAP-010: horizontal → equatorial inverts equatorial → horizontal."""
    alt, az = sa.equatorial_to_horizontal(np.array([200.0]), np.array([-20.0]), 150.0, 51.0)
    ra, dec = sa.horizontal_to_equatorial(alt[0], az[0], 150.0, 51.0)
    assert ra == pytest.approx(200.0) and dec == pytest.approx(-20.0)


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_precession():
    """SKYMAP-010: precession moves J2000 coordinates ~50″/yr — Polaris' RA changes ~0.4° by 2026, a star at J2000 stays put."""
    ra, dec = sa.precess_from_j2000(np.array([100.0]), np.array([20.0]), 2451545.0)
    assert ra[0] == pytest.approx(100.0) and dec[0] == pytest.approx(20.0)
    ra, _ = sa.precess_from_j2000(np.array([100.0]), np.array([20.0]), 2451545.0 + 26 * 365.25)
    assert 0.3 < ra[0] - 100.0 < 0.5


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_projection_round_trip_and_east_left():
    """SKYMAP-010: the stereographic projection inverts, and facing south east is on the left."""
    vp = sa.Viewport(az0=180.0, alt0=35.0, fov_deg=80.0, width=800, height=600)
    x, y, vis = vp.project(np.array([35.0, 50.0, 10.0]), np.array([180.0, 200.0, 150.0]))
    assert vis.all()
    assert x[0] == pytest.approx(400.0) and y[0] == pytest.approx(300.0)   # centre maps to centre
    alt, az = vp.unproject(x, y)
    assert alt == pytest.approx([35.0, 50.0, 10.0]) and az == pytest.approx([180.0, 200.0, 150.0])
    west, _, _ = vp.project(np.array([35.0]), np.array([200.0]))            # az 200° is west of south
    east, _, _ = vp.project(np.array([35.0]), np.array([160.0]))            # az 160° is east of south
    assert east[0] < 400.0 < west[0]


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_sun_position_at_the_2000_march_equinox():
    """SKYMAP-010: the Sun is near RA 0h, Dec 0° at the March 2000 equinox (solar-system positions need no download)."""
    bodies = {b["name"]: b for b in sa.solar_system_positions(dt.datetime(2000, 3, 20, 7, 35))}
    assert {"Sun", "Moon", "Mars", "Jupiter"} <= set(bodies)
    sun = bodies["Sun"]
    assert min(sun["ra_deg"], 360.0 - sun["ra_deg"]) < 1.0 and abs(sun["dec_deg"]) < 0.5


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_catalog_falls_back_to_named_stars_offline(tmp_path, monkeypatch):
    """SKYMAP-010: with no cache and no network the atlas still has the brightest named stars, and doesn't cache the fallback."""
    monkeypatch.setattr(sa, "_cache_path", lambda: tmp_path / "stars.json")
    monkeypatch.setattr(sa, "_fetch_bsc", lambda: None)
    cat = sa.load_star_catalog()
    assert "Sirius" in cat.names and "Polaris" in cat.names
    assert cat.mag.min() == pytest.approx(-1.46)
    assert not (tmp_path / "stars.json").exists()


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_catalog_is_cached_and_reloaded(tmp_path, monkeypatch):
    """SKYMAP-010: a fetched catalog is cached and read back without another fetch."""
    fetched = sa.StarCatalog(np.array([10.0, 20.0]), np.array([1.0, 2.0]), np.array([3.0, 4.0]),
                             ["Foo", ""], ["", "9Bar Baz"])
    calls = []
    monkeypatch.setattr(sa, "_cache_path", lambda: tmp_path / "stars.json")
    monkeypatch.setattr(sa, "_fetch_bsc", lambda: calls.append(1) or fetched)
    first = sa.load_star_catalog()
    second = sa.load_star_catalog()
    assert len(calls) == 1
    assert second.names == ["Foo", ""] and second.designations == ["", "9Bar Baz"]
    assert second.ra.tolist() == first.ra.tolist() == [10.0, 20.0]


def _box(code="ORI", ra0=80.0, ra1=90.0, dec0=0.0, dec1=10.0):
    """One rectangular B1875 'constellation' (edges on constant RA/Dec, like the real boundaries)."""
    return [code] * 4, [ra0, ra1, ra1, ra0], [dec0, dec0, dec1, dec1]


@pytest.mark.requirement("TC-SKYMAP-030")
@pytest.mark.priority("MVP")
def test_star_atlas_precess_to_j2000_inverts_precession():
    """SKYMAP-030: constellation boundaries are B1875 vertices, converted to J2000 by inverting the precession."""
    ra, dec = sa.precess_from_j2000(np.array([10.0, 200.0, 300.0]), np.array([-40.0, 5.0, 70.0]), sa._B1875_JD)
    back_ra, back_dec = sa.precess_to_j2000(ra, dec, sa._B1875_JD)
    assert back_ra == pytest.approx([10.0, 200.0, 300.0]) and back_dec == pytest.approx([-40.0, 5.0, 70.0])


@pytest.mark.requirement("TC-SKYMAP-030")
@pytest.mark.priority("MVP")
def test_star_atlas_boundaries_are_closed_outlines_along_constant_ra_dec():
    """SKYMAP-030: each outline is closed, its edges are densified along lines of constant RA/Dec, and it is named."""
    codes, ra, dec = _box()
    b = sa.build_boundaries(codes, ra, dec)
    assert len(b) == 1 and b.names == ["Orion"]
    ra_j, dec_j = b.ra[b.outline(0)], b.dec[b.outline(0)]
    assert (ra_j[0], dec_j[0]) == (ra_j[-1], dec_j[-1])           # closed
    assert len(ra_j) > 30                                          # 40° of edge at ≤1° steps
    # B1875 → J2000 moves the box ~1.6° east and ~0.3° north (near RA 5h, Dec +5°).
    assert 1.0 < ra_j.min() - 80.0 < 3.0
    assert 80.0 < b.center_ra[0] + 0.0 < 95.0 and 0.0 < b.center_dec[0] < 12.0


@pytest.mark.requirement("TC-SKYMAP-030")
@pytest.mark.priority("MVP")
def test_star_atlas_boundary_edges_wrap_through_ra_zero():
    """SKYMAP-030: an edge crossing RA 0°/360° is interpolated the short way round, not across the whole sky."""
    b = sa.build_boundaries(["PEG"] * 4, [350.0, 10.0, 10.0, 350.0], [0.0, 0.0, 10.0, 10.0])
    ra_j = b.ra[b.outline(0)]
    d = np.abs((np.diff(ra_j) + 180.0) % 360.0 - 180.0)
    assert d.max() < 2.0


@pytest.mark.requirement("TC-SKYMAP-030")
@pytest.mark.priority("MVP")
def test_star_atlas_boundaries_cached_and_offline_empty(tmp_path, monkeypatch):
    """SKYMAP-030: fetched vertices are cached and rebuilt from the cache; offline with no cache draws none."""
    monkeypatch.setattr(sa, "_boundary_cache_path", lambda: tmp_path / "bounds.json")
    monkeypatch.setattr(sa, "_fetch_boundaries", lambda: None)
    assert len(sa.load_constellation_boundaries()) == 0
    assert not (tmp_path / "bounds.json").exists()
    codes, ra, dec = _box("UMA")
    calls = []
    monkeypatch.setattr(sa, "_fetch_boundaries", lambda: calls.append(1) or {"cst": codes, "ra": ra, "dec": dec})
    assert sa.load_constellation_boundaries().names == ["Ursa Major"]
    monkeypatch.setattr(sa, "_fetch_boundaries", lambda: pytest.fail("should read the cache"))
    assert sa.load_constellation_boundaries().names == ["Ursa Major"] and len(calls) == 1


def test_star_atlas_every_boundary_code_has_a_name():
    """The IAU name table covers all 88 constellations (Serpens is two outlines)."""
    assert len(set(sa.CONSTELLATION_NAMES.values())) == 88


# --- the widget -----------------------------------------------------------------

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def view():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.ui.star_atlas import StarAtlasView
    v = StarAtlasView()
    v.resize(800, 600)
    v.daylight_sky = False
    v.set_catalogs(sa._fallback_catalog(), [])
    # Put Vega on the meridian at 40°N so it is almost at the zenith.
    when = dt.datetime(2024, 6, 1, 3, 0)
    gmst = sa.local_sidereal_deg(sa.julian_date(when), 0.0)
    lon = (279.235 - gmst + 180.0) % 360.0 - 180.0
    v.latitude, v.longitude = 40.0, lon
    v.set_time(when)
    yield v
    v.close()


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_view_renders(view):
    """SKYMAP-010: the view paints the sky for the configured place and time."""
    view.center_on_altaz(60.0, 180.0)
    image = view.grab().toImage()
    assert not image.isNull() and image.width() == 800
    colours = {image.pixel(x, y) for x in range(0, 800, 40) for y in range(0, 600, 40)}
    assert len(colours) > 1     # not a flat fill: grid, ground, stars


@pytest.mark.requirement("TC-SKYMAP-030")
@pytest.mark.priority("MVP")
def test_star_atlas_view_draws_constellation_boundaries_when_enabled(view):
    """SKYMAP-030: constellation boundaries are drawn, and the toggle switches them off."""
    codes, ra, dec = _box(ra0=270.0, ra1=290.0, dec0=30.0, dec1=48.0)
    view.set_catalogs(sa._fallback_catalog(), [], sa.build_boundaries(codes, ra, dec))
    view.show_grid = False
    view.show_labels = False
    view.center_on_altaz(view._bnd_center_alt[0], view._bnd_center_az[0])
    view.set_fov(60.0)

    def boundary_pixels() -> int:
        """Pixels with the boundary line's purple hue (red and blue both well above green);
        stars, sky and horizon never have it."""
        image = view.grab().toImage()
        count = 0
        for x in range(0, 800, 2):
            for y in range(0, 600, 2):
                c = image.pixelColor(x, y)
                if c.red() - c.green() > 25 and c.blue() - c.green() > 25:
                    count += 1
        return count

    assert boundary_pixels() > 100
    view.set_option("show_boundaries", False)
    assert boundary_pixels() == 0


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_view_pans_and_zooms(view):
    """SKYMAP-010: the view is pannable and zoomable — zoom is clamped, and altitude can't pass the zenith."""
    view.set_fov(30.0)
    assert view.view.fov_deg == 30.0
    view.set_fov(0.01)
    assert view.view.fov_deg == 0.5
    view.set_fov(1000.0)
    assert view.view.fov_deg == 150.0
    view.center_on_altaz(120.0, 400.0)
    assert view.view.alt0 == 90.0 and view.view.az0 == pytest.approx(40.0)


@pytest.mark.requirement("TC-SKYMAP-020")
@pytest.mark.priority("MVP")
def test_star_atlas_click_identifies_object(view):
    """SKYMAP-020: clicking an object on the map identifies it."""
    vega = view.find("vega")
    assert vega is not None and vega["name"] == "Vega" and vega["alt"] > 85.0
    view.center_on(vega)
    picked = view.object_at(400, 300)
    assert picked is not None and picked["name"] == "Vega"
    assert view.object_at(5, 5) is None
    seen = []
    view.objectSelected.connect(seen.append)
    view.select(picked)
    assert seen and seen[0]["name"] == "Vega" and view.selected is picked


@pytest.mark.requirement("TC-SKYMAP-020")
@pytest.mark.priority("MVP")
def test_star_atlas_double_click_centres_and_tracks(view):
    """SKYMAP-020: centring an object tracks it — the view follows it as time advances."""
    vega = view.find("Vega")
    view.center_on(vega, track=True)
    az_before = view.view.az0
    view.set_time(view.when + dt.timedelta(hours=3))
    alt, az = view._altaz_of(vega)
    assert view.view.az0 == pytest.approx(az % 360.0) and view.view.az0 != pytest.approx(az_before)
    assert view.view.alt0 == pytest.approx(np.clip(alt, -10.0, 90.0))


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_daylight_hides_faint_stars(view):
    """SKYMAP-010: with the Sun up, the sky washes out and only the brightest stars remain."""
    view.daylight_sky = True
    view.set_time(dt.datetime(2024, 6, 1, 20, 0))   # local noon-ish for the Vega-meridian site
    night = view.mag_limit
    assert view.effective_mag_limit() <= night
    assert view._sun_alt > 0 and view.effective_mag_limit() < 0


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_find_solar_system_body(view):
    """SKYMAP-010: the Sun, Moon and planets are on the map and can be found by name."""
    jupiter = view.find("jupiter")
    assert jupiter is not None and jupiter["type"] == "Planet"
    assert view.find("no such thing") is None


# --- the Star Atlas page ----------------------------------------------------------

@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(sa, "load_star_catalog", sa._fallback_catalog)
    from galileo.library.database import db, init_db
    init_db(tmp_path / "star_atlas_page.db")
    from galileo.ui.app_window import AppWindow
    win = AppWindow()
    win.app = app
    yield win
    win._window.close()
    db.close()


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_section_sits_above_planning():
    """The Star Atlas section (the planetarium) is listed directly above Planning (the catalog lookup formerly labelled Sky Atlas)."""
    from galileo.ui.app_window import PRIMARY_SECTIONS
    ids = [s[0] for s in PRIMARY_SECTIONS]
    assert ids[ids.index("sky_atlas") - 1] == "star_atlas"
    labels = {s[0]: s[1] for s in PRIMARY_SECTIONS}
    assert labels["star_atlas"] == "Star Atlas" and labels["sky_atlas"] == "Planning"


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_page_shows_the_sky_at_the_observatory_site(window):
    """SKYMAP-010: the Star Atlas page hosts the sky view, using the selected Pier's Observatory as its site."""
    from galileo.observatory import create_observatory, create_pier
    from galileo.ui.star_atlas import StarAtlasView
    window._current_pier = create_pier(create_observatory("Dark Site", latitude=-33.9, longitude=151.2), "Pier A")
    window._on_pier_changed()
    views = window._window.findChildren(StarAtlasView)
    assert len(views) == 1
    assert views[0].latitude == pytest.approx(-33.9) and views[0].longitude == pytest.approx(151.2)
    assert views[0].grab().toImage().width() > 0
