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

from galileo.history import get_history
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

class _ConfiguredAutofocus:
    """An ``AutofocusService`` plus the Pier's saved sweep settings (FOC-070), exposing the
    zero-argument ``run()`` / ``cancel()`` the executor expects."""

    def __init__(self, service: Any, step_size: int, num_points: int) -> None:
        self._service, self._step, self._points = service, step_size, num_points

    async def run(self):
        return await self._service.run(step_size=self._step, num_points=self._points)

    def cancel(self) -> None:
        self._service.cancel()


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
    """A ``NotificationService`` bound to the current Observatory, with the operator's e-mail /
    SMS channels from its contact details (OBS-090, NOTIF-040) and in-app delivery to the log."""
    from galileo.notify import NotificationService
    from galileo.notify_settings import configure_service, load_notify_settings
    service = NotificationService()
    observatory = getattr(window, "_current_observatory", None)
    contacts = None
    # The UI's Observatory is a database record; only the in-memory ``Observatory`` carries
    # contact details (OBS-090) today, so external channels are added only when they exist.
    if observatory is not None and hasattr(observatory, "contact_details"):
        service.set_owning_observatory(observatory)
        contacts = service.resolve_delivery_contacts()
    # Recipients: the Observatory's contact details when set, else Options > Notifications;
    # SMTP server, credentials, gateway and per-event switches always come from Options > Notifications.
    configure_service(service, load_notify_settings(), contacts)
    service.subscribe(lambda n: logger.info("Notification: %r", n))
    return service


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

    ctx = SessionContext(
        pier_name=getattr(pier, "name", "") or "",
        camera=camera, mount=mount, filter_wheel=wheel, focuser=focuser,
        rotator=_page_adapter(window, "rotator", key, selected),
        dome=_page_adapter(window, "dome", key, selected),
        dome_service=_dome_service(window, key, selected), arbiter=_observatory_arbiter(window),
        guider=guider, flat_panel=_page_adapter(window, "flat_panel", key, selected),
        observatory=getattr(window, "_current_observatory", None),
        notify_service=_build_notify_service(window),
        history=get_history(),
    )

    location_getter = getattr(window, "_flats_observing_location", None)
    ctx.location = (location_getter() if selected else location_getter(pier)) if location_getter else None
    if pier is not None and camera is not None:
        try:
            from galileo.observatory import get_device_config
            cfg = get_device_config(pier, "camera", slot=camera_slot)
            ctx.max_well_depth = cfg.max_well_depth if cfg is not None else None
        except Exception:
            logger.exception("Could not read the camera's Max Well Depth")

    frame_context_getter = getattr(window, "_imaging_frame_context", None)
    try:
        if not (frame_context_getter and camera is not None):
            frame_context = {}
        else:
            frame_context = frame_context_getter(pier, camera_slot=camera_slot)
    except Exception:
        logger.exception("Could not gather the FITS header context")
        frame_context = {}

    def make_imaging():
        from galileo.ui.imaging import ImagingService
        svc = ImagingService(camera=camera)
        svc.auto_save_to_library = True
        svc.frame_context = dict(frame_context)
        svc._mount = mount
        return svc

    def autofocus_inputs():
        from galileo.observatory import get_autofocus_params, get_filter_offset_steps
        return get_autofocus_params(pier), get_filter_offset_steps(pier)

    def make_autofocus():
        from galileo.autofocus import AutofocusService
        params, offsets = autofocus_inputs()
        service = AutofocusService(
            camera=camera, focuser=focuser, exposure_s=params.exposure_s,
            backlash_compensation=params.backlash_compensation, pier_key=key, filter_offsets=offsets)
        service._current_position = int(getattr(focuser, "position", 0) or 0)
        return _ConfiguredAutofocus(service, params.step_size, params.num_points)

    async def apply_filter_focus_offset(from_filter, to_filter):
        if focuser is None or not from_filter or from_filter == to_filter:
            return
        params, offsets = autofocus_inputs()
        if not offsets:
            return
        from galileo.autofocus import AutofocusService
        service = AutofocusService(
            focuser=focuser, backlash_compensation=params.backlash_compensation, filter_offsets=offsets)
        service._current_position = int(getattr(focuser, "position", 0) or 0)
        await service.apply_filter_offset(from_filter, to_filter)

    def make_solve_workflow():
        from galileo.observatory import make_pier_solver
        from galileo.platesolve import SolveWorkflow
        solver = make_pier_solver(pier, pier_key=key)
        if not solver.is_available():
            raise RuntimeError(f"the plate solver is not set up — {solver.missing_message()}")
        return SolveWorkflow(solver, camera=camera, mount=mount, log=logger.info,
                             frame_metadata=dict(frame_context))

    def make_calibration():
        from galileo.calibration import CalibrationService
        from galileo.ui.imaging import ImagingService
        return CalibrationService(
            camera=camera, filter_wheel=wheel, flat_panel=ctx.flat_panel, mount=mount,
            output_dir=ImagingService()._scratch_folder() / "flats")

    ctx.make_imaging = make_imaging
    ctx.make_autofocus = make_autofocus
    ctx.make_solve_workflow = make_solve_workflow
    ctx.make_calibration = make_calibration
    ctx.apply_filter_focus_offset = apply_filter_focus_offset
    return ctx


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

@dataclass
class ActiveRun:
    """One in-flight session on one Pier."""
    region: Any
    job: Any
    scheduler: Any
    executor: SessionExecutor
    thread: QThread | None = None
    manual: bool = True                      # started by Run, not by the scheduler's tick
    prior_start: str | None = None           # the job's timeline start before a manual Run moved it
    was_scheduled: bool = False
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
        executor = run.executor

        async def runner(job):
            run.result = await executor.run(job.sequence.blocks)
            return run.result

        try:
            state = asyncio.run(run.scheduler.run_job(run.job, runner))
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
        if key in self._runs:
            return ["A session is already running on this Pier."], []
        if not region.blocks:
            return ["This session has no blocks to run."], []
        context = build_session_context(self._window, camera_slot=getattr(region, "camera_slot", None))
        problems = preflight(region.blocks, context)
        if problems:
            return problems, []
        was_scheduled = region.is_scheduled
        prior_start = region._job.scheduled_start_utc if (was_scheduled and region._job) else None
        conflicts = region.run_now()
        self._launch(region, context, manual=True, was_scheduled=was_scheduled, prior_start=prior_start)
        return [], conflicts

    def _launch(self, region: Any, context: SessionContext, manual: bool,
                was_scheduled: bool = False, prior_start: str | None = None, key: Any = None) -> None:
        key = self._key() if key is None else key
        job = region._job
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
        thread.progress.connect(lambda p, k=key: self._on_progress(k, p))
        thread.finished_with.connect(lambda state, k=key: self._on_finished(k, state))
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
        if state != "completed" and run.manual:
            # A manual Run that didn't finish leaves the session as it was before: back on its
            # earlier timeline slot if it had one, otherwise an editable draft again.
            if run.was_scheduled:
                job.scheduled_start_utc = run.prior_start
                job.run_state = "pending"
                scheduler.save()
            else:
                region.deschedule()
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
