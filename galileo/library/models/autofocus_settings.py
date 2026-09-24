# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Persisted per-Pier autofocus parameters (Options > Focus, FOC-070).

One row per Pier holds the autofocus-run defaults (step size, sample points,
exposure time, backlash compensation) the Focus screen's controls are seeded
from, so they survive an application restart instead of always resetting to
``galileo.autofocus.AutofocusParams``' hardcoded class defaults.
"""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel
from galileo.library.models.observatory import PierRecord


class AutofocusSettingsRecord(BaseModel):
    """One Pier's saved autofocus defaults (FOC-070)."""

    pier = pw.ForeignKeyField(PierRecord, backref="autofocus_settings", on_delete="CASCADE", unique=True)
    step_size = pw.IntegerField(default=200)
    num_points = pw.IntegerField(default=9)
    exposure_s = pw.FloatField(default=3.0)
    backlash_compensation = pw.IntegerField(default=0)

    class Meta:
        table_name = "autofocus_settings"
