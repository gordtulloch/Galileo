# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Observatory scheduler — multi-target, multi-night job queue (SCHED-010 … SCHED-100).

Each ``SchedulerJob`` references a target, a sequence definition, and a Pier.
The scheduler applies per-job constraints, startup conditions, and completion
conditions to decide which job runs next.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Startup conditions (SCHED-040)
# ---------------------------------------------------------------------------

class StartImmediate:
    """Start the job as soon as it is runnable."""
    pass


@dataclass
class StartAtCulmination:
    """Start when the target reaches transit (culmination)."""
    pass


@dataclass
class StartAtTime:
    """Start at a specific UTC time."""
    time_utc: str


# ---------------------------------------------------------------------------
# Completion conditions (SCHED-050)
# ---------------------------------------------------------------------------

class RunOnce:
    """Run the job once then mark it complete."""
    pass


@dataclass
class RepeatNTimes:
    """Repeat the job *n* times in total."""
    n: int


class RepeatIndefinitely:
    """Repeat the job until manually stopped."""
    pass


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
        self._persistence_path: Path | None = None
        self._progress_store: Path | None = None

    # --- Queue management (SCHED-020) ------------------------------------

    def add_job(self, job: SchedulerJob) -> None:
        self.jobs.append(job)
        self._sort_jobs()

    def remove_job(self, job: SchedulerJob) -> None:
        self.jobs.remove(job)

    def move_job(self, job: SchedulerJob, new_position: int) -> None:
        self.jobs.remove(job)
        self.jobs.insert(new_position, job)

    def update_job(self, job: SchedulerJob, updates: dict) -> None:
        for key, value in updates.items():
            setattr(job, key, value)

    def _sort_jobs(self) -> None:
        self.jobs.sort(key=lambda j: j.priority)

    def get_ordered_jobs(self) -> list[SchedulerJob]:
        return list(sorted(self.jobs, key=lambda j: j.priority))

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

    def set_progress_store(self, path: "Path | str") -> None:
        self._progress_store = Path(path)
        self._progress_store.parent.mkdir(parents=True, exist_ok=True)

    async def record_frames_captured(self, job: SchedulerJob, count: int) -> None:
        job._frames_captured += count
        self._flush_progress()

    def get_remaining_frames(self, job: SchedulerJob) -> int:
        return max(0, job.total_required - job.frames_captured)

    def _flush_progress(self) -> None:
        if self._progress_store is None:
            return
        data = [
            {"name": j.name, "captured": j._frames_captured, "total": j.total_required}
            for j in self.jobs
        ]
        self._progress_store.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # --- Altitude chart (SCHED-080) --------------------------------------

    def get_job_trajectory_chart(self, job: SchedulerJob, date: str | None = None) -> dict:
        from galileo.planning.visibility import altitude_chart
        if self._location is None:
            return {"times": [], "altitudes": [], "run_window": None}
        chart = altitude_chart(job.target_ra, job.target_dec, self._location, date)
        chart["run_window"] = None
        return chart

    # --- Persistence (SCHED-100) -----------------------------------------

    def set_persistence(self, path: "Path | str") -> None:
        self._persistence_path = Path(path)
        self._persistence_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        if self._persistence_path is None:
            return
        data = [
            {
                "name": j.name,
                "pier_name": j.pier_name,
                "target_ra": j.target_ra,
                "target_dec": j.target_dec,
                "priority": j.priority,
                "frames_captured": j._frames_captured,
                "total_required": j.total_required,
            }
            for j in self.jobs
        ]
        self._persistence_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> None:
        if self._persistence_path is None or not self._persistence_path.exists():
            return
        data = json.loads(self._persistence_path.read_text("utf-8"))
        self.jobs = []
        for d in data:
            job = SchedulerJob(
                name=d["name"],
                pier_name=d.get("pier_name", ""),
                target_ra=d.get("target_ra", 0.0),
                target_dec=d.get("target_dec", 0.0),
                priority=d.get("priority", 5),
            )
            job._frames_captured = d.get("frames_captured", 0)
            job.total_required = d.get("total_required", 0)
            self.jobs.append(job)
