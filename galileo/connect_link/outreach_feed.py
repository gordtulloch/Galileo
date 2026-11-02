# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Feeding the outreach event its live image (LINK-160).

While an event is open this subscribes to the bus for finished frames, keeps the latest frame of each
offered Pier, and has the facility render it through the preview service's guest mode (no metadata, capped
size and quality) and push it to the guests viewing that Pier. It subscribes only while an event is open, and
a Pier's reference here is the text of its database id, the same key the Imaging screen uses.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import numpy as np

from galileo.bus import EventBus, FrameCapturedEvent, get_bus
from galileo.connect_link.outreach import OutreachFacility, OutreachOptions
from galileo.preview import PreviewParams, PreviewService

logger = logging.getLogger(__name__)


def pier_display_names(refs: Any) -> dict[str, str]:
    """``{reference: "Observatory / Pier"}`` for the offered Pier ids; an unknown one keeps its reference."""
    names = {str(r): str(r) for r in refs}
    try:
        from galileo.library.models.base import db
        from galileo.library.models.observatory import PierRecord
        db.connect(reuse_if_open=True)
        ids = [int(r) for r in names if str(r).isdigit()]
        for rec in PierRecord.select().where(PierRecord.id.in_(ids)):  # type: ignore[attr-defined]
            names[str(rec.id)] = f"{rec.observatory.name} / {rec.name}"
    except Exception:
        logger.debug("Could not look up Pier names for outreach", exc_info=True)
    return names


class OutreachFeed:
    def __init__(self, facility: OutreachFacility, options: Any = OutreachOptions.load,
                 session_busy: Any = None, bus: EventBus | None = None) -> None:
        self._facility = facility
        self._options = options
        self._bus = bus or get_bus()
        self._frames: dict[str, tuple[int, np.ndarray]] = {}
        self._counter = 0
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Future[Any]] = set()
        self._attached = False
        self.preview = PreviewService({"current": self._source}, busy=session_busy)

    # -- the bus ---------------------------------------------------------------------------------
    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start following frames (called when an event opens)."""
        self._loop = loop
        if not self._attached:
            self._bus.subscribe(FrameCapturedEvent, self._on_frame)
            self._attached = True

    def detach(self) -> None:
        """Stop following frames and forget them (called when the event ends)."""
        if self._attached:
            self._bus.unsubscribe(FrameCapturedEvent, self._on_frame)
            self._attached = False
        with self._lock:
            self._frames.clear()
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

    def _on_frame(self, event: Any) -> None:
        """Runs on the imaging thread: take the frame and hand the rendering to the service's loop."""
        ref = str(event.payload.get("pier", ""))
        service = event.payload.get("service")
        frame = getattr(service, "current_frame", None)
        loop = self._loop
        if frame is None or loop is None or not ref:
            return
        with self._lock:
            self._counter += 1
            self._frames[ref] = (self._counter, np.asarray(frame))
        try:
            loop.call_soon_threadsafe(self._schedule, ref)
        except RuntimeError:                                  # the loop has gone; the event is over
            return

    def _schedule(self, ref: str) -> None:
        task = asyncio.ensure_future(self._facility.on_frame_complete(ref))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- rendering -------------------------------------------------------------------------------
    def _source(self, reference: str) -> tuple[str, np.ndarray] | None:
        with self._lock:
            found = self._frames.get(reference.split(":", 1)[-1])
        return None if found is None else (str(found[0]), found[1])

    async def render(self, ref: str) -> bytes | None:
        """The Pier's latest frame as a guest-mode JPEG, or ``None`` when there is none yet."""
        opts = self._options()
        try:
            preview = await self.preview.render(
                f"current:{ref}", PreviewParams(guest=True, max_size=opts.preview_size, quality=opts.preview_quality))
        except Exception:
            return None
        return preview.data


__all__ = ["OutreachFeed", "pier_display_names"]
