# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Imaging on the engine (CSURF-120): one ``ImagingService`` per Pier, made by the same assembly a session uses.

A capture is the desktop's own ``capture_series``: each frame is shown (kept as the current frame with its statistics
and histogram), saved to the Library, and announced on the bus as a frame captured, so what listens for frames
(NodeConnect's transfer, the history) sees a remote capture as it sees any other. A Pier runs one capture at a time and
none while a session is running, since both would drive the one camera.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from galileo.engine.sessions import build_context
from galileo.livestack import LIVE_STACK_MIN_FRAMES

logger = logging.getLogger(__name__)


class EngineImaging:
    """``ImagingAccess`` (``galileo.control_surface.imaging``) over the device service and session runner."""

    def __init__(self, devices: Any, runner: Any, state: Any = None) -> None:
        self._devices, self._runner = devices, runner
        self._state = state                              # where the progress a client draws is published, if anywhere
        self._services: dict[str, Any] = {}              # Pier -> the ImagingService holding its current frame
        self._busy: set[str] = set()

    def why_not(self, pier: str) -> str | None:
        camera = self._devices.controller(pier, "camera")
        if camera is None:
            return "this Pier has no camera"
        if not getattr(camera, "is_connected", True):
            return "the camera is not connected"
        if self._runner.is_running(pier):
            return "a session is running on this Pier"
        if pier in self._busy:
            return "a capture is already running on this Pier"
        return None

    async def capture(self, pier: str, count: int, seconds: float, filter_name: str, frame_type: str,
                      gain: int, offset: int, camera_slot: str, progress: Any,
                      live_stack: bool = False, binning: int = 1) -> dict[str, Any]:
        reason = self.why_not(pier)
        if reason:
            from galileo.control_surface import Refused
            raise Refused(reason)
        self._busy.add(pier)
        try:
            service = (await build_context(self._devices, pier, camera_slot)).make_imaging()
            service.gain, service.offset, service.binning = gain, offset, binning
            service.live_stack_enabled = live_stack
            self._services[pier] = service
            ticker = asyncio.create_task(self._publish_progress(pier, service, count))
            try:
                ids = await service.capture_series(count, seconds, filter_name, frame_type,
                                                   on_frame_done=progress)
            finally:
                ticker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ticker
                self._clear_progress(pier)
            return {"frames": service.series_done, "requested": count, "library_ids": list(ids),
                    "note": service.library_note, "stopped": service.stop_requested}
        finally:
            self._busy.discard(pier)

    _PROGRESS_KEYS = ("imaging.exposure_progress", "imaging.exposure_s", "imaging.progress", "imaging.frame",
                      "imaging.count")

    async def _publish_progress(self, pier: str, service: Any, count: int) -> None:
        """While a capture runs, publish how far the exposure and the series have got (twice a second), so a client can
        draw the bars. ``imaging.exposure_progress`` and ``imaging.progress`` are 0 to 1."""
        if self._state is None:
            return
        while True:
            started = service.exposure_started_at
            seconds = float(service.exposure_seconds or 0.0)
            if started is not None and seconds > 0:
                self._state.publish(pier, "imaging.exposure_progress", min(1.0, max(0.0, (time.time() - started) / seconds)))
                self._state.publish(pier, "imaging.exposure_s", seconds)
            else:
                self._state.publish(pier, "imaging.exposure_progress", None)
            done = int(service.series_done)
            self._state.publish(pier, "imaging.progress", done / count if count else None)
            self._state.publish(pier, "imaging.frame", min(done + 1, count))
            self._state.publish(pier, "imaging.count", count)
            await asyncio.sleep(0.5)

    def _clear_progress(self, pier: str) -> None:
        if self._state is not None:
            for key in self._PROGRESS_KEYS:
                self._state.publish(pier, key, None)

    async def stop(self, pier: str) -> bool:
        service = self._services.get(pier)
        if pier not in self._busy or service is None:
            return False
        service.request_stop()
        camera = self._devices.controller(pier, "camera")
        try:
            await camera.abort_exposure()
        except Exception:
            logger.exception("Pier %s: could not abort the exposure", pier)
        return True

    def status(self, pier: str) -> dict[str, Any]:
        service = self._services.get(pier)
        out: dict[str, Any] = {"capturing": pier in self._busy, "why_not": self.why_not(pier) or ""}
        if service is None:
            return out
        out.update(status=service.capture_status, series_done=service.series_done, series_total=service.series_total)
        if service.exposure_started_at is not None:
            out["exposure"] = {"seconds": service.exposure_seconds,
                               "elapsed": max(0.0, time.time() - service.exposure_started_at)}
        stacker = service.active_stacker
        if service.live_stack_enabled and service.series_total >= LIVE_STACK_MIN_FRAMES:   # shorter runs don't stack
            out["stack"] = {"enabled": True, "frames": stacker.frames, "requested": service.series_total,
                            "total_exposure_s": stacker.total_exposure_s, "method": getattr(stacker, "method", ""),
                            "rejected": getattr(stacker, "rejected", 0)}
        if service.current_frame is not None:
            out["frame"] = {"shape": list(getattr(service.current_frame, "shape", ())),
                            "stats": _plain(service.get_frame_stats()), "histogram": _plain(service.get_histogram()),
                            "shot": _plain(service.last_shot)}
        return out


def _plain(value: Any) -> Any:
    """JSON-friendly copy: numpy scalars and arrays become numbers and lists, times become text."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


__all__ = ["EngineImaging"]
