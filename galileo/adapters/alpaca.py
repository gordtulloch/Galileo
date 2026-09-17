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

logger = logging.getLogger(__name__)

_ALPACA_DISCOVERY_PORT = 32227
_ALPACA_DISCOVERY_MSG = b"alpacadiscovery1"


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
    """
    try:
        from zeroconf import AddressResolver, Zeroconf
    except ImportError as exc:
        raise RuntimeError(
            f"Cannot resolve '{host}': the 'zeroconf' package is required to "
            "resolve .local hostnames (Windows does not do this on its own "
            "without Bonjour installed). Install it with 'pip install "
            "zeroconf', or use the device's IP address directly."
        ) from exc

    name = host if host.endswith(".") else f"{host}."
    zc = Zeroconf()
    try:
        resolver = AddressResolver(name)
        if not resolver.request(zc, timeout_ms):
            raise RuntimeError(
                f"Could not resolve '{host}' via mDNS within {timeout_ms / 1000:g}s. "
                "Make sure the device is powered on and on the same network, "
                "or use its IP address directly."
            )
        addresses = resolver.parsed_addresses()
        if not addresses:
            raise RuntimeError(f"mDNS lookup for '{host}' returned no address.")
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
        alpaca_type = self.device_type.lower().replace(" ", "")
        effective_host = self._resolved_host or self.host
        return f"http://{effective_host}:{self.port}/api/v1/{alpaca_type}/{self.device_number}"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities()

    def get_properties(self) -> dict:
        return dict(self._properties)

    async def _get(self, attribute: str) -> Any:
        """HTTP GET an Alpaca device attribute."""
        await self._ensure_resolved()
        self._transaction_id += 1
        url = f"{self.base_url}/{attribute}"
        params = {
            "ClientID": self._client_id,
            "ClientTransactionID": self._transaction_id,
        }
        try:
            import httpx  # type: ignore[import]
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                data = resp.json()
                return data.get("Value")
        except ImportError:
            # httpx not available; use urllib synchronously
            import urllib.request
            import urllib.parse
            query = urllib.parse.urlencode(params)
            with urllib.request.urlopen(f"{url}?{query}", timeout=10) as r:
                data = json.loads(r.read())
                return data.get("Value")

    async def _put(self, attribute: str, **body: Any) -> None:
        """HTTP PUT an Alpaca device attribute."""
        await self._ensure_resolved()
        self._transaction_id += 1
        url = f"{self.base_url}/{attribute}"
        body.update({"ClientID": self._client_id, "ClientTransactionID": self._transaction_id})
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.put(url, data=body)
        except ImportError:
            import urllib.request
            import urllib.parse
            data = urllib.parse.urlencode(body).encode()
            req = urllib.request.Request(url, data=data, method="PUT")
            urllib.request.urlopen(req, timeout=10)

    async def connect(self) -> None:
        await self._put("connected", Connected=True)
        self._connected = True

    async def disconnect(self) -> None:
        await self._put("connected", Connected=False)
        self._connected = False

    async def set_property(self, name: str, value: object) -> None:
        self._properties[name] = value

    async def list_available_devices(self, category: DeviceCategory) -> list[str]:
        """Return device names from this Alpaca server for *category*, via the
        server's Management API (``get_configured_devices``)."""
        wanted = (category.value if isinstance(category, DeviceCategory) else str(category)).lower()
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

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(has_cooler=True, can_set_gain=True, can_bin=True)

    async def start_exposure(self, duration: float, **kwargs) -> None:
        await self._put("startexposure", Duration=duration, Light=True)

    async def abort_exposure(self) -> None:
        await self._put("abortexposure")

    async def get_image_array(self):
        return await self._get("imagearray")

    async def set_temperature(self, temp_c: float) -> None:
        await self._put("setccdtemperature", SetCCDTemperature=temp_c)

    def get_temperature(self) -> float:
        return float(self._properties.get("CCD_TEMPERATURE", -10.0))

    def get_cooler_power(self) -> float:
        return float(self._properties.get("COOLER_POWER", 0.0))

    async def warm_up(self) -> None:
        await self._put("cooleron", CoolerOn=False)


# ---------------------------------------------------------------------------
# Mount
# ---------------------------------------------------------------------------

class AlpacaMountAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.MOUNT, host, port, **kwargs)
        self.ra = 0.0
        self.dec = 0.0
        self.altitude = 0.0
        self.azimuth = 0.0
        self.pier_side = "East"
        self.is_tracking = False
        self.is_slewing = False

    async def slew_to_coordinates(self, ra: float, dec: float) -> None:
        await self._put("slewtocoordinatesasync", RightAscension=ra / 15.0, Declination=dec)
        self.ra, self.dec = ra, dec

    async def abort_slew(self) -> None:
        await self._put("abortslew")

    async def park(self) -> None:
        await self._put("park")

    async def unpark(self) -> None:
        await self._put("unpark")

    async def set_tracking(self, enabled: bool) -> None:
        await self._put("tracking", Tracking=enabled)
        self.is_tracking = enabled

    async def set_tracking_rate(self, ra_rate_arcsec_s: float, dec_rate_arcsec_s: float) -> None:
        self._properties.update({"RA_RATE": ra_rate_arcsec_s, "DEC_RATE": dec_rate_arcsec_s})

    async def sync_to_coordinates(self, ra: float, dec: float) -> None:
        await self._put("synctocoordinates", RightAscension=ra / 15.0, Declination=dec)
        self.ra, self.dec = ra, dec


# ---------------------------------------------------------------------------
# Remaining category adapters
# ---------------------------------------------------------------------------

class AlpacaFWAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.FILTER_WHEEL, host, port, **kwargs)
        self.filter_names: list[str] = []
        self.position = 0

    async def move_to(self, index: int) -> None:
        await self._put("position", Position=index)
        self.position = index


class AlpacaFocuserAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.FOCUSER, host, port, **kwargs)
        self.position = 5000
        self.temperature = 15.0
        self.is_moving = False

    async def move_to(self, position: int) -> None:
        await self._put("move", Position=position)
        self.position = position

    async def move_by(self, steps: int) -> None:
        await self.move_to(self.position + steps)


class AlpacaRotatorAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.ROTATOR, host, port, **kwargs)
        self.mechanical_angle = 0.0
        self.sky_angle = 0.0

    async def move_to_angle(self, angle: float) -> None:
        await self._put("moveabsolute", Position=angle)
        self.mechanical_angle = angle


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
