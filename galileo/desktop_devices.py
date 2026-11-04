# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The desktop's way onto the engine's device service, behind a setting (HEAD, off by default).

Normally each Equipment screen builds and keeps its own adapter. With *Hold devices in the device service* on (Options >
Equipment, stored as ``engine`` / ``desktop_uses_device_service`` in the settings database), a screen's Connect
builds the adapter through the same :class:`~galileo.engine.devices.DeviceService` the headless engine uses, so the
Control Surface, the safety guard and every other client of the service find the devices the screen connected, and
the screens' own copies are no longer the only owners.

Turned off, nothing here is called and the screens behave exactly as before. The service is created on first use and
lives for the process; it is the desktop's own, not a connection to a separate engine process.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any

from galileo.engine.devices import DeviceService

logger = logging.getLogger(__name__)

NAMESPACE = "engine"
KEY = "desktop_uses_device_service"

_lock = threading.Lock()
_service: DeviceService | None = None


def enabled() -> bool:
    from galileo.settings_store import get_setting
    try:
        return bool(get_setting(NAMESPACE, KEY, False))
    except Exception:
        logger.exception("Could not read the device-service setting; leaving it off")
        return False


def set_enabled(value: bool) -> bool:
    from galileo.settings_store import set_setting
    return bool(set_setting(NAMESPACE, KEY, bool(value)))


def service(factory: Callable[..., Any] | None = None) -> DeviceService:
    """The desktop's device service (created on first use; *factory* is only for tests)."""
    global _service
    with _lock:
        if _service is None:
            _service = DeviceService(factory=factory) if factory is not None else DeviceService()
        return _service


def reset() -> None:
    """Forget the service (tests)."""
    global _service
    with _lock:
        _service = None


def connect(pier: Any, category: Any, slot: str, driver: str, server: str, port: int, device_name: str,
            configure: Callable[[Any], None] | None = None) -> Any | None:
    """Connect one device through the service and return the adapter (``None`` when it failed). Blocks, like the
    screens' own connect does."""
    from galileo.engine.devices import pier_id
    return asyncio.run(service().connect_device(
        pier_id(pier), getattr(category, "value", str(category)), slot or "primary", driver, server, port,
        device_name, configure))


def forget(adapter: Any) -> None:
    """A screen disconnected *adapter*: the service stops holding it. Does nothing when no service exists."""
    if _service is not None:
        _service.release(adapter)


def host_engine() -> Any | None:
    """With the setting on, the desktop hosts a lean engine in its own process (HEAD-090): it takes the single-engine
    lock, serves the local channel and the Control Surface over the desktop's device service, and starts nothing the
    desktop already does. Returns the :class:`~galileo.engine.embedded.Attachment` to close at exit, or ``None`` when
    the setting is off, another engine already holds the lock (this desktop then keeps its own devices as before;
    attaching as a client is not built yet), or the engine could not start. Never raises."""
    if not enabled():
        return None
    from galileo import __version__
    from galileo.engine.embedded import attach_or_host
    from galileo.engine.lock import EngineAlreadyRunning
    from galileo.engine.main import Engine

    svc = service()
    built: list[Engine] = []

    def factory(lock: Any) -> Engine:
        built.append(Engine(lock, embedded=True, devices=svc))
        return built[0]

    try:
        attachment = attach_or_host(__version__, engine_factory=factory)
    except EngineAlreadyRunning as exc:
        logger.warning("%s Devices stay with this desktop.", exc)
        return None
    except Exception:
        logger.exception("The desktop could not host the engine; carrying on without it")
        for engine in built:
            try:
                engine.stop()
            except Exception:
                logger.exception("Stopping the half-started engine failed")
        return None
    if not attachment.hosting:
        logger.warning("Another engine is running on this machine. This desktop cannot attach to it yet, so its devices "
                       "stay with this desktop.")
        return None
    logger.info("The desktop is hosting the engine (device service on)")
    return attachment


class PierAdapters:
    """A screen's adapters by ``pier_key``, standing in for the plain dictionary each Equipment screen used to keep.

    What a screen stores here is kept as before. What the device service holds for the same Pier and category is
    read first, so a device the service connected, replaced or released is what the screen sees, not a stale copy.
    With no service (the setting never used) it is exactly a dictionary.

    ``nested=False`` is for a screen with one device per Pier (``get`` gives the adapter); ``nested=True`` for one
    with several slots (``get`` gives ``{slot: adapter}``, as the Focuser screen expects)."""

    def __init__(self, category: Any, nested: bool = False) -> None:
        self._category = str(getattr(category, "value", category)).lower()
        self._nested = nested
        self._local: dict[Any, Any] = {}

    def _held(self, key: Any) -> dict[str, Any]:
        if _service is None or key is None:
            return {}
        return _service.controllers(str(key), self._category)

    def get(self, key: Any, default: Any = None) -> Any:
        held = self._held(key)
        if self._nested:
            merged = {**self._local.get(key, {}), **held}
            return merged or default
        if held:
            return held.get("primary") or next(iter(held.values()))
        return self._local.get(key, default)

    def __setitem__(self, key: Any, adapter: Any) -> None:
        self._local[key] = adapter

    def setdefault(self, key: Any, default: Any) -> Any:
        return self._local.setdefault(key, default)

    def pop(self, key: Any, default: Any = None) -> Any:
        found = self.get(key, default=_MISSING)
        self._local.pop(key, None)
        return default if found is _MISSING else found


_MISSING = object()


__all__ = ["KEY", "NAMESPACE", "PierAdapters", "connect", "enabled", "forget", "host_engine", "reset", "service", "set_enabled"]
