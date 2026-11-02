# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 036_add_frame_location.py.

Where a frame's pixels live (LIB-200): ``fitsFileLocation`` is ``local`` (the file is on this node) or
``on_master`` (a Master holds it and the local copy was deleted), and ``fitsFileHolderNode`` names the
holding node. The catalog row, thumbnail and quality metrics stay either way. Camel-case column names
follow the rest of the AstroFiler catalog. Guarded so it survives a fake replay.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    existing = set() if fake else {c.name for c in database.get_columns("fitsFile")}
    if "fitsFileLocation" not in existing:
        migrator.sql("ALTER TABLE fitsFile ADD COLUMN fitsFileLocation TEXT NOT NULL DEFAULT 'local'")
    if "fitsFileHolderNode" not in existing:
        migrator.sql("ALTER TABLE fitsFile ADD COLUMN fitsFileHolderNode TEXT")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    pass
