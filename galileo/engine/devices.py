# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The engine's device service (HEAD-040): every Pier's devices, with no screen.

Connects the devices of each Pier's saved profile, holds the controllers per Pier, publishes connection
changes on the event bus, and implements the Control Surface's ``DeviceAccess`` (CSURF-110). It imports no
Qt and nothing from ``galileo.ui``. A device that will not connect is logged, announced as a
``DeviceErrorEvent`` and left out; it never stops the others from connecting (ARCH-060).

After a device connects it is sent the current UTC time and the Observatory's location, and the active
optical tube's focal length and aperture where it takes them, so that a mount knows when and where it is
however it was connected.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from galileo.bus import (
    DeviceConnectedEvent,
    DeviceDisconnectedEvent,
    DeviceErrorEvent,
    EventBus,
    get_bus,
)
from galileo.core.devices import DeviceCategory

logger = logging.getLogger(__name__)

# The Control Surface's category names (CSURF-110) and the device layer's.
CATEGORIES: dict[str, DeviceCategory] = {
    "mount": DeviceCategory.MOUNT, "camera": DeviceCategory.CAMERA,
    "filter_wheel": DeviceCategory.FILTER_WHEEL, "focuser": DeviceCategory.FOCUSER,
    "rotator": DeviceCategory.ROTATOR, "dome": DeviceCategory.DOME,
    "flat_panel": DeviceCategory.FLAT_PANEL, "weather": DeviceCategory.WEATHER_STATION,
    "safety": DeviceCategory.SAFETY_MONITOR, "guider": DeviceCategory.GUIDER,
}
PRIMARY = "primary"


def pier_id(pier: Any) -> str:
    """The text that names a Pier to the Control Surface: its database id."""
    return str(getattr(pier, "id", None) if getattr(pier, "id", None) is not None else pier.name)


def _alpaca_number(label: str) -> int | None:
    m = re.search(r"\(#(\d+)\)\s*$", label or "")
    return int(m.group(1)) if m else None


def make_adapter(category: DeviceCategory, driver: str, server: str, port: int, device_name: str) -> Any:
    """Instantiate (without connecting) the INDI or Alpaca backend for one configured device."""
    if driver == "INDI":
        from galileo.adapters.indi import get_adapter_class
        return get_adapter_class(category)(host=server, port=port, device_name=device_name)
    from galileo.adapters.alpaca import get_adapter_class as alpaca_class
    kwargs: dict[str, Any] = {}
    number = _alpaca_number(device_name)
    if number is not None:
        kwargs["device_number"] = number
    return alpaca_class(category)(host=server, port=port, **kwargs)


class DeviceService:
    def __init__(self, bus: EventBus | None = None,
                 factory: Callable[..., Any] = make_adapter) -> None:
        self._bus = bus or get_bus()
        self._factory = factory
        self._lock = threading.RLock()
        self._adapters: dict[tuple[str, str, str], Any] = {}        # (pier, category, slot) -> adapter
        self._piers: dict[str, Any] = {}                            # pier id -> PierRecord
        self._manual: dict[str, Any] = {}
        self._stoppers: dict[str, Callable[[], Any]] = {}
        self._default_stopper: Callable[[str], Any] | None = None
        self.problems: dict[str, list[str]] = {}                    # pier -> devices that would not connect
        self._cancel = threading.Event()

    # -- Piers --------------------------------------------------------------------------------
    def load_piers(self, observatory: str | None = None) -> list[str]:
        """The Piers of the named Observatory (every Observatory when *observatory* is ``None``); returns their ids."""
        from galileo.observatory import list_observatories, list_piers
        with self._lock:
            self._piers = {pier_id(p): p for o in list_observatories()
                           if observatory is None or o.name == observatory for p in list_piers(o)}
            return list(self._piers)

    def pier_name(self, pier: str) -> str:
        record = self._piers.get(pier)
        return str(getattr(record, "name", pier))

    def pier_ids(self) -> list[str]:
        with self._lock:
            return list(self._piers)

    # -- connecting ---------------------------------------------------------------------------
    async def connect_pier(self, pier: str) -> dict[str, bool]:
        """Connect every device configured for *pier* that is not already connected; returns ``{category/slot: ok}``."""
        record = self._piers.get(pier)
        if record is None:
            raise KeyError(f"unknown Pier {pier!r}")
        from galileo.observatory import list_device_configs
        results: dict[str, bool] = {}
        configs = [c for c in list_device_configs(record) if c.driver and c.server and c.device_name != ""]
        outcomes = await asyncio.gather(*(self._connect_one(pier, c) for c in configs))
        for cfg, ok in zip(configs, outcomes, strict=True):
            results[f"{cfg.category}/{cfg.slot}"] = ok
        await self._push_context(pier)
        return results

    async def connect_startup_piers(self, retry_limit: int = 0, retry_interval_s: float = 0.0) -> dict[str, dict[str, bool]]:
        """Auto-connect every Pier whose profile says *connect on startup* (HEAD-040). A Pier whose devices did not
        all connect is reported in ``problems`` and the journal and tried again up to *retry_limit* more times,
        *retry_interval_s* apart (HEAD-140); ``cancel_retries`` ends the waiting."""
        self._cancel.clear()
        out: dict[str, dict[str, bool]] = {}
        pending = [pid for pid, rec in self._piers.items() if getattr(rec, "connect_on_startup", True)]
        for attempt in range(retry_limit + 1):
            if attempt:
                logger.warning("Retrying the devices of Pier(s) %s (try %d of %d)", ", ".join(pending), attempt, retry_limit)
                await self._wait(retry_interval_s)
                if self._cancel.is_set():
                    break
            still: list[str] = []
            for pid in pending:
                try:
                    out[pid] = await self.connect_pier(pid)
                except Exception:
                    logger.exception("Could not connect the devices of Pier %r", pid)
                    out[pid] = {"*": False}
                failed = sorted(k for k, ok in out[pid].items() if not ok)
                if failed:
                    self.problems[pid] = failed
                    still.append(pid)
                    logger.warning("Pier %s: could not connect %s", pid, ", ".join(failed))
                else:
                    self.problems.pop(pid, None)
            pending = still
            if not pending:
                break
        return out

    async def _wait(self, seconds: float) -> None:
        """Sleep, but in short slices so ``cancel_retries`` ends it promptly."""
        end = time.monotonic() + seconds
        while not self._cancel.is_set() and (left := end - time.monotonic()) > 0:  # noqa: ASYNC110 -- cancelled from another thread
            await asyncio.sleep(min(0.5, left))

    def cancel_retries(self) -> None:
        self._cancel.set()

    async def _connect_one(self, pier: str, cfg: Any) -> bool:
        key = (pier, str(cfg.category).lower(), cfg.slot or PRIMARY)
        existing = self._adapters.get(key)
        if existing is not None and getattr(existing, "is_connected", False):
            return True
        category = self._category_of(cfg.category)
        if category is None:
            logger.warning("Pier %s: unknown device category %r", pier, cfg.category)
            return False
        label = f"{category.value} {cfg.device_name or ''} at {cfg.server}:{cfg.port}"
        try:
            adapter = self._factory(category, cfg.driver, cfg.server, int(cfg.port), cfg.device_name or "")
            await adapter.connect()
        except Exception as exc:                                    # one device never stops the rest
            logger.exception("Could not connect %s", label)
            self._bus.publish(DeviceErrorEvent(source=key[1], pier=pier, slot=key[2], error=str(exc)))
            return False
        with self._lock:
            self._adapters[key] = adapter
            self._manual.pop(pier, None)
        logger.info("Pier %s: connected %s", pier, label)
        self._bus.publish(DeviceConnectedEvent(source=key[1], pier=pier, slot=key[2]))
        return True

    async def connect_device(self, pier: str, category: str, slot: str, driver: str, server: str, port: int,
                             device_name: str, configure: Callable[[Any], None] | None = None) -> Any | None:
        """Build, configure and connect one device from explicit settings (what a screen's Connect button has, as
        opposed to the saved profile ``connect_pier`` reads), and hold it under (*pier*, *category*, *slot*).
        Returns the adapter, or ``None`` after publishing the error. A device already held there is
        disconnected first, so a slot never has two."""
        cat = self._category_of(category)
        if cat is None:
            logger.warning("Pier %s: unknown device category %r", pier, category)
            return None
        label = f"{cat.value} {device_name or ''} at {server}:{port}"
        try:
            adapter = self._factory(cat, driver, server, int(port), device_name or "")
            if configure is not None:
                configure(adapter)
            await adapter.connect()
        except Exception as exc:
            logger.exception("Could not connect %s", label)
            self._bus.publish(DeviceErrorEvent(source=cat.value.lower(), pier=pier, slot=slot or PRIMARY, error=str(exc)))
            return None
        self.adopt(pier, cat.value.lower(), slot, adapter)
        logger.info("Pier %s: connected %s", pier, label)
        return adapter

    def adopt(self, pier: str, category: str, slot: str, adapter: Any) -> None:
        """Hold an adapter some other code connected, so everything that asks the service for it finds it."""
        key = (pier, category.lower(), slot or PRIMARY)
        with self._lock:
            previous = self._adapters.get(key)
            self._adapters[key] = adapter
            self._manual.pop(pier, None)
        if previous is not None and previous is not adapter:
            logger.warning("Pier %s: %s/%s replaced by a new connection", pier, key[1], key[2])
        self._bus.publish(DeviceConnectedEvent(source=key[1], pier=pier, slot=key[2]))

    def release(self, adapter: Any) -> bool:
        """Stop holding *adapter* (it was disconnected elsewhere); ``False`` when the service did not hold it."""
        with self._lock:
            keys = [k for k, a in self._adapters.items() if a is adapter]
            for key in keys:
                del self._adapters[key]
                self._manual.pop(key[0], None)
        for key in keys:
            self._bus.publish(DeviceDisconnectedEvent(source=key[1], pier=key[0], slot=key[2]))
        return bool(keys)

    @staticmethod
    def _category_of(name: str) -> DeviceCategory | None:
        text = str(name)
        for cat in DeviceCategory:
            if text == cat.value or text.lower().replace("_", "") == cat.value.lower():
                return cat
        return CATEGORIES.get(text.lower())

    async def disconnect_pier(self, pier: str) -> None:
        with self._lock:
            keys = [k for k in self._adapters if k[0] == pier]
            adapters = [(k, self._adapters.pop(k)) for k in keys]
            self._manual.pop(pier, None)
        for key, adapter in adapters:
            try:
                await adapter.disconnect()
            except Exception:
                logger.exception("Pier %s: %s did not disconnect cleanly", pier, key[1])
            self._bus.publish(DeviceDisconnectedEvent(source=key[1], pier=pier, slot=key[2]))

    async def disconnect_all(self) -> None:
        for pid in self.pier_ids():
            await self.disconnect_pier(pid)

    async def _push_context(self, pier: str) -> None:
        """Send time and site (and optics) to the Pier's connected devices; best effort."""
        record = self._piers.get(pier)
        site: dict[str, Any] = {}
        try:
            obs = record.observatory
            site = {"latitude": obs.latitude, "longitude": obs.longitude,
                    "elevation": getattr(obs, "elevation_m", None)}
        except Exception:
            logger.exception("Could not read the Observatory location for Pier %s", pier)
        for key, adapter in list(self._adapters.items()):
            if key[0] != pier or not hasattr(adapter, "push_context"):
                continue
            try:
                await adapter.push_context(**site)
            except Exception:
                logger.exception("Pier %s: could not send time and site to the %s", pier, key[1])

    # -- DeviceAccess (CSURF-110) -------------------------------------------------------------------
    def controller(self, pier: str, category: str, slot: str = PRIMARY) -> Any | None:
        with self._lock:
            return self._adapters.get((pier, category.lower(), slot)) or next(
                (a for (p, c, _s), a in self._adapters.items() if p == pier and c == category.lower()), None)

    def controllers(self, pier: str, category: str) -> dict[str, Any]:
        """Every adapter held for *pier* in *category*, by slot."""
        with self._lock:
            return {s: a for (p, c, s), a in self._adapters.items() if p == pier and c == category.lower()}

    def connected(self, pier: str) -> list[str]:
        with self._lock:
            return sorted(f"{c}/{s}" for (p, c, s), a in self._adapters.items()
                          if p == pier and getattr(a, "is_connected", False))

    def manual_focus(self, pier: str) -> Any | None:
        focuser = self.controller(pier, "focuser")
        if focuser is None:
            return None
        with self._lock:
            mf = self._manual.get(pier)
            if mf is None:
                from galileo.autofocus import ManualFocus
                from galileo.observatory import get_focuser_settings
                s = get_focuser_settings(self._piers.get(pier))
                mf = self._manual[pier] = ManualFocus(focuser, travel_min=s.travel_min, travel_max=s.travel_max,
                                                      pier_key=pier)
            return mf

    def set_session_stopper(self, pier: str, stop: Callable[[], Any]) -> None:
        """The session runner (HEAD-050) registers how to stop a Pier's session."""
        self._stoppers[pier] = stop

    def set_default_session_stopper(self, stop: Callable[[str], Any]) -> None:
        """How to stop any Pier's session when none was registered for that Pier (the engine's runner)."""
        self._default_stopper = stop

    def stop_session(self, pier: str) -> Any:
        stop = self._stoppers.get(pier)
        if stop is not None:
            return stop()
        return self._default_stopper(pier) if self._default_stopper is not None else None


__all__ = ["CATEGORIES", "DeviceService", "make_adapter", "pier_id"]
