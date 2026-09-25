"""Peewee migrations -- 017_add_autofocus_and_solver_settings.py.

``autofocus_settings`` (FOC-070) and ``solver_settings`` (PLT-060): one row per
Pier holding the Options > Focus / Options > Solve pages' saved defaults, in
the shared database per CLAUDE.md's persistence-unification policy.

Plain SQL rather than ``create_model``: ``migrator.orm`` is only populated by
migrations that actually run in *this* batch (see ``peewee_migrate.migrator.ORM``),
not by the live database schema, so ``migrator.orm["piers"]`` KeyErrors on any
database where migration 013 was already applied in an earlier run — i.e. on
every real upgrade, as opposed to a from-scratch install where 013 and 017 both
run together. Same reasoning as migration 015's ``horizon_points`` table.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS autofocus_settings ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "pier_id INTEGER NOT NULL REFERENCES piers (id) ON DELETE CASCADE, "
        "step_size INTEGER NOT NULL DEFAULT 200, "
        "num_points INTEGER NOT NULL DEFAULT 9, "
        "exposure_s REAL NOT NULL DEFAULT 3.0, "
        "backlash_compensation INTEGER NOT NULL DEFAULT 0)"
    )
    migrator.sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS autofocussettingsrecord_pier_id "
        "ON autofocus_settings (pier_id)"
    )
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS solver_settings ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "pier_id INTEGER NOT NULL REFERENCES piers (id) ON DELETE CASCADE, "
        "executable TEXT, "
        "fov_hint_deg REAL NOT NULL DEFAULT 0.0, "
        "search_radius_deg REAL NOT NULL DEFAULT 30.0, "
        "downsample INTEGER NOT NULL DEFAULT 0)"
    )
    migrator.sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS solversettingsrecord_pier_id "
        "ON solver_settings (pier_id)"
    )


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql("DROP TABLE IF EXISTS solver_settings")
    migrator.sql("DROP TABLE IF EXISTS autofocus_settings")
