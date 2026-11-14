# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
# ruff: noqa: S608  -- table and column names are fixed literals chosen by this migration
"""Peewee migrations -- 038_add_saved_targets.py.

``saved_targets``: the user's saved target list (Planning > Targets), filled from the Save context-menu item on
Search and What's Up Tonight tiles. One row per object, keyed by its primary name. Plain SQL, guarded so it
survives a fake replay. The table is created already under change tracking (REPL-010/030) — ``modified``, ``rev``,
``dirty`` and ``base_rev`` columns and insert / update / delete triggers, tombstone key the object's name — so
the list replicates to the other nodes and is published to mobile connections like the other configuration.
The trigger statements are those migration 037 uses.
"""

import peewee as pw
from peewee_migrate import Migrator

_NOW = "(julianday('now') - 2440587.5) * 86400.0"
PAYLOAD = ("designations_json", "ra_deg", "dec_deg", "object_type", "magnitude", "size_arcmin", "description", "saved_at")


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS saved_targets ("
        "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
        "name VARCHAR(255) NOT NULL UNIQUE, "
        "designations_json TEXT NOT NULL DEFAULT '[]', "
        "ra_deg REAL NOT NULL, "
        "dec_deg REAL NOT NULL, "
        "object_type VARCHAR(255) NOT NULL DEFAULT 'Other', "
        "magnitude REAL NOT NULL DEFAULT 99.0, "
        "size_arcmin REAL NOT NULL DEFAULT 0.0, "
        "description TEXT NOT NULL DEFAULT '', "
        "saved_at REAL NOT NULL DEFAULT 0.0, "
        "modified REAL NOT NULL DEFAULT 0, rev INTEGER NOT NULL DEFAULT 0, "
        "dirty INTEGER NOT NULL DEFAULT 0, base_rev INTEGER NOT NULL DEFAULT 0)"
    )
    off = "(SELECT apply_mode FROM repl_state WHERE id = 1) = 0"
    changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in PAYLOAD)
    migrator.sql(
        f"CREATE TRIGGER IF NOT EXISTS repl_saved_targets_ins AFTER INSERT ON saved_targets WHEN {off} BEGIN "
        f"UPDATE saved_targets SET dirty = 1, modified = {_NOW}, base_rev = 0 WHERE rowid = NEW.rowid; END")
    migrator.sql(
        f"CREATE TRIGGER IF NOT EXISTS repl_saved_targets_upd AFTER UPDATE OF {', '.join(PAYLOAD)} ON saved_targets "
        f"WHEN {off} AND ({changed}) BEGIN "
        f"UPDATE saved_targets SET dirty = 1, modified = {_NOW}, "
        f"base_rev = CASE WHEN OLD.dirty = 1 THEN OLD.base_rev ELSE OLD.rev END WHERE rowid = NEW.rowid; END")
    migrator.sql(
        f"CREATE TRIGGER IF NOT EXISTS repl_saved_targets_del AFTER DELETE ON saved_targets WHEN {off} BEGIN "
        f"INSERT INTO repl_tombstones (table_name, natural_key, rev, deleted_at) "
        f"VALUES ('saved_targets', json_array(OLD.name), OLD.rev, {_NOW}); END")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    for suffix in ("ins", "upd", "del"):
        migrator.sql(f"DROP TRIGGER IF EXISTS repl_saved_targets_{suffix}")
    migrator.sql("DROP TABLE IF EXISTS saved_targets")
