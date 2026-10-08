"""Peewee migrations -- 025_add_weather_safety_rule_slot.py.

The Equipment > Safety screen now holds any number of safety devices (weather
stations, safety monitors), each with its own per-reading rules, so
``weather_safety_rules`` gains a ``slot`` column naming the device the rule
belongs to. Existing rows become the ``primary`` device's, and the unique
index widens from (pier, parameter) to (pier, slot, parameter).

Plain SQL for the same reason as migration 024.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    # Skipped when the column is already there (a database built from the
    # current models); introspection is skipped under ``fake`` replays, where
    # ``database`` is a mock.
    if fake or "slot" not in {c.name for c in database.get_columns("weather_safety_rules")}:
        migrator.sql("ALTER TABLE weather_safety_rules ADD COLUMN slot TEXT NOT NULL DEFAULT 'primary'")
    migrator.sql("DROP INDEX IF EXISTS weathersafetyrulerecord_pier_id_parameter")
    migrator.sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS weathersafetyrulerecord_pier_id_slot_parameter "
        "ON weather_safety_rules (pier_id, slot, parameter)"
    )


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql("DROP INDEX IF EXISTS weathersafetyrulerecord_pier_id_slot_parameter")
    migrator.sql("DELETE FROM weather_safety_rules WHERE slot != 'primary'")
    migrator.sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS weathersafetyrulerecord_pier_id_parameter "
        "ON weather_safety_rules (pier_id, parameter)"
    )
