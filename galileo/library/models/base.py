"""Peewee ORM base model for Galileo (adapted from AstroFiler)."""

from __future__ import annotations

import peewee as pw

# The database instance is configured at application startup via
# ``galileo.library.database.init_db(path)``.
db = pw.SqliteDatabase(None, pragmas={"journal_mode": "wal", "foreign_keys": 1})


class BaseModel(pw.Model):
    """Shared Peewee base model; all tables use the same database instance."""

    class Meta:
        database = db
