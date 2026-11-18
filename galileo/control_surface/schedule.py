# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The scheduler's job queue and the saved sessions a client can run (CSURF-186, CSURF-200, CSURF-205).

``scheduler.jobs`` lists a Pier's queued jobs in priority order with their target, progress, planned window and last
run state, and names the job that would run next. It reads the queue as the scheduler last saved it, so what a client
sees is what the Schedule screen last committed.

The live queue and the session runs belong to the desktop application, and a second writer on the saved queue would
corrupt it, so the engine never edits the queue itself. A desktop that hosts the engine registers a
:class:`ScheduleOwner`; everything that changes the queue or starts a saved session goes through it (``session.saved``,
``session.start_check``, ``session.run_saved``, ``scheduler.remove``, ``.reorder``, ``.pause``, ``.resume``,
``.stop``), and each is unavailable, with the reason, when no desktop owns the queue. With an owner, ``scheduler.jobs``
lists the live queue, including the running session and whether it is paused.

``register_schedule_operations(registry, access)`` takes a :class:`ScheduleAccess` so this module imports no database.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

import asyncio
import logging

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry
from galileo.control_surface.schema import Arg

logger = logging.getLogger(__name__)


NO_OWNER = "the Schedule belongs to the desktop application, which is not available"


class ScheduleAccess(Protocol):
    def jobs(self, pier: str) -> list[dict[str, Any]]:
        """The Pier's saved jobs, highest priority first (lowest number)."""


class ScheduleOwner(Protocol):
    """What the desktop that owns the live queue offers the engine. Every method may block (the desktop runs it on its
    own UI thread), so the engine calls them off its event loop, and raises :class:`Refused` for a rule it enforces."""

    def jobs(self, pier: str) -> list[dict[str, Any]]:
        """The live queue, highest priority first, with the running session (queued or not) first and ``running`` and
        ``paused`` on every entry."""

    def saved(self, pier: str) -> list[dict[str, Any]]:
        """The Pier's saved sessions (never templates): ``name``, ``blocks``, ``target``."""

    def check(self, pier: str, name: str) -> dict[str, Any]:
        """``{"running": name or "", "upcoming": [job names], "reason": why not or ""}`` for starting *name* now."""

    def run_saved(self, pier: str, name: str, preempt: bool) -> dict[str, Any]: ...

    def remove(self, pier: str, name: str) -> None: ...

    def reorder(self, pier: str, name: str, position: int) -> None: ...

    def pause(self, pier: str) -> None: ...

    def resume(self, pier: str) -> None: ...

    def stop(self, pier: str) -> None: ...


class ScheduleControl:
    """:class:`ScheduleAccess` that reads the desktop's live queue while one owns it and the stored queue otherwise, and
    holds the owner the operations below call."""

    def __init__(self, stored: ScheduleAccess) -> None:
        self._stored = stored
        self.owner: ScheduleOwner | None = None

    def set_owner(self, owner: ScheduleOwner | None) -> None:
        self.owner = owner

    def why_not(self, pier: str) -> str | None:
        return None if self.owner is not None else NO_OWNER

    def jobs(self, pier: str) -> list[dict[str, Any]]:
        if self.owner is not None:
            try:
                return self.owner.jobs(pier)
            except Exception:
                logger.exception("The desktop could not list its job queue; reading the stored queue")
        return [{**j, "running": False, "paused": False} for j in self._stored.jobs(pier)]


def register_schedule_operations(registry: Registry, access: ScheduleAccess) -> None:
    async def jobs(ctx: OperationContext, args: dict[str, Any]) -> Any:
        found = access.jobs(ctx.pier)
        waiting = next((j["name"] for j in found if j.get("run_state") == "pending" and not j.get("complete")), "")
        return {"jobs": found, "next": waiting}

    registry.register(OperationSpec("scheduler.jobs", "read", (), needs_lease=False,
                                    description="The Pier's queued scheduler jobs, in priority order, and the next one"),
                      jobs)


def register_schedule_control_operations(registry: Registry, control: ScheduleControl) -> None:
    """The operations that need the desktop's live queue (CSURF-186, CSURF-205)."""

    async def owner_call(method: str, *args: Any) -> Any:
        owner = control.owner
        if owner is None:
            raise Refused(NO_OWNER)
        return await asyncio.to_thread(getattr(owner, method), *args)

    async def saved(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return {"sessions": await owner_call("saved", ctx.pier)}

    async def start_check(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return await owner_call("check", ctx.pier, args["name"])

    async def run_saved(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return await owner_call("run_saved", ctx.pier, args["name"], bool(args.get("preempt")))

    async def remove(ctx: OperationContext, args: dict[str, Any]) -> Any:
        await owner_call("remove", ctx.pier, args["name"])
        return {"removed": args["name"]}

    async def reorder(ctx: OperationContext, args: dict[str, Any]) -> Any:
        await owner_call("reorder", ctx.pier, args["name"], int(args["position"]))
        return {"moved": args["name"], "position": int(args["position"])}

    def simple(method: str, done: str):
        async def handler(ctx: OperationContext, args: dict[str, Any]) -> Any:
            await owner_call(method, ctx.pier)
            return {done: True}
        return handler

    why = control.why_not
    registry.register(OperationSpec("session.saved", "read", (), needs_lease=False, available=why,
                                    description="The Pier's saved sessions that can be run (never templates)"), saved)
    registry.register(OperationSpec(
        "session.start_check", "read", (Arg("name", "str"),), needs_lease=False, available=why,
        description="Whether a saved session can be started now: the job running, or the jobs still to come, "
                    "on the Pier's schedule"), start_check)
    registry.register(OperationSpec(
        "session.run_saved", "operate", (Arg("name", "str"), Arg("preempt", "bool", required=False, default=False)),
        needs_lease=True, available=why,
        description="Start a saved session now, as Run on the desktop's Sessions screen does. Refused while a job is "
                    "running, and while a job is still to come unless preempt is true"), run_saved)
    registry.register(OperationSpec("scheduler.remove", "operate", (Arg("name", "str"),), needs_lease=True, available=why,
                                    description="Take a queued job off the schedule (not the running one)"), remove)
    registry.register(OperationSpec(
        "scheduler.reorder", "operate", (Arg("name", "str"), Arg("position", "int", minimum=0)), needs_lease=True,
        available=why, description="Move a queued job to a place in the queue, 0 first (not the running one)"), reorder)
    registry.register(OperationSpec("scheduler.pause", "operate", (), needs_lease=True, available=why,
                                    description="Pause the running job"), simple("pause", "paused"))
    registry.register(OperationSpec("scheduler.resume", "operate", (), needs_lease=True, available=why,
                                    description="Resume the paused job"), simple("resume", "resumed"))
    registry.register(OperationSpec("scheduler.stop", "operate", (), needs_lease=True, available=why,
                                    description="Stop the running job"), simple("stop", "stopping"))


class StoredSchedule:
    """:class:`ScheduleAccess` over the saved ``SchedulerJobRecord`` rows. *pier_name* maps a Pier id to the name the
    rows are filed under."""

    def __init__(self, pier_name: Callable[[str], str]) -> None:
        self._pier_name = pier_name

    def jobs(self, pier: str) -> list[dict[str, Any]]:
        from galileo.library.models.scheduler import SchedulerJobRecord
        rows = (SchedulerJobRecord.select().where(SchedulerJobRecord.pier_name == self._pier_name(pier))
                .order_by(SchedulerJobRecord.priority, SchedulerJobRecord.id))
        out = []
        for r in rows:
            out.append({
                "name": r.name, "kind": r.kind, "priority": r.priority, "target_ra": r.target_ra,
                "target_dec": r.target_dec, "frames_captured": r.frames_captured, "total_required": r.total_required,
                "complete": bool(r.total_required) and r.frames_captured >= r.total_required,
                "run_state": r.run_state, "start": r.scheduled_start_utc, "end": r.scheduled_end_utc,
                "minutes": r.duration_minutes, "operation": r.pier_op_kind, "log": _log(r.run_log_json)[-20:]})
        return out


def _log(text: str) -> list[str]:
    try:
        value = json.loads(text)
    except ValueError:
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


__all__ = ["ScheduleAccess", "StoredSchedule", "register_schedule_operations"]
