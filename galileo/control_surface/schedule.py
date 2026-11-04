# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The scheduler's job queue, read-only (CSURF-200).

``scheduler.jobs`` lists a Pier's queued jobs in priority order with their target, progress, planned window and last
run state, and names the job that would run next. It reads the queue as the scheduler last saved it, so what a client
sees is what the Schedule screen last committed. Creating, editing, reordering and running jobs are not offered yet:
they need the engine to own the live scheduler (today only the desktop does), and a second writer on the saved queue
would corrupt it.

``register_schedule_operations(registry, access)`` takes a :class:`ScheduleAccess` so this module imports no database.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Registry


class ScheduleAccess(Protocol):
    def jobs(self, pier: str) -> list[dict[str, Any]]:
        """The Pier's saved jobs, highest priority first (lowest number)."""


def register_schedule_operations(registry: Registry, access: ScheduleAccess) -> None:
    async def jobs(ctx: OperationContext, args: dict[str, Any]) -> Any:
        found = access.jobs(ctx.pier)
        waiting = next((j["name"] for j in found if j["run_state"] == "pending" and not j["complete"]), "")
        return {"jobs": found, "next": waiting}

    registry.register(OperationSpec("scheduler.jobs", "read", (), needs_lease=False,
                                    description="The Pier's queued scheduler jobs, in priority order, and the next one"),
                      jobs)


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
