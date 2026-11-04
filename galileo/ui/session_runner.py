# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Runs Sessions-screen sessions (SES-030, SES-040, SES-050, SES-350) and fires scheduled ones.

``SessionRunController`` is the Qt-side owner of session execution. It builds a
``SessionContext`` from the active Pier's connected devices, runs
``galileo.session_exec.SessionExecutor`` on a worker thread (the same
QThread-plus-``asyncio.run`` pattern every other long device operation in this app uses, so
the UI never blocks), and relays progress back to the Sessions page through a queued signal.

Two things start a run, and both go through ``ObservatoryScheduler.run_job`` so a session
behaves identically however it was started:

* the session card's **Run** control (``start_region``), and
* a periodic tick that starts any job, on any Pier of the Observatory, whose timeline window
  has begun (``_tick``).

Every Equipment page keeps each Pier's connections across a Pier switch, so a Pier that is not
selected still has live devices: the tick builds its context from those (``adapter_for`` on the
pages) and gates it on that Pier's own safety devices. A Pier none of whose equipment is
connected is skipped until it is. One session runs per Pier at a time, and Piers run
concurrently (OBS-020, OBS-140).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from galileo.engine.runner import run_session
from galileo.session_context import assemble_context
from galileo.session_exec import (
    SessionContext,
    SessionExecutor,
    SessionProgress,
    SessionRunResult,
    preflight,
)

logger = logging.getLogger(__name__)

TICK_INTERVAL_MS = 15_000
SAFETY_INTERVAL_MS = 5_000


# ---------------------------------------------------------------------------
# Context construction (UI thread)
# ---------------------------------------------------------------------------

def _page_adapter(window: Any, page: str, key: Any = None, selected: bool = True) -> Any:
    """The device a page holds for a Pier. For the selected Pier that is whatever the page shows;
    for any other Pier (*selected* False, *key* its ``pier_key``) it is that Pier's own connection,
    which the page keeps across Pier switches — or ``None`` if it never connected one."""
    state = getattr(window, "_device_pages", {}).get(page) or {}
    if selected:
        return state.get("adapter")
    adapter_for = state.get("adapter_for")
    return adapter_for(key) if adapter_for else None


def _dome_service(window: Any, key: Any = None, selected: bool = True) -> Any:
    """A Pier's ``DomeService`` (DOME-010), or ``None`` without a connected dome."""
    state = getattr(window, "_device_pages", {}).get("dome") or {}
    if selected:
        getter = state.get("get_service")
        return getter() if getter else None
    service_for = state.get("service_for")
    return service_for(key) if service_for else None


def _observatory_arbiter(window: Any) -> Any:
    """The ``ResourceArbiter`` shared by every Pier of the current Observatory (OBS-100).

    The UI's Observatory is a database record with no arbiter of its own, so the window keeps
    one per Observatory name; each Pier's run gets the same instance and so sees the others'
    activity on the shared dome."""
    from galileo.observatory import ResourceArbiter
    arbiters = getattr(window, "_observatory_arbiters", None)
    if arbiters is None:
        arbiters = {}
        window._observatory_arbiters = arbiters
    name = getattr(getattr(window, "_current_observatory", None), "name", "") or ""
    if name not in arbiters:
        arbiters[name] = ResourceArbiter()
    return arbiters[name]


def _build_notify_service(window: Any) -> Any:
    """A ``NotificationService`` bound to the window's current Observatory (see ``build_notify_service``)."""
    from galileo.session_context import build_notify_service
    return build_notify_service(getattr(window, "_current_observatory", None))


def build_session_context(window: Any, pier: Any = None, camera_slot: str | None = None) -> SessionContext:
    """Snapshot a Pier's connected devices and services for one run. Call on the UI thread.
    Anything not connected is left ``None``; the executor's pre-flight reports it.

    *pier* defaults to the selected Pier, whose devices are what the Equipment pages show and
    whose camera/optics follow the top-bar selectors. Any other Pier of the Observatory is read
    from the connections its pages keep for it, with its primary camera and first optical tube
    (OBS-140), so scheduled sessions can run on Piers that are not on screen.

    *camera_slot* is the camera the session is bound to (``SessionRegion.camera_slot``): every
    action of the run uses it, whichever camera the top bar's selector is on. ``None`` falls back
    to that selector (selected Pier) or the primary camera."""
    from galileo.current_object import pier_key
    from galileo.ui.app_window._common import _camera_backend_key_for_slot

    selected_pier = getattr(window, "_current_pier", None)
    pier = selected_pier if pier is None else pier
    key = pier_key(pier)
    selected = key == pier_key(selected_pier)
    pages = getattr(window, "_device_pages", {})

    camera_slot = camera_slot or (getattr(window, "_active_camera_slot", "primary") if selected else "primary")
    if selected:
        cameras = getattr(window, "_camera_backends", {})
    else:
        cameras = getattr(window, "_camera_backends_by_pier", {}).get(key, {})
    camera = cameras.get(_camera_backend_key_for_slot(camera_slot))
    mount = _page_adapter(window, "mount", key, selected)
    focuser_state = pages.get("focuser") or {}
    if selected:
        focuser_getter = focuser_state.get("get_adapter")
        focuser = focuser_getter() if focuser_getter else None
    else:
        focuser = (focuser_state.get("adapter_for") or (lambda _k: None))(key)
    wheel_getter = getattr(window, "_active_filter_wheel", None)
    wheel = wheel_getter() if (selected and wheel_getter) else _page_adapter(window, "filter_wheel", key, selected)
    guider_state = pages.get("guider") or {}
    if selected:
        guider_getter = guider_state.get("get_service")
        guider = guider_getter() if guider_getter else None
    else:
        guider = (guider_state.get("service_for") or (lambda _k: None))(getattr(pier, "id", None))
    if guider is not None and not guider.is_connected:
        guider = None

    location_getter = getattr(window, "_flats_observing_location", None)
    location = (location_getter() if selected else location_getter(pier)) if location_getter else None

    frame_context_getter = getattr(window, "_imaging_frame_context", None)
    try:
        if not (frame_context_getter and camera is not None):
            frame_context = {}
        else:
            frame_context = frame_context_getter(pier, camera_slot=camera_slot)
    except Exception:
        logger.exception("Could not gather the FITS header context")
        frame_context = {}

    return assemble_context(
        pier=pier, key=key, camera_slot=camera_slot, camera=camera, mount=mount, filter_wheel=wheel,
        focuser=focuser, rotator=_page_adapter(window, "rotator", key, selected),
        dome=_page_adapter(window, "dome", key, selected), dome_service=_dome_service(window, key, selected),
        guider=guider, flat_panel=_page_adapter(window, "flat_panel", key, selected),
        arbiter=_observatory_arbiter(window), observatory=getattr(window, "_current_observatory", None),
        notify_service=_build_notify_service(window), location=location, frame_context=frame_context)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

@dataclass
class ActiveRun:
    """One in-flight session on one Pier."""
    region: Any
    job: Any                                 # the Schedule entry being run; None for a Run of an unscheduled session
    scheduler: Any
    executor: SessionExecutor
    thread: QThread | None = None
    manual: bool = True                      # started by Run, not by the scheduler's tick
    prior_start: str | None = None           # unused: a manual Run no longer moves its Schedule entry
    was_scheduled: bool = False              # a manual Run of a session that is also on the Schedule
    progress: SessionProgress = field(default_factory=SessionProgress)
    result: SessionRunResult | None = None


class _RunThread(QThread):
    progress = Signal(object)
    finished_with = Signal(str)

    def __init__(self, run: ActiveRun, parent=None) -> None:
        super().__init__(parent)
        self._run = run

    def run(self) -> None:
        run = self._run
        # The same code path the engine's SessionRunner runs (HEAD-050): a manual Run executes at once and stays
        # off the Schedule; a scheduled run goes through the scheduler so it behaves the same however it started.
        try:
            state, run.result = asyncio.run(run_session(
                run.executor, run.region.blocks, scheduler=run.scheduler, job=run.job, manual=run.manual))
        except Exception:
            logger.exception("Session run thread failed")
            state = "error"
        self.finished_with.emit(state)


class SessionRunController(QObject):
    """Starts, tracks, and controls session runs for one ``AppWindow``."""

    changed = Signal(object)          # emitted with the Pier key whenever a run's state changes

    def __init__(self, window: Any) -> None:
        super().__init__()
        self._window = window
        self._runs: dict[Any, ActiveRun] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._takeover: dict[Any, Any] = {}         # Pier key -> session whose Run is waiting for a scheduled run to stop
        self._blocked: dict[Any, str] = {}          # Pier key -> why the safety monitor holds its jobs
        self._safety_paused: set[Any] = set()       # runs we paused for unsafe conditions
        self._safety_timer = QTimer(self)
        self._safety_timer.setInterval(SAFETY_INTERVAL_MS)
        self._safety_timer.timeout.connect(self._enforce_safety)

    def start_ticking(self) -> None:
        """Begin servicing the active Pier's scheduler queue (call once the window is real)."""
        if not self._timer.isActive():
            self._timer.start()
        if not self._safety_timer.isActive():
            self._safety_timer.start()

    def stop_ticking(self, *_args) -> None:
        self._timer.stop()
        self._safety_timer.stop()

    # --- Queries --------------------------------------------------------------

    def _key(self) -> Any:
        from galileo.current_object import pier_key
        return pier_key(getattr(self._window, "_current_pier", None))

    def run_for(self, region: Any) -> ActiveRun | None:
        return next((r for r in self._runs.values() if r.region is region), None)

    def is_running(self, region: Any = None) -> bool:
        return (self.run_for(region) is not None) if region is not None else bool(self._runs)

    def run_snapshot(self) -> dict[Any, tuple[str, str]]:
        """``{pier_key: (state, session name)}`` for every Pier with a run in flight — what
        the Observatory dashboard (OBS-060) shows. A copy: safe to hand to another thread."""
        snapshot = {}
        for key, run in list(self._runs.items()):
            state = getattr(run.progress, "state", "running")
            text = str(getattr(state, "value", state))
            # A run exists, so it is at least starting, even before its first progress report.
            snapshot[key] = ("running" if text == "idle" else text, str(getattr(run.region, "name", "")))
        return snapshot

    def progress_snapshot(self) -> dict[Any, tuple[SessionProgress, str]]:
        """``{pier_key: (latest SessionProgress, session name)}`` for every Pier with a run in
        flight — what the Dashboard timelines (OBS-150) sample. Progress objects are replaced,
        never mutated, so the copy is safe to read from the UI thread."""
        return {key: (run.progress, str(getattr(run.region, "name", ""))) for key, run in list(self._runs.items())}

    # --- Starting -------------------------------------------------------------

    def start_region(self, region: Any) -> tuple[list[str], list[Any]]:
        """Run *region* right now (the Run control). Returns ``(problems, conflicts)``: if
        *problems* is non-empty nothing was started; *conflicts* lists other timeline entries
        the run's window overlaps (reported, not resolved — SCHED-150)."""
        key = self._key()
        running = self._runs.get(key)
        if running is not None:
            if running.manual:
                return ["A session is already running on this Pier."], []
            # A scheduled session is in progress: Run takes over. Stop it, and start this one as soon
            # as it has finished stopping (see _on_finished).
            self._takeover[key] = region
            running.executor.stop()
            return [], []
        if not region.blocks:
            return ["This session has no blocks to run."], []
        context = build_session_context(self._window, camera_slot=getattr(region, "camera_slot", None))
        problems = preflight(region.blocks, context)
        if problems:
            return problems, []
        scheduler = region._scheduler
        reason = scheduler.safety_block_reason() if scheduler is not None else ""
        if reason:
            return [f"Conditions are unsafe: {reason}."], []
        self._launch(region, context, manual=True, was_scheduled=region.is_scheduled)
        return [], []

    def _launch(self, region: Any, context: SessionContext, manual: bool,
                was_scheduled: bool = False, prior_start: str | None = None, key: Any = None) -> None:
        key = self._key() if key is None else key
        job = region._job if (not manual or region.is_scheduled) else None
        scheduler = region._scheduler
        executor = SessionExecutor(context, name=region.name)
        run = ActiveRun(region=region, job=job, scheduler=scheduler, executor=executor, manual=manual,
                        was_scheduled=was_scheduled, prior_start=prior_start)
        # No Qt parent: ``run.thread`` owns it. A parented QThread crashed natively (access
        # violation inside its constructor) on a live Pier; see CHANGELOG.
        thread = _RunThread(run)
        run.thread = thread

        def on_progress(progress: SessionProgress) -> None:      # worker thread -> queued to the UI
            thread.progress.emit(progress)

        executor.set_progress_callback(on_progress)
        from PySide6.QtCore import Qt
        thread.progress.connect(lambda p, k=key: self._on_progress(k, p), Qt.ConnectionType.QueuedConnection)
        thread.finished_with.connect(lambda state, k=key: self._on_finished(k, state), Qt.ConnectionType.QueuedConnection)
        self._runs[key] = run
        thread.start()
        self.changed.emit(key)

    # --- Control --------------------------------------------------------------

    def stop(self, region: Any) -> None:
        run = self.run_for(region)
        if run is not None:
            run.executor.stop()

    def pause(self, region: Any) -> None:
        run = self.run_for(region)
        if run is not None:
            run.executor.pause()

    def resume(self, region: Any) -> None:
        run = self.run_for(region)
        if run is not None:
            run.executor.resume()

    # --- Callbacks (UI thread) ---------------------------------------------------

    def _on_progress(self, key: Any, progress: SessionProgress) -> None:
        run = self._runs.get(key)
        if run is not None:
            run.progress = progress
            self.changed.emit(key)

    def _on_finished(self, key: Any, state: str) -> None:
        run = self._runs.pop(key, None)
        self._safety_paused.discard(key)
        if run is None:
            return
        if run.thread is not None:
            run.thread.wait()
        scheduler, job, region = run.scheduler, run.job, run.region
        message = ""
        if run.manual and state == "completed":
            # A completed session has nothing left to do (SES-210). If it was also on the Schedule,
            # that entry is satisfied too, and reaped below.
            if job is not None:
                job.runs_completed += 1
                job.run_state = "completed"
                job._frames_captured += getattr(run.result, "frames_captured", 0) or 0
                scheduler.save()
            else:
                region.delete()
        # Any other end of a manual Run leaves the session as it was: Run never touched the Schedule.
        if scheduler is not None:
            scheduler.reap_completed_jobs()
        result = run.result
        if result is not None and result.errors:
            message = "; ".join(result.errors[-3:])
        status = getattr(self._window, "_window", None)
        if status is not None and hasattr(status, "statusBar"):
            summary = {
                "completed": f"Session {region.name!r} completed.",
                "stopped": f"Session {region.name!r} stopped.",
            }.get(state, f"Session {region.name!r} ended with an error — {message or 'see log'}.")
            status.statusBar().showMessage(summary, 10000)
        self.changed.emit(key)
        waiting = self._takeover.pop(key, None)
        if waiting is not None:
            problems, _ = self.start_region(waiting) if key == self._key() else (["its Pier is no longer selected"], [])
            if problems and status is not None and hasattr(status, "statusBar"):
                status.statusBar().showMessage(f"Could not run {waiting.name!r}: {'; '.join(problems)}", 10000)

    # --- Scheduler tick -----------------------------------------------------------

    def _set_blocked(self, key: Any, reason: str) -> None:
        if self._blocked.get(key, "") != reason:
            self._blocked[key] = reason
            self.changed.emit(key)

    def blocked_reason(self, key: Any = None) -> str:
        """Why the Pier's scheduled jobs are held by the safety monitor, or ``""``."""
        return self._blocked.get(self._key() if key is None else key, "")

    def _enforce_safety(self) -> None:
        """Pause a scheduler-started run while conditions are unsafe and resume it once they
        are safe again (SCHED-060). A manual Run is left to the user. Runs on the UI thread
        every few seconds, since the safety page's rules are Qt-side state."""
        for key, run in list(self._runs.items()):
            if run.manual:
                continue
            reason = run.scheduler.safety_block_reason()
            if reason:
                self._set_blocked(key, reason)
                if run.executor.state.value == "running":
                    run.job.run_log.append(f"Paused: conditions are unsafe ({reason}).")
                    run.executor.pause()
                    self._safety_paused.add(key)
            elif key in self._safety_paused:
                self._safety_paused.discard(key)
                self._set_blocked(key, "")
                run.job.run_log.append("Conditions are safe again — resuming.")
                run.executor.resume()

    def _observatory_piers(self) -> list[Any]:
        """The selected Pier first, then every other Pier of the selected Observatory (OBS-140)."""
        from galileo.current_object import pier_key
        selected = getattr(self._window, "_current_pier", None)
        piers = [selected] if selected is not None else []
        observatory = getattr(self._window, "_current_observatory", None)
        if observatory is None:
            return piers
        try:
            from galileo.observatory import list_piers
            others = list_piers(observatory)
        except Exception:
            logger.exception("Could not list the Piers to service their scheduled sessions")
            return piers
        return piers + [p for p in others if pier_key(p) != pier_key(selected)]

    def _tick(self) -> None:
        """Start each Pier's next due scheduled job, for every Pier of the Observatory that is idle
        (OBS-020, OBS-140) — the selected Pier and the ones not on screen alike."""
        main = getattr(self._window, "_window", None)
        try:
            if main is None or not main.isVisible():      # closed/hidden window: nothing to service
                return
        except RuntimeError:                                # its C++ object is already gone
            self._timer.stop()
            return
        for pier in self._observatory_piers():
            try:
                self._tick_pier(pier)
            except Exception:
                # One Pier's trouble (a safety read, a bad job) must not stop the others being serviced.
                logger.exception("Could not service the scheduled sessions of Pier %r", getattr(pier, "name", pier))

    def _tick_pier(self, pier: Any) -> None:
        """Start *pier*'s next due scheduled job, if the Pier is idle and conditions are safe."""
        from galileo.current_object import pier_key
        key = pier_key(pier)
        if key in self._runs:
            return
        scheduler_for = getattr(self._window, "_scheduler_for_pier", None)
        if scheduler_for is None:
            return
        selected = key == self._key()
        scheduler = scheduler_for(pier.name)
        reason = scheduler.safety_block_reason()
        if reason:
            # Unsafe conditions hold every due job (SCHED-060); the Schedule screen shows why.
            self._set_blocked(key, reason)
            return
        self._set_blocked(key, "")
        for job in scheduler.due_jobs():
            region = job.sequence
            context = build_session_context(self._window, None if selected else pier,
                                            camera_slot=getattr(region, "camera_slot", None))
            if not selected and context.camera is None and context.mount is None:
                # Nothing of this Pier is connected (it was never selected since start-up, or was
                # disconnected). Hold the job rather than failing it: it starts once the Pier's
                # equipment is connected. The selected Pier still reports the problem, below.
                return
            problems = preflight(region.blocks, context)
            if problems:
                job.run_state = "error"
                job.run_log = ["Could not start:", *problems]
                scheduler.save()
                logger.warning("Scheduled session %r could not start: %s", job.name, "; ".join(problems))
                self.changed.emit(key)
                continue
            region._job = job
            self._launch(region, context, manual=False, key=key)
            return


def get_session_controller(window: Any) -> SessionRunController:
    """The window's single ``SessionRunController``, created on first use."""
    controller = window.__dict__.get("_session_controller") if hasattr(window, "__dict__") else None
    if controller is None:
        controller = SessionRunController(window)
        window._session_controller = controller
    return controller
