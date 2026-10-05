"""Peewee migrations -- 022_add_flat_panel_type.py.

``device_configs.panel_type``: which kind of flat panel is configured —
``"Flat Panel"`` (an Alnitak Flip-Flat-style motorized dust cap + light, with
both cover park/unpark and light controls) or ``"Observatory Panel"`` (a
fixed panel built into the observatory, light-only, with no motorized cover)
— the same two names ``galileo.calibration.FLAT_METHODS`` uses for these
sources on the Imaging page's Flats Assistant — set by hand on the Flat
Panel page (EQP-FP-010). Defaults to ``"Flat Panel"`` so existing Flat Panel
configs keep today's full set of controls.

Plain SQL rather than ``migrator.add_fields``, same reasoning as 018's
``max_well_depth``: ``migrator.orm`` only knows the ``device_configs`` model
when migration 013 actually created it in *this* batch -- on any database
where 013 was already applied in an earlier run, ``device_configs`` predates
the migrator and only ever gets patched via raw SQL.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    # With ``fake`` set, peewee-migrate is replaying an already-applied migration against a mocked
    # database only to rebuild its model state, so the column is always declared.
    if fake or "panel_type" not in {c.name for c in database.get_columns("device_configs")}:
        migrator.sql("ALTER TABLE device_configs ADD COLUMN panel_type TEXT NOT NULL DEFAULT 'Flat Panel'")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
