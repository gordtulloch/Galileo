"""Peewee migrations -- 019_add_schedule_timeline_fields.py.

Adds Schedule-timeline placement/outcome columns to ``scheduler_jobs``
(SCHED-110 ... SCHED-150): ``kind``/``pier_op_kind`` distinguish a
session-backed job from a standalone pier-level operation dropped onto the
Schedule screen's timeline (``galileo.ui.schedule``); ``scheduled_start_utc``/
``scheduled_end_utc``/``duration_minutes`` give it timeline placement; and
``run_state``/``run_log_json`` back the Schedule screen's green/red border
and per-entry Log control.

Plain SQL rather than ``migrator.add_fields``, same reasoning as 018: on any
database where 016 (which created ``scheduler_jobs``) was already applied in
an earlier run, the table predates this migration batch's ORM.
"""

import peewee as pw
from peewee_migrate import Migrator

_NEW_COLUMNS = {
    "kind": "TEXT",
    "pier_op_kind": "TEXT",
    "scheduled_start_utc": "TEXT",
    "scheduled_end_utc": "TEXT",
    "duration_minutes": "REAL",
    "run_state": "TEXT",
    "run_log_json": "TEXT",
}


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    existing = set() if fake else {c.name for c in database.get_columns("scheduler_jobs")}
    for name, sql_type in _NEW_COLUMNS.items():
        if fake or name not in existing:
            migrator.sql(f"ALTER TABLE scheduler_jobs ADD COLUMN {name} {sql_type}")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
