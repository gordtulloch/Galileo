# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Held mount jog for the Control Surface (CSURF-330): move the mount north, south, east or west only while a button
is held, with the deadman of CSURF-400 to CSURF-420.

This is the Imaging and Mount screens' hold-to-move pad (``galileo.ui.app_window._hold_to_move``) as a held operation:
``mount.move_axis(axis, signed rate)`` on press, the same call with rate 0 on release. The device layer's own refusals
(a parked mount) are returned as typed refusals before any hold exists, so a refused press never leaves a hold to keep
alive. Whatever ends the hold (a missing beat, the holder letting go, the lease changing hands, a safety stop) halts
the axis through the hold's ``stop``.

``register_mount_hold_operations(registry, access, holds)`` takes the same :class:`~galileo.control_surface.catalogue.DeviceAccess`
the rest of the device catalogue does, so this module imports no adapter, screen or global.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from galileo.control_surface.catalogue import DeviceAccess, _device
from galileo.control_surface.holds import HoldError, HoldManager
from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry
from galileo.control_surface.schema import Arg
from galileo.mount_limits import JOG_RATE_LEVELS

logger = logging.getLogger(__name__)

DIRECTIONS = ("north", "south", "east", "west")

#: The speed of a held jog: level 7 of the Mount page's nine, 0.2 degrees a second, which is what the Imaging screen's
#: nudge pad starts on. An INDI mount snaps it to the nearest slower rate the driver offers.
DEFAULT_JOG_RATE_DEG_S = JOG_RATE_LEVELS[7]


def axis_command(direction: str, rate: float = DEFAULT_JOG_RATE_DEG_S) -> tuple[int, float]:
    """The ``(axis, signed rate)`` for ``move_axis`` that moves the mount *direction* at *rate* degrees a second.
    North and south drive the secondary (Dec) axis, east and west the primary (RA) axis; north and east are positive.
    The same mapping as the desktop pad's ``galileo.ui.imaging.nudge_command``, without the pad's UI-side reversal:
    a mount whose driver reverses motion applies it itself, and a Pier with no screen has no checkbox to ask."""
    name = direction.lower()
    if name not in DIRECTIONS:
        raise ValueError(f"unknown direction {direction!r}")
    axis = 1 if name in ("north", "south") else 0
    sign = 1.0 if name in ("north", "east") else -1.0
    return axis, sign * abs(rate)


async def start_mount_hold(holds: HoldManager, mount: Any, pier: str, direction: str, holder: str, *,
                           rate: float = DEFAULT_JOG_RATE_DEG_S, origin: str = "") -> str:
    """Start the jog and register the hold that ends it; returns the hold id the client keeps beating.

    The mount is asked to move first: a parked mount, or one with no jog (an adapter without ``move_axis``), is refused
    here with the reason, and no hold is created."""
    move_axis = getattr(mount, "move_axis", None)
    if not callable(move_axis):
        raise Refused("this mount's driver has no manual motion, so it cannot be jogged from here")
    axis, signed = axis_command(direction, rate)
    loop = asyncio.get_running_loop()
    tasks: set[asyncio.Task] = set()

    def halt() -> None:
        def spawn() -> None:
            async def run() -> None:
                try:
                    await move_axis(axis, 0.0)
                except Exception:
                    logger.exception("Pier %s: could not stop the held jog", pier)
            task = loop.create_task(run())
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        loop.call_soon_threadsafe(spawn)

    try:
        hold_id = holds.start(pier, holder, halt, origin or "mount")
    except HoldError as exc:
        raise Refused(str(exc)) from exc
    try:
        await move_axis(axis, signed)
    except BaseException:
        holds.stop(hold_id, holder, "move refused")       # nothing moved, but stopping an axis is always harmless
        raise
    return hold_id


def register_mount_hold_operations(registry: Registry, access: DeviceAccess, holds: HoldManager) -> None:
    def available(pier: str) -> str | None:
        mount = access.controller(pier, "mount")
        if mount is None:
            return "this Pier has no mount"
        if hasattr(mount, "is_connected") and not mount.is_connected:
            return "the mount is not connected"
        return None

    async def start(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return await start_mount_hold(holds, access.controller(ctx.pier, "mount"), ctx.pier, args["direction"],
                                      ctx.principal, origin="control_surface")

    registry.register(OperationSpec(
        "mount.hold_start", "operate", (Arg("direction", "enum", choices=DIRECTIONS),), needs_lease=True,
        available=available, description="Move the mount while held; keep it alive with mount.hold_beat"), _device(start))
    registry.register(OperationSpec(
        "mount.hold_beat", "operate", (Arg("hold_id", "str"),), needs_lease=False, available=available,
        description="Keep a held mount move going"), _device(lambda c, a: holds.beat(a["hold_id"], c.principal)))
    registry.register(OperationSpec(
        "mount.hold_stop", "operate", (Arg("hold_id", "str"),), needs_lease=False, available=available,
        description="End a held mount move"), _device(lambda c, a: holds.stop(a["hold_id"], c.principal, "stopped")))


__all__ = ["DEFAULT_JOG_RATE_DEG_S", "DIRECTIONS", "axis_command", "register_mount_hold_operations", "start_mount_hold"]
