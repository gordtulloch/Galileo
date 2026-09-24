# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Persisted scheduler job queue (SCHED-100).

One row per queued ``galileo.scheduler.SchedulerJob``, scoped to its owning Pier
by ``pier_name`` (a plain string, not a foreign key — the scheduler stays
unaware of ``galileo.observatory``'s Pier records, consistent with SDD 4.9b).
Constraints and startup/completion conditions are stored as small JSON blobs
rather than their own columns, since they're closed, per-job variant shapes
``galileo.scheduler`` already (de)serializes to/from dicts.
"""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class SchedulerJobRecord(BaseModel):
    """One saved scheduler job (SCHED-100)."""

    pier_name = pw.TextField(default="")
    name = pw.TextField()
    target_ra = pw.FloatField(default=0.0)
    target_dec = pw.FloatField(default=0.0)
    priority = pw.IntegerField(default=5)
    frames_captured = pw.IntegerField(default=0)
    total_required = pw.IntegerField(default=0)
    constraints_json = pw.TextField(default="{}")
    startup_json = pw.TextField(default="{}")
    completion_json = pw.TextField(default="{}")

    class Meta:
        table_name = "scheduler_jobs"
