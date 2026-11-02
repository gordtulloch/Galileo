# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
# ruff: noqa: S608  -- table and column names are validated by _ident before they reach SQL

"""Change tracking for replicable tables (REPL-010, REPL-020, REPL-080).

Tracking lives in the database as triggers, so every ordinary write — including a bulk upsert that
bypasses the ORM's ``save`` — sets ``dirty``, stamps ``modified`` and remembers the ``base_rev`` the
edit started from, and a delete leaves a tombstone. :func:`tracking_sql` produces the statements a
numbered migration runs to put a new replicable table under tracking (migration 034 did it for
``app_settings``). While the sync engine applies replicated rows it wraps the work in
:func:`apply_mode`, which suspends the triggers so applying a change is not mistaken for a local edit.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NOW = "(julianday('now') - 2440587.5) * 86400.0"
TRACKED_COLUMNS = ("modified", "rev", "dirty", "base_rev")


class NotMasterError(RuntimeError):
    """Only the Master issues revisions (REPL-080)."""


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"not a safe SQL identifier: {name!r}")
    return name


def tracking_sql(table: str, key_columns: Iterable[str], payload_columns: Iterable[str],
                 existing_columns: Iterable[str] = (), key_exprs: Iterable[str] | None = None) -> list[str]:
    """The statements that put *table* under change tracking. ``existing_columns`` lets a migration skip
    columns already present, so replaying it is harmless."""
    table = _ident(table)
    keys, payload = [_ident(c) for c in key_columns], [_ident(c) for c in payload_columns]
    have = set(existing_columns)
    out = []
    for column, ddl in (("modified", "REAL NOT NULL DEFAULT 0"), ("rev", "INTEGER NOT NULL DEFAULT 0"),
                        ("dirty", "INTEGER NOT NULL DEFAULT 0"), ("base_rev", "INTEGER NOT NULL DEFAULT 0")):
        if column not in have:
            out.append(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    off = "(SELECT apply_mode FROM repl_state WHERE id = 1) = 0"
    changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in payload)
    # A tombstone's key is built from SQL expressions on OLD when a table's natural key goes through a
    # parent (a Pier is named by its Observatory's name, not by an id that differs on every node).
    key = ", ".join(key_exprs) if key_exprs is not None else ", ".join(f"OLD.{c}" for c in keys)
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


def _db():
    from galileo.library.models.base import db
    db.connect(reuse_if_open=True)
    return db


def reset_apply_mode() -> None:
    """Clear a flag left set by a crash mid-apply, so local edits are tracked again. Called at start-up."""
    try:
        _db().execute_sql("UPDATE repl_state SET apply_mode = 0 WHERE id = 1")
    except Exception:
        logger.debug("replication state not available yet", exc_info=True)


@contextmanager
def apply_mode() -> Iterator[None]:
    """Suspend tracking while replicated rows are applied, inside one transaction so a failure rolls the
    whole bulk back and the flag with it."""
    db = _db()
    with db.atomic("IMMEDIATE"):
        db.execute_sql("UPDATE repl_state SET apply_mode = 1 WHERE id = 1")
        try:
            yield
        finally:
            db.execute_sql("UPDATE repl_state SET apply_mode = 0 WHERE id = 1")


def dirty_rows(table: str) -> list[dict[str, Any]]:
    """Rows of *table* edited locally since they were last marked clean."""
    cur = _db().execute_sql(f"SELECT * FROM {_ident(table)} WHERE dirty = 1 ORDER BY modified")
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def mark_clean(table: str, where_sql: str, params: tuple[Any, ...], rev: int) -> None:
    """After a row has been synchronised: record its revision and clear ``dirty``, without tracking this
    bookkeeping as an edit."""
    with apply_mode():
        _db().execute_sql(
            f"UPDATE {_ident(table)} SET rev = ?, base_rev = ?, dirty = 0 WHERE {where_sql}", (rev, rev, *params))


def tombstones(table: str = "", since_id: int = 0) -> list[dict[str, Any]]:
    cur = _db().execute_sql(
        "SELECT id, table_name, natural_key, rev, deleted_at FROM repl_tombstones "
        "WHERE id > ? AND (? = '' OR table_name = ?) ORDER BY id", (since_id, table, table))
    return [{"id": i, "table": t, "key": json.loads(k), "rev": r, "deleted_at": d}
            for i, t, k, r, d in cur.fetchall()]


def release_tombstones(table: str, up_to_id: int) -> int:
    """The sync owner is done with these tombstones (REPL-020): delete them. Returns how many."""
    cur = _db().execute_sql("DELETE FROM repl_tombstones WHERE table_name = ? AND id <= ?", (table, up_to_id))
    return int(cur.rowcount)


class RevisionIssuer:
    """Issues revisions serially per table on the Master (REPL-080); a spoke never issues one."""

    def __init__(self, is_master: Callable[[], bool]) -> None:
        self._is_master = is_master

    def commit_rev(self, table: str) -> int:
        """The next revision of *table*; revisions are a total order within a table."""
        if not self._is_master():
            raise NotMasterError("only the Master issues revisions")
        db = _db()
        with db.atomic("IMMEDIATE"):
            db.execute_sql("INSERT OR IGNORE INTO repl_revisions (table_name, last_rev) VALUES (?, 0)",
                           (_ident(table),))
            db.execute_sql("UPDATE repl_revisions SET last_rev = last_rev + 1 WHERE table_name = ?", (table,))
            return int(db.execute_sql("SELECT last_rev FROM repl_revisions WHERE table_name = ?",
                                      (table,)).fetchone()[0])

    def current(self, table: str) -> int:
        row = _db().execute_sql("SELECT last_rev FROM repl_revisions WHERE table_name = ?", (table,)).fetchone()
        return int(row[0]) if row else 0


__all__ = ["TRACKED_COLUMNS", "NotMasterError", "RevisionIssuer", "apply_mode", "dirty_rows", "mark_clean",
           "release_tombstones", "reset_apply_mode", "tombstones", "tracking_sql"]
