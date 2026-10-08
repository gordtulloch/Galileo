"""Peewee migrations -- 026_add_mount_limits.py.

``device_configs`` gains the Mount page's "Meridian Flip" and "Limits" settings (EQP-MNT-060,
EQP-MNT-070): ``flip_enabled``/``flip_ha_deg``, ``alt_limits_enabled``/``min_alt``/``max_alt``/
``alt_tracking_only`` and ``ha_limits_enabled``/``max_ha_hours``. Only mount rows use them.

Plain SQL, for the same reason as 018 and 022: ``device_configs`` predates the migrator on any
database where 013 ran in an earlier batch.
"""

import peewee as pw
from peewee_migrate import Migrator

_COLUMNS = {
    "flip_enabled": "INTEGER NOT NULL DEFAULT 0",
    "flip_ha_deg": "REAL NOT NULL DEFAULT 5.0",
    "alt_limits_enabled": "INTEGER NOT NULL DEFAULT 0",
    "min_alt": "REAL NOT NULL DEFAULT 0.0",
    "max_alt": "REAL NOT NULL DEFAULT 90.0",
    "alt_tracking_only": "INTEGER NOT NULL DEFAULT 0",
    "ha_limits_enabled": "INTEGER NOT NULL DEFAULT 0",
    "max_ha_hours": "REAL NOT NULL DEFAULT 2.0",
}


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    existing = set() if fake else {c.name for c in database.get_columns("device_configs")}
    for name, ddl in _COLUMNS.items():
        if name not in existing:
            migrator.sql(f"ALTER TABLE device_configs ADD COLUMN {name} {ddl}")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
