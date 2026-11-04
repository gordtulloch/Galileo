# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Sky and framing, read-only (CSURF-130): find a target, see when it is up, and see how it frames on this Pier's rig.

``sky.search`` looks a name up in the bundled catalogue (offline, no Simbad); ``sky.object`` gives one object's
details and its rise, transit and set from the Pier's Observatory tonight; ``sky.framing`` works out the field of view
of the Pier's telescope and camera around a position, at a chosen rotation, and the panels of a mosaic that covers it.
Going to a target is the existing ``mount.slew``, and centring on it with a plate solve is ``solve.centre``, so a
client searches here and then hands the coordinates to those. The live planetarium view, the survey-image background
and the Telescopius and AAVSO lists stay on the desktop: they are pictures or need a key the node does not hold.

``register_sky_operations(registry, access)`` takes a :class:`SkyAccess` so this module imports no catalogue.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry
from galileo.control_surface.schema import Arg

MAX_RESULTS = 50                                # a short list a phone can show; the query narrows it


class SkyAccess(Protocol):
    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], int]:
        """Up to *limit* matching objects, and how many matched in all."""

    def detail(self, pier: str, name: str) -> dict[str, Any] | None:
        """One object (exact name or designation) with rise/transit/set for the Pier's site; ``None`` if unknown."""

    def framing(self, pier: str, *, ra_deg: float, dec_deg: float, rotation_deg: float, cols: int, rows: int,
                overlap_pct: float) -> dict[str, Any]:
        """The Pier's field of view and mosaic around a position; raises :class:`Refused` if it has no camera."""


def register_sky_operations(registry: Registry, access: SkyAccess) -> None:
    async def search(ctx: OperationContext, args: dict[str, Any]) -> Any:
        found, total = access.search(args["query"], int(args["limit"]))
        return {"query": args["query"], "objects": found, "total": total}

    async def detail(ctx: OperationContext, args: dict[str, Any]) -> Any:
        found = access.detail(ctx.pier, args["name"])
        if found is None:
            raise Refused(f"there is no catalogue object called {args['name']!r}")
        return found

    async def framing(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return access.framing(
            ctx.pier, ra_deg=float(args["ra_deg"]), dec_deg=float(args["dec_deg"]),
            rotation_deg=float(args["rotation_deg"]), cols=int(args["cols"]), rows=int(args["rows"]),
            overlap_pct=float(args["overlap_pct"]))

    registry.register(OperationSpec(
        "sky.search", "read",
        (Arg("query", "str"), Arg("limit", "int", required=False, default=20, minimum=1, maximum=MAX_RESULTS)),
        needs_lease=False, description="Find catalogue objects by name or designation"), search)
    registry.register(OperationSpec(
        "sky.object", "read", (Arg("name", "str"),), needs_lease=False,
        description="One object's details and its rise, transit and set tonight at the Pier's site"), detail)
    registry.register(OperationSpec(
        "sky.framing", "read",
        (Arg("ra_deg", "float", minimum=0, maximum=360, unit="deg"),
         Arg("dec_deg", "float", minimum=-90, maximum=90, unit="deg"),
         Arg("rotation_deg", "float", required=False, default=0.0, minimum=-360, maximum=360, unit="deg"),
         Arg("cols", "int", required=False, default=1, minimum=1, maximum=10),
         Arg("rows", "int", required=False, default=1, minimum=1, maximum=10),
         Arg("overlap_pct", "float", required=False, default=10.0, minimum=0, maximum=90, unit="%")),
        needs_lease=False,
        description="The Pier's field of view around a position, and the panels of a mosaic"), framing)


__all__ = ["MAX_RESULTS", "SkyAccess", "register_sky_operations"]
