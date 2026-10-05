"""Peewee migrations -- 022_add_observatory_notification_fields.py.

``observatories.notification_type``: how the operator wants to be notified
("Email", "Text", "Both", or NULL for none).
``observatories.email_address``: the address external-notification emails go to.
``observatories.cell_number``: the cell number SMS alerts go to.

Plain SQL, same reasoning as earlier column-add migrations: ``migrator.orm``
only knows the ``observatories`` model when migration 013 created it in this
batch — on any DB where 013 was applied in an earlier run, the table predates
the migrator and must be patched via raw SQL.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    existing = {c.name for c in database.get_columns("observatories")}
    if fake or "notification_type" not in existing:
        migrator.sql("ALTER TABLE observatories ADD COLUMN notification_type TEXT")
    if fake or "email_address" not in existing:
        migrator.sql("ALTER TABLE observatories ADD COLUMN email_address TEXT")
    if fake or "cell_number" not in existing:
        migrator.sql("ALTER TABLE observatories ADD COLUMN cell_number TEXT")


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    pass
