# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Persisted per-Pier, per-reading weather safety rules (Equipment > Weather
screen — ``EQP-WX-020``).

One row per (Pier, Weather-Station reading) holds whether that reading
counts toward the Weather screen's safety verdict and what crossing it means
("Rain is YES", "Wind >= 20 km/h"), so they survive an application restart.
The Safety Monitor screen (``EQP-SAFE-020``) reads the safety-related subset
of these rows alongside live readings, read-only.
"""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel
from galileo.library.models.observatory import PierRecord


class WeatherSafetyRuleRecord(BaseModel):
    """One Pier's saved safety rule for one Weather Station reading (EQP-WX-020)."""

    pier = pw.ForeignKeyField(PierRecord, backref="weather_safety_rules", on_delete="CASCADE")
    parameter = pw.TextField()
    label = pw.TextField(default="")
    unit = pw.TextField(default="")
    safety_related = pw.BooleanField(default=False)
    operator = pw.TextField(default=">=")
    threshold = pw.FloatField(default=0.0)

    class Meta:
        table_name = "weather_safety_rules"
        indexes = ((("pier", "parameter"), True),)
