# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Safety stops and their acknowledgement (CSURF-220).

A remote client can read the safety stops of a Pier (``safety.events``) and acknowledge them (``safety.acknowledge``).
Until a stop is acknowledged the Pier's other operations are unavailable, naming the reason; reads, the three
emergency operations and the acknowledgement itself stay offered. Acknowledging is not resuming: it is refused while
the monitor still reports unsafe, it restarts nothing, and when the Pier is safe again the next step is a person's
(``SAFE-040``).

``register_safety_operations(registry, access)`` takes a :class:`SafetyAccess` so this module imports no guard.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry

ACKNOWLEDGE = "safety.acknowledge"


class SafetyAccess(Protocol):
    def events(self, pier: str) -> list[dict[str, Any]]: ...

    def pending(self, pier: str) -> list[dict[str, Any]]: ...

    def acknowledge(self, pier: str, who: str) -> int:
        """Acknowledge the Pier's stops; raises ``ValueError`` (with the reason) while conditions are unsafe."""


def register_safety_operations(registry: Registry, access: SafetyAccess) -> None:
    async def events(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return {"events": access.events(ctx.pier), "pending": len(access.pending(ctx.pier))}

    async def acknowledge(ctx: OperationContext, args: dict[str, Any]) -> Any:
        if not access.pending(ctx.pier):
            raise Refused("there is no safety stop to acknowledge on this Pier")
        try:
            return {"acknowledged": access.acknowledge(ctx.pier, ctx.principal)}
        except ValueError as exc:
            raise Refused(str(exc)) from exc

    registry.register(OperationSpec("safety.events", "read", (), needs_lease=False,
                                    description="The Pier's safety stops and whether each is acknowledged"), events)
    registry.register(OperationSpec(ACKNOWLEDGE, "operate", (), needs_lease=False,
                                    description="Acknowledge the Pier's safety stops; it does not resume anything"), acknowledge)

    def gate(spec: OperationSpec, pier: str) -> str | None:
        if spec.permission_class in ("read", "emergency") or spec.name == ACKNOWLEDGE:
            return None
        return "a safety stop must be acknowledged first" if access.pending(pier) else None

    registry.set_gate(gate)


class GuardSafety:
    """:class:`SafetyAccess` over the engine's ``Guard``."""

    def __init__(self, guard: Any) -> None:
        self._guard = guard

    def events(self, pier: str) -> list[dict[str, Any]]:
        return [dict(e) for e in self._guard.events if e["pier"] == pier]

    def pending(self, pier: str) -> list[dict[str, Any]]:
        return self._guard.pending(pier)

    def acknowledge(self, pier: str, who: str) -> int:
        return int(self._guard.acknowledge(pier, who))


__all__ = ["ACKNOWLEDGE", "GuardSafety", "SafetyAccess", "register_safety_operations"]
