# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Safety and the watchdog in the engine (HEAD-160): they run whether or not any screen or client is attached.

``Guard`` is the engine's side of ``galileo.safety_supervisor`` (SAFE-180): it tells the supervisor what the engine
holds, connects the Observatory's safety devices, gives it the engine's activities to stop, and has one loop on its
own thread that calls it. The same thread beats the crash/hang watchdog (``SAFE-060``), which has a thread of its own.

The guard imports nothing from Qt.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from galileo.safety_supervisor import DatabaseStore, Roof, SafetySupervisor, Site, Source, State

logger = logging.getLogger(__name__)

SAFETY_INTERVAL_S = 10.0
_DEVICE_CATEGORY = {"weather": "weather", "safety_monitor": "safety"}


class Guard:
    def __init__(self, devices: Any, runner: Any, interval_s: float = SAFETY_INTERVAL_S,
                 watchdog: Any = None, bus: Any = None, *, guiding: Any = None, notify: Any = None,
                 store: Any = None, settings: Any = None, clock: Any = time.monotonic) -> None:
        self._devices, self._runner, self._interval_s = devices, runner, interval_s
        self.watchdog = watchdog
        self._guiding = guiding
        self._observatory_adapters: dict[str, Any] = {}      # "category:slot" -> the Observatory's safety device
        self._site = Site()
        self.supervisor = SafetySupervisor(
            lambda: self._site, scope=str(getattr(self._observatory(), "id", "") or ""), settings=settings,
            notify=notify, store=store if store is not None else DatabaseStore(), bus=bus, clock=clock)
        self.activities = self.supervisor.activities
        self.activities.register("sessions", self._stop_sessions)
        self.activities.register("devices", self._abort_devices)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task | None = None

    # -- what the engine holds ----------------------------------------------------------------------
    def _record(self, pier: str) -> Any:
        try:
            return self._devices.pier_record(pier)
        except Exception:
            return None

    def _observatory(self) -> Any:
        home = getattr(self._devices, "home_observatory", None)
        try:
            for pier in self._devices.pier_ids():
                observatory = getattr(self._record(pier), "observatory", None)
                if observatory is not None and (home is None or observatory.name == home):
                    return observatory
        except Exception:
            logger.debug("Could not find the engine's Observatory", exc_info=True)
        return None

    async def _observatory_sources(self, observatory: Any) -> list:
        """The Observatory's saved safety devices (OBS-030), connecting any that are not held."""
        if observatory is None:
            if self.supervisor.scope:      # not found this time is not the same as having no safety devices
                raise RuntimeError("the engine's Observatory could not be read")
            return []
        from galileo.observatory import get_safety_device_config, get_weather_safety_rules, registered_safety_slots
        from galileo.safety import default_weather_safety_rules
        found = []
        for kind, category in _DEVICE_CATEGORY.items():
            for slot in registered_safety_slots(observatory, kind):
                key = f"{kind}:{slot}"
                adapter = self._observatory_adapters.get(key)
                if adapter is None or getattr(adapter, "is_connected", True) is False:
                    adapter = await self._connect(category, get_safety_device_config(observatory, kind, slot))
                    self._observatory_adapters[key] = adapter
                rules = []
                if kind == "weather":
                    rules = get_weather_safety_rules(observatory, slot) or default_weather_safety_rules()
                name = "weather station" if kind == "weather" else "safety monitor"
                found.append(Source(key=key, name=name if slot == "primary" else f"{name} ({slot})", kind=kind,
                                    adapter=adapter, rules=rules))
        return found

    async def _connect(self, category: str, config: Any) -> Any | None:
        try:
            adapter = self._devices.build_adapter(category, config.driver, config.server, config.port,
                                                  config.device_name or "")
            await asyncio.wait_for(adapter.connect(), 30)
            return adapter
        except Exception:
            logger.warning("Could not connect the Observatory's %s", category, exc_info=True)
            return None

    async def _build_site(self) -> Site:
        from galileo.engine.sessions import mounts_under_roof
        sources = await self._observatory_sources(self._observatory())
        guiders, roofs, own = [], [], []
        mounts = mounts_under_roof(self._devices)
        for pier in self._devices.pier_ids():
            record = self._record(pier)
            name = getattr(record, "name", "") or pier
            # A monitor saved on a Pier (as the engine's device service holds it) counts as well.
            monitor = self._devices.controller(pier, "safety")
            if monitor is not None and not any(s.adapter is monitor for s in sources + own):
                own.append(Source(key=f"pier:{pier}", name="safety monitor", kind="safety_monitor", adapter=monitor))
            if self._guiding is not None:
                guider = self._guiding.service(pier)
                if guider is not None and getattr(guider, "is_connected", False):
                    guiders.append((name, guider))
            dome = self._devices.controller(pier, "dome")
            configured = False
            try:
                from galileo.observatory import get_device_config
                configured = record is not None and get_device_config(record, "dome") is not None
            except Exception:
                logger.debug("Pier %s: could not read its dome configuration", pier, exc_info=True)
            if dome is not None or configured:
                roofs.append(Roof(name=f"the dome of {name}", dome=dome, mounts=mounts))
        connected = [r for r in roofs if r.dome is not None]
        return Site(sources=sources + own, mounts=mounts, guiders=guiders, roofs=connected or roofs)

    # -- stopping ------------------------------------------------------------------------------------
    async def _stop_sessions(self) -> None:
        for pier in self._devices.pier_ids():
            stop = getattr(self._runner, "stop_for_safety", None) or self._runner.stop
            try:
                stop(pier)
            except Exception:
                logger.exception("Pier %s: could not stop the session", pier)
        running = getattr(self._runner, "is_running", None)
        while running is not None and running():      # noqa: ASYNC110 - runs end on their own threads
            await asyncio.sleep(0.5)

    async def _abort_devices(self) -> None:
        for pier in self._devices.pier_ids():
            for category, method in (("camera", "abort_exposure"), ("mount", "abort_slew")):
                device = self._devices.controller(pier, category)
                if device is not None and getattr(device, method, None) is not None:
                    try:
                        await asyncio.wait_for(getattr(device, method)(), 10)
                    except Exception:
                        logger.debug("Pier %s: %s failed during the safety stop", pier, method, exc_info=True)

    # -- one check -----------------------------------------------------------------------------------
    async def check_once(self) -> None:
        self._site = await self._build_site()
        await self.supervisor.tick()

    # -- what clients see (CSURF-220) ------------------------------------------------------------------
    @property
    def unsafe(self) -> dict[str, str]:
        """Pier -> why it is unsafe right now."""
        verdict = self.supervisor.verdict
        why = "; ".join(verdict.reasons)
        return dict.fromkeys(self._devices.pier_ids(), why) if verdict.blocking else {}

    @property
    def events(self) -> list[dict[str, Any]]:
        """The protective stops, newest last, one entry per Pier (they apply to the whole Observatory)."""
        found = []
        for record in self.supervisor.history():
            for pier in self._devices.pier_ids():
                found.append({"id": record["id"], "pier": pier, "why": record["reason"], "at": record["at"],
                              "outcome": record["outcome"], "problems": record["problems"],
                              "acknowledged_by": record["acknowledged_by"],
                              "acknowledged_at": record["acknowledged_at"]})
        return found

    def pending(self, pier: str) -> list[dict[str, Any]]:
        """The Pier's safety stops nobody has acknowledged yet."""
        if self.supervisor.state == State.READY:
            return []
        return [e for e in self.events if e["pier"] == pier and not e["acknowledged_by"]]

    def acknowledge(self, pier: str, who: str) -> int:
        """Acknowledge the protective stop (SAFE-040); raises ``ValueError`` while conditions are unsafe or have not
        been safe long enough. It restarts nothing."""
        waiting = len(self.pending(pier))
        if waiting:
            self.supervisor.acknowledge(who)
        return waiting

    def status(self) -> dict[str, Any]:
        wd = self.watchdog
        return {"unsafe": self.unsafe, "watchdog": wd.status if wd is not None else "off",
                "safety": self.supervisor.status()}

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
                    try:
                        await self.check_once()
                    except Exception:
                        logger.exception("The safety check failed")
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
    from galileo.engine.sessions import mounts_under_roof
    return WatchdogService(mount=_EveryPier(), dome=_EveryPier(), roof_mounts=lambda: mounts_under_roof(devices),
                           timeout_s=settings["timeout_s"], event_bus=bus or get_bus())


__all__ = ["SAFETY_INTERVAL_S", "Guard", "build_watchdog"]
