"""Persisted Observatory/Pier master records (OBS settings persistence).

Distinct from the live runtime ``galileo.observatory.Observatory``/``Pier``
classes, which hold in-process device pools and safety/dome wiring for a
running session and are never serialized — these are the on-disk settings a
user configures once (name, location, ownership) and selects between across
restarts, via the Observatory/Pier selectors in the UI's top bar.
"""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class ObservatoryRecord(BaseModel):
    """One saved Observatory configuration."""

    name = pw.TextField(unique=True)
    latitude = pw.FloatField(null=True)
    longitude = pw.FloatField(null=True)
    timezone = pw.TextField(null=True)
    physical_address = pw.TextField(null=True)
    owner = pw.TextField(null=True)

    class Meta:
        table_name = "observatories"


class PierRecord(BaseModel):
    """One saved Pier configuration, scoped to its owning Observatory."""

    observatory = pw.ForeignKeyField(ObservatoryRecord, backref="piers", on_delete="CASCADE")
    name = pw.TextField()

    class Meta:
        table_name = "piers"
        indexes = ((("observatory", "name"), True),)
