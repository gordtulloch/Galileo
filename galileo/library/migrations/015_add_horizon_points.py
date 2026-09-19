"""Peewee migrations -- 015_add_horizon_points.py.

``horizon_points``: an Observatory's horizon obstruction table — the altitude below
which the sky is blocked at each uploaded azimuth (Options > Star Atlas). Used to
shade the obstructions on the Star Atlas and to refuse slews into them.

Plain SQL rather than ``create_model``: the foreign key needs the migrator to know the
``observatories`` model, and it doesn't when migration 013 found that table already in
a database that predates migrations.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS horizon_points ("
        "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
        "observatory_id INTEGER NOT NULL REFERENCES observatories (id) ON DELETE CASCADE, "
        "azimuth_deg REAL NOT NULL, "
        "altitude_deg REAL NOT NULL)"
    )
    migrator.sql(
        "CREATE INDEX IF NOT EXISTS horizonpointrecord_observatory_id_azimuth_deg "
        "ON horizon_points (observatory_id, azimuth_deg)"
    )


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    migrator.sql("DROP TABLE IF EXISTS horizon_points")
