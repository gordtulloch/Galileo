# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
# ruff: noqa: S608  -- table and column names are fixed literals chosen by this migration
"""Peewee migrations -- 037_track_configuration_tables.py.

Puts the configuration tables under change tracking (REPL-010, REPL-020, REPL-030) as 034 did for
``app_settings``: ``modified``, ``rev``, ``dirty`` and ``base_rev`` columns, and insert / update / delete
triggers that keep them and leave a tombstone on delete. The tombstone key is built from the *names* of a
row's parents (an Observatory's name, a Pier's observatory and name) because the ids differ on every node.
Triggers are suspended while the sync engine applies replicated rows (``repl_state.apply_mode``). The
statements are the same ones ``galileo.replication.tracking.tracking_sql`` produces, written out here so
this migration never changes if that function does. Guarded so it survives a fake replay.
"""

import peewee as pw
from peewee_migrate import Migrator

_NOW = "(julianday('now') - 2440587.5) * 86400.0"

# table -> (payload columns whose change counts as an edit, SQL expressions on OLD forming the tombstone key)
TABLES = {
    'observatories': (
        ('latitude', 'longitude', 'timezone', 'physical_address', 'owner', 'elevation_m', 'notification_type', 'email_address', 'cell_number'),
        ['OLD.name'],
    ),
    'session_templates': (
        ('blocks_json',),
        ['OLD.name'],
    ),
    'piers': (
        ('connect_on_startup',),
        ['(SELECT name FROM observatories WHERE id = OLD.observatory_id)', 'OLD.name'],
    ),
    'horizon_points': (
        ('altitude_deg',),
        ['(SELECT name FROM observatories WHERE id = OLD.observatory_id)', 'OLD.azimuth_deg'],
    ),
    'observatory_safety_rules': (
        ('label', 'unit', 'safety_related', 'operator', 'threshold'),
        ['(SELECT name FROM observatories WHERE id = OLD.observatory_id)', 'OLD.slot', 'OLD.parameter'],
    ),
    'safety_device_configs': (
        ('driver', 'server', 'port', 'device_name'),
        ['(SELECT name FROM observatories WHERE id = OLD.observatory_id)', 'OLD.category', 'OLD.slot'],
    ),
    'optical_tubes': (
        ('name', 'focal_length_mm', 'aperture_mm', 'optical_system', 'image_reversed', 'image_inverted', 'associated_devices'),
        ['json_array((SELECT o.name FROM observatories o JOIN piers p ON p.observatory_id = o.id WHERE p.id = OLD.pier_id), (SELECT name FROM piers WHERE id = OLD.pier_id))', 'OLD.position'],
    ),
    'device_configs': (
        ('driver', 'server', 'port', 'device_name', 'pixel_size_um', 'sensor_width_px', 'sensor_height_px', 'sensor_name', 'bayer_pattern', 'max_well_depth', 'panel_type', 'flip_enabled', 'flip_ha_deg', 'alt_limits_enabled', 'min_alt', 'max_alt', 'alt_tracking_only', 'ha_limits_enabled', 'max_ha_hours', 'default_gain', 'default_offset', 'emergency_focus', 'focuser_mode', 'travel_min', 'travel_max'),
        ['json_array((SELECT o.name FROM observatories o JOIN piers p ON p.observatory_id = o.id WHERE p.id = OLD.pier_id), (SELECT name FROM piers WHERE id = OLD.pier_id))', 'OLD.category', 'OLD.slot'],
    ),
    'autofocus_settings': (
        ('step_size', 'num_points', 'exposure_s', 'backlash_compensation'),
        ['json_array((SELECT o.name FROM observatories o JOIN piers p ON p.observatory_id = o.id WHERE p.id = OLD.pier_id), (SELECT name FROM piers WHERE id = OLD.pier_id))'],
    ),
    'solver_settings': (
        ('fov_hint_deg', 'search_radius_deg', 'downsample', 'backend', 'nova_api_key'),
        ['json_array((SELECT o.name FROM observatories o JOIN piers p ON p.observatory_id = o.id WHERE p.id = OLD.pier_id), (SELECT name FROM piers WHERE id = OLD.pier_id))'],
    ),
    'filter_offsets': (
        ('is_primary', 'measurement_1', 'measurement_2', 'measurement_3', 'measurement_4', 'offset_steps'),
        ['json_array((SELECT o.name FROM observatories o JOIN piers p ON p.observatory_id = o.id WHERE p.id = OLD.pier_id), (SELECT name FROM piers WHERE id = OLD.pier_id))', 'OLD.filter_name'],
    ),
}


def _sql(table, payload, key_exprs, existing):
    out = []
    for column, ddl in (("modified", "REAL NOT NULL DEFAULT 0"), ("rev", "INTEGER NOT NULL DEFAULT 0"),
                        ("dirty", "INTEGER NOT NULL DEFAULT 0"), ("base_rev", "INTEGER NOT NULL DEFAULT 0")):
        if column not in existing:
            out.append(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    off = "(SELECT apply_mode FROM repl_state WHERE id = 1) = 0"
    changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in payload)
    key = ", ".join(key_exprs)
    out.append(
        f"CREATE TRIGGER IF NOT EXISTS repl_{table}_ins AFTER INSERT ON {table} WHEN {off} BEGIN "
        f"UPDATE {table} SET dirty = 1, modified = {_NOW}, base_rev = 0 WHERE rowid = NEW.rowid; END")
    out.append(
        f"CREATE TRIGGER IF NOT EXISTS repl_{table}_upd AFTER UPDATE OF {', '.join(payload)} ON {table} "
        f"WHEN {off} AND ({changed}) BEGIN "
        f"UPDATE {table} SET dirty = 1, modified = {_NOW}, "
        f"base_rev = CASE WHEN OLD.dirty = 1 THEN OLD.base_rev ELSE OLD.rev END WHERE rowid = NEW.rowid; END")
    out.append(
        f"CREATE TRIGGER IF NOT EXISTS repl_{table}_del AFTER DELETE ON {table} WHEN {off} BEGIN "
        f"INSERT INTO repl_tombstones (table_name, natural_key, rev, deleted_at) "
        f"VALUES ('{table}', json_array({key}), OLD.rev, {_NOW}); END")
    return out


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    for table, (payload, key_exprs) in TABLES.items():
        existing = set() if fake else {c.name for c in database.get_columns(table)}
        for statement in _sql(table, payload, key_exprs, existing):
            migrator.sql(statement)


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    for table in TABLES:
        for suffix in ("ins", "upd", "del"):
            migrator.sql(f"DROP TRIGGER IF EXISTS repl_{table}_{suffix}")
