# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Galileo engine: Galileo's domain core with no display (HEAD-010).

``Galileo --engine`` runs this. It imports nothing from ``galileo.ui`` and nothing from ``PySide6``
(``tests/test_head.py`` checks that in a subprocess), so it runs on a controller with no screen.

This is the first step of the engine (SDD §4.33): the composition root, the single-engine lock and the
service run. The device service (HEAD-040) is in; the session runner, the Pier helpers, safety and the watchdog join it in the
later steps; until then they are still held by the desktop.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from collections.abc import Sequence
from typing import Any

from galileo.engine.lock import EngineAlreadyRunning, EngineLock
from galileo.engine.service import EXIT_ALREADY_RUNNING, StopSignal, run_until_stopped

logger = logging.getLogger(__name__)


class Engine:
    """Owns what the engine starts and stops, in order. Safe to ``stop()`` after a partial ``start()``."""

    def __init__(self, lock: EngineLock | None = None, *, embedded: bool = False, devices: Any = None) -> None:
        """*embedded* is for a desktop that hosts the engine (HEAD-090): the desktop already opened the database,
        loaded plugins, installed crash reporting, connects its own devices and runs its own watchdog, so the engine
        takes the lock, serves the channel and Control Surface over *devices* (the desktop's device service) and
        starts none of those. It also leaves the devices connected when it stops: they are the desktop's."""
        self.lock = lock or EngineLock()
        self.embedded = embedded
        self._shared_devices = devices
        self.plugin_manager: Any = None
        self.devices: Any = None
        self.runner: Any = None
        self.state: Any = None
        self.helpers: Any = None
        self.leases: Any = None
        self.gateway: Any = None
        self.channel: Any = None
        self.feed: Any = None
        self.guiding: Any = None
        self._channel_loop: asyncio.AbstractEventLoop | None = None
        self._channel_thread: threading.Thread | None = None
        self.registry: Any = None
        self.config: Any = None
        self.guard: Any = None
        self.observatory: str | None = None
        self._connecting: threading.Thread | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.lock.acquire(role="desktop" if self.embedded else "engine")   # HEAD-020: before touching any device

        if not self.embedded:
            from galileo.crashreport import install_crash_handlers
            install_crash_handlers()              # no dialog: there is no screen

            from galileo.library.database import init_db
            init_db()

            from galileo.plugins import PluginManager
            self.plugin_manager = PluginManager()
            self.plugin_manager.initialize_from_disk()

        self._start_devices()                     # HEAD-040
        self._started = True

    def _start_devices(self) -> None:
        """The device service and the Control Surface's device operations; auto-connect runs in the background
        so a device that is slow or missing never delays the engine being ready."""
        from galileo.control_surface import Registry
        from galileo.control_surface.catalogue import register_device_operations
        from galileo.engine.devices import DeviceService

        from galileo.engine.runner import SessionRunner

        self.devices = self._shared_devices if self._shared_devices is not None else DeviceService()
        self.runner = SessionRunner()                       # HEAD-050
        self.devices.set_default_session_stopper(self.runner.stop)
        from galileo.engine.config import load_config, resolve_observatory
        from galileo.observatory import list_observatories

        self.config = load_config()                         # HEAD-130: from the database
        self.observatory = resolve_observatory(self.config, [o.name for o in list_observatories()])
        self.devices.load_piers(self.observatory)           # HEAD-140
        from galileo.control_surface import ObservableState
        from galileo.engine.helpers import Helpers

        self.state = ObservableState()
        self.registry = Registry()
        register_device_operations(self.registry, self.devices)
        from galileo.control_surface.sessions import register_session_operations
        from galileo.engine.sessions import EngineSessions
        from galileo.engine.guiding import EngineGuiding
        self.guiding = EngineGuiding(self.devices, self.state)
        sessions = EngineSessions(self.devices, self.runner, self.guiding)
        register_session_operations(self.registry, sessions)                                      # CSURF-180
        from galileo.control_surface.piers import EnginePiers, register_pier_operations
        register_pier_operations(self.registry, EnginePiers(self.devices, sessions))             # CSURF-100
        from galileo.control_surface.imaging import register_imaging_operations
        from galileo.engine.imaging import EngineImaging
        register_imaging_operations(self.registry, EngineImaging(self.devices, self.runner))      # CSURF-120
        from galileo.control_surface.flips import register_flip_operations
        from galileo.engine.flips import EngineFlips
        register_flip_operations(self.registry, EngineFlips(self.devices, self.runner))           # CSURF-170
        from galileo.control_surface.solve import register_solve_operations
        from galileo.engine.solve import EngineSolve
        register_solve_operations(self.registry, EngineSolve(self.devices, self.runner))          # CSURF-140
        from galileo.control_surface.guiding import register_guiding_operations
        register_guiding_operations(self.registry, self.guiding)                                  # CSURF-160
        from galileo.control_surface.sky import register_sky_operations
        from galileo.engine.sky import EngineSky
        register_sky_operations(self.registry, EngineSky(self.devices))                           # CSURF-130
        from galileo.control_surface.history import StoreHistory, register_history_operations
        register_history_operations(self.registry, StoreHistory())                                # CSURF-230
        from galileo.control_surface.schedule import StoredSchedule, register_schedule_operations
        register_schedule_operations(self.registry, StoredSchedule(self.devices.pier_name))      # CSURF-200
        if not self.embedded:                                # the desktop has its own pointing helpers and watchdog
            self.helpers = Helpers(self.devices, self.state)    # HEAD-060
            self.helpers.start()
            from galileo.engine.guard import Guard, build_watchdog

            self.guard = Guard(self.devices, self.runner, watchdog=build_watchdog(self.devices))   # HEAD-160
            self.guard.start()
            from galileo.control_surface.safety import GuardSafety, register_safety_operations
            register_safety_operations(self.registry, GuardSafety(self.guard))                   # CSURF-220
        self._start_channel()                                # HEAD-080
        from galileo.bus import get_bus
        from galileo.replication import SettingsChanged
        get_bus().subscribe(SettingsChanged, self._on_settings_changed)    # HEAD-130
        if self.embedded:
            return                                           # the desktop connects its devices itself
        self._connecting = threading.Thread(
            target=lambda: asyncio.run(self.devices.connect_startup_piers(
                self.config.retry_limit, self.config.retry_interval_s)), name="engine-connect", daemon=True)
        self._connecting.start()

    def stop(self) -> None:
        """Stop in the reverse order of ``start``. Each step is isolated so a failure in one never skips the rest."""
        steps = (
            ("Connect Link", self._stop_link),
            ("devices", self._stop_devices),
            ("CPU workers", self._stop_workers),
        )
        if self.embedded:                         # the desktop shuts those down itself
            steps = (("devices", self._stop_devices),)
        for name, step in steps:
            try:
                step()
            except Exception:
                logger.exception("Stopping %s failed", name)
        self._started = False
        self.lock.release()

    def _start_channel(self) -> None:
        """The lease, the request pipeline and the local channel a desktop attaches to."""
        from galileo import __version__
        from galileo.bus import get_bus
        from galileo.connect_link.audit import AuditLog
        from galileo.connect_link.gateway import Gateway
        from galileo.control_surface import LeaseBroker
        from galileo.engine.channel import EngineChannel
        from galileo.platform import get_data_dir

        bus = get_bus()
        self.leases = LeaseBroker(bus=bus)
        self.gateway = Gateway(self.registry, self.leases, AuditLog())
        self.channel = EngineChannel(
            registry=self.registry, leases=self.leases, gateway=self.gateway, state=self.state, devices=self.devices,
            bus=bus, version=__version__, directory=get_data_dir() / "engine", status_extra=self._status_extra)
        loop = asyncio.new_event_loop()
        self._channel_loop = loop
        self._channel_thread = threading.Thread(target=loop.run_forever, name="engine-channel", daemon=True)
        self._channel_thread.start()
        info = asyncio.run_coroutine_threadsafe(self.channel.start(), loop).result(30)
        self.lock.update(channel=info)
        from galileo.control_surface.feed import EventFeed
        from galileo.control_surface.service import ControlSurfaceService, publish_control_surface
        self.feed = EventFeed(state=self.state, leases=self.leases, bus=bus, pier_ids=self.devices.pier_ids)
        publish_control_surface(ControlSurfaceService(                  # CSURF-250: front-end plugins use these objects
            registry=self.registry, leases=self.leases, gateway=self.gateway, state=self.state,
            piers=lambda: asyncio.run_coroutine_threadsafe(self.channel._piers_list(), loop).result(10),
            feed=self.feed))                                            # CSURF-260

    def _on_settings_changed(self, _event: Any) -> None:
        """An Options change reached the database: read the engine's own settings again. A different Observatory
        takes effect at the next start, because changing it under a running session would be unsafe."""
        from galileo.engine.config import load_config
        self.config = load_config()
        logger.info("Engine settings reloaded")

    def _status_extra(self) -> dict[str, Any]:
        runner = self.runner
        return {"sessions": runner.snapshot() if runner is not None else [], "observatory": self.observatory,
                "problems": dict(self.devices.problems) if self.devices is not None else {},
                **(self.guard.status() if self.guard is not None else {})}

    def _stop_channel(self) -> None:
        loop, self._channel_loop = self._channel_loop, None
        from galileo.control_surface.service import withdraw_control_surface
        withdraw_control_surface()
        feed, self.feed = self.feed, None
        if feed is not None:
            feed.close()
        if loop is None:
            return
        if self.channel is not None:
            asyncio.run_coroutine_threadsafe(self.channel.stop(), loop).result(30)
        loop.call_soon_threadsafe(loop.stop)
        if self._channel_thread is not None:
            self._channel_thread.join(5)

    def _stop_devices(self) -> None:
        from galileo.bus import get_bus
        from galileo.replication import SettingsChanged
        get_bus().unsubscribe(SettingsChanged, self._on_settings_changed)
        self._stop_channel()
        if self.guard is not None:
            self.guard.stop()                         # disarmed first: a normal stop never parks the mount
        if self.helpers is not None:
            self.helpers.stop()
        if self.runner is not None:
            self.runner.shutdown()                    # sessions end before their devices are disconnected
        if self.guiding is not None:
            self.guiding.close()                      # after the sessions that might still be guiding
        if self.devices is not None:
            self.devices.cancel_retries()
            if self._connecting is not None:
                self._connecting.join(timeout=30)
            if not self.embedded:
                asyncio.run(self.devices.disconnect_all())

    @staticmethod
    def _stop_link() -> None:
        from galileo.connect_link.host import shutdown_host
        shutdown_host()

    @staticmethod
    def _stop_workers() -> None:
        from galileo.core.compute import shutdown_cpu_executor
        shutdown_cpu_executor(wait=False)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``Galileo --engine``. Returns the process exit code."""
    import multiprocessing
    multiprocessing.freeze_support()

    from galileo.diagnostics import DiagnosticsService
    DiagnosticsService()
    logging.getLogger().setLevel(logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")

    if "--status" in (argv or ()):
        from galileo.engine.status import status_main
        return status_main(json_output="--json" in argv)

    from galileo import __version__
    logger.info("Galileo engine %s starting", __version__)
    engine = Engine()
    try:
        engine.lock.acquire(role="engine")
        engine.lock.release()                     # a quick check so a refusal says so before any start-up work
    except EngineAlreadyRunning as exc:
        logger.error("%s", exc)  # noqa: TRY400 -- a refusal, not a fault: no traceback wanted
        print(exc, file=sys.stderr)
        return EXIT_ALREADY_RUNNING
    return run_until_stopped(engine.start, engine.stop, StopSignal())


__all__ = ["Engine", "main"]
