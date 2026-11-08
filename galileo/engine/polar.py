# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Polar alignment on the engine (CSURF-145): the Solve screen's own ``PolarAlignWorkflow``, assembled from the Pier's
devices and its Observatory's location.

A Pier runs one polar-alignment routine at a time, and none while a session or a plate solve is using the camera and
mount. The routine's live picture (phase, error, trend, the pole's offset in the latest frame, log) is kept as one
dictionary, published as the observable state ``polar.state`` on every change and returned by ``polar.status``, so a
client at the mount sees the knobs take effect without polling. The last picture stays readable after the run ends.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from galileo.control_surface import ObservableState, Refused
from galileo.control_surface.polar import STATE_KEY, quality
from galileo.engine.sessions import build_context

logger = logging.getLogger(__name__)

LOG_KEPT = 30
TREND_KEPT = 12                      # the recent totals a client draws as a trend
Factory = Callable[[str, Callable[[str], None], Callable[[Any], None]], Awaitable[Any]]


def site_of(devices: Any, pier: str) -> tuple[float, float] | None:
    """``(latitude, longitude)`` of the Pier's Observatory, or ``None`` when it has none set."""
    record = devices.pier_record(pier)
    try:
        observatory = record.observatory
        if observatory.latitude is not None and observatory.longitude is not None:
            return float(observatory.latitude), float(observatory.longitude)
    except Exception:
        logger.debug("Pier %s: could not read the Observatory's location", pier, exc_info=True)
    return None


async def build_workflow(devices: Any, pier: str, log: Callable[[str], None],
                         on_progress: Callable[[Any], None]) -> Any:
    """The Pier's ``PolarAlignWorkflow``; a solver that is not set up is refused in the solver's own words."""
    from galileo.observatory import make_pier_solver
    from galileo.polaralign import PolarAlignWorkflow
    site = site_of(devices, pier)
    if site is None:
        raise Refused("this Pier's Observatory has no latitude and longitude set")
    from galileo.current_object import pier_key
    context = await build_context(devices, pier)
    record = devices.pier_record(pier)
    solver = make_pier_solver(record, pier_key=pier_key(record))
    if not solver.is_available():
        raise Refused(f"the plate solver is not set up — {solver.missing_message()}")
    workflow = PolarAlignWorkflow(solver, camera=context.camera, mount=context.mount, latitude=site[0],
                                  longitude=site[1], on_progress=on_progress, log=log,
                                  frame_metadata=dict(context.frame_context))
    workflow.filter_wheel = context.filter_wheel
    return workflow


def _error_dict(error: Any, trend: list[float]) -> dict[str, Any]:
    return {"total_arcsec": error.total_arcsec, "altitude_arcsec": error.altitude_arcsec,
            "azimuth_arcsec": error.azimuth_arcsec, "azimuth_rotation_arcsec": error.azimuth_rotation_arcsec,
            "altitude_advice": error.altitude_advice(), "azimuth_advice": error.azimuth_advice(),
            "quality": quality(error.total_arcsec), "trend": list(trend)}


class EnginePolar:
    """``PolarAccess`` (``galileo.control_surface.polar``) over the device service and session runner."""

    def __init__(self, devices: Any, runner: Any, state: ObservableState, factory: Factory | None = None,
                 busy: Callable[[str], bool] | None = None, frames: Callable[[str, Any], int] | None = None) -> None:
        self._devices, self._runner, self._state = devices, runner, state
        self._frames = frames                                # takes each frame captured, so a client can look at it
        self._factory: Factory = factory or (lambda pier, log, progress: build_workflow(devices, pier, log, progress))
        self._busy = busy or (lambda pier: False)            # whether something else (a plate solve) holds the rig
        self._workflows: dict[str, Any] = {}
        self._picture: dict[str, dict[str, Any]] = {}

    def why_not(self, pier: str) -> str | None:
        camera = self._devices.controller(pier, "camera")
        if camera is None:
            return "this Pier has no camera"
        if not getattr(camera, "is_connected", True):
            return "the camera is not connected"
        mount = self._devices.controller(pier, "mount")
        if mount is None or not getattr(mount, "is_connected", True):
            return "the mount is not connected"
        if self._runner.is_running(pier):
            return "a session is running on this Pier"
        if pier in self._workflows:
            return "polar alignment is already running on this Pier"
        if self._busy(pier):
            return "a plate solve is running on this Pier"
        if site_of(self._devices, pier) is None:
            return "this Pier's Observatory has no latitude and longitude set"
        return None

    def running(self, pier: str) -> bool:
        return pier in self._workflows

    def _publish(self, pier: str) -> None:
        self._state.publish(pier, STATE_KEY, dict(self._picture[pier]))

    async def run(self, pier: str, *, exposure_s: float, settle_s: float, step_deg: float, direction: str,
                  refraction: bool, slew_from_zenith: bool, progress: Callable[[str], None]) -> dict[str, Any]:
        reason = self.why_not(pier)
        if reason:
            raise Refused(reason)
        from galileo.polaralign import PolarAlignSettings
        log: list[str] = []
        trend: deque[float] = deque(maxlen=TREND_KEPT)
        picture: dict[str, Any] = {"running": True, "phase": "measuring", "message": "Starting…", "step": 0,
                                   "steps": 3, "error": None, "target_offset_arcmin": None, "frame": None,
                                   "log": log, "stopped": False}
        self._picture[pier] = picture

        def note(message: str) -> None:
            log.append(message)
            del log[:-LOG_KEPT]

        def on_progress(update: Any) -> None:
            picture.update(phase=update.phase, message=update.message, step=update.step, steps=update.steps)
            if update.error is not None:
                trend.append(round(update.error.total_arcsec, 1))
                picture["error"] = _error_dict(update.error, list(trend))
                picture["target_offset_arcmin"] = (list(update.target_offset)
                                                   if update.target_offset is not None else None)
            geometry = getattr(update, "geometry", None)
            if geometry is not None and latest["width"]:
                # Where the axis point (circle) and the pole (cross) are in the frame "solve:<pier>" now holds, in
                # that frame's pixels from its top left, with what is needed to draw them over it.
                cx, cy = latest["width"] / 2.0, latest["height"] / 2.0
                picture["frame"] = {
                    "ref": f"solve:{pier}", "version": latest["version"], "width": latest["width"],
                    "height": latest["height"], "axis_px": [cx + geometry.axis_px[0], cy + geometry.axis_px[1]],
                    "pole_px": [cx + geometry.pole_px[0], cy + geometry.pole_px[1]],
                    "arcmin_per_px": geometry.arcmin_per_px}
            picture["log"] = list(log)
            self._publish(pier)
            progress(update.message)

        latest: dict[str, Any] = {"version": 0, "width": 0, "height": 0}

        def on_frame(data: Any) -> None:
            shape = getattr(data, "shape", None) or (0, 0)
            latest.update(height=int(shape[0]), width=int(shape[1]))
            if self._frames is not None:
                latest["version"] = self._frames(pier, data)

        self._workflows[pier] = None                         # claimed, so a second request is refused at once
        self._publish(pier)
        workflow = None
        try:
            workflow = await self._factory(pier, note, on_progress)
            self._workflows[pier] = workflow
            workflow.on_frame = on_frame
            await workflow.align(PolarAlignSettings(
                exposure_s=exposure_s, settle_s=settle_s, step_deg=step_deg, direction=direction,
                refraction=refraction, slew_from_zenith=slew_from_zenith))
            return {"error": picture["error"], "stopped": bool(getattr(workflow, "stopped", False)),
                    "log": list(log)}
        finally:
            self._workflows.pop(pier, None)
            picture.update(running=False, phase="finished", log=list(log),
                           stopped=bool(getattr(workflow, "stopped", False)))
            self._publish(pier)

    async def stop(self, pier: str) -> bool:
        workflow = self._workflows.get(pier)
        if workflow is None:
            return False
        workflow.stop()
        return True

    def status(self, pier: str) -> dict[str, Any]:
        picture = self._picture.get(pier) or {"running": False, "phase": "idle", "message": "", "step": 0,
                                              "steps": 3, "error": None, "target_offset_arcmin": None,
                                              "frame": None, "log": [], "stopped": False}
        return {**picture, "running": pier in self._workflows, "why_not": self.why_not(pier) or ""}


__all__ = ["EnginePolar", "build_workflow", "site_of"]
