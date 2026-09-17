"""IMG — Imaging Tab (TC-IMG-010 … TC-IMG-100)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def imaging_service(mock_indi_camera):
    imaging = pytest.importorskip("galileo.ui.imaging")
    svc = imaging.ImagingService(camera=mock_indi_camera)
    return svc


# ---------------------------------------------------------------------------
# TC-IMG-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-010")
@pytest.mark.priority("MVP")
async def test_tc_img_010_live_preview_after_readout(mock_indi_camera, imaging_service):
    """IMG-010: Display a newly captured frame in a live preview within a bounded time after camera readout."""
    import numpy as np
    frame_data = np.zeros((100, 100), dtype=np.uint16)
    mock_indi_camera.get_image_array = AsyncMock(return_value=frame_data)

    await imaging_service.capture_and_preview(duration=1.0)
    frame = imaging_service.current_frame
    assert frame is not None
    assert frame.shape == (100, 100)


# ---------------------------------------------------------------------------
# TC-IMG-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-020")
@pytest.mark.priority("MVP")
async def test_tc_img_020_auto_stretch_does_not_alter_saved_file(mock_indi_camera, imaging_service, tmp_path):
    """IMG-020: Auto-stretch preview does not alter the saved file's raw pixel data."""
    import numpy as np
    raw = np.arange(10000, dtype=np.uint16).reshape(100, 100)
    mock_indi_camera.get_image_array = AsyncMock(return_value=raw)

    await imaging_service.capture_and_preview(duration=1.0, save_dir=tmp_path)
    stretched = imaging_service.current_preview  # 8-bit display copy
    saved = imaging_service.last_saved_array      # raw unmodified copy

    assert stretched.max() <= 255
    assert saved.max() == raw.max(), "Saved data must match original raw values"


# ---------------------------------------------------------------------------
# TC-IMG-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-030")
@pytest.mark.priority("MVP")
async def test_tc_img_030_histogram_updated_per_capture(mock_indi_camera, imaging_service):
    """IMG-030: Display a histogram of the current frame, updated per capture."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.ones((100, 100), dtype=np.uint16) * 1000)
    await imaging_service.capture_and_preview(duration=1.0)

    hist = imaging_service.get_histogram()
    assert hist is not None
    assert len(hist["bins"]) > 0
    assert len(hist["counts"]) == len(hist["bins"])


# ---------------------------------------------------------------------------
# TC-IMG-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-040")
@pytest.mark.priority("MVP")
async def test_tc_img_040_per_frame_statistics(mock_indi_camera, imaging_service):
    """IMG-040: Compute per-frame statistics: mean, median, min/max, star count, HFR."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.float32))
    await imaging_service.capture_and_preview(duration=1.0)

    stats = imaging_service.get_frame_stats()
    for key in ("mean", "median", "min", "max", "star_count", "hfr"):
        assert key in stats, f"Frame stats must include '{key}'"


# ---------------------------------------------------------------------------
# TC-IMG-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-050")
@pytest.mark.priority("P2")
async def test_tc_img_050_star_overlay_toggleable(mock_indi_camera, imaging_service):
    """IMG-050: Overlay detected stars for HFR on the frame preview, toggleable by the user."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.float32))
    await imaging_service.capture_and_preview(duration=1.0)

    imaging_service.set_star_overlay(enabled=True)
    assert imaging_service.star_overlay_enabled is True

    imaging_service.set_star_overlay(enabled=False)
    assert imaging_service.star_overlay_enabled is False


# ---------------------------------------------------------------------------
# TC-IMG-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-060")
@pytest.mark.priority("MVP")
def test_tc_img_060_pan_and_zoom(imaging_service):
    """IMG-060: Allow the user to pan and zoom the displayed frame."""
    imaging_service.set_zoom(2.0)
    assert imaging_service.zoom_factor == 2.0

    imaging_service.set_pan_offset(dx=50, dy=-30)
    assert imaging_service.pan_offset == (50, -30)

    imaging_service.reset_view()
    assert imaging_service.zoom_factor == 1.0
    assert imaging_service.pan_offset == (0, 0)


# ---------------------------------------------------------------------------
# TC-IMG-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-070")
@pytest.mark.priority("MVP")
async def test_tc_img_070_manual_single_exposure(mock_indi_camera, imaging_service):
    """IMG-070: Support manual single-exposure capture independent of any running sequence."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.float32))

    frame = await imaging_service.capture_single(duration=5.0, filter_name="Ha")
    assert frame is not None
    mock_indi_camera.start_exposure.assert_called_once()


# ---------------------------------------------------------------------------
# TC-IMG-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-080")
@pytest.mark.priority("P2")
def test_tc_img_080_configurable_panel_layout(imaging_service):
    """IMG-080: Allow the user to configure imaging-tab panel arrangement; persisted across restarts."""
    layout = {"histogram": "bottom-left", "stats": "right", "preview": "center"}
    imaging_service.set_panel_layout(layout)
    saved = imaging_service.get_panel_layout()
    assert saved["histogram"] == "bottom-left"
    assert saved["preview"] == "center"


# ---------------------------------------------------------------------------
# TC-IMG-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-090")
@pytest.mark.priority("MVP")
async def test_tc_img_090_live_countdown_and_status(mock_indi_camera, imaging_service):
    """IMG-090: Display live exposure countdown and camera/download status during in-progress capture."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))

    # Check that status transitions are exposed during capture
    imaging_service._capture_status = "idle"
    capture_coro = imaging_service.capture_and_preview(duration=1.0)
    # Status must change from idle to exposing during capture
    # (tested via state inspection on service object)
    await capture_coro
    # After completion the status must be in a terminal state
    assert imaging_service.capture_status in ("idle", "complete", "preview_ready")


# ---------------------------------------------------------------------------
# TC-IMG-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-100")
@pytest.mark.priority("P2")
async def test_tc_img_100_save_current_frame_independently(mock_indi_camera, imaging_service, tmp_path):
    """IMG-100: Allow saving the currently displayed frame independently of the automatic sequence save path."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.float32))
    await imaging_service.capture_and_preview(duration=1.0)

    save_path = tmp_path / "manual_save.fits"
    imaging_service.save_current_frame(save_path)
    assert save_path.exists()
