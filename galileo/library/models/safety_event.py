# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The record of protective stops and their acknowledgement (SAFE-170). Node-local: it describes what this computer
did to the equipment it holds."""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class SafetyEventRecord(BaseModel):
    scope = pw.TextField(default="")          # the Observatory it happened to
    reason = pw.TextField(default="")
    at = pw.FloatField(default=0.0)
    outcome = pw.TextField(default="")        # "secured" or "not_secured"
    problems = pw.TextField(default="")
    acknowledged_by = pw.TextField(default="")
    acknowledged_at = pw.FloatField(null=True)

    class Meta:
        table_name = "safety_events"
