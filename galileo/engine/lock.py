# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""One engine per machine and database (HEAD-020).

The control lease is held in memory (LEASE-010), so two engines on one telescope would each have their own
and could send conflicting commands. An engine therefore holds an exclusive operating-system lock on a file
beside the database for as long as it runs. The lock belongs to the process, so a crashed engine releases it
and the next one starts without any clean-up; nothing needs to be judged stale.

Who holds the lock is written to a small sidecar file (the lock itself cannot be read on Windows while it is
held), so a refusing engine can name the holder.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LOCK_NAME = "engine.lock"
INFO_NAME = "engine.json"


class EngineAlreadyRunning(RuntimeError):
    """Another engine holds the lock. ``holder`` is what it wrote about itself (may be empty)."""

    def __init__(self, holder: dict[str, Any]) -> None:
        self.holder = holder
        pid = holder.get("pid")
        what = f"pid {pid}, version {holder.get('version', '?')}, since {holder.get('since', '?')}" if pid else "unknown process"
        super().__init__(f"Galileo is already running on this computer ({what}). Only one engine may use this database.")


def _default_dir() -> Path:
    from galileo.platform import get_data_dir
    return get_data_dir()


class EngineLock:
    """``acquire()`` raises :class:`EngineAlreadyRunning`; ``release()`` is idempotent. Usable as a context manager."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = Path(directory) if directory is not None else _default_dir()
        self.lock_path = self.directory / LOCK_NAME
        self.info_path = self.directory / INFO_NAME
        self._fh: Any = None

    # -- the operating-system lock ---------------------------------------------------------------
    def _try_lock(self, fh: Any) -> bool:
        if sys.platform == "win32":
            import msvcrt
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        import fcntl
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(self, fh: Any) -> None:
        try:
            if sys.platform == "win32":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            logger.debug("Unlocking the engine lock failed", exc_info=True)

    # -- public ------------------------------------------------------------------------------------
    @property
    def held(self) -> bool:
        return self._fh is not None

    def holder(self) -> dict[str, Any]:
        """What the running engine wrote about itself, or ``{}``."""
        try:
            data = json.loads(self.info_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def acquire(self, **info: Any) -> None:
        if self._fh is not None:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        fh = open(self.lock_path, "a+b")  # noqa: SIM115 -- held open for the life of the lock
        if not self._try_lock(fh):
            fh.close()
            raise EngineAlreadyRunning(self.holder())
        self._fh = fh
        from galileo import __version__
        record = {"pid": os.getpid(), "version": __version__,
                  "since": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **info}
        try:
            self.info_path.write_text(json.dumps(record), encoding="utf-8")
        except OSError:
            logger.warning("Could not write %s; the engine still holds the lock", self.info_path)

    def update(self, **info: Any) -> None:
        """Add to what the holder says about itself (the local channel's address and token), readable only
        by the engine's user. Only the holder may call it."""
        if self._fh is None:
            return
        record = {**self.holder(), **info}
        try:
            self.info_path.write_text(json.dumps(record), encoding="utf-8")
            with contextlib.suppress(OSError):
                os.chmod(self.info_path, 0o600)
        except OSError:
            logger.warning("Could not update %s", self.info_path)

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        with contextlib.suppress(OSError):
            self.info_path.unlink(missing_ok=True)
        self._unlock(fh)
        fh.close()

    def __enter__(self) -> EngineLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


__all__ = ["EngineAlreadyRunning", "EngineLock"]
