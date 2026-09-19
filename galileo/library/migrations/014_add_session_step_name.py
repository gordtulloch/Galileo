"""Peewee migrations -- 014_add_session_step_name.py.

``fitsSession.fitsSessionStepName``: the sequence step that produced a session.
Set only for the session containers the sequencer creates itself (LIB-160), so
they can be told apart from sessions inferred from FITS headers (LIB-040).
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    # With ``fake`` set, peewee-migrate is replaying an already-applied migration against a mocked
    # database only to rebuild its model state, so the column is always declared.
    if fake or "fitsSessionStepName" not in {c.name for c in database.get_columns("fitssession")}:
        migrator.add_fields("fitssession", fitsSessionStepName=pw.TextField(null=True))


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    migrator.remove_fields("fitssession", "fitsSessionStepName")
