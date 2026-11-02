# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The three emergency operations (CSURF-300).

``system.stop_everything``, ``mount.park`` and ``dome.close`` are registered as class ``emergency``:
no lease, no second confirmation step (the client's deliberate gesture is the confirmation), highest
priority, always audited. They call the same services the desktop's own emergency actions call; this
module only declares them, so core can register them once the services hand over their callables.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from galileo.control_surface.holds import HoldManager
from galileo.control_surface.registry import OperationContext, OperationSpec, Registry

EMERGENCY_OPERATIONS = ("system.stop_everything", "mount.emergency_park", "dome.emergency_close")

PierAction = Callable[[str], Any]


def register_emergency(
    registry: Registry, *, stop_everything: PierAction, park: PierAction, close_dome: PierAction,
    holds: HoldManager | None = None,
    available: dict[str, Callable[[str], str | None]] | None = None,
) -> None:
    """Declare the emergency operations. ``stop_everything`` also cancels every held motion."""
    avail = available or {}

    def spec(name: str, description: str) -> OperationSpec:
        return OperationSpec(name, "emergency", description=description,
                             available=avail.get(name, lambda pier: None))

    def do_stop(ctx: OperationContext, args: dict[str, Any]) -> Any:
        if holds is not None:
            holds.cancel_pier(ctx.pier, "emergency stop")
        return stop_everything(ctx.pier)

    registry.register(spec(EMERGENCY_OPERATIONS[0], "Stop the session, all motion and exposures"), do_stop)
    registry.register(spec(EMERGENCY_OPERATIONS[1], "Park the mount now"), lambda ctx, a: park(ctx.pier))
    registry.register(spec(EMERGENCY_OPERATIONS[2], "Close the dome or roof now"),
                      lambda ctx, a: close_dome(ctx.pier))


__all__ = ["EMERGENCY_OPERATIONS", "register_emergency"]
