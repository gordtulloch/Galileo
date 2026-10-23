"""Peewee migrations -- 030_add_camera_default_gain_offset.py.

``device_configs.default_gain`` / ``default_offset``: a camera's preferred gain and offset, set on
the Equipment > Camera page and loaded into the Imaging page whenever that camera (or Pier) is
selected. NULL means "not set" -- the Imaging page keeps its own default. Plain SQL, for the same
reason as 018's ``max_well_depth``.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    existing = set() if fake else {c.name for c in database.get_columns("device_configs")}
    for column in ("default_gain", "default_offset"):
        if column not in existing:
            migrator.sql(f"ALTER TABLE device_configs ADD COLUMN {column} INTEGER")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
