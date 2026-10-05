# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Persisted per-Pier, per-filter focus offsets (Focus screen's Filter Offsets
dialog — ``EQP-FW-020``, ``FOC-060``).

One row per (Pier, filter name) holds that filter's four measured best-focus
positions from the last Filter Offsets run and the resulting offset relative
to the Pier's Primary filter, so they survive an application restart and feed
the filter-change workflows' automatic focus compensation (``FOC-060``)
without a full autofocus run.
"""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel
from galileo.library.models.observatory import PierRecord


class FilterOffsetRecord(BaseModel):
    """One Pier's saved offset state for one filter (EQP-FW-020, FOC-060)."""

    pier = pw.ForeignKeyField(PierRecord, backref="filter_offsets", on_delete="CASCADE")
    filter_name = pw.TextField()
    is_primary = pw.BooleanField(default=False)
    measurement_1 = pw.IntegerField(null=True)
    measurement_2 = pw.IntegerField(null=True)
    measurement_3 = pw.IntegerField(null=True)
    measurement_4 = pw.IntegerField(null=True)
    offset_steps = pw.IntegerField(null=True)

    class Meta:
        table_name = "filter_offsets"
        indexes = ((("pier", "filter_name"), True),)
