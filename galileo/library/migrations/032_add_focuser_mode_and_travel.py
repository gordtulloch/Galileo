# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 032_add_focuser_mode_and_travel.py.

``device_configs`` gains a focuser's operating mode and travel guard-rails (EQP-FOC-040/050):
``focuser_mode`` (``Absolute`` or ``Pulse``), ``focuser_position`` (the last known position, kept so
a pulse focuser -- which cannot report one -- is not "lost" on restart), and ``travel_min`` /
``travel_max`` (user-calibrated limits that stop moves short of the physical stops). The last three
are NULL until set. Plain SQL, for the same reason as 018's ``max_well_depth``.
"""

import peewee as pw
from peewee_migrate import Migrator

_COLUMNS = {
    "focuser_mode": "TEXT NOT NULL DEFAULT 'Absolute'",
    "focuser_position": "INTEGER",
    "travel_min": "INTEGER",
    "travel_max": "INTEGER",
}


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    existing = set() if fake else {c.name for c in database.get_columns("device_configs")}
    for name, ddl in _COLUMNS.items():
        if name not in existing:
            migrator.sql(f"ALTER TABLE device_configs ADD COLUMN {name} {ddl}")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
