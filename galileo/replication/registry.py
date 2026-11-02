# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The replicable-table registry (REPL-030, REPL-040).

A model declares itself replicable with its natural key, its dependency order, the fields that stay on
the node and those that are secret, and the converters to and from the wire form. ``specs()`` returns
them in dependency order. A table registered later — including one from a plugin — is replicated with
no change to the consumer.

``unclassified_tables`` backs the test that keeps "complete" true as Galileo grows: every table of the
database must be registered, on :data:`NOT_CONFIGURATION`, or — visibly, until its spec is written — on
:data:`PENDING_REGISTRATION`.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

# Tables that hold no configuration: the Library catalog, node-local security data and infrastructure.
NOT_CONFIGURATION = frozenset({
    "fitsfile", "fitssession", "mapping", "Masters", "VariableStars",          # the Library catalog
    "link_peers", "link_audit",                                                # node-local: peers and audit
    "migratehistory", "sqlite_sequence",                                       # schema bookkeeping
    "repl_state", "repl_revisions", "repl_tombstones",                         # replication bookkeeping
    "sync_outbox", "sync_inbox", "sync_snapshots", "sync_run_reports", "sync_transfer_queue",
    "sync_peer_state",
})

# Configuration tables whose ReplicableSpec has not been written yet. Replication of these waits for it;
# removing a name here means registering it (with a numbered migration for its tracking columns).
PENDING_REGISTRATION = frozenset({"scheduler_jobs"})   # the scheduler is being reworked

Row = dict[str, Any]

# ``app_settings`` namespaces that describe this node rather than the observatory.
NODE_LOCAL_NAMESPACES = ("node", "connect_link", "plugin.NodeConnect", "plugin.MobileConnect", "plugin.WebConnect")


def is_node_local_namespace(namespace: str) -> bool:
    """A namespace that is node-local, or a dotted sub-namespace of one (``connect_link.x``)."""
    return any(namespace == n or namespace.startswith(n + ".") for n in NODE_LOCAL_NAMESPACES)


class RegistryError(ValueError):
    """A registration the registry refuses."""


def _identity(row: Row) -> Row:
    return dict(row)


@dataclass(frozen=True)
class ReplicableSpec:
    table: str
    natural_key: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    node_local_fields: frozenset[str] = frozenset()
    secret_fields: frozenset[str] = frozenset()
    to_wire: Callable[[Row], Row] = field(default=_identity, compare=False)
    from_wire: Callable[[Row], Row] = field(default=_identity, compare=False)
    # Rows that belong to one node (for example a plugin's own pairing state) and never replicate.
    row_filter: Callable[[Row], bool] = field(default=lambda row: True, compare=False)

    def key_of(self, row: Row) -> str:
        """The natural key of a row as canonical JSON, the same form tombstones use."""
        return json.dumps([row[c] for c in self.natural_key])

    def replicates(self, row: Row) -> bool:
        return bool(self.row_filter(row))

    def wire(self, row: Row, include_secrets: bool = False) -> Row:
        """The row as sent to a peer: node-local and (unless asked) secret fields removed, bookkeeping
        columns dropped, then the converter applied."""
        drop = set(self.node_local_fields) | (set() if include_secrets else set(self.secret_fields))
        drop |= {"id", "dirty", "base_rev"}
        return self.to_wire({k: v for k, v in row.items() if k not in drop})


class ReplicableRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ReplicableSpec] = {}
        self._lock = threading.Lock()

    def register(self, spec: ReplicableSpec) -> None:
        if not spec.natural_key:
            raise RegistryError(f"{spec.table}: a replicable table needs a natural key")
        if spec.table in NOT_CONFIGURATION:
            raise RegistryError(f"{spec.table} is on the not-configuration list")
        with self._lock:
            if spec.table in self._specs:
                raise RegistryError(f"{spec.table} is already registered")
            self._specs[spec.table] = spec

    def unregister(self, table: str) -> None:
        with self._lock:
            self._specs.pop(table, None)

    def get(self, table: str) -> ReplicableSpec | None:
        return self._specs.get(table)

    def specs(self) -> list[ReplicableSpec]:
        """Every spec in dependency order (a table after the tables it depends on); ties keep the order
        of registration. A missing dependency or a cycle is an error."""
        with self._lock:
            specs = dict(self._specs)
        ordered: list[ReplicableSpec] = []
        done: set[str] = set()
        visiting: set[str] = set()

        def visit(table: str) -> None:
            if table in done:
                return
            if table in visiting:
                raise RegistryError(f"dependency cycle through {table}")
            spec = specs.get(table)
            if spec is None:
                raise RegistryError(f"{table} is a dependency but is not registered")
            visiting.add(table)
            for dep in spec.depends_on:
                visit(dep)
            visiting.discard(table)
            done.add(table)
            ordered.append(spec)

        for table in specs:
            visit(table)
        return ordered

    def unclassified_tables(self, tables: Iterable[str]) -> list[str]:
        """Tables that are registered, not configuration, or pending nowhere — the REPL-040 failures."""
        known = set(self._specs) | NOT_CONFIGURATION | PENDING_REGISTRATION
        return sorted(t for t in tables if t not in known)

    def pending(self, tables: Iterable[str]) -> list[str]:
        """Configuration tables present in the database that are not yet replicable."""
        return sorted(t for t in tables if t in PENDING_REGISTRATION and t not in self._specs)


registry = ReplicableRegistry()


def register_defaults(target: ReplicableRegistry | None = None) -> None:
    """Register core's own replicable tables (``app_settings`` first)."""
    reg = target or registry
    if reg.get("app_settings") is None:
        reg.register(ReplicableSpec(
            "app_settings", ("namespace", "key", "scope"),
            row_filter=lambda row: not is_node_local_namespace(str(row.get("namespace", ""))),
        ))
    from galileo.replication.specs import register_config_specs
    register_config_specs(reg)


__all__ = [
    "NODE_LOCAL_NAMESPACES",
    "NOT_CONFIGURATION",
    "PENDING_REGISTRATION",
    "RegistryError",
    "ReplicableRegistry",
    "ReplicableSpec",
    "register_defaults",
    "registry",
]
