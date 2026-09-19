# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""FOC — Autofocus (TC-FOC-010 … TC-FOC-080)."""

import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def foc_service(mock_indi_camera, mock_focuser, tmp_path):
    foc_mod = pytest.importorskip("galileo.autofocus")
    svc = foc_mod.AutofocusService(
        camera=mock_indi_camera,
        focuser=mock_focuser,
        output_dir=tmp_path,
    )
    return svc


def _synthetic_hfr(position: int, best: int = 5000, width: float = 500.0) -> float:
    """V-curve HFR model: HFR(p) = 1 + ((p - best) / width) ** 2."""
    return 1.0 + ((position - best) / width) ** 2



# ---------------------------------------------------------------------------
# TC-FOC-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FOC-010")
@pytest.mark.priority("MVP")
async def test_tc_foc_010_hfr_curve_fit_to_best_focus(mock_indi_camera, mock_focuser, foc_service):
    """FOC-010: Autofocus samples HFR at multiple focuser positions and fits a curve to determine best focus."""
    positions = [4000, 4250, 4500, 4750, 5000, 5250, 5500, 5750, 6000]
    hfr_values = [_synthetic_hfr(p, best=5000) for p in positions]

    call_idx = [0]

    async def mock_measure_hfr():
        hfr = hfr_values[call_idx[0] % len(hfr_values)]
        call_idx[0] += 1
        return hfr

    foc_service._measure_hfr = AsyncMock(side_effect=mock_measure_hfr)
    result = await foc_service.run(step_size=250, num_points=9)

    assert result.success is True
    assert abs(result.best_position - 5000) < 300


# ---------------------------------------------------------------------------
# TC-FOC-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FOC-020")
@pytest.mark.priority("MVP")
async def test_tc_foc_020_move_to_best_and_confirm(mock_focuser, foc_service):
    """FOC-020: Move focuser to computed best-focus position and verify with a confirmation exposure."""
    foc_service._measure_hfr = AsyncMock(return_value=1.2)
    foc_service._last_best_position = 5050

    await foc_service.apply_and_confirm(best_position=5050)
    mock_focuser.move_to.assert_called_with(5050)
    assert foc_service._measure_hfr.call_count >= 1  # confirmation exposure taken


# ---------------------------------------------------------------------------
# TC-FOC-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FOC-030")
@pytest.mark.priority("MVP")
async def test_tc_foc_030_report_failure_distinctly(mock_indi_camera, mock_focuser, foc_service):
    """FOC-030: Report autofocus failure distinctly; do not leave focuser at untested position."""
    initial_position = mock_focuser.position

    foc_service._measure_hfr = AsyncMock(return_value=float("nan"))

    foc_mod = pytest.importorskip("galileo.autofocus")
    result = await foc_service.run(step_size=250, num_points=5)

    assert result.success is False
    assert result.failure_reason != ""
    # Focuser must be returned to the position it started at
    mock_focuser.move_to.assert_called_with(initial_position)


# ---------------------------------------------------------------------------
# TC-FOC-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FOC-040")
@pytest.mark.priority("P2")
async def test_tc_foc_040_record_run_for_later_review(foc_service, tmp_path):
    """FOC-040: Record each autofocus run's sample points and resulting curve for later review."""
    positions = [4500, 4750, 5000, 5250, 5500]
    hfr_values = [_synthetic_hfr(p, best=5000) for p in positions]
    call_idx = [0]

    async def mock_hfr():
        v = hfr_values[call_idx[0] % len(hfr_values)]
        call_idx[0] += 1
        return v

    foc_service._measure_hfr = AsyncMock(side_effect=mock_hfr)
    result = await foc_service.run(step_size=250, num_points=5)

    assert result.sample_points is not None
    assert len(result.sample_points) == 5
    assert result.curve_coefficients is not None


# ---------------------------------------------------------------------------
# TC-FOC-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FOC-050")
@pytest.mark.priority("MVP")
async def test_tc_foc_050_manual_and_trigger_invocation(foc_service):
    """FOC-050: Autofocus invocable both manually (on demand) and via sequencer triggers."""
    foc_service._measure_hfr = AsyncMock(return_value=1.0)
    foc_service._last_best_position = 5000

    # Manual invocation
    await foc_service.run_manual(step_size=250, num_points=5)
    assert foc_service.last_run is not None

    # Trigger-based invocation (same entry point with 'trigger' context)
    await foc_service.run_triggered(reason="hfr_increase", threshold=0.2)
    assert foc_service.last_run is not None


# ---------------------------------------------------------------------------
# TC-FOC-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FOC-060")
@pytest.mark.priority("P2")
async def test_tc_foc_060_apply_filter_offset_without_full_run(mock_focuser, foc_service):
    """FOC-060: Apply per-filter focus offset on filter change without a full autofocus run."""
    foc_service._filter_offsets = {"Ha": 0, "OIII": -50, "SII": 10}
    foc_service._current_position = 5000

    await foc_service.apply_filter_offset(from_filter="Ha", to_filter="OIII")
    expected = 5000 + (-50 - 0)
    mock_focuser.move_to.assert_called_with(expected)


# ---------------------------------------------------------------------------
# TC-FOC-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FOC-070")
@pytest.mark.priority("MVP")
def test_tc_foc_070_autofocus_params_per_profile(minimal_profile):
    """FOC-070: Allow configuration of autofocus parameters (step size, points, exposure, backlash) per profile."""
    foc_mod = pytest.importorskip("galileo.autofocus")
    params = foc_mod.AutofocusParams(
        step_size=150,
        num_points=9,
        exposure_s=5.0,
        backlash_compensation=50,
    )
    assert params.step_size == 150
    assert params.num_points == 9
    assert params.exposure_s == 5.0
    assert params.backlash_compensation == 50


# ---------------------------------------------------------------------------
# TC-FOC-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-FOC-080")
@pytest.mark.priority("P2")
async def test_tc_foc_080_aberration_inspection_per_region(mock_indi_camera, foc_service):
    """FOC-080: Aberration-inspection tool computing per-region HFR/tilt indicators across the frame."""
    frame = np.zeros((600, 800), dtype=np.float32)
    # Plant synthetic stars at corners to simulate tilt
    for cy, cx, fwhm in [(75, 100, 3.0), (75, 700, 5.0), (525, 100, 4.5), (525, 700, 6.0)]:
        y, x = np.mgrid[0:600, 0:800]
        frame += np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * fwhm ** 2))

    mock_indi_camera.get_image_array = AsyncMock(return_value=frame)
    result = await foc_service.run_aberration_inspection()

    assert result is not None
    assert len(result.regions) >= 3
    for region in result.regions:
        assert "hfr" in region or hasattr(region, "hfr")
