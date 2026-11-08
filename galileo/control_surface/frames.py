# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Frames a front end can look at (PREV-070): the Pier's current exposure and any Library frame.

The preview service (``galileo.preview``) renders whatever its *sources* hand it; until now none were registered, so
nothing could ask it for a picture. :class:`FrameSources` is that registration. It follows the bus for finished
frames (a remote capture and a running session both announce theirs) and keeps the latest frame of each Pier, and it
reads a Library frame from disk on request. :class:`FramePreviews` puts the two behind the calls a plugin needs: a
preview, a tile, the facts about a frame, and a list of recent Library frames to choose from.

A reference is ``current:<pier>`` (the text of the Pier's database id, as everywhere in the Control Surface; the
latest single exposure), ``stack:<pier>`` (the live stack of the series under way, once it has a frame) or
``guide:<pier>`` (the whole frame PHD2 is guiding on, for choosing the guide star), ``solve:<pier>`` (the latest frame
captured for plate solving or polar alignment, so a client can watch it) or ``library:<frame id>``. This module imports no Qt and no device code; the engine builds it and hands it to the plugin
through ``ControlSurfaceService.previews``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from galileo.bus import EventBus, FrameCapturedEvent, get_bus
from galileo.preview import Preview, PreviewError, PreviewParams, PreviewService

logger = logging.getLogger(__name__)

REF = re.compile(r"^(current|stack|guide|solve|library):[\w.\-]{1,80}$")
LOADED_KEPT = 3                       # decoded Library frames held, so a pan or a restretch does not re-read the file
RECENT_MAX = 100


class FrameSources:
    """``Source`` callables for the preview service, keyed by the part of a reference before the colon."""

    def __init__(self, bus: EventBus | None = None, loader: Callable[[str], tuple[str, np.ndarray] | None] | None = None,
                 guide: Callable[[str], tuple[str, np.ndarray] | None] | None = None) -> None:
        self._bus = bus or get_bus()
        self._guide_frame = guide
        self._load_library = loader or _library_frame
        self._latest: dict[str, tuple[int, np.ndarray]] = {}
        self._stacks: dict[str, tuple[int, np.ndarray]] = {}
        self._solves: dict[str, tuple[int, np.ndarray]] = {}
        self._counter = 0
        self._loaded: OrderedDict[str, tuple[str, np.ndarray]] = OrderedDict()
        self._lock = threading.Lock()
        self._bus.subscribe(FrameCapturedEvent, self._on_frame)

    def close(self) -> None:
        self._bus.unsubscribe(FrameCapturedEvent, self._on_frame)
        with self._lock:
            self._latest.clear()
            self._stacks.clear()
            self._solves.clear()
            self._loaded.clear()

    def sources(self) -> dict[str, Callable[[str], tuple[str, np.ndarray] | None]]:
        return {"current": self._current, "stack": self._stack, "guide": self._guide, "solve": self._solve,
                "library": self._library}

    def _on_frame(self, event: Any) -> None:
        """On the imaging thread: remember the frame (a reference, not a copy; a service replaces its frame). With a
        live stack running, ``current_frame`` is the stack, so the single exposure is the service's ``last_sub_frame``
        and the stack is kept under its own reference."""
        pier = str(event.payload.get("pier", ""))
        service = event.payload.get("service")
        frame = getattr(service, "last_sub_frame", None)
        if frame is None:
            frame = getattr(service, "current_frame", None)
        if not pier or frame is None:
            return
        stacker = getattr(service, "active_stacker", None) if getattr(service, "live_stack_enabled", False) else None
        stacked = stacker.result if stacker is not None and stacker.frames else None
        with self._lock:
            self._counter += 1
            self._latest[pier] = (self._counter, np.asarray(frame))
            if stacked is not None:
                self._stacks[pier] = (self._counter, np.asarray(stacked))
            else:
                self._stacks.pop(pier, None)

    def _current(self, ref: str) -> tuple[str, np.ndarray] | None:
        with self._lock:
            found = self._latest.get(ref.split(":", 1)[-1])
        return None if found is None else (str(found[0]), found[1])

    def _stack(self, ref: str) -> tuple[str, np.ndarray] | None:
        with self._lock:
            found = self._stacks.get(ref.split(":", 1)[-1])
        return None if found is None else (str(found[0]), found[1])

    def set_solve_frame(self, pier: str, frame: Any) -> int:
        """Remember the frame just captured for solving on *pier* (a reference, not a copy). Returns its version."""
        with self._lock:
            self._counter += 1
            self._solves[pier] = (self._counter, np.asarray(frame))
            return self._counter

    def _solve(self, ref: str) -> tuple[str, np.ndarray] | None:
        with self._lock:
            found = self._solves.get(ref.split(":", 1)[-1])
        return None if found is None else (str(found[0]), found[1])

    def _guide(self, ref: str) -> tuple[str, np.ndarray] | None:
        if self._guide_frame is None:
            return None
        return self._guide_frame(ref.split(":", 1)[-1])

    def _library(self, ref: str) -> tuple[str, np.ndarray] | None:
        key = ref.split(":", 1)[-1]
        with self._lock:
            hit = self._loaded.get(key)
            if hit is not None:
                self._loaded.move_to_end(key)
                return hit
        found = self._load_library(key)
        if found is not None:
            with self._lock:
                self._loaded[key] = found
                while len(self._loaded) > LOADED_KEPT:
                    self._loaded.popitem(last=False)
        return found

    def stack_version(self, pier: str) -> int:
        """0 while the Pier has no live stack; then a number that changes each time a frame joins it."""
        with self._lock:
            found = self._stacks.get(pier)
        return 0 if found is None else found[0]

    def current_version(self, pier: str) -> int:
        """0 until the Pier has a frame; then a number that changes with each new one (the page uses it to refresh)."""
        with self._lock:
            found = self._latest.get(pier)
        return 0 if found is None else found[0]


def _library_frame(frame_id: str) -> tuple[str, np.ndarray] | None:
    """Read a Library frame's pixels (fetching it first if it is held on a Master). ``None`` when there is no such
    frame or it cannot be read; the version is the file's modification time, so an edited file is re-rendered."""
    from astropy.io import fits

    from galileo.library.core.location import LocationError, ensure_local_sync
    try:
        path = Path(ensure_local_sync(frame_id))
    except (LocationError, KeyError, ValueError, OSError) as exc:
        logger.info("Library frame %s is not available for preview: %s", frame_id, exc)
        return None
    try:
        with fits.open(path, memmap=False) as hdus:
            data = next((h.data for h in hdus if getattr(h, "data", None) is not None and h.data.ndim >= 2), None)
        return None if data is None else (f"{path.stat().st_mtime_ns}", np.asarray(data))
    except Exception:
        logger.exception("Could not read frame %s for preview", frame_id)
        return None


def recent_library_frames(limit: int = 30) -> list[dict[str, Any]]:
    """The newest Library frames a person might want to look at, newest first. Soft-deleted frames are left out."""
    from galileo.library.models.base import db
    from galileo.library.models.fits_file import fitsFile
    db.connect(reuse_if_open=True)
    rows = (fitsFile.select().where((fitsFile.fitsFileSoftDelete == False) | (fitsFile.fitsFileSoftDelete.is_null()))
            .order_by(fitsFile.fitsFileDate.desc(), fitsFile.fitsFileId.desc()).limit(max(1, min(RECENT_MAX, limit))))
    return [{"id": r.fitsFileId, "name": Path(r.fitsFileName or "").name, "object": r.fitsFileObject or "",
             "type": r.fitsFileType or "", "filter": r.fitsFileFilter or "", "exposure": r.fitsFileExpTime or "",
             "date": str(r.fitsFileDate or ""), "session": r.fitsFileSession or "",
             "local": (r.fitsFileLocation or "local") == "local"} for r in rows]


class FramePreviews:
    """What the plugin calls: render, tile, info and the list of frames, each taking a reference and parameters."""

    def __init__(self, sources: FrameSources, *, busy: Callable[[], bool] | None = None,
                 recent: Callable[[int], list[dict[str, Any]]] = recent_library_frames,
                 max_size_limit: int = 4096, quality_limit: int = 95) -> None:
        self.sources = sources
        self._recent = recent
        self.service = PreviewService(sources.sources(), busy=busy, max_size_limit=max_size_limit,
                                      quality_limit=quality_limit)

    @staticmethod
    def check(ref: str) -> str:
        if not REF.match(ref or ""):
            raise PreviewError("not a frame reference")
        return ref

    async def render(self, ref: str, params: PreviewParams) -> Preview:
        return await self.service.render(self.check(ref), params)

    async def tile(self, ref: str, level: int, x: int, y: int, params: PreviewParams) -> bytes:
        return await self.service.tile(self.check(ref), level, x, y, params)

    async def info(self, ref: str) -> dict[str, Any]:
        """Shape and version of a frame, without rendering it (``PreviewError`` when there is no such frame)."""
        ref = self.check(ref)
        version, data = await asyncio.to_thread(self.service._load, ref)
        shape = list(np.asarray(data).shape)
        if len(shape) == 3 and shape[0] in (3, 4) and shape[-1] not in (3, 4):
            shape = shape[1:] + shape[:1]                       # a channel-first cube
        return {"ref": ref, "version": version, "height": int(shape[0]), "width": int(shape[1])}

    async def frames(self, pier: str, limit: int = 30) -> dict[str, Any]:
        current = self.sources.current_version(pier)
        recent = await asyncio.to_thread(self._recent, limit)
        stack = self.sources.stack_version(pier)
        return {"current": {"ref": f"current:{pier}", "version": current, "available": current > 0},
                "stack": {"ref": f"stack:{pier}", "version": stack, "available": stack > 0}, "frames": recent}


__all__ = ["REF", "FramePreviews", "FrameSources", "recent_library_frames"]
