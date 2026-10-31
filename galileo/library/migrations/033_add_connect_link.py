# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 033_add_connect_link.py.

Connect Link's two core-owned tables (LINK-030, LINK-240; no plugin ships its own):

* ``link_peers`` -- every paired peer (and each plugin's service credential): who it is, which
  plugin paired it, its permissions (JSON list), the salted scrypt hash of its token (never the
  token), its pinned certificate fingerprint, an expiry/revocation time and a JSON ``metadata``
  record in which a plugin keeps its own per-peer fields so they are deleted with the peer.
* ``link_audit`` -- who did what: time, acting peer, carrying peer (when delegated), plugin,
  route/operation, outcome, reason and plugin-defined fields as JSON.

Plain SQL with IF NOT EXISTS, as for 028.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS link_peers ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "peer_id TEXT NOT NULL, "
        "plugin TEXT NOT NULL, "
        "name TEXT NOT NULL, "
        "kind TEXT NOT NULL DEFAULT '', "
        "platform TEXT NOT NULL DEFAULT '', "
        "is_service INTEGER NOT NULL DEFAULT 0, "
        "permissions TEXT NOT NULL DEFAULT '[]', "
        "token_salt TEXT NOT NULL DEFAULT '', "
        "token_hash TEXT NOT NULL DEFAULT '', "
        "cert_fingerprint TEXT NOT NULL DEFAULT '', "
        "metadata TEXT NOT NULL DEFAULT '{}', "
        "created_at REAL NOT NULL, "
        "expires_at REAL, "
        "revoked_at REAL, "
        "last_contact REAL)"
    )
    migrator.sql("CREATE UNIQUE INDEX IF NOT EXISTS linkpeer_peer_id ON link_peers (peer_id)")
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS link_audit ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "ts REAL NOT NULL, "
        "actor TEXT NOT NULL DEFAULT '', "
        "carrier TEXT NOT NULL DEFAULT '', "
        "plugin TEXT NOT NULL DEFAULT '', "
        "route TEXT NOT NULL DEFAULT '', "
        "outcome TEXT NOT NULL DEFAULT '', "
        "reason TEXT NOT NULL DEFAULT '', "
        "fields TEXT NOT NULL DEFAULT '{}')"
    )
    migrator.sql("CREATE INDEX IF NOT EXISTS linkaudit_ts ON link_audit (ts)")
    migrator.sql("CREATE INDEX IF NOT EXISTS linkaudit_actor_ts ON link_audit (actor, ts)")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql("DROP TABLE IF EXISTS link_audit")
    migrator.sql("DROP TABLE IF EXISTS link_peers")
