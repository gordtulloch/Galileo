"""Peewee migrations -- 021_add_pier_connect_on_startup.py.

``piers.connect_on_startup``: whether this Pier's configured devices should be
auto-connected when Galileo starts, set from the checkbox next to the top
bar's Pier selector. Defaults to true so existing Piers keep today's
behaviour (the Pier selected at start-up auto-connects) unchanged; unchecking
it replaces that with a manual "Connect" button next to the checkbox.

Plain SQL rather than ``migrator.add_fields``, same reasoning as 018's
``max_well_depth``/020's ``elevation_m``: ``migrator.orm`` only knows the
``piers`` model when migration 013 actually created it in *this* batch -- on
any database where 013 was already applied in an earlier run, ``piers``
predates the migrator and only ever gets patched via raw SQL.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    # With ``fake`` set, peewee-migrate is replaying an already-applied migration against a mocked
    # database only to rebuild its model state, so the column is always declared.
    if fake or "connect_on_startup" not in {c.name for c in database.get_columns("piers")}:
        migrator.sql("ALTER TABLE piers ADD COLUMN connect_on_startup INTEGER NOT NULL DEFAULT 1")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
