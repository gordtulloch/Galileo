# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Version handshake (LINK-080).

Each side states its Galileo version, plugin-API version, schema (migration) level and Connect Link
protocol version. A different protocol version is refused; a different schema level *restricts* the
exchange to what does not depend on the two databases agreeing (``control``, ``view``) — a view
client has no stake in the other node's schema, but replicating data or configuration across
different schemas would corrupt it. Either way the message is written for a person. A plugin may add
its own payload (for example capability limits) and its own verdict.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from galileo.connect_link.permissions import PAIRED_PERMISSIONS

OK, RESTRICTED, REFUSED = "ok", "restricted", "refused"
SCHEMA_DEPENDENT = frozenset({"config.read", "config.write", "data.push", "data.pull"})

# ``extension(peer_payload) -> (own_payload, verdict_or_None, message)``
Extension = Callable[[dict[str, Any]], "ExtensionResult"]


@dataclass(frozen=True)
class ExtensionResult:
    payload: dict[str, Any]
    verdict: str = OK
    message: str = ""


@dataclass(frozen=True)
class Versions:
    galileo: str
    plugin_api: str
    schema: int
    protocol: int

    def as_dict(self) -> dict[str, Any]:
        return {"galileo": self.galileo, "plugin_api": self.plugin_api,
                "schema": self.schema, "protocol": self.protocol}


@dataclass(frozen=True)
class HandshakeResult:
    verdict: str
    message: str
    allowed: frozenset[str]
    node: dict[str, Any]
    plugin: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "message": self.message, "allowed": sorted(self.allowed),
                "node": self.node, "plugin": self.plugin}


def schema_level(migration_name: str) -> int:
    """``'033_add_connect_link'`` -> ``33``; ``'none'`` -> ``0``."""
    m = re.match(r"^(\d+)", migration_name or "")
    return int(m.group(1)) if m else 0


class Handshake:
    def __init__(self, versions: Callable[[], Versions]) -> None:
        self._versions = versions
        self._extensions: dict[str, Extension] = {}

    def extend(self, plugin: str, extension: Extension) -> None:
        self._extensions[plugin.strip().lower()] = extension

    def remove_extension(self, plugin: str) -> None:
        self._extensions.pop(plugin.strip().lower(), None)

    def evaluate(self, plugin: str, theirs: dict[str, Any]) -> HandshakeResult:
        ours = self._versions()
        node = ours.as_dict()
        try:
            their_protocol, their_schema = int(theirs["protocol"]), int(theirs["schema"])
        except (KeyError, TypeError, ValueError):
            return HandshakeResult(
                REFUSED, "The other side did not say which Connect Link and database versions it uses.",
                frozenset(), node)

        verdict, messages, allowed = OK, [], set(PAIRED_PERMISSIONS)
        if their_protocol != ours.protocol:
            newer = "newer" if their_protocol > ours.protocol else "older"
            return HandshakeResult(
                REFUSED, f"The other side uses a {newer} Connect Link protocol ({their_protocol}; this "
                f"node uses {ours.protocol}). Update Galileo on whichever is older.", frozenset(), node)
        if their_schema != ours.schema:
            verdict, allowed = RESTRICTED, allowed - SCHEMA_DEPENDENT
            newer = "newer" if their_schema > ours.schema else "older"
            messages.append(
                f"The other side's database is {newer} (level {their_schema}; this node is {ours.schema}), "
                "so only control and viewing are available until both are updated to the same version.")

        extra: dict[str, Any] = {}
        ext = self._extensions.get(plugin.strip().lower())
        if ext is not None:
            result = ext(dict(theirs.get("plugin") or {}))
            extra = result.payload
            if result.verdict == REFUSED:
                return HandshakeResult(REFUSED, result.message or "The plugin refused the exchange.",
                                       frozenset(), node, extra)
            if result.verdict == RESTRICTED:
                verdict, allowed = RESTRICTED, allowed - SCHEMA_DEPENDENT
            if result.message:
                messages.append(result.message)
        return HandshakeResult(verdict, " ".join(messages), frozenset(allowed), node, extra)


__all__ = ["OK", "REFUSED", "RESTRICTED", "SCHEMA_DEPENDENT", "ExtensionResult", "Handshake",
           "HandshakeResult", "Versions", "schema_level"]
