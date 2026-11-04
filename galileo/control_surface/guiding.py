# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Control Surface catalogue for guiding (CSURF-160): connect to PHD2, guide, stop, dither, recalibrate, and read
the error trace and the guide-star cut-out.

Commands are the Guider screen's own: each is *requested* of PHD2 and answered once PHD2 has accepted it, not once
guiding has settled, because settling can take minutes. ``guiding.status`` reports the progress (state, whether it is
settling, the RMS error and the recent samples), and the same values are published as observable state so a client
that follows the event feed sees them change. Every command is refused with PHD2's own reason if PHD2 rejects it, and
none is offered until the Pier has a PHD2 guider saved and connected.

``register_guiding_operations(registry, access)`` takes a :class:`GuidingAccess` so this module imports no guider.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Registry
from galileo.control_surface.schema import Arg


class GuidingAccess(Protocol):
    def why_not_connect(self, pier: str) -> str | None:
        """Why Galileo cannot connect to this Pier's PHD2 now (none saved, already connected), or ``None``."""

    def why_not_command(self, pier: str) -> str | None:
        """Why a guiding command cannot be sent now (not connected to PHD2), or ``None``."""

    async def connect(self, pier: str) -> dict[str, Any]: ...

    async def disconnect(self, pier: str) -> None: ...

    async def command(self, pier: str, name: str, **kwargs: Any) -> None:
        """Send ``guide`` (with ``recalibrate``), ``stop``, ``dither`` or ``find_star``; ``Refused`` if PHD2 rejects."""

    def status(self, pier: str) -> dict[str, Any]: ...

    def star(self, pier: str) -> dict[str, Any] | None: ...


def register_guiding_operations(registry: Registry, access: GuidingAccess) -> None:
    async def status(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return access.status(ctx.pier)

    async def star(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return access.star(ctx.pier) or {"available": False}

    async def connect(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return await access.connect(ctx.pier)

    async def disconnect(ctx: OperationContext, args: dict[str, Any]) -> Any:
        await access.disconnect(ctx.pier)
        return {"connected": False}

    def sender(name: str, requested: str, **fixed: Any):
        async def send(ctx: OperationContext, args: dict[str, Any]) -> Any:
            await access.command(ctx.pier, name, **{**args, **fixed})
            return {requested: True}
        return send

    def commands_available(pier: str) -> str | None:
        return access.why_not_command(pier)

    registry.register(OperationSpec("guiding.status", "read", (), needs_lease=False,
                                    description="PHD2 connection, guiding state, RMS error and the recent error trace"),
                      status)
    registry.register(OperationSpec("guiding.star", "read", (), needs_lease=False,
                                    description="The guide star's cut-out image and position"), star)
    registry.register(OperationSpec("guiding.connect", "operate", (), needs_lease=True,
                                    available=access.why_not_connect,
                                    description="Connect to the Pier's saved PHD2"), connect)
    registry.register(OperationSpec("guiding.disconnect", "operate", (), needs_lease=True,
                                    description="Disconnect from PHD2"), disconnect)
    registry.register(OperationSpec("guiding.start", "operate", (Arg("recalibrate", "bool", required=False, default=False),),
                                    needs_lease=True, available=commands_available,
                                    description="Start guiding; PHD2 settles in its own time (watch guiding.status)"),
                      sender("guide", "requested"))
    registry.register(OperationSpec("guiding.recalibrate", "operate", (), needs_lease=True,
                                    available=commands_available,
                                    description="Calibrate again, then guide"), sender("guide", "requested", recalibrate=True))
    registry.register(OperationSpec("guiding.stop", "operate", (), needs_lease=True, available=commands_available,
                                    description="Stop guiding and looping"), sender("stop", "stopping"))
    registry.register(OperationSpec("guiding.dither", "operate", (), needs_lease=True, available=commands_available,
                                    description="Dither by the Options > Guiding amount and settle"),
                      sender("dither", "requested"))
    registry.register(OperationSpec("guiding.find_star", "operate", (), needs_lease=True,
                                    available=commands_available,
                                    description="Ask PHD2 to choose a guide star"), sender("find_star", "requested"))


__all__ = ["GuidingAccess", "register_guiding_operations"]
