# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Control Surface catalogue for plate solving (CSURF-140): solve a new frame, sync the mount to it, centre on a
target, and stop.

``solve.capture`` takes a frame with the Pier's camera and solves it, then does the Solver Action asked for (``nothing``,
the default; ``sync``, which tells the mount where it is really pointing; or ``slew``, which slews to the Pier's current
object, or back to where the mount pointed when the run began if there is none, and corrects until the solution is within
the accuracy asked for); ``solve.sync`` and ``solve.centre`` are the same with the action fixed, ``centre`` to a target
given as coordinates; ``solve.load`` solves a Library frame (``solve.frames`` lists recent ones) and slews the mount to
where it points, as Load & Slew does on the desktop. All of these are long-running: they answer at once with a correlation id, report each step as progress, and end
with one finished event. The solutions themselves (a finished event carries only the outcome) are read from
``solve.status`` afterwards. The solver, its search parameters and the image scale come from the Pier's saved
Options > Solve settings and optics, exactly as for the Solve screen, so a Pier whose solver is not set up is refused
with the solver's own message.

Polar alignment is its own catalogue, ``polar.*`` (CSURF-145, ``galileo.control_surface.polar``).

What the screen shows is observable state, published as it changes: ``solve.running``, ``solve.accuracy_arcsec`` (the ring
of the bullseye), ``solve.points`` (the ``[dRA, dDE]`` arcsecond offsets of recent solutions from their targets, oldest
first, which is the bullseye) and ``solve.last`` (the last run: ``solutions``, each with its position in J2000 and JNow,
its error from the target, scale, rotation, field of view and the focal length and focal ratio it implies, then
``solved``, ``stopped`` and ``log``).

``register_solve_operations(registry, access)`` takes a :class:`SolveAccess` so this module imports no camera or solver.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry
from galileo.control_surface.schema import Arg


class SolveAccess(Protocol):
    def why_not(self, pier: str, mount: bool = False, camera: bool = True) -> str | None:
        """Why a solve cannot start on *pier* now (with *camera*, no camera; a session or solve running; and with
        *mount* no connected mount), or ``None``."""

    async def run(self, pier: str, *, action: str, exposure_s: float, accuracy_arcsec: float, max_iterations: int,
                  binning: int, gain: int, filter_name: str, target: tuple[float, float, str] | None,
                  progress: Any) -> dict[str, Any]:
        """Capture and solve; ``action`` is ``nothing``, ``sync`` or ``slew`` (to *target*). Calls
        ``progress(message)`` for each step; returns every solution."""

    async def load(self, pier: str, *, frame_id: str, progress: Any) -> dict[str, Any]:
        """Solve the Library frame *frame_id* and slew the mount to where it points; returns the same summary."""

    def frames(self) -> list[dict[str, Any]]:
        """Recent Library frames a person might choose to solve, newest first."""

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
        return await run(ctx, args, args["action"], None)

    async def load(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return await access.load(ctx.pier, frame_id=str(args["frame_id"]),
                                 progress=lambda message: ctx.progress(None, message))

    async def frames(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return {"frames": access.frames()}

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
        "solve.capture", "operate",
        (*_COMMON, Arg("action", "enum", required=False, default="nothing", choices=("nothing", "sync", "slew"),
                       description="What to do with the answer: nothing, sync the mount, or slew to the target")),
        needs_lease=True, long_running=True, available=access.why_not,
        description="Take a frame, solve it and do the Solver Action (by default nothing: the mount is not touched)"),
        capture)
    registry.register(OperationSpec(
        "solve.load", "operate", (Arg("frame_id", "str", description="A Library frame, from solve.frames"),),
        needs_lease=True, long_running=True, available=lambda pier: access.why_not(pier, mount=True, camera=False),
        description="Solve a Library frame and slew the mount to where it points"), load)
    registry.register(OperationSpec("solve.frames", "read", (), needs_lease=False,
                                    description="Recent Library frames that solve.load can solve"), frames)
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
