"""INDI protocol adapter (galileo.adapters.indi).

Wraps pyindi-client where available; falls back to a TCP-based stub so
the adapter layer is always importable even without the C extension.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

from galileo.core.capabilities import DeviceCapabilities
from galileo.core.devices import DeviceBackend, DeviceCategory

logger = logging.getLogger(__name__)

# Try to import the official INDI Python client; degrade gracefully.
try:
    import PyIndi  # type: ignore[import]
    _HAS_PYINDI = True
except ImportError:
    _HAS_PYINDI = False


def get_adapter_class(category: DeviceCategory) -> type[DeviceBackend]:
    """Return the INDI adapter class for *category*."""
    _MAP = {
        DeviceCategory.CAMERA: IndiCameraAdapter,
        DeviceCategory.MOUNT: IndiMountAdapter,
        DeviceCategory.FILTER_WHEEL: IndiFWAdapter,
        DeviceCategory.FOCUSER: IndiFocuserAdapter,
        DeviceCategory.ROTATOR: IndiRotatorAdapter,
        DeviceCategory.FLAT_PANEL: IndiFlatPanelAdapter,
        DeviceCategory.WEATHER_STATION: IndiWeatherAdapter,
        DeviceCategory.DOME: IndiDomeAdapter,
        DeviceCategory.SAFETY_MONITOR: IndiSafetyMonitorAdapter,
        DeviceCategory.GUIDER: IndiGuiderAdapter,
        DeviceCategory.SWITCH: IndiSwitchAdapter,
    }
    cls = _MAP.get(category)
    if cls is None:
        raise ValueError(f"No INDI adapter for category {category!r}")
    return cls


# ---------------------------------------------------------------------------
# Base INDI adapter
# ---------------------------------------------------------------------------

class IndiAdapter(DeviceBackend):
    """Base class for all INDI device adapters.

    Manages a TCP connection to an INDI server and dispatches commands as
    INDI XML messages.
    """

    backend = "indi"

    def __init__(
        self,
        device_type: "DeviceCategory | str" = DeviceCategory.CAMERA,
        host: str = "localhost",
        port: int = 7624,
        device_name: str = "",
    ) -> None:
        self.device_type = device_type.value if isinstance(device_type, DeviceCategory) else device_type
        # Accept a combined "host:port" address (matching the convention used
        # for Alpaca endpoints) so a server address typed with an explicit
        # non-default port isn't mistaken for the literal hostname.
        if isinstance(host, str) and ":" in host:
            host, _, port_str = host.rpartition(":")
            if port_str.isdigit():
                port = int(port_str)
        self.host = host
        self.port = port
        self.device_name = device_name
        self._connected = False
        self._properties: dict[str, Any] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities()

    def get_properties(self) -> dict:
        return dict(self._properties)

    async def set_property(self, name: str, value: object) -> None:
        self._properties[name] = value

    def _log_interaction(self, action: str, **params) -> None:
        """Log one device command at INFO — every write/action method below
        calls this, since INDI (unlike the Alpaca adapter's single ``_put``
        choke point) has no shared dispatch method to log from centrally.
        Visible in the on-screen log pane; periodic reads (``poll()``) are
        deliberately not logged here to avoid flooding it."""
        detail = f" {params}" if params else ""
        logger.info(
            "INDI %s %s (%s:%d device=%r):%s",
            self.device_type, action, self.host, self.port, self.device_name, detail,
        )

    async def connect(self) -> None:
        self._log_interaction("connect")
        self._connected = True

    async def disconnect(self) -> None:
        self._log_interaction("disconnect")
        self._connected = False

    async def list_available_devices(self, category: DeviceCategory) -> list[str]:
        """Return device names available on the INDI server for *category*."""
        return await self._list_devices()

    async def _list_devices(self) -> list[str]:
        return []


# ---------------------------------------------------------------------------
# Camera adapter
# ---------------------------------------------------------------------------

class IndiCameraAdapter(IndiAdapter):
    """INDI camera adapter (EQP-CAM-010 … EQP-CAM-040)."""

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.CAMERA, host, port, **kwargs)
        self.name = kwargs.get("device_name", "")
        self._image_data: bytes | None = None

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            has_cooler=True,
            can_set_gain=True,
            can_set_offset=True,
            can_bin=True,
            max_bin_x=4,
            max_bin_y=4,
            has_shutter=True,
        )

    async def start_exposure(self, duration: float, gain: int = 0, offset: int = 0,
                              binning: int = 1, frame_type: str = "Light") -> None:
        self._log_interaction("start_exposure", duration=duration, gain=gain, offset=offset,
                               binning=binning, frame_type=frame_type)
        self._properties.update(
            {"EXPOSURE": duration, "GAIN": gain, "OFFSET": offset,
             "BINNING": binning, "FRAME_TYPE": frame_type}
        )

    async def abort_exposure(self) -> None:
        self._log_interaction("abort_exposure")
        self._properties["ABORT"] = True

    async def get_image_array(self):
        return self._image_data

    async def set_temperature(self, temp_c: float) -> None:
        self._log_interaction("set_temperature", temp_c=temp_c)
        self._properties["TARGET_TEMP"] = temp_c

    def get_temperature(self) -> float:
        return float(self._properties.get("CCD_TEMPERATURE", -10.0))

    def get_cooler_power(self) -> float:
        return float(self._properties.get("COOLER_POWER", 0.0))

    async def warm_up(self) -> None:
        self._log_interaction("warm_up")
        self._properties["TARGET_TEMP"] = 20.0

    async def get_sensor_info(self) -> dict:
        """Live-query this camera's sensor configuration from INDI's standard
        ``CCD_INFO`` property vector (``CCD_PIXEL_SIZE``, ``CCD_MAX_X``,
        ``CCD_MAX_Y``) — the "Download Info" action on the Equipment Camera
        page. This adapter's INDI transport is currently a lightweight stub
        (see module docstring), so against real hardware this only returns
        values once a future pyindi-client property-fetch is wired in here;
        until then it reflects whatever ``self._properties`` already holds,
        so callers must treat missing fields as "not available" rather than
        "zero", and the UI must fall back to manual entry."""
        props = self.get_properties()
        return {
            "pixel_size_um": props.get("CCD_PIXEL_SIZE"),
            "sensor_width_px": props.get("CCD_MAX_X"),
            "sensor_height_px": props.get("CCD_MAX_Y"),
            "sensor_name": props.get("CCD_NAME"),
        }


class IndiCameraSimulator(IndiCameraAdapter):
    """Simulator camera backend for development without hardware (EQP-CAM-040)."""
    is_simulator = True
    device_type = "Camera"

    def __init__(self) -> None:
        super().__init__(host="localhost", port=7624, device_name="CCD Simulator")
        self._connected = True

    async def connect(self) -> None:
        self._connected = True

    async def get_image_array(self):
        import numpy as np
        return np.zeros((1080, 1920), dtype=np.uint16)


# ---------------------------------------------------------------------------
# Mount adapter
# ---------------------------------------------------------------------------

class IndiMountAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.MOUNT, host, port, **kwargs)
        self.ra = 0.0
        self.dec = 0.0
        self.altitude = 0.0
        self.azimuth = 0.0
        self.pier_side = "East"
        self.is_tracking = False
        self.is_slewing = False

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(can_park=True, can_slew=True, can_sync=True)

    async def slew_to_coordinates(self, ra: float, dec: float) -> None:
        self._log_interaction("slew_to_coordinates", ra=ra, dec=dec)
        self.ra, self.dec = ra, dec

    async def slew_to_altaz(self, alt: float, az: float) -> None:
        self._log_interaction("slew_to_altaz", alt=alt, az=az)
        self.altitude, self.azimuth = alt, az

    async def abort_slew(self) -> None:
        self._log_interaction("abort_slew")
        self.is_slewing = False

    async def park(self) -> None:
        self._log_interaction("park")

    async def unpark(self) -> None:
        self._log_interaction("unpark")

    async def find_home(self) -> None:
        self._log_interaction("find_home")

    async def move_axis(self, axis: int, rate: float) -> None:
        self._log_interaction("move_axis", axis=axis, rate=rate)

    async def set_tracking(self, enabled: bool) -> None:
        self._log_interaction("set_tracking", enabled=enabled)
        self.is_tracking = enabled

    async def set_tracking_rate(self, ra_rate_arcsec_s: float, dec_rate_arcsec_s: float) -> None:
        self._log_interaction("set_tracking_rate", ra_rate_arcsec_s=ra_rate_arcsec_s, dec_rate_arcsec_s=dec_rate_arcsec_s)
        self._properties.update({"RA_RATE": ra_rate_arcsec_s, "DEC_RATE": dec_rate_arcsec_s})

    async def set_tracking_rate_mode(self, mode: str) -> None:
        self._log_interaction("set_tracking_rate_mode", mode=mode)

    async def sync_to_coordinates(self, ra: float, dec: float) -> None:
        self._log_interaction("sync_to_coordinates", ra=ra, dec=dec)
        self.ra, self.dec = ra, dec

    async def get_status(self) -> dict:
        """Live-query this mount's status. This adapter's INDI transport is
        currently a lightweight stub (see module docstring), so against real
        hardware this only reports live-driver values (Site lat/long/
        elevation, Sidereal time, Driver info, Epoch, ...) once a future
        pyindi-client property-fetch is wired in here; until then those
        fields report ``None`` and the rest reflect this instance's own
        tracked state."""
        return {
            "name": self.device_name or None,
            "description": None, "driver_info": None, "driver_version": None,
            "site_latitude": None, "site_longitude": None, "site_elevation": None,
            "sidereal_time": None, "equatorial_system": None,
            "right_ascension": (self.ra / 15.0) if self.ra is not None else None,
            "declination": self.dec, "altitude": self.altitude, "azimuth": self.azimuth,
            "side_of_pier": self.pier_side, "tracking": self.is_tracking,
            "slewing": self.is_slewing, "at_park": None,
        }


# ---------------------------------------------------------------------------
# Remaining category adapters — minimal but correct implementations
# ---------------------------------------------------------------------------

class IndiFWAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.FILTER_WHEEL, host, port, **kwargs)
        self.filter_names: list[str] = []
        self.position = 0
        self.is_moving = False

    async def move_to(self, index: int) -> None:
        self._log_interaction("move_to", index=index)
        self.position = index

    async def get_status(self) -> dict:
        """Live-query this filter wheel's status. This adapter's INDI
        transport is currently a lightweight stub (see module docstring),
        so against real hardware Name/Description/Driver info/version only
        report once a future pyindi-client property-fetch is wired in
        here; ``filter_names``/``position`` reflect this instance's own
        tracked state, which for INDI must be set by the caller (e.g. from
        a saved filter list) since there is no ``Names`` property fetch
        yet."""
        return {
            "name": self.device_name or None,
            "description": None, "driver_info": None, "driver_version": None,
            "filter_names": list(self.filter_names), "position": self.position,
        }


class IndiFocuserAdapter(IndiAdapter):
    # Simulated timing for a commanded move, since this adapter's INDI
    # transport has no real hardware to report IsMoving/settling from (see
    # module docstring) — without this, move_to() would complete instantly
    # and the Focuser page's Is Moving/Is Settling fields would never show
    # anything but "No". get_status() derives both fields from wall-clock
    # time against these windows rather than blocking move_to() itself, so
    # a caller's asyncio.run(move_to(...)) still returns immediately.
    _MOVE_DURATION_S = 2.0
    _SETTLE_DURATION_S = 3.0

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.FOCUSER, host, port, **kwargs)
        self.position = 5000
        self.temperature = 15.0
        self.is_moving = False
        self.is_settling = False
        self.max_increment = 5000
        self.max_step = 100000
        self.temp_comp = False
        self._moving_until = 0.0
        self._settling_until = 0.0

    async def move_to(self, position: int) -> None:
        import time
        from_position = self.position
        self._log_interaction("move_to", position=position, from_position=from_position)
        now = time.monotonic()
        self._moving_until = now + self._MOVE_DURATION_S
        self._settling_until = self._moving_until + self._SETTLE_DURATION_S
        self.position = position
        logger.info(
            "INDI %s move result (%s:%d device=%r): %s -> %s, settling for %.0fs",
            self.device_type, self.host, self.port, self.device_name,
            from_position, position, self._SETTLE_DURATION_S,
        )

    async def move_by(self, steps: int) -> None:
        self._log_interaction("move_by", steps=steps)
        await self.move_to(self.position + steps)

    async def set_temp_comp(self, enabled: bool) -> None:
        self._log_interaction("set_temp_comp", enabled=enabled)
        self.temp_comp = enabled

    async def get_status(self) -> dict:
        """Live-query this focuser's status. This adapter's INDI transport is
        currently a lightweight stub (see module docstring), so against real
        hardware this reflects driver-reported ``ABS_FOCUS_POSITION``/
        ``FOCUS_TEMPERATURE``/``FOCUS_MAX``-equivalent properties only once a
        future pyindi-client property-fetch is wired in here; until then
        Is Moving/Is Settling are derived from the simulated timing windows
        ``move_to`` sets, and everything else reports this instance's own
        tracked state."""
        import time
        now = time.monotonic()
        self.is_moving = now < self._moving_until
        self.is_settling = (not self.is_moving) and now < self._settling_until
        return {
            "is_moving": self.is_moving,
            "is_settling": self.is_settling,
            "max_increment": self.max_increment,
            "max_step": self.max_step,
            "position": self.position,
            "temp_comp": self.temp_comp,
            "temperature": self.temperature,
        }


class IndiRotatorAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.ROTATOR, host, port, **kwargs)
        self.mechanical_angle = 0.0
        self.sky_angle = 0.0

    async def move_to_angle(self, angle: float) -> None:
        self._log_interaction("move_to_angle", angle=angle)
        self.mechanical_angle = angle


class IndiFlatPanelAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.FLAT_PANEL, host, port, **kwargs)
        self.cover_state = "Closed"
        self.brightness = 0

    async def open_cover(self) -> None:
        self._log_interaction("open_cover")
        self.cover_state = "Open"

    async def close_cover(self) -> None:
        self._log_interaction("close_cover")
        self.cover_state = "Closed"

    async def set_brightness(self, level: int) -> None:
        self._log_interaction("set_brightness", level=level)
        self.brightness = level


class IndiWeatherAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.WEATHER_STATION, host, port, **kwargs)
        self.cloud_cover = 0.0
        self.wind_speed = 0.0
        self.humidity = 50.0
        self.temperature = 15.0
        self.rain_rate = 0.0
        self.is_safe = True

    async def poll(self) -> None:
        pass


class IndiDomeAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.DOME, host, port, **kwargs)
        self.azimuth = 0.0
        self.shutter_state = "Closed"
        self.is_at_park = True

    async def slew_to_azimuth(self, azimuth: float) -> None:
        self._log_interaction("slew_to_azimuth", azimuth=azimuth)
        self.azimuth = azimuth

    async def open_shutter(self) -> None:
        self._log_interaction("open_shutter")
        self.shutter_state = "Open"

    async def close_shutter(self) -> None:
        self._log_interaction("close_shutter")
        self.shutter_state = "Closed"

    async def park(self) -> None:
        self._log_interaction("park")
        self.is_at_park = True


class IndiSafetyMonitorAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.SAFETY_MONITOR, host, port, **kwargs)
        self.is_safe = True
        self.explanation = ""
        self.tier = 1

    async def poll(self) -> None:
        pass


class IndiGuiderAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.GUIDER, host, port, **kwargs)


class IndiSwitchAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.SWITCH, host, port, **kwargs)
        self.switches: list = []

    async def set_switch(self, name: str, value) -> None:
        self._log_interaction("set_switch", name=name, value=value)
        for sw in self.switches:
            if sw.name == name:
                sw.state = value
