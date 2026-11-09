# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Plate solving on the engine (CSURF-140): the Solve screen's own ``SolveWorkflow``, assembled from the Pier's devices.

The workflow comes from the same assembly a session's Plate Solve block uses (``make_solve_workflow``), so the solver,
its search parameters and the image scale are the Pier's saved Options > Solve settings and optics. A Pier runs one
solve at a time and none while a session is running, since both would drive the one camera and mount. The workflow's
own log lines become the operation's progress, and the last run's solutions and log stay readable until the next run.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from galileo.control_surface import ObservableState, Refused
from galileo.engine.sessions import build_context

logger = logging.getLogger(__name__)

LOG_KEPT = 30
POINTS_KEPT = 30                    # solutions' offsets from their targets kept for the bullseye
ARCSEC_PER_RAD_UM_MM = 206.265       # image scale (″/px) = this x pixel size (µm) / focal length (mm)
Factory = Callable[[str, Callable[[str], None]], Awaitable[Any]]


async def build_workflow(devices: Any, pier: str, log: Callable[[str], None]) -> Any:
    """The Pier's ``SolveWorkflow``; a solver that is not set up is refused in the solver's own words."""
    context = await build_context(devices, pier)
    try:
        workflow = context.make_solve_workflow(log=log)
    except RuntimeError as exc:
        raise Refused(str(exc)) from exc
    workflow.filter_wheel = devices.controller(pier, "filter_wheel")
    return workflow


class EngineSolve:
    """``SolveAccess`` (``galileo.control_surface.solve``) over the device service and session runner."""

    def __init__(self, devices: Any, runner: Any, factory: Factory | None = None,
                 busy: Callable[[str], bool] | None = None,
                 frames: Callable[[str, Any], int] | None = None, state: ObservableState | None = None) -> None:
        self._devices, self._runner = devices, runner
        self._state = state                                # where what the screen shows is published, if anywhere
        self._points: dict[str, list[list[float]]] = {}
        self._frames = frames                              # takes each frame captured for solving, so it can be previewed
        self._busy = busy or (lambda pier: False)          # whether polar alignment holds the camera and mount
        self._factory: Factory = factory or (lambda pier, log: build_workflow(devices, pier, log))
        self._workflows: dict[str, Any] = {}
        self._last: dict[str, dict[str, Any]] = {}

    def why_not(self, pier: str, mount: bool = False, camera: bool = True) -> str | None:
        device = self._devices.controller(pier, "camera")
        if camera and device is None:
            return "this Pier has no camera"
        if camera and not getattr(device, "is_connected", True):
            return "the camera is not connected"
        if self._runner.is_running(pier):
            return "a session is running on this Pier"
        if pier in self._workflows:
            return "a plate solve is already running on this Pier"
        if self._busy(pier):
            return "polar alignment is running on this Pier"
        if mount:
            controller = self._devices.controller(pier, "mount")
            if controller is None or not getattr(controller, "is_connected", True):
                return "the mount is not connected"
        return None

    async def run(self, pier: str, *, action: str, exposure_s: float, accuracy_arcsec: float, max_iterations: int,
                  binning: int, gain: int, filter_name: str, target: tuple[float, float, str] | None,
                  progress: Callable[[str], None]) -> dict[str, Any]:
        reason = self.why_not(pier, mount=action != "nothing")
        if reason:
            raise Refused(reason)
        from galileo.platesolve import SolveAction, SolveSettings
        if action == "slew" and target is None:
            target = self._current_object(pier)            # as the desktop: the Pier's current object, if it has one
        size = {"width": 0, "height": 0}

        def on_frame(data: Any) -> int:
            shape = getattr(data, "shape", None) or (0, 0)
            size.update(height=int(shape[0]), width=int(shape[1]))
            version = self._frames(pier, data) if self._frames is not None else 0
            # Announced as it arrives, so a client can show the frame being solved instead of waiting for the result.
            self._publish(pier, "solve.frame", {"version": version, "width": size["width"], "height": size["height"]})
            return version

        def configure(workflow: Any) -> None:
            workflow.on_frame = on_frame
            if target is not None:
                workflow.set_target(target[0], target[1], target[2])

        settings = SolveSettings(
            exposure_s=exposure_s, accuracy_arcsec=accuracy_arcsec, max_iterations=max_iterations,
            binning=binning, gain=gain, filter_name=filter_name,
            action={"nothing": SolveAction.NOTHING, "sync": SolveAction.SYNC,
                    "slew": SolveAction.SLEW_TO_TARGET}[action])
        return await self._execute(pier, progress, configure, lambda workflow: workflow.capture_and_solve(settings),
                                   size, accuracy_arcsec)

    async def load(self, pier: str, *, frame_id: str, progress: Callable[[str], None]) -> dict[str, Any]:
        """Load & Slew: solve a Library frame and slew the mount to where it points."""
        reason = self.why_not(pier, mount=True, camera=False)
        if reason:
            raise Refused(reason)
        import asyncio

        from galileo.library.core.location import LocationError, ensure_local_sync
        try:
            path = await asyncio.to_thread(ensure_local_sync, frame_id)
        except (LocationError, KeyError, ValueError, OSError) as exc:
            raise Refused(f"that frame is not available: {exc}") from exc
        return await self._execute(pier, progress, lambda workflow: None,
                                   lambda workflow: workflow.solve_file(str(path), slew=True), {"width": 0, "height": 0},
                                   None)

    def frames(self) -> list[dict[str, Any]]:
        from galileo.control_surface.frames import recent_library_frames
        return recent_library_frames(30)

    async def _execute(self, pier: str, progress: Callable[[str], None], configure: Callable[[Any], None],
                       start: Callable[[Any], Awaitable[Any]], size: dict[str, int],
                       accuracy_arcsec: float | None) -> dict[str, Any]:
        log: list[str] = []

        def note(message: str) -> None:
            log.append(message)
            del log[:-LOG_KEPT]
            progress(message)

        self._workflows[pier] = None                       # claimed, so a second request is refused at once
        self._publish(pier, "solve.running", True)
        if accuracy_arcsec is not None:
            self._publish(pier, "solve.accuracy_arcsec", accuracy_arcsec)
        try:
            workflow = await self._factory(pier, note)
            self._workflows[pier] = workflow
            configure(workflow)
            results = await start(workflow)
            target = getattr(workflow, "target", None)
            optics = self._optics(pier)
            solutions = [_solution(r, target if len(results) else None, size, optics) for r in results]
            summary = {"solutions": solutions, "solved": bool(results) and bool(results[-1].success),
                       "stopped": bool(getattr(workflow, "stopped", False)), "log": list(log)}
            self._last[pier] = summary
            points = self._points.setdefault(pier, [])
            points.extend([s["d_ra_arcsec"], s["d_dec_arcsec"]] for s in solutions if s.get("d_ra_arcsec") is not None)
            del points[:-POINTS_KEPT]
            self._publish(pier, "solve.points", [list(p) for p in points])
            self._publish(pier, "solve.last", summary)
            return summary
        finally:
            self._workflows.pop(pier, None)
            self._publish(pier, "solve.running", False)

    def _publish(self, pier: str, key: str, value: Any) -> None:
        if self._state is not None:
            self._state.publish(pier, key, value)

    def _current_object(self, pier: str) -> tuple[float, float, str] | None:
        try:
            from galileo.current_object import get_current_objects
            obj = get_current_objects().get(self._devices.pier_record(pier))
        except Exception:
            logger.debug("Pier %s: could not read the current object", pier, exc_info=True)
            return None
        return None if obj is None else (obj.ra_deg, obj.dec_deg, obj.name)

    def _optics(self, pier: str) -> tuple[float | None, float | None, float | None]:
        """``(focal length mm, aperture mm, camera pixel size µm)``, ``None`` for whatever is not set."""
        focal = aperture = pixel = None
        try:
            from galileo.observatory import get_device_config, list_optical_tubes
            record = self._devices.pier_record(pier)
            tubes = list_optical_tubes(record)
            if tubes:
                focal, aperture = tubes[0].focal_length_mm or None, tubes[0].aperture_mm or None
            cfg = get_device_config(record, "camera")
            pixel = (cfg.pixel_size_um if cfg is not None else None) or None
        except Exception:
            logger.debug("Pier %s: could not read the optics", pier, exc_info=True)
        return focal, aperture, pixel

    async def stop(self, pier: str) -> bool:
        workflow = self._workflows.get(pier)
        if workflow is None:
            return False
        workflow.stop()
        return True

    def running(self, pier: str) -> bool:
        return pier in self._workflows

    def status(self, pier: str) -> dict[str, Any]:
        return {"running": pier in self._workflows, "why_not": self.why_not(pier) or "",
                "last": self._last.get(pier), "points": list(self._points.get(pier, []))}


def _solution(result: Any, target: tuple[float, float] | None = None, size: dict[str, int] | None = None,
              optics: tuple[float | None, float | None, float | None] = (None, None, None)) -> dict[str, Any]:
    """One solve as the Solve screen reads it: the plain result, then Solution Coordinates (JNow) as the desktop shows
    them: the position, the error from the target, scale, rotation, field of view, and the focal length and ratio the
    scale implies against the optics set up."""
    out: dict[str, Any] = {
        "success": bool(result.success), "ra_deg": result.ra_deg, "dec_deg": result.dec_deg,
        "rotation_deg": result.rotation_deg, "scale_arcsec_px": result.scale_arcsec_px,
        "failure_reason": result.failure_reason}
    if not result.success or result.ra_deg is None or result.dec_deg is None:
        return out
    from galileo.platesolve import j2000_to_mount_frame
    from galileo.platesolve_solvers import angular_offset_arcsec
    ra_now, dec_now = j2000_to_mount_frame(result.ra_deg, result.dec_deg, None)
    out.update(jnow_ra_hours=ra_now / 15.0, jnow_dec_deg=dec_now)
    if target is not None:
        d_ra, d_dec = angular_offset_arcsec(result.ra_deg, result.dec_deg, target[0], target[1])
        out.update(d_ra_arcsec=d_ra, d_dec_arcsec=d_dec, error_arcsec=(d_ra ** 2 + d_dec ** 2) ** 0.5)
    scale = result.scale_arcsec_px
    width, height = (size or {}).get("width", 0), (size or {}).get("height", 0)
    if scale and width and height:
        out["fov_arcmin"] = [width * scale / 60.0, height * scale / 60.0]
    focal, aperture, pixel = optics
    if scale and pixel:
        solved_focal = ARCSEC_PER_RAD_UM_MM * pixel / scale
        out["focal_mm"] = solved_focal
        if aperture:
            out["focal_ratio"] = solved_focal / aperture
        if focal:
            out.update(expected_focal_mm=focal, scale_ratio=scale / (ARCSEC_PER_RAD_UM_MM * pixel / focal))
            if aperture:
                out["expected_focal_ratio"] = focal / aperture
    return out


__all__ = ["EngineSolve", "build_workflow"]
