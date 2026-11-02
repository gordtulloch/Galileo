# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 035_replicate_equipment_tables.py.

Change tracking (see 034) for the configuration tables that are linked by database ids: the
observatory, pier, device, optical-tube, filter-offset, horizon, solver, autofocus and safety tables
and session templates. Each gains ``modified``, ``rev``, ``dirty`` and ``base_rev`` and the same three
triggers as ``app_settings``.

A row's id means nothing on another node, so a deletion's tombstone records the row's **names** (for
example ``[observatory, pier, category, slot]``), looked up by the trigger. A row removed because its
parent was removed (a cascade) leaves no tombstone of its own -- the parent's tombstone covers it.
``device_configs.focuser_position`` is runtime state and does not mark a row dirty.
"""

import peewee as pw
from peewee_migrate import Migrator

_NOW = "(julianday('now') - 2440587.5) * 86400.0"
_GUARD = "(SELECT suppress FROM repl_state WHERE id = 1) = 0"
_TRACKING = ("modified", "rev", "dirty", "base_rev")
_COLUMNS = {
    "modified": "REAL NOT NULL DEFAULT 0",
    "rev": "INTEGER NOT NULL DEFAULT 0",
    "dirty": "INTEGER NOT NULL DEFAULT 0",
    "base_rev": "INTEGER NOT NULL DEFAULT 0",
}

# table -> (scope, own key columns, columns that do not mark the row dirty)
_TABLES = {
    "observatories": ("none", ("name",), ()),
    "piers": ("observatory", ("name",), ()),
    "device_configs": ("pier", ("category", "slot"), ("focuser_position",)),
    "filter_offsets": ("pier", ("filter_name",), ()),
    "optical_tubes": ("pier", ("position",), ()),
    "autofocus_settings": ("pier", (), ()),
    "solver_settings": ("pier", (), ()),
    "horizon_points": ("observatory", ("azimuth_deg", "altitude_deg"), ()),
    "safety_device_configs": ("observatory", ("category", "slot"), ()),
    "observatory_safety_rules": ("observatory", ("slot", "parameter"), ()),
    "session_templates": ("none", ("name",), ()),
}


def _key_parts(scope: str, own: tuple[str, ...], row: str) -> list[str]:
    parts: list[str] = []
    if scope == "observatory":
        parts.append(f"(SELECT name FROM observatories WHERE id = {row}.observatory_id)")  # noqa: S608 - identifiers are constants or validated
    elif scope == "pier":
        parts.append("(SELECT o.name FROM observatories o JOIN piers p ON p.observatory_id = o.id "  # noqa: S608 - identifiers are constants or validated
                     f"WHERE p.id = {row}.pier_id)")
        parts.append(f"(SELECT name FROM piers WHERE id = {row}.pier_id)")  # noqa: S608 - identifiers are constants or validated
    parts.extend(f"{row}.{c}" for c in own)
    return parts


def _parent_exists(scope: str) -> str:
    if scope == "observatory":
        return "EXISTS (SELECT 1 FROM observatories WHERE id = OLD.observatory_id)"
    if scope == "pier":
        return "EXISTS (SELECT 1 FROM piers WHERE id = OLD.pier_id)"
    return "1"


def _triggers(table: str, scope: str, own: tuple[str, ...], data_cols: list[str]) -> list[str]:
    changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in data_cols) or "0"
    return [
        f"CREATE TRIGGER IF NOT EXISTS {table}_repl_ins AFTER INSERT ON {table} WHEN {_GUARD} BEGIN "  # noqa: S608 - identifiers are constants or validated
        f"UPDATE {table} SET modified = {_NOW}, dirty = 1, base_rev = 0 WHERE id = NEW.id; END",
        f"CREATE TRIGGER IF NOT EXISTS {table}_repl_upd AFTER UPDATE ON {table} WHEN {_GUARD} AND ({changed}) BEGIN "  # noqa: S608 - identifiers are constants or validated
        f"UPDATE {table} SET modified = {_NOW}, "
        f"base_rev = CASE WHEN OLD.dirty = 1 THEN OLD.base_rev ELSE OLD.rev END, dirty = 1 WHERE id = NEW.id; END",
        f"CREATE TRIGGER IF NOT EXISTS {table}_repl_del AFTER DELETE ON {table} WHEN {_GUARD} AND {_parent_exists(scope)} BEGIN "  # noqa: S608 - identifiers are constants or validated
        "INSERT INTO repl_tombstones (table_name, natural_key, rev, deleted_at) "
        f"VALUES ('{table}', json_array({', '.join(_key_parts(scope, own, 'OLD'))}), OLD.rev, {_NOW}); END",
    ]


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    for table, (scope, own, ignore) in _TABLES.items():
        existing = set() if fake else {c.name for c in database.get_columns(table)}
        added = False
        for name, ddl in _COLUMNS.items():
            if name not in existing:
                migrator.sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                added = True
        if added:                                       # rows that predate tracking go out on the first sync
            migrator.sql(f"UPDATE {table} SET dirty = 1, modified = {_NOW}")  # noqa: S608 - identifiers are constants or validated
        data_cols = [c for c in sorted(existing) if c != "id" and c not in _TRACKING and c not in ignore]
        if fake:
            continue
        for stmt in _triggers(table, scope, own, data_cols):
            migrator.sql(stmt)


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    for table in _TABLES:
        for suffix in ("ins", "upd", "del"):
            migrator.sql(f"DROP TRIGGER IF EXISTS {table}_repl_{suffix}")
