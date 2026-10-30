# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Connect Link audit log (LINK-240) — a core-owned table, retention enforced, no secrets."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import peewee as pw

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 90
_SETTINGS_NS = "connect_link"
_FORBIDDEN_KEY = re.compile(r"token|secret|pass[_-]?phrase|password|guest", re.IGNORECASE)
_DAY_S = 86400.0


@dataclass(frozen=True)
class AuditEvent:
    ts: float
    actor: str
    carrier: str
    plugin: str
    route: str
    outcome: str
    reason: str
    fields: dict[str, Any] = field(default_factory=dict)


def _scrub(fields: dict[str, Any] | None) -> dict[str, Any]:
    """Drop any plugin-defined field whose name suggests a secret (LINK-240: never stored)."""
    return {k: v for k, v in (fields or {}).items() if not _FORBIDDEN_KEY.search(str(k))}


class AuditLog:
    """Writes, queries and prunes ``link_audit``. Writing never raises into the request path."""

    def __init__(self, clock=time.time) -> None:
        self._clock = clock

    def write(
        self, actor: str, plugin: str, route: str, outcome: str, reason: str = "", *,
        carrier: str = "", fields: dict[str, Any] | None = None,
    ) -> bool:
        from galileo.library.models.base import db
        from galileo.library.models.link import LinkAuditRecord
        try:
            if db.database is None:
                return False
            db.connect(reuse_if_open=True)
            LinkAuditRecord.create(
                ts=self._clock(), actor=actor, carrier=carrier, plugin=plugin, route=route,
                outcome=outcome, reason=reason, fields=json.dumps(_scrub(fields), default=str),
            )
            return True
        except Exception:
            logger.warning("Could not write a Connect Link audit event", exc_info=True)
            return False

    def query(self, peer: str = "", since: float | None = None, limit: int = 500) -> list[AuditEvent]:
        """Events newest first, optionally those where *peer* is the actor or the carrier."""
        from galileo.library.models.base import db
        from galileo.library.models.link import LinkAuditRecord as R
        if db.database is None:
            return []
        db.connect(reuse_if_open=True)
        q = R.select().order_by(R.ts.desc(), pw.SQL("id DESC")).limit(limit)
        if peer:
            q = q.where((R.actor == peer) | (R.carrier == peer))
        if since is not None:
            q = q.where(R.ts >= since)
        return [
            AuditEvent(r.ts, r.actor, r.carrier, r.plugin, r.route, r.outcome, r.reason,
                       json.loads(r.fields or "{}"))
            for r in q
        ]

    def retention_days(self) -> int:
        from galileo import settings_store
        try:
            days = int(settings_store.get_setting(_SETTINGS_NS, "audit_retention_days", DEFAULT_RETENTION_DAYS))
        except (TypeError, ValueError):
            return DEFAULT_RETENTION_DAYS
        return days if days > 0 else DEFAULT_RETENTION_DAYS

    def prune(self) -> int:
        """Delete events older than the retention period; returns how many went."""
        from galileo.library.models.base import db
        from galileo.library.models.link import LinkAuditRecord as R
        if db.database is None:
            return 0
        db.connect(reuse_if_open=True)
        cutoff = self._clock() - self.retention_days() * _DAY_S
        return R.delete().where(R.ts < cutoff).execute()
