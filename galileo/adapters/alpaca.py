# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""ASCOM Alpaca adapter (galileo.adapters.alpaca).

Communicates with Alpaca devices via HTTP/REST per the ASCOM Alpaca
specification, including UDP discovery.  Uses ``httpx`` where available
for async HTTP; falls back to ``urllib`` for minimal dependency footprint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import struct
from typing import Any

from galileo.core.capabilities import DeviceCapabilities
from galileo.core.devices import DeviceBackend, DeviceCategory
from galileo.core.slew_guard import get_slew_guard
from galileo.exceptions import DeviceConnectionError, DeviceError, DevicePropertyError, MountParkedError

try:
    import httpx as _httpx
    _TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (_httpx.HTTPError, OSError)
except ImportError:  # the urllib fallbacks below raise OSError subclasses (URLError)
    _TRANSPORT_ERRORS = (OSError,)

logger = logging.getLogger(__name__)

_ALPACA_DISCOVERY_PORT = 32227
_ALPACA_DISCOVERY_MSG = b"alpacadiscovery1"

# The ASCOM Alpaca spec's DeviceType names don't all match Galileo's internal
# DeviceCategory values — most notably there is no Alpaca "Mount" type, a
# mount is "Telescope" on the wire. Using DeviceCategory.MOUNT.value ("Mount")
# directly as the Alpaca DeviceType/URL segment silently matched nothing
# against any real Alpaca server's "Telescope" entries (including a Seestar's
# Alpaca bridge), surfacing as a confusing "No Alpaca Mount devices found"
# during discovery, and would 404 every actual mount command (slew/park/...)
# had discovery not blocked it first. WeatherStation/FlatPanel have the same
# mismatch against Alpaca's ObservingConditions/CoverCalibrator types.
_ALPACA_WIRE_TYPE: dict["DeviceCategory", str] = {
    DeviceCategory.MOUNT: "telescope",
    DeviceCategory.WEATHER_STATION: "observingconditions",
    DeviceCategory.FLAT_PANEL: "covercalibrator",
}


def get_adapter_class(category: DeviceCategory) -> type[DeviceBackend]:
    """Return the Alpaca adapter class for *category*."""
    _MAP = {
        DeviceCategory.CAMERA: AlpacaCameraAdapter,
        DeviceCategory.MOUNT: AlpacaMountAdapter,
        DeviceCategory.FILTER_WHEEL: AlpacaFWAdapter,
        DeviceCategory.FOCUSER: AlpacaFocuserAdapter,
        DeviceCategory.ROTATOR: AlpacaRotatorAdapter,
        DeviceCategory.DOME: AlpacaDomeAdapter,
        DeviceCategory.SAFETY_MONITOR: AlpacaSafetyMonitorAdapter,
        DeviceCategory.SWITCH: AlpacaSwitchAdapter,
        DeviceCategory.WEATHER_STATION: AlpacaWeatherAdapter,
        DeviceCategory.GUIDER: AlpacaGuiderAdapter,
        DeviceCategory.FLAT_PANEL: AlpacaFlatPanelAdapter,
    }
    cls = _MAP.get(category)
    if cls is None:
        raise ValueError(f"No Alpaca adapter for category {category!r}")
    return cls


# ---------------------------------------------------------------------------
# UDP discovery
# ---------------------------------------------------------------------------

class AlpacaDiscovery:
    """Discovers Alpaca devices on the LAN via UDP broadcast (ARCH-050)."""

    async def discover(self, timeout_s: float = 2.0) -> list[dict]:
        raw = await self._raw_discover()
        return raw

    async def _raw_discover(self) -> list[dict]:
        results: list[dict] = []
        loop = asyncio.get_event_loop()

        def _broadcast() -> list[dict]:
            found: list[dict] = []
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.settimeout(1.0)
                sock.sendto(_ALPACA_DISCOVERY_MSG, ("<broadcast>", _ALPACA_DISCOVERY_PORT))
                while True:
                    try:
                        data, addr = sock.recvfrom(1024)
                        resp = json.loads(data.decode())
                        resp["_host"] = addr[0]
                        found.append(resp)
                    except socket.timeout:
                        break
            except Exception as exc:
                logger.debug("Alpaca discovery error: %s", exc)
            finally:
                sock.close()
            return found

        return await loop.run_in_executor(None, _broadcast)


_MDNS_TIMEOUT_MS = 3000


def resolve_mdns_host_sync(host: str, timeout_ms: int = _MDNS_TIMEOUT_MS) -> str:
    """Resolve a ``.local`` mDNS hostname to an IP address.

    Windows does not resolve ``.local`` names through the normal DNS
    resolver unless Bonjour/Apple software is installed, so a request to
    e.g. ``http://seestar.local:32323`` fails at the name-lookup stage on
    Windows — surfacing as a connection error that looks like the address
    is unreachable even though the host/port are correct. Querying mDNS
    directly via ``zeroconf`` sidesteps that (mirrors the approach proven
    in this author's VSTarget project's ``alpaca_client.py``).

    The operating system's own resolver is tried first: current Windows,
    macOS and Linux (with avahi/nss-mdns) resolve ``.local`` themselves, and
    that also works where ``zeroconf``'s compiled extension can't load (e.g.
    a Windows Application Control policy blocking its DLL).
    """
    try:
        return socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    except OSError:
        pass  # fall back to querying mDNS directly

    try:
        from zeroconf import AddressResolver, Zeroconf
    except ImportError as exc:
        raise DeviceConnectionError(
            f"Cannot resolve '{host}': the operating system could not resolve "
            f"it and the 'zeroconf' package could not be loaded ({exc}). "
            "Install it with 'pip install zeroconf', or use the device's IP "
            "address directly."
        ) from exc

    name = host if host.endswith(".") else f"{host}."
    zc = Zeroconf()
    try:
        resolver = AddressResolver(name)
        if not resolver.request(zc, timeout_ms):
            raise DeviceConnectionError(
                f"Could not resolve '{host}' via mDNS within {timeout_ms / 1000:g}s. "
                "Make sure the device is powered on and on the same network, "
                "or use its IP address directly."
            )
        addresses = resolver.parsed_addresses()
        if not addresses:
            raise DeviceConnectionError(f"mDNS lookup for '{host}' returned no address.")
        return addresses[0]
    finally:
        zc.close()


async def resolve_mdns_host(host: str, timeout_ms: int = _MDNS_TIMEOUT_MS) -> str:
    """Async wrapper around :func:`resolve_mdns_host_sync` (zeroconf is synchronous)."""
    return await asyncio.to_thread(resolve_mdns_host_sync, host, timeout_ms)


async def get_configured_devices(host: str, port: int, protocol: str = "http") -> list[dict]:
    """Query an Alpaca server's Management API for its configured devices.

    This is the standard Alpaca discovery step (``GET /management/v1/configureddevices``)
    that a client is expected to call before talking to any specific device's
    ``/api/v1/{devicetype}/{devicenumber}/...`` endpoint — the same sequence
    used by AstroLlama's ``alpaca_server_status`` tool via ``alpyca``'s
    ``alpaca.management.configureddevices()`` helper. Each returned dict has
    ``DeviceType``, ``DeviceName``, ``DeviceNumber``, and ``UniqueID`` keys.
    """
    if isinstance(host, str) and ":" in host:
        host, _, port_str = host.rpartition(":")
        if port_str.isdigit():
            port = int(port_str)
    if host.lower().endswith(".local"):
        host = await resolve_mdns_host(host)

    url = f"{protocol}://{host}:{port}/management/v1/configureddevices"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params={"ClientID": 1, "ClientTransactionID": 1})
            resp.raise_for_status()
            data = resp.json()
    except ImportError:
        import urllib.request
        import urllib.parse
        query = urllib.parse.urlencode({"ClientID": 1, "ClientTransactionID": 1})
        with urllib.request.urlopen(f"{url}?{query}", timeout=10) as r:
            data = json.loads(r.read())
    return data.get("Value") or []


# ---------------------------------------------------------------------------
# Base Alpaca adapter
# ---------------------------------------------------------------------------

class AlpacaAdapter(DeviceBackend):
    """Base class for all Alpaca device adapters.

    Each concrete adapter targets one ASCOM Alpaca device at
    ``http://{host}:{port}/api/v1/{device_type}/{device_number}/``.
    """

    backend = "alpaca"

    def __init__(
        self,
        device_type: "DeviceCategory | str" = DeviceCategory.CAMERA,
        host: str = "localhost",
        port: int = 11111,
        device_number: int = 0,
    ) -> None:
        self.device_type = device_type.value if isinstance(device_type, DeviceCategory) else str(device_type)
        category = device_type if isinstance(device_type, DeviceCategory) else None
        self._alpaca_wire_type = _ALPACA_WIRE_TYPE.get(category, self.device_type.lower().replace(" ", ""))
        # Alpaca endpoints are conventionally given as a single "host:port"
        # string (this is what alpyca's Camera/Telescope/management helpers
        # expect) — accept that form here too, so a server address typed as
        # e.g. "seestar.local:32323" isn't mistaken for the literal hostname
        # with the default port appended after it.
        if isinstance(host, str) and ":" in host:
            host, _, port_str = host.rpartition(":")
            if port_str.isdigit():
                port = int(port_str)
        self.host = host
        self.port = port
        self.device_number = device_number
        self._connected = False
        self._properties: dict[str, Any] = {}
        self._client_id = 1
        self._transaction_id = 0
        self._resolved_host: str | None = None

    async def _ensure_resolved(self) -> None:
        """Resolve a ``.local`` mDNS hostname to an IP address, once, and
        cache it — Windows can't resolve ``.local`` names without Bonjour
        installed, so every real network call must go through this first."""
        if self._resolved_host is None:
            if self.host.lower().endswith(".local"):
                self._resolved_host = await resolve_mdns_host(self.host)
            else:
                self._resolved_host = self.host

    @property
    def base_url(self) -> str:
        effective_host = self._resolved_host or self.host
        return f"http://{effective_host}:{self.port}/api/v1/{self._alpaca_wire_type}/{self.device_number}"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities()

    def get_properties(self) -> dict:
        return dict(self._properties)

    # ASCOM's own "well-known" Alpaca error code (spec table 3) for a
    # property/method the driver simply doesn't implement — routine for
    # optional properties (e.g. many real mounts don't implement
    # SiteElevation or SideOfPier) rather than a fault, so ``_get`` treats
    # it as "no value" instead of raising. A poller (e.g. Mount/Focuser
    # get_status()) reading one every couple of seconds would otherwise
    # log a full ERROR-level traceback each time, flooding the on-screen
    # log pane with noise for a condition that will never change.
    _ASCOM_NOT_IMPLEMENTED = 0x400

    def _raise_on_alpaca_error(self, data: dict, attribute: str) -> None:
        """Raise if the device's Alpaca JSON envelope reports a driver-level
        error (``ErrorNumber``/``ErrorMessage``) — e.g. a real focuser
        refusing a move outside its range. The Alpaca spec puts these in
        the 200 OK response body rather than the HTTP status, so a caller
        that only checks the HTTP status — or discards the body outright,
        as ``_put`` used to — never sees the failure."""
        error_number = data.get("ErrorNumber") or 0
        if error_number:
            raise DevicePropertyError(
                f"Alpaca {self.device_type} device at {self.base_url} rejected "
                f"{attribute!r}: {data.get('ErrorMessage') or '(no message)'} "
                f"(ErrorNumber={error_number})"
            )

    def _unreachable_error(self, exc: BaseException) -> DeviceConnectionError:
        """A one-line, user-facing replacement for a raw httpx/urllib transport error."""
        reason = str(exc) or type(exc).__name__
        return DeviceConnectionError(
            f"Alpaca {self.device_type} device at {self.host}:{self.port} is not responding "
            f"({reason}). Make sure it is powered on, on the same network, and that the "
            f"Alpaca server is running."
        )

    async def _get(self, attribute: str, timeout: float = 10.0) -> Any:
        """HTTP GET an Alpaca device attribute."""
        await self._ensure_resolved()
        self._transaction_id += 1
        url = f"{self.base_url}/{attribute}"
        params = {
            "ClientID": self._client_id,
            "ClientTransactionID": self._transaction_id,
        }
        try:
            try:
                import httpx  # type: ignore[import]
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
            except ImportError:
                # httpx not available; use urllib synchronously
                import urllib.request
                import urllib.parse
                query = urllib.parse.urlencode(params)
                with urllib.request.urlopen(f"{url}?{query}", timeout=timeout) as r:
                    data = json.loads(r.read())
        except _TRANSPORT_ERRORS as exc:
            raise self._unreachable_error(exc) from exc
        if (data.get("ErrorNumber") or 0) == self._ASCOM_NOT_IMPLEMENTED:
            return None
        self._raise_on_alpaca_error(data, attribute)
        return data.get("Value")

    async def _put(self, attribute: str, **body: Any) -> None:
        """HTTP PUT an Alpaca device attribute.

        Every device command (connect/disconnect, move/slew/park, exposure
        start/abort, temperature/switch/brightness sets, ...) funnels through
        here, so this is the single place that logs device interactions at
        INFO — visible in the on-screen log pane, unlike the DEBUG-level
        reads in ``_get`` which would otherwise flood it via periodic status
        polling. It's also the single place a driver-reported error
        (``ErrorNumber``) is caught — previously the response body was
        discarded entirely, so a real device refusing a command (e.g. a
        focuser move outside its travel range) failed silently.
        """
        await self._ensure_resolved()
        self._transaction_id += 1
        url = f"{self.base_url}/{attribute}"
        params = {k: v for k, v in body.items() if k not in ("ClientID", "ClientTransactionID")}
        logger.info("Alpaca %s device interaction: %s %s at %s", self.device_type, attribute, params, url)
        body.update({"ClientID": self._client_id, "ClientTransactionID": self._transaction_id})
        try:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.put(url, data=body)
                    resp.raise_for_status()
                    try:
                        data = resp.json()
                    except Exception:
                        data = {}
            except ImportError:
                import urllib.request
                import urllib.parse
                encoded = urllib.parse.urlencode(body).encode()
                req = urllib.request.Request(url, data=encoded, method="PUT")
                with urllib.request.urlopen(req, timeout=10) as r:
                    try:
                        data = json.loads(r.read())
                    except Exception:
                        data = {}
        except _TRANSPORT_ERRORS as exc:
            raise self._unreachable_error(exc) from exc
        self._raise_on_alpaca_error(data, attribute)

    async def connect(self) -> None:
        await self._put("connected", Connected=True)
        self._connected = True
        await self._log_supported_actions()

    async def _log_supported_actions(self) -> None:
        """Log the driver's ``SupportedActions`` (device-specific extras
        callable via ``Action``) at DEBUG. Purely diagnostic, so a driver
        that doesn't implement it, or a failed query, never fails connect."""
        if not logger.isEnabledFor(logging.DEBUG):
            return
        try:
            actions = await self._get("supportedactions")
        except Exception as exc:
            logger.debug("Alpaca %s at %s: could not read SupportedActions: %s",
                         self.device_type, self.base_url, exc)
            return
        if actions:
            logger.debug("Alpaca %s at %s SupportedActions (%d): %s",
                         self.device_type, self.base_url, len(actions), ", ".join(map(str, actions)))
        else:
            logger.debug("Alpaca %s at %s reports no SupportedActions", self.device_type, self.base_url)

    async def disconnect(self) -> None:
        await self._put("connected", Connected=False)
        self._connected = False

    async def set_property(self, name: str, value: object) -> None:
        self._properties[name] = value

    async def get_driver_info(self) -> dict[str, "str | None"]:
        """The ASCOM ``Name``/``Description``/``DriverInfo``/``DriverVersion``
        common properties, which a driver must serve even while not
        connected. ``DriverInfo`` is read first and any failure there
        propagates (an unreachable server or wrong device number should be
        reported once, not timed out four times); the rest are optional
        and read defensively."""
        info: dict[str, "str | None"] = {}
        value = await self._get("driverinfo")
        info["driver_info"] = str(value) if value is not None else None
        for key, attribute in (
            ("driver_version", "driverversion"), ("name", "name"), ("description", "description"),
        ):
            try:
                value = await self._get(attribute)
                info[key] = str(value) if value is not None else None
            except Exception as exc:
                logger.debug("Could not read %s from %s: %s", attribute, self.base_url, exc)
                info[key] = None
        return {"name": info["name"], "description": info["description"],
                "driver_info": info["driver_info"], "driver_version": info["driver_version"]}

    async def list_available_devices(self, category: DeviceCategory) -> list[str]:
        """Return device names from this Alpaca server for *category*, via the
        server's Management API (``get_configured_devices``)."""
        category_enum = category if isinstance(category, DeviceCategory) else None
        default = (category.value if isinstance(category, DeviceCategory) else str(category)).lower()
        wanted = _ALPACA_WIRE_TYPE.get(category_enum, default)
        devices = await get_configured_devices(self.host, self.port)
        return [
            f"{d.get('DeviceName', '?')} (#{d.get('DeviceNumber', 0)})"
            for d in devices
            if str(d.get("DeviceType", "")).lower() == wanted
        ]


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

class AlpacaCameraAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.CAMERA, host, port, **kwargs)
        self._exposure_s = 0.0

    # Allowed on top of the exposure time for readout and a slow Wi-Fi download.
    _IMAGE_MARGIN_S = 60.0
    _IMAGE_POLL_S = 0.5
    _CAMERA_ERROR = 5          # ASCOM CameraStates.cameraError

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(has_cooler=True, can_set_gain=True, can_bin=True)

    async def start_exposure(self, duration: float, gain: int = 0, frame_type: str = "Light", **kwargs) -> None:
        # gain 0 means "leave as configured", as for INDI. Not every camera has an adjustable gain,
        # and a refusal shouldn't cost the exposure.
        if gain:
            try:
                await self._put("gain", Gain=int(gain))
            except Exception:
                logger.warning("Could not set gain %s on %s; exposing with its current gain", gain, self.base_url)
        # ASCOM's Light flag is False for frames taken with the shutter closed.
        dark = any(word in frame_type.lower() for word in ("dark", "bias"))
        await self._put("startexposure", Duration=duration, Light=not dark)
        self._exposure_s = float(duration)

    async def abort_exposure(self) -> None:
        await self._put("abortexposure")

    async def get_image_array(self):
        """Wait for the exposure started by :meth:`start_exposure` to finish, then
        download it as a numpy array shaped ``(height, width)`` — ``(height,
        width, planes)`` for a colour camera. ``startexposure`` returns at once,
        so asking for ``imagearray`` straight away fails with "no image
        available" until the driver reports ``imageready``."""
        import numpy as np
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._exposure_s + self._IMAGE_MARGIN_S
        while True:
            ready = await self._get("imageready")
            if ready is None or ready:          # None: the driver can't say — just try the download
                break
            if await self._get("camerastate") == self._CAMERA_ERROR:
                raise DeviceError(f"Alpaca Camera at {self.base_url} reported an error during the exposure.")
            if loop.time() > deadline:
                raise DeviceError(
                    f"Alpaca Camera at {self.base_url} did not finish a {self._exposure_s:g} s exposure "
                    f"within {self._IMAGE_MARGIN_S:g} s of its end.")
            await asyncio.sleep(self._IMAGE_POLL_S)
        value = await self._get("imagearray", timeout=self._exposure_s + self._IMAGE_MARGIN_S)
        if value is None:
            raise DeviceError(f"Alpaca Camera at {self.base_url} returned no image data.")
        # ASCOM sends the image as columns (X first); numpy/FITS want rows (Y first).
        return np.asarray(value).swapaxes(0, 1)

    async def set_temperature(self, temp_c: float) -> None:
        await self._put("setccdtemperature", SetCCDTemperature=temp_c)

    def get_temperature(self) -> float:
        """Sensor temperature in °C, or NaN when none has been read (nothing polls it yet)."""
        value = self._properties.get("CCD_TEMPERATURE")
        return float("nan") if value is None else float(value)

    def get_cooler_power(self) -> float:
        return float(self._properties.get("COOLER_POWER", 0.0))

    async def warm_up(self) -> None:
        await self._put("cooleron", CoolerOn=False)

    async def get_sensor_info(self) -> dict:
        """Live-query this camera's sensor configuration from the standard
        ASCOM Camera properties (PixelSizeX/Y, CameraXSize/YSize, SensorName)
        — the "Download Info" action on the Equipment Camera page. Every
        Alpaca-compliant camera exposes these, including a Seestar's second
        (wide-field) camera device, so no device-specific handling is needed
        here beyond already targeting the right device_number/base_url."""
        info: dict[str, "float | int | str | None"] = {
            "pixel_size_um": None, "sensor_width_px": None,
            "sensor_height_px": None, "sensor_name": None,
        }
        try:
            pixel_size_x = await self._get("pixelsizex")
            info["pixel_size_um"] = float(pixel_size_x) if pixel_size_x is not None else None
        except Exception:
            logger.exception("Could not read PixelSizeX from %s", self.base_url)
        try:
            width = await self._get("cameraxsize")
            height = await self._get("cameraysize")
            info["sensor_width_px"] = int(width) if width is not None else None
            info["sensor_height_px"] = int(height) if height is not None else None
        except Exception:
            logger.exception("Could not read CameraXSize/YSize from %s", self.base_url)
        try:
            info["sensor_name"] = await self._get("sensorname")
        except Exception:
            # SensorName is optional in the ASCOM spec — many drivers omit it.
            pass
        return info


# ---------------------------------------------------------------------------
# Mount
# ---------------------------------------------------------------------------

class AlpacaMountAdapter(AlpacaAdapter):
    # ASCOM's SideOfPier/EquatorialSystem/TrackingRate properties are integer
    # enums on the wire — normalized to strings here so the UI (and any other
    # caller) doesn't need to know ASCOM's enum ordinals.
    _SIDE_OF_PIER = {-1: "Unknown", 0: "East", 1: "West"}
    _EQUATORIAL_SYSTEM = {0: "Other", 1: "JNOW", 2: "J2000", 3: "J2050", 4: "B1950"}
    TRACKING_RATE_NAMES = ["Sidereal", "Lunar", "Solar", "King"]

    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.MOUNT, host, port, **kwargs)
        self.ra = 0.0
        self.dec = 0.0
        self.altitude = 0.0
        self.azimuth = 0.0
        self.pier_side = "East"
        self.is_tracking = False
        self.is_slewing = False
        self._static_status: "dict[str, Any] | None" = None

    async def _refuse_if_parked(self, command: str) -> None:
        """Movement commands must not reach a parked mount. Asks the mount
        (``AtPark``) rather than trusting a cached value, so a park done
        outside Galileo is honoured too. If the mount can't say, the command
        goes ahead and the device decides — ASCOM drivers reject movement
        while parked themselves."""
        try:
            parked = bool(await self._get("atpark"))
        except Exception:
            logger.warning("Could not read AtPark from %s before %s; sending it anyway", self.base_url, command)
            return
        if parked:
            logger.warning("Not sending %s to %s: the mount is parked", command, self.base_url)
            raise MountParkedError(f"The mount is parked, so {command} was not sent — unpark it first.")

    async def slew_to_coordinates(self, ra: float, dec: float) -> None:
        await self._refuse_if_parked("slew_to_coordinates")
        get_slew_guard().check_radec(ra, dec)
        await self._put("slewtocoordinatesasync", RightAscension=ra / 15.0, Declination=dec)
        self.ra, self.dec = ra, dec

    async def slew_to_altaz(self, alt: float, az: float) -> None:
        await self._refuse_if_parked("slew_to_altaz")
        get_slew_guard().check_altaz(alt, az)
        await self._put("slewtoaltazasync", Azimuth=az, Altitude=alt)
        self.altitude, self.azimuth = alt, az

    async def abort_slew(self) -> None:
        await self._put("abortslew")

    async def park(self) -> None:
        await self._put("park")

    async def unpark(self) -> None:
        await self._put("unpark")

    async def find_home(self) -> None:
        await self._refuse_if_parked("find_home")
        await self._put("findhome")

    async def move_axis(self, axis: int, rate: float) -> None:
        """Continuous jog via ``ITelescopeV3.MoveAxis`` — Axis 0 is Primary
        (RA/Az), Axis 1 is Secondary (Dec/Alt). A nonzero ``rate`` (deg/s)
        starts motion on that axis; ``rate=0`` stops it. Used by the Mount
        page's N/S/E/W jog buttons rather than a one-shot relative slew,
        since MoveAxis is the standard way to drive a mount while a button
        is held rather than computing a target coordinate. Stopping an axis
        (``rate=0``) is always allowed."""
        if rate:
            await self._refuse_if_parked("move_axis")
        await self._put("moveaxis", Axis=axis, Rate=rate)

    async def set_tracking(self, enabled: bool) -> None:
        if enabled:
            await self._refuse_if_parked("set_tracking")
        await self._put("tracking", Tracking=enabled)
        self.is_tracking = enabled

    async def set_tracking_rate(self, ra_rate_arcsec_s: float, dec_rate_arcsec_s: float) -> None:
        self._properties.update({"RA_RATE": ra_rate_arcsec_s, "DEC_RATE": dec_rate_arcsec_s})

    async def set_tracking_rate_mode(self, mode: str) -> None:
        """Select one of ASCOM's four standard ``TrackingRate`` enum values
        (Sidereal/Lunar/Solar/King) by name — distinct from
        ``set_tracking_rate``'s arbitrary custom RA/Dec rates (EQP-MNT-040's
        non-sidereal tracking), this is the Mount page's "Set tracking rate"
        control mirroring what a real ASCOM driver exposes as a dropdown."""
        try:
            idx = self.TRACKING_RATE_NAMES.index(mode)
        except ValueError:
            idx = 0
        await self._put("trackingrate", TrackingRate=idx)

    async def sync_to_coordinates(self, ra: float, dec: float) -> None:
        await self._refuse_if_parked("sync_to_coordinates")
        await self._put("synctocoordinates", RightAscension=ra / 15.0, Declination=dec)
        self.ra, self.dec = ra, dec

    async def _read_static_status(self) -> dict[str, Any]:
        """Properties that don't change while connected. A failed read is
        logged once and stays ``None`` (cached too, so an unimplemented
        optional property like SiteElevation isn't retried every poll)."""
        static: dict[str, Any] = {}
        reads: list[tuple[str, str, Any]] = [
            ("name", "name", str),
            ("description", "description", str),
            ("driver_info", "driverinfo", str),
            ("driver_version", "driverversion", str),
            ("site_latitude", "sitelatitude", float),
            ("site_longitude", "sitelongitude", float),
            ("site_elevation", "siteelevation", float),
        ]
        for key, attribute, caster in reads:
            try:
                value = await self._get(attribute)
                static[key] = caster(value) if value is not None else None
            except Exception:
                logger.exception("Could not read %s from %s", attribute, self.base_url)
                static[key] = None
        try:
            raw_equatorial_system = await self._get("equatorialsystem")
            static["equatorial_system"] = (
                self._EQUATORIAL_SYSTEM.get(int(raw_equatorial_system)) if raw_equatorial_system is not None else None
            )
        except Exception:
            logger.exception("Could not read EquatorialSystem from %s", self.base_url)
            static["equatorial_system"] = None
        return static

    async def get_status(self) -> dict:
        """Live-query this mount's status from the standard ASCOM
        ``ITelescopeV3`` properties — the Mount page's live status display
        (Name/Description/Driver info/version, Site latitude/longitude/
        elevation, Sidereal time, Right Ascension/Declination, Altitude/
        Azimuth, Side of Pier, Tracking, Epoch). Every property is read
        defensively since not every driver implements every optional one
        (e.g. SiteElevation) — a failed read leaves that field ``None``
        rather than aborting the whole refresh.

        The UI polls this every couple of seconds and each property is its
        own HTTP request, so the ones that never change while connected
        (identity, site, equatorial system) are read once and reused."""
        if self._static_status is None:
            self._static_status = await self._read_static_status()
        status: dict[str, Any] = dict(self._static_status)
        reads: list[tuple[str, str, Any]] = [
            ("sidereal_time", "siderealtime", float),
            ("right_ascension", "rightascension", float),
            ("declination", "declination", float),
            ("altitude", "altitude", float),
            ("azimuth", "azimuth", float),
            ("tracking", "tracking", bool),
            ("slewing", "slewing", bool),
            ("at_park", "atpark", bool),
        ]
        for key, attribute, caster in reads:
            try:
                value = await self._get(attribute)
                status[key] = caster(value) if value is not None else None
            except Exception:
                logger.exception("Could not read %s from %s", attribute, self.base_url)
                status[key] = None
        try:
            raw_side_of_pier = await self._get("sideofpier")
            status["side_of_pier"] = self._SIDE_OF_PIER.get(int(raw_side_of_pier)) if raw_side_of_pier is not None else None
        except Exception:
            logger.exception("Could not read SideOfPier from %s", self.base_url)
            status["side_of_pier"] = None

        if status.get("right_ascension") is not None:
            self.ra = status["right_ascension"] * 15.0
        if status.get("declination") is not None:
            self.dec = status["declination"]
        if status.get("altitude") is not None:
            self.altitude = status["altitude"]
        if status.get("azimuth") is not None:
            self.azimuth = status["azimuth"]
        if status.get("side_of_pier") is not None:
            self.pier_side = status["side_of_pier"]
        if status.get("tracking") is not None:
            self.is_tracking = status["tracking"]
        if status.get("slewing") is not None:
            self.is_slewing = status["slewing"]
        return status


# ---------------------------------------------------------------------------
# Remaining category adapters
# ---------------------------------------------------------------------------

class AlpacaFWAdapter(AlpacaAdapter):
    """Filter wheel via the ASCOM Alpaca ``IFilterWheelV2`` interface."""

    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.FILTER_WHEEL, host, port, **kwargs)
        self.filter_names: list[str] = []
        self.position = 0

    async def connect(self) -> None:
        await super().connect()
        try:
            names = await self._get("names")
            if names:
                self.filter_names = [str(n) for n in names]
        except Exception:
            logger.exception("Could not read Names from %s", self.base_url)
        try:
            position = await self._get("position")
            if position is not None:
                self.position = int(position)
        except Exception:
            logger.exception("Could not read initial Position from %s", self.base_url)

    async def move_to(self, index: int) -> None:
        await self._put("position", Position=index)
        self.position = index

    async def get_status(self) -> dict:
        """Live-query this filter wheel's status from the standard ASCOM
        ``IFilterWheelV2`` properties — the Filter Wheel page's status
        display (Name/Description/Driver info/version) and current
        selection (``Names``/``Position``, refreshing this adapter's own
        cached ``filter_names``/``position`` in case they changed on the
        device since ``connect()``). Every property is read defensively
        since not every driver implements every optional one."""
        status: dict[str, Any] = {}
        reads: list[tuple[str, str, Any]] = [
            ("name", "name", str),
            ("description", "description", str),
            ("driver_info", "driverinfo", str),
            ("driver_version", "driverversion", str),
        ]
        for key, attribute, caster in reads:
            try:
                value = await self._get(attribute)
                status[key] = caster(value) if value is not None else None
            except Exception:
                logger.exception("Could not read %s from %s", attribute, self.base_url)
                status[key] = None
        try:
            names = await self._get("names")
            if names:
                self.filter_names = [str(n) for n in names]
        except Exception:
            logger.exception("Could not read Names from %s", self.base_url)
        try:
            position = await self._get("position")
            if position is not None:
                self.position = int(position)
        except Exception:
            logger.exception("Could not read Position from %s", self.base_url)
        status["filter_names"] = list(self.filter_names)
        status["position"] = self.position
        return status


class AlpacaFocuserAdapter(AlpacaAdapter):
    """Focuser via the ASCOM Alpaca ``IFocuserV3`` interface.

    ``MaxStep`` (the device's valid travel range, consumed by
    ``FocuserController``'s EQP-FOC-030 clamp) and ``Absolute`` (whether
    ``Move`` takes an absolute position or a relative step count) are
    read from the real device on connect rather than assumed — a physical
    focuser such as a Seestar's Alpaca bridge may be relative-only, and its
    range is device-specific, not a fixed simulator constant.
    """

    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.FOCUSER, host, port, **kwargs)
        self.position = 0
        self.temperature = 15.0
        self.is_moving = False
        self.max_step: "int | None" = None
        self.max_increment: "int | None" = None
        self.absolute: "bool | None" = None

    async def connect(self) -> None:
        await super().connect()
        try:
            self.absolute = bool(await self._get("absolute"))
        except Exception:
            logger.exception("Could not read Absolute from %s", self.base_url)
        try:
            self.max_step = int(await self._get("maxstep"))
        except Exception:
            logger.exception("Could not read MaxStep from %s", self.base_url)
        try:
            self.max_increment = int(await self._get("maxincrement"))
        except Exception:
            logger.exception("Could not read MaxIncrement from %s", self.base_url)
        try:
            self.position = int(await self._get("position"))
        except Exception:
            logger.exception("Could not read initial Position from %s", self.base_url)
        try:
            self.temperature = float(await self._get("temperature"))
        except Exception:
            pass

    async def move_to(self, position: int) -> None:
        await self._put("move", Position=position)
        try:
            self.position = int(await self._get("position"))
        except Exception:
            logger.exception("Could not read back Position from %s after move", self.base_url)
            self.position = position
        try:
            self.is_moving = bool(await self._get("ismoving"))
        except Exception:
            pass

    async def move_by(self, steps: int) -> None:
        if self.absolute is False:
            # Relative-only focuser: Move's Position argument *is* the step
            # delta, so send it directly rather than computing (and
            # asserting) an absolute target it doesn't support.
            await self._put("move", Position=steps)
            try:
                self.position = int(await self._get("position"))
            except Exception:
                logger.exception("Could not read back Position from %s after move", self.base_url)
                self.position += steps
        else:
            await self.move_to(self.position + steps)

    async def set_temp_comp(self, enabled: bool) -> None:
        await self._put("tempcomp", TempComp=enabled)

    async def get_status(self) -> dict:
        """Live-query this focuser's status from the standard ASCOM
        ``IFocuserV3`` properties — the Focuser page's per-panel status
        display (Is Moving, Max Increment, Max Step, Position, Temp Comp,
        Temperature). ASCOM has no standard "is settling" property, so that
        field is always reported ``False`` here. Successful reads also
        refresh this adapter's own cached ``position``/``max_step``/
        ``max_increment`` (used by ``FocuserController``'s clamp), so they
        stay current even if the initial ``connect()``-time fetch failed
        transiently."""
        status: dict[str, "bool | int | float | None"] = {
            "is_moving": None, "is_settling": False, "max_increment": None,
            "max_step": None, "position": None, "temp_comp": None, "temperature": None,
        }
        try:
            status["is_moving"] = bool(await self._get("ismoving"))
            self.is_moving = status["is_moving"]
        except Exception:
            logger.exception("Could not read IsMoving from %s", self.base_url)
        try:
            status["position"] = int(await self._get("position"))
            self.position = status["position"]
        except Exception:
            logger.exception("Could not read Position from %s", self.base_url)
        try:
            status["max_increment"] = int(await self._get("maxincrement"))
            self.max_increment = status["max_increment"]
        except Exception:
            logger.exception("Could not read MaxIncrement from %s", self.base_url)
        try:
            status["max_step"] = int(await self._get("maxstep"))
            self.max_step = status["max_step"]
        except Exception:
            logger.exception("Could not read MaxStep from %s", self.base_url)
        try:
            status["temp_comp"] = bool(await self._get("tempcomp"))
        except Exception:
            # TempComp is only present when TempCompAvailable is True.
            pass
        try:
            status["temperature"] = float(await self._get("temperature"))
            self.temperature = status["temperature"]
        except Exception:
            pass
        return status


class AlpacaRotatorAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.ROTATOR, host, port, **kwargs)
        self.mechanical_angle = 0.0
        self.sky_angle = 0.0

    async def move_to_angle(self, angle: float) -> None:
        await self._put("moveabsolute", Position=angle)
        self.mechanical_angle = angle

    async def halt(self) -> None:
        await self._put("halt")

    async def set_reverse(self, reverse: bool) -> None:
        await self._put("reverse", Reverse=reverse)

    async def sync_position(self, angle: float) -> None:
        """``IRotatorV3.Sync``: declare the current sky position to be *angle*
        (``sync_position(0)`` = "set current position as zero")."""
        await self._put("sync", Position=angle)
        self.sky_angle = angle

    async def set_backlash(self, steps: float) -> None:
        raise DevicePropertyError("ASCOM Alpaca's IRotatorV3 interface has no backlash setting.")

    async def get_status(self) -> dict:
        """Live status from the standard ASCOM ``IRotatorV3`` properties:
        ``Position`` (sky, as synced) and ``MechanicalPosition`` (raw), plus
        ``IsMoving`` and ``Reverse``. Each is read defensively — a driver
        that doesn't implement one leaves that field ``None``."""
        status: dict[str, Any] = {}
        reads: list[tuple[str, str, Any]] = [
            ("name", "name", str), ("description", "description", str),
            ("driver_info", "driverinfo", str), ("driver_version", "driverversion", str),
            ("position", "position", float), ("mechanical_position", "mechanicalposition", float),
            ("is_moving", "ismoving", bool), ("reverse", "reverse", bool),
        ]
        for key, attribute, caster in reads:
            try:
                value = await self._get(attribute)
                status[key] = caster(value) if value is not None else None
            except Exception:
                logger.exception("Could not read %s from %s", attribute, self.base_url)
                status[key] = None
        status.update(backlash=None, backlash_supported=False, can_sync=True, max_angle=360.0)
        if status["position"] is not None:
            self.sky_angle = status["position"]
        if status["mechanical_position"] is not None:
            self.mechanical_angle = status["mechanical_position"]
        return status


class AlpacaDomeAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.DOME, host, port, **kwargs)
        self.azimuth = 0.0
        self.shutter_state = "Closed"
        self.is_at_park = True

    async def slew_to_azimuth(self, azimuth: float) -> None:
        await self._put("slewtoazimuth", Azimuth=azimuth)
        self.azimuth = azimuth

    async def open_shutter(self) -> None:
        await self._put("openshutter")
        self.shutter_state = "Open"

    async def close_shutter(self) -> None:
        await self._put("closeshutter")
        self.shutter_state = "Closed"

    async def park(self) -> None:
        await self._put("park")


class AlpacaSafetyMonitorAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.SAFETY_MONITOR, host, port, **kwargs)
        self.is_safe = True
        self.explanation = ""
        self.tier = 1

    async def poll(self) -> None:
        self.is_safe = await self._get("issafe") or True


class AlpacaSwitchAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.SWITCH, host, port, **kwargs)
        self.switches: list = []

    async def set_switch(self, name: str, value) -> None:
        for i, sw in enumerate(self.switches):
            if sw.name == name:
                await self._put("setswitch", Id=i, State=value)
                sw.state = value


class AlpacaWeatherAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.WEATHER_STATION, host, port, **kwargs)
        self.cloud_cover = 0.0
        self.wind_speed = 0.0
        self.humidity = 50.0
        self.temperature = 15.0
        self.rain_rate = 0.0
        self.is_safe = True

    async def poll(self) -> None:
        pass


class AlpacaGuiderAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.GUIDER, host, port, **kwargs)


class AlpacaFlatPanelAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.FLAT_PANEL, host, port, **kwargs)
        self.cover_state = "Closed"
        self.brightness = 0

    async def open_cover(self) -> None:
        await self._put("opencover")
        self.cover_state = "Open"

    async def close_cover(self) -> None:
        await self._put("closecover")
        self.cover_state = "Closed"

    async def set_brightness(self, level: int) -> None:
        await self._put("brightness", Brightness=level)
        self.brightness = level
