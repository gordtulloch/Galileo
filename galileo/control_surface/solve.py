# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Control Surface catalogue for plate solving (CSURF-140): solve a new frame, sync the mount to it, centre on a
target, and stop.

``solve.capture`` takes a frame with the Pier's camera and solves it; ``solve.sync`` does the same and tells the mount
where it is really pointing; ``solve.centre`` slews to a target and corrects until the solution is within the accuracy
asked for. All three are long-running: they answer at once with a correlation id, report each step as progress, and end
with one finished event. The solutions themselves (a finished event carries only the outcome) are read from
``solve.status`` afterwards. The solver, its search parameters and the image scale come from the Pier's saved
Options > Solve settings and optics, exactly as for the Solve screen, so a Pier whose solver is not set up is refused
with the solver's own message.

Not offered yet: solving a frame already on disk, and the polar-alignment routine. Both need the engine to keep the
last frame as a file, and polar alignment is a multi-step guided routine that has no operation shape yet.

``register_solve_operations(registry, access)`` takes a :class:`SolveAccess` so this module imports no camera or solver.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry
from galileo.control_surface.schema import Arg


class SolveAccess(Protocol):
    def why_not(self, pier: str, mount: bool = False) -> str | None:
        """Why a solve cannot start on *pier* now (no camera, a session or solve running, and with *mount* no
        connected mount), or ``None``."""

    async def run(self, pier: str, *, action: str, exposure_s: float, accuracy_arcsec: float, max_iterations: int,
                  binning: int, gain: int, filter_name: str, target: tuple[float, float, str] | None,
                  progress: Any) -> dict[str, Any]:
        """Capture and solve; ``action`` is ``nothing``, ``sync`` or ``slew`` (to *target*). Calls
        ``progress(message)`` for each step; returns every solution."""

    async def stop(self, pier: str) -> bool:
        """Cancel the run in progress; ``False`` when none is running."""

    def status(self, pier: str) -> dict[str, Any]: ...


_COMMON = (
    Arg("exposure_s", "float", required=False, default=5.0, minimum=0.001, maximum=600, unit="s"),
    Arg("accuracy_arcsec", "float", required=False, default=30.0, minimum=1, maximum=3600, unit="arcsec"),
    Arg("max_iterations", "int", required=False, default=5, minimum=1, maximum=20),
    Arg("binning", "int", required=False, default=1, minimum=1, maximum=8),
    Arg("gain", "int", required=False, default=0, minimum=0, maximum=10000),
    Arg("filter", "str", required=False),
)


def register_solve_operations(registry: Registry, access: SolveAccess) -> None:
    async def run(ctx: OperationContext, args: dict[str, Any], action: str,
                  target: tuple[float, float, str] | None) -> Any:
        return await access.run(
            ctx.pier, action=action, exposure_s=float(args["exposure_s"]),
            accuracy_arcsec=float(args["accuracy_arcsec"]), max_iterations=int(args["max_iterations"]),
            binning=int(args["binning"]), gain=int(args["gain"]), filter_name=args.get("filter") or "",
            target=target, progress=lambda message: ctx.progress(None, message))

    async def capture(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return await run(ctx, args, "nothing", None)

    async def sync(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return await run(ctx, args, "sync", None)

    async def centre(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return await run(ctx, args, "slew", (float(args["ra_deg"]), float(args["dec_deg"]), args.get("name") or ""))

    async def stop(ctx: OperationContext, args: dict[str, Any]) -> Any:
        if not await access.stop(ctx.pier):
            raise Refused("no plate solve is running on this Pier")
        return {"stopping": True}

    async def status(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return access.status(ctx.pier)

    registry.register(OperationSpec(
        "solve.capture", "operate", _COMMON, needs_lease=True, long_running=True, available=access.why_not,
        description="Take a frame and solve it; the mount is not touched"), capture)
    registry.register(OperationSpec(
        "solve.sync", "operate", _COMMON, needs_lease=True, long_running=True,
        available=lambda pier: access.why_not(pier, mount=True),
        description="Take a frame, solve it and tell the mount where it is really pointing"), sync)
    registry.register(OperationSpec(
        "solve.centre", "operate",
        (Arg("ra_deg", "float", minimum=0, maximum=360, unit="deg"),
         Arg("dec_deg", "float", minimum=-90, maximum=90, unit="deg"),
         Arg("name", "str", required=False), *_COMMON),
        needs_lease=True, long_running=True, available=lambda pier: access.why_not(pier, mount=True),
        description="Slew to a J2000 position and correct with solved frames until within the accuracy"), centre)
    registry.register(OperationSpec("solve.stop", "operate", (), needs_lease=True,
                                    description="Cancel the plate solve in progress"), stop)
    registry.register(OperationSpec("solve.status", "read", (), needs_lease=False,
                                    description="Whether a solve is running, its latest solutions and log"), status)


__all__ = ["SolveAccess", "register_solve_operations"]
