# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The desktop as the owner of the live job queue, for a phone, tablet or browser (CSURF-186, CSURF-205).

The queue (``ObservatoryScheduler``) and the session runs (``SessionRunController``) belong to this application, and a
second writer on the saved queue would corrupt it, so the engine's Control Surface never edits either: it calls this
object, which does what the Schedule and Sessions screens do and nothing else. Every call is made on the Qt thread: one
arriving from the engine's thread is queued there and waited for.

``DesktopScheduleOwner`` is registered on the hosted engine's ``ScheduleControl`` (``galileo.app``).
"""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QApplication

from galileo.control_surface.registry import Refused

logger = logging.getLogger(__name__)

CALL_TIMEOUT_S = 15.0


class _UiCaller(QObject):
    """Runs callables on the thread this object lives in (the UI thread) and hands back their result."""

    call = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.call.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, item: tuple[Callable[[], Any], concurrent.futures.Future]) -> None:
        fn, future = item
        try:
            future.set_result(fn())
        except BaseException as exc:                      # handed to the waiting thread
            future.set_exception(exc)

    def on_ui(self, fn: Callable[[], Any]) -> Any:
        app = QApplication.instance()
        if app is None or QThread.currentThread() is app.thread():
            return fn()
        future: concurrent.futures.Future = concurrent.futures.Future()
        self.call.emit((fn, future))
        try:
            return future.result(timeout=CALL_TIMEOUT_S)
        except concurrent.futures.TimeoutError as exc:
            raise Refused("the desktop application did not answer in time") from exc


class DesktopScheduleOwner:
    """:class:`galileo.control_surface.schedule.ScheduleOwner` over one ``AppWindow``. *devices* is the device service
    the engine shares, which maps an engine Pier id to the Pier's name and record."""

    def __init__(self, window: Any, devices: Any) -> None:
        self._window = window
        self._devices = devices
        self._ui = _UiCaller()                            # created on the UI thread, so it lives there

    # -- helpers (UI thread) -----------------------------------------------------------------------
    def _pier(self, pier: str) -> tuple[str, Any, Any]:
        """``(Pier name, desktop key, that Pier's scheduler)``."""
        from galileo.current_object import pier_key
        name = self._devices.pier_name(pier)
        record = self._devices.pier_record(pier)
        if record is None:
            raise Refused("there is no such Pier")
        return name, pier_key(record), self._window._scheduler_for_pier(name)

    def _controller(self) -> Any:
        from galileo.ui.session_runner import get_session_controller
        return get_session_controller(self._window)

    def _run(self, key: Any) -> Any:
        return self._controller()._runs.get(key)

    @staticmethod
    def _is_paused(run: Any) -> bool:
        from galileo.session_exec import RunState
        return getattr(run.progress, "state", None) == RunState.PAUSED

    @staticmethod
    def _running_job(run: Any, scheduler: Any, job: Any) -> bool:
        """Whether *job* is the one being run (by a scheduled run or by Run on its session)."""
        if scheduler.active_job is job:
            return True
        return run is not None and (run.job is job or (job.sequence is not None and run.region is job.sequence))

    def _upcoming(self, scheduler: Any, name: str = "") -> list[str]:
        """Pending session jobs whose time is still to come, or has begun and not run out (not *name* itself)."""
        now = datetime.datetime.now(datetime.UTC)
        found = []
        for job in scheduler.get_ordered_jobs():
            if job.name == name or job.run_state != "pending" or job.is_complete:
                continue
            window = job.effective_window()
            if window is not None and window[1] > now:
                found.append(job.name)
        return found

    def _refresh_screens(self) -> None:
        """Bring the Sessions and Schedule screens in line with a change made from outside."""
        pages = getattr(self._window, "_device_pages", {}) or {}
        for page in ("sessions", "schedule"):
            reload = (pages.get(page) or {}).get("reload")
            if reload is not None:
                try:
                    reload()
                except Exception:
                    logger.exception("Could not refresh the %s screen", page)

    # -- reads ---------------------------------------------------------------------------------------
    def jobs(self, pier: str) -> list[dict[str, Any]]:
        return self._ui.on_ui(lambda: self._jobs(pier))

    def _jobs(self, pier: str) -> list[dict[str, Any]]:
        _name, key, scheduler = self._pier(pier)
        run = self._run(key)
        out: list[dict[str, Any]] = []
        if run is not None and run.job is None:           # Run on a session that is not a queued job
            progress = run.progress
            out.append({"name": run.region.name, "kind": "session", "priority": 0, "target_ra": 0.0, "target_dec": 0.0,
                        "frames_captured": progress.frames_done, "total_required": progress.frames_total,
                        "complete": False, "run_state": "running", "start": None, "end": None, "minutes": None,
                        "operation": None, "running": True, "paused": self._is_paused(run), "queued": False})
        ordered = sorted(scheduler.get_ordered_jobs(), key=lambda j: not self._running_job(run, scheduler, j))
        for job in ordered:                               # the running job first, then the rest in priority order
            running = self._running_job(run, scheduler, job)
            out.append({
                "name": job.name, "kind": job.kind, "priority": job.priority, "target_ra": job.target_ra,
                "target_dec": job.target_dec, "frames_captured": job.frames_captured,
                "total_required": job.total_required, "complete": job.is_complete,
                "run_state": "running" if running else job.run_state, "start": job.scheduled_start_utc,
                "end": job.scheduled_end_utc, "minutes": job.duration_minutes, "operation": job.pier_op_kind,
                "running": running, "paused": bool(running and run is not None and self._is_paused(run)),
                "queued": True})
        return out

    def saved(self, pier: str) -> list[dict[str, Any]]:
        from galileo.library.models.saved_session import SavedSessionRecord
        name = self._devices.pier_name(pier)
        out = []
        for record in SavedSessionRecord.select().where(SavedSessionRecord.pier_name == (name or "")).order_by(
                SavedSessionRecord.id):
            try:
                blocks = json.loads(record.blocks_json)
            except ValueError:
                continue
            target = next((b.get("name", "") for b in blocks if b.get("_type") == "TargetBlock"), "")
            out.append({"name": record.name, "blocks": len(blocks), "target": target})
        return out

    def check(self, pier: str, name: str) -> dict[str, Any]:
        return self._ui.on_ui(lambda: self._check(pier, name))

    def _check(self, pier: str, name: str) -> dict[str, Any]:
        _pier_name, key, scheduler = self._pier(pier)
        run = self._run(key)
        running = run.region.name if run is not None else (scheduler.active_job.name if scheduler.active_job else "")
        reason = self._why_not_start(pier, key, name)
        return {"running": running, "upcoming": [] if running else self._upcoming(scheduler, name), "reason": reason}

    def _why_not_start(self, pier: str, key: Any, name: str) -> str:
        from galileo.current_object import pier_key
        if pier_key(getattr(self._window, "_current_pier", None)) != key:
            return "Select this Pier on the desktop application first."
        if not any(s["name"] == name for s in self.saved(pier)):
            return f"There is no saved session called {name!r} on this Pier."
        return ""

    # -- starting a saved session ------------------------------------------------------------------------
    def run_saved(self, pier: str, name: str, preempt: bool) -> dict[str, Any]:
        return self._ui.on_ui(lambda: self._run_saved(pier, name, preempt))

    def _run_saved(self, pier: str, name: str, preempt: bool) -> dict[str, Any]:
        pier_name, key, scheduler = self._pier(pier)
        if self._run(key) is not None or scheduler.active_job is not None:
            raise Refused("Jobs already running")
        reason = self._why_not_start(pier, key, name)
        if reason:
            raise Refused(reason)
        if not preempt and self._upcoming(scheduler, name):
            raise Refused("Upcoming jobs are scheduled; repeat with preempt to run now")
        job = next((j for j in scheduler.jobs if j.kind == "session" and j.name == name), None)
        region = job.sequence if job is not None and job.sequence is not None else self._load_region(
            pier_name, name, scheduler, job)
        problems, _conflicts = self._controller().start_region(region)
        if problems:
            raise Refused("; ".join(problems))
        self._refresh_screens()
        return {"started": name}

    @staticmethod
    def _load_region(pier_name: str, name: str, scheduler: Any, job: Any) -> Any:
        """A session to run, rebuilt from its saved copy (the Sessions screen's own regions are not reachable from
        here); tied to its queue entry if it has one, so a completed run satisfies that job as Run does."""
        from galileo.library.models.saved_session import SavedSessionRecord
        from galileo.ui.sessions import SessionRegion, _block_from_dict
        record = SavedSessionRecord.get_or_none(
            (SavedSessionRecord.pier_name == (pier_name or "")) & (SavedSessionRecord.name == name))
        if record is None:
            raise Refused(f"There is no saved session called {name!r} on this Pier.")
        region = SessionRegion(record.name, scheduler=scheduler)
        region.blocks = [_block_from_dict(d) for d in json.loads(record.blocks_json)]
        region._normalize_indents()
        region.camera_slot = record.camera_slot
        region._record_id = record.id
        region._pier_name = pier_name
        if job is not None:
            region._job = job
            region.is_scheduled = True
        return region

    # -- queue control ---------------------------------------------------------------------------------
    def remove(self, pier: str, name: str) -> None:
        self._ui.on_ui(lambda: self._remove(pier, name))

    def _remove(self, pier: str, name: str) -> None:
        _pier_name, key, scheduler = self._pier(pier)
        job = next((j for j in scheduler.jobs if j.name == name), None)
        if job is None:
            raise Refused(f"There is no queued job called {name!r}.")
        if self._running_job(self._run(key), scheduler, job):
            raise Refused("A running job cannot be removed: stop it first.")
        region = job.sequence
        if region is not None and hasattr(region, "deschedule"):
            region.deschedule()                           # off the queue; the saved session stays saved
        else:
            scheduler.remove_job(job)
        self._refresh_screens()

    def reorder(self, pier: str, name: str, position: int) -> None:
        self._ui.on_ui(lambda: self._reorder(pier, name, position))

    def _reorder(self, pier: str, name: str, position: int) -> None:
        _pier_name, key, scheduler = self._pier(pier)
        run = self._run(key)
        ordered = scheduler.get_ordered_jobs()
        job = next((j for j in ordered if j.name == name), None)
        if job is None:
            raise Refused(f"There is no queued job called {name!r}.")
        if self._running_job(run, scheduler, job):
            raise Refused("A running job cannot be moved.")
        ordered.remove(job)
        ordered.sort(key=lambda j: not self._running_job(run, scheduler, j))               # the running job stays first
        first = sum(1 for j in ordered if self._running_job(run, scheduler, j))
        ordered.insert(max(first, min(int(position), len(ordered))), job)
        for index, each in enumerate(ordered):            # the queue runs in priority order, so renumber to match
            each.priority = index + 1
        scheduler._sort_jobs()
        scheduler.save()
        self._refresh_screens()

    def _control(self, pier: str, action: str) -> None:
        _name, key, _scheduler = self._pier(pier)
        run = self._run(key)
        if run is None:
            raise Refused("No job is running on this Pier.")
        getattr(self._controller(), action)(run.region)
        self._refresh_screens()

    def pause(self, pier: str) -> None:
        self._ui.on_ui(lambda: self._control(pier, "pause"))

    def resume(self, pier: str) -> None:
        self._ui.on_ui(lambda: self._control(pier, "resume"))

    def stop(self, pier: str) -> None:
        self._ui.on_ui(lambda: self._control(pier, "stop"))


__all__ = ["DesktopScheduleOwner"]
