"""Peewee migrations -- 024_add_weather_safety_rules.py.

``weather_safety_rules`` (EQP-WX-020): one row per Pier+reading holding the
Weather screen's per-measure safety configuration -- whether that reading is
safety-related and the comparison/threshold that counts as unsafe for it.

Plain SQL rather than ``create_model``, same reasoning as migration 023's
filter_offsets: this table's foreign key references ``piers``, and
``migrator.orm["piers"]`` KeyErrors on any database where migration 013
already applied in an earlier run.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS weather_safety_rules ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "pier_id INTEGER NOT NULL REFERENCES piers (id) ON DELETE CASCADE, "
        "parameter TEXT NOT NULL, "
        "label TEXT NOT NULL DEFAULT '', "
        "unit TEXT NOT NULL DEFAULT '', "
        "safety_related INTEGER NOT NULL DEFAULT 0, "
        "operator TEXT NOT NULL DEFAULT '>=', "
        "threshold REAL NOT NULL DEFAULT 0.0)"
    )
    migrator.sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS weathersafetyrulerecord_pier_id_parameter "
        "ON weather_safety_rules (pier_id, parameter)"
    )


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql("DROP TABLE IF EXISTS weather_safety_rules")
