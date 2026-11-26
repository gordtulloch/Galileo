# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The desktop's side of the protective stop (``galileo.safety_supervisor``).

The supervisor runs on its own thread and may not touch widgets, so this object, on the UI thread, publishes a
snapshot of what is connected, stops the screens' activities when asked, and shows the banner that says a stop is
in force (SAFE-170).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from galileo.safety_supervisor import (
    DatabaseStore,
    Roof,
    SafetySettings,
    SafetySupervisor,
    Site,
    State,
    load_settings,
)

logger = logging.getLogger(__name__)

REFRESH_MS = 5000
SESSION_END_TIMEOUT_S = 25.0


def register_stopper(window: Any, name: str, stop: Callable[[], None]) -> None:
    """A screen registers how to stop whatever it is doing with equipment. *stop* runs on the UI thread."""
    stoppers = getattr(window, "_safety_stoppers", None)
    if stoppers is None:
        stoppers = window._safety_stoppers = {}
    stoppers[name] = stop


def safety_holding(window: Any) -> bool:
    """Whether safety forbids starting automatic motion now (meridian flips, dome slaving)."""
    host = getattr(window, "_safety_host", None)
    return host is not None and host.holding()


class _UiCall(QObject):
    """Run a function on the UI thread from the supervisor's thread."""

    requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.requested.connect(self._invoke, Qt.ConnectionType.QueuedConnection)

    def _invoke(self, job: Any) -> None:
        function, future = job
        try:
            future.set_result(function())
        except Exception as exc:
            future.set_exception(exc)

    def submit(self, function: Callable[[], Any]) -> concurrent.futures.Future:
        future: concurrent.futures.Future = concurrent.futures.Future()
        if QThread.currentThread() is self.thread():
            self._invoke((function, future))
        else:
            self.requested.emit((function, future))
        return future


class SafetyHost(QObject):
    def __init__(self, window: Any, store: Any = None) -> None:
        super().__init__()
        self._window = window
        self._store = store if store is not None else DatabaseStore()
        self._ui = _UiCall()
        self._lock = threading.Lock()
        self._site = Site()
        self._notify_service: Any = None
        self._supervisors: dict[str, SafetySupervisor] = {}
        self.supervisor: SafetySupervisor | None = None
        self.banner: QFrame | None = None
        self._banner_label: QLabel | None = None
        self._ack_button: QPushButton | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._run_thread = True

    # -- lifecycle ---------------------------------------------------------------------------------

    def start(self, run_thread: bool = True) -> None:
        self._run_thread = run_thread
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        for supervisor in self._supervisors.values():
            supervisor.stop()

    # -- UI thread: what is connected ----------------------------------------------------------------

    def _scope(self) -> str:
        return str(self._window._safety_observatory_key() or "") if hasattr(self._window, "_safety_observatory_key") else ""

    def refresh(self) -> None:
        """Publish the current site, pick this Observatory's supervisor and repaint the banner."""
        try:
            scope = self._scope()
            site = self._build_site()
            with self._lock:
                self._site = site
            observatory = getattr(self._window, "_current_observatory", None)
            from galileo.session_context import build_notify_service
            self._notify_service = build_notify_service(observatory)
            supervisor = self._supervisors.get(scope)
            if supervisor is None:
                supervisor = self._supervisors[scope] = self._new_supervisor(scope)
            if supervisor is not self.supervisor:
                if self.supervisor is not None:
                    self.supervisor.stop()            # only the selected Observatory's devices are held
                self.supervisor = supervisor
                if self._run_thread:
                    supervisor.start()
            self._paint()
        except Exception:
            logger.exception("Could not refresh the safety state")

    def _new_supervisor(self, scope: str) -> SafetySupervisor:
        supervisor = SafetySupervisor(self.snapshot, scope=scope, notify=self._notify, store=self._store,
                                      on_restart=lambda: self._ui.submit(self._restart_jobs))
        supervisor.activities.register("the desktop's activities", self._stop_activities)
        return supervisor

    def _build_site(self) -> Site:
        from galileo.current_object import pier_key
        from galileo.ui.session_runner import _observatory_piers, _page_adapter, _roof_mounts

        window = self._window
        pages = getattr(window, "_device_pages", {})
        sources_of = (pages.get("weather") or {}).get("sources")
        sources = sources_of() if sources_of else []
        mounts = _roof_mounts(window)
        selected_key = pier_key(getattr(window, "_current_pier", None))
        guiders, roofs, seen = [], [], set()
        for pier in _observatory_piers(window) or [None]:
            key = pier_key(pier)
            selected = pier is None or key == selected_key
            name = getattr(pier, "name", "") or "this Pier"
            guider_state = pages.get("guider") or {}
            if selected:
                getter = guider_state.get("get_service")
                guider = getter() if getter else None
            else:
                guider = (guider_state.get("service_for") or (lambda _k: None))(getattr(pier, "id", None))
            if guider is not None and getattr(guider, "is_connected", False):
                guiders.append((name, guider))
            dome = _page_adapter(window, "dome", key, selected)
            configured = False
            if pier is not None:
                try:
                    from galileo.observatory import get_device_config
                    configured = get_device_config(pier, "dome") is not None
                except Exception:
                    logger.debug("Could not read a Pier's dome configuration", exc_info=True)
            if (dome is not None and id(dome) not in seen) or (dome is None and configured):
                seen.add(id(dome))
                # A configured dome that is not connected stays listed: it cannot be confirmed closed.
                roofs.append(Roof(name=f"the dome of {name}", dome=dome, mounts=mounts))
        if len(roofs) > 1:   # the same physical roof saved on several Piers: a connected entry covers the others
            connected = [r for r in roofs if r.dome is not None]
            roofs = connected or roofs
        return Site(sources=sources, mounts=mounts, guiders=guiders, roofs=roofs)

    # -- any thread ---------------------------------------------------------------------------------

    def snapshot(self) -> Site:
        with self._lock:
            return self._site

    def evaluation(self) -> tuple[bool, bool, list[str]]:
        """``(monitored, may start, reasons)``: what the scheduler, Run and the Schedule screen gate on."""
        supervisor = self.supervisor
        sources = self.snapshot().sources
        if supervisor is None or (not sources and supervisor.state == State.READY):
            return False, True, []
        if not supervisor.checked and supervisor.state == State.READY:
            return True, False, ["safety has not been checked yet"]
        reason = supervisor.gate_reason()
        return True, supervisor.is_safe(), [reason] if reason else []

    def is_safe(self) -> bool:
        monitored, safe, _reasons = self.evaluation()
        return safe or not monitored

    def holding(self) -> bool:
        return not self.is_safe()

    async def _notify(self, message: str) -> None:
        self._ui.submit(lambda: self._status_message(message))
        service = self._notify_service
        if service is not None:
            from galileo.notify import NotificationEvent
            await service.emit(NotificationEvent.SAFETY_ABORT, message)

    # -- stopping activities (SAFE-150) ----------------------------------------------------------------

    async def _stop_activities(self) -> None:
        await asyncio.wrap_future(self._ui.submit(self._stop_on_ui))
        # What the screens asked to stop may be mid-exposure or mid-slew: abort at the devices as well.
        await self._abort_devices()
        deadline = asyncio.get_running_loop().time() + SESSION_END_TIMEOUT_S
        while await asyncio.wrap_future(self._ui.submit(self._sessions_running)):
            if asyncio.get_running_loop().time() > deadline:
                raise RuntimeError("a session did not end")
            await asyncio.sleep(0.5)
        await self._abort_devices()

    def _stop_on_ui(self) -> None:
        failed = []
        for name, stop in list(getattr(self._window, "_safety_stoppers", {}).items()):
            try:
                stop()
            except Exception:
                logger.exception("Could not stop %s", name)
                failed.append(name)
        controller = getattr(self._window, "_session_controller", None)
        if controller is not None:
            controller.stop_all_for_safety()
        if failed:
            raise RuntimeError(f"could not stop: {', '.join(failed)}")

    def _sessions_running(self) -> bool:
        controller = getattr(self._window, "_session_controller", None)
        return controller is not None and controller.is_running()

    def _devices(self) -> list[tuple[Any, str]]:
        found = [(mount, "abort_slew") for _name, mount in self.snapshot().mounts if mount is not None]
        cameras = list(getattr(self._window, "_camera_backends", {}).values())
        for per_pier in getattr(self._window, "_camera_backends_by_pier", {}).values():
            cameras += list(per_pier.values())
        unique = {id(c): c for c in cameras if c is not None}
        return found + [(camera, "abort_exposure") for camera in unique.values()]

    async def _abort_devices(self) -> None:
        devices = await asyncio.wrap_future(self._ui.submit(self._devices))

        async def abort(device: Any, method: str) -> None:
            try:
                await asyncio.wait_for(getattr(device, method)(), 10)
            except Exception:
                logger.debug("%s failed during the safety stop", method, exc_info=True)

        await asyncio.gather(*(abort(d, m) for d, m in devices))

    def _restart_jobs(self) -> None:
        """Opt-in restart (SAFE-040): scheduled sessions a protective stop ended become due again."""
        for scheduler in getattr(self._window, "_schedulers", {}).values():
            changed = False
            for job in scheduler.jobs:
                if job.run_state == "stopped" and any("stopped for safety" in line for line in job.run_log):
                    job.run_state = "pending"
                    changed = True
            if changed:
                scheduler.save()

    # -- the banner (SAFE-170) -----------------------------------------------------------------------

    def build_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("SafetyBanner")
        banner.setStyleSheet("#SafetyBanner { border: 2px solid #c0392b; border-radius: 4px; }")
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(12, 6, 12, 6)
        label = QLabel("")
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        button = QPushButton("Acknowledge safety stop")
        button.clicked.connect(self.acknowledge)
        layout.addWidget(button)
        banner.setVisible(False)
        self.banner, self._banner_label, self._ack_button = banner, label, button
        return banner

    def banner_text(self) -> str:
        supervisor = self.supervisor
        if supervisor is None:
            return ""
        status = supervisor.status()
        blocker = supervisor.acknowledge_blocker()
        waiting = f" Cannot acknowledge yet: {blocker}." if blocker else ""
        state, problems = status["state"], " ".join(status["problems"])
        if state == State.STOPPING:
            return f"SAFETY STOP — {status['reason']}. Stopping activity, parking and closing…"
        if state == State.SECURED:
            return f"SAFETY STOP — {status['reason']}. Equipment secured. Nothing starts until you acknowledge.{waiting}"
        if state == State.NOT_SECURED:
            return f"SAFETY STOP NOT COMPLETE — {status['reason']}. {problems}{waiting}"
        if state == State.AWAITING_ACK:
            return f"Safe again after a stop ({status['reason']}). {problems} Acknowledge to allow starting."
        if status["level"] == "unsafe":
            return "Conditions unsafe: " + "; ".join(status["reasons"])
        if status["warnings"]:
            return "Safety warning: " + "; ".join(status["warnings"])
        return ""

    def _paint(self) -> None:
        if self.banner is None or self.supervisor is None:
            return
        text = self.banner_text()
        self._banner_label.setText(text)
        self._ack_button.setVisible(self.supervisor.state != State.READY)
        blocker = self.supervisor.acknowledge_blocker()
        self._ack_button.setEnabled(not blocker)
        self._ack_button.setToolTip(blocker)
        self.banner.setVisible(bool(text))

    def _status_message(self, message: str) -> None:
        self._paint()
        main = getattr(self._window, "_window", None)
        if main is not None and hasattr(main, "statusBar"):
            main.statusBar().showMessage(message, 15000)

    def acknowledge(self) -> None:
        if self.supervisor is None:
            return
        try:
            self.supervisor.acknowledge("desktop")
        except ValueError as exc:
            self._status_message(f"Cannot acknowledge: {exc}")
        self._paint()

    def settings(self) -> SafetySettings:
        return load_settings(self._scope())


def start_safety(window: Any) -> SafetyHost:
    """Create the window's host, put its banner under the top bar, and start watching."""
    from PySide6.QtWidgets import QApplication

    host = SafetyHost(window)
    window._safety_host = host
    central = window._window.centralWidget()
    if central is not None and central.layout() is not None:
        central.layout().insertWidget(1, host.build_banner())
    host.start()
    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(host.stop)
    return host
