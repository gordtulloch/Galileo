# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 029_scope_safety_devices_to_observatory.py.

Safety devices (weather stations and safety monitors) and their per-reading rules belong to the
*Observatory*, not to a Pier: one weather station watches the sky over every Pier under that roof
(OBS-030). They move from ``device_configs`` / ``weather_safety_rules`` (both keyed by Pier) to
``safety_device_configs`` / ``observatory_safety_rules`` (keyed by Observatory).

Existing data is carried over: where an Observatory's Piers each had a setting, the one on its
lowest-numbered Pier wins (the others were copies of the same station in practice). The old
per-Pier safety rows are then removed.

Plain SQL with IF NOT EXISTS, for the same reasons as migrations 024 and 028.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS safety_device_configs ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "observatory_id INTEGER NOT NULL REFERENCES observatories (id) ON DELETE CASCADE, "
        "category TEXT NOT NULL, "
        "slot TEXT NOT NULL DEFAULT 'primary', "
        "driver TEXT NOT NULL, "
        "server TEXT NOT NULL, "
        "port INTEGER NOT NULL, "
        "device_name TEXT)"
    )
    migrator.sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS safetydeviceconfigrecord_observatory_id_category_slot "
        "ON safety_device_configs (observatory_id, category, slot)"
    )
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS observatory_safety_rules ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "observatory_id INTEGER NOT NULL REFERENCES observatories (id) ON DELETE CASCADE, "
        "slot TEXT NOT NULL DEFAULT 'primary', "
        "parameter TEXT NOT NULL, "
        "label TEXT NOT NULL DEFAULT '', "
        "unit TEXT NOT NULL DEFAULT '', "
        "safety_related INTEGER NOT NULL DEFAULT 0, "
        "operator TEXT NOT NULL DEFAULT '>=', "
        "threshold REAL NOT NULL DEFAULT 0.0)"
    )
    migrator.sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS observatorysafetyrulerecord_observatory_id_slot_parameter "
        "ON observatory_safety_rules (observatory_id, slot, parameter)"
    )
    # Carry the per-Pier settings up to their Observatory (lowest Pier id first, so it wins).
    migrator.sql(
        "INSERT OR IGNORE INTO safety_device_configs "
        "(observatory_id, category, slot, driver, server, port, device_name) "
        "SELECT p.observatory_id, d.category, d.slot, d.driver, d.server, d.port, d.device_name "
        "FROM device_configs d JOIN piers p ON p.id = d.pier_id "
        "WHERE d.category IN ('weather', 'safety_monitor') ORDER BY p.id"
    )
    migrator.sql(
        "INSERT OR IGNORE INTO observatory_safety_rules "
        "(observatory_id, slot, parameter, label, unit, safety_related, operator, threshold) "
        "SELECT p.observatory_id, r.slot, r.parameter, r.label, r.unit, r.safety_related, r.operator, r.threshold "
        "FROM weather_safety_rules r JOIN piers p ON p.id = r.pier_id ORDER BY p.id"
    )
    migrator.sql("DELETE FROM device_configs WHERE category IN ('weather', 'safety_monitor')")
    migrator.sql("DROP TABLE IF EXISTS weather_safety_rules")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS weather_safety_rules ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "pier_id INTEGER NOT NULL REFERENCES piers (id) ON DELETE CASCADE, "
        "slot TEXT NOT NULL DEFAULT 'primary', "
        "parameter TEXT NOT NULL, "
        "label TEXT NOT NULL DEFAULT '', "
        "unit TEXT NOT NULL DEFAULT '', "
        "safety_related INTEGER NOT NULL DEFAULT 0, "
        "operator TEXT NOT NULL DEFAULT '>=', "
        "threshold REAL NOT NULL DEFAULT 0.0)"
    )
    migrator.sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS weathersafetyrulerecord_pier_id_slot_parameter "
        "ON weather_safety_rules (pier_id, slot, parameter)"
    )
    # Every Pier gets a copy of its Observatory's settings again.
    migrator.sql(
        "INSERT OR IGNORE INTO device_configs (pier_id, category, slot, driver, server, port, device_name) "
        "SELECT p.id, c.category, c.slot, c.driver, c.server, c.port, c.device_name "
        "FROM safety_device_configs c JOIN piers p ON p.observatory_id = c.observatory_id"
    )
    migrator.sql(
        "INSERT OR IGNORE INTO weather_safety_rules "
        "(pier_id, slot, parameter, label, unit, safety_related, operator, threshold) "
        "SELECT p.id, r.slot, r.parameter, r.label, r.unit, r.safety_related, r.operator, r.threshold "
        "FROM observatory_safety_rules r JOIN piers p ON p.observatory_id = r.observatory_id"
    )
    migrator.sql("DROP TABLE IF EXISTS observatory_safety_rules")
    migrator.sql("DROP TABLE IF EXISTS safety_device_configs")
