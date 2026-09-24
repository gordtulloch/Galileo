"""Peewee migrations -- 017_add_autofocus_and_solver_settings.py.

``autofocus_settings`` (FOC-070) and ``solver_settings`` (PLT-060): one row per
Pier holding the Options > Focus / Options > Solve pages' saved defaults, in
the shared database per CLAUDE.md's persistence-unification policy.
"""

import peewee as pw


def migrate(migrator, database, fake=False, **kwargs):
    @migrator.create_model
    class AutofocusSettingsRecord(pw.Model):
        id = pw.AutoField()
        pier = pw.ForeignKeyField(
            column_name="pier_id", field="id", model=migrator.orm["piers"],
            on_delete="CASCADE", unique=True,
        )
        step_size = pw.IntegerField(default=200)
        num_points = pw.IntegerField(default=9)
        exposure_s = pw.FloatField(default=3.0)
        backlash_compensation = pw.IntegerField(default=0)

        class Meta:
            table_name = "autofocus_settings"

    @migrator.create_model
    class SolverSettingsRecord(pw.Model):
        id = pw.AutoField()
        pier = pw.ForeignKeyField(
            column_name="pier_id", field="id", model=migrator.orm["piers"],
            on_delete="CASCADE", unique=True,
        )
        executable = pw.TextField(null=True)
        fov_hint_deg = pw.FloatField(default=0.0)
        search_radius_deg = pw.FloatField(default=30.0)
        downsample = pw.IntegerField(default=0)

        class Meta:
            table_name = "solver_settings"


def rollback(migrator, database, fake=False, **kwargs):
    migrator.remove_model("solver_settings")
    migrator.remove_model("autofocus_settings")
