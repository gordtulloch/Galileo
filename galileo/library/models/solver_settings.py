# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Persisted per-Pier plate-solver settings (Options > Solve, PLT-060).

One row per Pier holds the ASTAP executable path override and solver search
parameters (field-of-view hint, search radius, downsample) the Solve screen's
``PlateSolver`` is built from, so they survive an application restart instead
of always falling back to auto-detecting the executable and the hardcoded
defaults ``galileo.ui.solve`` used to construct on every call.

``fov_hint_deg`` of ``0`` (the default) means "derive it from the active
optical train," same as ``galileo.platesolve.SolverParams`` already does —
this only stores an explicit override. ``executable`` is the ASTAP path; ``backend``,
``astrometry_executable`` and ``nova_api_key`` select and configure the astrometry.net alternatives.
"""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel
from galileo.library.models.observatory import PierRecord


class SolverSettingsRecord(BaseModel):
    """One Pier's saved solver defaults (PLT-060)."""

    pier = pw.ForeignKeyField(PierRecord, backref="solver_settings", on_delete="CASCADE", unique=True)
    executable = pw.TextField(null=True)
    fov_hint_deg = pw.FloatField(default=0.0)
    search_radius_deg = pw.FloatField(default=30.0)
    # 0 disables downsampling — the Solve screen's own long-standing default,
    # kept distinct from SolverParams' own general-purpose dataclass default
    # of 2 so that an unconfigured Pier's behaviour doesn't silently change.
    downsample = pw.IntegerField(default=0)
    # Which solver: "astap", "astrometry_local" (solve-field) or "astrometry_web" (nova.astrometry.net) or "tetra3".
    backend = pw.TextField(default="astap")
    astrometry_executable = pw.TextField(null=True)
    nova_api_key = pw.TextField(null=True)
    tetra3_database = pw.TextField(null=True)   # blank = the database tetra3 ships with

    class Meta:
        table_name = "solver_settings"
