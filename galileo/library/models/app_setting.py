# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The generic configuration row behind ``galileo.settings_store`` (migration 028)."""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class AppSettingRecord(BaseModel):
    """One setting: ``value`` is JSON text, ``scope`` is empty for global or e.g. a Pier id."""

    namespace = pw.TextField()
    key = pw.TextField()
    scope = pw.TextField(default="")
    value = pw.TextField(default="null")

    class Meta:
        table_name = "app_settings"
        indexes = ((("namespace", "key", "scope"), True),)
