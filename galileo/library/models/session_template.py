# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Persisted session templates (SES-180/SES-190).

A reusable, named block-list procedure saved from a Sessions screen region
(``galileo.ui.sessions.SessionRegion.save_as_template``) with its Target block
(if first) generalized to a placeholder. ``blocks_json`` mirrors the same
``{class name: fields}`` shape ``SessionRegion.save()`` already uses for a
``.gses`` file — this table just replaces the JSON *file* a template used to
be written to, not the block encoding itself.
"""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class SessionTemplateRecord(BaseModel):
    """One saved session template (SES-180)."""

    name = pw.TextField(unique=True)
    blocks_json = pw.TextField(default="[]")

    class Meta:
        table_name = "session_templates"
