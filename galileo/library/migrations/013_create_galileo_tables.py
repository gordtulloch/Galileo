"""Peewee migrations -- 013_create_galileo_tables.py.

Galileo's own tables — observatories, piers, per-Pier device configuration and
optical tubes — alongside the AstroFiler-derived library tables (001-012) in the
one shared database.

Before migrations managed them, ``galileo.library.database.init_db`` created
these with ``create_all`` and patched later columns on by hand, so a developer's
existing ``galileo.db`` may already hold them. Each table is therefore created
only if absent, and the two columns added after the original release
(``optical_tubes.name``, ``device_configs.bayer_pattern``) are added only if
missing.
"""

import peewee as pw
from peewee_migrate import Migrator


def _tables(database):
    return {t.lower() for t in database.get_tables()}


def _columns(database, table):
    return {c.name for c in database.get_columns(table)}


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    # With ``fake`` set, peewee-migrate is replaying an already-applied migration against a mocked
    # database only to rebuild its model state, so declare every model as if none existed.
    existing = set() if fake else _tables(database)

    if "observatories" not in existing:
        @migrator.create_model
        class ObservatoryRecord(pw.Model):
            id = pw.AutoField()
            name = pw.TextField(unique=True)
            latitude = pw.FloatField(null=True)
            longitude = pw.FloatField(null=True)
            timezone = pw.TextField(null=True)
            physical_address = pw.TextField(null=True)
            owner = pw.TextField(null=True)

            class Meta:
                table_name = "observatories"

    if "piers" not in existing:
        @migrator.create_model
        class PierRecord(pw.Model):
            id = pw.AutoField()
            observatory = pw.ForeignKeyField(
                column_name="observatory_id", field="id", model=migrator.orm["observatories"],
                on_delete="CASCADE",
            )
            name = pw.TextField()

            class Meta:
                table_name = "piers"
                indexes = ((("observatory", "name"), True),)

    if "device_configs" not in existing:
        @migrator.create_model
        class DeviceConfigRecord(pw.Model):
            id = pw.AutoField()
            pier = pw.ForeignKeyField(
                column_name="pier_id", field="id", model=migrator.orm["piers"], on_delete="CASCADE",
            )
            category = pw.TextField()
            slot = pw.TextField(default="primary")
            driver = pw.TextField()
            server = pw.TextField()
            port = pw.IntegerField()
            device_name = pw.TextField(null=True)
            pixel_size_um = pw.FloatField(null=True)
            sensor_width_px = pw.IntegerField(null=True)
            sensor_height_px = pw.IntegerField(null=True)
            sensor_name = pw.TextField(null=True)
            bayer_pattern = pw.TextField(default="RGGB")

            class Meta:
                table_name = "device_configs"
                indexes = ((("pier", "category", "slot"), True),)
    elif "bayer_pattern" not in _columns(database, "device_configs"):
        # The migrator only knows tables it created itself, so patch an older table with plain SQL.
        migrator.sql("ALTER TABLE device_configs ADD COLUMN bayer_pattern TEXT NOT NULL DEFAULT 'RGGB'")

    if "optical_tubes" not in existing:
        @migrator.create_model
        class OpticalTubeRecord(pw.Model):
            id = pw.AutoField()
            pier = pw.ForeignKeyField(
                column_name="pier_id", field="id", model=migrator.orm["piers"], on_delete="CASCADE",
            )
            position = pw.IntegerField(default=0)
            name = pw.TextField(default="")
            focal_length_mm = pw.FloatField(default=0.0)
            aperture_mm = pw.FloatField(default=0.0)
            optical_system = pw.TextField(default="Newtonian")
            image_reversed = pw.BooleanField(default=False)
            image_inverted = pw.BooleanField(default=False)
            associated_devices = pw.TextField(default="[]")

            class Meta:
                table_name = "optical_tubes"
                indexes = ((("pier", "position"), True),)
    elif "name" not in _columns(database, "optical_tubes"):
        migrator.sql("ALTER TABLE optical_tubes ADD COLUMN name TEXT NOT NULL DEFAULT ''")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    migrator.remove_model("optical_tubes")
    migrator.remove_model("device_configs")
    migrator.remove_model("piers")
    migrator.remove_model("observatories")
