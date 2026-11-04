# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Session history, read-only (CSURF-230): which sessions have run and how their frames did.

``history.sessions`` lists the recorded sessions, ``history.report`` gives one session's per-frame star count, HFR and
guide error with their averages (what the History screen charts), and ``history.frames`` gives the same frames
without the averages. Nothing here changes, exports or deletes history: those stay on the desktop. Library
thumbnails, frame previews and the full-FITS download are a separate part of ``CSURF-230`` that needs a binary route.

``register_history_operations(registry, access)`` takes a :class:`HistoryAccess` so this module imports no store.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry
from galileo.control_surface.schema import Arg

MAX_FRAMES = 5000                                # a very long session is cut, not allowed to flood a phone


class HistoryAccess(Protocol):
    def sessions(self) -> list[dict[str, Any]]: ...

    def frames(self, session: str) -> list[dict[str, Any]] | None:
        """The session's frames, or ``None`` when no such session is recorded."""

    def report(self, session: str) -> dict[str, Any] | None: ...


def register_history_operations(registry: Registry, access: HistoryAccess) -> None:
    async def sessions(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return {"sessions": access.sessions()}

    async def frames(ctx: OperationContext, args: dict[str, Any]) -> Any:
        found = access.frames(args["session"])
        if found is None:
            raise Refused(f"there is no recorded session called {args['session']!r}")
        return {"session": args["session"], "frames": found[:MAX_FRAMES], "total": len(found)}

    async def report(ctx: OperationContext, args: dict[str, Any]) -> Any:
        found = access.report(args["session"])
        if found is None:
            raise Refused(f"there is no recorded session called {args['session']!r}")
        found = dict(found)
        every = list(found.get("frames", []))
        found.update(session=args["session"], frames=every[:MAX_FRAMES], total=len(every))
        return found

    registry.register(OperationSpec("history.sessions", "read", (), needs_lease=False,
                                    description="The recorded sessions and how many frames each has"), sessions)
    registry.register(OperationSpec("history.frames", "read", (Arg("session", "str"),), needs_lease=False,
                                    description="One session's frames: star count, HFR and guide error"), frames)
    registry.register(OperationSpec("history.report", "read", (Arg("session", "str"),), needs_lease=False,
                                    description="One session's frames with the average HFR and star count"), report)


class StoreHistory:
    """:class:`HistoryAccess` over ``galileo.history.SessionHistory``."""

    def __init__(self, store: Any = None) -> None:
        self._store = store

    @property
    def store(self) -> Any:
        if self._store is None:
            from galileo.history import get_history
            return get_history()
        return self._store

    def _known(self, session: str) -> bool:
        return any(s["name"] == session for s in self.store.list_sessions())

    def sessions(self) -> list[dict[str, Any]]:
        return [dict(s) for s in self.store.list_sessions()]

    def frames(self, session: str) -> list[dict[str, Any]] | None:
        return self.store.get_frames_for_session(session) if self._known(session) else None

    def report(self, session: str) -> dict[str, Any] | None:
        return self.store.get_report_for_session(session) if self._known(session) else None


__all__ = ["MAX_FRAMES", "HistoryAccess", "StoreHistory", "register_history_operations"]
