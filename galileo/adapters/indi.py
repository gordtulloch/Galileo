"""INDI protocol adapter (galileo.adapters.indi).

Talks to an INDI server through the native protocol client in
:mod:`galileo.adapters.indi_client` (XML over TCP, no C extension, so it also
works on Windows where ``pyindi-client`` cannot be built). Each adapter
targets one named INDI device on a server and translates Galileo's device
port methods into that device's standard INDI properties
(``CCD_EXPOSURE``, ``EQUATORIAL_EOD_COORD``, ``ABS_FOCUS_POSITION``, ...).
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

from galileo.adapters import indi_client as ic
from galileo.core.capabilities import DeviceCapabilities
from galileo.core.devices import DeviceBackend, DeviceCategory
from galileo.exceptions import DeviceConnectionError, DeviceError, DevicePropertyError

logger = logging.getLogger(__name__)

# INDI has no per-category "device type" query: a server's devices are
# classified by the ``DRIVER_INTERFACE`` bit mask in each one's DRIVER_INFO.
# SAFETY_MONITOR has no INDI interface at all, so nothing is ever listed for it.
_INTERFACE_MASK: dict[DeviceCategory, int] = {
    DeviceCategory.CAMERA: ic.INTERFACE_CCD,
    DeviceCategory.MOUNT: ic.INTERFACE_TELESCOPE,
    DeviceCategory.FILTER_WHEEL: ic.INTERFACE_FILTER,
    DeviceCategory.FOCUSER: ic.INTERFACE_FOCUSER,
    DeviceCategory.ROTATOR: ic.INTERFACE_ROTATOR,
    DeviceCategory.GUIDER: ic.INTERFACE_GUIDER,
    DeviceCategory.DOME: ic.INTERFACE_DOME,
    DeviceCategory.WEATHER_STATION: ic.INTERFACE_WEATHER,
    DeviceCategory.FLAT_PANEL: ic.INTERFACE_DUSTCAP | ic.INTERFACE_LIGHTBOX,
    DeviceCategory.SWITCH: ic.INTERFACE_POWER | ic.INTERFACE_OUTPUT | ic.INTERFACE_AUX,
}


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
    """Base class for all INDI device adapters: owns the (shared) server
    connection, connects/disconnects the named INDI device, and provides
    typed property read/write helpers for the category subclasses."""

    backend = "indi"

    # How long to wait for a real device (USB camera, mount handshake, ...)
    # to finish its CONNECT.
    CONNECT_TIMEOUT_S = 45.0

    def __init__(
        self,
        device_type: "DeviceCategory | str" = DeviceCategory.CAMERA,
        host: str = "localhost",
        port: int = 7624,
        device_name: str = "",
    ) -> None:
        self.device_type = device_type.value if isinstance(device_type, DeviceCategory) else device_type
        self._category = device_type if isinstance(device_type, DeviceCategory) else None
        # Accept a combined "host:port" address (matching the convention used
        # for Alpaca endpoints) so a server address typed with an explicit
        # non-default port isn't mistaken for the literal hostname.
        if isinstance(host, str) and ":" in host:
            host, _, port_str = host.rpartition(":")
            if port_str.isdigit():
                port = int(port_str)
        self.host = host
        self.port = port
        self.device_name = device_name or ""
        self.name = self.device_name
        self._connected = False
        self._properties: dict[str, Any] = {}
        self._client: ic.IndiClient | None = None
        # Whether *we* switched the INDI device on — if another client (Ekos,
        # KStars) already had it connected, disconnect() must leave it alone.
        self._we_connected_device = False

    @property
    def is_connected(self) -> bool:
        return self._connected and (self._client is None or self._client.alive)

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities()

    def get_properties(self) -> dict:
        props = dict(self._properties)
        if self._client is not None and self.device_name:
            props.update(self._client.device_snapshot(self.device_name))
        return props

    async def set_property(self, name: str, value: object) -> None:
        self._properties[name] = value

    def _log_interaction(self, action: str, **params) -> None:
        """Log one device command at INFO — every write/action method below
        calls this, since INDI (unlike the Alpaca adapter's single ``_put``
        choke point) has no shared dispatch method to log from centrally.
        Visible in the on-screen log pane; periodic reads (``get_status()``)
        are deliberately not logged here to avoid flooding it."""
        detail = f" {params}" if params else ""
        logger.info(
            "INDI %s %s (%s:%d device=%r):%s",
            self.device_type, action, self.host, self.port, self.device_name, detail,
        )

    # -- connection --------------------------------------------------------

    async def connect(self) -> None:
        self._log_interaction("connect")
        if not self.device_name:
            raise DeviceConnectionError("No INDI device selected — scan the server and pick a device first.")
        await asyncio.to_thread(self._connect_sync)
        self._log_available_properties()
        await asyncio.to_thread(self._on_connected)

    def _log_available_properties(self) -> None:
        """Log every property the driver defines, at DEBUG, so what a given
        device actually supports (vs. what Galileo's adapter expects) can be
        diagnosed from the log without a separate INDI client."""
        if not logger.isEnabledFor(logging.DEBUG) or self._client is None:
            return
        props = self._client.device_properties(self.device_name)
        logger.debug(
            "INDI %s %r (%s:%d) exposes %d properties:",
            self.device_type, self.device_name, self.host, self.port, len(props),
        )
        for p in props:
            elements = ", ".join(p.elements) or "-"
            logger.debug(
                "INDI %r property %s/%s [%s %s state=%s]: %s",
                self.device_name, p.group or "-", p.name, p.kind, p.perm, p.state, elements,
            )

    def _connect_sync(self) -> None:
        client = ic.acquire_client(self.host, self.port)
        try:
            if self.device_name not in client.device_names():
                raise DeviceConnectionError(
                    f"INDI server {self.host}:{self.port} has no device named {self.device_name!r} "
                    f"(available: {', '.join(client.device_names()) or 'none'})."
                )
            client.wait_property(self.device_name, "CONNECTION", 10.0)
            if not client.get_switch(self.device_name, "CONNECTION", "CONNECT"):
                client.send_switch(self.device_name, "CONNECTION", {"CONNECT": True, "DISCONNECT": False})
                self._we_connected_device = True
                client.wait_for(
                    lambda: client.get_state(self.device_name, "CONNECTION") in (ic.OK, ic.ALERT),
                    self.CONNECT_TIMEOUT_S, f"{self.device_name} to connect",
                )
                if not client.get_switch(self.device_name, "CONNECTION", "CONNECT"):
                    last = client.messages[-1] if client.messages else "no message from driver"
                    raise DeviceConnectionError(f"INDI device {self.device_name!r} failed to connect: {last}")
            # Drivers define most of their properties only once connected, and
            # do so *after* reporting CONNECT — wait for that burst to finish.
            client.wait_settled(quiet=0.6, timeout=8.0, restart=True)
        except BaseException:
            ic.release_client(client)
            self._we_connected_device = False
            raise
        self._client = client
        self._connected = True

    def _on_connected(self) -> None:
        """Category hook run right after the device connects."""

    async def disconnect(self) -> None:
        self._log_interaction("disconnect")
        client, self._client = self._client, None
        self._connected = False
        if client is None:
            return
        try:
            if self._we_connected_device and client.alive:
                client.send_switch(self.device_name, "CONNECTION", {"CONNECT": False, "DISCONNECT": True})
        finally:
            self._we_connected_device = False
            ic.release_client(client)

    # -- discovery ---------------------------------------------------------

    async def list_available_devices(self, category: DeviceCategory) -> list[str]:
        """Return device names available on the INDI server for *category*."""
        return await self._list_devices(category)

    async def _list_devices(self, category: "DeviceCategory | None" = None) -> list[str]:
        category = category if isinstance(category, DeviceCategory) else self._category
        mask = _INTERFACE_MASK.get(category, 0)
        if not mask:
            return []
        return await asyncio.to_thread(self._list_devices_sync, mask)

    def _list_devices_sync(self, mask: int) -> list[str]:
        client = ic.acquire_client(self.host, self.port)
        try:
            return [d for d in client.device_names() if client.device_interface(d) & mask]
        finally:
            ic.release_client(client)

    # -- property helpers (all no-ops / None when not connected) -----------

    def _c(self) -> ic.IndiClient:
        if self._client is None or not self._client.alive:
            raise DeviceConnectionError(f"INDI {self.device_type} {self.device_name!r} is not connected.")
        return self._client

    def _has(self, prop: str) -> bool:
        return self._client is not None and self._client.get_property(self.device_name, prop) is not None

    def _num(self, prop: str, element: str) -> float | None:
        return self._client.get_number(self.device_name, prop, element) if self._client else None

    def _txt(self, prop: str, element: str) -> str | None:
        return self._client.get_text(self.device_name, prop, element) if self._client else None

    def _sw(self, prop: str, element: str) -> bool | None:
        return self._client.get_switch(self.device_name, prop, element) if self._client else None

    def _state(self, prop: str) -> str | None:
        return self._client.get_state(self.device_name, prop) if self._client else None

    def _require(self, prop: str) -> ic.IndiProperty:
        found = self._c().get_property(self.device_name, prop)
        if found is None:
            raise DevicePropertyError(
                f"INDI device {self.device_name!r} has no {prop!r} property — "
                f"its driver doesn't support this operation."
            )
        return found

    def _set_num(self, prop: str, values: dict[str, float]) -> None:
        self._require(prop)
        self._c().send_number(self.device_name, prop, values)

    def _set_sw(self, prop: str, values: dict[str, bool]) -> None:
        self._require(prop)
        self._c().send_switch(self.device_name, prop, values)

    def _select(self, prop: str, element: str) -> None:
        """Turn *element* On in a one-of-many switch vector (others go Off)."""
        found = self._require(prop)
        self._c().send_switch(self.device_name, prop, {n: n == element for n in found.elements})

    def _driver_info(self) -> dict[str, "str | None"]:
        return {
            "name": self.device_name or None,
            "description": self._txt("DRIVER_INFO", "DRIVER_EXEC"),
            "driver_info": self._txt("DRIVER_INFO", "DRIVER_NAME"),
            "driver_version": self._txt("DRIVER_INFO", "DRIVER_VERSION"),
        }

    async def _wait_not_busy(self, prop: str, timeout: float, what: str) -> None:
        """Wait for a commanded operation (property state Busy) to finish."""
        client = self._c()
        await asyncio.to_thread(
            client.wait_for,
            lambda: (p := client.get_property(self.device_name, prop)) is None or p.state != ic.BUSY,
            timeout, what,
        )
        if client.get_state(self.device_name, prop) == ic.ALERT:
            last = client.messages[-1] if client.messages else "no message from driver"
            raise DeviceError(f"INDI {self.device_name!r} {what} failed: {last}")


# ---------------------------------------------------------------------------
# Camera adapter
# ---------------------------------------------------------------------------

class IndiCameraAdapter(IndiAdapter):
    """INDI camera adapter (EQP-CAM-010 … EQP-CAM-040), for drivers exposing
    the standard ``INDI::CCD`` properties."""

    _FRAME_TYPES = (("dark", "FRAME_DARK"), ("bias", "FRAME_BIAS"), ("flat", "FRAME_FLAT"))

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.CAMERA, host, port, **kwargs)
        self._image_data = None
        self._blob_seq0 = 0
        self._exposure_s = 0.0

    def _on_connected(self) -> None:
        # Without this the server never sends this client the image BLOB.
        self._c().enable_blob(self.device_name, "Also")

    def get_capabilities(self) -> DeviceCapabilities:
        if self._client is None:
            return DeviceCapabilities()
        binning = self._client.get_property(self.device_name, "CCD_BINNING")
        max_bin = lambda el: int(binning.elements[el].max or 1) if binning and el in binning.elements else 1
        return DeviceCapabilities(
            has_cooler=self._has("CCD_TEMPERATURE"),
            can_set_gain=self._has("CCD_GAIN") or self._sw_or_num_gain() is not None,
            can_set_offset=self._has("CCD_OFFSET"),
            can_bin=binning is not None and binning.perm != "ro",
            max_bin_x=max_bin("HOR_BIN"),
            max_bin_y=max_bin("VER_BIN"),
            has_shutter=self._has("CCD_FRAME_TYPE"),
            sensor_width=int(self._num("CCD_INFO", "CCD_MAX_X") or 0),
            sensor_height=int(self._num("CCD_INFO", "CCD_MAX_Y") or 0),
            pixel_size_x=self._num("CCD_INFO", "CCD_PIXEL_SIZE_X") or self._num("CCD_INFO", "CCD_PIXEL_SIZE") or 0.0,
            pixel_size_y=self._num("CCD_INFO", "CCD_PIXEL_SIZE_Y") or self._num("CCD_INFO", "CCD_PIXEL_SIZE") or 0.0,
        )

    def _sw_or_num_gain(self) -> "float | None":
        # Older drivers expose gain through the generic CCD_CONTROLS vector.
        return self._num("CCD_CONTROLS", "Gain")

    def _frame_type_element(self, frame_type: str) -> str:
        lowered = frame_type.lower()
        for needle, element in self._FRAME_TYPES:
            if needle in lowered:
                return element
        return "FRAME_LIGHT"

    def _prepare_transfer(self) -> None:
        """Make sure the finished frame is delivered to *this* client as an
        uncompressed FITS, not saved on the server or sent in a native raw
        format Galileo can't read."""
        client = self._c()
        for prop, wanted in (("UPLOAD_MODE", "UPLOAD_CLIENT"), ("CCD_TRANSFER_FORMAT", "FORMAT_FITS"),
                             ("CCD_COMPRESSION", "CCD_RAW")):
            found = client.get_property(self.device_name, prop)
            if found is not None and not found.value(wanted) and wanted in found.elements:
                self._select(prop, wanted)

    async def start_exposure(self, duration: float, gain: int = 0, offset: int = 0,
                              binning: int = 1, frame_type: str = "Light") -> None:
        self._log_interaction("start_exposure", duration=duration, gain=gain, offset=offset,
                               binning=binning, frame_type=frame_type)
        self._require("CCD_EXPOSURE")
        self._prepare_transfer()
        # gain/offset default to 0 meaning "leave as configured" — a camera's
        # real gain is usually set by the user on the driver, and 0 is also
        # the signature's default, so only an explicit nonzero value is applied.
        if gain:
            if self._has("CCD_GAIN"):
                self._set_num("CCD_GAIN", {"GAIN": gain})
            elif self._sw_or_num_gain() is not None:
                self._set_num("CCD_CONTROLS", {"Gain": gain})
        if offset and self._has("CCD_OFFSET"):
            self._set_num("CCD_OFFSET", {"OFFSET": offset})
        if self._has("CCD_BINNING") and self._num("CCD_BINNING", "HOR_BIN") != binning:
            self._set_num("CCD_BINNING", {"HOR_BIN": binning, "VER_BIN": binning})
        if self._has("CCD_FRAME_TYPE"):
            self._select("CCD_FRAME_TYPE", self._frame_type_element(frame_type))
        self._exposure_s = float(duration)
        self._blob_seq0 = self._c().blob_seq(self.device_name, "CCD1")
        self._c().send_number(self.device_name, "CCD_EXPOSURE", {"CCD_EXPOSURE_VALUE": duration})

    async def abort_exposure(self) -> None:
        self._log_interaction("abort_exposure")
        self._set_sw("CCD_ABORT_EXPOSURE", {"ABORT": True})

    async def get_image_array(self):
        """Wait for the exposure started by :meth:`start_exposure` to finish
        downloading, and return it as a numpy array (FITS is the only
        transfer format Galileo works with)."""
        client = self._c()
        name = self.device_name

        def _ready() -> bool:
            return (client.blob_seq(name, "CCD1") > self._blob_seq0
                    or client.get_state(name, "CCD_EXPOSURE") == ic.ALERT)

        # Exposure time plus generous margin for readout and a slow Wi-Fi download.
        await asyncio.to_thread(client.wait_for, _ready, self._exposure_s + 90.0, "the exposure to download")
        if client.blob_seq(name, "CCD1") <= self._blob_seq0:
            last = client.messages[-1] if client.messages else "no message from driver"
            raise DeviceError(f"INDI camera {name!r} exposure failed: {last}")
        blob = client.latest_blob(name, "CCD1")
        if blob is None:
            raise DeviceError(f"INDI camera {name!r} reported an image but sent no data.")
        self._image_data = await asyncio.to_thread(self._decode_fits, *blob)
        return self._image_data

    @staticmethod
    def _decode_fits(data: bytes, fmt: str):
        if "fit" not in fmt.lower():
            raise DevicePropertyError(
                f"INDI camera sent an image in unsupported format {fmt!r}; Galileo needs FITS "
                "(set the driver's transfer format to FITS)."
            )
        import io
        from astropy.io import fits
        with fits.open(io.BytesIO(data), memmap=False) as hdul:
            return hdul[0].data.copy()

    async def set_temperature(self, temp_c: float) -> None:
        self._log_interaction("set_temperature", temp_c=temp_c)
        self._set_num("CCD_TEMPERATURE", {"CCD_TEMPERATURE_VALUE": temp_c})
        if self._has("CCD_COOLER") and not self._sw("CCD_COOLER", "COOLER_ON"):
            self._set_sw("CCD_COOLER", {"COOLER_ON": True, "COOLER_OFF": False})

    def get_temperature(self) -> float:
        """Sensor temperature in °C, or NaN if the driver reports none."""
        value = self._num("CCD_TEMPERATURE", "CCD_TEMPERATURE_VALUE")
        return float("nan") if value is None else value

    def get_cooler_power(self) -> float:
        return self._num("CCD_COOLER_POWER", "CCD_COOLER_VALUE") or 0.0

    async def warm_up(self) -> None:
        self._log_interaction("warm_up")
        self._set_sw("CCD_COOLER", {"COOLER_ON": False, "COOLER_OFF": True})

    async def get_sensor_info(self) -> dict:
        """Live-query this camera's sensor configuration from INDI's standard
        ``CCD_INFO`` property vector — the "Download Info" action on the
        Equipment Camera page. INDI has no separate sensor-model property, so
        ``sensor_name`` is the INDI device name, which drivers normally set to
        the camera model."""
        pixel = self._num("CCD_INFO", "CCD_PIXEL_SIZE") or self._num("CCD_INFO", "CCD_PIXEL_SIZE_X")
        width, height = self._num("CCD_INFO", "CCD_MAX_X"), self._num("CCD_INFO", "CCD_MAX_Y")
        return {
            "pixel_size_um": pixel,
            "sensor_width_px": int(width) if width else None,
            "sensor_height_px": int(height) if height else None,
            "sensor_name": self.device_name or None,
        }


class IndiCameraSimulator(IndiCameraAdapter):
    """Simulator camera backend for development without hardware (EQP-CAM-040).
    Fully offline — never opens a connection to an INDI server."""
    is_simulator = True
    device_type = "Camera"

    def __init__(self) -> None:
        super().__init__(host="localhost", port=7624, device_name="CCD Simulator")
        self._connected = True

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def start_exposure(self, *args, **kwargs) -> None:
        pass

    async def abort_exposure(self) -> None:
        pass

    async def get_image_array(self):
        import numpy as np
        return np.zeros((1080, 1920), dtype=np.uint16)


# ---------------------------------------------------------------------------
# Mount adapter
# ---------------------------------------------------------------------------

class IndiMountAdapter(IndiAdapter):
    """INDI telescope adapter (``INDI::Telescope`` standard properties).
    Coordinates are the mount's ``EQUATORIAL_EOD_COORD`` (JNow), matching
    what the Alpaca adapter hands to ASCOM."""

    # Galileo's names -> INDI TELESCOPE_TRACK_MODE elements.
    _TRACK_MODES = {"Sidereal": "TRACK_SIDEREAL", "Lunar": "TRACK_LUNAR",
                    "Solar": "TRACK_SOLAR", "King": "TRACK_KING"}
    # Speeds for jogging, slowest first: (max deg/s, INDI TELESCOPE_SLEW_RATE element).
    _SLEW_RATES = ((0.02, "SLEW_GUIDE"), (0.2, "SLEW_CENTERING"), (2.0, "SLEW_FIND"), (math.inf, "SLEW_MAX"))

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
        if self._client is None:
            return DeviceCapabilities(can_park=True, can_slew=True, can_sync=True)
        return DeviceCapabilities(
            can_park=self._has("TELESCOPE_PARK"),
            can_slew=self._has("EQUATORIAL_EOD_COORD") or self._has("HORIZONTAL_COORD"),
            can_sync=self._has("ON_COORD_SET"),
            can_track_non_sidereal=self._has("TELESCOPE_TRACK_RATE"),
        )

    async def slew_to_coordinates(self, ra: float, dec: float) -> None:
        self._log_interaction("slew_to_coordinates", ra=ra, dec=dec)
        self._select("ON_COORD_SET", "TRACK")
        self._set_num("EQUATORIAL_EOD_COORD", {"RA": ra / 15.0, "DEC": dec})
        self.ra, self.dec = ra, dec

    async def slew_to_altaz(self, alt: float, az: float) -> None:
        self._log_interaction("slew_to_altaz", alt=alt, az=az)
        self._set_num("HORIZONTAL_COORD", {"ALT": alt, "AZ": az})
        self.altitude, self.azimuth = alt, az

    async def abort_slew(self) -> None:
        self._log_interaction("abort_slew")
        self._set_sw("TELESCOPE_ABORT_MOTION", {"ABORT": True})

    async def park(self) -> None:
        self._log_interaction("park")
        self._set_sw("TELESCOPE_PARK", {"PARK": True, "UNPARK": False})

    async def unpark(self) -> None:
        self._log_interaction("unpark")
        self._set_sw("TELESCOPE_PARK", {"PARK": False, "UNPARK": True})

    async def find_home(self) -> None:
        self._log_interaction("find_home")
        self._select("TELESCOPE_HOME", "FIND")

    async def move_axis(self, axis: int, rate: float) -> None:
        """Continuous jog, same contract as the Alpaca adapter's ``MoveAxis``:
        axis 0 is RA (positive = east), axis 1 is Dec (positive = north),
        ``rate`` in deg/s, ``0`` stops that axis. INDI drives jogging with
        direction switches plus a discrete slew-rate selector, so the
        requested speed is snapped to the nearest slower standard rate."""
        self._log_interaction("move_axis", axis=axis, rate=rate)
        if axis == 0:
            prop, positive, negative = "TELESCOPE_MOTION_WE", "MOTION_EAST", "MOTION_WEST"
        else:
            prop, positive, negative = "TELESCOPE_MOTION_NS", "MOTION_NORTH", "MOTION_SOUTH"
        if rate and self._has("TELESCOPE_SLEW_RATE"):
            speed = next(el for limit, el in self._SLEW_RATES if abs(rate) <= limit)
            if speed in self._require("TELESCOPE_SLEW_RATE").elements:
                self._select("TELESCOPE_SLEW_RATE", speed)
        self._set_sw(prop, {positive: rate > 0, negative: rate < 0})

    async def set_tracking(self, enabled: bool) -> None:
        self._log_interaction("set_tracking", enabled=enabled)
        self._set_sw("TELESCOPE_TRACK_STATE", {"TRACK_ON": enabled, "TRACK_OFF": not enabled})
        self.is_tracking = enabled

    async def set_tracking_rate(self, ra_rate_arcsec_s: float, dec_rate_arcsec_s: float) -> None:
        self._log_interaction("set_tracking_rate", ra_rate_arcsec_s=ra_rate_arcsec_s, dec_rate_arcsec_s=dec_rate_arcsec_s)
        self._select("TELESCOPE_TRACK_MODE", "TRACK_CUSTOM")
        self._set_num("TELESCOPE_TRACK_RATE", {"TRACK_RATE_RA": ra_rate_arcsec_s, "TRACK_RATE_DE": dec_rate_arcsec_s})
        self._properties.update({"RA_RATE": ra_rate_arcsec_s, "DEC_RATE": dec_rate_arcsec_s})

    async def set_tracking_rate_mode(self, mode: str) -> None:
        self._log_interaction("set_tracking_rate_mode", mode=mode)
        self._select("TELESCOPE_TRACK_MODE", self._TRACK_MODES.get(mode, "TRACK_SIDEREAL"))

    async def sync_to_coordinates(self, ra: float, dec: float) -> None:
        self._log_interaction("sync_to_coordinates", ra=ra, dec=dec)
        self._select("ON_COORD_SET", "SYNC")
        self._set_num("EQUATORIAL_EOD_COORD", {"RA": ra / 15.0, "DEC": dec})
        self.ra, self.dec = ra, dec

    async def get_status(self) -> dict:
        """Live status from the standard ``INDI::Telescope`` properties. A
        property the driver doesn't define reports ``None`` (the UI treats
        that as "not available")."""
        longitude = self._num("GEOGRAPHIC_COORD", "LONG")
        if longitude is not None and longitude > 180.0:
            longitude -= 360.0  # INDI reports 0..360° east; ASCOM/UI use -180..180
        side = "PIER_WEST" if self._sw("TELESCOPE_PIER_SIDE", "PIER_WEST") else (
            "PIER_EAST" if self._sw("TELESCOPE_PIER_SIDE", "PIER_EAST") else None)
        status: dict[str, Any] = {
            **self._driver_info(),
            "site_latitude": self._num("GEOGRAPHIC_COORD", "LAT"),
            "site_longitude": longitude,
            "site_elevation": self._num("GEOGRAPHIC_COORD", "ELEV"),
            "sidereal_time": self._num("TIME_LST", "LST"),
            "equatorial_system": "JNOW" if self._has("EQUATORIAL_EOD_COORD") else None,
            "right_ascension": self._num("EQUATORIAL_EOD_COORD", "RA"),
            "declination": self._num("EQUATORIAL_EOD_COORD", "DEC"),
            "altitude": self._num("HORIZONTAL_COORD", "ALT"),
            "azimuth": self._num("HORIZONTAL_COORD", "AZ"),
            "side_of_pier": {"PIER_WEST": "West", "PIER_EAST": "East"}.get(side) if side else None,
            "tracking": self._sw("TELESCOPE_TRACK_STATE", "TRACK_ON"),
            "slewing": (self._state("EQUATORIAL_EOD_COORD") == ic.BUSY) if self._has("EQUATORIAL_EOD_COORD") else None,
            "at_park": self._sw("TELESCOPE_PARK", "PARK"),
        }
        if status["right_ascension"] is not None:
            self.ra = status["right_ascension"] * 15.0
        if status["declination"] is not None:
            self.dec = status["declination"]
        if status["altitude"] is not None:
            self.altitude = status["altitude"]
        if status["azimuth"] is not None:
            self.azimuth = status["azimuth"]
        if status["side_of_pier"] is not None:
            self.pier_side = status["side_of_pier"]
        if status["tracking"] is not None:
            self.is_tracking = status["tracking"]
        if status["slewing"] is not None:
            self.is_slewing = status["slewing"]
        return status


# ---------------------------------------------------------------------------
# Remaining category adapters
# ---------------------------------------------------------------------------

class IndiFWAdapter(IndiAdapter):
    """Filter wheel via ``INDI::FilterWheel`` (``FILTER_SLOT`` is 1-based on
    the wire; this adapter's ``position`` is 0-based like the Alpaca one)."""

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.FILTER_WHEEL, host, port, **kwargs)
        self.filter_names: list[str] = []
        self.position = 0
        self.is_moving = False

    def _on_connected(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        names = self._client.find_property(self.device_name, lambda p: p.name == "FILTER_NAME") if self._client else None
        if names is not None:
            self.filter_names = [str(el.value) for el in names.elements.values()]
        slot = self._num("FILTER_SLOT", "FILTER_SLOT_VALUE")
        if slot is not None:
            self.position = int(slot) - 1

    async def move_to(self, index: int) -> None:
        self._log_interaction("move_to", index=index)
        self._set_num("FILTER_SLOT", {"FILTER_SLOT_VALUE": index + 1})
        self.position = index
        await self._wait_not_busy("FILTER_SLOT", 60.0, "filter change")

    async def get_status(self) -> dict:
        self._refresh()
        self.is_moving = self._state("FILTER_SLOT") == ic.BUSY
        return {**self._driver_info(), "filter_names": list(self.filter_names), "position": self.position}


class IndiFocuserAdapter(IndiAdapter):
    """Focuser via ``INDI::Focuser``: absolute moves use ``ABS_FOCUS_POSITION``;
    relative-only drivers use ``REL_FOCUS_POSITION`` + ``FOCUS_MOTION``."""

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.FOCUSER, host, port, **kwargs)
        self.position = 0
        self.temperature = 15.0
        self.is_moving = False
        self.is_settling = False
        self.max_increment: "int | None" = None
        self.max_step: "int | None" = None
        self.absolute: "bool | None" = None
        self.temp_comp = False

    def _on_connected(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self.absolute = self._has("ABS_FOCUS_POSITION")
        absolute = self._client.get_property(self.device_name, "ABS_FOCUS_POSITION") if self._client else None
        relative = self._client.get_property(self.device_name, "REL_FOCUS_POSITION") if self._client else None
        if absolute is not None:
            el = absolute.elements.get("FOCUS_ABSOLUTE_POSITION")
            if el is not None:
                if el.value is not None:
                    self.position = int(el.value)
                if el.max is not None:
                    self.max_step = int(el.max)
        if relative is not None:
            el = relative.elements.get("FOCUS_RELATIVE_POSITION")
            if el is not None and el.max is not None:
                self.max_increment = int(el.max)
        temp = self._num("FOCUS_TEMPERATURE", "TEMPERATURE")
        if temp is not None:
            self.temperature = temp

    def _temp_comp_property(self) -> "ic.IndiProperty | None":
        # INDI has no standard temperature-compensation property; drivers that
        # support it (MoonLite, Pegasus, ...) each name it differently.
        return self._client.find_property(
            self.device_name, lambda p: p.kind == "switch" and "COMPENS" in p.name.upper(),
        ) if self._client else None

    async def move_to(self, position: int) -> None:
        self._log_interaction("move_to", position=position, from_position=self.position)
        if self._has("ABS_FOCUS_POSITION"):
            self._set_num("ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": position})
        else:
            await self.move_by(position - self.position)
            return
        self.position = position

    async def move_by(self, steps: int) -> None:
        self._log_interaction("move_by", steps=steps)
        if self._has("REL_FOCUS_POSITION"):
            self._select("FOCUS_MOTION", "FOCUS_OUTWARD" if steps >= 0 else "FOCUS_INWARD")
            self._set_num("REL_FOCUS_POSITION", {"FOCUS_RELATIVE_POSITION": abs(steps)})
            self.position += steps
        else:
            await self.move_to(self.position + steps)

    async def set_temp_comp(self, enabled: bool) -> None:
        self._log_interaction("set_temp_comp", enabled=enabled)
        prop = self._temp_comp_property()
        if prop is None:
            raise DevicePropertyError(
                f"INDI focuser {self.device_name!r} has no temperature-compensation switch."
            )
        on = next((n for n in prop.elements if "ENABLE" in n.upper() or n.upper().endswith("_ON")), None)
        off = next((n for n in prop.elements if "DISABLE" in n.upper() or n.upper().endswith("_OFF")), None)
        if on is None:
            raise DevicePropertyError(f"Cannot interpret INDI switch {prop.name!r} as temperature compensation.")
        values = {on: enabled}
        if off is not None:
            values[off] = not enabled
        self._c().send_switch(self.device_name, prop.name, values)
        self.temp_comp = enabled

    async def get_status(self) -> dict:
        self._refresh()
        busy = ic.BUSY in (self._state("ABS_FOCUS_POSITION"), self._state("REL_FOCUS_POSITION"))
        self.is_moving = busy
        comp = self._temp_comp_property()
        if comp is not None:
            self.temp_comp = any(el.value for n, el in comp.elements.items() if "ENABLE" in n.upper() or n.upper().endswith("_ON"))
        return {
            "is_moving": self.is_moving,
            # INDI has no "settling" state distinct from Busy.
            "is_settling": False,
            "max_increment": self.max_increment,
            "max_step": self.max_step,
            "position": self.position,
            "temp_comp": self.temp_comp if comp is not None else None,
            "temperature": self._num("FOCUS_TEMPERATURE", "TEMPERATURE"),
        }


class IndiRotatorAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.ROTATOR, host, port, **kwargs)
        self.mechanical_angle = 0.0
        self.sky_angle = 0.0

    async def move_to_angle(self, angle: float) -> None:
        self._log_interaction("move_to_angle", angle=angle)
        self._set_num("ABS_ROTATOR_ANGLE", {"ANGLE": angle})
        self.mechanical_angle = angle

    async def halt(self) -> None:
        self._log_interaction("halt")
        self._set_sw("ROTATOR_ABORT_MOTION", {"ABORT": True})

    async def set_reverse(self, reverse: bool) -> None:
        self._log_interaction("set_reverse", reverse=reverse)
        self._set_sw("ROTATOR_REVERSE", {"INDI_ENABLED": reverse, "INDI_DISABLED": not reverse})

    async def sync_position(self, angle: float) -> None:
        """Declare the rotator's current physical position to be *angle*
        (``sync_position(0)`` = "set current position as zero")."""
        self._log_interaction("sync_position", angle=angle)
        prop = "SYNC_ROTATOR_ANGLE" if self._has("SYNC_ROTATOR_ANGLE") else "SYNC_ROTATOR"
        self._set_num(prop, {"ANGLE": angle})
        self.mechanical_angle = self.sky_angle = angle

    async def set_backlash(self, steps: float) -> None:
        """Set backlash compensation (a step count; ``0`` disables it). Only
        drivers implementing ``INDI::RotatorInterface``'s backlash properties
        have it — others raise ``DevicePropertyError``."""
        self._log_interaction("set_backlash", steps=steps)
        self._require("ROTATOR_BACKLASH_STEPS")
        if self._has("ROTATOR_BACKLASH_TOGGLE"):
            self._set_sw("ROTATOR_BACKLASH_TOGGLE", {"INDI_ENABLED": steps > 0, "INDI_DISABLED": steps <= 0})
        self._set_num("ROTATOR_BACKLASH_STEPS", {"ROTATOR_BACKLASH_VALUE": steps})

    async def get_status(self) -> dict:
        """Live rotator status. INDI reports a single angle (moved with
        ``ABS_ROTATOR_ANGLE``, redefined with a sync), so mechanical and sky
        position are the same value here."""
        angle = self._num("ABS_ROTATOR_ANGLE", "ANGLE")
        if angle is not None:
            self.mechanical_angle = self.sky_angle = angle
        limit = self._client.get_property(self.device_name, "ABS_ROTATOR_ANGLE") if self._client else None
        el = limit.elements.get("ANGLE") if limit else None
        return {
            **self._driver_info(),
            "position": angle,
            "mechanical_position": angle,
            "is_moving": (self._state("ABS_ROTATOR_ANGLE") == ic.BUSY) if angle is not None else None,
            "reverse": self._sw("ROTATOR_REVERSE", "INDI_ENABLED"),
            "backlash": self._num("ROTATOR_BACKLASH_STEPS", "ROTATOR_BACKLASH_VALUE"),
            "backlash_supported": self._has("ROTATOR_BACKLASH_STEPS"),
            "can_sync": self._has("SYNC_ROTATOR_ANGLE") or self._has("SYNC_ROTATOR"),
            "max_angle": el.max if el is not None else None,
        }


class IndiFlatPanelAdapter(IndiAdapter):
    """Flat panel: a dust cap (``CAP_PARK``) and/or light box
    (``FLAT_LIGHT_CONTROL`` / ``FLAT_LIGHT_INTENSITY``)."""

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.FLAT_PANEL, host, port, **kwargs)
        self.cover_state = "Closed"
        self.brightness = 0

    async def open_cover(self) -> None:
        self._log_interaction("open_cover")
        self._set_sw("CAP_PARK", {"UNPARK": True, "PARK": False})
        self.cover_state = "Open"

    async def close_cover(self) -> None:
        self._log_interaction("close_cover")
        self._set_sw("CAP_PARK", {"PARK": True, "UNPARK": False})
        self.cover_state = "Closed"

    async def set_brightness(self, level: int) -> None:
        self._log_interaction("set_brightness", level=level)
        if self._has("FLAT_LIGHT_CONTROL"):
            self._set_sw("FLAT_LIGHT_CONTROL", {"FLAT_LIGHT_ON": level > 0, "FLAT_LIGHT_OFF": level <= 0})
        self._set_num("FLAT_LIGHT_INTENSITY", {"FLAT_LIGHT_INTENSITY_VALUE": level})
        self.brightness = level


class IndiWeatherAdapter(IndiAdapter):
    """Weather station via ``INDI::Weather`` (``WEATHER_PARAMETERS`` +
    ``WEATHER_STATUS``). INDI has no standard cloud-cover parameter."""

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.WEATHER_STATION, host, port, **kwargs)
        self.cloud_cover = 0.0
        self.wind_speed = 0.0
        self.humidity = 50.0
        self.temperature = 15.0
        self.rain_rate = 0.0
        self.is_safe = True

    async def poll(self) -> None:
        for attr, element in (("temperature", "WEATHER_TEMPERATURE"), ("humidity", "WEATHER_HUMIDITY"),
                              ("wind_speed", "WEATHER_WIND_SPEED"), ("rain_rate", "WEATHER_RAIN_HOUR")):
            value = self._num("WEATHER_PARAMETERS", element)
            if value is not None:
                setattr(self, attr, value)
        state = self._state("WEATHER_STATUS")
        if state is not None:
            self.is_safe = state != ic.ALERT


class IndiDomeAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.DOME, host, port, **kwargs)
        self.azimuth = 0.0
        self.shutter_state = "Closed"
        self.is_at_park = True

    async def slew_to_azimuth(self, azimuth: float) -> None:
        self._log_interaction("slew_to_azimuth", azimuth=azimuth)
        self._set_num("ABS_DOME_POSITION", {"DOME_ABSOLUTE_POSITION": azimuth})
        self.azimuth = azimuth

    async def open_shutter(self) -> None:
        self._log_interaction("open_shutter")
        self._set_sw("DOME_SHUTTER", {"SHUTTER_OPEN": True, "SHUTTER_CLOSE": False})
        self.shutter_state = "Open"

    async def close_shutter(self) -> None:
        self._log_interaction("close_shutter")
        self._set_sw("DOME_SHUTTER", {"SHUTTER_OPEN": False, "SHUTTER_CLOSE": True})
        self.shutter_state = "Closed"

    async def park(self) -> None:
        self._log_interaction("park")
        self._set_sw("DOME_PARK", {"PARK": True, "UNPARK": False})
        self.is_at_park = True


class IndiSafetyMonitorAdapter(IndiAdapter):
    """INDI defines no safety-monitor device interface, so there is nothing
    to discover or read; ``poll()`` leaves the last known state unchanged."""

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
