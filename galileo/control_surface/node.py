# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Node health and power for the Control Surface (CSURF-310): how the computer running Galileo is doing, and
restarting or powering it off from a phone, tablet or browser.

``node.health`` (read) returns the latest reading: ``cpu_percent``, ``cpu_cores``, ``load``, ``memory_percent``,
``disk_free_gb``, ``disk_used_percent``, ``temperature_c`` (null where the computer reports none), ``uptime_s`` and
``status`` (``ok``, ``warning`` or ``critical``). The same dictionary is the observable state ``node.health``, published
by the engine every few seconds, so a client following the event feed needs no polling.

``node.restart`` and ``node.shutdown`` are class *confirm*: the gateway asks for a second, deliberate step before
either runs. Both are refused while a session is running, because ending the computer under a running session would
leave the mount tracking and the dome open; stop the session first.

``register_node_operations(registry, access)`` takes a :class:`NodeAccess` so this module imports no OS code.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry

STATE_KEY = "node.health"
HEALTH, RESTART, SHUTDOWN = "node.health", "node.restart", "node.shutdown"


class NodeAccess(Protocol):
    def health(self) -> dict[str, Any]: ...

    def busy_reason(self) -> str | None:
        """Why the computer must not be restarted or powered off now (a session is running), or ``None``."""

    def power(self, action: str) -> None:
        """Restart or power off; raises ``RuntimeError`` (with the reason) when the computer refuses."""


def register_node_operations(registry: Registry, access: NodeAccess) -> None:
    def unavailable(pier: str) -> str | None:
        return access.busy_reason()

    async def health(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return access.health()

    def power(action: str):
        async def run(ctx: OperationContext, args: dict[str, Any]) -> Any:
            reason = access.busy_reason()
            if reason:
                raise Refused(reason)
            try:
                await asyncio.to_thread(access.power, action)
            except RuntimeError as exc:
                raise Refused(str(exc)) from exc
            return {"requested": action}
        return run

    registry.register(OperationSpec(HEALTH, "read", description="CPU, memory, free disk space, temperature and uptime "
                                    "of the computer running Galileo"), health)
    registry.register(OperationSpec(RESTART, "confirm", available=unavailable,
                                    description="Restart the computer running Galileo"), power("restart"))
    registry.register(OperationSpec(SHUTDOWN, "confirm", available=unavailable,
                                    description="Power off the computer running Galileo"), power("shutdown"))


__all__ = ["HEALTH", "RESTART", "SHUTDOWN", "STATE_KEY", "NodeAccess", "register_node_operations"]
