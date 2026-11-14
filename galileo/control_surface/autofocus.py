# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Control Surface catalogue for autofocus (CSURF-340): the Focus screen's "Run autofocus" and "Cancel" buttons,
driven from a phone, tablet or browser standing at the telescope.

``focus.autofocus`` runs the Focus screen's own sweep: it moves the focuser across the Pier's saved number of points,
measures the star HFR at each, fits the V-curve, moves to the best position and confirms with an exposure. It is
long-running and reports each measured point as progress. The Pier's saved autofocus settings (step size, points,
exposure, backlash compensation, filter offsets: Options > Focus) apply exactly as for the desktop. ``focus.autofocus_cancel``
asks a run to stop after the exposure in progress; the focuser goes back to where it started and the run reports
``Cancelled``.

While it runs, and after, the live picture is the observable state key ``focus.autofocus`` (published on every change, so
a client following the event feed needs no polling):

* ``running`` and ``phase`` (``idle``, ``sweeping``, ``confirming``, ``finished``), ``message``, ``step`` of ``steps``;
* ``points``: the ``[position, hfr]`` pairs measured so far, for drawing the V-curve;
* ``best_position`` (null until a run succeeds), ``success`` (null while running), ``cancelled`` and ``failure_reason``.

A Pier with no connected camera or focuser, or one whose camera is in use by a session, a plate solve or polar alignment,
is refused with a reason before anything moves.

``register_autofocus_operations(registry, access)`` takes an :class:`AutofocusAccess` so this module imports no camera,
focuser or solver.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry, Unreachable
from galileo.exceptions import DeviceConnectionError, DeviceError, DeviceTimeoutError, SafetyError

STATE_KEY = "focus.autofocus"


class AutofocusAccess(Protocol):
    def why_not(self, pier: str) -> str | None:
        """Why autofocus cannot start on *pier* now (no camera or focuser, a session, plate solve or polar run using the
        camera, a run already in progress), or ``None``."""

    async def run(self, pier: str, *, progress: Any) -> dict[str, Any]:
        """Run one autofocus sweep; calls ``progress(message)`` for each measured point."""

    def cancel(self, pier: str) -> bool:
        """Ask the run in progress to stop; ``False`` when none is running."""

    def status(self, pier: str) -> dict[str, Any]: ...


def register_autofocus_operations(registry: Registry, access: AutofocusAccess) -> None:
    async def start(ctx: OperationContext, args: dict[str, Any]) -> Any:
        try:
            return await access.run(ctx.pier, progress=lambda message: ctx.progress(None, message))
        except (DeviceConnectionError, DeviceTimeoutError) as exc:
            raise Unreachable(str(exc) or "the device did not answer") from exc
        except (DeviceError, SafetyError) as exc:
            raise Refused(str(exc)) from exc

    async def cancel(ctx: OperationContext, args: dict[str, Any]) -> Any:
        if not access.cancel(ctx.pier):
            raise Refused("autofocus is not running on this Pier")
        return {"cancelling": True}

    registry.register(OperationSpec(
        "focus.autofocus", "operate", (), needs_lease=True, long_running=True, available=access.why_not,
        description="Run autofocus: sweep the focuser, measure the star HFR at each point, fit the V-curve, move to "
                    "the best position and confirm"), start)
    registry.register(OperationSpec("focus.autofocus_cancel", "operate", (), needs_lease=True,
                                    description="Cancel the autofocus run in progress"), cancel)


__all__ = ["STATE_KEY", "AutofocusAccess", "register_autofocus_operations"]
