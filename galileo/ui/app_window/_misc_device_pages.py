# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The remaining, still-minimal device-category/section pages (Guider, Focus, Sessions, Scheduler, Solve)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import QWidget

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
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
        self._device_pages["guider"] = {"reload": page.reload, "autoconnect": page.autoconnect}
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
        Sessions and Planning > Scheduler, created lazily, one per Pier. Persists to
        (and, on first use, loads from) the shared database (SCHED-100) so a Pier's
        job queue survives an application restart."""
        from galileo.scheduler import ObservatoryScheduler
        key = pier_name or ""
        if key not in self._schedulers:
            scheduler = ObservatoryScheduler()
            scheduler.set_persistence(key)
            scheduler.load()
            self._schedulers[key] = scheduler
        return self._schedulers[key]

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

    def _build_scheduler_page(self: AppWindowState) -> QWidget:
        """Planning > Scheduler (SCHED-010 … SCHED-100): the per-Pier job queue —
        see ``galileo.ui.scheduler``."""
        from galileo.ui.scheduler import SchedulerPageWidget
        page = SchedulerPageWidget(self)
        self._device_pages["scheduler"] = {"reload": page.reload}
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
