"""Peewee migrations -- 029_add_solver_tetra3_database.py.

``solver_settings`` gains the path of the tetra3 star-pattern database (PLT-060); blank means the
one tetra3 ships with. Plain SQL, for the same reason as 027.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    existing = set() if fake else {c.name for c in database.get_columns("solver_settings")}
    if "tetra3_database" not in existing:
        migrator.sql("ALTER TABLE solver_settings ADD COLUMN tetra3_database TEXT")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
