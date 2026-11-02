# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Typed access to the core-owned sync tables (REPL-070).

Outbox and inbox queues (insert / claim / acknowledge), snapshots (save / read back for undo), run
reports, the transfer queue and per-peer state all live in core tables (migration 035), so a sync
plugin ships no migration. A plugin also releases tombstones here once a deletion has propagated.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, Protocol

from galileo.replication import tracking


class SyncStorePort(Protocol):
    """The shape a plugin codes against (and fakes in its tests)."""

    def outbox_add(self, peer_id: str, table: str, key: str, payload: dict[str, Any], rev: int = 0,
                   op: str = "upsert") -> int: ...
    def outbox_claim(self, peer_id: str, limit: int = 200) -> list[dict[str, Any]]: ...
    def outbox_ack(self, ids: list[int]) -> None: ...
    def inbox_add(self, peer_id: str, table: str, key: str, payload: dict[str, Any], rev: int = 0,
                  op: str = "upsert") -> int: ...
    def inbox_pending(self, peer_id: str, limit: int = 200) -> list[dict[str, Any]]: ...
    def inbox_mark(self, ids: list[int], status: str) -> None: ...
    def snapshot_save(self, run_id: str, table: str, key: str, before: dict[str, Any] | None) -> None: ...
    def snapshot_rows(self, run_id: str) -> list[dict[str, Any]]: ...
    def report_append(self, run_id: str, peer_id: str, outcome: str, summary: dict[str, Any],
                      started_at: float | None = None) -> None: ...
    def reports(self, limit: int = 50) -> list[dict[str, Any]]: ...
    def transfer_enqueue(self, peer_id: str, direction: str, object_hash: str, size: int,
                         priority: int = 5) -> int: ...
    def transfer_claim(self, peer_id: str = "") -> dict[str, Any] | None: ...
    def transfer_update(self, transfer_id: int, state: str) -> None: ...
    def peer_state_get(self, peer_id: str, key: str, default: Any = None) -> Any: ...
    def peer_state_set(self, peer_id: str, key: str, value: Any) -> None: ...
    def release_tombstones(self, table: str, up_to_id: int) -> int: ...


def _db():
    from galileo.library.models.base import db
    db.connect(reuse_if_open=True)
    return db


def _rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = _db().execute_sql(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


class SyncStore:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock

    # -- outbox / inbox ---------------------------------------------------------------------
    def outbox_add(self, peer_id: str, table: str, key: str, payload: dict[str, Any], rev: int = 0,
                   op: str = "upsert") -> int:
        cur = _db().execute_sql(
            "INSERT INTO sync_outbox (peer_id, table_name, natural_key, op, payload, rev, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (peer_id, table, key, op, json.dumps(payload), rev, self._clock()))
        return int(cur.lastrowid)

    def outbox_claim(self, peer_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """The oldest unacknowledged changes for a peer, marked claimed. A claim that is never
        acknowledged is offered again, so a dropped connection loses nothing."""
        rows = _rows("SELECT * FROM sync_outbox WHERE peer_id = ? AND acked_at IS NULL ORDER BY id LIMIT ?",
                     (peer_id, limit))
        if rows:
            marks = ",".join("?" * len(rows))
            _db().execute_sql(f"UPDATE sync_outbox SET claimed_at = ? WHERE id IN ({marks})",  # noqa: S608
                              (self._clock(), *[r["id"] for r in rows]))
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    def outbox_ack(self, ids: list[int]) -> None:
        if ids:
            marks = ",".join("?" * len(ids))
            _db().execute_sql(f"UPDATE sync_outbox SET acked_at = ? WHERE id IN ({marks})",  # noqa: S608
                              (self._clock(), *ids))

    def inbox_add(self, peer_id: str, table: str, key: str, payload: dict[str, Any], rev: int = 0,
                  op: str = "upsert") -> int:
        cur = _db().execute_sql(
            "INSERT INTO sync_inbox (peer_id, table_name, natural_key, op, payload, rev, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (peer_id, table, key, op, json.dumps(payload), rev, self._clock()))
        return int(cur.lastrowid)

    def inbox_pending(self, peer_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = _rows("SELECT * FROM sync_inbox WHERE peer_id = ? AND status = 'pending' ORDER BY id LIMIT ?",
                     (peer_id, limit))
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    def inbox_mark(self, ids: list[int], status: str) -> None:
        if ids:
            marks = ",".join("?" * len(ids))
            _db().execute_sql(f"UPDATE sync_inbox SET status = ?, applied_at = ? WHERE id IN ({marks})",  # noqa: S608
                              (status, self._clock(), *ids))

    # -- snapshots and reports -------------------------------------------------------------
    def snapshot_save(self, run_id: str, table: str, key: str, before: dict[str, Any] | None) -> None:
        """The row as it was before an apply (``None`` when it did not exist), so the run can be undone."""
        _db().execute_sql(
            "INSERT INTO sync_snapshots (run_id, table_name, natural_key, before, taken_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, table, key, None if before is None else json.dumps(before), self._clock()))

    def snapshot_rows(self, run_id: str) -> list[dict[str, Any]]:
        """The run's snapshots, newest first — the order an undo replays them."""
        rows = _rows("SELECT * FROM sync_snapshots WHERE run_id = ? ORDER BY id DESC", (run_id,))
        for r in rows:
            r["before"] = None if r["before"] is None else json.loads(r["before"])
        return rows

    def report_append(self, run_id: str, peer_id: str, outcome: str, summary: dict[str, Any],
                      started_at: float | None = None) -> None:
        now = self._clock()
        _db().execute_sql(
            "INSERT INTO sync_run_reports (run_id, peer_id, started_at, finished_at, outcome, summary) "
            "VALUES (?, ?, ?, ?, ?, ?)", (run_id, peer_id, started_at if started_at is not None else now, now,
                                          outcome, json.dumps(summary)))

    def reports(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = _rows("SELECT * FROM sync_run_reports ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["summary"] = json.loads(r["summary"])
        return rows

    # -- transfer queue ----------------------------------------------------------------------
    def transfer_enqueue(self, peer_id: str, direction: str, object_hash: str, size: int, priority: int = 5) -> int:
        """Queue an object by its hash; the same object for the same peer and direction is queued once."""
        now = self._clock()
        _db().execute_sql(
            "INSERT OR IGNORE INTO sync_transfer_queue "
            "(peer_id, direction, object_hash, size, priority, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (peer_id, direction, object_hash, size, priority, now, now))
        row = _db().execute_sql(
            "SELECT id FROM sync_transfer_queue WHERE peer_id = ? AND direction = ? AND object_hash = ?",
            (peer_id, direction, object_hash)).fetchone()
        return int(row[0])

    def transfer_claim(self, peer_id: str = "") -> dict[str, Any] | None:
        """The next queued transfer (lowest priority number first) marked ``active``, or ``None``."""
        rows = _rows("SELECT * FROM sync_transfer_queue WHERE state IN ('queued', 'retry') "
                     "AND (? = '' OR peer_id = ?) ORDER BY priority, id LIMIT 1", (peer_id, peer_id))
        if not rows:
            return None
        _db().execute_sql("UPDATE sync_transfer_queue SET state = 'active', attempts = attempts + 1, "
                          "updated_at = ? WHERE id = ?", (self._clock(), rows[0]["id"]))
        rows[0]["attempts"] += 1
        rows[0]["state"] = "active"
        return rows[0]

    def transfer_update(self, transfer_id: int, state: str) -> None:
        _db().execute_sql("UPDATE sync_transfer_queue SET state = ?, updated_at = ? WHERE id = ?",
                          (state, self._clock(), transfer_id))

    # -- per-peer state ------------------------------------------------------------------------
    def peer_state_get(self, peer_id: str, key: str, default: Any = None) -> Any:
        row = _db().execute_sql("SELECT value FROM sync_peer_state WHERE peer_id = ? AND key = ?",
                                (peer_id, key)).fetchone()
        return json.loads(row[0]) if row else default

    def peer_state_set(self, peer_id: str, key: str, value: Any) -> None:
        _db().execute_sql("INSERT INTO sync_peer_state (peer_id, key, value) VALUES (?, ?, ?) "
                          "ON CONFLICT (peer_id, key) DO UPDATE SET value = excluded.value",
                          (peer_id, key, json.dumps(value)))

    # -- tombstones ----------------------------------------------------------------------------
    def release_tombstones(self, table: str, up_to_id: int) -> int:
        return tracking.release_tombstones(table, up_to_id)


__all__ = ["SyncStore", "SyncStorePort"]
