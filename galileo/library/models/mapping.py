# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Repository-to-filesystem path mapping model."""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class PathMapping(BaseModel):
    """Maps an original file path to its organized repository path."""

    id = pw.AutoField()
    original_path = pw.TextField(index=True)
    repo_path = pw.TextField(null=True)
    object_name = pw.TextField(null=True)
    date_str = pw.TextField(null=True)

    class Meta:
        table_name = "path_mappings"
