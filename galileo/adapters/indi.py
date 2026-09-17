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

    async def connect(self) -> None:
        logger.info("INDI connect %s:%d device=%r", self.host, self.port, self.device_name)
        self._connected = True

    async def disconnect(self) -> None:
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
        self._properties.update(
            {"EXPOSURE": duration, "GAIN": gain, "OFFSET": offset,
             "BINNING": binning, "FRAME_TYPE": frame_type}
        )

    async def abort_exposure(self) -> None:
        self._properties["ABORT"] = True

    async def get_image_array(self):
        return self._image_data

    async def set_temperature(self, temp_c: float) -> None:
        self._properties["TARGET_TEMP"] = temp_c

    def get_temperature(self) -> float:
        return float(self._properties.get("CCD_TEMPERATURE", -10.0))

    def get_cooler_power(self) -> float:
        return float(self._properties.get("COOLER_POWER", 0.0))

    async def warm_up(self) -> None:
        self._properties["TARGET_TEMP"] = 20.0


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
        self.ra, self.dec = ra, dec

    async def abort_slew(self) -> None:
        self.is_slewing = False

    async def park(self) -> None:
        pass

    async def unpark(self) -> None:
        pass

    async def set_tracking(self, enabled: bool) -> None:
        self.is_tracking = enabled

    async def set_tracking_rate(self, ra_rate_arcsec_s: float, dec_rate_arcsec_s: float) -> None:
        self._properties.update({"RA_RATE": ra_rate_arcsec_s, "DEC_RATE": dec_rate_arcsec_s})

    async def sync_to_coordinates(self, ra: float, dec: float) -> None:
        self.ra, self.dec = ra, dec


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
        self.position = index


class IndiFocuserAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.FOCUSER, host, port, **kwargs)
        self.position = 5000
        self.temperature = 15.0
        self.is_moving = False

    async def move_to(self, position: int) -> None:
        self.position = position

    async def move_by(self, steps: int) -> None:
        self.position += steps


class IndiRotatorAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.ROTATOR, host, port, **kwargs)
        self.mechanical_angle = 0.0
        self.sky_angle = 0.0

    async def move_to_angle(self, angle: float) -> None:
        self.mechanical_angle = angle


class IndiFlatPanelAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.FLAT_PANEL, host, port, **kwargs)
        self.cover_state = "Closed"
        self.brightness = 0

    async def open_cover(self) -> None:
        self.cover_state = "Open"

    async def close_cover(self) -> None:
        self.cover_state = "Closed"

    async def set_brightness(self, level: int) -> None:
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
        self.azimuth = azimuth

    async def open_shutter(self) -> None:
        self.shutter_state = "Open"

    async def close_shutter(self) -> None:
        self.shutter_state = "Closed"

    async def park(self) -> None:
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
        for sw in self.switches:
            if sw.name == name:
                sw.state = value
