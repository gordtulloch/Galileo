# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Assembling a ``SessionContext`` from a Pier's devices, with no Qt (SES-030, CSURF-180).

The desktop gathers a Pier's adapters from its Equipment pages and the engine gathers them from its device
service; both then call :func:`assemble_context`, so the services a session block asks for (imaging,
autofocus, plate solving, calibration, the focus offset between filters) are built the same way whoever
starts the run.
"""

from __future__ import annotations

import logging
from typing import Any

from galileo.history import get_history
from galileo.session_exec import SessionContext

logger = logging.getLogger(__name__)


class ConfiguredAutofocus:
    """An ``AutofocusService`` plus the Pier's saved sweep settings (FOC-070), exposing the
    zero-argument ``run()`` / ``cancel()`` the executor expects."""

    def __init__(self, service: Any, step_size: int, num_points: int) -> None:
        self._service, self._step, self._points = service, step_size, num_points

    async def run(self):
        return await self._service.run(step_size=self._step, num_points=self._points)

    def cancel(self) -> None:
        self._service.cancel()


def build_notify_service(observatory: Any) -> Any:
    """A ``NotificationService`` bound to *observatory*, with the operator's e-mail / SMS channels from its
    contact details (OBS-090, NOTIF-040) and in-app delivery to the log."""
    from galileo.notify import NotificationService
    from galileo.notify_settings import configure_service, load_notify_settings
    service = NotificationService()
    contacts = None
    # The database's Observatory record has no contact details yet; only the in-memory ``Observatory`` does
    # (OBS-090), so external channels are added only when they exist.
    if observatory is not None and hasattr(observatory, "contact_details"):
        service.set_owning_observatory(observatory)
        contacts = service.resolve_delivery_contacts()
    # Recipients: the Observatory's contact details when set, else Options > Notifications;
    # SMTP server, credentials, gateway and per-event switches always come from Options > Notifications.
    configure_service(service, load_notify_settings(), contacts)
    service.subscribe(lambda n: logger.info("Notification: %r", n))
    return service


def assemble_context(
    *, pier: Any, key: Any, camera_slot: str, camera: Any, mount: Any, filter_wheel: Any, focuser: Any,
    rotator: Any, dome: Any, dome_service: Any, guider: Any, flat_panel: Any, arbiter: Any, observatory: Any,
    notify_service: Any, location: Any, frame_context: dict,
) -> SessionContext:
    """The context for one run on *pier* from the devices already gathered. Anything ``None`` is not
    connected; the executor's pre-flight reports it."""
    ctx = SessionContext(
        pier_name=getattr(pier, "name", "") or "",
        camera=camera, mount=mount, filter_wheel=filter_wheel, focuser=focuser, rotator=rotator,
        dome=dome, dome_service=dome_service, arbiter=arbiter, guider=guider, flat_panel=flat_panel,
        observatory=observatory, notify_service=notify_service, history=get_history(), location=location,
    )
    if pier is not None and camera is not None:
        try:
            from galileo.observatory import get_device_config
            cfg = get_device_config(pier, "camera", slot=camera_slot)
            ctx.max_well_depth = cfg.max_well_depth if cfg is not None else None
        except Exception:
            logger.exception("Could not read the camera's Max Well Depth")

    def make_imaging():
        from galileo.ui.imaging import ImagingService
        svc = ImagingService(camera=camera)
        svc.auto_save_to_library = True
        svc.pier_key = key
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
        return ConfiguredAutofocus(service, params.step_size, params.num_points)

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
            camera=camera, filter_wheel=filter_wheel, flat_panel=flat_panel, mount=mount,
            output_dir=ImagingService()._scratch_folder() / "flats")

    ctx.make_imaging = make_imaging
    ctx.make_autofocus = make_autofocus
    ctx.make_solve_workflow = make_solve_workflow
    ctx.make_calibration = make_calibration
    ctx.apply_filter_focus_offset = apply_filter_focus_offset
    return ctx


__all__ = ["ConfiguredAutofocus", "assemble_context", "build_notify_service"]
