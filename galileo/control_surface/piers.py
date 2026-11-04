# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Control Surface catalogue for Observatories and Piers (CSURF-100): which Piers there are and how each is doing.

A client chooses the working Pier by naming it in every request, so there is nothing to "select" on the engine;
``pier.list`` gives it the ids to name, with enough state to choose by: the devices connected, any that would not
connect, and the running session. ``register_pier_operations(registry, access)`` takes a :class:`PierAccess` so this
module imports no device service, runner or database.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Registry


class PierAccess(Protocol):
    def pier_ids(self) -> list[str]: ...

    def pier_name(self, pier: str) -> str: ...

    def observatory_name(self, pier: str) -> str: ...

    def connected(self, pier: str) -> list[str]: ...

    def problems(self, pier: str) -> list[str]: ...

    def session(self, pier: str) -> dict[str, Any] | None: ...


def pier_summary(access: PierAccess, pier: str) -> dict[str, Any]:
    return {"id": pier, "name": access.pier_name(pier), "observatory": access.observatory_name(pier),
            "connected": access.connected(pier), "problems": access.problems(pier),
            "session": access.session(pier) or {"state": "idle"}}


def register_pier_operations(registry: Registry, access: PierAccess) -> None:
    async def piers(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return {"piers": [pier_summary(access, p) for p in access.pier_ids()]}

    registry.register(OperationSpec("pier.list", "read", (), needs_lease=False,
                                    description="Every Pier this node runs, with its devices and running session"), piers)


class EnginePiers:
    """:class:`PierAccess` over the engine's device service and session access."""

    def __init__(self, devices: Any, sessions: Any) -> None:
        self._devices, self._sessions = devices, sessions

    def pier_ids(self) -> list[str]:
        return list(self._devices.pier_ids())

    def pier_name(self, pier: str) -> str:
        return str(self._devices.pier_name(pier))

    def observatory_name(self, pier: str) -> str:
        try:
            return str(self._devices.pier_record(pier).observatory.name)
        except Exception:
            return ""

    def connected(self, pier: str) -> list[str]:
        return list(self._devices.connected(pier))

    def problems(self, pier: str) -> list[str]:
        return list(self._devices.problems.get(pier, []))

    def session(self, pier: str) -> dict[str, Any] | None:
        return self._sessions.progress(pier)


__all__ = ["EnginePiers", "PierAccess", "pier_summary", "register_pier_operations"]
