# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 036_tombstone_commit.py.

``repl_tombstones.committed``: a deletion is a change like any other, so on the Master it must be
given a revision from the table's serial counter (REPL-080) before spokes can ask for "everything
since revision N". A tombstone starts uncommitted (its ``rev`` is only the revision the row had when
it was deleted) and the Master commits it, replacing ``rev`` with a new one and setting ``committed``.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    existing = set() if fake else {c.name for c in database.get_columns("repl_tombstones")}
    if "committed" not in existing:
        migrator.sql("ALTER TABLE repl_tombstones ADD COLUMN committed INTEGER NOT NULL DEFAULT 0")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    pass
