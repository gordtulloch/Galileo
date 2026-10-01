"""Peewee migrations -- 020_add_observatory_elevation.py.

``observatories.elevation_m``: site elevation above sea level in metres, set
on the Observatory creation screen alongside latitude/longitude. Feeds
``galileo.planning.visibility.ObservingLocation.elevation_m`` (used for the
astropy ``EarthLocation`` height in altitude/visibility calculations), which
previously always defaulted to 0.0 since no Observatory field could set it.

Plain SQL rather than ``migrator.add_fields``, same reasoning as 018's
``max_well_depth``: ``migrator.orm`` only knows the ``observatories`` model
when migration 013 actually created it in *this* batch — on any database
where 013 was already applied in an earlier run, ``observatories`` predates
the migrator and only ever gets patched via raw SQL.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    # With ``fake`` set, peewee-migrate is replaying an already-applied migration against a mocked
    # database only to rebuild its model state, so the column is always declared.
    if fake or "elevation_m" not in {c.name for c in database.get_columns("observatories")}:
        migrator.sql("ALTER TABLE observatories ADD COLUMN elevation_m REAL")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
