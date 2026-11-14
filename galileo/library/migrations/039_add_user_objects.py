# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 039_add_user_objects.py.

``user_objects``: objects found by an online name search that are not in the bundled catalog. They are kept so
they are always shown in the Star Atlas, What's Up Tonight and Search. Catalog data rather than configuration, so
it is not put under replication tracking.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS user_objects ("
        "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
        "name VARCHAR(255) NOT NULL UNIQUE, "
        "designations_json TEXT NOT NULL DEFAULT '[]', "
        "ra_deg REAL NOT NULL, "
        "dec_deg REAL NOT NULL, "
        "object_type VARCHAR(255) NOT NULL DEFAULT 'Other', "
        "magnitude REAL NOT NULL DEFAULT 99.0, "
        "size_arcmin REAL NOT NULL DEFAULT 0.0)"
    )


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql("DROP TABLE IF EXISTS user_objects")
