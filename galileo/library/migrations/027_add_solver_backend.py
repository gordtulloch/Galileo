# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 027_add_solver_backend.py.

``solver_settings`` gains the choice of solver backend (``astap``, ``astrometry_local`` or
``astrometry_web``), the astrometry.net ``solve-field`` path and the nova.astrometry.net API key
(PLT-060). Plain SQL, for the same reason as 018, 022 and 026.
"""

import peewee as pw
from peewee_migrate import Migrator

_COLUMNS = {
    "backend": "TEXT NOT NULL DEFAULT 'astap'",
    "astrometry_executable": "TEXT",
    "nova_api_key": "TEXT",
}


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    existing = set() if fake else {c.name for c in database.get_columns("solver_settings")}
    for name, ddl in _COLUMNS.items():
        if name not in existing:
            migrator.sql(f"ALTER TABLE solver_settings ADD COLUMN {name} {ddl}")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
