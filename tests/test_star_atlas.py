"""Star Atlas planetarium (``galileo.planning.star_atlas``, ``galileo.ui.star_atlas``, the Star Atlas page).

The Star Atlas sidebar section shows a basic planetarium: the sky maths is plain
numpy and is tested directly; the view and page are built offscreen. Catalog
loading is patched to the built-in offline star list so no test touches the
network. Requirement IDs are the SKYMAP ones the planetarium partly satisfies
(SKYMAP-010 render, SKYMAP-020 identify / centre-and-track, SKYMAP-030 constellation
boundaries and outlines); constellation art, comets/asteroids/satellites and the
FOV/mount overlay are not built.
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
    """Planning opens onto Targets (the catalog lookup), Sequence and Scheduler; Science holds Variable Stars.
    None of those four is a top-level section any more."""
    from galileo.ui.app_window import PLANNING_ITEMS, PRIMARY_SECTIONS, SCIENCE_ITEMS
    ids = [s[0] for s in PRIMARY_SECTIONS]
    assert ids == ["equipment", "star_atlas", "planning", "framing", "imaging", "guiding", "library", "science"]
    assert [i[:2] for i in PLANNING_ITEMS] == [("targets", "Targets"), ("sequencer", "Sequence"), ("scheduler", "Scheduler")]
    assert [i[:2] for i in SCIENCE_ITEMS] == [("variable_stars", "Variable Stars")]

    from PySide6 import QtWidgets
    assert len(window._window.findChildren(QtWidgets.QWidget, "SubmenuPage")) == 2
    menus = [
        [" ".join(b.text().split()) for b in c.findChildren(QtWidgets.QToolButton)]
        for c in window._nav_columns if c.objectName() == "SecondarySidebar"
    ]
    assert ["Targets", "Sequence", "Scheduler"] in menus and ["Variable Stars"] in menus


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
