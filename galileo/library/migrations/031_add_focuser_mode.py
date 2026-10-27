# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 031_add_focuser_mode.py.

A no-op kept so databases that already recorded this name in ``migratehistory`` still start:
``peewee-migrate`` re-reads every applied migration's file, so deleting it breaks them. The columns
it once added (``focuser_mode`` and friends) are now added, idempotently, by
``032_add_focuser_mode_and_travel``.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    pass


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
