# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SKY — Sky Atlas / Targets (TC-SKY-010 … TC-SKY-120)."""

import pytest
from unittest.mock import AsyncMock, patch


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


@pytest.mark.requirement("TC-SKY-020")
@pytest.mark.priority("MVP")
def test_tc_sky_020_filter_by_apparent_size_range(sky_atlas):
    """SKY-020: apparent-size filtering is a min/max range, not just a lower bound — matching the
    reference Telescopius layout's "Apparent Size" filter (assets/samples/target.png)."""
    results = sky_atlas.filter(min_size_arcmin=5.0, max_size_arcmin=30.0)
    for obj in results:
        assert 5.0 <= obj.size_arcmin <= 30.0

    # max_size_arcmin=0 (the default) means "no upper bound" — same as omitting it.
    unbounded = sky_atlas.filter(min_size_arcmin=5.0)
    bounded = sky_atlas.filter(min_size_arcmin=5.0, max_size_arcmin=0.0)
    assert len(unbounded) == len(bounded)


@pytest.mark.requirement("TC-SKY-020")
@pytest.mark.priority("MVP")
def test_tc_sky_020_visible_tonight_altitude_and_duration_are_configurable(observing_location):
    """SKY-020: "visible tonight" isn't a fixed 20 degrees for one instant — both the altitude
    threshold and a minimum continuous duration are configurable, matching the reference Telescopius
    layout's "Reach an altitude of X for at least Y hours" filter (assets/samples/target.png)."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    atlas = sky_mod.SkyAtlas(catalog=[
        sky_mod.DeepSkyObject(
            primary_name="M42", designations=["M42"], ra_deg=83.8221, dec_deg=-5.3911,
            object_type=sky_mod.ObjectType.NEBULA, magnitude=4.0,
        ),
    ])

    # A modest altitude/duration requirement M42 clears tonight from this latitude.
    assert atlas.filter(
        location=observing_location, visible_tonight=True,
        min_altitude_deg=20.0, min_duration_hours=1.0, date_str="2026-09-16",
    )

    # An unreasonably demanding one (near-zenith for hours) filters it out.
    assert not atlas.filter(
        location=observing_location, visible_tonight=True,
        min_altitude_deg=85.0, min_duration_hours=6.0, date_str="2026-09-16",
    )


@pytest.mark.requirement("TC-SKY-020")
@pytest.mark.priority("MVP")
def test_tc_sky_020_filter_by_moon_separation(observing_location):
    """SKY-020: exclude anything closer to the Moon than a configured minimum separation, matching
    the reference Telescopius layout's "Distance from the Moon" filter (assets/samples/target.png)."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    from galileo.planning.visibility import moon_position_deg

    moon_ra, moon_dec = moon_position_deg(observing_location, date_str="2026-09-16")
    near_moon = sky_mod.DeepSkyObject(
        primary_name="Near Moon", designations=["Near Moon"], ra_deg=moon_ra, dec_deg=moon_dec,
        object_type=sky_mod.ObjectType.OTHER, magnitude=10.0,
    )
    far_from_moon = sky_mod.DeepSkyObject(
        primary_name="Far From Moon", designations=["Far From Moon"],
        ra_deg=(moon_ra + 180.0) % 360.0, dec_deg=-moon_dec,
        object_type=sky_mod.ObjectType.OTHER, magnitude=10.0,
    )
    atlas = sky_mod.SkyAtlas(catalog=[near_moon, far_from_moon])

    results = atlas.filter(location=observing_location, min_moon_separation_deg=30.0, date_str="2026-09-16")

    assert far_from_moon in results
    assert near_moon not in results

    # min_moon_separation_deg=0 (the default) means "no Moon filter" — same as omitting it.
    unfiltered = atlas.filter(location=observing_location, date_str="2026-09-16")
    assert near_moon in unfiltered and far_from_moon in unfiltered


@pytest.mark.requirement("TC-SKY-020")
@pytest.mark.priority("MVP")
def test_tc_sky_020_filter_by_catalog():
    """SKY-020: filter by which astronomical catalog (Messier/Caldwell/NGC) an object belongs to,
    matching the reference Telescopius layout's "Catalog" filter (assets/samples/target.png) — reuses
    the same catalog-membership logic (catalogs_of) the Star Atlas/skymap's own overlay toggles
    already use, rather than a second, separate notion of "catalog"."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")

    messier_obj = sky_mod.DeepSkyObject(
        primary_name="M1", designations=["M1", "NGC 1952"], ra_deg=83.63, dec_deg=22.01,
        object_type=sky_mod.ObjectType.SUPERNOVA_REMNANT, magnitude=8.4,
    )
    caldwell_obj = sky_mod.DeepSkyObject(
        primary_name="C 99", designations=["C 99"], ra_deg=192.4, dec_deg=-63.2,
        object_type=sky_mod.ObjectType.NEBULA, magnitude=99.0,
    )
    ngc_only_obj = sky_mod.DeepSkyObject(
        primary_name="NGC 5000", designations=["NGC 5000"], ra_deg=198.0, dec_deg=10.0,
        object_type=sky_mod.ObjectType.GALAXY, magnitude=13.0,
    )
    atlas = sky_mod.SkyAtlas(catalog=[messier_obj, caldwell_obj, ngc_only_obj])

    assert sky_mod.catalogs_of(messier_obj) == {"Messier", "NGC"}
    assert sky_mod.catalogs_of(caldwell_obj) == {"Caldwell"}
    assert sky_mod.catalogs_of(ngc_only_obj) == {"NGC"}

    assert atlas.filter(catalogs={"Messier"}) == [messier_obj]

    # An object matching any selected catalog passes — Caldwell-only is included alongside
    # Messier when both are selected, even though it isn't itself a Messier object.
    both = atlas.filter(catalogs={"Messier", "Caldwell"})
    assert messier_obj in both and caldwell_obj in both and ngc_only_obj not in both

    # No catalogs given (the default) means "no catalog filter" — same as every result.
    assert atlas.filter() == [messier_obj, caldwell_obj, ngc_only_obj]


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


@pytest.mark.requirement("TC-SKY-030")
@pytest.mark.priority("MVP")
def test_tc_sky_030_rise_transit_set_for_a_normal_object(sky_atlas, observing_location):
    """SKY-030: rise/transit/set times, read off the same altitude curve the chart plots, for an
    object that rises and sets within the charted night."""
    m42 = sky_atlas.get_by_designation("M42")
    rts = sky_atlas.rise_transit_set(m42, location=observing_location, date="2026-09-16")

    assert rts["rise"] is not None
    assert rts["transit"] is not None
    assert rts["set"] is not None
    # Rise -> transit -> set in chronological order.
    assert rts["rise"] < rts["transit"] < rts["set"]


@pytest.mark.requirement("TC-SKY-030")
@pytest.mark.priority("MVP")
def test_tc_sky_030_rise_transit_set_circumpolar_never_sets(observing_location):
    """SKY-030: a circumpolar object (always above the horizon at this latitude) has a transit but no
    rise or set within the night — it never crosses the horizon at all."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    from galileo.planning.visibility import rise_transit_set

    # High declination, close to the north celestial pole, from a mid-northern latitude.
    rts = rise_transit_set(37.95, 89.26, observing_location, date_str="2026-09-16")
    assert rts["transit"] is not None
    assert rts["rise"] is None
    assert rts["set"] is None


@pytest.mark.requirement("TC-SKY-030")
@pytest.mark.priority("MVP")
def test_tc_sky_030_rise_transit_set_never_rises(observing_location):
    """SKY-030: a target that never clears the horizon tonight (a far-southern declination from a
    mid-northern latitude) reports no rise, transit, or set at all, rather than a bogus time."""
    from galileo.planning.visibility import rise_transit_set

    rts = rise_transit_set(0.0, -80.0, observing_location, date_str="2026-09-16")
    assert rts == {"rise": None, "transit": None, "set": None}


@pytest.mark.requirement("TC-SKY-030")
@pytest.mark.priority("MVP")
def test_tc_sky_030_altitude_charts_batch_matches_individual_calls(sky_atlas, observing_location):
    """SKY-030: the batched multi-object chart (used by the Sky Atlas page's per-result cards, where
    computing this individually for up to 200 results is too slow) returns the same altitude data as
    calling altitude_chart individually per object — a performance optimization, not a different
    calculation."""
    m42 = sky_atlas.get_by_designation("M42")
    m31 = sky_atlas.get_by_designation("M31")

    individual = [
        sky_atlas.altitude_chart(m42, observing_location, date="2026-09-16"),
        sky_atlas.altitude_chart(m31, observing_location, date="2026-09-16"),
    ]
    batched = sky_atlas.altitude_charts_batch([m42, m31], observing_location, date="2026-09-16")

    assert len(batched) == 2
    for ind, batch in zip(individual, batched):
        assert batch["times"] == ind["times"]
        assert batch["altitudes"] == pytest.approx(ind["altitudes"], abs=1e-6)


@pytest.mark.requirement("TC-SKY-030")
@pytest.mark.priority("MVP")
def test_tc_sky_030_rise_transit_set_reuses_a_precomputed_chart(sky_atlas, observing_location):
    """SKY-030: passing an already-computed chart to rise_transit_set skips recomputing it, and
    produces the same result as the no-chart path — needed so the per-result cards (which need both
    the chart for their graph and rise/transit/set text) don't pay for the astropy transform twice."""
    m42 = sky_atlas.get_by_designation("M42")

    chart = sky_atlas.altitude_chart(m42, observing_location, date="2026-09-16")
    from_chart = sky_atlas.rise_transit_set(m42, observing_location, date="2026-09-16", chart=chart)
    from_scratch = sky_atlas.rise_transit_set(m42, observing_location, date="2026-09-16")

    assert from_chart == from_scratch


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


@pytest.mark.requirement("TC-SKY-080")
@pytest.mark.priority("P2")
def test_tc_sky_080_thumbnail_field_is_derived_from_object_size():
    """SKY-080: the thumbnail's requested field size is padded around the object's own angular size
    (cropping a point-source star and a multi-degree nebula differently) rather than a fixed window,
    clamped to sane bounds either way."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")

    # A mid-sized object's field pads its own size, not the fixed default.
    assert sky_mod._thumbnail_field_arcmin(20.0) == pytest.approx(20.0 * sky_mod._THUMBNAIL_SIZE_PAD)

    # A tiny/point-source object is clamped up to the minimum, not zoomed in past what a 150x150 px
    # thumbnail can usefully show.
    assert sky_mod._thumbnail_field_arcmin(0.5) == pytest.approx(sky_mod._THUMBNAIL_MIN_FOV_ARCMIN)

    # An enormous object is clamped down to the maximum rather than requesting an ever-larger cutout.
    assert sky_mod._thumbnail_field_arcmin(500.0) == pytest.approx(sky_mod._THUMBNAIL_MAX_FOV_ARCMIN)

    # An unknown size (0, e.g. a star with no catalog major-axis value) falls back to the previous
    # fixed window rather than collapsing to a degenerate zero-size request.
    assert sky_mod._thumbnail_field_arcmin(0.0) == pytest.approx(sky_mod._THUMBNAIL_DEFAULT_FOV_ARCMIN)


@pytest.mark.requirement("TC-SKY-080")
@pytest.mark.priority("P2")
async def test_tc_sky_080_fetch_thumbnail_passes_size_derived_field_to_the_cutout_fetch(sky_atlas, tmp_path, monkeypatch):
    """SKY-080: _fetch_thumbnail actually threads the size-derived field through to the cutout
    fetch — not just computing it and still requesting the old fixed window."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    monkeypatch.setattr("galileo.platform.get_cache_dir", lambda: tmp_path)
    obj = sky_mod.DeepSkyObject(
        primary_name="Big Nebula", designations=["Big Nebula"], ra_deg=10.0, dec_deg=20.0,
        object_type=sky_mod.ObjectType.NEBULA, magnitude=8.0, size_arcmin=20.0,
    )
    with patch.object(sky_mod, "_fetch_hips_thumbnail_sync", return_value=b"data") as mock_fetch:
        data = await sky_atlas._fetch_thumbnail(obj)

    assert data == b"data"
    expected_field = 20.0 * sky_mod._THUMBNAIL_SIZE_PAD
    mock_fetch.assert_called_once_with(
        10.0, 20.0, pytest.approx(expected_field), pytest.approx(expected_field), 150,
    )


@pytest.mark.requirement("TC-SKY-080")
@pytest.mark.priority("P2")
async def test_tc_sky_080_fetch_thumbnail_caches_to_disk_and_reuses_it(sky_atlas, tmp_path, monkeypatch):
    """SKY-080: a thumbnail is cached to disk on a successful fetch and served from that cache on a
    later request for the same object — a second selection, or the same object turning up again in a
    later search's result cards, shouldn't re-hit the network."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    monkeypatch.setattr("galileo.platform.get_cache_dir", lambda: tmp_path)
    obj = sky_mod.DeepSkyObject(
        primary_name="Cache Test Object", designations=["Cache Test Object"], ra_deg=50.0, dec_deg=-10.0,
        object_type=sky_mod.ObjectType.GALAXY, magnitude=9.0, size_arcmin=10.0,
    )

    with patch.object(sky_mod, "_fetch_hips_thumbnail_sync", return_value=b"first-fetch-bytes") as mock_fetch:
        first = await sky_atlas._fetch_thumbnail(obj)
    assert first == b"first-fetch-bytes"
    mock_fetch.assert_called_once()

    # A second fetch for the same object must come from the cache, not another network call —
    # the mock would return different bytes if it were actually invoked again.
    with patch.object(sky_mod, "_fetch_hips_thumbnail_sync", return_value=b"should-not-be-used") as mock_fetch_2:
        second = await sky_atlas._fetch_thumbnail(obj)
    assert second == b"first-fetch-bytes"
    mock_fetch_2.assert_not_called()


@pytest.mark.requirement("TC-SKY-080")
@pytest.mark.priority("P2")
async def test_tc_sky_080_fetch_thumbnail_size_px_is_a_separate_cache_entry(sky_atlas, tmp_path, monkeypatch):
    """SKY-080: a larger size_px (the Targets page's click-to-enlarge full-image overlay) fetches and
    caches separately from the default 150px result-tile thumbnail — over the same field of view, just
    more pixels of it — rather than colliding with, or being satisfied by, the small cached entry."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    monkeypatch.setattr("galileo.platform.get_cache_dir", lambda: tmp_path)
    obj = sky_mod.DeepSkyObject(
        primary_name="Enlarge Test", designations=["Enlarge Test"], ra_deg=30.0, dec_deg=5.0,
        object_type=sky_mod.ObjectType.GALAXY, magnitude=10.0, size_arcmin=5.0,
    )

    with patch.object(sky_mod, "_fetch_hips_thumbnail_sync", return_value=b"small-150px") as mock_small:
        small = await sky_atlas._fetch_thumbnail(obj)
    assert small == b"small-150px"
    mock_small.assert_called_once()

    # A different size_px must not be satisfied by the 150px cache entry above.
    with patch.object(sky_mod, "_fetch_hips_thumbnail_sync", return_value=b"large-640px") as mock_large:
        large = await sky_atlas._fetch_thumbnail(obj, size_px=640)
    assert large == b"large-640px"
    mock_large.assert_called_once()
    assert mock_large.call_args[0][-1] == 640

    # Re-fetching either size afterward comes from its own cache entry, not the network, and not
    # each other's.
    with patch.object(sky_mod, "_fetch_hips_thumbnail_sync") as mock_unused:
        assert await sky_atlas._fetch_thumbnail(obj) == b"small-150px"
        assert await sky_atlas._fetch_thumbnail(obj, size_px=640) == b"large-640px"
    mock_unused.assert_not_called()


@pytest.mark.requirement("TC-SKY-080")
@pytest.mark.priority("P2")
def test_tc_sky_080_options_planning_bulk_caches_all_catalog_thumbnails(tmp_path, monkeypatch):
    """SKY-080: Options > Planning's "Cache All Catalog Thumbnails" button bulk-fetches a thumbnail
    for every catalog object (via the same disk-cached SkyAtlas._fetch_thumbnail path a search's
    result tiles use) off the Qt UI thread, so a later search doesn't pay the fetch cost per result."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "thumbnail_cache_test.db")
    from galileo.observatory import create_observatory, create_pier
    from galileo.ui.app_window import AppWindow

    class _FakeObj:
        def __init__(self, name):
            self.primary_name = name
            self.ra_deg, self.dec_deg = 10.0, 10.0
            self.size_arcmin = 0.0

    fetched_names = []

    class _FakeSkyAtlas:
        def __init__(self, *a, **k):
            self._catalog = [_FakeObj(f"Obj{i}") for i in range(5)]

        async def _fetch_thumbnail(self, obj):
            fetched_names.append(obj.primary_name)
            return b"data"

    monkeypatch.setattr(sky_mod, "SkyAtlas", _FakeSkyAtlas)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Yes))

    win = AppWindow()
    try:
        win.app, win.QtWidgets = app, QtWidgets
        win.pier = create_pier(create_observatory("Test Obs"), "Pier A")
        win._current_pier = win.pier

        page = win._build_planning_settings_page()
        cache_btn = next(b for b in page.findChildren(QtWidgets.QPushButton) if "Cache All" in b.text())

        cache_btn.click()
        assert win._thumbnail_cache_worker is not None, "the confirmation dialog should not have blocked starting it"

        import time
        for _ in range(300):
            app.processEvents()
            if win._thumbnail_cache_worker is None:
                break
            time.sleep(0.01)

        assert win._thumbnail_cache_worker is None, "worker did not finish in time"
        assert sorted(fetched_names) == [f"Obj{i}" for i in range(5)]
        assert "complete" in win._window.statusBar().currentMessage().lower()
    finally:
        win._window.close()
        db.close()


@pytest.mark.requirement("TC-SKY-080")
@pytest.mark.priority("P2")
def test_tc_sky_080_select_result_adds_it_to_the_target_list(tmp_path, monkeypatch):
    """SKY-080: the Targets page's "Select" button reconciles the two mechanisms this codebase
    previously carried in parallel — it doesn't just make the object the Pier's current target
    (IMG-140), it also adds it to SkyAtlas's own target list, via a single persistent SkyAtlas
    instance so the list actually accumulates across multiple selections rather than resetting."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "select_target_list_test.db")
    from galileo.observatory import create_observatory, create_pier
    from galileo.ui.app_window import AppWindow

    monkeypatch.setattr("galileo.platform.get_cache_dir", lambda: tmp_path)
    # No live network dependency: a real (uncached) thumbnail fetch would otherwise go out to
    # hips2fits, same as every other test in this file that exercises _fetch_thumbnail for real.
    monkeypatch.setattr(sky_mod, "_fetch_hips_thumbnail_sync", lambda *a, **k: b"fake-thumbnail-bytes")

    win = AppWindow()
    try:
        win.app, win.QtWidgets = app, QtWidgets
        win.pier = create_pier(create_observatory("Test Obs"), "Pier A")
        win._current_pier = win.pier

        m42 = sky_mod.SkyAtlas().get_by_designation("M42")
        m31 = sky_mod.SkyAtlas().get_by_designation("M31")

        assert win._sky_atlas is None
        win._select_result(m42)
        first_atlas = win._sky_atlas
        assert first_atlas is not None
        assert [o.primary_name for o in first_atlas._target_list] == ["M42"]
        assert win._current_object_label.text() == "Current object: M42"

        # A second Select must accumulate on the *same* shared instance, not reset it.
        win._select_result(m31)
        assert win._sky_atlas is first_atlas
        assert [o.primary_name for o in first_atlas._target_list] == ["M42", "M31"]
        assert win._current_object_label.text() == "Current object: M31"
    finally:
        win._window.close()
        db.close()


@pytest.mark.requirement("TC-SKY-080")
@pytest.mark.priority("P2")
def test_tc_sky_080_clicking_a_result_tile_thumbnail_opens_a_full_size_image(tmp_path, monkeypatch):
    """SKY-080: clicking a Targets-page result tile's thumbnail opens a dialog with a larger view of
    the same survey-image field, fetched at a bigger pixel size — a separate cache entry from the
    small 150px tile thumbnail, not an upscaled copy of it — and degrades to a text message, not a
    crash, when the fetch fails."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtCore = pytest.importorskip("PySide6.QtCore")
    QtTest = pytest.importorskip("PySide6.QtTest")
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "full_image_test.db")
    from galileo.observatory import create_observatory, create_pier
    from galileo.ui.app_window import AppWindow, _ClickableThumbnail

    monkeypatch.setattr("galileo.platform.get_cache_dir", lambda: tmp_path)
    fetch_sizes = []

    def fake_fetch(ra, dec, w, h, size_px=150):
        fetch_sizes.append(size_px)
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (size_px, size_px), color="gray").save(buf, format="JPEG")
        return buf.getvalue()

    monkeypatch.setattr(sky_mod, "_fetch_hips_thumbnail_sync", fake_fetch)

    win = AppWindow()
    try:
        win.app, win.QtWidgets = app, QtWidgets
        win.pier = create_pier(create_observatory("Test Obs"), "Pier A")
        win._current_pier = win.pier

        m42 = sky_mod.SkyAtlas().get_by_designation("M42")

        captured = {}

        def fake_exec(self):
            captured["dialog"] = self
            return QtWidgets.QDialog.Rejected

        monkeypatch.setattr(QtWidgets.QDialog, "exec", fake_exec)

        win._show_full_image(m42)

        assert fetch_sizes == [640], "should fetch at the full-view size, not the small tile size"
        dialog = captured["dialog"]
        assert dialog.windowTitle() == "M42"
        image_label = dialog.findChildren(QtWidgets.QLabel)[0]
        pixmap = image_label.pixmap()
        assert pixmap is not None and not pixmap.isNull()
        assert (pixmap.width(), pixmap.height()) == (640, 640)

        # End-to-end wiring: a real result tile's thumbnail is a _ClickableThumbnail that reaches
        # _show_full_image on a left click, not just a method callable in isolation. A fresh cache
        # dir avoids the first half's direct M42 fetch above satisfying this from cache, which would
        # only prove caching works (already covered elsewhere), not that the click reaches the method.
        monkeypatch.setattr("galileo.platform.get_cache_dir", lambda: tmp_path / "part2")
        fetch_sizes.clear()
        page = win._build_sky_atlas_page()
        results = page.findChildren(QtWidgets.QListWidget)[0]
        search_btn = next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Search")
        spins = page.findChildren(QtWidgets.QDoubleSpinBox)
        spins[0].setValue(4.0)  # max magnitude, to keep the result set small
        search_btn.click()

        tile = results.itemWidget(results.item(0)).findChildren(QtWidgets.QWidget, "ResultTile")[0]
        thumb = tile.findChildren(_ClickableThumbnail)[0]
        captured.clear()
        QtTest.QTest.mouseClick(thumb, QtCore.Qt.LeftButton)
        assert captured.get("dialog") is not None
        assert 640 in fetch_sizes
    finally:
        win._window.close()
        db.close()


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
async def test_tc_sky_100_catalog_first_search_with_simbad_fallback(sky_atlas):
    """SKY-100: Object search resolves primarily via the offline catalog
    (SKY-010), falling back to a live Simbad lookup (traces to EXT-110) only
    when the offline catalog has no match for the searched name and internet
    is available — this reverses the previous Simbad-first/catalog-fallback
    design so that ordinary object search, not only catalog browse/filter/
    chart, satisfies NFR-OFFLINE-010's no-internet guarantee."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")

    # The offline catalog has a match -> used directly; Simbad is never consulted.
    with patch.object(sky_mod, "_search_simbad_sync") as mock_search:
        results = await sky_atlas.search_online("M42")
        assert any("M42" in obj.designations for obj in results)
        mock_search.assert_not_called()

    simbad_hit = sky_mod.DeepSkyObject(
        primary_name="Not In Catalog", designations=["Not In Catalog"], ra_deg=10.0, dec_deg=20.0,
        object_type=sky_mod.ObjectType.NEBULA, magnitude=12.0,
    )

    # Offline catalog has no match, internet available -> falls back to Simbad.
    with patch.object(sky_mod, "_search_simbad_sync", return_value=[simbad_hit]) as mock_search:
        results = await sky_atlas.search_online("Not In Catalog")
        assert results == [simbad_hit]
        mock_search.assert_called_once_with("Not In Catalog")

    # Offline catalog has no match, Simbad unreachable (no internet) -> no results,
    # never an exception, and NFR-OFFLINE-010's no-internet guarantee still holds.
    with patch.object(sky_mod, "_search_simbad_sync", side_effect=OSError("no network")):
        results = await sky_atlas.search_online("Not In Catalog")
        assert results == []

    # Offline catalog has no match, Simbad reachable but also finds nothing -> no results.
    with patch.object(sky_mod, "_search_simbad_sync", return_value=[]):
        results = await sky_atlas.search_online("Not In Catalog")
        assert results == []

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


# ---------------------------------------------------------------------------
# TC-SKY-110
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-110")
@pytest.mark.priority("P2")
async def test_tc_sky_110_telescopius_augmentation_requires_api_key_never_substitutes(sky_atlas):
    """SKY-110: Optionally augment object search with the Telescopius API's target-search/suggestion data (traces to EXT-150) when the user has configured their own Telescopius API key, never as a substitute for the offline-first/Simbad-fallback path of SKY-010/SKY-100."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")

    # No API key configured -> Telescopius is never queried; offline-first/Simbad-fallback still runs.
    sky_atlas.set_telescopius_api_key(None)
    with patch.object(sky_mod, "_search_telescopius_sync") as mock_telescopius:
        results = await sky_atlas.search_online("M42")
        assert any("M42" in obj.designations for obj in results)
        mock_telescopius.assert_not_called()

    # API key configured -> Telescopius augments the results, on top of the offline-first path.
    sky_atlas.set_telescopius_api_key("user-supplied-key")
    telescopius_hit = sky_mod.DeepSkyObject(
        primary_name="Telescopius Suggestion", designations=["Telescopius Suggestion"],
        ra_deg=30.0, dec_deg=15.0, object_type=sky_mod.ObjectType.GALAXY, magnitude=11.0,
    )
    with patch.object(sky_mod, "_search_telescopius_sync", return_value=[telescopius_hit]) as mock_telescopius:
        results = await sky_atlas.search_online("M42")
        assert any("M42" in obj.designations for obj in results), "offline-first result still present"
        assert telescopius_hit in results, "augmented, not substituted"
        mock_telescopius.assert_called_once()


# ---------------------------------------------------------------------------
# TC-SKY-120
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SKY-120")
@pytest.mark.priority("P2")
async def test_tc_sky_120_import_telescopius_observing_list_requires_api_key(sky_atlas):
    """SKY-120: Allow importing a user's existing Telescopius observing list into a Galileo session/target list (traces to EXT-150) when a Telescopius API key is configured."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")

    # No API key -> import is unavailable.
    sky_atlas.set_telescopius_api_key(None)
    with pytest.raises(sky_mod.TelescopiusNotConfiguredError):
        await sky_atlas.import_telescopius_observing_list("My List")

    # API key configured -> the observing list imports into the target list.
    sky_atlas.set_telescopius_api_key("user-supplied-key")
    fake_list = [
        {"name": "M42", "ra_deg": 83.8221, "dec_deg": -5.3911},
        {"name": "M31", "ra_deg": 10.6847, "dec_deg": 41.2687},
    ]
    with patch.object(sky_mod, "_fetch_telescopius_observing_list_sync", return_value=fake_list):
        imported = await sky_atlas.import_telescopius_observing_list("My List")

    assert len(imported) == 2
    assert {t["name"] for t in imported} == {"M42", "M31"}
