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

logger = logging.getLogger(__name__)

_ALL_TABLES = [
    FitsFile, FitsSession, MasterFrame, PathMapping,
    ObservatoryRecord, PierRecord, DeviceConfigRecord,
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
    logger.info("Database initialised at %s", path)


def get_db() -> pw.SqliteDatabase:
    return db
