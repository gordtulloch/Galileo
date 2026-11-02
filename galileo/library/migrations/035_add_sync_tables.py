# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 035_add_sync_tables.py.

The core-owned synchronisation tables (REPL-070), so a plugin ships no migration of its own:

* ``sync_outbox`` / ``sync_inbox`` -- changes waiting to go to, or arrived from, a peer;
* ``sync_snapshots`` -- the rows as they were before an apply, so it can be undone;
* ``sync_run_reports`` -- one report per sync run;
* ``sync_transfer_queue`` -- the durable queue of binary objects to move (LINK-070);
* ``sync_peer_state`` -- small per-peer key/value state (cursors, clock offset, last run).

Plain SQL with IF NOT EXISTS, as for 033.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_outbox ("
        "id INTEGER NOT NULL PRIMARY KEY, peer_id TEXT NOT NULL, table_name TEXT NOT NULL, "
        "natural_key TEXT NOT NULL, op TEXT NOT NULL DEFAULT 'upsert', payload TEXT NOT NULL DEFAULT '{}', "
        "rev INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, claimed_at REAL, acked_at REAL)")
    migrator.sql("CREATE INDEX IF NOT EXISTS syncout_peer ON sync_outbox (peer_id, acked_at, id)")
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_inbox ("
        "id INTEGER NOT NULL PRIMARY KEY, peer_id TEXT NOT NULL, table_name TEXT NOT NULL, "
        "natural_key TEXT NOT NULL, op TEXT NOT NULL DEFAULT 'upsert', payload TEXT NOT NULL DEFAULT '{}', "
        "rev INTEGER NOT NULL DEFAULT 0, received_at REAL NOT NULL, applied_at REAL, "
        "status TEXT NOT NULL DEFAULT 'pending')")
    migrator.sql("CREATE INDEX IF NOT EXISTS syncin_peer ON sync_inbox (peer_id, status, id)")
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_snapshots ("
        "id INTEGER NOT NULL PRIMARY KEY, run_id TEXT NOT NULL, table_name TEXT NOT NULL, "
        "natural_key TEXT NOT NULL, before TEXT, taken_at REAL NOT NULL)")
    migrator.sql("CREATE INDEX IF NOT EXISTS syncsnap_run ON sync_snapshots (run_id, id)")
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_run_reports ("
        "id INTEGER NOT NULL PRIMARY KEY, run_id TEXT NOT NULL, peer_id TEXT NOT NULL DEFAULT '', "
        "started_at REAL NOT NULL, finished_at REAL, outcome TEXT NOT NULL DEFAULT '', "
        "summary TEXT NOT NULL DEFAULT '{}')")
    migrator.sql("CREATE INDEX IF NOT EXISTS syncrep_started ON sync_run_reports (started_at)")
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_transfer_queue ("
        "id INTEGER NOT NULL PRIMARY KEY, peer_id TEXT NOT NULL, direction TEXT NOT NULL DEFAULT 'up', "
        "object_hash TEXT NOT NULL, size INTEGER NOT NULL DEFAULT 0, priority INTEGER NOT NULL DEFAULT 5, "
        "state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, "
        "created_at REAL NOT NULL, updated_at REAL NOT NULL)")
    migrator.sql("CREATE UNIQUE INDEX IF NOT EXISTS synctq_obj ON sync_transfer_queue (peer_id, direction, object_hash)")
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS sync_peer_state ("
        "peer_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL DEFAULT 'null', "
        "PRIMARY KEY (peer_id, key))")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    for table in ("sync_peer_state", "sync_transfer_queue", "sync_run_reports", "sync_snapshots",
                  "sync_inbox", "sync_outbox"):
        migrator.sql(f"DROP TABLE IF EXISTS {table}")
