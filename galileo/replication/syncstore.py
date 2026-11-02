# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Typed access to the core-owned sync tables (REPL-070); a plugin ships no migration.

Outbox / inbox are queues (enqueue, claim, acknowledge), snapshots hold the rows an apply is about to
overwrite so it can be undone, reports record each run, the transfer queue tracks image transfers by
content hash, and peer state is a small per-node key/value store.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any


def _db():
    from galileo.library.models.base import db
    return db


def _rows(cursor) -> list[dict[str, Any]]:
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, r, strict=True)) for r in cursor.fetchall()]


class SyncStore:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock

    def _x(self, sql: str, params: tuple = ()):
        return _db().execute_sql(sql, params)

    # -- queues ------------------------------------------------------------------------
    def outbox_add(self, peer_id: str, table: str, natural_key: Any, op: str, payload: Any, rev: int = 0) -> int:
        cur = self._x("INSERT INTO sync_outbox (peer_id, table_name, natural_key, op, payload, rev, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (peer_id, table, json.dumps(natural_key), op, json.dumps(payload), rev, self._clock()))
        return int(cur.lastrowid)

    def outbox_claim(self, peer_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """The oldest unclaimed entries for *peer_id*, marked claimed (and attempt-counted)."""
        rows = _rows(self._x("SELECT * FROM sync_outbox WHERE peer_id = ? AND claimed_at IS NULL "
                             "ORDER BY id LIMIT ?", (peer_id, limit)))
        for r in rows:
            self._x("UPDATE sync_outbox SET claimed_at = ?, attempts = attempts + 1 WHERE id = ?",
                    (self._clock(), r["id"]))
            r["natural_key"], r["payload"] = json.loads(r["natural_key"]), json.loads(r["payload"])
        return rows

    def outbox_ack(self, ids: list[int]) -> int:
        n = 0
        for i in ids:
            n += int(self._x("DELETE FROM sync_outbox WHERE id = ?", (i,)).rowcount)
        return n

    def outbox_release(self, peer_id: str) -> int:
        """Make claimed-but-unacknowledged entries claimable again (the connection dropped)."""
        return int(self._x("UPDATE sync_outbox SET claimed_at = NULL WHERE peer_id = ?", (peer_id,)).rowcount)

    def inbox_add(self, peer_id: str, table: str, natural_key: Any, op: str, payload: Any, rev: int = 0) -> int:
        cur = self._x("INSERT INTO sync_inbox (peer_id, table_name, natural_key, op, payload, rev, received_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (peer_id, table, json.dumps(natural_key), op, json.dumps(payload), rev, self._clock()))
        return int(cur.lastrowid)

    def inbox_pending(self, limit: int = 1000) -> list[dict[str, Any]]:
        rows = _rows(self._x("SELECT * FROM sync_inbox WHERE state = 'pending' ORDER BY id LIMIT ?", (limit,)))
        for r in rows:
            r["natural_key"], r["payload"] = json.loads(r["natural_key"]), json.loads(r["payload"])
        return rows

    def inbox_mark(self, ids: list[int], state: str) -> None:
        for i in ids:
            self._x("UPDATE sync_inbox SET state = ?, applied_at = ? WHERE id = ?", (state, self._clock(), i))

    # -- snapshots and reports ------------------------------------------------------------
    def snapshot_save(self, run_id: str, data: Any, label: str = "") -> int:
        cur = self._x("INSERT INTO sync_snapshots (run_id, taken_at, label, data) VALUES (?, ?, ?, ?)",
                      (run_id, self._clock(), label, json.dumps(data)))
        return int(cur.lastrowid)

    def snapshot_get(self, run_id: str) -> list[dict[str, Any]]:
        rows = _rows(self._x("SELECT * FROM sync_snapshots WHERE run_id = ? ORDER BY id", (run_id,)))
        for r in rows:
            r["data"] = json.loads(r["data"])
        return rows

    def snapshot_delete(self, run_id: str) -> int:
        return int(self._x("DELETE FROM sync_snapshots WHERE run_id = ?", (run_id,)).rowcount)

    def report_start(self, run_id: str, peer_id: str = "") -> None:
        self._x("INSERT INTO sync_run_reports (run_id, peer_id, started_at) VALUES (?, ?, ?)",
                (run_id, peer_id, self._clock()))

    def report_finish(self, run_id: str, outcome: str, summary: Any) -> None:
        self._x("UPDATE sync_run_reports SET finished_at = ?, outcome = ?, summary = ? WHERE run_id = ?",
                (self._clock(), outcome, json.dumps(summary), run_id))

    def reports(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = _rows(self._x("SELECT * FROM sync_run_reports ORDER BY id DESC LIMIT ?", (limit,)))
        for r in rows:
            r["summary"] = json.loads(r["summary"])
        return rows

    # -- transfer queue ---------------------------------------------------------------------
    def transfer_add(self, peer_id: str, sha256: str, direction: str, name: str = "", size: int = 0,
                     priority: int = 0) -> bool:
        """Queue an object once per (peer, hash, direction); ``False`` if it was already queued."""
        now = self._clock()
        cur = self._x("INSERT OR IGNORE INTO sync_transfer_queue "
                      "(peer_id, sha256, name, size, direction, priority, created_at, updated_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (peer_id, sha256, name, size, direction, priority, now, now))
        return bool(cur.rowcount)

    def transfer_next(self, peer_id: str, direction: str) -> dict[str, Any] | None:
        rows = _rows(self._x("SELECT * FROM sync_transfer_queue WHERE peer_id = ? AND direction = ? "
                             "AND state = 'queued' ORDER BY priority DESC, id LIMIT 1", (peer_id, direction)))
        return rows[0] if rows else None

    def transfer_set(self, transfer_id: int, state: str) -> None:
        self._x("UPDATE sync_transfer_queue SET state = ?, updated_at = ?, "
                "attempts = attempts + CASE WHEN ? = 'failed' THEN 1 ELSE 0 END WHERE id = ?",
                (state, self._clock(), state, transfer_id))

    # -- per-node state ---------------------------------------------------------------------
    def peer_get(self, peer_id: str, key: str, default: Any = None) -> Any:
        row = self._x("SELECT value FROM sync_peer_state WHERE peer_id = ? AND key = ?", (peer_id, key)).fetchone()
        return json.loads(row[0]) if row else default

    def peer_set(self, peer_id: str, key: str, value: Any) -> None:
        self._x("INSERT INTO sync_peer_state (peer_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT (peer_id, key) DO UPDATE SET value = excluded.value", (peer_id, key, json.dumps(value)))

    def peer_forget(self, peer_id: str) -> None:
        """A node was deleted on the Master: drop everything held for it."""
        for table in ("sync_outbox", "sync_inbox", "sync_transfer_queue", "sync_peer_state"):
            self._x(f"DELETE FROM {table} WHERE peer_id = ?", (peer_id,))  # noqa: S608 - identifiers are constants or validated
