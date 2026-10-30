# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Connect Link's peer and audit rows (migration 033; LINK-030, LINK-240)."""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class LinkPeerRecord(BaseModel):
    """A paired peer or a plugin's service credential. ``token_hash`` is a salted scrypt hash."""

    peer_id = pw.TextField(unique=True)
    plugin = pw.TextField()
    name = pw.TextField()
    kind = pw.TextField(default="")
    platform = pw.TextField(default="")
    is_service = pw.IntegerField(default=0)
    permissions = pw.TextField(default="[]")
    token_salt = pw.TextField(default="")
    token_hash = pw.TextField(default="")
    cert_fingerprint = pw.TextField(default="")
    metadata = pw.TextField(default="{}")
    created_at = pw.FloatField()
    expires_at = pw.FloatField(null=True)
    revoked_at = pw.FloatField(null=True)
    last_contact = pw.FloatField(null=True)

    class Meta:
        table_name = "link_peers"


class LinkAuditRecord(BaseModel):
    """One audit event. Never holds a token, secret, passphrase or guest identifier."""

    ts = pw.FloatField(index=True)
    actor = pw.TextField(default="")
    carrier = pw.TextField(default="")
    plugin = pw.TextField(default="")
    route = pw.TextField(default="")
    outcome = pw.TextField(default="")
    reason = pw.TextField(default="")
    fields = pw.TextField(default="{}")

    class Meta:
        table_name = "link_audit"
        indexes = ((("actor", "ts"), False),)
