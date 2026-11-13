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


@pytest.mark.requirement("TC-EQP-020")
@pytest.mark.priority("MVP")
async def test_tc_eqp_020_set_property_from_a_running_loop_is_held_and_completes(mock_indi_camera):
    """EQP-020: from a running event loop the property write is scheduled, kept referenced until it finishes, and actually runs."""
    import asyncio
    devices = pytest.importorskip("galileo.core.devices")
    ctrl = devices.DeviceController(mock_indi_camera)
    ctrl.set_property("GAIN", 200)
    assert len(devices._pending_property_writes) == 1      # strongly referenced while in flight
    await asyncio.gather(*list(devices._pending_property_writes))
    await asyncio.sleep(0)                                  # let the done-callback run
    mock_indi_camera.set_property.assert_awaited_once_with("GAIN", 200)
    assert not devices._pending_property_writes


@pytest.mark.requirement("TC-EQP-020")
@pytest.mark.priority("MVP")
async def test_tc_eqp_020_failed_property_write_is_logged_not_lost(mock_indi_camera, caplog):
    """EQP-020: a property write that fails is logged with its traceback rather than vanishing, and does not raise into the caller."""
    import asyncio
    devices = pytest.importorskip("galileo.core.devices")
    mock_indi_camera.set_property.side_effect = RuntimeError("device refused")
    ctrl = devices.DeviceController(mock_indi_camera)
    with caplog.at_level("ERROR", logger="galileo.core.devices"):
        ctrl.set_property("GAIN", 999)
        await asyncio.gather(*list(devices._pending_property_writes), return_exceptions=True)
        await asyncio.sleep(0)
    assert any("GAIN" in r.getMessage() and r.exc_info for r in caplog.records)


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
# TC-EQP-AUX-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
async def test_tc_eqp_aux_010_generic_property_groups_and_writes(mock_aux_device):
    """EQP-AUX-010: an Aux device's driver-defined properties are exposed as groups, and writes reach the backend."""
    devices = pytest.importorskip("galileo.core.devices")
    aux = devices.AuxController(mock_aux_device)

    groups = await aux.get_property_groups()
    assert len(groups) == 1 and groups[0].name == "Main Control"
    prop = groups[0].properties[0]
    assert prop.kind == "switch" and prop.name == "CAP_PARK"

    await aux.write_property("CAP_PARK", {"PARK": True})
    mock_aux_device.write_property.assert_called_with("CAP_PARK", {"PARK": True})


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
# TC-EQP-WX-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-WX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_wx_020_per_measure_safety_rules():
    """EQP-WX-020: Mark a Weather-Station reading safety-related and configure its unsafe condition."""
    safety = pytest.importorskip("galileo.safety")

    rain_rule = safety.WeatherSafetyRule(parameter="rain", operator=">", threshold=0.0, safety_related=True)
    wind_rule = safety.WeatherSafetyRule(parameter="wind_speed", operator=">=", threshold=20.0, safety_related=True)
    off_rule = safety.WeatherSafetyRule(parameter="humidity", operator=">=", threshold=90.0, safety_related=False)

    # Safe: no rain, wind below threshold.
    status = safety.evaluate_weather_safety(
        {"rain": 0.0, "wind_speed": 10.0, "humidity": 95.0}, [rain_rule, wind_rule, off_rule],
    )
    assert status.is_safe is True
    assert status.violations == []

    # Unsafe: rain detected ("Rain is YES").
    status = safety.evaluate_weather_safety(
        {"rain": 1.0, "wind_speed": 10.0, "humidity": 95.0}, [rain_rule, wind_rule, off_rule],
    )
    assert status.is_safe is False
    assert any("Rain" in v for v in status.violations)

    # Unsafe: wind at/above 20 km/h.
    status = safety.evaluate_weather_safety(
        {"rain": 0.0, "wind_speed": 25.0, "humidity": 95.0}, [rain_rule, wind_rule, off_rule],
    )
    assert status.is_safe is False
    assert any("Wind" in v for v in status.violations)

    # A reading with no value (device not reporting it) is skipped, not an automatic unsafe.
    status = safety.evaluate_weather_safety({"rain": None, "wind_speed": None}, [rain_rule, wind_rule])
    assert status.is_safe is True


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

    await dome.abort_slew()
    mock_dome.abort_slew.assert_called_once()

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
# TC-EQP-SAFE-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-SAFE-020")
@pytest.mark.priority("P2")
def test_tc_eqp_safe_020_weather_derived_measures_surfaced_read_only():
    """EQP-SAFE-020: Weather readings marked safety-related surface, with their verdict, independent of the device's own SAFE/NOT-SAFE state."""
    safety = pytest.importorskip("galileo.safety")

    rules = safety.default_weather_safety_rules()
    safety_related = [r for r in rules if r.safety_related]
    assert safety_related  # the defaults pre-enable at least Rain and Wind Speed (EQP-WX-020)
    assert {r.parameter for r in safety_related} >= {"rain", "wind_speed"}

    # The Weather screen's verdict (EQP-WX-020) and the Safety Monitor
    # screen's per-measure verdict (EQP-SAFE-020) are the same advisory
    # computation — surfacing it separately must not change the answer.
    readings = {"rain": 0.0, "wind_speed": 25.0}
    overall = safety.evaluate_weather_safety(readings, rules)
    wind_rule = next(r for r in safety_related if r.parameter == "wind_speed")
    per_measure = safety.evaluate_weather_safety(readings, [wind_rule])
    assert overall.is_safe is False
    assert per_measure.is_safe is False


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
    from galileo.current_object import pier_key
    thread = window._tracking_threads.get(pier_key(window._current_pier))
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
    from galileo.current_object import pier_key
    assert window._tracking_threads.get(pier_key(window._current_pier)) is None


async def _async_noop(*args, **kwargs):
    return None


@pytest.mark.requirement("TC-EQP-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_010_camera_page_has_a_connect_button_per_panel(window):
    """EQP-010: the Camera equipment panel provides connect, disconnect, and live connection-status —
    it previously had none of the three at all: every other device category (Mount, Focuser, Rotator,
    Filter Wheel, the generic scan-only categories) has its own Connect button, but the Camera panel's
    header only ever had Remove, with no way to connect a device short of a Pier switch or app restart."""
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")

    page = window._build_camera_page()
    frames = [f for f in page.findChildren(QtWidgets.QFrame) if f.objectName() == "DeviceSlotPanel"]
    assert frames, "expected at least the Primary camera panel"
    panel_buttons = {b.text() for b in frames[0].findChildren(QtWidgets.QPushButton)}
    assert "Connect" in panel_buttons


@pytest.mark.requirement("TC-EQP-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_010_camera_connect_button_connects_the_device(window, monkeypatch):
    """EQP-010: clicking a camera panel's Connect button — for a device picked but not yet saved, so
    the page's own build-time/Pier-switch autoconnect (unrelated to this button) has nothing to act on
    — actually connects it. Isolated from the Save-button flow (a separate test below), which now also
    auto-connects and would otherwise make this pass even with a broken/missing Connect button."""
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from unittest.mock import AsyncMock

    fake_adapter = AsyncMock()
    fake_adapter.get_driver_info = AsyncMock(return_value={"name": "CCD Simulator", "version": "1.0"})
    monkeypatch.setattr(window, "_connect_device_adapter", lambda *a, **k: fake_adapter)

    page = window._build_camera_page()
    assert window._camera_backends.get("primary camera") is None, "nothing configured/saved yet"

    frames = [f for f in page.findChildren(QtWidgets.QFrame) if f.objectName() == "DeviceSlotPanel"]
    device_combo = frames[0].findChildren(QtWidgets.QComboBox)[0]
    device_combo.setEditText("CCD Simulator")

    connect_btn = next(b for b in frames[0].findChildren(QtWidgets.QPushButton) if b.text() == "Connect")
    connect_btn.click()

    assert window._camera_backends.get("primary camera") is fake_adapter


@pytest.mark.requirement("TC-EQP-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_010_a_connected_camera_survives_switching_to_another_pier_and_back(window, monkeypatch):
    """EQP-010: a camera connected for one Pier stays connected — not disconnected, not silently
    reused — when a different Pier is selected and then this one is selected again. Each Pier now
    gets its own camera-backends dict (galileo/ui/app_window/_core.py's _camera_backends property),
    which is what makes it possible for two Piers to each keep a live (even mid-capture) camera
    connection at once, rather than the whole window sharing one dict that a Pier switch used to
    have to blow away to avoid handing Pier B a stale reference to Pier A's camera."""
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from unittest.mock import AsyncMock
    from galileo.observatory import create_pier

    fake_adapter = AsyncMock()
    fake_adapter.get_driver_info = AsyncMock(return_value={"name": "CCD Simulator", "version": "1.0"})
    monkeypatch.setattr(window, "_connect_device_adapter", lambda *a, **k: fake_adapter)

    pier_a = window._current_pier
    page = window._build_camera_page()
    frames = [f for f in page.findChildren(QtWidgets.QFrame) if f.objectName() == "DeviceSlotPanel"]
    device_combo = frames[0].findChildren(QtWidgets.QComboBox)[0]
    device_combo.setEditText("CCD Simulator")
    connect_btn = next(b for b in frames[0].findChildren(QtWidgets.QPushButton) if b.text() == "Connect")
    connect_btn.click()
    assert window._camera_backends.get("primary camera") is fake_adapter

    pier_b = create_pier(pier_a.observatory, "Pier B")
    window._current_pier = pier_b
    window._on_pier_changed()
    assert window._camera_backends.get("primary camera") is None, "Pier B has no camera of its own yet"

    window._current_pier = pier_a
    window._on_pier_changed()
    assert window._camera_backends.get("primary camera") is fake_adapter, "Pier A's own connection, untouched"


@pytest.mark.requirement("TC-EQP-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_010_saving_camera_config_auto_connects_a_newly_configured_device(window, monkeypatch):
    """EQP-010/SES: the real-world reported flow — Scan, pick a device, Save, with no manual Connect
    click at all — now leaves the camera connected. Previously nothing but a page rebuild or Pier
    switch ever attempted a connection, so a freshly saved camera stayed "not connected" indefinitely."""
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from unittest.mock import AsyncMock

    fake_adapter = AsyncMock()
    fake_adapter.get_driver_info = AsyncMock(return_value={"name": "CCD Simulator", "version": "1.0"})
    connect_calls = []

    def fake_connect(*args, **kwargs):
        connect_calls.append(args)
        return fake_adapter

    monkeypatch.setattr(window, "_connect_device_adapter", fake_connect)

    page = window._build_camera_page()
    frames = [f for f in page.findChildren(QtWidgets.QFrame) if f.objectName() == "DeviceSlotPanel"]
    device_combo = frames[0].findChildren(QtWidgets.QComboBox)[0]
    device_combo.setEditText("CCD Simulator")

    save_btn = next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Save")
    save_btn.click()

    assert len(connect_calls) == 1, "Save should auto-connect a newly configured device exactly once"
    assert window._camera_backends.get("primary camera") is fake_adapter

    # The Imaging tab's camera selector must reflect this without a Pier switch or app restart —
    # the second half of the reported bug ("the camera is set to not connected in the imaging tab").
    window._build_imaging_page()
    items = [window._camera_combo.itemText(i) for i in range(window._camera_combo.count())]
    assert any("not connected" not in item.lower() and "CCD Simulator" in item for item in items)

    # Saving again (nothing changed) must not reconnect an already-connected device.
    save_btn.click()
    assert len(connect_calls) == 1


# --- Mount meridian flip and limits (EQP-MNT-060 / EQP-MNT-070) --------------------------------

def _limits(**kw):
    from galileo.mount_limits import MountLimits
    return MountLimits(**kw)


@pytest.mark.requirement("TC-EQP-MNT-060")
@pytest.mark.priority("P2")
def test_tc_eqp_mnt_060_flip_is_due_only_past_the_limit_on_the_west_side():
    """EQP-MNT-060: with the flip requested, a tracking mount still on the west side of the pier is
    flipped once the hour angle passes the configured limit, and not otherwise."""
    from galileo.mount_limits import evaluate, flip_due
    on = _limits(flip_enabled=True, flip_ha_deg=5.0)
    assert flip_due(on, 5.0 / 15.0 + 0.01, "West")
    assert not flip_due(on, 4.0 / 15.0, "West")                     # not far enough past the meridian
    assert not flip_due(on, 1.0, "East")                            # already flipped
    assert not flip_due(_limits(flip_enabled=False), 1.0, "West")   # not requested
    assert not flip_due(on, -1.0, "West")                           # still east of the meridian

    base = {"alt_deg": 50.0, "ha_hours": 1.0, "side_of_pier": "West", "slewing": False}
    assert evaluate(on, tracking=True, **base).flip
    assert not evaluate(on, tracking=False, **base).flip            # only flips while tracking


@pytest.mark.requirement("TC-EQP-MNT-070")
@pytest.mark.priority("P2")
def test_tc_eqp_mnt_070_limits_stop_a_tracking_or_slewing_mount():
    """EQP-MNT-070: altitude and hour-angle limits stop a mount that is tracking or slewing; an
    idle mount is left alone, and "Tracking only" spares a slew from the altitude limits."""
    from galileo.mount_limits import evaluate
    lim = _limits(alt_limits_enabled=True, min_alt=20.0, max_alt=85.0, ha_limits_enabled=True, max_ha_hours=2.0)
    ok = {"alt_deg": 45.0, "ha_hours": 0.5, "side_of_pier": "East", "slewing": False}
    assert not evaluate(lim, tracking=True, **ok).stop
    assert evaluate(lim, tracking=True, **{**ok, "alt_deg": 10.0}).stop
    assert evaluate(lim, tracking=True, **{**ok, "alt_deg": 88.0}).stop
    assert evaluate(lim, tracking=True, **{**ok, "ha_hours": -2.5}).stop        # either side of the meridian
    assert evaluate(lim, tracking=False, **{**ok, "alt_deg": 10.0, "slewing": True}).stop
    assert not evaluate(lim, tracking=False, **{**ok, "alt_deg": 10.0}).stop     # idle / parked
    assert not evaluate(_limits(), tracking=True, **{**ok, "alt_deg": 10.0}).stop  # nothing enabled

    track_only = _limits(alt_limits_enabled=True, min_alt=20.0, alt_tracking_only=True)
    low = {**ok, "alt_deg": 10.0}
    assert evaluate(track_only, tracking=True, **low).stop
    assert not evaluate(track_only, tracking=False, **{**low, "slewing": True}).stop


@pytest.mark.requirement("TC-EQP-MNT-070")
@pytest.mark.priority("P2")
def test_tc_eqp_mnt_070_slews_beyond_the_limits_are_refused():
    """EQP-MNT-070: the slew guard refuses an RA/Dec or Alt/Az slew whose target breaks the limits,
    even when the horizon-obstruction check is switched off."""
    import datetime as dt
    from galileo.core.slew_guard import SlewGuard
    from galileo.exceptions import MountLimitError
    from galileo.planning import star_atlas as sa

    guard = SlewGuard()
    guard.latitude, guard.longitude = 45.0, -75.0
    guard.limits = _limits(alt_limits_enabled=True, min_alt=30.0, max_alt=80.0)
    guard.check_altaz(50.0, 180.0)
    with pytest.raises(MountLimitError):
        guard.check_altaz(10.0, 180.0)

    # An RA/Dec that is on the meridian at declination 45 is at the zenith from latitude 45: too high.
    when = dt.datetime(2026, 1, 1, 6, 0, tzinfo=dt.UTC)
    lst = float(sa.local_sidereal_deg(sa.julian_date(when), guard.longitude))
    with pytest.raises(MountLimitError):
        guard.check_radec(lst, 45.0, when)

    guard.limits = _limits(ha_limits_enabled=True, max_ha_hours=1.0)
    guard.check_radec(lst, 45.0, when)                              # on the meridian: fine
    with pytest.raises(MountLimitError):
        guard.check_radec((lst - 60.0) % 360.0, 45.0, when)         # 4 h west of the meridian
    with pytest.raises(MountLimitError):
        guard.check_altaz(10.0, 270.0)                              # due west on the horizon: far from the meridian


@pytest.mark.requirement("TC-EQP-MNT-060")
@pytest.mark.priority("P2")
def test_tc_eqp_mnt_060_pier_side_text():
    """EQP-MNT-060: the Mount page spells out which way the telescope points for each pier side."""
    from galileo.mount_limits import pier_side_text
    assert pier_side_text("East") == "East (pointing West)"
    assert pier_side_text("West") == "West (pointing East)"
    assert pier_side_text(None) == "Unknown"


@pytest.mark.requirement("TC-EQP-MNT-060")
@pytest.mark.priority("P2")
def test_tc_eqp_mnt_060_flip_and_limit_settings_are_saved_per_pier(window):
    """EQP-MNT-060/070: the Mount page's flip and limit settings round-trip through Save, reach the
    Pier's slew guard immediately, and come back when the page is reloaded."""
    from PySide6 import QtWidgets
    from galileo.core.slew_guard import get_slew_guard
    from galileo.current_object import pier_key
    from galileo.observatory import get_device_config, mount_limits_from_config

    page = window._build_mount_page()
    checks = {c.text(): c for c in page.findChildren(QtWidgets.QCheckBox)}
    spins = page.findChildren(QtWidgets.QDoubleSpinBox)
    flip_ha = next(s for s in spins if s.suffix() == "" and s.value() == 5.0)
    checks["Flip if HA >:"].setChecked(True)
    checks["Enable Alt limits"].setChecked(True)
    checks["Enable HA limits"].setChecked(True)
    flip_ha.setValue(7.5)

    guard = get_slew_guard(pier_key(window._current_pier))
    assert guard.limits.flip_enabled and guard.limits.alt_limits_enabled and guard.limits.flip_ha_deg == 7.5

    next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Save").click()
    saved = mount_limits_from_config(get_device_config(window._current_pier, "mount"))
    assert saved.flip_enabled and saved.alt_limits_enabled and saved.ha_limits_enabled
    assert saved.flip_ha_deg == 7.5 and saved.max_alt == 90.0

    checks["Flip if HA >:"].setChecked(False)
    window._device_pages["mount"]["reload"]()
    assert checks["Flip if HA >:"].isChecked() and flip_ha.value() == 7.5


@pytest.mark.requirement("TC-EQP-MNT-060")
@pytest.mark.priority("P2")
async def test_tc_eqp_mnt_060_monitor_flips_a_tracking_mount_and_stops_one_out_of_limits():
    """EQP-MNT-060/070: one monitor pass flips a tracking mount that is past its flip limit and
    resumes tracking, and aborts + stops tracking on a mount that has broken a limit."""
    pytest.importorskip("PySide6")
    from galileo.ui.app_window._threads import _MountGuardThread

    def mount(status):
        m = MagicMock()
        m.get_status = AsyncMock(return_value=status)
        for name in ("abort_slew", "set_tracking", "move_axis", "slew_to_coordinates"):
            setattr(m, name, AsyncMock())
        return m

    # LST 10h, RA 9h -> HA +1h (15 deg) west of the meridian, still on the west side of the pier.
    status = {"sidereal_time": 10.0, "right_ascension": 9.0, "declination": 30.0, "altitude": 50.0,
              "side_of_pier": "West", "tracking": True, "slewing": False}

    flipper = mount(status)
    result: dict = {}
    await _MountGuardThread(flipper, _limits(flip_enabled=True, flip_ha_deg=5.0))._guard(result)
    assert result["kind"] == "flipped"
    flipper.slew_to_coordinates.assert_awaited_once_with(ra=135.0, dec=30.0)

    stopper = mount({**status, "altitude": 5.0})
    result = {}
    await _MountGuardThread(stopper, _limits(alt_limits_enabled=True, min_alt=15.0))._guard(result)
    assert result["kind"] == "stopped" and "below the minimum" in result["reasons"][0]
    stopper.abort_slew.assert_awaited_once()
    stopper.set_tracking.assert_awaited_once_with(False)


@pytest.mark.requirement("TC-EQP-MNT-020")
@pytest.mark.priority("MVP")
def test_tc_eqp_mnt_020_park_and_tracking_controls_and_status_text(window):
    """EQP-MNT-020/010: the Mount page has separate Park/Unpark and Tracking On/Off buttons, and
    shows the park status and the tracking state with its rate."""
    from PySide6 import QtWidgets
    page = window._build_mount_page()
    buttons = {b.text(): b for b in page.findChildren(QtWidgets.QPushButton)}
    assert {"Park", "Unpark", "Tracking On", "Tracking Off", "Set tracking rate"} <= set(buttons)

    mount = MagicMock()
    mount.get_status = AsyncMock(return_value={"tracking": True, "tracking_rate": "Lunar", "at_park": False})
    for name in ("set_tracking", "unpark", "park"):
        setattr(mount, name, AsyncMock())
    window._device_pages["mount"]["adapter"] = mount

    def labels():
        return {label.text() for label in page.findChildren(QtWidgets.QLabel)}
    buttons["Tracking Off"].click()
    mount.set_tracking.assert_awaited_once_with(False)
    assert "Tracking: On (Lunar rate)" in labels() and "Park status: Unparked" in labels()
    assert buttons["Park"].isEnabled() and not buttons["Unpark"].isEnabled()

    mount.get_status.return_value = {"tracking": False, "tracking_rate": "Sidereal", "at_park": True}
    buttons["Tracking On"].click()          # any action refreshes the status
    buttons["Unpark"].click()
    mount.unpark.assert_awaited_once()
    assert "Tracking: Off (Sidereal rate selected)" in labels() and "Park status: Parked" in labels()
    assert not buttons["Park"].isEnabled()


@pytest.mark.requirement("TC-EQP-MNT-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_mnt_010_jog_pad_lists_the_drivers_slew_rates_and_mirrors_its_reversal(window):
    """EQP-MNT-010: with an INDI mount the Rate drop-down lists the driver's own slew rates (choosing one
    selects it in the driver, a jog then sends only the direction), and Primary/Secondary reversed show
    the driver's setting, write changes to it, and are not applied a second time by the UI."""
    from PySide6 import QtWidgets
    page = window._build_mount_page()
    rate = next(c for c in page.findChildren(QtWidgets.QComboBox) if c.findData(10.0) >= 0)
    mount = MagicMock()
    mount.get_status = AsyncMock(return_value={})
    mount.move_axis = AsyncMock()
    mount.set_slew_rate = AsyncMock()
    mount.set_axis_reversed = AsyncMock()
    state = window._device_pages["mount"]
    state["adapter"] = mount
    status = {"slew_rates": ["Guide", "Centering", "Find", "Max"], "slew_rate_index": 1,
              "axis_reversed": (False, True)}
    state["last_status"] = status
    state["sync_manual_motion"]()   # what each status refresh does
    assert [rate.itemText(i) for i in range(rate.count())] == status["slew_rates"]
    assert rate.currentText() == "Centering"
    primary = next(c for c in page.findChildren(QtWidgets.QCheckBox) if c.text() == "Primary reversed")
    secondary = next(c for c in page.findChildren(QtWidgets.QCheckBox) if c.text() == "Secondary reversed")
    assert (primary.isChecked(), secondary.isChecked()) == (False, True)
    assert state["axis_reversed"]() == (False, False)   # the driver reverses; the UI must not
    primary.setChecked(True)
    mount.set_axis_reversed.assert_awaited_once_with(0, True)
    rate.setCurrentIndex(3)
    jog = state["jog_controller"]
    jog.flush()
    mount.set_slew_rate.assert_awaited_with(3)
    east = next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "→")
    east.pressed.emit()
    jog.flush()
    east.released.emit()
    jog.flush()
    assert mount.move_axis.await_args_list[0].args[0] == 0 and mount.move_axis.await_args_list[0].args[1] > 0
    state["last_status"] = {}   # no driver rates: back to the fixed levels
    state["sync_manual_motion"]()
    assert rate.findData(10.0) >= 0 and state["axis_reversed"]() == (True, True)


@pytest.mark.requirement("TC-EQP-MNT-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_mnt_010_jog_pad_has_a_rate_selector_at_the_faster_speeds(window):
    """EQP-MNT-010: the N/S/E/W pad has a rate drop-down of levels 1-9, and a jog moves the
    mount at the selected level's speed (level 9 = 10 deg/s)."""
    from PySide6 import QtWidgets
    page = window._build_mount_page()
    rate = next(c for c in page.findChildren(QtWidgets.QComboBox) if c.findData(10.0) >= 0)
    assert [rate.itemText(i) for i in range(rate.count())] == [str(n) for n in range(1, 10)]
    assert rate.itemData(rate.count() - 1) == 10.0 and rate.currentText() == "5"
    mount = MagicMock()
    mount.get_status = AsyncMock(return_value={})
    mount.move_axis = AsyncMock()
    window._device_pages["mount"]["adapter"] = mount
    rate.setCurrentIndex(rate.findData(10.0))
    east = next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "→")
    east.pressed.emit()
    window._device_pages["mount"]["jog_controller"].flush()
    mount.move_axis.assert_awaited_once_with(0, 10.0)   # held: still moving
    east.released.emit()
    window._device_pages["mount"]["jog_controller"].flush()
    assert mount.move_axis.await_args_list[-1].args == (0, 0.0)


# --- the Mount page's logic without the page (galileo.mount_ops) ---------------------------------------------

class _OpsMount:
    """A mount adapter that records what it is asked and can be told to fail."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def _go(self, name, *args):
        async def run():
            self.calls.append((name, *args))
            if self.fail:
                raise self.fail
        return run()

    def slew_to_coordinates(self, ra, dec):
        return self._go("slew_radec", ra, dec)

    def slew_to_altaz(self, alt, az):
        return self._go("slew_altaz", alt, az)

    def park(self):
        return self._go("park")

    def set_tracking(self, on):
        return self._go("tracking", on)

    def set_axis_reversed(self, axis, value):
        return self._go("reversed", axis, value)

    async def get_status(self):
        return {"tracking": True}


@pytest.mark.requirement("TC-EQP-MNT-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_mnt_010_mount_ops_commands_and_outcomes():
    """EQP-MNT-010: mount commands run against the adapter and report what happened as an outcome (parked,
    obstructed, limit, failed, not connected) with no screen involved."""
    from galileo.exceptions import MountLimitError, MountParkedError, SlewObstructedError
    from galileo.mount_ops import FAILED, LIMIT, NOT_CONNECTED, OBSTRUCTED, PARKED, UNSUPPORTED, MountOps

    mount = _OpsMount()
    ops = MountOps(lambda: mount)
    assert ops.slew_to_coordinates(1.0, 20.0).ok and mount.calls[-1] == ("slew_radec", 15.0, 20.0)   # hours -> degrees
    assert ops.slew_to_altaz(45.0, 180.0).ok and ops.park().ok and ops.set_tracking(True).ok
    assert ops.set_axis_reversed(1, True).ok and mount.calls[-1] == ("reversed", 1, True)

    mount.fail = MountParkedError("parked")
    assert ops.slew_to_coordinates(1.0, 2.0).kind == PARKED and ops.set_tracking(False).kind == PARKED
    assert ops.park().kind == FAILED and "Park failed" in ops.park().message                        # park is never "parked"
    mount.fail = SlewObstructedError("blocked")
    assert ops.slew_to_altaz(1.0, 2.0).kind == OBSTRUCTED
    mount.fail = MountLimitError("below the altitude limit")
    out = ops.slew_to_coordinates(1.0, 2.0)
    assert out.kind == LIMIT and out.message == "below the altitude limit"
    mount.fail = RuntimeError("boom")
    assert ops.slew_to_coordinates(1.0, 2.0).kind == FAILED and ops.slew_to_coordinates(1.0, 2.0).message == "Slew failed — see log."

    none = MountOps(lambda: None)
    assert none.park().kind == NOT_CONNECTED and none.status() is None and not none.disconnect()
    assert MountOps(lambda: mount).status() == {"tracking": True}
    assert MountOps(lambda: mount).set_home_position().kind == UNSUPPORTED                        # no such method on this driver


@pytest.mark.requirement("TC-EQP-MNT-020")
@pytest.mark.priority("MVP")
def test_tc_eqp_mnt_020_mount_status_text_and_targets():
    """EQP-MNT-020: the status display text, the park/tracking wording and the manual coordinate fields are
    computed without the page."""
    from galileo.mount_ops import describe_status, target_alt_az, target_ra_dec

    blank = describe_status({})
    assert blank.name == "—" and blank.tracking_status == "Tracking: —" and blank.park_status == "Park status: —"
    assert blank.park_enabled and blank.unpark_enabled and blank.tracking_flag is None
    view = describe_status({"name": "EQ6", "right_ascension": 6.5, "sidereal_time": 5.0, "declination": -10.5,
                            "site_elevation": 123.456, "tracking": True, "tracking_rate": "sidereal", "at_park": False})
    assert view.name == "EQ6" and view.right_ascension == "06:30:00" and view.meridian_in == "01:30:00"
    assert view.declination.startswith("-10°") and view.site_elevation == "123.5 m"
    assert view.tracking_status == "Tracking: On (sidereal rate)" and view.park_status == "Park status: Unparked"
    assert view.park_enabled and view.unpark_enabled is False
    parked = describe_status({"tracking": False, "tracking_rate": "lunar", "at_park": True})
    assert parked.tracking_status == "Tracking: Off (lunar rate selected)" and not parked.park_enabled and parked.unpark_enabled

    assert target_ra_dec((1, 30, 0.0), (-10, 30, 0)) == (1.5, -10.5)
    assert target_alt_az((45, 0, 36), (180, 30, 0)) == (45.01, 180.5)


@pytest.mark.requirement("TC-EQP-MNT-020")
@pytest.mark.priority("MVP")
def test_tc_eqp_mnt_020_connect_mount_uses_given_factory_and_site():
    """EQP-MNT-020: a mount is built by whichever factory is given, told the Observatory's location, connected,
    and a failure gives ``None`` instead of raising."""
    from types import SimpleNamespace

    from galileo.core.devices import DeviceCategory
    from galileo.mount_ops import connect_mount

    adapter = MagicMock()
    adapter.connect = AsyncMock()
    made = []

    def factory(*args):
        made.append(args)
        return adapter

    site = SimpleNamespace(latitude=51.0, longitude=-114.0, elevation_m=1000.0)
    assert connect_mount(factory, "INDI", "pi", 7624, "EQMod", site) is adapter
    assert made == [(DeviceCategory.MOUNT, "INDI", "pi", 7624, "EQMod")]
    assert (adapter.site_lat, adapter.site_lon, adapter.site_elevation) == (51.0, -114.0, 1000.0)
    adapter.connect.assert_awaited_once()

    adapter.connect = AsyncMock(side_effect=RuntimeError("no route"))
    assert connect_mount(factory, "INDI", "pi", 7624, "EQMod") is None
    assert connect_mount(lambda *a: (_ for _ in ()).throw(OSError("x")), "INDI", "pi", 7624, "EQMod") is None


class _OpsFocuser:
    def __init__(self):
        self.position = 500
        self.moves = []
        self.temp_comp = None
        self.fail = False
        self.disconnected = False

    async def move_to(self, target):
        if self.fail:
            raise RuntimeError("stalled")
        self.moves.append(target)

    async def set_temp_comp(self, enabled):
        self.temp_comp = enabled

    async def get_status(self):
        return {"position": self.position}

    async def get_driver_info(self):
        return {"name": "Mock"}

    async def disconnect(self):
        self.disconnected = True


@pytest.mark.requirement("TC-EQP-FOC-040")
@pytest.mark.priority("P2")
def test_tc_eqp_foc_040_focuser_ops_commands_and_outcomes():
    """EQP-FOC-040: focuser commands run without the page and report an outcome; travel limits are changed
    through the focuser settings and refused when they would not be a range."""
    from galileo.device_ops import FAILED, NOT_CONNECTED
    from galileo.focuser_ops import FocuserOps, clear_travel_limits, set_travel_limit
    from galileo.focuser_settings import FocuserSettings

    focuser = _OpsFocuser()
    ops = FocuserOps(lambda: focuser)
    assert ops.move_to(700).ok and focuser.moves == [700]
    assert ops.set_temp_comp(True).ok and focuser.temp_comp is True
    assert ops.status() == {"position": 500} and ops.driver_info() == {"name": "Mock"} and ops.position() == 500
    focuser.fail = True
    failed = ops.move_to(1)
    assert failed.kind == FAILED and failed.message == "Move failed — see log."
    assert ops.disconnect() and focuser.disconnected

    none = FocuserOps(lambda: None)
    assert none.move_to(1).kind == NOT_CONNECTED and none.status() is None and none.position() is None
    assert not none.disconnect()

    settings = FocuserSettings()
    assert set_travel_limit(settings, "max", 900) == "" and settings.travel_max == 900
    assert set_travel_limit(settings, "min", 100) == "" and (settings.travel_min, settings.travel_max) == (100, 900)
    assert set_travel_limit(settings, "min", 950)                                  # above the max: refused
    assert (settings.travel_min, settings.travel_max) == (100, 900)
    ops.apply_travel(settings)
    assert (focuser.travel_min, focuser.travel_max) == (100, 900)
    clear_travel_limits(settings)
    assert settings.travel_min is None and settings.travel_max is None


@pytest.mark.requirement("TC-EQP-FOC-040")
@pytest.mark.priority("P2")
def test_tc_eqp_foc_040_focuser_status_text_and_transitions(caplog):
    """EQP-FOC-040: the panel text is computed without the page, and only moves/settles starting or stopping
    are logged."""
    import logging

    from galileo.focuser_ops import describe_status, log_transitions

    blank = describe_status({})
    assert blank.is_moving == blank.position == blank.temperature == "—"
    assert blank.position_value is None and blank.temp_comp is None
    view = describe_status({"is_moving": True, "is_settling": False, "position": 1234, "temp_comp": 0,
                            "temperature": 12.34, "max_step": 5000})
    assert (view.is_moving, view.is_settling, view.position, view.position_value) == ("Yes", "No", "1234", 1234)
    assert view.temp_comp is False and view.temperature == "12.3 °C" and view.max_step == "5000"

    with caplog.at_level(logging.INFO, logger="galileo.focuser_ops"):
        last = log_transitions("Primary", {"is_moving": True, "position": 1}, (None, None), 99)
        last = log_transitions("Primary", {"is_moving": True, "position": 2}, last, 99)      # unchanged: silent
        last = log_transitions("Primary", {"is_moving": False, "position": 3}, last, 99)
    assert last == (False, None)
    assert [r.getMessage() for r in caplog.records] == [
        "Focuser Primary: started moving (target position 99)", "Focuser Primary: stopped moving at position 3"]


@pytest.mark.requirement("TC-EQP-FOC-040")
@pytest.mark.priority("P2")
def test_tc_eqp_foc_040_device_ops_connect_and_scan(monkeypatch):
    """EQP-FOC-040: a device is built by the given factory, configured and connected, and a failed step gives
    ``None`` instead of raising."""
    from galileo.core.devices import DeviceCategory
    from galileo.device_ops import connect_device

    adapter = MagicMock()
    adapter.connect = AsyncMock()
    configured = []
    got = connect_device(lambda *a: adapter, DeviceCategory.FOCUSER, "INDI", "pi", 7624, "Focuser",
                         configure=configured.append)
    assert got is adapter and configured == [adapter]
    adapter.connect.assert_awaited_once()
    assert connect_device(lambda *a: adapter, DeviceCategory.FOCUSER, "INDI", "pi", 7624, "F",
                          configure=lambda a: 1 / 0) is None


@pytest.mark.requirement("TC-EQP-ROT-010")
@pytest.mark.priority("P2")
def test_tc_eqp_rot_010_rotator_ops_outcomes_and_status():
    """EQP-ROT-010: rotator commands report an outcome without the page, a driver without the property is
    'unsupported' with its own text, and the status/derotation maths need no screen."""
    from galileo.device_ops import FAILED, NOT_CONNECTED, UNSUPPORTED
    from galileo.exceptions import DevicePropertyError
    from galileo.rotator_ops import RotatorOps, derotation_rate, describe_status

    class Rot:
        def __init__(self):
            self.calls = []

        async def move_to_angle(self, angle):
            self.calls.append(angle)

        async def set_backlash(self, value):
            raise DevicePropertyError("no backlash")

        async def sync_position(self, value):
            raise RuntimeError("boom")

    rot = Rot()
    ops = RotatorOps(lambda: rot)
    assert ops.run("move_to_angle", 12.5, action="move").ok and rot.calls == [12.5]
    unsupported = ops.run("set_backlash", 1.0, action="backlash")
    assert unsupported.kind == UNSUPPORTED and unsupported.message == "no backlash"
    failed = ops.run("sync_position", 0.0, action="sync")
    assert failed.kind == FAILED and failed.message == "Rotator sync failed — see log."
    assert RotatorOps(lambda: None).run("move_to_angle", 1, action="move").kind == NOT_CONNECTED

    blank = describe_status({})
    assert not blank.connected and blank.position_text == "—" and blank.detail == "" and blank.goto_hint == ""
    view = describe_status({"position": 10.0, "mechanical_position": 20.0, "is_moving": True, "reverse": 0,
                            "backlash_supported": True, "backlash": 1.5, "max_angle": 360.0, "can_sync": False})
    assert view.connected and view.position_text == "10.00" and view.detail == "Mechanical 20.00° · Sky 10.00° · moving"
    assert view.reverse is False and view.backlash == 1.5 and view.backlash_tip == ""
    assert view.goto_hint == "(0 – 359.99)" and not view.can_sync
    assert describe_status({"position": 1.0}).backlash_tip == "This rotator's driver has no backlash setting."

    assert derotation_rate(None, 50.0, -100.0, 0, False) is None
    # Polaris from mid-northern latitude is above the horizon; the opposite pole is below it.
    up = derotation_rate((37.95, 89.26), 50.0, -100.0, 0, False)
    assert up is not None and up[2] is not None
    assert derotation_rate((37.95, 89.26), 50.0, -100.0, 10, True)[2] == pytest.approx(-up[2] * 1.1)
    assert derotation_rate((0.0, -89.0), 50.0, -100.0, 0, False)[2] is None


@pytest.mark.requirement("TC-EQP-WX-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_wx_010_weather_ops_readings_and_verdict():
    """EQP-WX-010: a safety device is polled, shown and judged against its rules without the page."""
    from galileo.safety import WeatherSafetyRule
    from galileo.weather_ops import banner_text, format_value, read_device, violations

    class Monitor:
        is_safe = False

        async def poll(self):
            pass

    assert read_device(Monitor(), "safety_monitor") == {"is_safe": 0.0}
    Monitor.is_safe = True
    assert read_device(Monitor(), "safety_monitor") == {"is_safe": 1.0}

    assert format_value(None, "C") == "—" and format_value(1, "bool") == "Yes" and format_value(0, "bool") == "No"
    assert format_value(12.345, "C") == "12.3 C" and format_value("windy", "C") == "windy"

    rule = WeatherSafetyRule("wind", safety_related=True, operator=">", threshold=30.0, label="Wind", unit="km/h")
    ignored = WeatherSafetyRule("rain", safety_related=False, operator=">", threshold=0.0, label="Rain", unit="mm")
    assert banner_text({}, [rule], "Weather Station") == "Not connected."
    assert banner_text({"wind": 5.0}, [rule], "Weather Station") == "Weather Station: SAFE"
    unsafe = banner_text({"wind": 50.0}, [rule], "Weather Station")
    assert unsafe.startswith("Weather Station: UNSAFE — ") and "Wind" in unsafe
    assert violations({"wind": 5.0, "rain": 9.0}, [rule, ignored]) == []             # a rule not marked safety-related is ignored
    assert len(violations({"wind": 50.0}, [rule, ignored])) == 1


@pytest.mark.requirement("TC-EQP-DOME-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_dome_010_dome_ops_outcomes_status_and_slaving():
    """EQP-DOME-010: dome commands, the status text and the slaving steps work without the page."""

    from galileo.device_ops import FAILED, NOT_CONNECTED
    from galileo.dome_ops import DomeOps, describe_status, slave_status_text, slave_step, sync_to_mount

    class Dome:
        def __init__(self):
            self.calls = []

        async def open_shutter(self):
            self.calls.append("open")

        async def park(self):
            raise RuntimeError("stuck")

    dome = Dome()
    ops = DomeOps(lambda: dome)
    assert ops.run("open_shutter", action="open").ok and dome.calls == ["open"]
    failed = ops.run("park", action="park")
    assert failed.kind == FAILED and failed.message == "Dome park failed — see log."
    assert DomeOps(lambda: None).run("open_shutter", action="open").kind == NOT_CONNECTED

    blank = describe_status({})
    assert not blank.connected and blank.park_chip == "—" and blank.at_park is None and blank.park_button == "Park"
    parked = describe_status({"shutter_state": "Closed", "azimuth": 90.04, "is_at_park": True})
    assert (parked.shutter, parked.azimuth, parked.park_button, parked.park_chip) == ("Closed", "90.0°", "Unpark", "Parked")
    assert parked.parked and describe_status({"is_at_park": False}).park_chip == "Unparked"

    class Service:
        slaving_enabled = True
        ready = True
        last_slaved_azimuth = None
        fail = False

        async def sync_to_mount(self, force):
            if self.fail:
                raise RuntimeError("no mount")

        async def track_mount(self):
            if self.fail:
                raise RuntimeError("no mount")

    service = Service()
    assert sync_to_mount(service).ok and slave_step(service)
    assert slave_status_text(service) == "Slaving on — waiting for the mount to track"
    service.last_slaved_azimuth = 123.45
    assert slave_status_text(service) == "Slaving on — followed mount to 123.5°"
    service.ready = False
    assert slave_status_text(service) == "Waiting for a connected mount"
    service.slaving_enabled = False
    assert slave_status_text(service) == "Slaving off" and slave_status_text(None) == "—"
    service.fail = True
    assert sync_to_mount(service).message == "Dome sync failed — see log." and not slave_step(service)


@pytest.mark.requirement("TC-EQP-SW-120")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_120_switch_ops_degrade_instead_of_raising(monkeypatch):
    """EQP-SW-120: a lost server or a device that stops answering gives an error result, not an exception; a channel
    write reports what failed."""
    from types import SimpleNamespace

    from galileo.device_ops import FAILED, NOT_CONNECTED, UNSUPPORTED
    from galileo.switch_ops import SwitchOps, format_reading

    class Adapter:
        pass

    channel = SimpleNamespace(id="p1", label="Dew heater")
    none = SwitchOps(lambda: None)
    assert none.read_panel() is None and none.set_channel(channel).kind == NOT_CONNECTED
    assert none.write_property("X", {}).kind == NOT_CONNECTED

    adapter = Adapter()
    ops = SwitchOps(lambda: adapter)
    assert ops.write_property("X", {}).kind == UNSUPPORTED                    # this adapter has no raw writer
    wrote = []

    async def writer(name, values):
        wrote.append((name, values))

    adapter.write_property = writer
    assert ops.write_property("X", {"a": 1}).ok and wrote == [("X", {"a": 1})]

    async def broken(name, values):
        raise RuntimeError("link down")

    adapter.write_property = broken
    failed = ops.write_property("X", {})
    assert failed.kind == FAILED and failed.message == "Could not set X: link down"

    from galileo.core.devices import SwitchController

    assert ops.read_panel().error == ""                                         # a bare adapter reads as an empty panel

    async def lost(self):
        raise ConnectionError("server gone")

    monkeypatch.setattr(SwitchController, "get_panel", lost)
    result = ops.read_panel()
    assert result is not None and result.panel is None
    assert result.error == "Cannot read the device right now: server gone"
    assert format_reading(None, "A") == "—" and format_reading(float("nan"), "A") == "—"
    assert format_reading(1.234, "A") == "1.23 A"


@pytest.mark.requirement("TC-EQP-FW-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_fw_010_filter_wheel_ops_and_status():
    """EQP-FW-010: a filter change reports an outcome and the wheel's status is described without the page."""
    from galileo.device_ops import FAILED, NOT_CONNECTED
    from galileo.simple_device_ops import FilterWheelOps, describe_filter_wheel

    class Wheel:
        moves = []
        fail = False

        async def move_to(self, index):
            if self.fail:
                raise RuntimeError("jammed")
            self.moves.append(index)

    wheel = Wheel()
    ops = FilterWheelOps(lambda: wheel)
    assert ops.move_to(2).ok and wheel.moves == [2]
    wheel.fail = True
    failed = ops.move_to(3)
    assert failed.kind == FAILED and failed.message == "Filter change failed — see log."
    assert FilterWheelOps(lambda: None).move_to(1).kind == NOT_CONNECTED

    view = describe_filter_wheel({"name": "EFW", "filter_names": ["L", "R", "G"], "position": 1})
    assert (view.name, view.position, view.current_filter, view.filter_names) == ("EFW", 1, "R", ["L", "R", "G"])
    out_of_range = describe_filter_wheel({"filter_names": ["L"], "position": 5})
    assert out_of_range.position is None and out_of_range.current_filter is None and out_of_range.name == "—"
    assert describe_filter_wheel({}).filter_names == []


@pytest.mark.requirement("TC-EQP-FP-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_fp_010_flat_panel_ops_and_status():
    """EQP-FP-010: flat panel commands report an outcome and the cover/light/brightness text needs no page."""
    from galileo.device_ops import FAILED, NOT_CONNECTED
    from galileo.simple_device_ops import FlatPanelOps, describe_flat_panel

    class Panel:
        levels = []

        async def set_brightness(self, level):
            self.levels.append(level)

        async def light_on(self):
            raise RuntimeError("no power")

    panel = Panel()
    ops = FlatPanelOps(lambda: panel)
    assert ops.run("set_brightness", 77, action="set brightness").ok and panel.levels == [77]
    failed = ops.run("light_on", action="light on")
    assert failed.kind == FAILED and failed.message == "Flat panel light on failed — see log."
    assert FlatPanelOps(lambda: None).run("light_on", action="light on").kind == NOT_CONNECTED

    blank = describe_flat_panel({})
    assert not blank.connected and (blank.cover, blank.light, blank.brightness) == ("—", "—", None)
    view = describe_flat_panel({"cover_state": "Closed", "is_light_on": False, "brightness": 128.0})
    assert view.connected and (view.cover, view.light, view.brightness) == ("Parked", "Off", 128)
    assert describe_flat_panel({"cover_state": "Open", "is_light_on": True}).cover == "Unparked"


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_aux_ops_write_read_and_rebuild(monkeypatch):
    """EQP-AUX-010: a property write reports an outcome, groups are read without raising, and the tabs are rebuilt
    only when the device's set of properties changes."""
    from types import SimpleNamespace

    from galileo.core.devices import AuxController
    from galileo.device_ops import FAILED, NOT_CONNECTED
    from galileo.simple_device_ops import AuxOps, aux_needs_rebuild

    written = []

    async def write(self, name, values):
        if name == "BAD":
            raise RuntimeError("rejected")
        written.append((name, values))

    async def groups(self):
        return [SimpleNamespace(properties=[SimpleNamespace(name="A"), SimpleNamespace(name="B")])]

    monkeypatch.setattr(AuxController, "write_property", write)
    monkeypatch.setattr(AuxController, "get_property_groups", groups)
    ops = AuxOps(lambda: object())
    assert ops.write_property("A", {"x": 1}).ok and written == [("A", {"x": 1})]
    failed = ops.write_property("BAD", {})
    assert failed.kind == FAILED and failed.message == "Could not set BAD — see log."
    none = AuxOps(lambda: None)
    assert none.write_property("A", {}).kind == NOT_CONNECTED and none.read_groups() is None

    found = ops.read_groups()
    assert found is not None
    assert not aux_needs_rebuild({"A", "B"}, found, True)
    assert aux_needs_rebuild({"A"}, found, True) and aux_needs_rebuild({"A", "B"}, found, False)

    async def broken(self):
        raise ConnectionError("gone")

    monkeypatch.setattr(AuxController, "get_property_groups", broken)
    assert ops.read_groups() is None
