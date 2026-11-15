# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Sessions that were saved or scheduled, kept until they complete or are deleted (SES-060, SES-210)."""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class SavedSessionRecord(BaseModel):
    """One Sessions-screen session: its Pier, name, camera and block list (``blocks_json`` uses the same
    ``{class name: fields}`` encoding as templates)."""

    pier_name = pw.CharField(default="", index=True)
    name = pw.CharField()
    camera_slot = pw.CharField(default="primary")
    blocks_json = pw.TextField(default="[]")

    class Meta:
        table_name = "saved_sessions"
