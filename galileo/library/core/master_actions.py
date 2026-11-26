# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Acting on one master calibration frame: recreate it from its source session, or delete it (LIB-240)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from galileo.library.core.master_manager import MasterFrameManager
from galileo.library.models import Masters, fitsFile, fitsSession

logger = logging.getLogger(__name__)

#: The fewest source frames a master is stacked from.
MIN_SOURCE_FRAMES = 2

_SESSION_FIELDS = ("fitsBiasMaster", "fitsDarkMaster", "fitsFlatMaster")


class MasterActionError(Exception):
    """Why a master could not be recreated or deleted, worded for the user."""


def list_masters() -> list[Masters]:
    """Every master in the catalog, newest first."""
    return list(Masters.select().where(Masters.soft_delete == False)
                .order_by(Masters.creation_date.desc()))


def source_frames(master: Masters) -> tuple[list[str], int]:
    """``(paths still on disk, number catalogued)`` for the frames *master*'s source session holds."""
    if not master.source_session_id:
        return [], 0
    rows = list(fitsFile.select().where(
        fitsFile.fitsFileSession == master.source_session_id,
        fitsFile.fitsFileObject.contains(master.master_type.upper())))
    return [r.fitsFileName for r in rows if r.fitsFileName and os.path.exists(r.fitsFileName)], len(rows)


def recreate_blocker(master: Masters) -> str | None:
    """Why *master* cannot be recreated, or ``None`` if it can."""
    if not master.source_session_id:
        return "This master was not built from a session in the Library (it was imported), so it cannot be recreated."
    if fitsSession.get_or_none(fitsSession.fitsSessionId == master.source_session_id) is None:
        return "The session this master was built from is no longer in the Library."
    present, catalogued = source_frames(master)
    if len(present) < MIN_SOURCE_FRAMES:
        return (f"Only {len(present)} of the {catalogued} source frames are still on disk; "
                f"at least {MIN_SOURCE_FRAMES} are needed.")
    return None


def _other_records_use(path: str, master: Masters) -> bool:
    return Masters.select().where((Masters.master_path == path) & (Masters.id != master.id)).exists()


def recreate_master(master_id: int, progress_callback: Callable | None = None) -> Masters:
    """Stack *master_id* again from its source session. The record keeps its identity, so sessions
    that refer to it still do; the old record and file are left alone if stacking fails."""
    master = Masters.get_by_id(master_id)
    blocker = recreate_blocker(master)
    if blocker:
        raise MasterActionError(blocker)
    present, _ = source_frames(master)

    new = MasterFrameManager().create_master_from_session(
        str(master.source_session_id), master.master_type, MIN_SOURCE_FRAMES, progress_callback)
    if new is None:
        raise MasterActionError("The master could not be stacked. See the log for the reason.")

    old_path = master.master_path
    master.master_path = new.master_path
    master.hash_value = new.hash_value
    master.file_size = new.file_size
    master.file_count = len(present)
    master.creation_date = new.creation_date
    master.cloud_url = None          # the cloud copy, if any, is of the old pixels
    master.quality_score = None
    master.is_validated = False
    master.validation_date = None
    with Masters._meta.database.atomic():
        new.delete_instance()
        master.save()
        for name in _SESSION_FIELDS:
            field = getattr(fitsSession, name)
            fitsSession.update({field: master.master_id}).where(field == old_path).execute()
        # Any other record of the same file now describes the new pixels too.
        Masters.update(hash_value=master.hash_value, file_size=master.file_size).where(
            (Masters.master_path == master.master_path) & (Masters.id != master.id)).execute()

    if (os.path.normcase(os.path.abspath(old_path)) != os.path.normcase(os.path.abspath(master.master_path))
            and os.path.exists(old_path) and not _other_records_use(old_path, master)):
        try:
            os.remove(old_path)
        except OSError:
            logger.warning("Could not remove the replaced master file %s", old_path, exc_info=True)
    logger.info("Recreated %s master %s from %d frames", master.master_type, master.master_id, len(present))
    return master


def delete_master(master_id: int) -> None:
    """Delete the master's file and catalog record, and clear the sessions' references to it. The
    source frames are not touched. A file another record also describes is kept."""
    master = Masters.get_by_id(master_id)
    path = master.master_path
    if path and os.path.exists(path) and not _other_records_use(path, master):
        try:
            os.remove(path)
        except OSError as exc:
            raise MasterActionError(f"The file could not be deleted, so nothing was changed:\n{exc}") from exc
    refs = [r for r in (master.master_id, path) if r]
    with Masters._meta.database.atomic():
        for name in _SESSION_FIELDS:
            field = getattr(fitsSession, name)
            fitsSession.update({field: None}).where(field.in_(refs)).execute()
        master.delete_instance()
    logger.info("Deleted master %s (%s)", master.master_id, path)
