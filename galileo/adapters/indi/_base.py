# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The shared INDI adapter base: connect/disconnect, property helpers and the device-interface mask."""

from __future__ import annotations

import asyncio
import datetime
import logging
import time
from typing import Any

from galileo.adapters import indi_client as ic
from galileo.core.capabilities import DeviceCapabilities
from galileo.core.devices import DeviceBackend, DeviceCategory
from galileo.exceptions import DeviceConnectionError, DeviceError, DevicePropertyError, DeviceTimeoutError

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


def _send_optics(client: ic.IndiClient, device: str, focal_length_mm: float, aperture_mm: float, has=None) -> bool:
    """Write the telescope's focal length and aperture to whichever of the device's
    ``SCOPE_INFO`` / ``TELESCOPE_INFO`` vectors it defines, only to elements it really
    has. ``TELESCOPE_INFO`` also carries a ``GUIDER_*`` pair (what a guide camera such
    as the Guide Simulator reads); the caller passes the optics of the tube the device
    sits behind. Returns whether anything was sent."""
    if focal_length_mm <= 0 or aperture_mm <= 0:
        return False
    for name in ("TELESCOPE_INFO", "SCOPE_INFO"):
        prop = client.get_property(device, name)
        if not (has(name) if has is not None else prop is not None):
            continue
        wanted = {
            "TELESCOPE_FOCAL_LENGTH": focal_length_mm, "TELESCOPE_APERTURE": aperture_mm,
            "GUIDER_FOCAL_LENGTH": focal_length_mm, "GUIDER_APERTURE": aperture_mm,
            "FOCAL_LENGTH": focal_length_mm, "APERTURE": aperture_mm,
        }
        elements = getattr(prop, "elements", None)
        if isinstance(elements, dict):
            values = {k: v for k, v in wanted.items() if k in elements}
        else:       # element list not known: the pair the vector is documented to carry
            keys = ("TELESCOPE_FOCAL_LENGTH", "TELESCOPE_APERTURE") if name == "TELESCOPE_INFO" else ("FOCAL_LENGTH", "APERTURE")
            values = {k: wanted[k] for k in keys}
        if values:
            client.send_number(device, name, values)
            return True
    return False


async def push_optics_to_server(
    host: str, port: int, focal_length_mm: float, aperture_mm: float,
    per_device: dict[str, tuple[float, float]] | None = None,
) -> int:
    """Send the optics to *every* device on an INDI server that wants them, including
    ones Galileo doesn't drive itself — notably a guide camera that PHD2 owns, which
    otherwise warns "Telescope focal length is missing" on every exposure. *per_device*
    maps an INDI device name to its own ``(focal_length_mm, aperture_mm)`` — a device
    behind a different optical tube than the default pair. Best effort; returns how many
    devices were written."""
    own = per_device or {}

    def run() -> int:
        client = ic.acquire_client(host, port)
        try:
            return sum(_send_optics(client, dev, *own.get(dev, (focal_length_mm, aperture_mm)))
                       for dev in client.device_names())
        finally:
            ic.release_client(client)

    try:
        return await asyncio.to_thread(run)
    except Exception:
        logger.warning("Could not push optics to the INDI server %s:%s", host, port, exc_info=True)
        return 0


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
        device_type: DeviceCategory | str = DeviceCategory.CAMERA,
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
        # What push_context last sent, so a repeat (connect pushes from both the
        # adapter and the UI) isn't re-sent to a slow serial mount driver.
        self._last_time_push = float("-inf")
        self._last_geo_push: dict[str, float] | None = None

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

    async def push_context(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        elevation: float | None = None,
        focal_length_mm: float = 0.0,
        aperture_mm: float = 0.0,
    ) -> None:
        """Send the driver the current UTC time, the site (``GEOGRAPHIC_COORD``) and the
        telescope (``SCOPE_INFO``), for whichever of those properties the device defines —
        right after connecting, and again when the optics change. Drivers use them for
        FITS headers and simulated skies, and warn ("Telescope focal length is missing")
        when they are absent. Best effort: a failure is logged, never raised."""
        if self._client is None:
            return
        client = self._client

        def settle(prop: str) -> None:
            # Slow mount drivers (LX200 OnStep) run each of these as a serial
            # exchange with the mount and log "Error setting ..." if the next
            # command arrives while the previous one is still Busy.
            try:
                client.wait_for(lambda: client.get_state(self.device_name, prop) != ic.BUSY, 15.0, f"{prop} to finish")
            except Exception:
                logger.debug("INDI %r: %s still busy after 15s", self.device_name, prop)

        def push() -> None:
            now = time.monotonic()
            # Connect pushes context from both the adapter and the UI — don't
            # repeat a time set the driver has only just been given.
            if self._has("TIME_UTC") and now - self._last_time_push > 60.0:
                utc = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")
                client.send_text(self.device_name, "TIME_UTC", {"UTC": utc, "OFFSET": "0"})
                self._last_time_push = now
                settle("TIME_UTC")
            if latitude is not None and longitude is not None and self._has("GEOGRAPHIC_COORD"):
                geo = {"LAT": latitude, "LONG": longitude if longitude >= 0 else longitude + 360.0}
                if elevation is not None:
                    geo["ELEV"] = elevation
                if geo != self._last_geo_push:
                    client.send_number(self.device_name, "GEOGRAPHIC_COORD", geo)
                    self._last_geo_push = geo
                    settle("GEOGRAPHIC_COORD")
            _send_optics(client, self.device_name, focal_length_mm, aperture_mm, self._has)

        self._log_interaction("push_context", lat=latitude, lon=longitude, focal=focal_length_mm, aperture=aperture_mm)
        try:
            await asyncio.to_thread(push)
        except Exception:
            logger.warning("Could not push time/site/optics to INDI %r", self.device_name, exc_info=True)

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
        # Phase timings, logged once connected — a Pier switch reconnects every
        # device, so knowing which wait dominates is what makes it tunable.
        phases: dict[str, float] = {}
        mark = time.perf_counter()

        def lap(name: str) -> None:
            nonlocal mark
            now = time.perf_counter()
            phases[name] = now - mark
            mark = now

        client = ic.acquire_client(self.host, self.port)
        lap("server")
        try:
            if self.device_name not in client.device_names():
                raise DeviceConnectionError(
                    f"INDI server {self.host}:{self.port} has no device named {self.device_name!r} "
                    f"(available: {', '.join(client.device_names()) or 'none'})."
                )
            client.wait_property(self.device_name, "CONNECTION", 10.0)
            lap("CONNECTION property")
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
            lap("device CONNECT" if self._we_connected_device else "already connected")
            # Drivers define most of their properties only once connected, and
            # do so *after* reporting CONNECT — wait for that burst to finish.
            client.wait_settled(quiet=0.6, timeout=8.0, restart=True)
            lap("property settle")
        except BaseException:
            ic.release_client(client)
            self._we_connected_device = False
            raise
        self._client = client
        self._connected = True
        logger.info(
            "INDI %s %r (%s:%d) connected in %.2fs: %s",
            self.device_type, self.device_name, self.host, self.port, sum(phases.values()),
            ", ".join(f"{name} {secs:.2f}s" for name, secs in phases.items()),
        )

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

    async def _list_devices(self, category: DeviceCategory | None = None) -> list[str]:
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

    def _driver_info(self, client: ic.IndiClient | None = None) -> dict[str, str | None]:
        client = client or self._client

        def txt(element: str) -> str | None:
            return client.get_text(self.device_name, "DRIVER_INFO", element) if client else None

        return {
            "name": self.device_name or None,
            "description": txt("DRIVER_EXEC"),
            "driver_info": txt("DRIVER_NAME"),
            "driver_version": txt("DRIVER_VERSION"),
        }

    async def get_driver_info(self) -> dict[str, str | None]:
        """The device's ``DRIVER_INFO`` property. A driver defines it as soon
        as the server knows the device, before anything connects it, so when
        this adapter isn't connected it borrows the server connection just
        long enough to read it — without switching the device on."""
        if self._client is not None and self._client.alive:
            return self._driver_info()
        if not self.device_name:
            return {}
        return await asyncio.to_thread(self._read_driver_info_sync)

    def _read_driver_info_sync(self) -> dict[str, str | None]:
        client = ic.acquire_client(self.host, self.port)
        try:
            if self.device_name not in client.device_names():
                raise DeviceConnectionError(
                    f"INDI server {self.host}:{self.port} has no device named {self.device_name!r} "
                    f"(available: {', '.join(client.device_names()) or 'none'})."
                )
            client.wait_property(self.device_name, "DRIVER_INFO", 10.0)
            return self._driver_info(client)
        finally:
            ic.release_client(client)

    _ACK_GRACE_S = 2.0   # how long to wait for a driver to acknowledge a command before assuming it finished

    async def _wait_not_busy(self, prop: str, timeout: float, what: str, after_seq: int | None = None) -> None:  # noqa: ASYNC109 -- deadline for the wait loop below
        """Wait for a commanded operation (property state Busy) to finish.

        Pass *after_seq* (``blob_seq`` taken just before the command was sent) so the wait first sees the
        driver's reply. Without it, a state still reading Ok from before the command (its Busy update
        not yet received) makes this return at once, before the operation has even started."""
        client = self._c()
        if after_seq is not None:
            try:
                await asyncio.to_thread(
                    client.wait_for, lambda: client.blob_seq(self.device_name, prop) > after_seq,
                    min(timeout, self._ACK_GRACE_S), what,
                )
            except DeviceTimeoutError:
                pass  # a driver that never replies: fall through to the plain state check
        await asyncio.to_thread(
            client.wait_for,
            lambda: (p := client.get_property(self.device_name, prop)) is None or p.state != ic.BUSY,
            timeout, what,
        )
        if client.get_state(self.device_name, prop) == ic.ALERT:
            last = client.messages[-1] if client.messages else "no message from driver"
            raise DeviceError(f"INDI {self.device_name!r} {what} failed: {last}")
