# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 041_add_solver_astap_args.py.

``solver_settings`` gains ``astap_args``: extra ASTAP command-line options the user types in
Options > Solve (PLT-060). Plain SQL, for the same reason as 018, 022 and 027.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    existing = set() if fake else {c.name for c in database.get_columns("solver_settings")}
    if "astap_args" not in existing:
        migrator.sql("ALTER TABLE solver_settings ADD COLUMN astap_args TEXT")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
