# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The remaining, still-minimal device-category/section pages (Guider, Focus, Sessions, Schedule, Solve)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import QWidget

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from galileo.scheduler import ObservatoryScheduler

    from ._state import AppWindowState


class AppWindowMiscDevicePagesMixin:
    def _build_guider_page(self: AppWindowState) -> QWidget:
        """Guiding page (a primary sidebar section): a live view onto PHD2
        (GUIDE-070 … GUIDE-090) — see ``galileo.ui.guider``. Unlike the
        Equipment categories there is no device
        to scan for; PHD2 is reached by host and port, and does its own
        camera/mount handling."""
        from galileo.ui.guider import GuiderPage
        page = GuiderPage(self)
        self._device_pages["guider"] = {
            "reload": page.reload, "autoconnect": page.autoconnect,
            "disconnect": page.disconnect_from_phd2,
            "get_service": page._service,     # this Pier's GuidingService, for session execution
            "connected": lambda: (svc := page._service()) is not None and svc.is_connected,
        }
        page.reload()
        return page

    def _build_focus_page(self: AppWindowState) -> QWidget:
        """Focus page (a primary sidebar section): follows autofocus runs and
        can start one — see ``galileo.ui.focus``. It only redraws while a run
        is in progress."""
        from galileo.ui.focus import FocusPage
        page = FocusPage(self)
        self._device_pages["focus"] = {"reload": page.reload}
        return page

    def _scheduler_for_pier(self: AppWindowState, pier_name: str | None) -> ObservatoryScheduler:
        """The one ``ObservatoryScheduler`` for *pier_name* — shared by Planning >
        Sessions and Planning > Schedule, created lazily, one per Pier. Persists to
        (and, on first use, loads from) the shared database (SCHED-100) so a Pier's
        job queue survives an application restart."""
        from galileo.scheduler import ObservatoryScheduler
        key = pier_name or ""
        if key not in self._schedulers:
            scheduler = ObservatoryScheduler()
            scheduler.set_persistence(key)
            scheduler.load()
            # Gate jobs on this window's connected safety devices (SCHED-060). The monitor
            # re-reads the Safety page on every check, so connecting/disconnecting a device
            # needs no re-registration.
            from galileo.safety import LiveSafetyMonitor
            scheduler.set_safety_monitor(LiveSafetyMonitor(self._safety_evaluation))
            self._schedulers[key] = scheduler
        return self._schedulers[key]

    def _safety_evaluation(self: AppWindowState) -> tuple[bool, bool, list[str]]:
        """``(any safety device connected, safe, reasons)`` for the active Pier, from the
        Equipment > Safety page; ``(False, True, [])`` while that page or its devices don't exist."""
        evaluate = (getattr(self, "_device_pages", {}).get("weather") or {}).get("evaluate")
        if evaluate is None:
            return False, True, []
        return evaluate()

    def _build_sessions_page(self: AppWindowState) -> QWidget:
        """Planning > Sessions (SES-100 … SES-230): per-Pier, block-based session
        authoring — see ``galileo.ui.sessions``."""
        from galileo.ui.sessions import SessionsPageWidget
        page = SessionsPageWidget(self)
        self._device_pages["sessions"] = {
            "reload": page.reload,
            "create_session_for_target": page.create_session_for_target,
        }
        return page

    def _build_schedule_page(self: AppWindowState) -> QWidget:
        """Planning > Schedule (SCHED-110 … SCHED-160): the per-Pier visual
        timeline over the same job queue — see ``galileo.ui.schedule``."""
        from galileo.ui.schedule import SchedulePageWidget
        page = SchedulePageWidget(self)
        self._device_pages["schedule"] = {"reload": page.reload}
        return page

    def _build_history_page(self: AppWindowState) -> QWidget:
        """Planning > History (HIST-020, HIST-040): per-frame HFR / star count / guide RMS of
        past and running sessions — see ``galileo.ui.history``."""
        from galileo.ui.history import HistoryPageWidget
        page = HistoryPageWidget(self)
        self._device_pages["history"] = {"reload": page.reload}
        return page

    def _build_dashboard_page(self: AppWindowState) -> QWidget:
        """Dashboard page (a primary sidebar section): every Pier of the selected
        Observatory at a glance (OBS-060) — see ``galileo.ui.dashboard``. It
        refreshes itself, off the UI thread, while it is on screen."""
        from galileo.ui.dashboard import DashboardPage
        page = DashboardPage(self)
        self._device_pages["dashboard"] = {"reload": page.reload}
        return page

    def _build_solve_page(self: AppWindowState) -> QWidget:
        """Solve page (a primary sidebar section): plate solving, with the frame
        being solved and its results on show (PLT-070) — see ``galileo.ui.solve``.
        It follows every solve, whoever started it, but only while it is on
        screen."""
        from galileo.ui.solve import SolvePage
        page = SolvePage(self)
        self._device_pages["solve"] = {"reload": page.reload, "refresh_target": page.refresh_target}
        return page
