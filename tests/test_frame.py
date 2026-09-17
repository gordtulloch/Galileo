"""FRAME — Framing Assistant (TC-FRAME-010 … TC-FRAME-060)."""

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
@pytest.mark.priority("P2")
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
@pytest.mark.priority("P2")
async def test_tc_frame_020_online_and_offline_sky_background(framing_assistant):
    """FRAME-020: Support at least one online sky-survey source and one offline/cached rendering mode."""
    frame_mod = pytest.importorskip("galileo.planning.framing")

    framing_assistant._fetch_online_image = AsyncMock(return_value=b"\x89PNG" + b"\x00" * 50)
    online = await framing_assistant.get_background(ra=83.8, dec=-5.4, mode="online")
    assert online is not None

    framing_assistant._render_offline = MagicMock(return_value=b"\x89PNG" + b"\x00" * 50)
    offline = framing_assistant.get_background_offline(ra=83.8, dec=-5.4)
    assert offline is not None


# ---------------------------------------------------------------------------
# TC-FRAME-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-030")
@pytest.mark.priority("P2")
def test_tc_frame_030_rotate_framing_rectangle(framing_assistant):
    """FRAME-030: Allow rotating the framing rectangle to preview a given camera/rotator position angle."""
    framing_assistant.set_rotation_angle(45.0)
    assert framing_assistant.rotation_angle == 45.0

    framing_assistant.set_rotation_angle(0.0)
    assert framing_assistant.rotation_angle == 0.0


# ---------------------------------------------------------------------------
# TC-FRAME-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-040")
@pytest.mark.priority("P3")
def test_tc_frame_040_mosaic_panel_grid(framing_assistant):
    """FRAME-040: Support defining a mosaic as a grid of overlapping panels with configurable overlap."""
    mosaic = framing_assistant.create_mosaic(
        center_ra=83.8, center_dec=-5.4,
        cols=3, rows=2, overlap_pct=10.0,
    )
    assert mosaic.total_panels == 6
    for panel in mosaic.panels:
        assert panel.overlap_pct == 10.0
        assert "ra" in panel.__dict__ or hasattr(panel, "ra")


# ---------------------------------------------------------------------------
# TC-FRAME-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FRAME-050")
@pytest.mark.priority("P2")
def test_tc_frame_050_send_framing_to_sequencer(framing_assistant):
    """FRAME-050: Allow a defined framing target (and each mosaic panel) to be sent to the sequencer as a target."""
    framing_assistant.set_target(ra=83.8221, dec=-5.3911, name="M42 Frame")
    target = framing_assistant.as_sequence_target()
    assert target["name"] == "M42 Frame"
    assert abs(target["ra_deg"] - 83.8221) < 0.001

    mosaic = framing_assistant.create_mosaic(center_ra=83.8, center_dec=-5.4, cols=2, rows=2, overlap_pct=10.0)
    panel_targets = [p.as_sequence_target() for p in mosaic.panels]
    assert len(panel_targets) == 4


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
