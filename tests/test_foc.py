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

    pytest.importorskip("galileo.autofocus")
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


@pytest.mark.requirement("TC-FOC-070")
@pytest.mark.priority("MVP")
def test_tc_foc_070_measure_stars_accepts_non_contiguous_frame():
    """FOC-070: star measurement must not fall back to the contrast estimate (SEP rejects
    non-C-contiguous arrays) when a frame arrives transposed/F-ordered."""
    from galileo.autofocus import _measure_stars
    rng = np.random.default_rng(1)
    frame = rng.normal(800, 20, (200, 300)).astype(np.float32)
    yy, xx = np.mgrid[-6:7, -6:7]
    star = 20000 * np.exp(-(yy ** 2 + xx ** 2) / 6.0)
    for y, x in ((50, 60), (120, 200), (150, 90)):
        frame[y - 6:y + 7, x - 6:x + 7] += star
    f_ordered = np.asfortranarray(frame)
    assert not f_ordered.flags["C_CONTIGUOUS"]
    _hfr, stars = _measure_stars(f_ordered)
    assert stars >= 3


# ---------------------------------------------------------------------------
# TC-FOC-100 … 130 — manual focus
# ---------------------------------------------------------------------------

class _Focuser:
    def __init__(self, position=5000, max_step=10000, temperature=4.5):
        self.position, self.max_step, self.temperature = position, max_step, temperature
        self.moves = []

    async def move_to(self, position):
        self.moves.append(position)
        self.position = position


@pytest.mark.requirement("TC-FOC-100")
@pytest.mark.priority("MVP")
async def test_tc_foc_100_manual_moves_halt_and_readings_need_no_screen():
    """FOC-100: manual focus moves in or out by a step, moves to an absolute position, halts and reads the
    position and temperature, as functions of the focus module."""
    from galileo.autofocus import ManualFocus
    f = _Focuser()
    mf = ManualFocus(f)
    assert mf.position() == 5000 and mf.temperature() == 4.5
    assert await mf.move_by(-120) == 4880 and f.position == 4880
    assert await mf.move_by(300) == 5180 and await mf.move_to(7000) == 7000 and f.moves[-1] == 7000
    await mf.halt()
    assert f.moves[-1] == 7000                                          # no halt of its own: holds where it is
    stopped = []
    f.halt = lambda: stopped.append(True)
    await mf.halt()
    assert stopped == [True]
    assert ManualFocus(_Focuser(temperature=None)).temperature() is None
    assert ManualFocus(object()).position() is None
    with pytest.raises(ValueError):
        await ManualFocus(object()).move_by(10)


@pytest.mark.requirement("TC-FOC-100")
@pytest.mark.priority("MVP")
async def test_tc_foc_100_limits_and_backlash_are_applied_once():
    """FOC-100 / FOC-110: the focuser's own travel and the user's limits hold every move; with a backlash
    set the focuser approaches the target from the same side."""
    from galileo.autofocus import ManualFocus
    f = _Focuser(position=100, max_step=9000)
    mf = ManualFocus(f, travel_min=500, travel_max=8000)
    assert mf.clamp(-5) == 500 and mf.clamp(20000) == 8000 and mf.clamp(4000) == 4000
    assert await mf.move_to(9500) == 8000 and f.position == 8000
    assert await mf.move_by(-99999) == 500
    assert ManualFocus(_Focuser(max_step=6000), travel_max=8000).clamp(7000) == 6000       # the tighter wins
    f2 = _Focuser(position=3000)
    await ManualFocus(f2, backlash=150).move_to(3500)
    assert f2.moves == [3350, 3500]
    f3 = _Focuser(position=3000)
    await ManualFocus(f3, backlash=150, travel_min=100).move_to(120)
    assert f3.moves == [100, 120]                                       # the overshoot is limited too


@pytest.mark.requirement("TC-FOC-110")
@pytest.mark.priority("MVP")
def test_tc_foc_110_the_focus_screen_uses_the_modules_manual_focus():
    """FOC-110: the desktop Focus screen consumes ManualFocus instead of driving the focuser itself."""
    import inspect

    from galileo.ui import focus
    source = inspect.getsource(focus.FocusPage.manual_move)
    assert "ManualFocus" in source and "move_to(" in source and ".move_to(position)" not in source.replace(
        "manual.move_to(position)", "")


@pytest.mark.requirement("TC-FOC-120")
@pytest.mark.priority("MVP")
async def test_tc_foc_120_control_surface_offers_focus_not_a_generic_focuser_move():
    """FOC-120: manual focus is published under the focus area, from the module's own ManualFocus; a
    remote client reaches it through the registry and gets the same limits."""
    from galileo.autofocus import ManualFocus
    from galileo.control_surface import Arg, OperationSpec, Registry

    f = _Focuser(position=5000, max_step=6000)
    mf = ManualFocus(f)
    reg = Registry()
    reg.register(OperationSpec("focus.move_to", "operate", (Arg("position", "int", minimum=0),), needs_lease=True),
                 lambda ctx, a: mf.move_to(a["position"]))
    reg.register(OperationSpec("focus.move_by", "operate", (Arg("steps", "int"),), needs_lease=True),
                 lambda ctx, a: mf.move_by(a["steps"]))
    assert not any(n.startswith("focuser.") for n in reg.names())
    assert (await reg.invoke("focus.move_to", {"position": 9000}, "p1", "c")).value == 6000        # same limit
    assert (await reg.invoke("focus.move_by", {"steps": -1000}, "p1", "c")).value == 5000


@pytest.mark.requirement("TC-FOC-130")
@pytest.mark.priority("MVP")
async def test_tc_foc_130_a_held_move_runs_while_beats_arrive_and_stops_on_the_deadman():
    """FOC-130: a held move keeps stepping while the keep-alive arrives and halts when it stops, using the
    deadman semantics of CSURF-400."""
    import asyncio

    from galileo.autofocus import ManualFocus
    from galileo.control_surface import HoldManager

    now = [0.0]
    holds = HoldManager(lambda: now[0], beat_s=0.25, deadman_s=0.6)
    f = _Focuser(position=1000)
    halted = []
    f.halt = lambda: halted.append(f.position)
    mf = ManualFocus(f, pier_key="p1", step=10)
    hold_id = mf.start_hold(holds, +1, "client-a")
    for _ in range(20):
        await asyncio.sleep(0)
    assert f.position > 1000 and holds.active("p1") == [hold_id]
    moved = f.position
    now[0] += 0.3
    holds.beat(hold_id, "client-a")
    now[0] += 0.5
    assert holds.check() == 0                                           # a beat 0.5 s ago is still fresh
    now[0] += 0.2
    assert holds.check() == 1
    for _ in range(20):
        await asyncio.sleep(0)
    assert halted and holds.active("p1") == []
    settled = f.position
    for _ in range(20):
        await asyncio.sleep(0)
    assert f.position == settled >= moved                                # nothing moves after the stop
    inward = mf.start_hold(holds, -1, "client-a")
    for _ in range(10):
        await asyncio.sleep(0)
    assert f.position < settled
    assert holds.cancel_pier("p1", "lease changed") == 1 and inward
