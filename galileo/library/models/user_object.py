# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Objects the user found by searching that are not in the bundled catalog (an online name lookup's results)."""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class UserObjectRecord(BaseModel):
    """One catalog object added by a search; merged into the Star Atlas, What's Up Tonight and Search."""

    name = pw.CharField(unique=True)
    designations_json = pw.TextField(default="[]")
    ra_deg = pw.FloatField()
    dec_deg = pw.FloatField()
    object_type = pw.CharField(default="Other")
    magnitude = pw.FloatField(default=99.0)
    size_arcmin = pw.FloatField(default=0.0)

    class Meta:
        table_name = "user_objects"
