# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 042_add_safety_events.py.

``safety_events`` records each protective stop and its acknowledgement (SAFE-170), and ``observatory_safety_rules``
gains ``action``: whether a breached weather rule stops everything or only warns (SAFE-030). Existing rules stop,
as they blocked before. Plain SQL, for the same reasons as 029 and 041.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS safety_events ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "scope TEXT NOT NULL DEFAULT '', "
        "reason TEXT NOT NULL DEFAULT '', "
        "at REAL NOT NULL DEFAULT 0, "
        "outcome TEXT NOT NULL DEFAULT '', "
        "problems TEXT NOT NULL DEFAULT '', "
        "acknowledged_by TEXT NOT NULL DEFAULT '', "
        "acknowledged_at REAL)"
    )
    existing = set() if fake else {c.name for c in database.get_columns("observatory_safety_rules")}
    if "action" not in existing:
        migrator.sql("ALTER TABLE observatory_safety_rules ADD COLUMN action TEXT NOT NULL DEFAULT 'stop'")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    pass
