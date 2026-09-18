"""CAL — Calibration / Flat Wizard (TC-CAL-010 … TC-CAL-060)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def cal_service(mock_indi_camera, mock_filter_wheel, mock_flat_panel, tmp_path):
    cal_mod = pytest.importorskip("galileo.calibration")
    svc = cal_mod.CalibrationService(
        camera=mock_indi_camera,
        filter_wheel=mock_filter_wheel,
        flat_panel=mock_flat_panel,
        output_dir=tmp_path,
    )
    return svc


# ---------------------------------------------------------------------------
# TC-CAL-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-CAL-010")
@pytest.mark.priority("MVP")
async def test_tc_cal_010_adaptive_flat_exposure_to_target_adu(mock_indi_camera, cal_service):
    """CAL-010: Automated flat-frame capture routine adjusts exposure time to reach a configured target ADU."""
    import numpy as np
    call_count = [0]
    target_adu = 30000

    async def adaptive_expose(**kwargs):
        call_count[0] += 1

    async def get_frame():
        # After 2 attempts, 'succeed' at reaching target ADU
        adu = 10000 + call_count[0] * 15000
        return np.full((100, 100), min(adu, target_adu), dtype=np.uint16)

    mock_indi_camera.start_exposure = AsyncMock(side_effect=adaptive_expose)
    mock_indi_camera.get_image_array = AsyncMock(side_effect=get_frame)

    result = await cal_service.run_flat_wizard(
        filter_name="Ha",
        count=5,
        target_adu=target_adu,
        adu_tolerance=0.05,
    )
    assert result.frames_captured == 5
    assert result.final_exposure_s > 0


# ---------------------------------------------------------------------------
# TC-CAL-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-CAL-020")
@pytest.mark.priority("MVP")
async def test_tc_cal_020_flat_frames_for_all_filters(mock_indi_camera, mock_filter_wheel, cal_service):
    """CAL-020: Capture configured number of flat frames per active filter automatically, cycling the filter wheel."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.full((100, 100), 30000, dtype=np.uint16))

    results = await cal_service.run_flat_wizard_all_filters(count_per_filter=3, target_adu=30000)

    assert len(results) == len(mock_filter_wheel.filter_names)
    for r in results:
        assert r.frames_captured == 3


# ---------------------------------------------------------------------------
# TC-CAL-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-CAL-030")
@pytest.mark.priority("MVP")
async def test_tc_cal_030_dark_and_bias_capture(mock_indi_camera, cal_service, tmp_path):
    """CAL-030: Dark-frame and bias-frame capture sequences with configurable exposure/count/binning."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.float32))

    dark_result = await cal_service.capture_darks(exposure_s=300.0, count=10, binning=1)
    assert dark_result.frames_captured == 10

    bias_result = await cal_service.capture_biases(count=25, binning=1)
    assert bias_result.frames_captured == 25

    dark_files = list(tmp_path.rglob("*.fits"))
    assert len(dark_files) >= 10


# ---------------------------------------------------------------------------
# TC-CAL-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-CAL-040")
@pytest.mark.priority("MVP")
async def test_tc_cal_040_flat_panel_integration(mock_flat_panel, cal_service):
    """CAL-040: Integrate with a connected flat panel device to control brightness/cover as part of flat capture."""
    import numpy as np
    mock_flat_panel.cover_state = "Closed"
    cal_service._camera.get_image_array = AsyncMock(return_value=np.full((100, 100), 30000, dtype=np.uint16))

    await cal_service.run_flat_wizard(filter_name="L", count=5, target_adu=30000)

    mock_flat_panel.open_cover.assert_called()
    mock_flat_panel.set_brightness.assert_called()
    mock_flat_panel.close_cover.assert_called()


# ---------------------------------------------------------------------------
# TC-CAL-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-CAL-050")
@pytest.mark.priority("P2")
async def test_tc_cal_050_abort_if_adu_unreachable(mock_indi_camera, cal_service):
    """CAL-050: Abort and report the flat-capture routine if target ADU cannot be reached within exposure bounds."""
    import numpy as np
    # Always return images that are too dim regardless of exposure
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.uint16))

    cal_mod = pytest.importorskip("galileo.calibration")
    with pytest.raises(cal_mod.FlatCalibrationError, match="target ADU"):
        await cal_service.run_flat_wizard(
            filter_name="Ha",
            count=5,
            target_adu=30000,
            max_exposure_s=60.0,
        )


# ---------------------------------------------------------------------------
# TC-CAL-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-CAL-060")
@pytest.mark.priority("MVP")
def test_tc_cal_060_flat_wizard_is_not_a_top_level_navigation_section():
    """CAL-060: The flat-wizard workflow is presented within the Imaging tab, not as a separate top-level section."""
    from galileo.ui.app_window import PRIMARY_SECTIONS
    section_ids = [section[0] for section in PRIMARY_SECTIONS]
    assert "flat_wizard" not in section_ids
    assert "imaging" in section_ids
