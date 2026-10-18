# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Persisted per-Observatory safety devices and their per-reading rules (Equipment > Safety
screen — ``EQP-WX-020``, ``OBS-030``).

Safety devices (weather stations, safety monitors) belong to the Observatory, not to a Pier:
one station watches the sky over every Pier under the roof. ``SafetyDeviceConfigRecord`` holds
how to reach each device; ``WeatherSafetyRuleRecord`` holds, per (device slot, reading), whether
that reading counts toward the safety verdict and what crossing it means ("Rain is YES",
"Wind >= 20 km/h"), so they survive an application restart.
"""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel
from galileo.library.models.observatory import ObservatoryRecord

PRIMARY_SLOT = "primary"


class SafetyDeviceConfigRecord(BaseModel):
    """One saved safety device (weather station or safety monitor), scoped to its Observatory."""

    observatory = pw.ForeignKeyField(ObservatoryRecord, backref="safety_devices", on_delete="CASCADE")
    category = pw.TextField()
    slot = pw.TextField(default=PRIMARY_SLOT)
    driver = pw.TextField()
    server = pw.TextField()
    port = pw.IntegerField()
    device_name = pw.TextField(null=True)

    class Meta:
        table_name = "safety_device_configs"
        indexes = ((("observatory", "category", "slot"), True),)


class WeatherSafetyRuleRecord(BaseModel):
    """One Observatory's saved safety rule for one reading of one safety device (EQP-WX-020)."""

    observatory = pw.ForeignKeyField(ObservatoryRecord, backref="safety_rules", on_delete="CASCADE")
    slot = pw.TextField(default=PRIMARY_SLOT)
    parameter = pw.TextField()
    label = pw.TextField(default="")
    unit = pw.TextField(default="")
    safety_related = pw.BooleanField(default=False)
    operator = pw.TextField(default=">=")
    threshold = pw.FloatField(default=0.0)

    class Meta:
        table_name = "observatory_safety_rules"
        indexes = ((("observatory", "slot", "parameter"), True),)
