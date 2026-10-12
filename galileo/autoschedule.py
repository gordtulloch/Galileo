# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Autoschedule (SCHED-160): place every unpositioned timeline entry on a night.

Pure domain logic with no Qt. :func:`plan_autoschedule` is a *dry run*: it
returns an :class:`AutoschedulePlan` (placements plus the jobs it could not
place and why) without touching the scheduler, so the Schedule screen can show a
preview and let the user confirm; :func:`apply_plan` then writes the placements.

Jobs are placed in priority order (lower number first), each in the earliest free
slot of its duration where, for the whole slot, the Sun is below the job's twilight
limit, the target is above its minimum altitude and above the horizon profile
(when it respects the horizon), and the Moon is at least its minimum separation
away. Slots that overlap another job on the same Pier (the ``overlapping_jobs()``
rule: same Pier, intersecting window) are excluded, including jobs placed earlier
in the same run. Already-positioned jobs are never moved, and nothing here
preempts or reorders a running queue: continuous replanning stays the separate
``SCHED-070`` concern.

The sky is reached through a small :class:`SkyModel` interface so the algorithm is
testable without astropy; :class:`AstropySkyModel` is the real implementation.
"""

from __future__ import annotations

import datetime
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Protocol
from collections.abc import Sequence

from galileo.scheduler import (
    ObservatoryScheduler,
    SchedulerJob,
    StartAtCulmination,
    StartAtTime,
    _parse_utc,
)

logger = logging.getLogger(__name__)

STEP_MINUTES = 10

# Sun altitude (degrees) the Sun must be at or below, per JobConstraints.twilight_restriction.
TWILIGHT_SUN_LIMIT_DEG = {"civil": -6.0, "nautical": -12.0, "astronomical": -18.0}


class SkyModel(Protocol):
    """Sky geometry sampled at *times* (aware UTC datetimes)."""

    def sun_altitudes(self, times: Sequence[datetime.datetime]) -> list[float] | None: ...

    def target_altaz(
        self, ra_deg: float, dec_deg: float, times: Sequence[datetime.datetime],
    ) -> tuple[list[float], list[float]] | None:
        """(altitudes, azimuths) in degrees."""

    def moon_separations(
        self, ra_deg: float, dec_deg: float, times: Sequence[datetime.datetime],
    ) -> list[float] | None: ...

    def horizon_altitudes(self, azimuths: Sequence[float]) -> list[float]:
        """Obstruction altitude at each azimuth (zeros when no horizon profile)."""


class AstropySkyModel:
    """:class:`SkyModel` backed by astropy for an ``ObservingLocation``."""

    def __init__(self, location: Any) -> None:
        self.location = location

    def _frame_times(self, times):
        from astropy.time import Time
        return Time([t.astimezone(datetime.UTC).replace(tzinfo=None) for t in times], scale="utc")

    def _earth(self):
        import astropy.units as u
        from astropy.coordinates import EarthLocation
        loc = self.location
        return EarthLocation(
            lat=loc.latitude * u.deg, lon=loc.longitude * u.deg,
            height=(getattr(loc, "elevation_m", 0.0) or 0.0) * u.m)

    def sun_altitudes(self, times):
        try:
            from astropy.coordinates import AltAz, get_sun
            t = self._frame_times(times)
            return [float(a) for a in get_sun(t).transform_to(AltAz(obstime=t, location=self._earth())).alt.deg]
        except Exception:
            logger.debug("Autoschedule: Sun altitude unavailable", exc_info=True)
            return None

    def target_altaz(self, ra_deg, dec_deg, times):
        try:
            import astropy.units as u
            from astropy.coordinates import AltAz, SkyCoord
            t = self._frame_times(times)
            altaz = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg).transform_to(
                AltAz(obstime=t, location=self._earth()))
            return [float(a) for a in altaz.alt.deg], [float(a) for a in altaz.az.deg]
        except Exception:
            logger.debug("Autoschedule: target altitude unavailable", exc_info=True)
            return None

    def moon_separations(self, ra_deg, dec_deg, times):
        try:
            from astropy.coordinates import get_body
            from galileo.planning.visibility import moon_separation_deg
            t = self._frame_times(times)
            moon = get_body("moon", t, self._earth())
            return [moon_separation_deg(ra_deg, dec_deg, float(r), float(d))
                    for r, d in zip(moon.ra.deg, moon.dec.deg, strict=True)]
        except Exception:
            logger.debug("Autoschedule: Moon separation unavailable", exc_info=True)
            return None

    def horizon_altitudes(self, azimuths):
        horizon = getattr(self.location, "_horizon", None)
        if horizon is None or not getattr(horizon, "points", None):
            return [0.0] * len(azimuths)
        return [float(v) for v in horizon.min_altitudes(list(azimuths))]


@dataclass
class Placement:
    job: SchedulerJob
    start: datetime.datetime
    end: datetime.datetime


@dataclass
class AutoschedulePlan:
    placements: list[Placement] = field(default_factory=list)
    unplaced: list[tuple[SchedulerJob, str]] = field(default_factory=list)

    def summary(self, tz: datetime.tzinfo | None = None) -> str:
        """Human-readable preview, times in *tz* (system local zone by default)."""
        lines = []
        for p in self.placements:
            s, e = p.start.astimezone(tz), p.end.astimezone(tz)
            lines.append(f"{p.job.name}: {s:%H:%M} - {e:%H:%M}")
        for job, reason in self.unplaced:
            lines.append(f"{job.name}: not placed ({reason})")
        return "\n".join(lines)


def is_unpositioned_session(job: SchedulerJob) -> bool:
    """A job Autoschedule may place: a session entry with no start, still waiting to run."""
    return job.kind == "session" and not job.scheduled_start_utc and job.run_state == "pending"


def _duration(job: SchedulerJob) -> datetime.timedelta:
    return datetime.timedelta(minutes=job.duration_minutes or SchedulerJob.DEFAULT_DURATION_MINUTES)


def plan_autoschedule(
    scheduler: ObservatoryScheduler,
    sky: SkyModel | None,
    night_start: datetime.datetime,
    night_end: datetime.datetime,
    *,
    step_minutes: int = STEP_MINUTES,
) -> AutoschedulePlan:
    """Dry-run placement of the scheduler's unpositioned session jobs within
    [*night_start*, *night_end*] (aware datetimes). Does not modify *scheduler*."""
    plan = AutoschedulePlan()
    candidates = [j for j in scheduler.get_ordered_jobs() if is_unpositioned_session(j)]
    if not candidates:
        return plan
    if sky is None:
        plan.unplaced = [(j, "no observatory location is configured") for j in candidates]
        return plan

    step = datetime.timedelta(minutes=step_minutes)
    n = int((night_end - night_start) / step) + 1
    times = [night_start + i * step for i in range(max(n, 0))]
    if not times:
        plan.unplaced = [(j, "the night window is empty") for j in candidates]
        return plan
    sun = sky.sun_altitudes(times)
    if sun is None:
        plan.unplaced = [(j, "the Sun's position could not be computed") for j in candidates]
        return plan

    # Occupied intervals per Pier: every positioned job plus placements made this run,
    # which is exactly the overlapping_jobs() same-Pier intersection rule.
    busy: dict[str, list[tuple[datetime.datetime, datetime.datetime]]] = {}
    for other in scheduler.jobs:
        window = other.effective_window()
        if window is not None:
            busy.setdefault(other.pier_name, []).append(window)

    for job in candidates:
        slot = _find_slot(job, sky, times, sun, step, busy.get(job.pier_name, []))
        if isinstance(slot, str):
            plan.unplaced.append((job, slot))
            continue
        start = slot
        end = start + _duration(job)
        plan.placements.append(Placement(job, start, end))
        busy.setdefault(job.pier_name, []).append((start, end))
    return plan


def _find_slot(job, sky, times, sun, step, busy) -> datetime.datetime | str:
    """Start of the best free slot for *job*, or a reason string."""
    c = job.constraints
    sun_limit = TWILIGHT_SUN_LIMIT_DEG.get(c.twilight_restriction, -12.0)
    altaz = sky.target_altaz(job.target_ra, job.target_dec, times)
    if altaz is None:
        return "the target's position could not be computed"
    alts, azs = altaz
    horizon = sky.horizon_altitudes(azs) if c.respect_horizon else [0.0] * len(times)
    moon = sky.moon_separations(job.target_ra, job.target_dec, times) if c.min_moon_separation_deg > 0 else None
    if c.min_moon_separation_deg > 0 and moon is None:
        return "the Moon's position could not be computed"

    not_before = None
    if isinstance(job.startup_condition, StartAtTime) and job.startup_condition.time_utc:
        not_before = _parse_utc(job.startup_condition.time_utc)

    ok = []
    for i, t in enumerate(times):
        good = (sun[i] <= sun_limit and alts[i] >= max(c.min_altitude_deg, horizon[i])
                and (moon is None or moon[i] >= c.min_moon_separation_deg)
                and (not_before is None or t >= not_before))
        ok.append(good)
    if not any(ok):
        return "no time tonight satisfies its altitude, Moon, twilight and horizon constraints"

    need = max(1, math.ceil(_duration(job) / step))
    slots = []
    for i in range(len(times) - need + 1):
        if not all(ok[i:i + need]):
            continue
        start = times[i]
        end = start + _duration(job)
        if any(start < b_end and b_start < end for b_start, b_end in busy):
            continue
        slots.append(i)
    if not slots:
        return "no free slot long enough where its constraints hold"

    if isinstance(job.startup_condition, StartAtCulmination):
        peak = max(range(len(alts)), key=lambda k: alts[k])
        best = min(slots, key=lambda i: abs((i + need / 2) - peak))
    else:
        best = slots[0]
    return times[best]


def apply_plan(scheduler: ObservatoryScheduler, plan: AutoschedulePlan) -> int:
    """Write *plan*'s placements onto their jobs (start, end, duration) and save.
    Returns the number placed."""
    for p in plan.placements:
        p.job.scheduled_start_utc = p.start.astimezone(datetime.UTC).isoformat(timespec="seconds")
        p.job.scheduled_end_utc = p.end.astimezone(datetime.UTC).isoformat(timespec="seconds")
        p.job.duration_minutes = (p.end - p.start).total_seconds() / 60.0
    if plan.placements:
        scheduler.save()
    return len(plan.placements)
