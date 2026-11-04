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

from galileo.control_surface import Refused
from galileo.engine.sessions import build_context

logger = logging.getLogger(__name__)

LOG_KEPT = 30
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

    def __init__(self, devices: Any, runner: Any, factory: Factory | None = None) -> None:
        self._devices, self._runner = devices, runner
        self._factory: Factory = factory or (lambda pier, log: build_workflow(devices, pier, log))
        self._workflows: dict[str, Any] = {}
        self._last: dict[str, dict[str, Any]] = {}

    def why_not(self, pier: str, mount: bool = False) -> str | None:
        camera = self._devices.controller(pier, "camera")
        if camera is None:
            return "this Pier has no camera"
        if not getattr(camera, "is_connected", True):
            return "the camera is not connected"
        if self._runner.is_running(pier):
            return "a session is running on this Pier"
        if pier in self._workflows:
            return "a plate solve is already running on this Pier"
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
        log: list[str] = []

        def note(message: str) -> None:
            log.append(message)
            del log[:-LOG_KEPT]
            progress(message)

        self._workflows[pier] = None                       # claimed, so a second request is refused at once
        try:
            workflow = await self._factory(pier, note)
            self._workflows[pier] = workflow
            if target is not None:
                workflow.set_target(target[0], target[1], target[2])
            settings = SolveSettings(
                exposure_s=exposure_s, accuracy_arcsec=accuracy_arcsec, max_iterations=max_iterations,
                binning=binning, gain=gain, filter_name=filter_name,
                action={"nothing": SolveAction.NOTHING, "sync": SolveAction.SYNC,
                        "slew": SolveAction.SLEW_TO_TARGET}[action])
            results = await workflow.capture_and_solve(settings)
            summary = {
                "solutions": [_solution(r) for r in results],
                "solved": bool(results) and bool(results[-1].success),
                "stopped": bool(getattr(workflow, "stopped", False)), "log": list(log)}
            self._last[pier] = summary
            return summary
        finally:
            self._workflows.pop(pier, None)

    async def stop(self, pier: str) -> bool:
        workflow = self._workflows.get(pier)
        if workflow is None:
            return False
        workflow.stop()
        return True

    def status(self, pier: str) -> dict[str, Any]:
        return {"running": pier in self._workflows, "why_not": self.why_not(pier) or "",
                "last": self._last.get(pier)}


def _solution(result: Any) -> dict[str, Any]:
    return {"success": bool(result.success), "ra_deg": result.ra_deg, "dec_deg": result.dec_deg,
            "rotation_deg": result.rotation_deg, "scale_arcsec_px": result.scale_arcsec_px,
            "failure_reason": result.failure_reason}


__all__ = ["EngineSolve", "build_workflow"]
