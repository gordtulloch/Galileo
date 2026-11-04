# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Control Surface catalogue for the meridian flip (CSURF-170): its state, and a flip on request.

``flip.status`` (read) gives where the flip stands (inactive, waiting for the mount to track, armed, due, flipping),
the hour angle, the pier side, the minutes to the flip limit, and the outcome of the last flip. ``flip.now`` is a
``confirm`` operation: it flips the mount across the meridian, resumes tracking and reports the outcome, and is long
running, so it answers at once with a correlation id and finishes with one event. Whether it can start is part of
availability. A flip cannot be deferred: the service has no way to postpone one, so the catalogue does not pretend to.

``register_flip_operations(registry, access)`` takes a :class:`FlipAccess` so this module imports no mount or service.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry


class FlipRefused(Exception):
    """A flip could not be done; the message says why, in words a person can act on."""


class FlipAccess(Protocol):
    def why_not(self, pier: str) -> str | None:
        """Why a flip cannot be started on *pier* now (from what is known without asking the mount), or ``None``."""

    async def state(self, pier: str) -> dict[str, Any]: ...

    async def flip(self, pier: str, progress: Any) -> dict[str, Any]:
        """Flip the mount; raises :class:`FlipRefused` when it must not, returns the outcome."""


def register_flip_operations(registry: Registry, access: FlipAccess) -> None:
    async def status(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return await access.state(ctx.pier)

    async def flip(ctx: OperationContext, args: dict[str, Any]) -> Any:
        try:
            return await access.flip(ctx.pier, lambda message: ctx.progress(None, message))
        except FlipRefused as exc:
            raise Refused(str(exc)) from exc

    registry.register(OperationSpec(
        "flip.status", "read", (), needs_lease=False,
        description="Meridian flip state, hour angle, pier side, minutes to the flip limit and the last outcome"), status)
    registry.register(OperationSpec(
        "flip.now", "confirm", (), needs_lease=True, long_running=True, available=access.why_not,
        description="Flip the mount across the meridian and resume tracking (asks for a second confirmation)"), flip)


__all__ = ["FlipAccess", "FlipRefused", "register_flip_operations"]
