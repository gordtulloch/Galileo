# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""EQP — Equipment Control (TC-EQP-010 … TC-EQP-SAFE-010)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, call


# ---------------------------------------------------------------------------
# TC-EQP-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_010_connect_disconnect_status_per_category(mock_indi_camera):
    """EQP-010: Provide connect, disconnect, and live connection-status for every device category."""
    devices = pytest.importorskip("galileo.core.devices")
    ctrl = devices.DeviceController(mock_indi_camera)

    assert ctrl.is_connected is True
    await ctrl.disconnect()
    mock_indi_camera.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# TC-EQP-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-020")
@pytest.mark.priority("MVP")
def test_tc_eqp_020_display_and_configure_device_settings(mock_indi_camera):
    """EQP-020: Display and allow configuration of device-specific settings exposed by the backend."""
    devices = pytest.importorskip("galileo.core.devices")
    ctrl = devices.DeviceController(mock_indi_camera)
    props = ctrl.get_properties()
    assert isinstance(props, dict), "get_properties() must return a dict"

    ctrl.set_property("GAIN", 200)
    mock_indi_camera.set_property.assert_called_with("GAIN", 200)


# ---------------------------------------------------------------------------
# TC-EQP-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-030")
@pytest.mark.priority("MVP")
async def test_tc_eqp_030_log_connect_disconnect_errors(mock_indi_camera, event_bus):
    """EQP-030: Log all device connect/disconnect/error events with timestamps to the diagnostics log."""
    devices = pytest.importorskip("galileo.core.devices")
    ctrl = devices.DeviceController(mock_indi_camera, event_bus=event_bus)

    mock_indi_camera.connect = AsyncMock(side_effect=ConnectionError("refused"))
    with pytest.raises(ConnectionError):
        await ctrl.connect()

    # An error event must have been published
    assert event_bus.publish.called
    published_event = event_bus.publish.call_args[0][0]
    assert hasattr(published_event, "timestamp")
    assert "error" in str(type(published_event)).lower() or "device" in str(type(published_event)).lower()


# ---------------------------------------------------------------------------
# TC-EQP-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-040")
@pytest.mark.priority("MVP")
async def test_tc_eqp_040_select_from_reachable_devices():
    """EQP-040: Select a device from all reachable INDI/Alpaca devices in its category, with refresh."""
    devices = pytest.importorskip("galileo.core.devices")
    indi = pytest.importorskip("galileo.adapters.indi")

    adapter = indi.IndiAdapter(host="localhost", port=7624)
    adapter._list_devices = AsyncMock(return_value=["CCD Simulator", "Guide Simulator"])

    available = await adapter.list_available_devices(devices.DeviceCategory.CAMERA)
    assert "CCD Simulator" in available

    # Re-calling (refresh) returns updated list
    adapter._list_devices.return_value = ["CCD Simulator", "ZWO ASI294"]
    available2 = await adapter.list_available_devices(devices.DeviceCategory.CAMERA)
    assert "ZWO ASI294" in available2


# ---------------------------------------------------------------------------
# TC-EQP-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-050")
@pytest.mark.priority("MVP")
async def test_tc_eqp_050_error_state_distinct_from_disconnect(event_bus):
    """EQP-050: Surface a device-reported error/alert state distinctly from a normal disconnect."""
    devices = pytest.importorskip("galileo.core.devices")

    error_device = MagicMock()
    error_device.is_connected = True
    error_device.device_type = "Camera"
    error_device.name = "ErrCam"
    error_device.has_error = True
    error_device.error_message = "Sensor overheated"

    ctrl = devices.DeviceController(error_device, event_bus=event_bus)
    state = ctrl.connection_state()

    assert state != devices.ConnectionState.DISCONNECTED
    assert state == devices.ConnectionState.ERROR or hasattr(ctrl, "error_message")


# ---------------------------------------------------------------------------
# TC-EQP-050 (Alpaca transport)
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-050")
@pytest.mark.priority("MVP")
async def test_tc_eqp_050_alpaca_error_envelope_raises():
    """EQP-050: A driver-reported Alpaca error (nonzero ErrorNumber) is surfaced as a DeviceError, not silently discarded."""
    alpaca = pytest.importorskip("galileo.adapters.alpaca")
    exceptions = pytest.importorskip("galileo.exceptions")

    backend = alpaca.AlpacaFocuserAdapter(host="seestar.local", port=32323)

    with pytest.raises(exceptions.DevicePropertyError, match="out of range"):
        backend._raise_on_alpaca_error(
            {"ErrorNumber": 0x401, "ErrorMessage": "Position out of range"}, "move"
        )
    assert issubclass(exceptions.DevicePropertyError, exceptions.DeviceError)

    # No error present -> no exception
    backend._raise_on_alpaca_error({"ErrorNumber": 0, "ErrorMessage": ""}, "move")


# ---------------------------------------------------------------------------
# TC-EQP-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-060")
@pytest.mark.priority("P2")
def test_tc_eqp_060_advanced_property_inspector(mock_indi_camera):
    """EQP-060: Advanced device-property inspector exposing raw INDI properties or Alpaca parameters."""
    devices = pytest.importorskip("galileo.core.devices")
    inspector = devices.DevicePropertyInspector(mock_indi_camera)
    raw = inspector.get_all_raw_properties()
    assert isinstance(raw, dict)


# ---------------------------------------------------------------------------
# TC-EQP-CAM-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-CAM-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_010_exposure_params(mock_indi_camera):
    """EQP-CAM-010: Control exposure start/abort, exposure time, gain/offset, binning, frame type."""
    devices = pytest.importorskip("galileo.core.devices")
    cam = devices.CameraController(mock_indi_camera)

    await cam.start_exposure(duration=300.0, gain=100, offset=0, binning=1, frame_type="Light")
    mock_indi_camera.start_exposure.assert_called_once_with(
        duration=300.0, gain=100, offset=0, binning=1, frame_type="Light"
    )

    await cam.abort_exposure()
    mock_indi_camera.abort_exposure.assert_called_once()


# ---------------------------------------------------------------------------
# TC-EQP-CAM-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-CAM-020")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_020_cooler_control(mock_indi_camera):
    """EQP-CAM-020: Cooled cameras: set target temperature, monitor current temp, issue warm-up."""
    devices = pytest.importorskip("galileo.core.devices")
    cam = devices.CameraController(mock_indi_camera)

    await cam.set_target_temperature(-10.0)
    mock_indi_camera.set_temperature.assert_called_with(-10.0)

    temp = cam.get_temperature()
    assert temp == -10.0

    await cam.warm_up()
    mock_indi_camera.warm_up.assert_called_once()


# ---------------------------------------------------------------------------
# TC-EQP-CAM-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-CAM-030")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_030_frame_retrieval_to_imaging_tab(mock_indi_camera):
    """EQP-CAM-030: Retrieve captured frame data and render in the imaging tab."""
    import numpy as np
    devices = pytest.importorskip("galileo.core.devices")
    cam = devices.CameraController(mock_indi_camera)

    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.uint16))
    frame = await cam.get_image_array()
    assert frame is not None
    assert frame.shape == (100, 100)


# ---------------------------------------------------------------------------
# TC-EQP-CAM-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-CAM-040")
@pytest.mark.priority("MVP")
def test_tc_eqp_cam_040_simulator_backend():
    """EQP-CAM-040: Support a simulator camera backend for development and testing without hardware."""
    indi = pytest.importorskip("galileo.adapters.indi")
    sim = indi.IndiCameraSimulator()
    assert sim.is_simulator is True
    assert sim.device_type == "Camera"


# ---------------------------------------------------------------------------
# TC-EQP-MNT-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-MNT-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_mnt_010_slew_track_park(mock_indi_mount):
    """EQP-MNT-010: Control mount slew-to-coordinates, slew-abort, tracking on/off, tracking rate, park/unpark."""
    devices = pytest.importorskip("galileo.core.devices")
    mnt = devices.MountController(mock_indi_mount)

    await mnt.slew_to_coordinates(ra=83.8221, dec=-5.3911)
    mock_indi_mount.slew_to_coordinates.assert_called_with(ra=83.8221, dec=-5.3911)

    await mnt.abort_slew()
    mock_indi_mount.abort_slew.assert_called_once()

    await mnt.set_tracking(enabled=True)
    mock_indi_mount.set_tracking.assert_called_with(enabled=True)

    await mnt.park()
    mock_indi_mount.park.assert_called_once()

    await mnt.unpark()
    mock_indi_mount.unpark.assert_called_once()


# ---------------------------------------------------------------------------
# TC-EQP-MNT-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-MNT-020")
@pytest.mark.priority("MVP")
def test_tc_eqp_mnt_020_position_display(mock_indi_mount):
    """EQP-MNT-020: Display RA/Dec, Alt/Az, pier side, and tracking state refreshed on a polling interval."""
    devices = pytest.importorskip("galileo.core.devices")
    mnt = devices.MountController(mock_indi_mount)
    status = mnt.get_status()

    assert "ra" in status
    assert "dec" in status
    assert "altitude" in status
    assert "azimuth" in status
    assert "pier_side" in status
    assert "is_tracking" in status


# ---------------------------------------------------------------------------
# TC-EQP-MNT-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-MNT-030")
@pytest.mark.priority("MVP")
async def test_tc_eqp_mnt_030_sync_to_coordinates(mock_indi_mount):
    """EQP-MNT-030: Support mount sync-to-coordinates as issued by the plate-solving workflow."""
    devices = pytest.importorskip("galileo.core.devices")
    mnt = devices.MountController(mock_indi_mount)

    await mnt.sync_to_coordinates(ra=83.8221, dec=-5.3911)
    mock_indi_mount.sync_to_coordinates.assert_called_with(ra=83.8221, dec=-5.3911)


# ---------------------------------------------------------------------------
# TC-EQP-MNT-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-MNT-040")
@pytest.mark.priority("P2")
async def test_tc_eqp_mnt_040_non_sidereal_tracking(mock_indi_mount):
    """EQP-MNT-040: Slew to and track a non-sidereal target at a custom rate where the backend supports it."""
    devices = pytest.importorskip("galileo.core.devices")
    mock_indi_mount.capabilities = MagicMock(can_track_non_sidereal=True)
    mnt = devices.MountController(mock_indi_mount)

    await mnt.set_tracking_rate(ra_rate_arcsec_s=0.5, dec_rate_arcsec_s=-0.1)
    mock_indi_mount.set_tracking_rate.assert_called_once()


# ---------------------------------------------------------------------------
# TC-EQP-FW-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-FW-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_fw_010_filter_enumeration_and_change(mock_filter_wheel):
    """EQP-FW-010: Enumerate filter names/slots and issue filter-change commands with in-progress status."""
    devices = pytest.importorskip("galileo.core.devices")
    fw = devices.FilterWheelController(mock_filter_wheel)

    filters = fw.get_filter_names()
    assert "Ha" in filters
    assert len(filters) == 7

    await fw.move_to_filter("OIII")
    expected_idx = mock_filter_wheel.filter_names.index("OIII")
    mock_filter_wheel.move_to.assert_called_with(expected_idx)


# ---------------------------------------------------------------------------
# TC-EQP-FW-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-FW-020")
@pytest.mark.priority("MVP")
def test_tc_eqp_fw_020_per_filter_focus_offset(mock_filter_wheel):
    """EQP-FW-020: Per-filter focus-offset configuration for autofocus and filter-change workflows."""
    devices = pytest.importorskip("galileo.core.devices")
    fw = devices.FilterWheelController(mock_filter_wheel)

    fw.set_focus_offset("OIII", -50)
    assert fw.get_focus_offset("OIII") == -50
    assert fw.get_focus_offset("Ha") == 0  # default


# ---------------------------------------------------------------------------
# TC-EQP-FOC-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-FOC-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_foc_010_absolute_relative_moves(mock_focuser):
    """EQP-FOC-010: Issue absolute and relative focuser moves; display current position and temperature."""
    devices = pytest.importorskip("galileo.core.devices")
    foc = devices.FocuserController(mock_focuser)

    await foc.move_to(6000)
    mock_focuser.move_to.assert_called_with(6000)

    await foc.move_by(-100)
    mock_focuser.move_by.assert_called_with(-100)

    assert foc.get_temperature() == 15.0
    assert foc.get_position() == 5000


# ---------------------------------------------------------------------------
# TC-EQP-FOC-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-FOC-020")
@pytest.mark.priority("P2")
async def test_tc_eqp_foc_020_backlash_compensation(mock_focuser):
    """EQP-FOC-020: Configurable focuser backlash compensation applied to move commands."""
    devices = pytest.importorskip("galileo.core.devices")
    foc = devices.FocuserController(mock_focuser, backlash_steps=50)

    # Moving inward: backlash overshoot then return expected
    await foc.move_to(4900)
    calls = mock_focuser.move_to.call_args_list
    # Last call must settle at 4900
    assert calls[-1] == call(4900)
    # Overshoot must have occurred in an earlier call
    assert len(calls) >= 2


# ---------------------------------------------------------------------------
# TC-EQP-FOC-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-FOC-030")
@pytest.mark.priority("MVP")
async def test_tc_eqp_foc_030_clamp_to_valid_travel_range(mock_focuser):
    """EQP-FOC-030: Clamp absolute/relative focuser moves to the device's valid travel range (0..MaxStep)."""
    devices = pytest.importorskip("galileo.core.devices")
    mock_focuser.max_step = 8000
    foc = devices.FocuserController(mock_focuser)

    # Absolute move beyond MaxStep is clamped, not passed through unchecked
    await foc.move_to(9000)
    mock_focuser.move_to.assert_called_with(8000)

    # Absolute move below zero is clamped to zero
    await foc.move_to(-500)
    mock_focuser.move_to.assert_called_with(0)

    # Relative move that would exceed MaxStep is clamped to land exactly on it
    mock_focuser.position = 7900
    await foc.move_by(500)
    mock_focuser.move_by.assert_called_with(100)


@pytest.mark.requirement("TC-EQP-FOC-030")
@pytest.mark.priority("MVP")
async def test_tc_eqp_foc_030_alpaca_maxstep_feeds_the_clamp():
    """EQP-FOC-030: AlpacaFocuserAdapter reads MaxStep from the live device on connect, and FocuserController clamps against that value (not a hardcoded simulator constant)."""
    devices = pytest.importorskip("galileo.core.devices")
    alpaca = pytest.importorskip("galileo.adapters.alpaca")

    backend = alpaca.AlpacaFocuserAdapter(host="seestar.local", port=32323)
    live_values = {
        "absolute": True, "maxstep": 5000, "maxincrement": 5000,
        "position": 2500, "temperature": 12.0, "ismoving": False,
    }
    backend._get = AsyncMock(side_effect=lambda attribute: live_values[attribute])
    backend._put = AsyncMock()

    await backend.connect()
    assert backend.max_step == 5000

    foc = devices.FocuserController(backend)
    await foc.move_to(9999)
    backend._put.assert_any_call("move", Position=5000)


# ---------------------------------------------------------------------------
# TC-EQP-ROT-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-ROT-010")
@pytest.mark.priority("P2")
async def test_tc_eqp_rot_010_rotator_move_and_position(mock_rotator):
    """EQP-ROT-010: Issue rotator move-to-angle commands and display current mechanical/sky position angle."""
    devices = pytest.importorskip("galileo.core.devices")
    rot = devices.RotatorController(mock_rotator)

    await rot.move_to_angle(90.0)
    mock_rotator.move_to_angle.assert_called_with(90.0)

    status = rot.get_status()
    assert "mechanical_angle" in status
    assert "sky_angle" in status


# ---------------------------------------------------------------------------
# TC-EQP-GDR-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-GDR-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_gdr_010_guider_controls(mock_guider):
    """EQP-GDR-010: Expose guider connect/start/stop/dither controls via the external guiding interface."""
    devices = pytest.importorskip("galileo.core.devices")
    guiding = pytest.importorskip("galileo.guiding")
    ctrl = devices.GuiderController(guiding_service=guiding.GuidingService.__new__(guiding.GuidingService))
    ctrl._service = mock_guider

    await ctrl.start_guiding()
    mock_guider.start_guiding.assert_called_once()

    await ctrl.dither()
    mock_guider.dither.assert_called_once()

    await ctrl.stop_guiding()
    mock_guider.stop_guiding.assert_called_once()


# ---------------------------------------------------------------------------
# TC-EQP-SW-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-SW-010")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_010_switch_enumeration_and_control(mock_switch_device):
    """EQP-SW-010: Enumerate switch/relay devices and their state; support boolean and analog switches."""
    devices = pytest.importorskip("galileo.core.devices")
    sw = devices.SwitchController(mock_switch_device)

    switches = sw.list_switches()
    assert len(switches) == 3
    booleans = [s for s in switches if not s.is_analog]
    analogs = [s for s in switches if s.is_analog]
    assert len(booleans) >= 1
    assert len(analogs) >= 1

    await sw.set_switch("Power-Cam", True)
    mock_switch_device.set_switch.assert_called_with("Power-Cam", True)


# ---------------------------------------------------------------------------
# TC-EQP-FP-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-FP-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_fp_010_flat_panel_cover_and_brightness(mock_flat_panel):
    """EQP-FP-010: Control flat-panel cover open/close and brightness level."""
    devices = pytest.importorskip("galileo.core.devices")
    fp = devices.FlatPanelController(mock_flat_panel)

    await fp.open_cover()
    mock_flat_panel.open_cover.assert_called_once()

    await fp.set_brightness(128)
    mock_flat_panel.set_brightness.assert_called_with(128)

    await fp.close_cover()
    mock_flat_panel.close_cover.assert_called_once()


# ---------------------------------------------------------------------------
# TC-EQP-WX-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-WX-010")
@pytest.mark.priority("P2")
async def test_tc_eqp_wx_010_weather_polling_and_display(mock_weather_station):
    """EQP-WX-010: Poll and display weather readings at a configurable interval."""
    devices = pytest.importorskip("galileo.core.devices")
    wx = devices.WeatherController(mock_weather_station, poll_interval_s=60)

    await wx.poll()
    mock_weather_station.poll.assert_called_once()

    readings = wx.get_readings()
    assert "cloud_cover" in readings
    assert "wind_speed" in readings
    assert "humidity" in readings
    assert "temperature" in readings
    assert "rain_rate" in readings


# ---------------------------------------------------------------------------
# TC-EQP-DOME-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-DOME-010")
@pytest.mark.priority("P2")
async def test_tc_eqp_dome_010_slew_shutter_park(mock_dome):
    """EQP-DOME-010: Slew dome to azimuth, open/close shutter, park, and display azimuth/shutter state."""
    devices = pytest.importorskip("galileo.core.devices")
    dome = devices.DomeController(mock_dome)

    await dome.slew_to_azimuth(90.0)
    mock_dome.slew_to_azimuth.assert_called_with(90.0)

    await dome.open_shutter()
    mock_dome.open_shutter.assert_called_once()

    await dome.park()
    mock_dome.park.assert_called_once()

    status = dome.get_status()
    assert "azimuth" in status
    assert "shutter_state" in status


# ---------------------------------------------------------------------------
# TC-EQP-SAFE-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-SAFE-010")
@pytest.mark.priority("P2")
async def test_tc_eqp_safe_010_safety_monitor_polling(mock_safety_monitor, event_bus):
    """EQP-SAFE-010: Poll safety-monitor device SAFE/NOT-SAFE state with explanation string at configurable interval."""
    devices = pytest.importorskip("galileo.core.devices")
    safe_ctrl = devices.SafetyMonitorController(mock_safety_monitor, event_bus=event_bus)

    await safe_ctrl.poll()
    mock_safety_monitor.poll.assert_called_once()
    assert safe_ctrl.is_safe is True
    assert safe_ctrl.explanation == "All sensors nominal"

    # Transition to unsafe triggers event
    mock_safety_monitor.is_safe = False
    mock_safety_monitor.explanation = "Rain detected"
    await safe_ctrl.poll()
    assert event_bus.publish.called


# ---------------------------------------------------------------------------
# Alpaca camera: the image is only fetched once the exposure has finished
# ---------------------------------------------------------------------------

def _alpaca_camera(monkeypatch, replies):
    """An Alpaca camera whose GETs are scripted: ``replies[attribute]`` is a list, consumed in order (last one repeats)."""
    from galileo.adapters.alpaca import AlpacaCameraAdapter
    adapter = AlpacaCameraAdapter(host="h", port=1)
    adapter.reads = []
    adapter._IMAGE_POLL_S = 0.0

    async def fake_get(attribute, timeout=10.0):
        adapter.reads.append(attribute)
        queue = replies[attribute]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    async def fake_put(attribute, **body):
        adapter.reads.append(attribute)

    monkeypatch.setattr(adapter, "_get", fake_get)
    monkeypatch.setattr(adapter, "_put", fake_put)
    return adapter


@pytest.mark.requirement("TC-EQP-CAM-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_010_alpaca_waits_for_the_exposure_before_downloading(monkeypatch):
    """EQP-CAM-010: an Alpaca exposure is polled until ImageReady, then the image is returned as a (height, width) array."""
    import numpy as np
    columns = [[1, 2, 3], [4, 5, 6]]                    # ASCOM order: X first — 2 wide, 3 high
    cam = _alpaca_camera(monkeypatch, {"imageready": [False, False, True], "camerastate": [2],
                                       "imagearray": [columns]})
    await cam.start_exposure(duration=10.0)
    image = await cam.get_image_array()
    assert cam.reads.index("imagearray") > max(i for i, r in enumerate(cam.reads) if r == "imageready")
    assert cam.reads.count("imageready") == 3
    assert isinstance(image, np.ndarray) and image.shape == (3, 2) and image[2, 1] == 6


@pytest.mark.requirement("TC-EQP-CAM-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_010_alpaca_exposure_failure_is_reported(monkeypatch):
    """EQP-CAM-010: a camera error state, or an exposure that never completes, raises instead of hanging or returning nothing."""
    from galileo.exceptions import DeviceError
    cam = _alpaca_camera(monkeypatch, {"imageready": [False], "camerastate": [5], "imagearray": [None]})
    with pytest.raises(DeviceError, match="error during the exposure"):
        await cam.get_image_array()

    cam = _alpaca_camera(monkeypatch, {"imageready": [False], "camerastate": [2], "imagearray": [None]})
    cam._IMAGE_MARGIN_S = -1.0                          # deadline already passed
    with pytest.raises(DeviceError, match="did not finish"):
        await cam.get_image_array()


# ---------------------------------------------------------------------------
# EQP-MNT-050 — tracking resumes at the target's own rate when a slew finishes
# ---------------------------------------------------------------------------

class _TrackingMount:
    """A mount that reports itself slewing for a few polls, then arrived."""

    def __init__(self, slewing_polls=2, can_select_rate=True, fail_rate=False):
        self.calls: list = []
        self.polls = 0
        self._slewing_polls = slewing_polls
        self._fail_rate = fail_rate
        if not can_select_rate:
            self.set_tracking_rate_mode = None

    async def get_status(self):
        self.polls += 1
        return {"slewing": self.polls <= self._slewing_polls}

    async def set_tracking_rate_mode(self, mode):
        if self._fail_rate:
            raise RuntimeError("this mount will not change rate")
        self.calls.append(("rate", mode))

    async def set_tracking(self, enabled):
        self.calls.append(("tracking", enabled))


@pytest.mark.requirement("TC-EQP-MNT-050")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("target, expected", [
    ("Moon", "Lunar"),
    ("moon", "Lunar"),
    ("Sun", "Solar"),
    ("  SUN  ", "Solar"),
    ("Vega", "Sidereal"),
    ("M 31", "Sidereal"),
    ("Jupiter", "Sidereal"),
    (None, "Sidereal"),
    ("", "Sidereal"),
])
def test_tc_eqp_mnt_050_rate_follows_the_target(target, expected):
    """EQP-MNT-050: the Sun and Moon get their own rates; everything else, and nothing at all, tracks sidereal."""
    from galileo.tracking import tracking_rate_for
    assert tracking_rate_for(target) == expected


@pytest.mark.requirement("TC-EQP-MNT-050")
@pytest.mark.priority("MVP")
def test_tc_eqp_mnt_050_the_target_can_be_an_object_or_a_dict():
    """EQP-MNT-050: the rate can be worked out from a current object or a Star Atlas selection, not just a name."""
    from galileo.current_object import CurrentObject
    from galileo.tracking import tracking_rate_for
    assert tracking_rate_for(CurrentObject("Moon", 0.0, 0.0, kind="Moon")) == "Lunar"
    assert tracking_rate_for({"kind": "body", "name": "Sun", "ra_deg": 0.0, "dec_deg": 0.0}) == "Solar"
    assert tracking_rate_for(CurrentObject("M 42", 83.8, -5.4, kind="Nebula")) == "Sidereal"


@pytest.mark.requirement("TC-EQP-MNT-050")
@pytest.mark.priority("MVP")
async def test_tc_eqp_mnt_050_tracking_starts_only_once_the_slew_has_finished():
    """EQP-MNT-050: the mount is left alone until it reports it has stopped slewing, then tracking is turned on."""
    from galileo.tracking import resume_tracking
    mount = _TrackingMount(slewing_polls=3)

    rate = await resume_tracking(mount, "Vega")

    assert mount.polls > 3, "it waited for the slew"
    assert rate == "Sidereal"
    # The rate is chosen before tracking is switched on, so it never tracks at the wrong one.
    assert mount.calls == [("rate", "Sidereal"), ("tracking", True)]


@pytest.mark.requirement("TC-EQP-MNT-050")
@pytest.mark.priority("MVP")
async def test_tc_eqp_mnt_050_the_moon_and_sun_get_their_own_rates_after_a_slew():
    """EQP-MNT-050: slewing to the Moon leaves the mount tracking lunar, and to the Sun, solar."""
    from galileo.tracking import resume_tracking
    for target, expected in (("Moon", "Lunar"), ("Sun", "Solar")):
        mount = _TrackingMount(slewing_polls=1)
        assert await resume_tracking(mount, target) == expected
        assert mount.calls == [("rate", expected), ("tracking", True)]


@pytest.mark.requirement("TC-EQP-MNT-050")
@pytest.mark.priority("MVP")
async def test_tc_eqp_mnt_050_a_mount_that_never_settles_is_left_alone():
    """EQP-MNT-050: a slew that never ends does not get tracking commands piled on top of it."""
    from galileo.tracking import resume_tracking
    mount = _TrackingMount(slewing_polls=10_000)

    assert await resume_tracking(mount, "Vega", timeout_s=0.3) is None
    assert mount.calls == [], "nothing was sent to a mount that is still moving"


@pytest.mark.requirement("TC-EQP-MNT-050")
@pytest.mark.priority("MVP")
async def test_tc_eqp_mnt_050_a_mount_that_cannot_select_a_rate_still_tracks():
    """EQP-MNT-050: a mount with no rate selection, or one that refuses, is still left tracking — sidereal is what it does anyway."""
    from galileo.tracking import resume_tracking
    without = _TrackingMount(slewing_polls=1, can_select_rate=False)
    assert await resume_tracking(without, "Moon") == "Lunar"
    assert without.calls == [("tracking", True)]

    refuses = _TrackingMount(slewing_polls=1, fail_rate=True)
    assert await resume_tracking(refuses, "Moon") == "Lunar"
    assert refuses.calls == [("tracking", True)]


@pytest.mark.requirement("TC-EQP-MNT-050")
@pytest.mark.priority("MVP")
async def test_tc_eqp_mnt_050_a_mount_that_does_not_report_slewing_is_not_waited_on_forever():
    """EQP-MNT-050: a mount that can't say whether it is slewing is taken as arrived rather than never tracked."""
    from galileo.tracking import resume_tracking

    class _Quiet(_TrackingMount):
        async def get_status(self):
            self.polls += 1
            return {}           # no 'slewing' key at all

    mount = _Quiet()
    assert await resume_tracking(mount, "Vega") == "Sidereal"
    assert mount.calls == [("rate", "Sidereal"), ("tracking", True)]


@pytest.mark.requirement("TC-EQP-MNT-050")
@pytest.mark.priority("MVP")
async def test_tc_eqp_mnt_050_a_slow_starting_mount_is_still_waited_for():
    """EQP-MNT-050: a mount that hasn't begun moving when first asked is not mistaken for one that has arrived."""
    import galileo.tracking as tracking_mod
    from galileo.tracking import resume_tracking

    class _SlowToStart(_TrackingMount):
        async def get_status(self):
            self.polls += 1
            # Not moving yet for the first two polls, then slewing, then arrived.
            return {"slewing": 3 <= self.polls <= 5}

    mount = _SlowToStart()
    assert await resume_tracking(mount, "Vega") == "Sidereal"
    assert mount.polls > 5, "it did not take the initial 'not slewing' as 'already arrived'"
    assert tracking_mod._START_GRACE_S > 0


@pytest.mark.requirement("TC-EQP-MNT-050")
@pytest.mark.priority("MVP")
async def test_tc_eqp_mnt_050_plate_solving_leaves_the_mount_tracking(tmp_path):
    """EQP-MNT-050: a Slew to Target run leaves the mount tracking the object it centred on."""
    from unittest.mock import AsyncMock
    plt = pytest.importorskip("galileo.platesolve")
    import numpy as np
    from unittest.mock import MagicMock

    calls: list = []
    camera = MagicMock()
    camera.start_exposure = AsyncMock()
    camera.get_image_array = AsyncMock(return_value=np.full((40, 60), 100, dtype=np.uint16))
    mount = MagicMock()
    mount.get_status = AsyncMock(return_value={
        "right_ascension": 100.0 / 15.0, "declination": 20.0, "equatorial_system": "J2000", "slewing": False})
    mount.slew_to_coordinates = AsyncMock()
    mount.sync_to_coordinates = AsyncMock()
    mount.set_tracking_rate_mode = AsyncMock(side_effect=lambda mode: calls.append(("rate", mode)))
    mount.set_tracking = AsyncMock(side_effect=lambda enabled: calls.append(("tracking", enabled)))

    solver = plt.PlateSolver(backend="astap", executable="unused")
    solver._run_solver = AsyncMock(return_value=plt.SolveResult(
        success=True, ra_deg=10.0, dec_deg=41.0, rotation_deg=0.0, scale_arcsec_px=3.0))
    workflow = plt.SolveWorkflow(solver, camera=camera, mount=mount, work_dir=tmp_path / "solve")
    workflow.set_target(10.0, 41.0, name="Moon")

    await workflow.capture_and_solve(plt.SolveSettings(action=plt.SolveAction.SLEW_TO_TARGET, settle_s=0.0))

    assert ("rate", "Lunar") in calls and ("tracking", True) in calls


@pytest.fixture
def window(tmp_path):
    """A built AppWindow for the two cases that go through the Star Atlas Goto. Only those tests
    request it, so the rest of this file stays free of Qt."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "tracking.db")
    from galileo.observatory import create_observatory, create_pier
    from galileo.ui.app_window import AppWindow

    win = AppWindow()
    win.app = app
    win._current_pier = create_pier(create_observatory("Tracking Obs"), "Pier A")
    yield win
    win._window.close()
    db.close()


def _wait_for_tracking(window):
    thread = window._tracking_thread
    if thread is not None:
        thread.wait(10000)
        window.app.processEvents()


@pytest.mark.requirement("TC-EQP-MNT-050")
@pytest.mark.priority("MVP")
def test_tc_eqp_mnt_050_star_atlas_goto_leaves_the_mount_tracking(window):
    """EQP-MNT-050: a Goto from the Star Atlas ends with the mount tracking that object at its own rate."""
    mount = _TrackingMount(slewing_polls=1)
    mount.slew_to_coordinates = _async_noop
    mount.sync_to_coordinates = _async_noop
    window._device_pages["mount"]["adapter"] = mount

    moon = {"kind": "body", "name": "Moon", "type": "Moon", "ra_deg": 100.0, "dec_deg": 20.0, "alt": 45.0}
    assert window._mount_to_object("goto", moon) is True
    _wait_for_tracking(window)

    assert mount.calls == [("rate", "Lunar"), ("tracking", True)]


@pytest.mark.requirement("TC-EQP-MNT-050")
@pytest.mark.priority("MVP")
def test_tc_eqp_mnt_050_a_sync_does_not_start_tracking(window):
    """EQP-MNT-050: Sync only tells the mount where it is — nothing moved, so nothing is resumed."""
    mount = _TrackingMount(slewing_polls=0)
    mount.slew_to_coordinates = _async_noop
    mount.sync_to_coordinates = _async_noop
    window._device_pages["mount"]["adapter"] = mount

    vega = {"kind": "star", "name": "Vega", "type": "Star", "ra_deg": 279.2, "dec_deg": 38.8, "alt": 60.0}
    assert window._mount_to_object("sync", vega) is True
    _wait_for_tracking(window)

    assert mount.calls == []
    assert window._tracking_thread is None


async def _async_noop(*args, **kwargs):
    return None
