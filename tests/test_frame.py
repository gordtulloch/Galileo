# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""FRAME — Framing Assistant (TC-FRAME-010 … TC-FRAME-090).

Invoked contextually (FRAME-070), not as a primary-navigation section: opened
from the Imaging tab's Framing… control (IMG-180) or a Session Image block's
own Framing… control (SES-130). Both entry points share every requirement
below and the same underlying design.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def framing_assistant(minimal_profile):
    frame_mod = pytest.importorskip("galileo.planning.framing")
    asst = frame_mod.FramingAssistant.from_profile(minimal_profile)
    return asst


# ---------------------------------------------------------------------------
# TC-FRAME-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-010")
@pytest.mark.priority("MVP")
def test_tc_frame_010_fov_rectangle_from_optical_train(minimal_profile, framing_assistant):
    """FRAME-010: Display FOV rectangle computed from active camera sensor and telescope focal length."""
    fov = framing_assistant.compute_fov()
    # FOV width = (sensor_width_px * pixel_size_um / focal_length_mm) * 206.265 / 3600 [degrees]
    expected_w_deg = (4656 * 5.86 / 1000.0) * 206.265 / 3600.0
    assert abs(fov.width_deg - expected_w_deg) < 0.01


# ---------------------------------------------------------------------------
# TC-FRAME-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-020")
@pytest.mark.priority("MVP")
async def test_tc_frame_020_online_and_offline_sky_background(framing_assistant):
    """FRAME-020: Support at least one online sky-survey source and one offline/cached rendering mode."""
    frame_mod = pytest.importorskip("galileo.planning.framing")

    framing_assistant._fetch_online_image = AsyncMock(return_value=b"\x89PNG" + b"\x00" * 50)
    online = await framing_assistant.get_background(ra=83.8, dec=-5.4, mode="online")
    assert online is not None

    framing_assistant._render_offline = MagicMock(return_value=b"\x89PNG" + b"\x00" * 50)
    offline = framing_assistant.get_background_offline(ra=83.8, dec=-5.4)
    assert offline is not None


@pytest.mark.requirement("TC-FRAME-020")
@pytest.mark.priority("MVP")
def test_tc_frame_020_survey_cutout_extent_is_padded_around_the_fov(framing_assistant):
    """FRAME-020: a survey-image fetch/preview requests a wider field than the FOV itself, so the
    FOV rectangle overlay reads as a frame against surrounding sky context, not fill the whole image."""
    fov = framing_assistant.compute_fov()

    ext_w, ext_h = framing_assistant.survey_cutout_extent_deg()

    assert ext_w > fov.width_deg
    assert ext_h > fov.height_deg


@pytest.mark.requirement("TC-FRAME-020")
@pytest.mark.priority("MVP")
def test_tc_frame_020_survey_cutout_extent_is_clamped_for_a_wide_field():
    """FRAME-020: a wide-field optical train whose (padded) FOV would exceed the sanity ceiling on
    a survey-image request is clamped to that ceiling rather than growing without bound — the
    real-world bug this originally covered (before the hips2fits migration): a short-focal-length/
    large-sensor rig's several-degree FOV, padded 3x for context, requested a cutout the old
    STScI dss_search service rejected outright, so the dialog silently showed nothing."""
    frame_mod = pytest.importorskip("galileo.planning.framing")
    wide_field = frame_mod.FramingAssistant(
        focal_length_mm=50, sensor_width_px=6000, sensor_height_px=4000, pixel_size_um=5.86)
    max_deg = frame_mod._MAX_HIPS_FOV_DEG

    ext_w, ext_h = wide_field.survey_cutout_extent_deg()

    assert ext_w == pytest.approx(max_deg)
    assert ext_h == pytest.approx(max_deg)


@pytest.mark.requirement("TC-FRAME-020")
@pytest.mark.priority("MVP")
def test_tc_frame_020_sync_fetch_falls_back_to_cache_without_raising(framing_assistant, monkeypatch):
    """FRAME-020: the Qt-side synchronous fetch helper never raises — an online failure falls back to
    any cached copy (or an empty result, never an exception, so a dialog can't crash opening it)."""
    frame_mod = pytest.importorskip("galileo.planning.framing")

    async def _boom(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr(framing_assistant, "_fetch_online_image", _boom)
    monkeypatch.setattr(framing_assistant, "_render_offline", lambda *a, **k: b"cached-bytes")

    data = framing_assistant.fetch_survey_image_sync(ra=83.8, dec=-5.4)

    assert data == b"cached-bytes"


# ---------------------------------------------------------------------------
# TC-FRAME-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-030")
@pytest.mark.priority("MVP")
def test_tc_frame_030_rotate_framing_rectangle(framing_assistant):
    """FRAME-030: Allow rotating the framing rectangle to preview a given camera/rotator position angle, where the active optical train has a rotator equipped; rotation is unavailable, not silently ignored, with no rotator present."""
    framing_assistant.set_rotation_angle(45.0)
    assert framing_assistant.rotation_angle == 45.0

    framing_assistant.set_rotation_angle(0.0)
    assert framing_assistant.rotation_angle == 0.0


@pytest.mark.requirement("TC-FRAME-030")
@pytest.mark.priority("MVP")
def test_tc_frame_030_rotation_unavailable_without_rotator(minimal_profile):
    """FRAME-030: With no rotator equipped on the active optical train, rotation is unavailable rather than silently ignored."""
    frame_mod = pytest.importorskip("galileo.planning.framing")
    import copy
    profile_no_rotator = copy.deepcopy(minimal_profile)
    profile_no_rotator["piers"][0]["optical_trains"][0].pop("rotator", None)
    asst = frame_mod.FramingAssistant.from_profile(profile_no_rotator)

    assert asst.rotator_available is False
    with pytest.raises(frame_mod.RotatorUnavailableError):
        asst.set_rotation_angle(45.0)


@pytest.mark.requirement("TC-FRAME-030")
@pytest.mark.priority("MVP")
def test_tc_frame_030_rotated_bounding_box_without_a_rotator(framing_assistant):
    """FRAME-030: with no rotator to physically tilt the frame, the FOV can still be framed at an
    angle by covering the tilted rectangle's axis-aligned bounding box with a mosaic instead —
    this is that bounding box. At 0 deg it's just the FOV; at 90 deg width/height swap."""
    fov = framing_assistant.compute_fov()

    identity = framing_assistant.rotated_frame_bounding_box_deg(0.0)
    assert identity[0] == pytest.approx(fov.width_deg)
    assert identity[1] == pytest.approx(fov.height_deg)

    swapped = framing_assistant.rotated_frame_bounding_box_deg(90.0)
    assert swapped[0] == pytest.approx(fov.height_deg)
    assert swapped[1] == pytest.approx(fov.width_deg)


# ---------------------------------------------------------------------------
# TC-FRAME-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-040")
@pytest.mark.priority("P2")
def test_tc_frame_040_mosaic_panel_grid(framing_assistant):
    """FRAME-040: Support defining a mosaic as a grid of overlapping panels, with a pane-overlap percentage configurable on the Imaging settings screen and shared by both Framing Assistant entry points rather than configured separately per entry point."""
    mosaic = framing_assistant.create_mosaic(
        center_ra=83.8, center_dec=-5.4,
        cols=3, rows=2, overlap_pct=10.0,
    )
    assert mosaic.total_panels == 6
    for panel in mosaic.panels:
        assert panel.overlap_pct == 10.0
        assert "ra" in panel.__dict__ or hasattr(panel, "ra")


@pytest.mark.requirement("TC-FRAME-040")
@pytest.mark.priority("P2")
def test_tc_frame_040_mosaic_footprint_matches_panel_spacing(framing_assistant):
    """FRAME-040: the mosaic's overall RA/Dec footprint (used to size a survey-image fetch/preview
    around the whole grid) matches the same panel spacing create_mosaic actually places panels at."""
    cols, rows, overlap_pct = 3, 2, 10.0
    mosaic = framing_assistant.create_mosaic(center_ra=83.8, center_dec=-5.4, cols=cols, rows=rows,
                                              overlap_pct=overlap_pct)
    ra_span = max(p.ra_deg for p in mosaic.panels) - min(p.ra_deg for p in mosaic.panels)
    dec_span = max(p.dec_deg for p in mosaic.panels) - min(p.dec_deg for p in mosaic.panels)
    fov = framing_assistant.compute_fov()

    width_deg, height_deg = framing_assistant.mosaic_footprint_deg(cols, rows, overlap_pct)

    assert abs(width_deg - (ra_span + fov.width_deg)) < 1e-9
    assert abs(height_deg - (dec_span + fov.height_deg)) < 1e-9


@pytest.mark.requirement("TC-FRAME-040")
@pytest.mark.priority("P2")
def test_tc_frame_040_mosaic_grid_to_cover_a_target_area(framing_assistant):
    """FRAME-040: the smallest mosaic grid whose footprint fully contains a given area — one frame
    needs a 1x1 grid, anything larger needs to grow the grid until it's covered."""
    fov = framing_assistant.compute_fov()

    assert framing_assistant.mosaic_grid_to_cover_deg(fov.width_deg, fov.height_deg, overlap_pct=0.0) == (1, 1)
    assert framing_assistant.mosaic_grid_to_cover_deg(
        fov.width_deg * 1.5, fov.height_deg, overlap_pct=0.0) == (2, 1)
    assert framing_assistant.mosaic_grid_to_cover_deg(
        fov.width_deg, fov.height_deg * 2.5, overlap_pct=0.0) == (1, 3)


@pytest.mark.requirement("TC-FRAME-040")
@pytest.mark.priority("P2")
def test_tc_frame_040_pane_overlap_shared_across_entry_points():
    """FRAME-040: The pane-overlap setting is one shared, Imaging-settings-scoped value, not configured separately per Framing Assistant entry point (Imaging tab vs. Session Image block)."""
    frame_mod = pytest.importorskip("galileo.planning.framing")
    settings = frame_mod.MosaicSettings.instance()
    settings.set_pane_overlap_pct(15.0)

    assert frame_mod.MosaicSettings.instance().pane_overlap_pct == 15.0
    # A second, independently-constructed assistant sees the same shared setting.
    another = frame_mod.MosaicSettings.instance()
    assert another.pane_overlap_pct == 15.0


# ---------------------------------------------------------------------------
# TC-FRAME-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-050")
@pytest.mark.priority("P2")
def test_tc_frame_050_single_frame_attaches_to_opening_context(framing_assistant):
    """FRAME-050: Attach a defined framing target — a single frame, or, where a mosaic grid is defined, the whole mosaic as one unit — to whichever context opened the Framing Assistant, as that context's own capture target."""
    framing_assistant.set_target(ra=83.8221, dec=-5.3911, name="M42 Frame")
    target = framing_assistant.attach_to_context()
    assert target["name"] == "M42 Frame"
    assert abs(target["ra_deg"] - 83.8221) < 0.001


@pytest.mark.requirement("TC-FRAME-050")
@pytest.mark.priority("P2")
def test_tc_frame_050_mosaic_attaches_as_one_unit_not_per_panel_targets(framing_assistant):
    """FRAME-050: A defined mosaic grid attaches to the opening context as one unit (traces to FRAME-090) — this supersedes the earlier "each mosaic panel sent to the sequencer as its own target" model; a mosaic is owned and captured internally by one Imaging-tab run or one Image block, not decomposed into separate per-panel targets upstream of capture."""
    mosaic = framing_assistant.create_mosaic(center_ra=83.8, center_dec=-5.4, cols=2, rows=2, overlap_pct=10.0)
    framing_assistant.set_mosaic(mosaic)

    target = framing_assistant.attach_to_context()

    # One capture target owning the whole mosaic internally...
    assert target["mosaic"] is mosaic
    assert target["is_mosaic"] is True
    # ...not a list of separate per-panel targets handed upstream to the sequencer.
    assert not hasattr(framing_assistant, "as_sequence_target")
    assert not any(hasattr(p, "as_sequence_target") for p in mosaic.panels)


# ---------------------------------------------------------------------------
# TC-FRAME-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-060")
@pytest.mark.priority("P2")
def test_tc_frame_060_constellation_lines_and_grid_overlay(framing_assistant):
    """FRAME-060: Overlay constellation lines and a coordinate grid on the framing view."""
    framing_assistant.set_overlay(constellations=True, coordinate_grid=True)
    assert framing_assistant.show_constellations is True
    assert framing_assistant.show_grid is True

    framing_assistant.set_overlay(constellations=False, coordinate_grid=False)
    assert framing_assistant.show_constellations is False
    assert framing_assistant.show_grid is False


# ---------------------------------------------------------------------------
# TC-FRAME-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-070")
@pytest.mark.priority("MVP")
def test_tc_frame_070_only_contextual_invocation_no_standalone_route():
    """FRAME-070: Present the Framing Assistant only when invoked from the Imaging tab (IMG-180) or a Session Image block (SES-130), never as a primary-navigation section of its own, and return to whichever context opened it when closed."""
    frame_mod = pytest.importorskip("galileo.planning.framing")

    # No bare top-level constructor/route: only the two named entry points exist.
    assert hasattr(frame_mod, "open_from_imaging_tab")
    assert hasattr(frame_mod, "open_from_session_image_block")
    assert not hasattr(frame_mod, "PRIMARY_NAV_ENTRY"), \
        "Framing Assistant must not register as a primary-navigation section"

    imaging_context = MagicMock(name="ImagingTabContext")
    asst = frame_mod.open_from_imaging_tab(imaging_context)
    assert asst.opening_context is imaging_context

    returned_to = asst.close()
    assert returned_to is imaging_context


@pytest.mark.requirement("TC-FRAME-070")
@pytest.mark.priority("MVP")
def test_tc_frame_070_session_image_block_entry_point_keeps_independent_state(framing_assistant):
    """FRAME-070: Each entry point retains its own independent framing/mosaic state — the Imaging tab's current setup is separate from a given Session Image block's own stored definition."""
    frame_mod = pytest.importorskip("galileo.planning.framing")

    imaging_context = MagicMock(name="ImagingTabContext")
    session_block_context = MagicMock(name="SessionImageBlockContext")

    from_imaging = frame_mod.open_from_imaging_tab(imaging_context)
    from_imaging.set_target(ra=83.8221, dec=-5.3911, name="M42 Frame")

    from_block = frame_mod.open_from_session_image_block(session_block_context)
    from_block.set_target(ra=10.6847, dec=41.2687, name="M31 Frame")

    assert from_imaging.target_name == "M42 Frame"
    assert from_block.target_name == "M31 Frame"  # independent state, not shared


# ---------------------------------------------------------------------------
# TC-FRAME-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-080")
@pytest.mark.priority("P2")
def test_tc_frame_080_compare_cameras_overlays_every_pier_camera(framing_assistant):
    """FRAME-080: Provide a Compare Cameras control that overlays a field-of-view rectangle for every camera configured across every Pier in the current Observatory — not only the currently active one — with the survey image auto-scaled to the largest field size among them."""
    frame_mod = pytest.importorskip("galileo.planning.framing")

    cam_small = frame_mod.FovSpec(width_deg=0.5, height_deg=0.3, pier_name="Pier-1", camera_name="Small")
    cam_large = frame_mod.FovSpec(width_deg=2.0, height_deg=1.5, pier_name="Pier-2", camera_name="Large")
    observatory = MagicMock(name="Backyard")
    observatory.all_camera_fovs = MagicMock(return_value=[cam_small, cam_large])

    comparison = framing_assistant.compare_cameras(observatory)

    assert {f.camera_name for f in comparison.fovs} == {"Small", "Large"}
    assert comparison.survey_scale_deg == pytest.approx(2.0)  # scaled to the largest field size


# ---------------------------------------------------------------------------
# TC-FRAME-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-090")
@pytest.mark.priority("P2")
def test_tc_frame_090_mosaic_capture_is_pane_major_round_robin(framing_assistant):
    """FRAME-090: Where a target includes a defined mosaic grid, slew to and capture one exposure at each pane in turn before repeating the pass for any additional exposures per pane, rather than completing all of one pane's exposures before moving to the next. The re-slew between passes is what dithers a pane's frames against each other."""
    mosaic = framing_assistant.create_mosaic(center_ra=83.8, center_dec=-5.4, cols=2, rows=1, overlap_pct=10.0)

    order = framing_assistant.mosaic_capture_order(mosaic, exposures_per_pane=3)

    pane_ids = [p.pane_index for p in mosaic.panels]
    # Pane-major: pass 1 visits every pane once, then pass 2 visits every pane again, etc.
    expected = pane_ids * 3
    assert [step.pane_index for step in order] == expected
    # NOT pane-complete-then-next (which would be [pane0]*3 + [pane1]*3 + ...).
    assert [step.pane_index for step in order] != sorted(expected)


@pytest.mark.requirement("TC-FRAME-090")
@pytest.mark.priority("P2")
def test_tc_frame_090_reslew_between_passes_is_the_dither_mechanism(framing_assistant):
    """FRAME-090: The inter-pass re-slew dithers a pane's frames against each other; it is distinct from and does not require a separate guider-dither command (GUIDE-030) between exposures of an unchanged target."""
    mosaic = framing_assistant.create_mosaic(center_ra=83.8, center_dec=-5.4, cols=2, rows=1, overlap_pct=10.0)

    order = framing_assistant.mosaic_capture_order(mosaic, exposures_per_pane=2)

    # Consecutive steps within one pass target *different* panes (a re-slew each time),
    # so no guider-dither command is needed between them.
    for step in order:
        assert step.requires_guider_dither is False
        assert step.requires_reslew is True
