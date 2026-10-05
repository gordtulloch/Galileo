"""Peewee migrations -- 023_add_filter_offsets.py.

``filter_offsets`` (EQP-FW-020, FOC-060): one row per Pier+filter holding the
Focus screen's Filter Offsets dialog's four measured best-focus positions and
the resulting offset relative to the Pier's Primary filter, in the shared
database per CLAUDE.md's persistence-unification policy.

Plain SQL rather than ``create_model``, same reasoning as migration 017's
autofocus_settings/solver_settings: this table's foreign key references
``piers``, and ``migrator.orm["piers"]`` KeyErrors on any database where
migration 013 already applied in an earlier run (i.e. on every real upgrade,
as opposed to a from-scratch install where 013 and this migration both run
together).
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS filter_offsets ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "pier_id INTEGER NOT NULL REFERENCES piers (id) ON DELETE CASCADE, "
        "filter_name TEXT NOT NULL, "
        "is_primary INTEGER NOT NULL DEFAULT 0, "
        "measurement_1 INTEGER, "
        "measurement_2 INTEGER, "
        "measurement_3 INTEGER, "
        "measurement_4 INTEGER, "
        "offset_steps INTEGER)"
    )
    migrator.sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS filteroffsetrecord_pier_id_filter_name "
        "ON filter_offsets (pier_id, filter_name)"
    )


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql("DROP TABLE IF EXISTS filter_offsets")
