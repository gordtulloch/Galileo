"""Database manager for the Galileo repository (adapted from AstroFiler database.py)."""

from __future__ import annotations

import logging
from pathlib import Path

import peewee as pw

from galileo.library.models.base import db
from galileo.library.models.fits_file import FitsFile
from galileo.library.models.fits_session import FitsSession
from galileo.library.models.mapping import PathMapping
from galileo.library.models.masters import MasterFrame
from galileo.library.models.observatory import ObservatoryRecord, PierRecord
from galileo.library.models.device_config import DeviceConfigRecord
from galileo.library.models.optical_tube import OpticalTubeRecord

logger = logging.getLogger(__name__)

_ALL_TABLES = [
    FitsFile, FitsSession, MasterFrame, PathMapping,
    ObservatoryRecord, PierRecord, DeviceConfigRecord, OpticalTubeRecord,
]


def init_db(path: "Path | str | None" = None) -> None:
    """Initialise (or re-initialise) the SQLite database at *path*."""
    if path is None:
        from galileo.platform import get_db_path
        path = get_db_path("galileo.db")
    db.init(str(path), pragmas={"journal_mode": "wal", "foreign_keys": 1})
    if db.is_closed():
        db.connect(reuse_if_open=True)
    db.create_tables(_ALL_TABLES, safe=True)
    _add_missing_columns()
    logger.info("Database initialised at %s", path)


def _add_missing_columns() -> None:
    """Add columns introduced after a table was first created.

    ``create_tables(safe=True)`` skips tables that already exist, so a column
    added to a model later never reaches an existing database on its own.
    """
    from playhouse.migrate import SqliteMigrator, migrate

    migrator = SqliteMigrator(db)
    for model, field_names in ((OpticalTubeRecord, ("name",)),):
        existing = {col.name for col in db.get_columns(model._meta.table_name)}
        for field_name in field_names:
            if field_name not in existing:
                migrate(migrator.add_column(model._meta.table_name, field_name, getattr(model, field_name)))
                logger.info("Added column %s.%s", model._meta.table_name, field_name)


def get_db() -> pw.SqliteDatabase:
    return db
