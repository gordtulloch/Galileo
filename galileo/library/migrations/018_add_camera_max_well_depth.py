"""Peewee migrations -- 018_add_camera_max_well_depth.py.

``device_configs.max_well_depth``: a camera's full-well capacity in electrons,
set by hand on the Camera page (mirroring ``bayer_pattern``). Feeds the
forthcoming Flat Assistant's target-ADU calculation (CAL-010).

Plain SQL rather than ``migrator.add_fields``: ``migrator.orm`` only knows the
``device_configs`` model when migration 013 actually created it in *this*
batch (see ``peewee_migrate.migrator.ORM``) — on any database where 013 was
already applied in an earlier run, ``device_configs`` predates the migrator
and only ever gets patched via raw SQL, same reasoning as 013's own
``bayer_pattern`` column and 017's new tables.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    # With ``fake`` set, peewee-migrate is replaying an already-applied migration against a mocked
    # database only to rebuild its model state, so the column is always declared.
    if fake or "max_well_depth" not in {c.name for c in database.get_columns("device_configs")}:
        migrator.sql("ALTER TABLE device_configs ADD COLUMN max_well_depth INTEGER")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
