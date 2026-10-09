# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Runs Sessions-screen sessions (SES-030, SES-040, SES-050, SES-350) and fires scheduled ones.

``SessionRunController`` is the Qt-side owner of session execution. It builds a
``SessionContext`` from the active Pier's connected devices, runs
``galileo.sequencer.session_exec.SessionExecutor`` on a worker thread (the same
QThread-plus-``asyncio.run`` pattern every other long device operation in this app uses, so
the UI never blocks), and relays progress back to the Sessions page through a queued signal.

Two things start a run, and both go through ``ObservatoryScheduler.run_job`` so a session
behaves identically however it was started:

* the session card's **Run** control (``start_region``), and
* a periodic tick that starts any job on the active Pier's queue whose timeline window has
  begun (``_tick``).

Limitation: devices are only live for the *active* Pier (``AppWindow._device_pages`` is
rebuilt on a Pier switch), so only the active Pier's queue is serviced; a due job on another
Pier waits until that Pier is selected. One session runs per Pier at a time.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from galileo.sequencer.session_exec import (
    SessionContext,
    SessionExecutor,
    SessionProgress,
    SessionRunResult,
    preflight,
)

logger = logging.getLogger(__name__)

TICK_INTERVAL_MS = 15_000


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


def _page_adapter(window: Any, page: str) -> Any:
    return (getattr(window, "_device_pages", {}).get(page) or {}).get("adapter")


def _build_notify_service(window: Any) -> Any:
    """A ``NotificationService`` bound to the current Observatory, with the operator's e-mail /
    SMS channels from its contact details (OBS-090, NOTIF-040) and in-app delivery to the log."""
    from galileo.notify import EmailChannel, NotificationService, SmsChannel
    service = NotificationService()
    observatory = getattr(window, "_current_observatory", None)
    contacts = None
    # The UI's Observatory is a database record; only the in-memory ``Observatory`` carries
    # contact details (OBS-090) today, so external channels are added only when they exist.
    if observatory is not None and hasattr(observatory, "contact_details"):
        service.set_owning_observatory(observatory)
        contacts = service.resolve_delivery_contacts()
    wanted = set((contacts.channels if contacts and contacts.channels else None) or ["email", "sms"])
    if contacts is not None:
        if contacts.email and "email" in wanted:
            service.add_channel(EmailChannel(contacts.email))
        if contacts.phone_number and "sms" in wanted:
            service.add_channel(SmsChannel(contacts.phone_number))
    service.subscribe(lambda n: logger.info("Notification: %r", n))
    return service


def build_session_context(window: Any) -> SessionContext:
    """Snapshot the active Pier's connected devices and services for one run. Call on the UI
    thread. Anything not connected is left ``None``; the executor's pre-flight reports it."""
    from galileo.current_object import pier_key
    from galileo.ui.app_window._common import _camera_backend_key_for_slot

    pier = getattr(window, "_current_pier", None)
    key = pier_key(pier)
    camera = getattr(window, "_camera_backends", {}).get(
        _camera_backend_key_for_slot(getattr(window, "_active_camera_slot", "primary")))
    mount = _page_adapter(window, "mount")
    focuser_getter = (getattr(window, "_device_pages", {}).get("focuser") or {}).get("get_adapter")
    focuser = focuser_getter() if focuser_getter else None
    wheel_getter = getattr(window, "_active_filter_wheel", None)
    wheel = wheel_getter() if wheel_getter else _page_adapter(window, "filter_wheel")
    guider_getter = (getattr(window, "_device_pages", {}).get("guider") or {}).get("get_service")
    guider = guider_getter() if guider_getter else None
    if guider is not None and not guider.is_connected:
        guider = None

    ctx = SessionContext(
        pier_name=getattr(pier, "name", "") or "",
        camera=camera, mount=mount, filter_wheel=wheel, focuser=focuser,
        rotator=_page_adapter(window, "rotator"), dome=_page_adapter(window, "dome"),
        guider=guider, flat_panel=_page_adapter(window, "flat_panel"),
        observatory=getattr(window, "_current_observatory", None),
        notify_service=_build_notify_service(window),
    )

    location_getter = getattr(window, "_flats_observing_location", None)
    ctx.location = location_getter() if location_getter else None
    if pier is not None and camera is not None:
        try:
            from galileo.observatory import get_device_config
            cfg = get_device_config(pier, "camera", slot=window._active_camera_slot)
            ctx.max_well_depth = cfg.max_well_depth if cfg is not None else None
        except Exception:
            logger.exception("Could not read the camera's Max Well Depth")

    frame_context_getter = getattr(window, "_imaging_frame_context", None)
    try:
        frame_context = frame_context_getter() if (frame_context_getter and camera is not None) else {}
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
        from galileo.observatory import get_solver_settings
        from galileo.platesolve import PlateSolver, SolveWorkflow
        executable, params = get_solver_settings(pier)
        solver = PlateSolver(backend="astap", executable=executable, params=params, pier_key=key)
        if not solver.executable:
            raise RuntimeError("the ASTAP solver was not found — install it, or set its path in Options > Solve")
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

    def start_ticking(self) -> None:
        """Begin servicing the active Pier's scheduler queue (call once the window is real)."""
        if not self._timer.isActive():
            self._timer.start()

    def stop_ticking(self, *_args) -> None:
        self._timer.stop()

    # --- Queries --------------------------------------------------------------

    def _key(self) -> Any:
        from galileo.current_object import pier_key
        return pier_key(getattr(self._window, "_current_pier", None))

    def run_for(self, region: Any) -> ActiveRun | None:
        return next((r for r in self._runs.values() if r.region is region), None)

    def is_running(self, region: Any = None) -> bool:
        return (self.run_for(region) is not None) if region is not None else bool(self._runs)

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
        context = build_session_context(self._window)
        problems = preflight(region.blocks, context)
        if problems:
            return problems, []
        was_scheduled = region.is_scheduled
        prior_start = region._job.scheduled_start_utc if (was_scheduled and region._job) else None
        conflicts = region.run_now()
        self._launch(region, context, manual=True, was_scheduled=was_scheduled, prior_start=prior_start)
        return [], conflicts

    def _launch(self, region: Any, context: SessionContext, manual: bool,
                was_scheduled: bool = False, prior_start: str | None = None) -> None:
        key = self._key()
        job = region._job
        scheduler = region._scheduler
        executor = SessionExecutor(context, name=region.name)
        run = ActiveRun(region=region, job=job, scheduler=scheduler, executor=executor, manual=manual,
                        was_scheduled=was_scheduled, prior_start=prior_start)
        thread = _RunThread(run, self)
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

    def _tick(self) -> None:
        """Start the active Pier's next due scheduled job, if the Pier is idle."""
        main = getattr(self._window, "_window", None)
        try:
            if main is None or not main.isVisible():      # closed/hidden window: nothing to service
                return
        except RuntimeError:                                # its C++ object is already gone
            self._timer.stop()
            return
        key = self._key()
        pier = getattr(self._window, "_current_pier", None)
        if pier is None or key in self._runs:
            return
        scheduler_for = getattr(self._window, "_scheduler_for_pier", None)
        if scheduler_for is None:
            return
        scheduler = scheduler_for(pier.name)
        for job in scheduler.due_jobs():
            region = job.sequence
            context = build_session_context(self._window)
            problems = preflight(region.blocks, context)
            if problems:
                job.run_state = "error"
                job.run_log = ["Could not start:", *problems]
                scheduler.save()
                logger.warning("Scheduled session %r could not start: %s", job.name, "; ".join(problems))
                self.changed.emit(key)
                continue
            region._job = job
            self._launch(region, context, manual=False)
            return


def get_session_controller(window: Any) -> SessionRunController:
    """The window's single ``SessionRunController``, created on first use."""
    controller = window.__dict__.get("_session_controller") if hasattr(window, "__dict__") else None
    if controller is None:
        controller = SessionRunController(window)
        window._session_controller = controller
    return controller
