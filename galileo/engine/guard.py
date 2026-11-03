# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Safety and the watchdog in the engine (HEAD-160): they run whether or not any screen or client is attached.

``Guard`` has one loop on its own thread. Every second it beats the crash/hang watchdog (``SAFE-060``), which has
its own thread and so still fires if this loop hangs; every ``interval_s`` it polls each Pier's safety monitor.
When a monitor reports unsafe (or a connected monitor cannot be read, which counts as unsafe), the Pier is acted
on once for that episode: its running session is stopped and its mount is parked. A ``SafetyUnsafeEvent`` reaches
the bus, as the desktop's own monitor does, so notifications and attached clients see it. When the monitor
reports safe again the episode ends; resuming is a person's decision (``SAFE-040``), not the guard's.

The guard imports nothing from Qt. The watchdog's e-mail / SMS notification is still built by the desktop and is
not part of this step.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

SAFETY_INTERVAL_S = 10.0


class Guard:
    def __init__(self, devices: Any, runner: Any, interval_s: float = SAFETY_INTERVAL_S,
                 watchdog: Any = None, bus: Any = None) -> None:
        self._devices, self._runner, self._interval_s = devices, runner, interval_s
        self.watchdog = watchdog
        self._bus = bus
        self.unsafe: dict[str, str] = {}                           # pier -> why it is unsafe right now
        self._acted: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task | None = None

    # -- one check -------------------------------------------------------------------------------
    async def check_once(self) -> None:
        for pier in self._devices.pier_ids():
            monitor = self._devices.controller(pier, "safety")
            if monitor is None or not getattr(monitor, "is_connected", False):
                self.unsafe.pop(pier, None)                        # nothing to gate on (as the scheduler's rule)
                self._acted.discard(pier)
                continue
            try:
                await monitor.poll()
                safe, why = bool(monitor.is_safe), str(getattr(monitor, "explanation", "") or "")
            except Exception:
                logger.exception("Could not read the safety monitor of Pier %s", pier)
                safe, why = False, "the safety monitor could not be read"
            if safe:
                self.unsafe.pop(pier, None)
                self._acted.discard(pier)
                continue
            self.unsafe[pier] = why or "the safety monitor reports unsafe conditions"
            if pier not in self._acted:
                self._acted.add(pier)
                await self._act(pier, self.unsafe[pier])

    async def _act(self, pier: str, why: str) -> None:
        logger.warning("Pier %s is unsafe (%s): stopping its session and parking the mount", pier, why)
        try:
            self._runner.stop(pier)
        except Exception:
            logger.exception("Pier %s: could not stop the session", pier)
        mount = self._devices.controller(pier, "mount")
        if mount is not None and getattr(mount, "is_connected", False):
            try:
                await mount.park()
            except Exception:
                logger.exception("Pier %s: could not park the mount", pier)
        from galileo.bus import SafetyUnsafeEvent, get_bus
        (self._bus or get_bus()).publish(SafetyUnsafeEvent(source=f"pier:{pier}", pier=pier, explanation=why))

    def status(self) -> dict[str, Any]:
        wd = self.watchdog
        return {"unsafe": dict(self.unsafe), "watchdog": wd.status if wd is not None else "off"}

    # -- the loop ----------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        loop, ready = asyncio.new_event_loop(), threading.Event()

        async def run() -> None:
            next_check = 0.0
            while True:
                if self.watchdog is not None and not self.watchdog.tripped:
                    self.watchdog.heartbeat()
                if time.monotonic() >= next_check:
                    await self.check_once()
                    next_check = time.monotonic() + self._interval_s
                await asyncio.sleep(1.0)

        def serve() -> None:
            asyncio.set_event_loop(loop)
            self._task = loop.create_task(run())
            loop.call_soon(ready.set)
            try:
                loop.run_until_complete(self._task)
            except asyncio.CancelledError:
                pass
            finally:
                loop.close()

        if self.watchdog is not None:
            self.watchdog.start()
        self._loop = loop
        self._thread = threading.Thread(target=serve, name="engine-guard", daemon=True)
        self._thread.start()
        ready.wait(5)

    def stop(self) -> None:
        """Disarm the watchdog first, so a normal shutdown never parks the mount."""
        if self.watchdog is not None:
            self.watchdog.stop_sync()
        loop, task, thread = self._loop, self._task, self._thread
        self._loop = self._task = self._thread = None
        if loop is not None and task is not None:
            loop.call_soon_threadsafe(task.cancel)
        if thread is not None:
            thread.join(10)


async def _each(devices: Any, category: str, method: str) -> None:
    for pier in devices.pier_ids():
        adapter = devices.controller(pier, category)
        if adapter is not None and getattr(adapter, "is_connected", False):
            try:
                await getattr(adapter, method)()
            except Exception:
                logger.exception("Watchdog: Pier %s: %s of the %s failed", pier, method, category)


def build_watchdog(devices: Any, bus: Any = None) -> Any:
    """The watchdog the saved settings ask for, or ``None`` when it is switched off. Devices are looked up when it
    trips, so ones connected after start-up are covered, on every Pier."""
    from galileo.safety import WatchdogService
    from galileo.watchdog_settings import load_watchdog_settings

    settings = load_watchdog_settings()
    if not settings["enabled"]:
        return None

    class _EveryPier:
        """Parks every Pier's mount and closes every Pier's dome, whichever are connected when it trips."""

        async def park(self) -> None:
            await _each(devices, "mount", "park")

        async def close_shutter(self) -> None:
            await _each(devices, "dome", "close_shutter")

    from galileo.bus import get_bus
    return WatchdogService(mount=_EveryPier(), dome=_EveryPier(),
                           timeout_s=settings["timeout_s"], event_bus=bus or get_bus())


__all__ = ["SAFETY_INTERVAL_S", "Guard", "build_watchdog"]
