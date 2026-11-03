# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""What every device page does to a device, with no screen (EQP-MNT-010, EQP-FOC-040).

Shared by the per-device ``*_ops`` modules (``mount_ops``, ``focuser_ops``): the :class:`Outcome` a command
returns instead of showing a message, :func:`scan_devices` to list what a server offers and
:func:`connect_device` to build and connect one adapter. Nothing here imports Qt.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

NOT_CONNECTED = "not_connected"
PARKED = "parked"
OBSTRUCTED = "obstructed"
LIMIT = "limit"
UNSUPPORTED = "unsupported"
FAILED = "failed"


@dataclass(frozen=True)
class Outcome:
    """The result of one device command. ``kind`` is empty on success, else one of the constants above;
    ``message`` is the text for the person where the command has its own wording, empty otherwise."""

    ok: bool
    kind: str = ""
    message: str = ""


OK = Outcome(True)


def forget(adapter: Any) -> None:
    """*adapter* has been disconnected: the device service (if the desktop is using one) stops holding it."""
    try:
        from galileo import desktop_devices
        desktop_devices.forget(adapter)
    except Exception:
        logger.exception("Could not tell the device service about a disconnected device")


def scan_devices(category: Any, driver: str, server: str, port: int) -> list[str] | None:
    """The devices of *category* the server at *server*:*port* offers through *driver* (``"INDI"`` or Alpaca).
    ``None`` when the scan itself failed, so a caller can tell that from an empty server."""
    try:
        if driver == "INDI":
            from galileo.adapters.indi import get_adapter_class
        else:
            from galileo.adapters.alpaca import get_adapter_class
        adapter = get_adapter_class(category)(host=server, port=port)
        return list(asyncio.run(adapter.list_available_devices(category)))
    except Exception:
        logger.exception("%s scan failed on %s:%s", getattr(category, "value", category), server, port)
        return None


def connect_device(make_adapter: Callable[..., Any], category: Any, driver: str, server: str, port: int,
                   device_name: str, configure: Callable[[Any], None] | None = None) -> Any | None:
    """Build the adapter with *make_adapter* (``(category, driver, server, port, device_name)``), let *configure*
    set it up, connect it and return it; ``None`` after logging why when any step fails."""
    try:
        adapter = make_adapter(category, driver, server, port, device_name)
        if configure is not None:
            configure(adapter)
        asyncio.run(adapter.connect())
    except Exception:
        logger.exception("Could not connect %s %r at %s:%s", getattr(category, "value", category), device_name,
                         server, port)
        return None
    return adapter


class DeviceOps:
    """Runs commands against the adapter ``get_adapter()`` returns *now* (so the same code serves a device the page
    connected itself or one a device service holds) and reports each as an :class:`Outcome`."""

    def __init__(self, get_adapter: Callable[[], Any]) -> None:
        self._get = get_adapter

    @property
    def adapter(self) -> Any | None:
        return self._get()

    def _call(self, name: str, call: Callable[[Any], Awaitable[Any]], failed: str = "", detail: str = "") -> Outcome:
        adapter = self._get()
        if adapter is None:
            return Outcome(False, NOT_CONNECTED)
        try:
            asyncio.run(call(adapter))
        except Exception:
            logger.exception("Could not %s%s", name, detail)
            return Outcome(False, FAILED, failed)
        return OK

    def status(self, label: str = "the device") -> dict | None:
        """The adapter's status, or ``None`` when nothing is connected or it cannot be read."""
        adapter = self._get()
        if adapter is None:
            return None
        try:
            return asyncio.run(adapter.get_status())
        except Exception:
            logger.exception("Could not refresh status for %s", label)
            return None

    def driver_info(self) -> dict | None:
        adapter = self._get()
        if adapter is None:
            return None
        try:
            return asyncio.run(adapter.get_driver_info())
        except Exception:
            logger.exception("Could not read driver info from the connected device")
            return None

    def disconnect(self, label: str = "the device") -> bool:
        """Disconnect; ``False`` when nothing was connected. A device that will not disconnect cleanly is logged."""
        adapter = self._get()
        if adapter is None:
            return False
        try:
            asyncio.run(adapter.disconnect())
        except Exception:
            logger.exception("Could not disconnect %s", label)
        forget(adapter)
        return True


def disconnect_all(adapters: Any, label: str = "device") -> None:
    """Disconnect each adapter in *adapters* (an iterable), logging any that will not."""
    for adapter in adapters:
        DeviceOps(lambda adapter=adapter: adapter).disconnect(label)


__all__ = [
    "FAILED",
    "LIMIT",
    "NOT_CONNECTED",
    "OBSTRUCTED",
    "OK",
    "PARKED",
    "UNSUPPORTED",
    "DeviceOps",
    "Outcome",
    "connect_device",
    "disconnect_all",
    "scan_devices",
]
