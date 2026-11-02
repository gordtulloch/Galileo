# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 034_add_replication.py.

Replication support for NodeConnect (REPL-010, REPL-020, REPL-070, REPL-080).

* ``app_settings`` (the first replicable table) gains ``modified`` (UTC seconds), ``rev`` (issued by
  the Master), ``dirty`` (set by a local write) and ``base_rev`` (the revision the local edit started
  from). Rows that already exist are marked dirty so the first sync carries them.
* The columns are maintained by SQLite **triggers**, not by Python, so every write path --
  ``save``, ``insert ... on_conflict``, a bulk ``update`` -- is tracked and none can forget. A
  deletion writes a row to ``repl_tombstones``. The triggers stand down while ``repl_state.suppress``
  is 1, which is how a bulk apply of rows received from the Master writes without marking them dirty.
* ``repl_revs`` holds the Master's last revision per table.
* The core-owned sync tables: outbox, inbox, snapshots, run reports, transfer queue and per-node state.

Plain SQL with IF NOT EXISTS where it can be, as for 028.
"""

import peewee as pw
from peewee_migrate import Migrator

_NOW = "(julianday('now') - 2440587.5) * 86400.0"
_TABLE = "app_settings"
_KEY_COLS = ("namespace", "key", "scope")
_COLUMNS = {
    "modified": "REAL NOT NULL DEFAULT 0",
    "rev": "INTEGER NOT NULL DEFAULT 0",
    "dirty": "INTEGER NOT NULL DEFAULT 0",
    "base_rev": "INTEGER NOT NULL DEFAULT 0",
}
_GUARD = "(SELECT suppress FROM repl_state WHERE id = 1) = 0"


def _triggers(table: str, key_cols: tuple[str, ...]) -> list[str]:
    old_key = ", ".join(f"OLD.{c}" for c in key_cols)
    where = " AND ".join(f"{c} = NEW.{c}" for c in key_cols)
    return [
        f"CREATE TRIGGER IF NOT EXISTS {table}_repl_ins AFTER INSERT ON {table} WHEN {_GUARD} BEGIN "
        f"UPDATE {table} SET modified = {_NOW}, dirty = 1, base_rev = 0 WHERE {where}; END",
        f"CREATE TRIGGER IF NOT EXISTS {table}_repl_upd AFTER UPDATE ON {table} WHEN {_GUARD} AND ("
        + " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in (*key_cols, "value"))
        + ") BEGIN "
        f"UPDATE {table} SET modified = {_NOW}, "
        f"base_rev = CASE WHEN OLD.dirty = 1 THEN OLD.base_rev ELSE OLD.rev END, dirty = 1 WHERE {where}; END",
        f"CREATE TRIGGER IF NOT EXISTS {table}_repl_del AFTER DELETE ON {table} WHEN {_GUARD} BEGIN "
        f"INSERT INTO repl_tombstones (table_name, natural_key, rev, deleted_at) "
        f"VALUES ('{table}', json_array({old_key}), OLD.rev, {_NOW}); END",
    ]


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql("CREATE TABLE IF NOT EXISTS repl_state (id INTEGER NOT NULL PRIMARY KEY, suppress INTEGER NOT NULL DEFAULT 0)")
    migrator.sql("INSERT OR IGNORE INTO repl_state (id, suppress) VALUES (1, 0)")
    migrator.sql("CREATE TABLE IF NOT EXISTS repl_revs (table_name TEXT NOT NULL PRIMARY KEY, rev INTEGER NOT NULL DEFAULT 0)")
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS repl_tombstones ("
        "id INTEGER NOT NULL PRIMARY KEY, table_name TEXT NOT NULL, natural_key TEXT NOT NULL, "
        "rev INTEGER NOT NULL DEFAULT 0, deleted_at REAL NOT NULL)"
    )
    migrator.sql("CREATE INDEX IF NOT EXISTS repltomb_table ON repl_tombstones (table_name, id)")

    existing = set() if fake else {c.name for c in database.get_columns(_TABLE)}
    added = False
    for name, ddl in _COLUMNS.items():
        if name not in existing:
            migrator.sql(f"ALTER TABLE {_TABLE} ADD COLUMN {name} {ddl}")
            added = True
    if added:                                           # rows that predate tracking go out on the first sync
        migrator.sql(f"UPDATE {_TABLE} SET dirty = 1, modified = {_NOW}")
    for stmt in _triggers(_TABLE, _KEY_COLS):
        migrator.sql(stmt)

    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_outbox ("
        "id INTEGER NOT NULL PRIMARY KEY, peer_id TEXT NOT NULL, table_name TEXT NOT NULL, "
        "natural_key TEXT NOT NULL, op TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', "
        "rev INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, claimed_at REAL, attempts INTEGER NOT NULL DEFAULT 0)"
    )
    migrator.sql("CREATE INDEX IF NOT EXISTS syncoutbox_peer ON sync_outbox (peer_id, id)")
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_inbox ("
        "id INTEGER NOT NULL PRIMARY KEY, peer_id TEXT NOT NULL, table_name TEXT NOT NULL, "
        "natural_key TEXT NOT NULL, op TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', "
        "rev INTEGER NOT NULL DEFAULT 0, received_at REAL NOT NULL, applied_at REAL, "
        "state TEXT NOT NULL DEFAULT 'pending')"
    )
    migrator.sql("CREATE INDEX IF NOT EXISTS syncinbox_state ON sync_inbox (state, id)")
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_snapshots ("
        "id INTEGER NOT NULL PRIMARY KEY, run_id TEXT NOT NULL, taken_at REAL NOT NULL, "
        "label TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}')"
    )
    migrator.sql("CREATE INDEX IF NOT EXISTS syncsnap_run ON sync_snapshots (run_id)")
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_run_reports ("
        "id INTEGER NOT NULL PRIMARY KEY, run_id TEXT NOT NULL, peer_id TEXT NOT NULL DEFAULT '', "
        "started_at REAL NOT NULL, finished_at REAL, outcome TEXT NOT NULL DEFAULT '', "
        "summary TEXT NOT NULL DEFAULT '{}')"
    )
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_transfer_queue ("
        "id INTEGER NOT NULL PRIMARY KEY, peer_id TEXT NOT NULL, sha256 TEXT NOT NULL, "
        "name TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0, direction TEXT NOT NULL, "
        "priority INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'queued', "
        "attempts INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL)"
    )
    migrator.sql("CREATE UNIQUE INDEX IF NOT EXISTS synctransfer_obj ON sync_transfer_queue (peer_id, sha256, direction)")
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_peer_state ("
        "peer_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL DEFAULT 'null', "
        "PRIMARY KEY (peer_id, key))"
    )


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    for t in ("sync_peer_state", "sync_transfer_queue", "sync_run_reports", "sync_snapshots",
              "sync_inbox", "sync_outbox", "repl_tombstones", "repl_revs", "repl_state"):
        migrator.sql(f"DROP TABLE IF EXISTS {t}")
    for suffix in ("ins", "upd", "del"):
        migrator.sql(f"DROP TRIGGER IF EXISTS {_TABLE}_repl_{suffix}")
