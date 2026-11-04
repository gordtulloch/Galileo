# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Control Surface catalogue for running sessions (CSURF-180): status, pause, resume and stop.

The operations call the same runner the desktop and the scheduler use, so a remote client gets the same
behaviour: stopping asks the executor to stop at the next block or frame boundary and aborts the running
device call, exactly as the Stop button does. Starting a session and listing saved ones are not here yet
(see the SDD), and neither is skipping a step, which the executor does not support.

``register_session_operations(registry, access)`` takes a :class:`SessionAccess` so this module imports no
runner, screen or adapter.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry
from galileo.control_surface.schema import Arg


class SessionRefused(Exception):
    """A session could not be started; the message says why, in words a person can act on."""


class SessionAccess(Protocol):
    """How the catalogue reaches a Pier's session run."""

    def progress(self, pier: str) -> dict[str, Any] | None:
        """The Pier's running session as plain data, or ``None`` when nothing is running."""

    def pause(self, pier: str) -> bool: ...

    def resume(self, pier: str) -> bool: ...

    def stop(self, pier: str) -> bool: ...


class SessionStarter(SessionAccess, Protocol):
    """A :class:`SessionAccess` that can also list saved templates and start one (``session.run``)."""

    def templates(self) -> list[str]: ...

    async def start(self, pier: str, template: str, target: dict[str, Any] | None = None,
                    camera_slot: str = "primary") -> None: ...


def progress_dict(name: str, state: str, progress: Any) -> dict[str, Any]:
    """A run and its latest ``SessionProgress`` as JSON-friendly data (the block as its class name)."""
    state_text = str(getattr(getattr(progress, "state", None), "value", getattr(progress, "state", None)) or state)
    block = getattr(progress, "block", None)
    return {
        "name": name,
        "state": "running" if state_text == "idle" else state_text,
        "block": type(block).__name__ if block is not None else "",
        "block_index": getattr(progress, "block_index", 0),
        "block_total": getattr(progress, "block_total", 0),
        "frames_done": getattr(progress, "frames_done", 0),
        "frames_total": getattr(progress, "frames_total", 0),
        "message": getattr(progress, "message", ""),
    }


class RunnerSessions:
    """:class:`SessionAccess` over the engine's ``SessionRunner``."""

    def __init__(self, runner: Any) -> None:
        self._runner = runner

    def progress(self, pier: str) -> dict[str, Any] | None:
        for snap in self._runner.snapshot():
            if snap.pier == pier:
                return progress_dict(snap.name, snap.state, snap.progress)
        return None

    def pause(self, pier: str) -> bool:
        return bool(self._runner.pause(pier))

    def resume(self, pier: str) -> bool:
        return bool(self._runner.resume(pier))

    def stop(self, pier: str) -> bool:
        return bool(self._runner.stop(pier))


def register_session_operations(registry: Registry, access: SessionAccess) -> None:
    def running(pier: str) -> str | None:
        return None if access.progress(pier) is not None else "no session is running on this Pier"

    def control(name: str, call: Any, description: str) -> None:
        async def handler(ctx: OperationContext, args: dict[str, Any]) -> Any:
            if not call(ctx.pier):
                raise Refused("no session is running on this Pier")
            return access.progress(ctx.pier)
        registry.register(OperationSpec(name, "operate", (), needs_lease=True, available=running,
                                        description=description), handler)

    async def status(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return access.progress(ctx.pier) or {"state": "idle"}

    registry.register(OperationSpec("session.status", "read", (), needs_lease=False,
                                    description="The running session and its progress, block by block"), status)
    control("session.pause", access.pause, "Pause the running session at the next block or frame boundary")
    control("session.resume", access.resume, "Resume a paused session")
    control("session.stop", access.stop, "Stop the running session")
    if hasattr(access, "start") and hasattr(access, "templates"):
        register_start_operations(registry, access)           # type: ignore[arg-type]


def register_start_operations(registry: Registry, access: SessionStarter) -> None:
    """``session.templates`` (read) and ``session.run`` (operate): starting a saved template with a chosen target."""
    async def templates(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return {"templates": access.templates()}

    async def run(ctx: OperationContext, args: dict[str, Any]) -> Any:
        target = None
        if args.get("target_name"):
            if args.get("ra_deg") is None or args.get("dec_deg") is None:
                raise Refused("a target needs target_name, ra_deg and dec_deg together")
            target = {"name": args["target_name"], "ra_deg": args["ra_deg"], "dec_deg": args["dec_deg"]}
        try:
            await access.start(ctx.pier, args["template"], target, args.get("camera_slot") or "primary")
        except SessionRefused as exc:
            raise Refused(str(exc)) from exc
        return access.progress(ctx.pier) or {"state": "running"}

    registry.register(OperationSpec("session.templates", "read", (), needs_lease=False,
                                    description="The saved session templates that can be run"), templates)
    registry.register(OperationSpec(
        "session.run", "operate",
        (Arg("template", "str"), Arg("target_name", "str", required=False),
         Arg("ra_deg", "float", required=False, minimum=0, maximum=360, unit="deg"),
         Arg("dec_deg", "float", required=False, minimum=-90, maximum=90, unit="deg"),
         Arg("camera_slot", "str", required=False)),
        needs_lease=True, description="Start a saved session template, with a target for its placeholder"), run)


__all__ = ["RunnerSessions", "SessionAccess", "SessionRefused", "SessionStarter", "progress_dict",
           "register_session_operations", "register_start_operations"]
