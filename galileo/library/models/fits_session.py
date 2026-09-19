# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""FITS session (image group) model (adapted from AstroFiler models/fits_session.py)."""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class FitsSession(BaseModel):
    """A group of related FITS files forming one imaging session."""

    id = pw.TextField(primary_key=True)
    session_name = pw.TextField(null=True)
    object_name = pw.TextField(null=True)
    session_date = pw.DateField(null=True)
    instrument = pw.TextField(null=True)
    binning_x = pw.TextField(null=True)
    binning_y = pw.TextField(null=True)
    ccd_temp = pw.TextField(null=True)
    frame_count = pw.IntegerField(default=0)
    session_type = pw.TextField(null=True)  # light | calibration | sequence_step
    step_name = pw.TextField(null=True)     # for sequence-step sessions (LIB-160)

    class Meta:
        table_name = "fits_sessions"
