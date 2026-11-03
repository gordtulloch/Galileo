# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""How a desktop gets its engine (HEAD-090, HEAD-100).

``attach_or_host`` is the desktop's one question at start-up: *is an engine already running here?*

* No: the desktop **hosts** one in its own process. It is the same ``Engine`` that ``Galileo --engine`` runs and it
  holds the same lock (HEAD-020), so a single-computer user sees no difference and a second desktop on the
  machine finds the lock taken.
* Yes: the desktop **attaches** to it as a client (HEAD-070) and starts nothing of its own.

Closing follows from which it is (HEAD-100): a hosting desktop stops the engine as on a normal exit, but asks first
while a session is running; an attached desktop leaves the engine, its sessions, devices and listeners alone.

This module imports nothing from Qt, so it can be tested and used by any front end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from galileo.engine.client import EngineClient, find_engine
from galileo.engine.lock import EngineAlreadyRunning, EngineLock
from galileo.engine.main import Engine

logger = logging.getLogger(__name__)

HOSTING = "hosting"
ATTACHED = "attached"


@dataclass
class Attachment:
    """What the desktop holds: its own engine (``hosting``) or a client of another process's (``attached``)."""

    mode: str
    engine: Engine | None = None
    client: EngineClient | None = None

    @property
    def hosting(self) -> bool:
        return self.mode == HOSTING

    def sessions_running(self) -> bool:
        """Whether a session is running on an engine this desktop hosts (an attached desktop never needs to know)."""
        runner = getattr(self.engine, "runner", None)
        return bool(runner is not None and runner.is_running())

    def needs_confirmation(self) -> bool:
        """True when closing would stop a running session: only a hosting desktop, only while one runs."""
        return self.hosting and self.sessions_running()

    def close(self, confirmed: bool = False) -> bool:
        """Close the desktop's side. Returns ``False`` (and does nothing) when a hosting desktop has a session
        running and *confirmed* is not given, so the caller can ask the user. An attached desktop leaves the
        engine untouched; closing its ``client`` connection is the caller's, since that is asynchronous."""
        if not self.hosting:
            return True
        if self.needs_confirmation() and not confirmed:
            return False
        if self.engine is not None:
            self.engine.stop()
        return True


def attach_or_host(version: str, lock: EngineLock | None = None, engine_factory: Any = Engine) -> Attachment:
    """Host an engine if none is running; otherwise return a client for the one that is.

    Raises :class:`EngineAlreadyRunning` when another process holds the lock but has not published its channel yet
    (it is still starting, or is an older build with no channel); the message names it. The client is returned
    unattached: the caller awaits ``client.attach()`` so a version mismatch (HEAD-180) is reported where the user
    can see it.
    """
    lock = lock or EngineLock()
    engine = engine_factory(lock)
    try:
        engine.start()
    except EngineAlreadyRunning as exc:
        info = find_engine(lock.directory)
        if not info.get("address") or not info.get("token"):
            raise
        logger.info("An engine is already running (%s); attaching to it", exc.holder.get("pid", "?"))
        from galileo import __version__
        return Attachment(ATTACHED, client=EngineClient(info["address"], info["token"], version or __version__))
    return Attachment(HOSTING, engine=engine)


__all__ = ["ATTACHED", "HOSTING", "Attachment", "attach_or_host"]
