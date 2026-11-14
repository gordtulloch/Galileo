# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Persisted saved targets (Planning > Targets): the objects the user chose to keep from Search / What's Up Tonight."""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class SavedTargetRecord(BaseModel):
    """One saved catalog object. Stored whole (not by catalog id) so an object found by an online name lookup
    survives even though it is not in the bundled catalog."""

    name = pw.CharField(unique=True)
    designations_json = pw.TextField(default="[]")
    ra_deg = pw.FloatField()
    dec_deg = pw.FloatField()
    object_type = pw.CharField(default="Other")
    magnitude = pw.FloatField(default=99.0)
    size_arcmin = pw.FloatField(default=0.0)
    description = pw.TextField(default="")
    saved_at = pw.FloatField(default=0.0)

    class Meta:
        table_name = "saved_targets"
