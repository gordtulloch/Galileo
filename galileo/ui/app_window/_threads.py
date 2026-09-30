# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""QThread workers used by the various pages to keep slow device calls off the Qt UI thread."""

from __future__ import annotations

import logging

from ._common import _HAS_QT, QThread, Signal

logger = logging.getLogger(__name__)


class _CaptureThread(QThread if _HAS_QT else object):
    """Runs one manual capture (IMG-070) off the Qt UI thread, so the
    Imaging page's countdown/status display (IMG-090) keeps updating while
    the async expose/download call is in flight — the rest of this window
    calls device adapters with a blocking ``asyncio.run`` directly on the UI
    thread since those calls are quick (scan/connect/status), but a manual
    exposure can run for minutes and would otherwise freeze the whole app."""

    finished_ok = Signal() if _HAS_QT else None
    failed = Signal(str) if _HAS_QT else None
    frame_started = Signal(int, int) if _HAS_QT else None     # (frame number, frames in the series)
    frame_done = Signal(int, int) if _HAS_QT else None

    def __init__(self, service, quantity: int, duration: float, filter_name: str, frame_type: str,
                 parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._quantity = quantity
        self._duration = duration
        self._filter_name = filter_name
        self._frame_type = frame_type

    def run(self) -> None:
        import asyncio
        try:
            asyncio.run(self._service.capture_series(
                self._quantity, self._duration, self._filter_name, self._frame_type,
                on_frame_start=self.frame_started.emit, on_frame_done=self.frame_done.emit,
            ))
        except Exception as exc:
            if not self._service.stop_requested:
                self.failed.emit(str(exc))
                return
        self.finished_ok.emit()


class _MosaicCaptureThread(QThread if _HAS_QT else object):
    """Runs one mosaic capture (IMG-180, FRAME-090) off the Qt UI thread — mirrors
    ``_CaptureThread``, but drives ``ImagingService.capture_mosaic`` instead of
    ``capture_series``, since a mosaic's per-pane re-slews can each take as long as
    the exposures themselves and must not freeze the window either."""

    finished_ok = Signal() if _HAS_QT else None
    failed = Signal(str) if _HAS_QT else None
    slew_started = Signal(int, int) if _HAS_QT else None      # (step number, steps in the mosaic)
    frame_started = Signal(int, int) if _HAS_QT else None
    frame_done = Signal(int, int) if _HAS_QT else None

    def __init__(self, service, exposures_per_pane: int, duration: float, filter_name: str, frame_type: str,
                 parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._exposures_per_pane = exposures_per_pane
        self._duration = duration
        self._filter_name = filter_name
        self._frame_type = frame_type

    def run(self) -> None:
        import asyncio
        try:
            asyncio.run(self._service.capture_mosaic(
                self._exposures_per_pane, self._duration, self._filter_name, self._frame_type,
                on_slew_start=self.slew_started.emit,
                on_frame_start=self.frame_started.emit, on_frame_done=self.frame_done.emit,
            ))
        except Exception as exc:
            if not self._service.stop_requested:
                self.failed.emit(str(exc))
                return
        self.finished_ok.emit()


class _PreviewRenderThread(QThread if _HAS_QT else object):
    """Re-renders the Imaging page's preview (debayer + stretch) off the Qt UI thread — seconds
    of work on a large frame (NFR-PERF-020). ``rendered`` carries the result for
    ``ImagingService.apply_preview``, or ``None`` if rendering failed."""

    rendered = Signal(object) if _HAS_QT else None

    def __init__(self, service, parent=None) -> None:
        super().__init__(parent)
        self._service = service

    def run(self) -> None:
        try:
            result = self._service.render_preview()
        except Exception:
            logger.exception("Could not render the Imaging preview")
            result = None
        self.rendered.emit(result)


class _AnnotateThread(QThread if _HAS_QT else object):
    """Runs one Annotate solve+render (IMG-200) off the Qt UI thread: plate-solving is an
    external process that can take tens of seconds, and the Imaging page must stay responsive
    while it runs, same as every other blocking device/solver call in this window."""

    done = Signal() if _HAS_QT else None

    def __init__(self, service, solver, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._solver = solver

    def run(self) -> None:
        import asyncio
        try:
            asyncio.run(self._service.annotate_current_frame(self._solver))
        except Exception as exc:
            logger.exception("Annotate failed")
            self._service.annotate_note = f"Annotate failed: {exc}"
        self.done.emit()


class _DetermineRotationThread(QThread if _HAS_QT else object):
    """Runs one Determine Rotation solve (FRAME-100) off the Qt UI thread for the Framing
    Assistant dialog: plate-solves the Imaging tab's current frame via
    ``ImagingService.solve_current_frame`` (the same solve plumbing Annotate uses) and reports
    success/failure, mirroring ``_AnnotateThread`` but without building the annotate overlay."""

    finished_ok = Signal() if _HAS_QT else None
    failed = Signal(str) if _HAS_QT else None

    def __init__(self, service, solver, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._solver = solver

    def run(self) -> None:
        import asyncio
        try:
            result = asyncio.run(self._service.solve_current_frame(self._solver))
        except Exception as exc:
            logger.exception("Determine Rotation solve failed")
            self.failed.emit(str(exc))
            return
        if result.success and result.rotation_deg is not None:
            self.finished_ok.emit()
        else:
            self.failed.emit(result.failure_reason or "The solver found no solution.")


class _FlatsThread(QThread if _HAS_QT else object):
    """Runs one Sky Flats run (CAL-070) off the Qt UI thread: the twilight-window check,
    the mount slew/tracking-off bracket, and the per-frame adaptive-exposure convergence
    loop can together take many minutes (longer still across every filter), so this keeps
    the Flats Assistant dialog responsive the same way every other multi-minute device
    sequence in this window already runs off-thread (mirrors ``_CaptureThread``)."""

    filter_started = Signal(object, int, int) if _HAS_QT else None    # (filter_name, index, total)
    frame_done = Signal(object, int, int) if _HAS_QT else None        # (filter_name, frame index, frame total)
    finished_ok = Signal(list) if _HAS_QT else None                   # list[CalibrationResult]
    failed = Signal(str) if _HAS_QT else None

    def __init__(self, service, filters, count: int, max_well_depth: int, location, measure: str,
                 exposure_s, exposure_increment_s: float, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._filters = filters
        self._count = count
        self._max_well_depth = max_well_depth
        self._location = location
        self._measure = measure
        self._exposure_s = exposure_s
        self._exposure_increment_s = exposure_increment_s

    def run(self) -> None:
        import asyncio
        try:
            results = asyncio.run(self._service.run_sky_flats_all_filters(
                self._filters, self._count, self._max_well_depth, location=self._location,
                measure=self._measure, exposure_s=self._exposure_s,
                exposure_increment_s=self._exposure_increment_s,
                on_filter_start=self.filter_started.emit, on_frame_done=self.frame_done.emit,
            ))
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(results)


class _FilterMoveThread(QThread if _HAS_QT else object):
    """Moves the filter wheel to a slot off the Qt UI thread — a wheel can take
    several seconds to settle (INDI waits up to a minute), which would otherwise
    freeze the window the way a blocking ``asyncio.run`` on the UI thread does."""

    finished_ok = Signal() if _HAS_QT else None
    failed = Signal(str) if _HAS_QT else None

    def __init__(self, wheel, index: int, parent=None) -> None:
        super().__init__(parent)
        self._wheel = wheel
        self._index = index

    def run(self) -> None:
        import asyncio
        try:
            asyncio.run(self._wheel.move_to(self._index))
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit()


class _ResumeTrackingThread(QThread if _HAS_QT else object):
    """Waits for a slew to finish and then starts tracking at the target's rate (EQP-MNT-050).

    Off the Qt UI thread because the wait lasts as long as the slew does — minutes, for a mount
    crossing the sky — and the window must stay responsive throughout."""

    done = Signal(str) if _HAS_QT else None          # the rate set, or "" if the mount never settled
    failed = Signal(str) if _HAS_QT else None

    def __init__(self, mount, target=None, parent=None) -> None:
        super().__init__(parent)
        self._mount = mount
        self._target = target

    def run(self) -> None:
        import asyncio
        from galileo.tracking import resume_tracking
        try:
            rate = asyncio.run(resume_tracking(self._mount, self._target))
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(rate or "")


class _MountPositionThread(QThread if _HAS_QT else object):
    """Reads one mount's position off the Qt UI thread, for the Star Atlas telescope reticles
    (SKYMAP-090). A mount that can't be read reports nothing rather than failing: the reticle is
    a convenience, and a slow or absent mount must not stall the sky view."""

    position = Signal(object) if _HAS_QT else None      # the mount's status dict, or None

    def __init__(self, mount, parent=None) -> None:
        super().__init__(parent)
        self._mount = mount

    def run(self) -> None:
        import asyncio
        try:
            status = asyncio.run(self._mount.get_status()) or {}
        except Exception:
            logger.debug("Could not read the mount position for the Star Atlas", exc_info=True)
            status = None
        self.position.emit(status)


class _NudgeThread(QThread if _HAS_QT else object):
    """Runs one mount nudge (IMG-130) off the Qt UI thread: the mount moves for
    the nudge's duration, and blocking the UI for that long would freeze the
    Imaging page's exposure countdown while the user is watching it."""

    finished_ok = Signal() if _HAS_QT else None
    failed = Signal(str) if _HAS_QT else None

    def __init__(self, mount, direction: str, rate: float, duration: float,
                 reversed_axes: tuple, parent=None) -> None:
        super().__init__(parent)
        self._args = (mount, direction, rate, duration, reversed_axes)

    def run(self) -> None:
        import asyncio
        from galileo.ui.imaging import nudge_mount
        try:
            asyncio.run(nudge_mount(*self._args))
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit()


class _ThumbnailCacheThread(QThread if _HAS_QT else object):
    """Bulk-caches every catalog object's survey-image thumbnail off the Qt UI
    thread (Options > Planning's "Cache all thumbnails" button, SKY-080), so a
    later search's result-tile thumbnails load from disk instead of each
    needing its own hips2fits round trip. Reuses ``SkyAtlas._fetch_thumbnail``'s
    own ra/dec/field-size-keyed disk cache unchanged — an object already cached
    (from a prior run, from having shown up in a search's result tiles, or from
    being added to a target list) returns instantly with no network call, so
    resuming after Cancel, or re-running later, only fetches what's still
    missing. Runs one object at a time, sequentially, matching every other
    thumbnail fetch already in this codebase — no added concurrency, so this
    doesn't hit the free hips2fits service any harder than normal use already
    does; for the full catalog (tens of thousands of objects) that means this
    can genuinely take hours, which is why it's cancellable and why the
    confirmation dialog before starting says so."""

    progress = Signal(int, int) if _HAS_QT else None        # (done, total)
    finished_ok = Signal(int, int) if _HAS_QT else None      # (cached, failed)
    failed = Signal(str) if _HAS_QT else None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        import asyncio
        try:
            from galileo.planning.sky_atlas import SkyAtlas
            atlas = SkyAtlas()
            catalog = atlas._catalog
            total = len(catalog)
            cached_count = 0
            failed_count = 0
            for i, obj in enumerate(catalog):
                if self._stop_requested:
                    break
                try:
                    data = asyncio.run(atlas._fetch_thumbnail(obj))
                except Exception:
                    data = b""
                if data:
                    cached_count += 1
                else:
                    failed_count += 1
                if i % 5 == 0 or i == total - 1:
                    self.progress.emit(i + 1, total)
        except Exception as exc:
            logger.exception("Bulk thumbnail caching failed")
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(cached_count, failed_count)

