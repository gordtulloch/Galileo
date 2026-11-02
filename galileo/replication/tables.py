# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Replicable specs for the equipment tables (REPL-030).

Observatories, piers, devices and the rest are linked by database ids, which differ on every node.
On the wire a row is therefore identified by **names** (observatory, pier, then its own key columns)
and its foreign keys are re-resolved to local ids on arrival. A row whose parent is not there yet is
refused with ``RegistryError`` -- the dependency order in the registry makes that a bug, not a race.
"""

from __future__ import annotations

from typing import Any

from galileo.replication.registry import RegistryError, ReplicableSpec, register

_TRACKING = ("modified", "rev", "dirty", "base_rev")


def _x(sql: str, params: tuple = ()) -> list[tuple]:
    from galileo.library.models.base import db
    return db.execute_sql(sql, params).fetchall()


# -- scopes: how a row names its parent -----------------------------------------------------
def _observatory_id(name: Any) -> int | None:
    rows = _x("SELECT id FROM observatories WHERE name = ?", (name,))
    return int(rows[0][0]) if rows else None


def _pier_id(obs: Any, pier: Any) -> int | None:
    rows = _x("SELECT p.id FROM piers p JOIN observatories o ON o.id = p.observatory_id "
              "WHERE o.name = ? AND p.name = ?", (obs, pier))
    return int(rows[0][0]) if rows else None


def _scope_names(scope: str, row: dict[str, Any]) -> list[Any]:
    if scope == "observatory":
        rows = _x("SELECT name FROM observatories WHERE id = ?", (row["observatory_id"],))
        return [rows[0][0]] if rows else [None]
    if scope == "pier":
        rows = _x("SELECT o.name, p.name FROM piers p JOIN observatories o ON o.id = p.observatory_id "
                  "WHERE p.id = ?", (row["pier_id"],))
        return list(rows[0]) if rows else [None, None]
    return []


_SCOPE_LABELS = {"none": (), "observatory": ("observatory",), "pier": ("observatory", "pier")}
_SCOPE_FK = {"observatory": "observatory_id", "pier": "pier_id"}


def _make(table: str, scope: str, own: tuple[str, ...], depends_on: tuple[str, ...],
          node_local: frozenset[str] = frozenset(), secret: frozenset[str] = frozenset()) -> ReplicableSpec:
    fk = _SCOPE_FK.get(scope)
    skip = {"id", *_TRACKING, *node_local, *secret} | ({fk} if fk else set())
    n_scope = len(_SCOPE_LABELS[scope])

    def wire_key(row: dict[str, Any]) -> list[Any]:
        return [*_scope_names(scope, row), *(row[c] for c in own)]

    def to_wire(row: dict[str, Any]) -> dict[str, Any]:
        return {"key": wire_key(row), "fields": {k: v for k, v in row.items() if k not in skip},
                "modified": row.get("modified", 0.0), "rev": row.get("rev", 0), "base_rev": row.get("base_rev", 0)}

    def resolve_scope(parts: list[Any]) -> int | None:
        if scope == "observatory":
            return _observatory_id(parts[0])
        if scope == "pier":
            return _pier_id(parts[0], parts[1])
        return None

    def from_wire(wire: dict[str, Any]) -> dict[str, Any]:
        key = wire["key"]
        row: dict[str, Any] = {k: v for k, v in wire["fields"].items() if k not in skip}
        row.update(zip(own, key[n_scope:], strict=True))
        if fk:
            parent = resolve_scope(key[:n_scope])
            if parent is None:
                raise RegistryError(f"{table}: parent {key[:n_scope]} is not on this node")
            row[fk] = parent
        row.update(modified=wire.get("modified", 0.0), rev=wire.get("rev", 0), base_rev=wire.get("base_rev", 0))
        return row

    def find_local(key: list[Any]) -> dict[str, Any] | None:
        where, params = [], []
        if fk:
            parent = resolve_scope(key[:n_scope])
            if parent is None:
                return None
            where.append(f"{fk} = ?")
            params.append(parent)
        for c, v in zip(own, key[n_scope:], strict=True):
            where.append(f"{c} = ?")
            params.append(v)
        sql = f"SELECT * FROM {table}" + (" WHERE " + " AND ".join(where) if where else "")  # noqa: S608 - identifiers are constants or validated
        from galileo.library.models.base import db
        cur = db.execute_sql(sql, tuple(params))
        names = [d[0] for d in cur.description]
        found = cur.fetchone()
        return dict(zip(names, found, strict=True)) if found else None

    labels = (*_SCOPE_LABELS[scope], *own)
    return ReplicableSpec(table, labels, to_wire, from_wire, depends_on=depends_on,
                          node_local_fields=node_local, secret_fields=secret,
                          wire_key=wire_key, find_local=find_local)


def register_equipment() -> None:
    """Register the equipment tables; idempotent."""
    from galileo.replication import registry
    if registry.get("observatories") is not None:
        return
    obs, pier = ("observatories",), ("piers",)
    for spec in (
        _make("observatories", "none", ("name",), ()),
        _make("piers", "observatory", ("name",), obs),
        _make("device_configs", "pier", ("category", "slot"), pier, node_local=frozenset({"focuser_position"})),
        _make("filter_offsets", "pier", ("filter_name",), pier),
        _make("optical_tubes", "pier", ("position",), pier),
        _make("autofocus_settings", "pier", (), pier),
        # executable paths describe this machine; the Nova key is a secret and never leaves it
        _make("solver_settings", "pier", (), pier,
              node_local=frozenset({"executable", "astrometry_executable", "tetra3_database"}),
              secret=frozenset({"nova_api_key"})),
        _make("horizon_points", "observatory", ("azimuth_deg", "altitude_deg"), obs),
        _make("safety_device_configs", "observatory", ("category", "slot"), obs),
        _make("observatory_safety_rules", "observatory", ("slot", "parameter"), obs),
        _make("session_templates", "none", ("name",), ()),
    ):
        register(spec)
