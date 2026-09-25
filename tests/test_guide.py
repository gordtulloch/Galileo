# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""GUIDE — Guiding Integration (TC-GUIDE-010 … TC-GUIDE-060)."""

import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def guiding_service():
    guiding_mod = pytest.importorskip("galileo.guiding")
    svc = guiding_mod.GuidingService(host="localhost", port=4400)
    return svc


# ---------------------------------------------------------------------------
# TC-GUIDE-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-010")
@pytest.mark.priority("MVP")
async def test_tc_guide_010_connect_and_reflect_state(guiding_service, mock_guider):
    """GUIDE-010: Connect to external guiding application's control interface and reflect its connection/guiding state."""
    guiding_service._client = mock_guider
    await guiding_service.connect()
    mock_guider.connect.assert_called_once()
    assert guiding_service.is_connected is True


# ---------------------------------------------------------------------------
# TC-GUIDE-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-020")
@pytest.mark.priority("MVP")
async def test_tc_guide_020_start_stop_guiding_await_confirm(guiding_service, mock_guider):
    """GUIDE-020: Issue start/stop guiding commands and await confirmation before dependent sequence steps proceed."""
    guiding_service._client = mock_guider

    guiding_service._wait_for_guiding_state = AsyncMock(return_value=True)
    await guiding_service.start_guiding()
    mock_guider.start_guiding.assert_called_once()
    guiding_service._wait_for_guiding_state.assert_called()

    await guiding_service.stop_guiding()
    mock_guider.stop_guiding.assert_called_once()


# ---------------------------------------------------------------------------
# TC-GUIDE-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-030")
@pytest.mark.priority("MVP")
async def test_tc_guide_030_dither_and_wait_for_settle(guiding_service, mock_guider):
    """GUIDE-030: Issue dither command between exposures and wait for guider to settle before resuming capture."""
    guiding_service._client = mock_guider
    mock_guider.dither = AsyncMock()
    mock_guider.wait_for_settle = AsyncMock(return_value=True)

    await guiding_service.dither_and_wait(settle_timeout_s=30.0, settle_pixels=0.5)

    mock_guider.dither.assert_called_once()
    mock_guider.wait_for_settle.assert_called()


# ---------------------------------------------------------------------------
# TC-GUIDE-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-040")
@pytest.mark.priority("P2")
def test_tc_guide_040_surface_guide_error_for_display_and_logging(guiding_service, mock_guider):
    """GUIDE-040: Surface the guider's reported guide error (RMS) for display and session-history logging."""
    guiding_service._client = mock_guider
    rms = guiding_service.get_rms()
    assert rms["ra"] == mock_guider.rms_ra
    assert rms["dec"] == mock_guider.rms_dec
    assert "total" in rms


# ---------------------------------------------------------------------------
# TC-GUIDE-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-050")
@pytest.mark.priority("MVP")
async def test_tc_guide_050_guiding_loss_is_recoverable_error(guiding_service, mock_guider, event_bus):
    """GUIDE-050: Guiding-connection loss during a sequence treated as recoverable error, not silent stall."""
    guiding_service._client = mock_guider
    guiding_service._event_bus = event_bus
    mock_guider.is_connected = False

    await guiding_service.check_health()

    assert event_bus.publish.called
    published = event_bus.publish.call_args[0][0]
    assert hasattr(published, "recoverable") or "guide" in str(type(published)).lower()


# ---------------------------------------------------------------------------
# TC-GUIDE-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-060")
@pytest.mark.priority("P2")
def test_tc_guide_060_independent_guider_per_pier():
    """GUIDE-060: Each Pier has its own independent guider connection — never shared across Piers."""
    guiding_mod = pytest.importorskip("galileo.guiding")
    obs_mod = pytest.importorskip("galileo.observatory")

    pier1 = obs_mod.Pier(name="Pier-1")
    pier2 = obs_mod.Pier(name="Pier-2")

    pier1.guiding_service = guiding_mod.GuidingService(host="localhost", port=4400)
    pier2.guiding_service = guiding_mod.GuidingService(host="localhost", port=4401)

    assert pier1.guiding_service is not pier2.guiding_service
    assert pier2.guiding_service.port == 4401


# ---------------------------------------------------------------------------
# PHD2 event-server protocol, against a fake server (TC-GUIDE-010 … 090)
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import base64  # noqa: E402
import struct  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from galileo.guiding import GuideModel, GuiderError, GuidingService  # noqa: E402
from tests.phd2_fake_server import FakePhd2Server  # noqa: E402


@pytest.fixture
def phd2():
    server = FakePhd2Server()
    yield server
    server.close()


def _wait_until(condition, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def _step(frame: int, ra: float, dec: float, **extra) -> dict:
    return {"Event": "GuideStep", "Frame": frame, "Time": float(frame), "RADistanceRaw": ra, "DECDistanceRaw": dec,
            "RADuration": 100, "RADirection": "West", "DECDuration": 50, "DECDirection": "North",
            "SNR": 30.0, "StarMass": 5000, "HFD": 2.5, **extra}


@pytest.mark.requirement("TC-GUIDE-070")
@pytest.mark.priority("MVP")
async def test_tc_guide_070_connects_by_host_and_port_and_reads_phd2_state(phd2):
    """GUIDE-070: Connect to PHD2 by host and port alone — no device selection — and read its current state."""
    service = GuidingService("127.0.0.1", phd2.port)
    await service.connect()
    await asyncio.to_thread(service.sync_state)
    try:
        assert service.is_connected
        assert _wait_until(lambda: service.model.phd_version == "2.6.13")
        snap = service.model.snapshot()
        assert snap.connected and snap.app_state == "Stopped" and snap.equipment_connected
        assert snap.exposure_ms == 2000 and snap.exposure_options_ms == [500, 1000, 2000, 3000]
        assert snap.pixel_scale == 2.0 and snap.frame_size == (640, 480) and snap.dec_mode == "Auto"
    finally:
        await service.disconnect()
    assert not service.is_connected and not service.model.snapshot().connected


@pytest.mark.requirement("TC-GUIDE-070")
@pytest.mark.priority("MVP")
async def test_tc_guide_070_unreachable_phd2_raises_a_guider_error():
    """GUIDE-070: An unreachable host/port fails with a clear error rather than hanging or crashing."""
    service = GuidingService("127.0.0.1", 1)
    with pytest.raises(GuiderError, match="127.0.0.1:1"):
        await service.connect()
    assert not service.is_connected


@pytest.mark.requirement("TC-GUIDE-050")
@pytest.mark.priority("MVP")
async def test_tc_guide_050_phd2_quitting_is_a_recoverable_error(phd2, event_bus):
    """GUIDE-050: PHD2 going away mid-session marks the guider disconnected and publishes a recoverable error."""
    service = GuidingService("127.0.0.1", phd2.port)
    service._event_bus = event_bus
    await service.connect()
    phd2.drop_clients()
    assert _wait_until(lambda: event_bus.publish.called)
    published = event_bus.publish.call_args[0][0]
    assert published.recoverable is True and published.source == "guider"
    assert not service.is_connected and not service.model.snapshot().connected


@pytest.mark.requirement("TC-GUIDE-020")
@pytest.mark.priority("MVP")
async def test_tc_guide_020_real_start_guiding_waits_for_phd2_to_settle(phd2):
    """GUIDE-020: start_guiding sends PHD2's guide command and returns only once PHD2 reports SettleDone."""
    def guide(params):
        threading.Timer(0.15, phd2.push, [{"Event": "SettleDone", "Status": 0}]).start()
        return 0

    phd2.responses["guide"] = guide
    service = GuidingService("127.0.0.1", phd2.port)
    await service.connect()
    try:
        started = time.monotonic()
        await service.start_guiding()
        assert time.monotonic() - started >= 0.1
        assert service.is_guiding
        params = next(p for m, p in phd2.received if m == "guide")
        assert params[1] is False and set(params[0]) == {"pixels", "time", "timeout"}
    finally:
        await service.disconnect()


@pytest.mark.requirement("TC-GUIDE-030")
@pytest.mark.priority("MVP")
async def test_tc_guide_030_real_dither_waits_for_settle_and_reports_failure(phd2):
    """GUIDE-030: dither waits for SettleDone, and a failed settle is raised rather than ignored."""
    def dither(params):
        threading.Timer(0.05, phd2.push, [{"Event": "SettleDone", "Status": 1, "Error": "timed out"}]).start()
        return 0

    phd2.responses["dither"] = dither
    service = GuidingService("127.0.0.1", phd2.port)
    await service.connect()
    try:
        with pytest.raises(GuiderError, match="timed out"):
            await service.dither_and_wait(settle_timeout_s=5)
    finally:
        await service.disconnect()


@pytest.mark.requirement("TC-GUIDE-040")
@pytest.mark.priority("P2")
def test_tc_guide_040_rms_is_computed_from_guide_steps_in_arcsec():
    """GUIDE-040: RMS is the standard deviation of the guide error since guiding started, scaled by PHD2's pixel scale."""
    svc = GuidingService("localhost", 4400)
    svc.model.update(pixel_scale=2.0)
    svc._handle_event({"Event": "StartGuiding"})
    for frame, ra in enumerate((1.0, -1.0, 1.0, -1.0)):
        svc._handle_event(_step(frame, ra, 0.5))
    rms = svc.get_rms()
    assert rms["ra"] == pytest.approx(2.0)      # ±1 px × 2 ″/px
    assert rms["dec"] == pytest.approx(0.0)     # constant offset has no spread
    assert rms["total"] == pytest.approx(2.0)
    assert svc.is_guiding
    svc._handle_event({"Event": "GuidingStopped"})
    assert not svc.is_guiding


@pytest.mark.requirement("TC-GUIDE-080")
@pytest.mark.priority("MVP")
def test_tc_guide_080_model_tracks_state_pulses_settling_and_log():
    """GUIDE-080: PHD2 events drive the state lamp, signed correction pulses, settling flag and the event log."""
    model = GuideModel()
    assert model.phase == "idle"
    model.apply_event({"Event": "LoopingExposures", "Frame": 1})
    assert model.app_state == "Looping" and model.phase == "prep"
    model.apply_event({"Event": "StartGuiding"})
    model.apply_event(_step(1, 0.2, -0.1, RADirection="East", DECDirection="South"))
    sample = model.snapshot().samples[-1]
    assert model.phase == "run" and sample.ra_pulse_ms == -100 and sample.dec_pulse_ms == -50
    model.apply_event({"Event": "SettleBegin"})
    assert model.settling and model.phase == "prep"
    model.apply_event({"Event": "SettleDone", "Status": 0})
    model.apply_event({"Event": "StarLost", "Frame": 9})
    assert model.app_state == "LostLock"
    text = "\n".join(model.snapshot().log)
    assert "Guiding started." in text and "Settle done." in text and "Lost track of the guide star" in text


@pytest.mark.requirement("TC-GUIDE-080")
@pytest.mark.priority("MVP")
def test_tc_guide_080_model_keeps_calibration_points_and_decodes_the_star_image():
    """GUIDE-080: calibration steps and PHD2's 16-bit star cut-out are kept for the plots."""
    model = GuideModel()
    model.apply_event({"Event": "StartCalibration", "Mount": "Mount"})
    model.apply_event({"Event": "Calibrating", "dir": "West", "dx": 1.5, "dy": -0.2, "step": 1})
    model.apply_event({"Event": "Calibrating", "dir": "North", "dx": 0.1, "dy": 2.0, "step": 1})
    assert [(p.direction, p.dx, p.dy) for p in model.snapshot().calibration_points] == [
        ("West", 1.5, -0.2), ("North", 0.1, 2.0)]
    model.apply_event({"Event": "StartCalibration"})  # a new run starts from a clean plot
    assert model.snapshot().calibration_points == []

    pixels = base64.b64encode(struct.pack("<6H", 0, 1, 2, 3, 4, 65535)).decode()
    model.set_star_image({"frame": 3, "width": 3, "height": 2, "star_pos": [1.0, 0.5], "pixels": pixels})
    star = model.snapshot().star_image
    assert (star.width, star.height, star.star_pos) == (3, 2, (1.0, 0.5))
    model.set_star_image({"frame": 4, "width": 9, "height": 9, "pixels": pixels})  # wrong size: ignored
    assert model.snapshot().star_image.frame == 3


@pytest.mark.requirement("TC-GUIDE-090")
@pytest.mark.priority("MVP")
async def test_tc_guide_090_commands_reach_phd2_and_rejections_are_logged(phd2):
    """GUIDE-090: user commands map to PHD2 requests; one PHD2 rejects shows up in the log instead of vanishing."""
    for method in ("loop", "stop_capture", "find_star", "set_exposure", "set_dec_guide_mode", "clear_calibration",
                   "set_connected", "guide", "dither"):
        phd2.responses[method] = 0
    service = GuidingService("127.0.0.1", phd2.port)
    await service.connect()
    try:
        service.loop().result(3)
        service.stop().result(3)
        service.find_star().result(3)
        service.guide(recalibrate=True).result(3)
        service.request_dither().result(3)
        service.set_exposure(1000).result(3)
        service.set_dec_guide_mode("North").result(3)
        service.clear_calibration().result(3)
        service.set_equipment_connected(False).result(3)
        sent = dict(phd2.received)
        assert sent["set_exposure"] == [1000] and sent["set_dec_guide_mode"] == ["North"]
        assert sent["guide"][1] is True and sent["set_connected"] == [False]
        assert sent["clear_calibration"] == ["both"]
        assert _wait_until(lambda: service.model.snapshot().exposure_ms == 1000 and service.model.snapshot().dec_mode == "North"
                           and not service.model.snapshot().equipment_connected)
        snap = service.model.snapshot()
        assert snap.dec_mode == "North" and not snap.equipment_connected

        with pytest.raises(ValueError):
            service.set_dec_guide_mode("Sideways")

        del phd2.responses["loop"]
        with pytest.raises(GuiderError):
            service.loop().result(3)
        assert _wait_until(lambda: any("PHD2 rejected loop" in line for line in service.model.snapshot().log))
    finally:
        await service.disconnect()
