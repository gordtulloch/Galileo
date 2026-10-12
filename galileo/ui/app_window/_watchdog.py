# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Starts the crash/hang watchdog (SAFE-060) inside the running application.

The Qt event loop beats the watchdog from a timer; the watchdog itself lives on its own
thread (``galileo.safety.WatchdogService``) so it still fires when that loop is hung. Its
status is shown in the status bar, and a trip raises an in-app notification plus the
configured e-mail / SMS channels.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_MS = 1000


def status_text(watchdog: Any) -> str:
    """One-line status for the status bar."""
    if watchdog is None:
        return "Watchdog: off"
    status = watchdog.status
    if status == "tripped":
        return "Watchdog: TRIPPED — mount parked, dome closed"
    if status == "armed":
        return f"Watchdog: armed ({watchdog.timeout_s:g} s)"
    return "Watchdog: stopped"


def start_watchdog(window: Any) -> Any:
    """Create, arm and wire the watchdog for the main window; returns it (or ``None`` when
    disabled in the saved settings). Stopped automatically when the application quits."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel
    from galileo.bus import get_bus
    from galileo.safety import WatchdogService
    from galileo.ui.session_runner import _build_notify_service, _page_adapter
    from galileo.watchdog_settings import load_watchdog_settings

    label = QLabel()
    label.setObjectName("WatchdogStatus")
    label.setToolTip("Crash/hang watchdog: if Galileo stops responding for the timeout, the mount "
                     "is parked and the dome closed.")
    window._window.statusBar().addPermanentWidget(label)
    window._watchdog_label = label

    settings = load_watchdog_settings()
    if not settings["enabled"]:
        window._watchdog = None
        label.setText(status_text(None))
        return None

    # Devices are looked up when needed, so ones connected after start-up are covered.
    watchdog = WatchdogService(
        mount=lambda: _page_adapter(window, "mount"),
        dome=lambda: _page_adapter(window, "dome"),
        timeout_s=settings["timeout_s"],
        event_bus=get_bus(),
    )

    def _notify(detail: str) -> None:  # runs on the watchdog thread
        try:
            service = window._watchdog_notify_service
            from galileo.notify import NotificationEvent
            asyncio.run(service.emit(NotificationEvent.SAFETY_ABORT, f"Watchdog: {detail}"))
        except Exception:
            logger.exception("Watchdog: could not send the trip notification")

    watchdog.add_trip_handler(_notify)
    window._watchdog = watchdog
    window._watchdog_notify_service = _build_notify_service(window)

    state = {"reported": False, "ticks": 0}

    def _tick() -> None:
        label.setText(status_text(watchdog))
        if watchdog.tripped:
            if not state["reported"]:
                state["reported"] = True
                window._window.statusBar().showMessage(watchdog.trip_detail, 0)
            return
        watchdog.heartbeat()
        # Built here, on the UI thread, so a trip never has to touch Qt state: the contacts
        # follow whichever Observatory is selected.
        state["ticks"] += 1
        if state["ticks"] % 30 == 0:
            window._watchdog_notify_service = _build_notify_service(window)

    timer = QTimer(window._window)
    timer.timeout.connect(_tick)
    timer.start(HEARTBEAT_INTERVAL_MS)
    window._watchdog_timer = timer
    watchdog.start()
    _tick()

    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(lambda: stop_watchdog(window))
    return watchdog


def stop_watchdog(window: Any) -> None:
    """Disarm the watchdog cleanly on exit (so quitting never parks the mount)."""
    timer = getattr(window, "_watchdog_timer", None)
    if timer is not None:
        timer.stop()
    watchdog = getattr(window, "_watchdog", None)
    if watchdog is not None:
        watchdog.stop_sync()
