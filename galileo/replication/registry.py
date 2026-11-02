# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The replicable-table registry (REPL-030, REPL-040).

A model declares itself replicable with its natural key (what identifies a row on every node),
dependency order, node-local and secret fields and wire converters. NodeConnect replicates whatever
is registered, in dependency order, with no change of its own when a table (including a plugin's)
is added.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class ReplicableSpec:
    table: str
    natural_key: tuple[str, ...]
    to_wire: Callable[[dict[str, Any]], dict[str, Any]]
    from_wire: Callable[[dict[str, Any]], dict[str, Any]]
    depends_on: tuple[str, ...] = ()
    node_local_fields: frozenset[str] = frozenset()
    secret_fields: frozenset[str] = frozenset()
    exclude_row: Callable[[dict[str, Any]], bool] = field(default=lambda row: False)
    # The row's key as it is on every node. Defaults to the natural-key columns; a table linked by
    # database ids supplies names instead, because an id means nothing on another node.
    wire_key: Callable[[dict[str, Any]], list[Any]] | None = None
    # The local row for a wire key (``None`` if absent), used by the apply step.
    find_local: Callable[[list[Any]], dict[str, Any] | None] | None = None

    def key_of(self, row: dict[str, Any]) -> dict[str, Any]:
        """``{natural_key name: value}`` for *row*, the same on every node."""
        values = self.wire_key(row) if self.wire_key else [row[c] for c in self.natural_key]
        return dict(zip(self.natural_key, values, strict=True))


# Tables that hold no configuration (REPL-040): the Library catalog, plus Connect Link's and the
# replication machinery's own state, which is per node by nature.
NOT_CONFIGURATION = frozenset({
    "fitsFile", "fitsSession", "Mapping", "Masters", "VariableStars",
    "link_peers", "link_audit", "scheduler_jobs",
})

_specs: dict[str, ReplicableSpec] = {}


def register(spec: ReplicableSpec) -> None:
    if not spec.natural_key:
        raise RegistryError(f"{spec.table}: a replicable table needs a natural key")
    if spec.table in _specs:
        raise RegistryError(f"{spec.table} is already registered")
    _specs[spec.table] = spec


def unregister(table: str) -> None:
    _specs.pop(table, None)


def get(table: str) -> ReplicableSpec | None:
    return _specs.get(table)


def specs() -> list[ReplicableSpec]:
    """Registered specs, each after the tables it depends on (REPL-030)."""
    ordered: list[ReplicableSpec] = []
    done: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in done:
            return
        if name in visiting:
            raise RegistryError(f"dependency cycle at {name}")
        spec = _specs.get(name)
        if spec is None:
            raise RegistryError(f"{name} is depended on but not registered")
        visiting.add(name)
        for dep in spec.depends_on:
            visit(dep)
        visiting.discard(name)
        done.add(name)
        ordered.append(spec)

    for name in sorted(_specs):
        visit(name)
    return ordered


# -- app_settings, the first replicable table ------------------------------------------------
# Settings of the link itself and of the replication plugin describe *this* node and never move.
NODE_LOCAL_NAMESPACES = frozenset({"connect_link", "plugin.NodeConnect", "plugin.MobileConnect",
                                   "plugin.WebConnect"})


def _settings_to_wire(row: dict[str, Any]) -> dict[str, Any]:
    return {"namespace": row["namespace"], "key": row["key"], "scope": row["scope"],
            "value": json.loads(row["value"]), "modified": row["modified"],
            "rev": row["rev"], "base_rev": row["base_rev"]}


def _settings_from_wire(wire: dict[str, Any]) -> dict[str, Any]:
    return {"namespace": wire["namespace"], "key": wire["key"], "scope": wire.get("scope", ""),
            "value": json.dumps(wire["value"]), "modified": wire.get("modified", 0.0),
            "rev": wire.get("rev", 0), "base_rev": wire.get("base_rev", 0)}


def _settings_find_local(key: list[Any]) -> dict[str, Any] | None:
    from galileo.library.models.base import db
    cur = db.execute_sql("SELECT * FROM app_settings WHERE namespace = ? AND key = ? AND scope = ?", tuple(key))
    found = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], found, strict=True)) if found else None


def register_core() -> None:
    """Register core's own replicable tables; idempotent."""
    if "app_settings" not in _specs:
        register(ReplicableSpec(
            "app_settings", ("namespace", "key", "scope"), _settings_to_wire, _settings_from_wire,
            exclude_row=lambda row: row.get("namespace") in NODE_LOCAL_NAMESPACES,
            wire_key=lambda row: [row["namespace"], row["key"], row["scope"]],
            find_local=_settings_find_local,
        ))
    from galileo.replication.tables import register_equipment
    register_equipment()


def unregistered_configuration_tables(all_tables: set[str]) -> set[str]:
    """Tables that are neither registered, nor declared not-configuration, nor pending (REPL-040)."""
    return all_tables - set(_specs) - NOT_CONFIGURATION


register_core()
