"""Peewee migrations -- 016_add_session_and_scheduler_persistence.py.

``session_templates`` (SES-180/SES-190) and ``scheduler_jobs`` (SCHED-100):
moves Session Template and Scheduler job-queue/progress persistence from ad
hoc JSON files into the shared database, per CLAUDE.md's persistence-
unification policy and the Data Design table (docs/SDD.md Section 5) — both
were tracked as a known gap in docs/SDD.md Sections 4.6a/4.9b and TODO.md.
"""

import peewee as pw


def migrate(migrator, database, fake=False, **kwargs):
    @migrator.create_model
    class SessionTemplateRecord(pw.Model):
        id = pw.AutoField()
        name = pw.TextField(unique=True)
        blocks_json = pw.TextField(default="[]")

        class Meta:
            table_name = "session_templates"

    @migrator.create_model
    class SchedulerJobRecord(pw.Model):
        id = pw.AutoField()
        pier_name = pw.TextField(default="")
        name = pw.TextField()
        target_ra = pw.FloatField(default=0.0)
        target_dec = pw.FloatField(default=0.0)
        priority = pw.IntegerField(default=5)
        frames_captured = pw.IntegerField(default=0)
        total_required = pw.IntegerField(default=0)
        constraints_json = pw.TextField(default="{}")
        startup_json = pw.TextField(default="{}")
        completion_json = pw.TextField(default="{}")

        class Meta:
            table_name = "scheduler_jobs"


def rollback(migrator, database, fake=False, **kwargs):
    migrator.remove_model("scheduler_jobs")
    migrator.remove_model("session_templates")
