# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The engine's background helpers (HEAD-060): mount pointing, slew-then-track and weather history.

These lived on the desktop window; here they run on the engine and publish what they learn as Control Surface
state (CSURF-060), so the desktop and every remote client read the same values:

* ``mount.position`` — ``{"ra_deg", "dec_deg", "slewing"}`` in J2000, or ``None`` when the mount cannot be read;
* ``mount.tracking`` — the rate set after a slew (``sidereal``, ``solar``, ``lunar``), or ``None`` while slewing;
* ``weather.readings`` — the latest readings of the Pier's weather station.

Weather history is kept per Pier for the trend display (``weather_history``). A helper that fails is logged and
skipped for that Pier at that tick; one Pier or device never stops another (ARCH-060).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from concurrent.futures import Future
from typing import Any

logger = logging.getLogger(__name__)

POINTING_INTERVAL_S = 2.0
WEATHER_INTERVAL_S = 60.0
HISTORY_MAX_SAMPLES = 1000


class Helpers:
    def __init__(self, devices: Any, state: Any, pointing_s: float = POINTING_INTERVAL_S,
                 weather_s: float = WEATHER_INTERVAL_S) -> None:
        self._devices, self._state = devices, state
        self._pointing_s, self._weather_s = pointing_s, weather_s
        self._history: dict[str, deque[tuple[float, dict]]] = {}
        self._tracking: dict[str, Future] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task | None = None

    # -- pointing ------------------------------------------------------------------------------
    async def poll_pointing(self) -> None:
        for pier in self._devices.pier_ids():
            mount = self._devices.controller(pier, "mount")
            if mount is None or not getattr(mount, "is_connected", False):
                self._state.publish(pier, "mount.position", None)
                continue
            try:
                status = await mount.get_status() or {}
                ra_hours, dec = status.get("right_ascension"), status.get("declination")
                if ra_hours is None or dec is None:
                    self._state.publish(pier, "mount.position", None)
                    continue
                from galileo.platesolve import mount_frame_to_j2000
                ra_deg, dec_deg = mount_frame_to_j2000(ra_hours * 15.0, dec, status.get("equatorial_system"))
                self._state.publish(pier, "mount.position", {
                    "ra_deg": ra_deg, "dec_deg": dec_deg, "slewing": bool(status.get("slewing"))})
            except Exception:
                logger.debug("Could not read the mount of Pier %s", pier, exc_info=True)
                self._state.publish(pier, "mount.position", None)    # a mount that cannot be read is forgotten

    # -- slew then track -----------------------------------------------------------------------------
    def slew_then_track(self, pier: str, target: Any = None) -> Future | None:
        """Once the slew just started finishes, track at the rate *target* needs (EQP-MNT-050). One wait per
        Pier: a second request while one is waiting is ignored (the later slew wins by finishing later). Returns
        a future for the rate set (``None`` if the mount never settled), or ``None`` if nothing was started."""
        mount, loop = self._devices.controller(pier, "mount"), self._loop
        waiting = self._tracking.get(pier)
        if mount is None or loop is None or (waiting is not None and not waiting.done()):
            return None

        async def wait() -> str | None:
            from galileo.tracking import resume_tracking
            self._state.publish(pier, "mount.tracking", None)
            try:
                rate = await resume_tracking(mount, target)
            except Exception:
                logger.exception("Could not start tracking on Pier %s after the slew", pier)
                return None
            self._state.publish(pier, "mount.tracking", rate)
            return rate

        future = asyncio.run_coroutine_threadsafe(wait(), loop)
        self._tracking[pier] = future
        return future

    # -- weather ------------------------------------------------------------------------------------
    async def poll_weather(self) -> None:
        from galileo.core.devices import WeatherController
        for pier in self._devices.pier_ids():
            adapter = self._devices.controller(pier, "weather")
            if adapter is None or not getattr(adapter, "is_connected", False):
                continue
            try:
                controller = WeatherController(adapter)
                await controller.poll()
                readings = dict(controller.get_readings())
            except Exception:
                logger.exception("Could not read the weather station of Pier %s", pier)
                continue
            history = self._history.setdefault(pier, deque(maxlen=HISTORY_MAX_SAMPLES))
            history.append((time.time(), readings))
            self._state.publish(pier, "weather.readings", readings)

    def weather_history(self, pier: str) -> list[tuple[float, dict]]:
        return list(self._history.get(pier, ()))

    # -- the loop --------------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        async def run() -> None:
            next_weather = 0.0
            while True:
                await self.poll_pointing()
                if time.monotonic() >= next_weather:
                    await self.poll_weather()
                    next_weather = time.monotonic() + self._weather_s
                await asyncio.sleep(self._pointing_s)

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

        self._loop = loop
        self._thread = threading.Thread(target=serve, name="engine-helpers", daemon=True)
        self._thread.start()
        ready.wait(5)

    def stop(self) -> None:
        loop, task, thread = self._loop, self._task, self._thread
        self._loop = self._task = self._thread = None
        if loop is not None and task is not None:
            loop.call_soon_threadsafe(task.cancel)
        if thread is not None:
            thread.join(10)


__all__ = ["HISTORY_MAX_SAMPLES", "Helpers"]
