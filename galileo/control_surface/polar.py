# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Control Surface catalogue for plate-solve polar alignment (CSURF-145): the Solve screen's polar-alignment
routine, driven from a phone, tablet or browser standing at the mount.

``polar.start`` runs the whole routine: it turns the mount to three measuring positions, solves a frame at each, and
then keeps solving while the user turns the altitude and azimuth adjusters, so the remaining error follows the knobs
live. It does not end by itself; ``polar.stop`` ends it. While it runs the operation reports each step as progress, and
the live picture is the observable state key ``polar.state`` (published on every change, so a client following the event
feed needs no polling) and the same dictionary from ``polar.status``:

* ``running`` and ``phase`` (``idle``, ``measuring``, ``adjusting``, ``finished``), ``message``, ``step`` of ``steps``;
* ``error``: ``total_arcsec``, ``altitude_arcsec`` (positive = axis too high), ``azimuth_arcsec`` (positive = move the
  axis west), ``azimuth_rotation_arcsec``, the two plain-English instructions, ``quality`` (``good``/``fair``/``poor``)
  and a ``trend`` of the last few totals so a client can show whether the knobs are helping;
* ``target_offset_arcmin``: where the pole lies relative to the axis in the latest frame (x right, y down), or null
  when the solver gives no field geometry;
* ``log``: the last lines of the workflow's own log.

The solver, image scale and site come from the Pier's saved settings exactly as for the Solve screen; a Pier whose solver
is not set up, or whose Observatory has no location, is refused with a reason before anything moves.

``register_polar_operations(registry, access)`` takes a :class:`PolarAccess` so this module imports no camera or solver.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry
from galileo.control_surface.schema import Arg

STATE_KEY = "polar.state"
QUALITY_GOOD_ARCSEC = 60.0                  # the same bands as the Solve screen's readout
QUALITY_FAIR_ARCSEC = 300.0


def quality(total_arcsec: float) -> str:
    return "good" if total_arcsec < QUALITY_GOOD_ARCSEC else "fair" if total_arcsec < QUALITY_FAIR_ARCSEC else "poor"


class PolarAccess(Protocol):
    def why_not(self, pier: str) -> str | None:
        """Why polar alignment cannot start on *pier* now (no camera or mount, a session or solve running, no site
        location, a run already in progress), or ``None``."""

    async def run(self, pier: str, *, exposure_s: float, settle_s: float, step_deg: float, direction: str,
                  refraction: bool, slew_from_zenith: bool, progress: Any) -> dict[str, Any]:
        """Measure and then adjust until :meth:`stop`; calls ``progress(message)`` for each step."""

    async def stop(self, pier: str) -> bool:
        """End the run in progress; ``False`` when none is running."""

    def status(self, pier: str) -> dict[str, Any]: ...


def register_polar_operations(registry: Registry, access: PolarAccess) -> None:
    async def start(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return await access.run(
            ctx.pier, exposure_s=float(args["exposure_s"]), settle_s=float(args["settle_s"]),
            step_deg=float(args["step_deg"]), direction=str(args["direction"]), refraction=bool(args["refraction"]),
            slew_from_zenith=bool(args["slew_from_zenith"]), progress=lambda message: ctx.progress(None, message))

    async def stop(ctx: OperationContext, args: dict[str, Any]) -> Any:
        if not await access.stop(ctx.pier):
            raise Refused("polar alignment is not running on this Pier")
        return {"stopping": True}

    async def status(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return access.status(ctx.pier)

    registry.register(OperationSpec(
        "polar.start", "operate",
        (Arg("exposure_s", "float", required=False, default=5.0, minimum=0.001, maximum=600, unit="s"),
         Arg("settle_s", "float", required=False, default=1.5, minimum=0, maximum=60, unit="s"),
         Arg("step_deg", "float", required=False, default=30.0, minimum=5, maximum=60, unit="deg",
             description="How far the mount turns in RA between the three measuring solves"),
         Arg("direction", "enum", required=False, default="east", choices=("east", "west"),
             description="Which way the RA axis turns"),
         Arg("refraction", "bool", required=False, default=True),
         Arg("slew_from_zenith", "bool", required=False, default=True,
             description="Go to the zenith and check the mount first; false measures from where it points now")),
        needs_lease=True, long_running=True, available=access.why_not,
        description="Measure the polar-alignment error with three plate solves, then keep it live while the "
                    "altitude and azimuth adjusters are turned; runs until polar.stop"), start)
    registry.register(OperationSpec("polar.stop", "operate", (), needs_lease=True,
                                    description="End the polar-alignment routine in progress"), stop)
    registry.register(OperationSpec("polar.status", "read", (), needs_lease=False,
                                    description="Whether polar alignment is running, and the live error"), status)


__all__ = [
    "QUALITY_FAIR_ARCSEC",
    "QUALITY_GOOD_ARCSEC",
    "STATE_KEY",
    "PolarAccess",
    "quality",
    "register_polar_operations",
]
