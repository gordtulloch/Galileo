# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Peewee ORM base model for Galileo (adapted from AstroFiler)."""

from __future__ import annotations

from typing import ClassVar

import peewee as pw

# The database instance is configured at application startup via
# ``galileo.library.database.init_db(path)``.
db = pw.SqliteDatabase(None, pragmas={"journal_mode": "wal", "foreign_keys": 1})


class BaseModel(pw.Model):
    """Shared Peewee base model; all tables use the same database instance."""

    # Declared for type checkers only (no value, so Peewee's metaclass ignores them): the implicit ``id``
    # primary key most tables get, and the per-model ``DoesNotExist`` exception Peewee creates.
    id: int
    DoesNotExist: ClassVar[type[Exception]]

    class Meta:
        database = db
