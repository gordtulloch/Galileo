# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Change tracking access (REPL-010, REPL-020, REPL-080).

The columns (``modified``, ``rev``, ``dirty``, ``base_rev``) and tombstones are maintained by SQLite
triggers installed by migration 034, so every write path is tracked. This module is the read/apply
side: list what changed, write received rows without marking them dirty, mark rows clean at a
revision, read and release tombstones, and (Master only) issue revisions.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Callable, Iterator
from typing import Any

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class NotMasterError(RuntimeError):
    """A spoke tried to issue a revision (REPL-080)."""


def _never() -> bool:
    return False


_is_master: Callable[[], bool] = _never


def configure(*, is_master: Callable[[], bool]) -> None:
    """Tell the module whether this node is the Master (NodeConnect sets this from its role)."""
    global _is_master
    _is_master = is_master


def _db():
    from galileo.library.models.base import db
    return db


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"not a table or column name: {name!r}")
    return name


@contextlib.contextmanager
def applying() -> Iterator[None]:
    """Write inside this block without marking rows dirty or leaving tombstones: used when applying
    rows received from the Master, in one transaction with them."""
    db = _db()
    with db.atomic():
        db.execute_sql("UPDATE repl_state SET suppress = 1 WHERE id = 1")
        try:
            yield
        finally:
            db.execute_sql("UPDATE repl_state SET suppress = 0 WHERE id = 1")


def _rows(cursor) -> list[dict[str, Any]]:
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, r, strict=True)) for r in cursor.fetchall()]


def dirty_rows(table: str) -> list[dict[str, Any]]:
    """Every row of *table* with a local change not yet acknowledged by the Master."""
    return _rows(_db().execute_sql(f"SELECT * FROM {_ident(table)} WHERE dirty = 1"))  # noqa: S608 - identifiers are constants or validated


def mark_clean(table: str, key: dict[str, Any], rev: int) -> bool:
    """Record that the Master accepted the row at *rev*: clear ``dirty`` and re-base. A row edited
    again since the push (``modified`` moved) is left dirty by the caller passing its own check."""
    cols = [_ident(c) for c in key]
    where = " AND ".join(f"{c} = ?" for c in cols)
    with applying():
        cur = _db().execute_sql(
            f"UPDATE {_ident(table)} SET dirty = 0, rev = ?, base_rev = ? WHERE {where}",  # noqa: S608 - identifiers are constants or validated
            (rev, rev, *key.values()))
    return bool(cur.rowcount)


def tombstones(table: str, after_id: int = 0, *, committed_after_rev: int | None = None) -> list[dict[str, Any]]:
    """Tombstones of *table* with id above *after_id*. With *committed_after_rev* (the Master's view
    for a spoke asking "what changed since revision N") only committed ones above that revision."""
    sql = ("SELECT id, table_name, natural_key, rev, deleted_at, committed FROM repl_tombstones "
           "WHERE table_name = ? AND id > ?")
    params: list[Any] = [_ident(table), after_id]
    if committed_after_rev is not None:
        sql += " AND committed = 1 AND rev > ?"
        params.append(committed_after_rev)
    rows = _rows(_db().execute_sql(sql + " ORDER BY id", tuple(params)))
    for r in rows:
        r["natural_key"] = json.loads(r["natural_key"])
    return rows


def commit_tombstones(table: str) -> int:
    """Master only: give each uncommitted tombstone of *table* a revision from the table's counter, so
    a deletion is a change in the same total order as an edit. Returns how many were committed."""
    if not _is_master():
        raise NotMasterError("only the Master issues revisions")
    db = _db()
    n = 0
    with db.atomic():
        for row in _rows(db.execute_sql("SELECT id FROM repl_tombstones WHERE table_name = ? AND committed = 0 "
                                        "ORDER BY id", (_ident(table),))):
            db.execute_sql("UPDATE repl_tombstones SET rev = ?, committed = 1 WHERE id = ?",
                           (commit_rev(table), row["id"]))
            n += 1
    return n


def release_tombstones(table: str, up_to_id: int) -> int:
    """Forget tombstones up to *up_to_id* once every node holding the table has seen them (REPL-070)."""
    cur = _db().execute_sql("DELETE FROM repl_tombstones WHERE table_name = ? AND id <= ?",
                            (_ident(table), up_to_id))
    return int(cur.rowcount)


def record_tombstone(table: str, natural_key: list[Any], rev: int) -> None:
    """Master only: record an already-committed deletion (one arbitrated from a node, whose row was
    removed while the triggers stood down) so spokes asking for changes since an earlier revision
    learn of it."""
    if not _is_master():
        raise NotMasterError("only the Master issues revisions")
    _db().execute_sql("INSERT INTO repl_tombstones (table_name, natural_key, rev, deleted_at, committed) "
                      "VALUES (?, ?, ?, (julianday('now') - 2440587.5) * 86400.0, 1)",
                      (_ident(table), json.dumps(natural_key), rev))


def drop_tombstone(tombstone_id: int) -> bool:
    """Forget one tombstone (a spoke, once the Master has accepted its deletion)."""
    return bool(_db().execute_sql("DELETE FROM repl_tombstones WHERE id = ?", (tombstone_id,)).rowcount)


def release_committed(table: str, up_to_rev: int) -> int:
    """Release committed tombstones at or below *up_to_rev*, the revision every paired node has
    acknowledged (NCON-180)."""
    return int(_db().execute_sql("DELETE FROM repl_tombstones WHERE table_name = ? AND committed = 1 AND rev <= ?",
                                 (_ident(table), up_to_rev)).rowcount)


def commit_rev(table: str) -> int:
    """Issue the next revision of *table* (Master only). Serial per table, so a revision is a total
    order within the table (REPL-080)."""
    if not _is_master():
        raise NotMasterError("only the Master issues revisions")
    db = _db()
    with db.atomic():
        db.execute_sql("INSERT OR IGNORE INTO repl_revs (table_name, rev) VALUES (?, 0)", (_ident(table),))
        db.execute_sql("UPDATE repl_revs SET rev = rev + 1 WHERE table_name = ?", (table,))
        return int(db.execute_sql("SELECT rev FROM repl_revs WHERE table_name = ?", (table,)).fetchone()[0])


def current_rev(table: str) -> int:
    row = _db().execute_sql("SELECT rev FROM repl_revs WHERE table_name = ?", (_ident(table),)).fetchone()
    return int(row[0]) if row else 0
