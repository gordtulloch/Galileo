"""INDI adapter behavior against a real-protocol fake INDI server.

Unlike the mock-based tests in ``test_eqp.py`` / ``test_ext.py`` (which use
``MagicMock`` device fixtures), these drive ``galileo.adapters.indi`` and the
native client in ``galileo.adapters.indi_client`` end to end over a loopback
TCP socket to ``tests/indi_fake_server.py``. They add coverage for the
requirements below (EQP-040, EQP-CAM-010/020, EQP-MNT-010, EQP-FW-010,
EQP-FOC-010, EXT-020/030) rather than introducing new TC IDs.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from galileo.adapters import indi, indi_client
from galileo.core.devices import DeviceCategory
from galileo.exceptions import DeviceConnectionError, DevicePropertyError

from tests.indi_fake_server import IMAGE, FakeIndiServer

CCD, MOUNT, WHEEL, FOCUSER = "CCD Simulator", "Telescope Simulator", "Filter Simulator", "Focuser Simulator"


@pytest.fixture
def server():
    srv = FakeIndiServer()
    yield srv
    srv.close()
    assert indi_client._registry == {}, "adapters leaked a shared INDI connection"


def make(cls, server, device):
    return cls(host="127.0.0.1", port=server.port, device_name=device)


def commands(server, device, prop):
    return [v for _, d, n, v in server.received if d == device and n == prop]


async def eventually(check, timeout=3.0):
    """Await ``check()`` (an async callable) until it returns something truthy, and return that."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await check()
        if result:
            return result
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


async def server_saw(predicate, timeout=3.0):
    """Wait for the fake server (which handles commands on its own threads) to have seen something."""
    async def _check():
        return predicate()
    await eventually(_check, timeout)


async def sent(server, device, prop, expected=None, exact=True, timeout=3.0):
    """Assert the *latest* command the fake server saw for ``device``/``prop`` matches ``expected``
    (exactly, or as a subset of its elements), polling because the server handles commands on its own threads."""
    def _matches():
        cmds = commands(server, device, prop)
        if not cmds:
            return False
        if expected is None:
            return True
        last = cmds[-1]
        return last == expected if exact else all(last.get(k) == v for k, v in expected.items())
    try:
        await server_saw(_matches, timeout)
    except AssertionError:
        raise AssertionError(f"{device}/{prop}: expected {expected!r} ({'exact' if exact else 'subset'}), "
                             f"server saw {commands(server, device, prop)!r}") from None


# --- number parsing --------------------------------------------------------

@pytest.mark.requirement("TC-EQP-MNT-010")
@pytest.mark.priority("MVP")
def test_tc_eqp_mnt_010_parse_sexagesimal_numbers():
    """EQP-MNT-010: mounts report coordinates as INDI sexagesimal numbers, which must parse."""
    assert indi_client.parse_indi_number("12.5") == 12.5
    assert indi_client.parse_indi_number("6:30:00") == 6.5
    assert indi_client.parse_indi_number("-10:30:00") == -10.5
    assert indi_client.parse_indi_number("-0:30") == -0.5
    with pytest.raises(ValueError):
        indi_client.parse_indi_number("nope")


# --- discovery -------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-040")
@pytest.mark.priority("MVP")
async def test_tc_eqp_040_scan_lists_devices_by_category(server):
    """EQP-040: list only the server's devices matching each category (by INDI driver interface)."""
    expected = {
        DeviceCategory.CAMERA: [CCD], DeviceCategory.MOUNT: [MOUNT],
        DeviceCategory.FILTER_WHEEL: [WHEEL], DeviceCategory.FOCUSER: [FOCUSER],
        DeviceCategory.DOME: [], DeviceCategory.SAFETY_MONITOR: [],
    }
    for category, names in expected.items():
        adapter = indi.get_adapter_class(category)(host="127.0.0.1", port=server.port)
        assert await adapter.list_available_devices(category) == names, category


@pytest.mark.requirement("TC-EXT-030")
@pytest.mark.priority("MVP")
async def test_tc_ext_030_unreachable_server_reports_clear_error():
    """EXT-030: an unreachable INDI server surfaces as a DeviceConnectionError naming host:port."""
    adapter = indi.IndiCameraAdapter(host="127.0.0.1", port=1)  # nothing listens on port 1
    with pytest.raises(DeviceConnectionError, match="127.0.0.1:1"):
        await adapter.list_available_devices(DeviceCategory.CAMERA)


# --- connection lifecycle --------------------------------------------------

@pytest.mark.requirement("TC-EQP-CAM-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_010_connect_disconnect_and_blob_enable(server):
    """EQP-CAM-010: connecting switches the INDI device on, enables image delivery, and disconnect reverses it."""
    cam = make(indi.IndiCameraAdapter, server, CCD)
    await cam.connect()
    assert cam.is_connected and CCD in server.connected
    await server_saw(lambda: CCD in server.blob_enabled)
    await cam.disconnect()
    assert not cam.is_connected
    await server_saw(lambda: CCD not in server.connected)


@pytest.mark.requirement("TC-EQP-CAM-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_010_disconnect_leaves_other_clients_device_connected():
    """EQP-CAM-010: a device another client (e.g. Ekos) already connected must stay connected after our disconnect."""
    srv = FakeIndiServer(preconnected=(CCD,))
    try:
        cam = make(indi.IndiCameraAdapter, srv, CCD)
        await cam.connect()
        await cam.disconnect()
        await asyncio.sleep(0.3)  # long enough for a (wrong) DISCONNECT to have arrived
        assert CCD in srv.connected
        assert not any(v.get("DISCONNECT") == "On" for v in commands(srv, CCD, "CONNECTION"))
    finally:
        srv.close()


@pytest.mark.requirement("TC-EQP-CAM-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_010_unknown_device_name_is_rejected(server):
    """EQP-CAM-010: asking for a device the server doesn't have fails with the available names listed."""
    cam = make(indi.IndiCameraAdapter, server, "Nonexistent Camera")
    with pytest.raises(DeviceConnectionError, match="CCD Simulator"):
        await cam.connect()
    assert not cam.is_connected


@pytest.mark.requirement("TC-EQP-CAM-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_010_connect_requires_device_name(server):
    """EQP-CAM-010: connect() without a selected device is an explicit error, not a silent success."""
    cam = indi.IndiCameraAdapter(host="127.0.0.1", port=server.port)
    with pytest.raises(DeviceConnectionError, match="No INDI device selected"):
        await cam.connect()


@pytest.mark.requirement("TC-EXT-030")
@pytest.mark.priority("MVP")
async def test_tc_ext_030_devices_share_one_server_connection(server):
    """EXT-030: adapters for one server share a single TCP connection, closed when the last one disconnects."""
    cam, mount = make(indi.IndiCameraAdapter, server, CCD), make(indi.IndiMountAdapter, server, MOUNT)
    await cam.connect()
    await mount.connect()
    assert len(indi_client._registry) == 1 and cam._client is mount._client
    await cam.disconnect()
    assert mount.is_connected and len(indi_client._registry) == 1
    await mount.disconnect()


# --- camera ----------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-CAM-020")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_020_exposure_downloads_fits_image(server):
    """EQP-CAM-020: an exposure is commanded with its frame settings and returns the decoded FITS pixels."""
    cam = make(indi.IndiCameraAdapter, server, CCD)
    await cam.connect()
    try:
        await cam.start_exposure(duration=2.5, gain=120, binning=2, frame_type="Dark Frame")
        image = await cam.get_image_array()
        assert image.shape == IMAGE.shape and (image == IMAGE).all()

        await sent(server, CCD, "CCD_EXPOSURE", {"CCD_EXPOSURE_VALUE": "2.5"})
        await sent(server, CCD, "CCD_GAIN", {"GAIN": "120"})
        await sent(server, CCD, "CCD_BINNING", {"HOR_BIN": "2", "VER_BIN": "2"})
        await sent(server, CCD, "CCD_FRAME_TYPE", {"FRAME_DARK": "On"}, exact=False)
        # Images must be routed to this client, not saved on the server.
        await sent(server, CCD, "UPLOAD_MODE", {"UPLOAD_CLIENT": "On"}, exact=False)
    finally:
        await cam.disconnect()


@pytest.mark.requirement("TC-EQP-CAM-020")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_020_second_exposure_waits_for_new_image(server):
    """EQP-CAM-020: get_image_array waits for the *new* frame rather than returning the previous one."""
    server.exposure_delay = 0.4
    cam = make(indi.IndiCameraAdapter, server, CCD)
    await cam.connect()
    try:
        await cam.start_exposure(duration=1.0)
        await cam.get_image_array()
        await cam.start_exposure(duration=1.0)
        started = time.monotonic()
        await cam.get_image_array()
        assert time.monotonic() - started >= 0.3
    finally:
        await cam.disconnect()


@pytest.mark.requirement("TC-EQP-CAM-020")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_020_failed_exposure_raises(server):
    """EQP-CAM-020: a driver-reported exposure failure (Alert) raises instead of hanging until timeout."""
    from galileo.exceptions import DeviceError
    cam = make(indi.IndiCameraAdapter, server, CCD)
    await cam.connect()
    try:
        await server_saw(lambda: CCD in server.blob_enabled)
        server.blob_enabled.discard(CCD)  # fake server alerts when the client never enabled BLOBs
        await cam.start_exposure(duration=1.0)
        with pytest.raises(DeviceError, match="exposure failed"):
            await cam.get_image_array()
    finally:
        await cam.disconnect()


@pytest.mark.requirement("TC-EQP-CAM-030")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_030_cooling_sensor_info_and_capabilities(server):
    """EQP-CAM-030: temperature, cooler control, sensor info and capabilities come from the live INDI properties."""
    cam = make(indi.IndiCameraAdapter, server, CCD)
    await cam.connect()
    try:
        assert cam.get_temperature() == 12.5
        await cam.set_temperature(-10.0)
        await sent(server, CCD, "CCD_TEMPERATURE", {"CCD_TEMPERATURE_VALUE": "-10"})
        await sent(server, CCD, "CCD_COOLER", {"COOLER_ON": "On"}, exact=False)

        info = await cam.get_sensor_info()
        assert info == {"pixel_size_um": 4.63, "sensor_width_px": 4144,
                        "sensor_height_px": 2822, "sensor_name": CCD}

        caps = cam.get_capabilities()
        assert caps.has_cooler and caps.can_set_gain and caps.can_bin
        assert (caps.max_bin_x, caps.sensor_width) == (4, 4144)
    finally:
        await cam.disconnect()


@pytest.mark.requirement("TC-EQP-CAM-040")
@pytest.mark.priority("MVP")
async def test_tc_eqp_cam_040_simulator_stays_offline():
    """EQP-CAM-040: the simulator camera works with no INDI server at all."""
    sim = indi.IndiCameraSimulator()
    await sim.connect()
    await sim.start_exposure(duration=1.0)
    assert (await sim.get_image_array()).shape == (1080, 1920)
    assert sim.get_temperature() != sim.get_temperature()  # NaN: no live device
    await sim.disconnect()


# --- mount -----------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-MNT-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_mnt_010_status_slew_park_and_tracking(server):
    """EQP-MNT-010: live status, slew (degrees -> hours), tracking and park map to standard telescope properties."""
    mount = make(indi.IndiMountAdapter, server, MOUNT)
    await mount.connect()
    try:
        status = await mount.get_status()
        assert status["right_ascension"] == 6.5 and status["declination"] == -10.5
        assert status["site_longitude"] == -10.0  # INDI 350°E -> ASCOM-style -10°
        assert status["side_of_pier"] == "West" and status["at_park"] is True
        assert status["tracking"] is False and status["sidereal_time"] == 5.5

        await mount.slew_to_coordinates(ra=180.0, dec=45.0)
        await sent(server, MOUNT, "ON_COORD_SET", {"TRACK": "On"}, exact=False)
        await sent(server, MOUNT, "EQUATORIAL_EOD_COORD", {"RA": "12", "DEC": "45"})

        async def _arrived():
            s = await mount.get_status()
            return s if s["right_ascension"] == 12.0 else None

        assert (await eventually(_arrived))["declination"] == 45.0

        await mount.set_tracking(True)
        await sent(server, MOUNT, "TELESCOPE_TRACK_STATE", {"TRACK_ON": "On", "TRACK_OFF": "Off"})
        await mount.unpark()
        await sent(server, MOUNT, "TELESCOPE_PARK", {"PARK": "Off", "UNPARK": "On"})
        await mount.abort_slew()
        await sent(server, MOUNT, "TELESCOPE_ABORT_MOTION")
    finally:
        await mount.disconnect()


@pytest.mark.requirement("TC-EQP-MNT-020")
@pytest.mark.priority("MVP")
async def test_tc_eqp_mnt_020_jog_direction_and_rate(server):
    """EQP-MNT-020: move_axis picks direction from the rate's sign and a matching INDI slew rate; 0 stops."""
    mount = make(indi.IndiMountAdapter, server, MOUNT)
    await mount.connect()
    try:
        await mount.move_axis(1, 0.5)   # secondary axis, positive = north, fast
        await sent(server, MOUNT, "TELESCOPE_SLEW_RATE", {"SLEW_FIND": "On"}, exact=False)
        await sent(server, MOUNT, "TELESCOPE_MOTION_NS", {"MOTION_NORTH": "On", "MOTION_SOUTH": "Off"})
        await mount.move_axis(1, 0.0)
        await sent(server, MOUNT, "TELESCOPE_MOTION_NS", {"MOTION_NORTH": "Off", "MOTION_SOUTH": "Off"})
        # This fake mount defines no TELESCOPE_MOTION_WE — unsupported ops say so.
        with pytest.raises(DevicePropertyError, match="TELESCOPE_MOTION_WE"):
            await mount.move_axis(0, 0.1)
    finally:
        await mount.disconnect()


# --- filter wheel / focuser --------------------------------------------------

@pytest.mark.requirement("TC-EQP-FW-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_fw_010_names_and_zero_based_position(server):
    """EQP-FW-010: filter names are read on connect; positions are 0-based here but 1-based on the wire."""
    wheel = make(indi.IndiFWAdapter, server, WHEEL)
    await wheel.connect()
    try:
        assert wheel.filter_names == ["L", "R", "Ha"] and wheel.position == 0
        await wheel.move_to(2)  # blocks until the slot change completes
        await sent(server, WHEEL, "FILTER_SLOT", {"FILTER_SLOT_VALUE": "3"})
        status = await wheel.get_status()
        assert status["position"] == 2 and status["filter_names"] == ["L", "R", "Ha"]
    finally:
        await wheel.disconnect()


@pytest.mark.requirement("TC-EQP-FOC-010")
@pytest.mark.priority("MVP")
async def test_tc_eqp_foc_010_absolute_relative_moves_and_limits(server):
    """EQP-FOC-010: absolute/relative moves use the standard properties; travel limits come from the driver."""
    focuser = make(indi.IndiFocuserAdapter, server, FOCUSER)
    await focuser.connect()
    try:
        assert (focuser.position, focuser.max_step, focuser.max_increment) == (5000, 60000, 2000)
        await focuser.move_to(5200)
        await sent(server, FOCUSER, "ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": "5200"})

        async def _moving():
            s = await focuser.get_status()
            return s if s["is_moving"] else None

        status = await eventually(_moving)  # the fake reports Busy briefly, like a real move
        assert status["temperature"] == 8.25 and status["position"] == 5200

        await focuser.move_by(-150)
        await sent(server, FOCUSER, "FOCUS_MOTION", {"FOCUS_INWARD": "On", "FOCUS_OUTWARD": "Off"})
        await sent(server, FOCUSER, "REL_FOCUS_POSITION", {"FOCUS_RELATIVE_POSITION": "150"})
    finally:
        await focuser.disconnect()
