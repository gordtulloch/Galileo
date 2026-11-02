# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
# ruff: noqa: S608  -- table and column names are fixed literals chosen by this migration
"""Peewee migrations -- 034_add_replication_tracking.py.

Change tracking for replicable tables (REPL-010, REPL-020, REPL-080), ``app_settings`` first:

* ``modified`` (UTC seconds), ``rev`` (issued by the Master only), ``dirty`` (a local write happened
  since the last sync) and ``base_rev`` (the revision the local edit started from) on the table;
* triggers that maintain them for every ordinary write -- insert, update of the payload and delete --
  so a write through any code path, including a bulk upsert, is tracked. A delete leaves a row in
  ``repl_tombstones``;
* ``repl_state`` (one row; ``apply_mode`` = 1 while the sync engine applies a bulk of replicated rows,
  which suspends the triggers so applying a change does not mark it as a local edit);
* ``repl_revisions`` (the last revision issued per table, REPL-080).

The trigger text is the same ``galileo.replication.tracking.tracking_sql`` produces for every later
replicable table, copied here so this migration never changes if that function does. Plain SQL,
guarded so it survives a fake replay.
"""

import peewee as pw
from peewee_migrate import Migrator

_NOW = "(julianday('now') - 2440587.5) * 86400.0"


def _tracking_sql(table, key_columns, payload_columns, existing):
    out = []
    for column, ddl in (("modified", "REAL NOT NULL DEFAULT 0"), ("rev", "INTEGER NOT NULL DEFAULT 0"),
                        ("dirty", "INTEGER NOT NULL DEFAULT 0"), ("base_rev", "INTEGER NOT NULL DEFAULT 0")):
        if column not in existing:
            out.append(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    off = "(SELECT apply_mode FROM repl_state WHERE id = 1) = 0"
    changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in payload_columns)
    of = ", ".join(payload_columns)
    key = ", ".join(f"OLD.{c}" for c in key_columns)
    out.append(
        f"CREATE TRIGGER IF NOT EXISTS repl_{table}_ins AFTER INSERT ON {table} WHEN {off} BEGIN "
        f"UPDATE {table} SET dirty = 1, modified = {_NOW}, base_rev = 0 WHERE rowid = NEW.rowid; END")
    out.append(
        f"CREATE TRIGGER IF NOT EXISTS repl_{table}_upd AFTER UPDATE OF {of} ON {table} "
        f"WHEN {off} AND ({changed}) BEGIN "
        f"UPDATE {table} SET dirty = 1, modified = {_NOW}, "
        f"base_rev = CASE WHEN OLD.dirty = 1 THEN OLD.base_rev ELSE OLD.rev END WHERE rowid = NEW.rowid; END")
    out.append(
        f"CREATE TRIGGER IF NOT EXISTS repl_{table}_del AFTER DELETE ON {table} WHEN {off} BEGIN "
        f"INSERT INTO repl_tombstones (table_name, natural_key, rev, deleted_at) "
        f"VALUES ('{table}', json_array({key}), OLD.rev, {_NOW}); END")
    return out


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql("CREATE TABLE IF NOT EXISTS repl_state ("
                 "id INTEGER NOT NULL PRIMARY KEY CHECK (id = 1), apply_mode INTEGER NOT NULL DEFAULT 0)")
    migrator.sql("INSERT OR IGNORE INTO repl_state (id, apply_mode) VALUES (1, 0)")
    migrator.sql("CREATE TABLE IF NOT EXISTS repl_revisions ("
                 "table_name TEXT NOT NULL PRIMARY KEY, last_rev INTEGER NOT NULL DEFAULT 0)")
    migrator.sql("CREATE TABLE IF NOT EXISTS repl_tombstones ("
                 "id INTEGER NOT NULL PRIMARY KEY, table_name TEXT NOT NULL, natural_key TEXT NOT NULL, "
                 "rev INTEGER NOT NULL DEFAULT 0, deleted_at REAL NOT NULL)")
    migrator.sql("CREATE INDEX IF NOT EXISTS repltomb_table ON repl_tombstones (table_name, id)")
    existing = set() if fake else {c.name for c in database.get_columns("app_settings")}
    for statement in _tracking_sql("app_settings", ("namespace", "key", "scope"), ("value",), existing):
        migrator.sql(statement)


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    for suffix in ("ins", "upd", "del"):
        migrator.sql(f"DROP TRIGGER IF EXISTS repl_app_settings_{suffix}")
