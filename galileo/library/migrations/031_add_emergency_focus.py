# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 031_add_emergency_focus.py.

``device_configs.emergency_focus``: a focuser's saved "emergency" position, set from the Focus
screen or Equipment > Focuser and returned to when the user is wildly out of focus. It lives on the
focuser's own device-config row (one per Pier and focuser slot), so each focuser has its own. NULL
means none saved. Plain SQL, for the same reason as 018's ``max_well_depth``.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    existing = set() if fake else {c.name for c in database.get_columns("device_configs")}
    if "emergency_focus" not in existing:
        migrator.sql("ALTER TABLE device_configs ADD COLUMN emergency_focus INTEGER")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
