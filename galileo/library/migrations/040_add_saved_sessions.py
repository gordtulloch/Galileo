# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 040_add_saved_sessions.py.

``saved_sessions``: a Sessions-screen session (its blocks and camera) that has been saved or scheduled, kept until
it completes or is deleted. Scheduled jobs are stored without their blocks in ``scheduler_jobs``, so before this a
scheduled session could not be run (or shown) again after a restart, and the Save button wrote a file nothing read.
Not put under replication tracking: a session belongs to the machine and Pier it was built on.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS saved_sessions ("
        "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
        "pier_name VARCHAR(255) NOT NULL DEFAULT '', "
        "name VARCHAR(255) NOT NULL, "
        "camera_slot VARCHAR(255) NOT NULL DEFAULT 'primary', "
        "blocks_json TEXT NOT NULL DEFAULT '[]')"
    )
    migrator.sql("CREATE INDEX IF NOT EXISTS savedsessionrecord_pier_name ON saved_sessions (pier_name)")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql("DROP TABLE IF EXISTS saved_sessions")
