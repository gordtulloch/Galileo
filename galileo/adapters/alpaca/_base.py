# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Alpaca adapter(s): the shared Alpaca adapter base, mDNS resolution and the wire-type table."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from typing import Any

from galileo.core.capabilities import DeviceCapabilities
from galileo.core.devices import DeviceBackend, DeviceCategory
from galileo.exceptions import DeviceConnectionError, DevicePropertyError
from galileo.net import http_request, urlopen_http

logger = logging.getLogger(__name__)


try:
    import httpx as _httpx
    _TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (_httpx.HTTPError, OSError)
except ImportError:  # the urllib fallbacks below raise OSError subclasses (URLError)
    _TRANSPORT_ERRORS = (OSError,)


# The ASCOM Alpaca spec's DeviceType names don't all match Galileo's internal
# DeviceCategory values — most notably there is no Alpaca "Mount" type, a
# mount is "Telescope" on the wire. Using DeviceCategory.MOUNT.value ("Mount")
# directly as the Alpaca DeviceType/URL segment silently matched nothing
# against any real Alpaca server's "Telescope" entries (including a Seestar's
# Alpaca bridge), surfacing as a confusing "No Alpaca Mount devices found"
# during discovery, and would 404 every actual mount command (slew/park/...)
# had discovery not blocked it first. WeatherStation/FlatPanel have the same
# mismatch against Alpaca's ObservingConditions/CoverCalibrator types.
_ALPACA_WIRE_TYPE: dict[DeviceCategory, str] = {
    DeviceCategory.MOUNT: "telescope",
    DeviceCategory.WEATHER_STATION: "observingconditions",
    DeviceCategory.FLAT_PANEL: "covercalibrator",
    # Aux has no device type of its own on the wire — it's scoped to ASCOM's
    # own generic/auxiliary-hardware interface, ISwitchV2 (see AlpacaAuxAdapter).
    DeviceCategory.AUX: "switch",
}


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

    Logs how long each lookup took and which resolver answered: every new
    adapter resolves again, so this is a per-device cost of a Pier switch.
    """
    start = time.perf_counter()
    try:
        address = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    except OSError:
        pass  # fall back to querying mDNS directly
    else:
        logger.info("Resolved %s to %s via the OS resolver in %.2fs", host, address, time.perf_counter() - start)
        return str(address)
    os_secs = time.perf_counter() - start

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
        logger.info(
            "Resolved %s to %s via zeroconf in %.2fs (OS resolver failed after %.2fs)",
            host, addresses[0], time.perf_counter() - start, os_secs,
        )
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
        import urllib.parse
        import urllib.request
        query = urllib.parse.urlencode({"ClientID": 1, "ClientTransactionID": 1})
        def _fetch() -> Any:
            with urlopen_http(f"{url}?{query}", 10) as r:
                return json.loads(r.read())
        data = await asyncio.to_thread(_fetch)
    return data.get("Value") or []


class AlpacaAdapter(DeviceBackend):
    """Base class for all Alpaca device adapters.

    Each concrete adapter targets one ASCOM Alpaca device at
    ``http://{host}:{port}/api/v1/{device_type}/{device_number}/``.
    """

    backend = "alpaca"

    def __init__(
        self,
        device_type: DeviceCategory | str = DeviceCategory.CAMERA,
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

    async def _get(self, attribute: str, timeout: float = 10.0, **extra: Any) -> Any:  # noqa: ASYNC109 -- per-request HTTP timeout, forwarded to the client
        """HTTP GET an Alpaca device attribute. *extra* adds device-specific
        query parameters (e.g. ISwitchV2's ``Id`` channel index)."""
        await self._ensure_resolved()
        self._transaction_id += 1
        url = f"{self.base_url}/{attribute}"
        params = {
            "ClientID": self._client_id,
            "ClientTransactionID": self._transaction_id,
            **extra,
        }
        try:
            try:
                import httpx  # type: ignore[import]
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
            except ImportError:
                # httpx not available; use urllib, off the event loop
                import urllib.parse
                import urllib.request
                query = urllib.parse.urlencode(params)

                def _fetch() -> Any:
                    with urlopen_http(f"{url}?{query}", timeout) as r:
                        return json.loads(r.read())
                data = await asyncio.to_thread(_fetch)
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
                import urllib.parse
                import urllib.request
                encoded = urllib.parse.urlencode(body).encode()
                req = http_request(url, data=encoded, method="PUT")

                def _send() -> Any:
                    with urlopen_http(req, 10) as r:
                        try:
                            return json.loads(r.read())
                        except Exception:
                            return {}
                data = await asyncio.to_thread(_send)
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

    async def get_driver_info(self) -> dict[str, str | None]:
        """The ASCOM ``Name``/``Description``/``DriverInfo``/``DriverVersion``
        common properties, which a driver must serve even while not
        connected. ``DriverInfo`` is read first and any failure there
        propagates (an unreachable server or wrong device number should be
        reported once, not timed out four times); the rest are optional
        and read defensively."""
        info: dict[str, str | None] = {}
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
