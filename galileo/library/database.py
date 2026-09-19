# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Library database: connection setup and ``peewee-migrate``-managed schema.

The library shares Galileo's one SQLite database (``galileo.platform.get_db_path``)
with the observatory/pier records, session history and scheduler. The schema is
owned by the numbered migration files in ``galileo/library/migrations`` — the
AstroFiler migrations ``001``-``012`` (the image catalog, sessions, field
mappings, master frames, variable stars) followed by Galileo's own. ``init_db``
applies any that are pending, so a fresh database and an existing AstroFiler
database both end up at the current schema.
"""

from __future__ import annotations

import datetime
import logging
import shutil
import time
from pathlib import Path
from typing import Any

import peewee as pw
from peewee_migrate import Router

from galileo.exceptions import DatabaseError
from galileo.library.models.base import db

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_LOCK_RETRIES = 5
_LOCK_RETRY_DELAY = 1.0


def _resolve_path(path: Path | str | None) -> Path:
    if path is None:
        from galileo.platform import get_db_path
        return get_db_path("galileo.db")
    return Path(path)


def _router() -> Router:
    return Router(db, migrate_dir=str(MIGRATIONS_DIR))


def init_db(path: Path | str | None = None) -> None:
    """Point the library at the SQLite file at *path* and bring its schema up to date.

    Leaves a connection open, as the ORM models expect.
    """
    target = _resolve_path(path)
    if not db.is_closed():
        db.close()
    db.init(str(target), pragmas={"journal_mode": "wal", "foreign_keys": 1, "busy_timeout": 5000})
    run_migrations()
    db.connect(reuse_if_open=True)
    logger.info("Database initialised at %s", target)


def run_migrations() -> None:
    """Apply every pending migration, retrying briefly if another process holds the lock."""
    if db.database is None:
        raise DatabaseError("Database path not set; call init_db() first.")
    for attempt in range(_LOCK_RETRIES):
        try:
            db.connect(reuse_if_open=True)
            _router().run()
            return
        except pw.OperationalError as exc:
            locked = "database is locked" in str(exc).lower()
            if locked and attempt < _LOCK_RETRIES - 1:
                wait = _LOCK_RETRY_DELAY * (2 ** attempt)
                logger.warning("Database is locked; retrying in %.1fs (%d/%d)", wait, attempt + 1, _LOCK_RETRIES)
                time.sleep(wait)
                continue
            if locked:
                raise DatabaseError(
                    f"Database is locked after {_LOCK_RETRIES} attempts; another Galileo process may be using it."
                ) from exc
            raise DatabaseError(f"Database operational error: {exc}") from exc
        except Exception as exc:
            raise DatabaseError(f"Failed to run migrations: {exc}") from exc


def setup_database() -> bool:
    """Make sure the database is initialised and migrated (idempotent); returns ``True``.

    The command-line utilities call this at start-up; the GUI has already done
    it via :func:`init_db`, in which case this only confirms the schema is current.
    """
    if db.database is None:
        init_db()
    else:
        run_migrations()
    return True


def create_migration(name: str) -> None:
    """Create an empty migration file named *name* in the migrations folder."""
    if not name or not name.strip():
        raise ValueError("Migration name cannot be empty")
    if db.database is None:
        raise DatabaseError("Database path not set; call init_db() first.")
    _router().create(name.strip())


def get_migration_status() -> dict[str, Any]:
    """``{'done': [...], 'undone': [...], 'current': name-or-'none'}`` for the open database."""
    if db.database is None:
        raise DatabaseError("Database path not set; call init_db() first.")
    router = _router()
    done = list(router.done)
    return {"done": done, "undone": list(router.diff), "current": done[-1] if done else "none"}


def backup_database(backup_dir: Path | str | None = None) -> Path | None:
    """Copy the SQLite file (and its WAL/SHM sidecars) to a timestamped backup; ``None`` if there's nothing to copy."""
    name = getattr(db, "database", None)
    if not name or name == ":memory:" or not Path(name).exists():
        return None
    source = Path(name)
    target_dir = Path(backup_dir) if backup_dir else source.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = target_dir / f"{source.stem}_backup_{stamp}{source.suffix}"
    shutil.copy2(source, backup_path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(source) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, target_dir / (backup_path.name + suffix))
    return backup_path


def get_db() -> pw.SqliteDatabase:
    return db
