# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Catalog registration for frames written during a running sequence (LIB-150, LIB-160).

The sequencer hands each frame it has just written to :meth:`LibraryRegistrar.register_frame`
so it is in the catalog immediately, rather than waiting for a later scan. Frames
acquired by one sequence step are grouped into a *session container*: a
``fitsSession`` row created from the step's own boundaries (authoritative), as
opposed to the sessions ``galileo.library.core.session_processing`` infers from
FITS headers afterwards (LIB-040).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from galileo.library.models import fitsFile, fitsSession

logger = logging.getLogger(__name__)


@dataclass
class SessionContainer:
    """The frames one sequence step acquired."""
    session_id: str
    step_name: str
    frame_count: int


class LibraryRegistrar:
    """Registers sequencer output in the library catalog, in place (files are not moved)."""

    def register_frame(self, path: Path | str, session_id: str | None = None) -> str | None:
        """Catalog the FITS file at *path*; returns its catalog id, or ``None`` if it was rejected.

        With *session_id*, the frame is also attached to that session container.
        """
        from galileo.library.core import fitsProcessing

        path = Path(path)
        file_id = fitsProcessing().registerFitsImage(str(path.parent), path.name, moveFiles=False)
        if not file_id:
            logger.warning("Frame was not registered: %s", path)
            return None
        if session_id:
            fitsFile.update(fitsFileSession=session_id).where(fitsFile.fitsFileId == file_id).execute()
        return file_id

    def register_capture(self, path: Path | str) -> str | None:
        """Catalog a frame captured by hand (IMG-150) and move it into the repository.

        Unlike :meth:`register_frame` the file is *moved* — it was written to a scratch folder and
        must not be left there — into the folder the Library's naming scheme gives it (for a light
        frame, ``Light/<object>/<telescope>/<instrument>/<date>``). Returns the catalog id, or
        ``None`` if the frame was not registered; a frame that was not registered is left where it
        is. Nothing is done when no repository folder is configured, since the file would otherwise
        be moved into the working directory.
        """
        from galileo.library.config import get_repository_path
        from galileo.library.core import fitsProcessing

        path = Path(path)
        if not get_repository_path():
            logger.warning("Frame not added to the Library: no repository folder is set (Options > Library).")
            return None
        try:
            file_id = fitsProcessing().registerFitsImage(str(path.parent), path.name, moveFiles=True)
        except Exception:
            logger.exception("Frame was not added to the Library: %s", path)
            return None
        if not file_id:
            logger.warning("Frame was not added to the Library: %s", path)
            return None
        return file_id

    def entry_count(self) -> int:
        """Number of catalogued frames."""
        return fitsFile.select().count()

    def begin_sequence_session(self, step_name: str) -> str:
        """Open a session container for the sequence step *step_name*; returns its id."""
        session_id = str(uuid.uuid4())
        fitsSession.create(fitsSessionId=session_id, fitsSessionStepName=step_name, fitsSessionObjectName=step_name)
        return session_id

    def add_frame_to_session(self, session_id: str, path: Path | str) -> str | None:
        """Register the frame at *path* and attach it to the container *session_id*."""
        return self.register_frame(path, session_id=session_id)

    def end_sequence_session(self, session_id: str) -> None:
        """Close the container: fill in what its frames have in common (date, equipment, exposure)."""
        frames = list(fitsFile.select().where(fitsFile.fitsFileSession == session_id))
        if not frames:
            return
        first = frames[0]
        fitsSession.update(
            fitsSessionObjectName=first.fitsFileObject or fitsSession.fitsSessionObjectName,
            fitsSessionDate=first.fitsFileDate,
            fitsSessionTelescope=first.fitsFileTelescop,
            fitsSessionImager=first.fitsFileInstrument,
            fitsSessionExposure=first.fitsFileExpTime,
            fitsSessionBinningX=first.fitsFileXBinning,
            fitsSessionBinningY=first.fitsFileYBinning,
            fitsSessionCCDTemp=first.fitsFileCCDTemp,
            fitsSessionGain=first.fitsFileGain,
            fitsSessionOffset=first.fitsFileOffset,
            fitsSessionFilter=first.fitsFileFilter,
        ).where(fitsSession.fitsSessionId == session_id).execute()

    def get_sequence_sessions(self) -> list[SessionContainer]:
        """Every sequencer-created session container, with its current frame count."""
        containers = []
        for session in fitsSession.select().where(fitsSession.fitsSessionStepName.is_null(False)):
            count = fitsFile.select().where(fitsFile.fitsFileSession == session.fitsSessionId).count()
            containers.append(SessionContainer(session.fitsSessionId, session.fitsSessionStepName, count))
        return containers
