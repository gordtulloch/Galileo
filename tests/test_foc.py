# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""FOC — Autofocus (TC-FOC-010 … TC-FOC-080)."""

import pytest
import numpy as np
from unittest.mock import AsyncMock


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

    async def mock_measure_hfr(confirm=False):
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

    async def mock_hfr(confirm=False):
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


@pytest.mark.requirement("TC-FOC-070")
@pytest.mark.priority("MVP")
async def test_tc_foc_070_backlash_compensation_overshoots_before_every_move(mock_indi_camera, mock_focuser, tmp_path):
    """FOC-070: a configured backlash compensation actually overshoots-then-returns on every
    focuser move during a run, not just a dataclass field nothing reads."""
    foc_mod = pytest.importorskip("galileo.autofocus")
    svc = foc_mod.AutofocusService(
        camera=mock_indi_camera, focuser=mock_focuser, output_dir=tmp_path, backlash_compensation=50,
    )
    await svc._move_to(5000)
    assert mock_focuser.move_to.await_args_list == [((4950,),), ((5000,),)]


@pytest.mark.requirement("TC-FOC-070")
@pytest.mark.priority("MVP")
async def test_tc_foc_070_zero_backlash_moves_directly(mock_indi_camera, mock_focuser, foc_service):
    """FOC-070: the default (no backlash configured) moves straight to the target, unchanged."""
    await foc_service._move_to(5000)
    mock_focuser.move_to.assert_awaited_once_with(5000)


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


# ---------------------------------------------------------------------------
# TC-FOC-090 — the run is reported on the event bus (what the Focus screen follows)
# ---------------------------------------------------------------------------

@pytest.fixture
def focus_events(foc_service, monkeypatch):
    """The service on a private bus, recording every focus event; star measurement is stubbed
    to a V-curve so the tests don't depend on SEP."""
    from galileo import autofocus as foc_mod
    from galileo.bus import (
        EventBus,
        FocusCompleteEvent,
        FocusFrameEvent,
        FocusStartedEvent,
    )

    monkeypatch.setattr(foc_mod, "_measure_stars", lambda frame: (_synthetic_hfr(foc_service._current_position), 12))
    foc_service._camera.get_image_array = AsyncMock(return_value=np.zeros((20, 30), dtype=np.float32))
    bus = EventBus()
    foc_service._event_bus = bus
    seen: list = []
    for event_type in (FocusStartedEvent, FocusFrameEvent, FocusCompleteEvent):
        bus.subscribe(event_type, seen.append)
    return seen


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
async def test_tc_foc_090_run_publishes_start_each_frame_and_completion(foc_service, mock_focuser, focus_events):
    """FOC-090: a run reports its start, every measured frame (with star count, HFR, FWHM) and its result."""
    foc_service.exposure_s = 2.5
    result = await foc_service.run(step_size=100, num_points=5)

    # 5 sweep frames plus 1 confirmation frame at the best-focus position (FOC-020)
    kinds = [type(e).__name__ for e in focus_events]
    assert kinds == ["FocusStartedEvent"] + ["FocusFrameEvent"] * 6 + ["FocusCompleteEvent"]
    started, *frames, complete = focus_events
    sweep_frames, confirm_frame = frames[:5], frames[5]
    assert started.payload["positions"] == [4800, 4900, 5000, 5100, 5200]
    assert [f.payload["position"] for f in sweep_frames] == started.payload["positions"]
    assert sweep_frames[2].payload["hfr"] == pytest.approx(1.0)
    assert sweep_frames[2].payload["fwhm"] == pytest.approx(1.5)
    assert sweep_frames[2].payload["star_count"] == 12
    assert sweep_frames[0].payload["frame"].shape == (20, 30)
    assert all(not f.payload.get("confirm", False) for f in sweep_frames)
    assert complete.payload["result"] is result and result.success
    # the focuser actually ends up at the computed best-focus position
    assert confirm_frame.payload["position"] == result.best_position
    assert confirm_frame.payload["confirm"] is True
    mock_focuser.move_to.assert_called_with(result.best_position)
    # each frame is a fresh exposure of the configured length, including the confirmation
    assert foc_service._camera.start_exposure.await_count == 6
    foc_service._camera.start_exposure.assert_awaited_with(duration=2.5)


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
async def test_tc_foc_090_a_failed_run_still_publishes_completion(foc_service, focus_events):
    """FOC-090: a run that fails reports that too, so a screen following it never waits on a run that has ended."""
    foc_service._camera.get_image_array = AsyncMock(return_value=None)
    result = await foc_service.run(step_size=100, num_points=3)

    assert not result.success
    assert [type(e).__name__ for e in focus_events] == ["FocusStartedEvent", "FocusCompleteEvent"]
    assert focus_events[-1].payload["result"] is result


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
async def test_tc_foc_090_cancel_stops_the_run_and_restores_the_focuser(foc_service, mock_focuser, focus_events):
    """FOC-090: cancelling a run stops it after the exposure in progress and puts the focuser back where it began."""
    from galileo.bus import FocusFrameEvent

    foc_service._event_bus.subscribe(FocusFrameEvent, lambda e: foc_service.cancel() if e.payload["position"] == 4900 else None)
    result = await foc_service.run(step_size=100, num_points=5)

    assert not result.success and result.failure_reason == "Cancelled"
    assert [e.payload["position"] for e in focus_events if isinstance(e, FocusFrameEvent)] == [4800, 4900]
    mock_focuser.move_to.assert_called_with(5000)
    assert type(focus_events[-1]).__name__ == "FocusCompleteEvent"
