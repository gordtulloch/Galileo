# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Star Atlas planetarium (``galileo.planning.star_atlas``, ``galileo.ui.star_atlas``, the Star Atlas page).

The Star Atlas sidebar section shows a basic planetarium: the sky maths is plain
numpy and is tested directly; the view and page are built offscreen. Catalog
loading is patched to the built-in offline star list so no test touches the
network. Requirement IDs are the SKYMAP ones the planetarium partly satisfies
(SKYMAP-010 render, SKYMAP-020 identify / centre-and-track, SKYMAP-030 constellation
boundaries and outlines); comets/asteroids/satellites and the FOV/mount overlay
are not built.
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


@pytest.mark.requirement("TC-SKYMAP-030")
@pytest.mark.priority("MVP")
def test_star_atlas_constellation_lines_are_densified_along_great_circles():
    """SKYMAP-030: outline segments are sampled along the great circle, RA -180..180 is normalised, and short/degenerate lines are dropped."""
    lines = sa.build_constellation_lines([[[-10.0, 0.0], [10.0, 0.0]], [[5.0, 5.0]]])
    assert len(lines) == 1
    ra, dec = lines.ra[lines.polyline(0)], lines.dec[lines.polyline(0)]
    assert ra[0] == pytest.approx(350.0) and ra[-1] == pytest.approx(10.0)
    assert 11 <= len(ra) <= 12                              # 20° at a 2° step (float round-off may add one), plus the end point
    assert np.abs((np.diff(ra) + 180.0) % 360.0 - 180.0).max() <= 2.0 + 1e-6
    assert dec == pytest.approx(np.zeros(len(dec)), abs=1e-9)   # the equator is a great circle
    assert len(sa.build_constellation_lines([])) == 0


@pytest.mark.requirement("TC-SKYMAP-030")
@pytest.mark.priority("MVP")
def test_star_atlas_constellation_lines_cached_and_offline_empty(tmp_path, monkeypatch):
    """SKYMAP-030: fetched outlines are cached and rebuilt from the cache; offline with no cache draws none."""
    monkeypatch.setattr(sa, "_lines_cache_path", lambda: tmp_path / "lines.json")
    monkeypatch.setattr(sa, "_fetch_constellation_lines", lambda: None)
    assert len(sa.load_constellation_lines()) == 0
    assert not (tmp_path / "lines.json").exists()
    calls = []
    monkeypatch.setattr(sa, "_fetch_constellation_lines",
                        lambda: calls.append(1) or [[[80.0, 0.0], [85.0, 5.0], [90.0, 0.0]]])
    assert len(sa.load_constellation_lines()) == 1
    monkeypatch.setattr(sa, "_fetch_constellation_lines", lambda: pytest.fail("should read the cache"))
    assert len(sa.load_constellation_lines()) == 1 and len(calls) == 1


@pytest.mark.requirement("TC-SKYMAP-030")
@pytest.mark.priority("MVP")
def test_star_atlas_boundaries_carry_iau_abbreviations():
    """SKYMAP-030: each outline keeps its three-letter IAU abbreviation next to its name (both Serpens parts are SER)."""
    codes = ["ORI"] * 4 + ["SER1"] * 4 + ["SER2"] * 4
    ra = [80.0, 90.0, 90.0, 80.0] * 3
    dec = [0.0, 0.0, 10.0, 10.0] * 3
    b = sa.build_boundaries(codes, ra, dec)
    assert b.codes == ["ORI", "SER", "SER"] and b.names == ["Orion", "Serpens", "Serpens"]
    assert sa.ConstellationBoundaries.empty().codes == []


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


@pytest.mark.requirement("TC-SKYMAP-030")
@pytest.mark.priority("MVP")
def test_star_atlas_constellation_names_shown_without_boundaries_or_outlines(view):
    """SKYMAP-030: constellation names are labels, so they stay when the boundary and outline layers are off — until Labels is switched off."""
    codes, ra, dec = _box(ra0=270.0, ra1=290.0, dec0=30.0, dec1=48.0)
    view.set_catalogs(sa._fallback_catalog(), [], sa.build_boundaries(codes, ra, dec))
    view.show_grid = False
    view.show_boundaries = False
    view.show_lines = False
    view.center_on_altaz(view._bnd_center_alt[0], view._bnd_center_az[0])
    view.set_fov(60.0)

    def label_pixels() -> int:
        """Pixels with the constellation-label purple (red and blue both well above green)."""
        image = view.grab().toImage()
        return sum(1 for x in range(0, 800, 1) for y in range(0, 600, 1)
                   if (c := image.pixelColor(x, y)).red() - c.green() > 25 and c.blue() - c.green() > 25)

    view.show_labels = True
    assert label_pixels() > 0
    view.show_labels = False
    assert label_pixels() == 0


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
    assert ids[ids.index("planning") - 1] == "star_atlas"
    labels = {s[0]: s[1] for s in PRIMARY_SECTIONS}
    assert labels["star_atlas"] == "Star Atlas" and labels["planning"] == "Planning"


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_planning_and_science_sections_carry_their_own_menus(window):
    """Planning opens onto Targets (the catalog lookup), Sessions and Scheduler; Science holds Variable Stars;
    Library holds AstroFiler's screens. None of those is a top-level section any more."""
    from galileo.ui.app_window import LIBRARY_ITEMS, PLANNING_ITEMS, PRIMARY_SECTIONS, SCIENCE_ITEMS
    ids = [s[0] for s in PRIMARY_SECTIONS]
    assert ids == ["equipment", "star_atlas", "planning", "framing", "imaging", "guiding", "focus", "solve", "library", "science"]
    assert [i[:2] for i in PLANNING_ITEMS] == [("targets", "Targets"), ("sessions", "Sessions"), ("scheduler", "Scheduler")]
    assert [i[:2] for i in SCIENCE_ITEMS] == [("variable_stars", "Variable Stars")]
    assert [i[:2] for i in LIBRARY_ITEMS] == [
        ("images", "Images"), ("sessions", "Sessions"), ("mappings", "Mappings"), ("dedup", "Dedup"), ("merge", "Merge Objects"), ("cloud", "Cloud"),
    ]

    from PySide6 import QtWidgets
    # Planning, Science, Library and Options each carry a secondary menu.
    assert len(window._window.findChildren(QtWidgets.QWidget, "SubmenuPage")) == 4
    menus = [
        [" ".join(b.text().split()) for b in c.findChildren(QtWidgets.QToolButton)]
        for c in window._nav_columns if c.objectName() == "SecondarySidebar"
    ]
    assert ["Targets", "Sessions", "Scheduler"] in menus and ["Variable Stars"] in menus
    assert ["Images", "Sessions", "Mappings", "Dedup", "Merge Objects", "Cloud"] in menus


@pytest.mark.requirement("TC-UI-020")
@pytest.mark.priority("P2")
def test_options_has_a_settings_placeholder_for_each_primary_section(window):
    """Options opens onto one settings page per primary sidebar section, in the same order,
    each a titled placeholder until its real settings are built (Library's are real: see test_lib.py)."""
    from PySide6 import QtWidgets
    from galileo.ui.app_window import OPTIONS_ITEMS, PRIMARY_SECTIONS
    assert [i[:2] for i in OPTIONS_ITEMS] == [s[:2] for s in PRIMARY_SECTIONS]

    menus = [
        [" ".join(b.text().split()) for b in c.findChildren(QtWidgets.QToolButton)]
        for c in window._nav_columns if c.objectName() == "SecondarySidebar"
    ]
    assert [s[1] for s in PRIMARY_SECTIONS] in menus

    titles = {w.text() for w in window._window.findChildren(QtWidgets.QLabel, "PageTitle")}
    for section_id, label, _icon in PRIMARY_SECTIONS:
        if section_id != "library":
            assert f"{label} settings" in titles


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


@pytest.mark.requirement("TC-SKYMAP-030")
@pytest.mark.priority("MVP")
def test_star_atlas_view_draws_constellation_lines_independently_of_boundaries(view):
    """SKYMAP-030: constellation outlines are drawn, and their toggle is independent of the boundary toggle."""
    lines = sa.build_constellation_lines([[[270.0, 35.0], [280.0, 45.0], [290.0, 35.0]]])
    view.set_catalogs(sa._fallback_catalog(), [], None, lines)
    view.show_grid = False
    view.show_labels = False
    alt, az = view._altaz_arrays(np.array([280.0]), np.array([40.0]))
    view.center_on_altaz(float(alt[0]), float(az[0]))
    view.set_fov(60.0)

    def line_pixels() -> int:
        """Pixels with the outline's teal hue (green and blue well above red); stars, sky and horizon never have it."""
        image = view.grab().toImage()
        count = 0
        for x in range(0, 800, 2):
            for y in range(0, 600, 2):
                c = image.pixelColor(x, y)
                if c.green() - c.red() > 40 and c.blue() - c.red() > 30:
                    count += 1
        return count

    assert line_pixels() > 50
    view.set_option("show_boundaries", False)
    assert line_pixels() > 50                       # outlines don't depend on the boundary toggle
    view.set_option("show_lines", False)
    assert line_pixels() == 0


_NGC_CSV = """Name;Type;RA;Dec;Const;MajAx;MinAx;PosAng;B-Mag;V-Mag;J-Mag;H-Mag;K-Mag;SurfBr;Hubble;Pax;Pm-RA;Pm-Dec;RadVel;Redshift;Cstar U-Mag;Cstar B-Mag;Cstar V-Mag;M;NGC;IC;Cstar Names;Identifiers;Common names;NED notes;OpenNGC notes;Sources
NGC0224;G;00:42:44.35;+41:16:08.6;And;177.83;69.66;35;4.29;3.44;;;;;;;;;;;;;;031;;;;UGC 00454;Andromeda Galaxy;;;
NGC7000;HII;20:59:17.14;+44:31:43.6;Cep;120.00;30.00;;4.00;;;;;;;;;;;;;;;;;;;C 020,LBN 373;North America Nebula;;;
NGC0001;G;00:07:15.84;+27:42:29.1;Peg;1.57;1.07;112;13.69;;;;;;;;;;;;;;;;;;;;;;;
NGC0002;Dup;00:07:16.00;+27:42:00.0;Peg;;;;;;;;;;;;;;;;;;;;;;;;;;;
IC0001;**;00:08:27.05;+27:43:03.6;Peg;;;;;;;;;;;;;;;;;;;;;;;;;;;;
"""
_ADDENDUM_CSV = """Name;Type;RA;Dec;Const;MajAx;MinAx;PosAng;B-Mag;V-Mag;J-Mag;H-Mag;K-Mag;SurfBr;Hubble;Pax;Pm-RA;Pm-Dec;RadVel;Redshift;Cstar U-Mag;Cstar B-Mag;Cstar V-Mag;M;NGC;IC;Cstar Names;Identifiers;Common names;NED notes;OpenNGC notes;Sources
C099;DrkN;12:31:19.0;-63:44:36;Cru;;;;;;;;;;;;;;;;;;;;;;;;Coalsack Nebula;;;
M040;**;12:22:16.1;+58:05:04;UMa;;;;;8.00;;;;;;;;;;;;;;040;;;;WDS J12222+5805AB;;;;
"""


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_deep_sky_catalog_parses_openngc_with_messier_and_caldwell():
    """SKYMAP-010: the deep-sky catalog keeps real positions, types and magnitudes, and tags Messier/Caldwell/NGC membership."""
    from galileo.planning import sky_atlas as sky
    objs = {o.primary_name: o for o in sky._parse_openngc(_NGC_CSV, _ADDENDUM_CSV)}
    assert "NGC 2" not in objs and "IC 1" in objs           # duplicates are skipped
    m31 = objs["M31"]
    assert m31.designations[:2] == ["M31", "NGC 224"] and "Andromeda Galaxy" in m31.designations
    assert m31.ra_deg == pytest.approx(10.6848, abs=1e-3) and m31.dec_deg == pytest.approx(41.2686, abs=1e-3)
    assert m31.object_type is sky.ObjectType.GALAXY and m31.magnitude == 3.44 and m31.size_arcmin == 177.83
    assert objs["NGC 1"].magnitude == 13.69                 # falls back to the B magnitude
    assert "C 20" in objs["NGC 7000"].designations          # "C 020" normalised
    assert sky.catalogs_of(m31) == {"Messier", "NGC"}
    assert sky.catalogs_of(objs["NGC 7000"]) == {"Caldwell", "NGC"}
    assert sky.catalogs_of(objs["C 99"]) == {"Caldwell"} and sky.catalogs_of(objs["M40"]) == {"Messier"}
    assert sky.catalogs_of(objs["IC 1"]) == set()
    assert objs["M40"].designations.count("M40") == 1


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_view_draws_only_the_selected_deep_sky_catalogs(view):
    """SKYMAP-010: only deep-sky objects from the chosen catalogs are drawn; objects with no magnitude survive only in Messier/Caldwell."""
    from galileo.planning.sky_atlas import DeepSkyObject, ObjectType

    def dso(name, designations, mag):
        return DeepSkyObject(name, designations, 279.0, 40.0, ObjectType.GALAXY, mag, 5.0)

    dsos = [dso("M1", ["M1", "NGC 1952"], 8.0), dso("C 9", ["C 9"], 99.0),
            dso("NGC 500", ["NGC 500"], 10.0), dso("NGC 501", ["NGC 501"], 99.0)]
    view.set_catalogs(sa._fallback_catalog(), dsos)
    assert view.dso_catalogs == {"Messier"}                  # Messier is on by default
    assert view.dso_catalog_counts() == {"Messier": 1, "Caldwell": 1, "NGC": 2}
    assert len(view._dsos) == 3                               # NGC 501 has no magnitude and is in no curated list
    view.dso_mag_limit = 16.0
    view.center_on_altaz(85.0, 0.0)
    view.set_fov(150.0)

    def drawn() -> set[str]:
        idx, _, _ = view._sets(view._viewport())["dsos"]
        return {view._dsos[i].primary_name for i in idx}

    view.show_ground = False
    assert drawn() == {"M1"}
    view.set_dso_catalogs({"Messier", "Caldwell"})
    assert drawn() == {"M1", "C 9"}
    view.set_dso_catalogs({"NGC"})
    assert drawn() == {"M1", "NGC 500"}                       # M1 is also NGC 1952
    view.set_dso_catalogs(set())
    assert drawn() == set()


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_page_catalog_list_adds_and_removes_catalogs(window):
    """SKYMAP-010: the Star Atlas panel has a Catalogs label with a "+" button; a listed catalog can be removed again."""
    from galileo.ui.star_atlas import StarAtlasView
    view = window._window.findChildren(StarAtlasView)[0]
    buttons = window._window.findChildren(QtWidgets.QToolButton)
    add = next(b for b in buttons if b.text() == "+" and b.toolTip().startswith("Add a deep-sky catalog"))
    assert add.isEnabled() and view.dso_catalogs == {"Messier"}
    remove = next(b for b in buttons if b.text() == "×" and b.toolTip() == "Remove Messier from the map")
    remove.click()
    assert view.dso_catalogs == set()


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_remembers_toggles_and_catalogs_between_runs(window):
    """SKYMAP-010: the Star Atlas remembers which options are ticked and which deep-sky catalogs are on the map."""
    from galileo.ui.star_atlas import StarAtlasView, load_display_prefs
    view = window._window.findChildren(StarAtlasView)[0]
    assert load_display_prefs() == {}                     # nothing is written until the user changes something
    grid = next(b for b in window._window.findChildren(QtWidgets.QCheckBox) if b.text() == "Coordinate grid")
    grid.setChecked(False)
    add = next(b for b in window._window.findChildren(QtWidgets.QToolButton)
               if b.text() == "+" and b.toolTip().startswith("Add a deep-sky catalog"))
    remove = next(b for b in window._window.findChildren(QtWidgets.QToolButton)
                  if b.text() == "×" and b.toolTip() == "Remove Messier from the map")
    remove.click()
    assert add.isEnabled()
    saved = load_display_prefs()
    assert saved["show_grid"] is False and saved["show_labels"] is True and saved["dso_catalogs"] == []

    from galileo.ui.app_window import AppWindow
    reopened = AppWindow()
    try:
        view2 = reopened._window.findChildren(StarAtlasView)[0]
        assert view2.show_grid is False and view2.dso_catalogs == set()
        box = next(b for b in reopened._window.findChildren(QtWidgets.QCheckBox) if b.text() == "Coordinate grid")
        assert not box.isChecked()
    finally:
        reopened._window.close()


@pytest.mark.requirement("TC-SKYMAP-010")
@pytest.mark.priority("MVP")
def test_star_atlas_display_prefs_ignore_bad_entries(tmp_path, monkeypatch):
    """SKYMAP-010: an unreadable or partly invalid options file falls back to the defaults instead of breaking the page."""
    import galileo.ui.star_atlas as ui
    path = tmp_path / "prefs.json"
    monkeypatch.setattr(ui, "_prefs_path", lambda: path)
    path.write_text("not json", encoding="utf-8")
    assert ui.load_display_prefs() == {}
    path.write_text('{"show_grid": "yes", "show_labels": false, "dso_catalogs": ["NGC", "Bogus"], "mag_limit": 1}',
                    encoding="utf-8")
    assert ui.load_display_prefs() == {"show_labels": False, "dso_catalogs": ["NGC"]}


@pytest.mark.requirement("TC-SKYMAP-020")
@pytest.mark.priority("MVP")
def test_star_atlas_right_click_offers_the_object_under_the_cursor(view):
    """SKYMAP-020: right-clicking the map selects the object under the cursor and asks for a context menu for it."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    view.center_on(view.find("Vega"))
    seen = []
    view.contextMenuRequested.connect(lambda obj, pos: seen.append((obj, pos)))
    view.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(400, 300), QPoint(1400, 900)))
    assert seen[-1][0]["name"] == "Vega" and view.selected["name"] == "Vega" and seen[-1][1] == QPoint(1400, 900)
    view.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(5, 5), QPoint(1005, 605)))
    assert seen[-1][0] is None


class _FakeMount:
    def __init__(self, system):
        self.system, self.calls = system, []

    async def get_status(self):
        return {"equatorial_system": self.system}

    async def slew_to_coordinates(self, ra, dec):
        self.calls.append(("goto", ra, dec))

    async def sync_to_coordinates(self, ra, dec):
        self.calls.append(("sync", ra, dec))


@pytest.mark.requirement("TC-SKYMAP-020")
@pytest.mark.priority("MVP")
def test_star_atlas_goto_and_sync_command_the_connected_mount(window):
    """SKYMAP-020: the Goto / Sync menu items slew the current Pier's mount to, or sync it on, the chosen object."""
    vega = {"name": "Vega", "ra_deg": 279.2347, "dec_deg": 38.7837, "alt": 60.0}
    mount = _FakeMount("J2000")
    window._device_pages["mount"]["adapter"] = mount
    assert window._mount_to_object("goto", vega) and window._mount_to_object("sync", vega)
    assert mount.calls == [("goto", 279.2347, 38.7837), ("sync", 279.2347, 38.7837)]   # J2000 mount: sent as is

    mount = _FakeMount("JNOW")
    window._device_pages["mount"]["adapter"] = mount
    assert window._mount_to_object("goto", vega)
    _, ra, dec = mount.calls[0]
    assert 0.0 < abs(ra - 279.2347) < 1.0 and 0.0 < abs(dec - 38.7837) < 0.5           # precessed to the epoch of date


@pytest.mark.requirement("TC-SKYMAP-020")
@pytest.mark.priority("MVP")
def test_star_atlas_goto_refused_without_mount_or_below_horizon(window):
    """SKYMAP-020: nothing is sent when no mount is connected or the object is below the horizon."""
    vega = {"name": "Vega", "ra_deg": 279.2347, "dec_deg": 38.7837, "alt": 60.0}
    window._device_pages["mount"]["adapter"] = None
    assert window._mount_to_object("goto", vega) is False
    mount = _FakeMount("JNOW")
    window._device_pages["mount"]["adapter"] = mount
    assert window._mount_to_object("goto", {**vega, "alt": -5.0}) is False
    assert window._mount_to_object("sync", {**vega, "alt": -5.0}) is False
    assert mount.calls == []


@pytest.mark.requirement("TC-SKYMAP-020")
@pytest.mark.priority("MVP")
def test_star_atlas_goto_to_a_parked_mount_says_so(window):
    """SKYMAP-020: a Goto the mount refuses because it is parked is reported as "parked", not as a generic failure."""
    from galileo.exceptions import MountParkedError

    class _ParkedMount(_FakeMount):
        async def slew_to_coordinates(self, ra, dec):
            raise MountParkedError("parked")

    vega = {"name": "Vega", "ra_deg": 279.2347, "dec_deg": 38.7837, "alt": 60.0}
    window._device_pages["mount"]["adapter"] = _ParkedMount("J2000")
    assert window._mount_to_object("goto", vega) is False
    assert "unpark" in window._window.statusBar().currentMessage()


@pytest.mark.requirement("TC-SKYMAP-020")
@pytest.mark.priority("MVP")
def test_star_atlas_goto_refusals_are_logged(window, caplog):
    """SKYMAP-020: a Goto/Sync that is not sent (no mount, below the horizon) leaves a log entry, not just a status-bar message."""
    import logging
    vega = {"name": "Vega", "ra_deg": 279.2347, "dec_deg": 38.7837, "alt": 60.0}
    with caplog.at_level(logging.WARNING, logger="galileo.ui.app_window"):
        window._device_pages["mount"]["adapter"] = None
        window._mount_to_object("goto", vega)
        window._device_pages["mount"]["adapter"] = _FakeMount("JNOW")
        window._mount_to_object("sync", {**vega, "alt": -5.0})
    assert "no mount is connected" in caplog.text and "below the horizon" in caplog.text


# --- horizon obstructions (SKYMAP-070, SKYMAP-080) -------------------------------

@pytest.fixture
def horizon_env(tmp_path, monkeypatch):
    """Keep the Planning options file out of the real config folder and put the process-wide slew guard back afterwards."""
    from galileo.core.slew_guard import get_slew_guard
    monkeypatch.setattr("galileo.planning.settings._path", lambda: tmp_path / "planning.json")
    guard = get_slew_guard()
    saved = (guard.enabled, guard.horizon, guard.latitude, guard.longitude)
    yield guard
    guard.enabled, guard.horizon, guard.latitude, guard.longitude = saved


@pytest.mark.requirement("TC-SKYMAP-070")
@pytest.mark.priority("P2")
def test_horizon_file_parsing_accepts_common_layouts_and_names_bad_lines():
    """SKYMAP-070: a horizon file is azimuth/altitude pairs (whitespace, comma or semicolon separated, comments and a header allowed); anything else is rejected with its line."""
    from galileo.planning.visibility import parse_horizon_text
    text = "﻿Azimuth,Altitude\n# my horizon\n90, 20\n\n0\t5 # north\n270;15.5\n"
    assert parse_horizon_text(text) == [(0.0, 5.0), (90.0, 20.0), (270.0, 15.5)]
    for bad, fragment in (("0 5\n10 x\n", "Line 2"), ("0 5 7\n", "Line 1"), ("400 5\n", "azimuth"),
                          ("10 95\n", "altitude"), ("-1 5\n", "azimuth"), ("# nothing\n", "no azimuth"), ("", "no azimuth")):
        with pytest.raises(ValueError, match=fragment):
            parse_horizon_text(bad)


@pytest.mark.requirement("TC-SKYMAP-070")
@pytest.mark.priority("P2")
def test_horizon_profile_interpolates_and_wraps_through_north():
    """SKYMAP-070: obstruction altitude is interpolated linearly between points and wraps from the last azimuth back to the first."""
    from galileo.planning.visibility import HorizonProfile
    h = HorizonProfile([(90.0, 20.0), (270.0, 40.0)])
    assert h.min_altitude_at(180.0) == pytest.approx(30.0)
    assert h.min_altitude_at(0.0) == pytest.approx(30.0)              # halfway round through north
    assert h.min_altitude_at(315.0) == pytest.approx(35.0)
    assert h.is_obstructed(25.0, 180.0) and not h.is_obstructed(35.0, 180.0)
    assert not HorizonProfile([]).is_obstructed(1.0, 10.0)            # no points, no obstruction
    assert list(HorizonProfile([(10.0, 12.0)]).min_altitudes(np.array([0.0, 200.0]))) == [12.0, 12.0]


@pytest.mark.requirement("TC-SKYMAP-070")
@pytest.mark.priority("P2")
def test_star_atlas_shades_obstructions_translucently_when_horizon_is_on(view):
    """SKYMAP-070: with "Horizon" on, the sky between the horizon and the obstruction altitude is tinted red — and only there — and the tint is translucent."""
    from galileo.planning.visibility import HorizonProfile
    from galileo.ui import star_atlas as ui
    view.show_ground = False
    view.show_grid = view.show_boundaries = view.show_lines = view.show_labels = False
    view.center_on_altaz(30.0, 180.0)
    view.set_horizon(HorizonProfile([(0.0, 40.0)]))                   # 40° all round
    vp = view._viewport()

    def pixel(alt: float):
        x, y, _ = vp.project(np.array([alt]), np.array([180.0]))
        return view.grab().toImage().pixelColor(int(x[0]), int(y[0]))

    below, above = pixel(20.0), pixel(60.0)
    assert view.show_horizon is False                                 # off by default
    view.set_option("show_horizon", True)
    shaded, clear = pixel(20.0), pixel(60.0)
    assert shaded.red() > below.red() + 40 and shaded.red() < 200    # tinted red, but not opaque
    assert ui._OBSTRUCTION_RGBA[3] < 128                              # translucent, so the stars behind it still show
    assert (clear.red(), clear.green(), clear.blue()) == (above.red(), above.green(), above.blue())
    view.set_horizon(None)
    assert pixel(20.0).red() == below.red()                           # nothing to shade without a horizon


@pytest.mark.requirement("TC-SKYMAP-070")
@pytest.mark.priority("P2")
def test_horizon_points_are_kept_per_observatory_by_a_migration(tmp_path):
    """SKYMAP-070: the horizon table is created by migration 015 and stored per Observatory; saving replaces it, an empty list clears it."""
    from galileo.library.database import db, get_migration_status, init_db
    from galileo.observatory import create_observatory, list_horizon_points, save_horizon_points
    init_db(tmp_path / "horizon.db")
    try:
        assert not get_migration_status()["undone"] and "horizon_points" in db.get_tables()
        home, away = create_observatory("Home"), create_observatory("Away")
        save_horizon_points(home, [(90.0, 20.0), (0.0, 5.0)])
        save_horizon_points(away, [(10.0, 1.0)])
        assert list_horizon_points(home) == [(0.0, 5.0), (90.0, 20.0)]
        save_horizon_points(home, [(45.0, 9.0)])
        assert list_horizon_points(home) == [(45.0, 9.0)] and list_horizon_points(away) == [(10.0, 1.0)]
        save_horizon_points(home, [])
        assert list_horizon_points(home) == []
    finally:
        db.close()


@pytest.mark.requirement("TC-SKYMAP-080")
@pytest.mark.priority("P2")
def test_slew_guard_blocks_only_when_enabled_with_a_horizon(horizon_env):
    """SKYMAP-080: an obstructed alt/az or RA/Dec raises the "obstructed" error, but only when the guard is on and a horizon exists."""
    from galileo.exceptions import SlewObstructedError
    from galileo.planning.visibility import HorizonProfile
    guard = horizon_env
    guard.enabled, guard.horizon, guard.latitude, guard.longitude = True, None, 40.0, 0.0
    guard.check_altaz(5.0, 90.0)                                      # no horizon: nothing blocked
    guard.horizon = HorizonProfile([(0.0, 30.0)])
    with pytest.raises(SlewObstructedError, match="Unable to slew to that area, it is obstructed"):
        guard.check_altaz(10.0, 90.0)
    guard.check_altaz(45.0, 90.0)
    guard.enabled = False
    guard.check_altaz(10.0, 90.0)                                     # switched off

    # At latitude 40°N, a star on the meridian at Dec +40° is at the zenith and the celestial pole is 40° up.
    when = dt.datetime(2024, 6, 1, 3, 0)
    lst = sa.local_sidereal_deg(sa.julian_date(when), 0.0)
    guard.enabled, guard.horizon = True, HorizonProfile([(0.0, 60.0)])
    with pytest.raises(SlewObstructedError):
        guard.check_radec(lst, 90.0, when)                            # 40° up, under the 60° obstruction
    guard.check_radec(lst, 40.0, when)                                # zenith: clear
    guard.latitude = None
    guard.check_radec(lst, 90.0, when)                                # no site: cannot convert, so not blocked


@pytest.mark.requirement("TC-SKYMAP-080")
@pytest.mark.priority("P2")
def test_mount_adapters_refuse_obstructed_slews_before_moving(horizon_env):
    """SKYMAP-080: both mount adapters consult the guard, so an obstructed slew is never sent to the mount."""
    import asyncio
    from galileo.adapters.alpaca import AlpacaMountAdapter
    from galileo.adapters.indi import IndiMountAdapter
    from galileo.exceptions import SlewObstructedError
    from galileo.planning.visibility import HorizonProfile
    guard = horizon_env
    guard.enabled, guard.horizon, guard.latitude, guard.longitude = True, HorizonProfile([(0.0, 30.0)]), 40.0, 0.0

    sent: list = []
    alpaca = AlpacaMountAdapter()

    async def no_park(_command):
        return None

    async def put(*args, **kwargs):
        sent.append((args, kwargs))

    alpaca._refuse_if_parked, alpaca._put = no_park, put
    with pytest.raises(SlewObstructedError):
        asyncio.run(alpaca.slew_to_altaz(10.0, 90.0))
    asyncio.run(alpaca.slew_to_altaz(50.0, 90.0))
    assert len(sent) == 1                                             # only the clear slew went out

    sent.clear()
    indi = IndiMountAdapter()
    indi._refuse_if_parked = lambda _command: None
    indi._set_num = indi._select = lambda *args, **kwargs: sent.append(args)
    lst = sa.local_sidereal_deg(sa.julian_date(dt.datetime.now(dt.timezone.utc)), 0.0)
    with pytest.raises(SlewObstructedError):
        asyncio.run(indi.slew_to_altaz(10.0, 90.0))
    with pytest.raises(SlewObstructedError):
        asyncio.run(indi.slew_to_coordinates(lst, -60.0))             # on the meridian, 10° below the horizon
    assert sent == []
    asyncio.run(indi.slew_to_coordinates(lst, 40.0))                  # zenith
    assert sent                                                       # went out


def _checkbox(window, text: str):
    from PySide6.QtWidgets import QCheckBox
    return next(box for box in window._window.findChildren(QCheckBox) if box.text() == text)


@pytest.mark.requirement("TC-SKYMAP-070")
@pytest.mark.priority("P2")
def test_options_star_atlas_uploads_a_horizon_and_the_atlas_shows_it(horizon_env, window, tmp_path, monkeypatch):
    """SKYMAP-070: Options > Star Atlas loads a file into the horizon table, the Star Atlas gets a "Horizon" checkbox that shades it, and a bad file changes nothing."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton, QTableWidget
    from galileo.observatory import create_observatory, list_horizon_points
    window._select_observatory(create_observatory("Home", 40.0, 0.0))
    assert window._star_atlas_set_horizon.__self__.show_horizon is False
    table = next(t for t in window._options_page.findChildren(QTableWidget))
    assert table.rowCount() == 0

    good = tmp_path / "horizon.txt"
    good.write_text("Azimuth Altitude\n0 10\n90 25\n180 5\n270 15\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(good), ""))
    upload = next(b for b in window._options_page.findChildren(QPushButton) if b.text().startswith("Upload"))
    upload.click()
    assert table.rowCount() == 4 and table.item(1, 0).text() == "90" and table.item(1, 1).text() == "25"
    assert list_horizon_points(window._current_observatory) == [(0.0, 10.0), (90.0, 25.0), (180.0, 5.0), (270.0, 15.0)]
    view = window._star_atlas_set_horizon.__self__
    assert view._horizon is not None and view._horizon.min_altitude_at(90.0) == 25.0

    _checkbox(window, "Horizon").setChecked(True)
    assert view.show_horizon is True

    bad = tmp_path / "bad.txt"
    bad.write_text("north ten\n", encoding="utf-8")
    warned: list = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(bad), ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[-1]))
    upload.click()
    assert warned and table.rowCount() == 4                           # rejected, previous table kept


@pytest.mark.requirement("TC-SKY-040")
@pytest.mark.priority("P2")
def test_options_star_atlas_edits_horizon_points_directly(horizon_env, window):
    """SKY-040: Options > Star Atlas lets a user add, edit, remove and save horizon
    obstruction points directly in the table, not only by uploading a file."""
    from PySide6.QtWidgets import QMessageBox, QPushButton, QTableWidget
    from galileo.observatory import create_observatory, list_horizon_points
    window._select_observatory(create_observatory("Home", 40.0, 0.0))
    table = next(t for t in window._options_page.findChildren(QTableWidget))

    def button(text):
        return next(b for b in window._options_page.findChildren(QPushButton) if b.text() == text)

    add_btn, remove_btn, save_btn = button("Add Point"), button("Remove Selected"), button("Save Changes")
    assert not remove_btn.isEnabled()  # nothing to remove yet

    # Add two points and edit their values directly.
    add_btn.click()
    table.item(0, 0).setText("45")
    table.item(0, 1).setText("12")
    add_btn.click()
    table.item(1, 0).setText("10")
    table.item(1, 1).setText("8")
    assert table.rowCount() == 2 and remove_btn.isEnabled()

    save_btn.click()
    # Saved sorted by azimuth, regardless of entry order — and saving refreshes the table
    # from the database, so its rows are now in that same azimuth order too: (10, 8), (45, 12).
    assert list_horizon_points(window._current_observatory) == [(10.0, 8.0), (45.0, 12.0)]
    assert table.item(0, 0).text() == "10" and table.item(1, 0).text() == "45"

    # An out-of-range value is rejected — nothing is saved, the table is left as typed.
    table.item(1, 1).setText("999")  # row 1 is (45, 12); this makes it (45, 999)
    warned: list = []
    import unittest.mock as mock
    with mock.patch.object(QMessageBox, "warning", lambda *a, **k: warned.append(a[-1])):
        save_btn.click()
    assert warned
    assert list_horizon_points(window._current_observatory) == [(10.0, 8.0), (45.0, 12.0)]  # unchanged

    # Restore it, then remove row 0 (10, 8) and save again, leaving only (45, 12).
    table.item(1, 1).setText("12")
    table.selectRow(0)
    remove_btn.click()
    assert table.rowCount() == 1
    save_btn.click()
    assert list_horizon_points(window._current_observatory) == [(45.0, 12.0)]

    # Removing the one remaining row and saving clears the horizon entirely.
    table.selectRow(0)
    remove_btn.click()
    save_btn.click()
    assert list_horizon_points(window._current_observatory) == []
    assert not remove_btn.isEnabled()  # table is empty again


@pytest.mark.requirement("TC-SKYMAP-080")
@pytest.mark.priority("P2")
def test_options_planning_switch_turns_the_slew_guard_on(horizon_env, window):
    """SKYMAP-080: Options > Planning has "Do not slew where obstructed (see Star Atlas)"; it is off by default, remembered, and switches the guard."""
    from galileo.observatory import create_observatory, save_horizon_points
    from galileo.planning.settings import load_planning_settings
    home = create_observatory("Home", 40.0, 0.0)
    save_horizon_points(home, [(0.0, 30.0)])
    window._select_observatory(home)
    box = _checkbox(window, "Do not slew where obstructed (see Star Atlas)")
    assert box.isChecked() is False and horizon_env.enabled is False
    assert horizon_env.horizon is not None and horizon_env.latitude == 40.0    # the guard has the site and horizon
    box.setChecked(True)
    assert horizon_env.enabled is True and load_planning_settings()["block_obstructed_slews"] is True
    box.setChecked(False)
    assert horizon_env.enabled is False and load_planning_settings()["block_obstructed_slews"] is False


@pytest.mark.requirement("TC-SKYMAP-080")
@pytest.mark.priority("P2")
def test_obstructed_goto_reports_the_error_in_the_status_bar(window):
    """SKYMAP-080: a Goto the mount refuses as obstructed says "Unable to slew to that area, it is obstructed" and is not reported as sent."""
    from galileo.exceptions import SlewObstructedError

    class _ObstructedMount(_FakeMount):
        async def slew_to_coordinates(self, ra, dec):
            raise SlewObstructedError()

    vega = {"name": "Vega", "ra_deg": 279.2347, "dec_deg": 38.7837, "alt": 60.0}
    window._device_pages["mount"]["adapter"] = _ObstructedMount("J2000")
    assert window._mount_to_object("goto", vega) is False
    assert "Unable to slew to that area, it is obstructed" in window._window.statusBar().currentMessage()


# ---------------------------------------------------------------------------
# SKYMAP-090 — a telescope reticle per Pier, tracking slews
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_current_objects():
    """The current-object store is process-wide and keyed by Pier id, and every test builds a fresh
    database whose ids restart at 1 — so clear it, or one test's target shows up in the next."""
    import galileo.current_object as co
    co._default_store = None
    yield
    co._default_store = None


class _ReticleMount:
    """A mount whose reported position can be moved between polls, as during a slew."""

    def __init__(self, ra_deg=279.235, dec_deg=38.784, slewing=False, system="J2000"):
        self.ra_deg, self.dec_deg, self.slewing, self.system = ra_deg, dec_deg, slewing, system
        self.polls = 0

    async def get_status(self):
        self.polls += 1
        return {"right_ascension": self.ra_deg / 15.0, "declination": self.dec_deg,
                "equatorial_system": self.system, "slewing": self.slewing}


class _SilentMount:
    async def get_status(self):
        raise RuntimeError("the mount stopped answering")


def _poll(window):
    """Poll the mount as the page's timer does, then wait for the worker thread and its signal."""
    done = []
    window._poll_pier_pointing(on_done=lambda: done.append(True))
    thread = window._pier_poll_thread
    if thread is not None:
        thread.wait(5000)
        window.app.processEvents()
    return done


def _two_piers(window):
    from galileo.observatory import create_observatory, create_pier
    observatory = create_observatory("Reticle Obs")
    window._current_observatory = observatory
    pier_a, pier_b = create_pier(observatory, "Pier A"), create_pier(observatory, "Pier B")
    window._current_pier = pier_a
    return pier_a, pier_b


@pytest.mark.requirement("TC-SKYMAP-090")
@pytest.mark.priority("P2")
def test_tc_skymap_090_each_pier_gets_a_labelled_reticle(window):
    """SKYMAP-090: every Pier in the current Observatory with something to show gets a labelled reticle."""
    from galileo.current_object import CurrentObject, get_current_objects
    pier_a, pier_b = _two_piers(window)
    assert window.pier_markers() == [], "nothing known about either Pier yet"

    get_current_objects().set(pier_a, CurrentObject("M 31", 10.6847, 41.2687))
    get_current_objects().set(pier_b, CurrentObject("M 42", 83.822, -5.391))
    markers = window.pier_markers()

    assert [m["label"] for m in markers] == ["Pier A → M 31", "Pier B → M 42"]
    assert markers[0]["ra_deg"] == pytest.approx(10.6847) and markers[1]["dec_deg"] == pytest.approx(-5.391)
    assert not any(m["slewing"] for m in markers)


@pytest.mark.requirement("TC-SKYMAP-090")
@pytest.mark.priority("P2")
def test_tc_skymap_090_reticle_follows_the_mount_and_moves_as_it_slews(window):
    """SKYMAP-090: a connected mount's reticle sits where it is really pointing and moves with it, so a slew can be watched."""
    from galileo.current_object import CurrentObject, get_current_objects
    pier_a, _pier_b = _two_piers(window)
    get_current_objects().set(pier_a, CurrentObject("M 31", 10.6847, 41.2687))
    mount = _ReticleMount(ra_deg=200.0, dec_deg=10.0, slewing=True)
    window._device_pages["mount"]["adapter"] = mount

    _poll(window)
    marker = window.pier_markers()[0]
    assert marker["ra_deg"] == pytest.approx(200.0, abs=1e-6) and marker["dec_deg"] == pytest.approx(10.0, abs=1e-6)
    assert marker["slewing"] is True and marker["label"] == "Pier A → M 31 (slewing)"
    # The target is carried too, so the view can draw where the mount is heading.
    assert marker["target"] == {"ra_deg": pytest.approx(10.6847), "dec_deg": pytest.approx(41.2687)}

    mount.ra_deg, mount.dec_deg = 100.0, 30.0      # the slew has run on
    _poll(window)
    moved = window.pier_markers()[0]
    assert moved["ra_deg"] == pytest.approx(100.0, abs=1e-6), "the reticle followed the mount"

    mount.ra_deg, mount.dec_deg, mount.slewing = 10.6847, 41.2687, False
    _poll(window)
    arrived = window.pier_markers()[0]
    assert arrived["slewing"] is False and arrived["label"] == "Pier A → M 31"


@pytest.mark.requirement("TC-SKYMAP-090")
@pytest.mark.priority("P2")
def test_tc_skymap_090_a_mount_reporting_jnow_is_converted_for_the_map(window):
    """SKYMAP-090: a mount that reports coordinates of date is converted to J2000, which is what the map draws in."""
    from galileo.platesolve import j2000_to_mount_frame
    pier_a, _ = _two_piers(window)
    j2000 = (37.95, 89.26)                                  # Polaris, which has precessed a long way
    jnow = j2000_to_mount_frame(*j2000, "JNOW")
    window._device_pages["mount"]["adapter"] = _ReticleMount(ra_deg=jnow[0], dec_deg=jnow[1], system="JNOW")

    _poll(window)
    marker = window.pier_markers()[0]
    assert marker["ra_deg"] == pytest.approx(j2000[0], abs=1e-4)
    assert marker["dec_deg"] == pytest.approx(j2000[1], abs=1e-4)
    assert marker["label"] == "Pier A", "no current object, so just the Pier's name"


@pytest.mark.requirement("TC-SKYMAP-090")
@pytest.mark.priority("P2")
def test_tc_skymap_090_an_unreadable_mount_falls_back_to_the_target(window):
    """SKYMAP-090: when the mount can't be read the reticle shows the Pier's target rather than freezing where it last was."""
    from galileo.current_object import CurrentObject, get_current_objects
    pier_a, _ = _two_piers(window)
    get_current_objects().set(pier_a, CurrentObject("M 31", 10.6847, 41.2687))
    window._device_pages["mount"]["adapter"] = _ReticleMount(ra_deg=200.0, dec_deg=10.0)
    _poll(window)
    assert window.pier_markers()[0]["ra_deg"] == pytest.approx(200.0, abs=1e-6)

    window._device_pages["mount"]["adapter"] = _SilentMount()
    _poll(window)
    marker = window.pier_markers()[0]
    assert marker["ra_deg"] == pytest.approx(10.6847), "back to the target"
    assert marker["slewing"] is False

    window._device_pages["mount"]["adapter"] = None       # disconnected entirely
    _poll(window)
    assert window.pier_markers()[0]["ra_deg"] == pytest.approx(10.6847)


@pytest.mark.requirement("TC-SKYMAP-090")
@pytest.mark.priority("P2")
def test_tc_skymap_090_the_mount_is_read_off_the_ui_thread(window):
    """SKYMAP-090: the mount is read on a worker thread — a slow mount must never stall the sky view."""
    import threading
    _two_piers(window)
    seen = {}

    class _ThreadRecordingMount(_ReticleMount):
        async def get_status(self):
            seen["thread"] = threading.current_thread().ident
            return await super().get_status()

    window._device_pages["mount"]["adapter"] = _ThreadRecordingMount()
    _poll(window)
    assert seen["thread"] != threading.current_thread().ident
    assert window._pier_poll_thread is None, "the thread is released once it reports"


@pytest.mark.requirement("TC-SKYMAP-090")
@pytest.mark.priority("P2")
def test_tc_skymap_090_the_view_draws_a_reticle_for_each_marker(view):
    """SKYMAP-090: the sky view draws the reticles it is given, and the Telescope markers option turns them off."""
    def painted(v):
        return v.grab().toImage()

    # Vega is near the zenith for this fixture, so a reticle on it lands in view.
    vega = {"ra_deg": 279.235, "dec_deg": 38.784}
    blank = painted(view)
    view.set_pier_markers([{**vega, "label": "Pier A → Vega", "slewing": False}])
    assert view.pier_markers and painted(view) != blank, "the reticle changed what is drawn"

    view.set_option("show_pier_markers", False)
    assert painted(view) == blank, "turning Telescope markers off removes them"


@pytest.mark.requirement("TC-SKYMAP-090")
@pytest.mark.priority("P2")
def test_tc_skymap_090_a_marker_off_the_map_or_malformed_is_skipped(view):
    """SKYMAP-090: a reticle outside the view, or one missing coordinates, is skipped rather than drawn wrongly or raising."""
    def paint(v):
        return v.grab().toImage()

    blank = paint(view)
    below = {"ra_deg": (279.235 + 180.0) % 360.0, "dec_deg": -38.784}      # opposite the zenith: under the horizon
    view.set_pier_markers([below | {"label": "Pier A"}, {"label": "Pier B (no coordinates)"}])
    assert paint(view) == blank


@pytest.mark.requirement("TC-SKYMAP-090")
@pytest.mark.priority("P2")
def test_tc_skymap_090_telescope_markers_is_a_remembered_option(tmp_path, monkeypatch):
    """SKYMAP-090: Telescope markers is on by default and remembered between runs, like the other display options."""
    import galileo.platform as platform_mod
    from galileo.ui.star_atlas import PERSISTED_TOGGLES, StarAtlasView, load_display_prefs, save_display_prefs
    monkeypatch.setattr(platform_mod, "get_config_dir", lambda: tmp_path)
    assert "show_pier_markers" in PERSISTED_TOGGLES

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    v = StarAtlasView()
    try:
        assert v.show_pier_markers is True
        v.show_pier_markers = False
        save_display_prefs(v)
        assert load_display_prefs()["show_pier_markers"] is False
    finally:
        v.close()
