# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Observatory scheduler — multi-target, multi-night job queue (SCHED-010 … SCHED-100).

Each ``SchedulerJob`` references a target, a sequence definition, and a Pier.
The scheduler applies per-job constraints, startup conditions, and completion
conditions to decide which job runs next.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Startup conditions (SCHED-040)
# ---------------------------------------------------------------------------

class StartImmediate:
    """Start the job as soon as it is runnable."""


@dataclass
class StartAtCulmination:
    """Start when the target reaches transit (culmination)."""


@dataclass
class StartAtTime:
    """Start at a specific UTC time."""
    time_utc: str


def _startup_to_dict(condition: Any) -> dict:
    d = {"_type": type(condition).__name__}
    if isinstance(condition, StartAtTime):
        d["time_utc"] = condition.time_utc
    return d


def _startup_from_dict(d: dict) -> Any:
    name = d.get("_type", "StartImmediate")
    if name == "StartAtTime":
        return StartAtTime(time_utc=d.get("time_utc", ""))
    if name == "StartAtCulmination":
        return StartAtCulmination()
    return StartImmediate()


# ---------------------------------------------------------------------------
# Completion conditions (SCHED-050)
# ---------------------------------------------------------------------------

class RunOnce:
    """Run the job once then mark it complete."""


@dataclass
class RepeatNTimes:
    """Repeat the job *n* times in total."""
    n: int


class RepeatIndefinitely:
    """Repeat the job until manually stopped."""


def _completion_to_dict(condition: Any) -> dict:
    d = {"_type": type(condition).__name__}
    if isinstance(condition, RepeatNTimes):
        d["n"] = condition.n
    return d


def _completion_from_dict(d: dict) -> Any:
    name = d.get("_type", "RunOnce")
    if name == "RepeatNTimes":
        return RepeatNTimes(n=d.get("n", 1))
    if name == "RepeatIndefinitely":
        return RepeatIndefinitely()
    return RunOnce()


# ---------------------------------------------------------------------------
# Constraints (SCHED-030)
# ---------------------------------------------------------------------------

@dataclass
class JobConstraints:
    min_altitude_deg: float = 0.0
    min_moon_separation_deg: float = 0.0
    twilight_restriction: str = "nautical"  # civil | nautical | astronomical
    respect_horizon: bool = True


# ---------------------------------------------------------------------------
# Scheduler job
# ---------------------------------------------------------------------------

class SchedulerJob:
    """One entry in the observatory scheduler queue."""

    def __init__(
        self,
        name: str,
        sequence=None,
        pier_name: str = "",
        target_ra: float = 0.0,
        target_dec: float = 0.0,
        priority: int = 5,
    ) -> None:
        self.name = name
        self.sequence = sequence
        self.pier_name = pier_name
        self.target_ra = target_ra
        self.target_dec = target_dec
        self.priority = priority
        self.constraints = JobConstraints()
        self.startup_condition = StartImmediate()
        self.completion_condition = RunOnce()
        self.total_required: int = 0
        self._frames_captured: int = 0
        self._state = "pending"

    @property
    def frames_captured(self) -> int:
        return self._frames_captured

    @property
    def is_complete(self) -> bool:
        """Whether this job has satisfied its completion condition (SCHED-050) and
        should be reaped from the queue. Only ``RunOnce`` is evaluated against real
        progress today — ``RepeatNTimes``/``RepeatIndefinitely`` need a per-run
        counter that has no real driver yet, since nothing feeds actual capture
        progress into ``record_frames_captured`` until session-block execution
        (out of scope here — see TODO.md) exists."""
        if isinstance(self.completion_condition, RunOnce):
            return self.total_required > 0 and self._frames_captured >= self.total_required
        return False

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"SchedulerJob({self.name!r}, pier={self.pier_name!r})"


# ---------------------------------------------------------------------------

class ObservatoryScheduler:
    """Manages and executes a prioritized queue of SchedulerJobs."""

    def __init__(self, observatory=None) -> None:
        self._observatory = observatory
        self.jobs: list[SchedulerJob] = []
        self.active_job: SchedulerJob | None = None
        self._safety_monitor = None
        self._location = None
        self._persist_key: str | None = None

    # --- Queue management (SCHED-020) ------------------------------------

    def add_job(self, job: SchedulerJob) -> None:
        self.jobs.append(job)
        self._sort_jobs()
        self.save()

    def remove_job(self, job: SchedulerJob) -> None:
        self.jobs.remove(job)
        self.save()

    def move_job(self, job: SchedulerJob, new_position: int) -> None:
        self.jobs.remove(job)
        self.jobs.insert(new_position, job)
        self.save()

    def update_job(self, job: SchedulerJob, updates: dict) -> None:
        for key, value in updates.items():
            setattr(job, key, value)
        self.save()

    def _sort_jobs(self) -> None:
        self.jobs.sort(key=lambda j: j.priority)

    def get_ordered_jobs(self) -> list[SchedulerJob]:
        return sorted(self.jobs, key=lambda j: j.priority)

    def reap_completed_jobs(self) -> list[SchedulerJob]:
        """Remove every job that has completed successfully (SCHED-050) and delete
        the session it came from, rather than leaving it desecheduled-but-present —
        a completed session has nothing left to do. Returns the jobs removed."""
        done = [j for j in self.jobs if j.is_complete]
        for job in done:
            self.jobs.remove(job)
            if self.active_job is job:
                self.active_job = None
            region = job.sequence
            if region is not None and hasattr(region, "delete"):
                region.delete()
        if done:
            self.save()
        return done

    def next_job(self) -> SchedulerJob | None:
        for job in self.get_ordered_jobs():
            if job._state == "pending":
                return job
        return None

    # --- Runtime (SCHED-060, SCHED-070) ----------------------------------

    def set_safety_monitor(self, monitor) -> None:
        self._safety_monitor = monitor

    def set_location(self, location) -> None:
        self._location = location

    async def can_start_job(self, job: SchedulerJob) -> bool:
        """Return True when the job's constraints and safety allow it to start."""
        if self._safety_monitor and not self._safety_monitor.is_safe:
            return False
        return True

    async def replan(self) -> None:
        """Replan the queue using priority-based preemption (SCHED-070)."""
        for job in self.get_ordered_jobs():
            if job.priority < (self.active_job.priority if self.active_job else 999):
                if await self.can_start_job(job):
                    self.active_job = job
                    return

    # --- Progress tracking (SCHED-090) -----------------------------------

    async def record_frames_captured(self, job: SchedulerJob, count: int) -> None:
        job._frames_captured += count
        self.save()

    def get_remaining_frames(self, job: SchedulerJob) -> int:
        return max(0, job.total_required - job.frames_captured)

    # --- Altitude chart (SCHED-080) --------------------------------------

    def get_job_trajectory_chart(self, job: SchedulerJob, date: str | None = None) -> dict:
        from galileo.planning.visibility import altitude_chart
        if self._location is None:
            return {"times": [], "altitudes": [], "run_window": None}
        chart = altitude_chart(job.target_ra, job.target_dec, self._location, date)
        chart["run_window"] = None
        return chart

    # --- Persistence (SCHED-100) -------------------------------------------
    #
    # Job queue and per-job progress live in the same shared database as
    # galileo.library/galileo.history (ADR-002; SDD Section 5's Data Design
    # table) rather than a separate file — set_persistence() scopes this
    # instance to one Pier's rows in the shared ``scheduler_jobs`` table,
    # since one queue exists per Pier (SDD Section 4.9b). Persistence is
    # opt-in (disabled by default, matching every existing test that never
    # calls set_persistence): every mutator above calls save(), which is a
    # no-op until a persist key is set.

    def set_persistence(self, pier_name: str) -> None:
        self._persist_key = pier_name

    def save(self) -> None:
        if self._persist_key is None:
            return
        from galileo.library.models.scheduler import SchedulerJobRecord
        with SchedulerJobRecord._meta.database.atomic():
            SchedulerJobRecord.delete().where(SchedulerJobRecord.pier_name == self._persist_key).execute()
            for j in self.jobs:
                SchedulerJobRecord.create(
                    pier_name=self._persist_key,
                    name=j.name,
                    target_ra=j.target_ra,
                    target_dec=j.target_dec,
                    priority=j.priority,
                    frames_captured=j._frames_captured,
                    total_required=j.total_required,
                    constraints_json=json.dumps(asdict(j.constraints)),
                    startup_json=json.dumps(_startup_to_dict(j.startup_condition)),
                    completion_json=json.dumps(_completion_to_dict(j.completion_condition)),
                )

    def load(self) -> None:
        if self._persist_key is None:
            return
        from galileo.library.models.scheduler import SchedulerJobRecord
        self.jobs = []
        for rec in SchedulerJobRecord.select().where(SchedulerJobRecord.pier_name == self._persist_key):
            job = SchedulerJob(
                name=rec.name,
                pier_name=rec.pier_name,
                target_ra=rec.target_ra,
                target_dec=rec.target_dec,
                priority=rec.priority,
            )
            job._frames_captured = rec.frames_captured
            job.total_required = rec.total_required
            job.constraints = JobConstraints(**json.loads(rec.constraints_json))
            job.startup_condition = _startup_from_dict(json.loads(rec.startup_json))
            job.completion_condition = _completion_from_dict(json.loads(rec.completion_json))
            self.jobs.append(job)
        self._sort_jobs()
