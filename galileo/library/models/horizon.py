# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Persisted horizon obstruction points (Options > Star Atlas).

The horizon belongs to the Observatory — it is the skyline seen from that site — so
every Pier under it shares one. Each row is one ``(azimuth, altitude)`` pair from the
uploaded file: the altitude below which the sky is blocked at that azimuth.
"""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel
from galileo.library.models.observatory import ObservatoryRecord


class HorizonPointRecord(BaseModel):
    """One obstruction point of an Observatory's horizon."""

    observatory = pw.ForeignKeyField(ObservatoryRecord, backref="horizon_points", on_delete="CASCADE")
    azimuth_deg = pw.FloatField()
    altitude_deg = pw.FloatField()

    class Meta:
        table_name = "horizon_points"
        indexes = ((("observatory", "azimuth_deg"), False),)
