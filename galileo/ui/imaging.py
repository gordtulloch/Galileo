# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Imaging tab service — preview, statistics, manual capture (IMG-010 … IMG-100)."""

from __future__ import annotations

import asyncio
import datetime
import logging
import math
from pathlib import Path

from galileo.core.compute import run_cpu
from galileo.current_object import safe_file_stem
from galileo.debayer import BAYER_PATTERNS, DEFAULT_PATTERN, debayer
from galileo.livestack import LIVE_STACK_MIN_FRAMES, LiveStacker, MosaicStacker

logger = logging.getLogger(__name__)

DEFAULT_GAIN = 110      # what the Imaging page's Gain field starts at (IMG-150)
DEFAULT_OFFSET = 0      # what the Imaging page's Offset field starts at (IMG-150)

# Auto-stretch slider (IMG-190): 0..100, where 0 clips almost nothing of each tail (a flat,
# close-to-linear preview) and 100 clips the most (the highest-contrast, most "stretched" look).
# The full range was found by testing to be too coarse — useful settings all sat within the first
# few clicks — so _auto_stretch's percentile margin only spans half of what it first did, and the
# default sits at what testing found to be a good, natural-looking setting on that halved scale.
DEFAULT_STRETCH_LEVEL = 2

PORTRAIT = "portrait"
LANDSCAPE = "landscape"

# Nudge speeds in deg/s (the unit of the mount adapters' ``move_axis``), slowest first.
# INDI snaps each to one of the driver's standard rates (guide / centering / find).
NUDGE_RATES: dict = {"Fine": 0.02, "Medium": 0.2, "Coarse": 1.0}
NUDGE_DIRECTIONS = ("N", "S", "E", "W")


def frame_orientation(data) -> str:
    """``"portrait"`` if *data* is taller than it is wide, else ``"landscape"``
    (a square frame, or no frame yet, counts as landscape)."""
    if data is None or getattr(data, "ndim", 0) < 2:
        return LANDSCAPE
    height, width = data.shape[0], data.shape[1]
    return PORTRAIT if height > width else LANDSCAPE


def format_ra_hms(ra_deg: float) -> str:
    """Right ascension in degrees as ``HH MM SS.s`` (the ``OBJCTRA`` card's format)."""
    seconds = round((ra_deg % 360.0) / 15.0 * 3600.0, 1)
    seconds %= 24 * 3600
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):02d} {int(minutes):02d} {secs:04.1f}"


def format_dec_dms(dec_deg: float) -> str:
    """Declination in degrees as ``+DD MM SS`` (the ``OBJCTDEC`` card's format)."""
    sign = "-" if dec_deg < 0 else "+"
    total = round(abs(dec_deg) * 3600.0)
    degrees, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{sign}{int(degrees):02d} {int(minutes):02d} {int(secs):02d}"


async def nudge_mount(mount, direction: str, rate: float, duration: float,
                      reversed_axes: tuple = (False, False)) -> None:
    """Move *mount* one way for *duration* seconds at *rate* deg/s, then stop.
    ``N``/``S`` drive the secondary (Dec) axis and ``E``/``W`` the primary (RA)
    axis, with the same signs as the Mount page's jog pad; *reversed_axes* is
    that page's (primary, secondary) "reversed" pair. The axis is always
    stopped afterwards, even if the wait is cancelled or the mount errors."""
    direction = direction.upper()
    if direction not in NUDGE_DIRECTIONS:
        raise ValueError(f"Unknown nudge direction {direction!r}")
    axis = 1 if direction in ("N", "S") else 0
    sign = 1.0 if direction in ("N", "E") else -1.0
    if reversed_axes[axis]:
        sign = -sign
    await mount.move_axis(axis, sign * abs(rate))
    try:
        await asyncio.sleep(max(0.0, duration))
    finally:
        await mount.move_axis(axis, 0.0)


class ImagingService:
    """Domain-layer service for the imaging tab; no PySide6 dependency."""

    def __init__(self, camera=None, output_dir: Path | str = ".") -> None:
        self._camera = camera
        self._output_dir = Path(output_dir)
        self.current_frame = None
        self.current_preview = None
        # Statistics and histogram of ``_analysed_frame``, worked out off the UI thread as each frame
        # arrives (NFR-PERF-020) so the page only has to read them.
        self.frame_stats: dict | None = None
        self.frame_histogram: dict | None = None
        self._analysed_frame = None
        self.last_saved_array = None
        self.last_saved_path: Path | None = None
        self.zoom_factor: float = 1.0
        self.pan_offset: tuple[int, int] = (0, 0)
        self.capture_status: str = "idle"
        self._panel_layout: dict = {}
        self._capture_status: str = "idle"
        # Debayering (IMG-110) only changes the preview; current_frame stays the camera's raw mosaic.
        self.debayer_enabled: bool = False
        self.bayer_pattern: str = DEFAULT_PATTERN  # the camera's mosaic layout, as set on its Equipment page
        self.debayer_note: str = ""                # what the last preview did, for the UI to show
        # Auto-stretch strength (IMG-190), set by the slider above the histogram. Preview-only —
        # never affects current_frame, frame_stats, frame_histogram or a saved file.
        self.stretch_level: int = DEFAULT_STRETCH_LEVEL
        self._preview_generation: int = 0          # bumped by each display-setting change; stale renders are dropped
        # The Pier's current object (IMG-140): names saved frames and is written to their OBJECT keyword.
        self.object_name: str = ""
        # Page layout (IMG-120): follows the frame's shape unless the user picks one.
        self.manual_orientation: str | None = None
        # Capture settings and header context (IMG-150). Gain/offset 0 means "leave the camera
        # as configured".
        self.gain: int = 0
        self.offset: int = 0
        self.frame_context: dict = {}          # what the page knows about the rig: telescope, site, ...
        self.last_shot: dict = {}              # when and how the frame in ``current_frame`` was taken
        # Series capture and Library auto-save (IMG-150).
        self.auto_save_to_library: bool = True
        self.library_registrar = None          # anything with register_capture(path) -> id | None
        self.scratch_dir: Path | None = None
        self.series_total: int = 0
        self.series_done: int = 0
        self.stop_requested: bool = False
        self.library_ids: list = []            # catalog ids of the frames added by the last series
        self.library_note: str = ""            # why a frame did not (fully) reach the Library, for the UI
        # Live stacking (IMG-160): each frame is registered onto the first and added to a running
        # mean, so the displayed image builds up instead of each exposure replacing the last.
        self.live_stack_enabled: bool = False
        self.stacker = LiveStacker()
        # A mosaic capture's stack (IMG-180): each pane's own running stack composited onto one
        # canvas at its grid position, fresh per mosaic capture — None until the first one runs.
        self.mosaic_stacker: MosaicStacker | None = None
        self.stack_started = None              # when the stack's first sub began, for its DATE-OBS
        # The FITS sample format saved frames are written in (IMG-170, Options > Imaging).
        # "auto" (the default) is the pre-existing behaviour; loaded fresh per instance so a
        # changed setting takes effect on the next screen build rather than needing a restart.
        from galileo.imaging_settings import load_imaging_settings
        self.bitpix: int | str = load_imaging_settings()["bitpix"]
        # Framing Assistant (IMG-180): a mosaic defined and run directly from this tab.
        self.active_mosaic = None
        self._mount = None      # set by the page (Equipment > Mount's adapter) before a mosaic capture

        # Annotation overlay (IMG-200 … IMG-220): labels catalogued stars/DSOs on the preview from
        # a plate solve of ``current_frame``. Never touches current_frame/current_preview, frame_stats
        # or the Library paths (_auto_save_to_library, save_stack_to_library) — those always take the
        # raw frame/stack directly, regardless of annotate_enabled (IMG-220).
        self.annotate_enabled: bool = False
        self.last_solve = None                  # the platesolve.SolveResult behind annotated_preview
        self.annotated_preview = None            # RGB uint8 overlay, or None if none/stale
        self._annotated_frame = None             # identity of current_frame annotated_preview was built for
        self.annotate_note: str = ""             # status text for the Imaging page's Annotate hint

    # --- Annotation (IMG-200 … IMG-220) ------------------------------------

    async def solve_current_frame(self, solver):
        """Plate-solve ``current_frame`` with *solver*, updating ``last_solve`` — the plumbing
        shared between Annotate (IMG-200, via :meth:`annotate_current_frame`) and the Framing
        Assistant's Determine Rotation control (FRAME-100), which reads back
        ``last_solve.rotation_deg`` when neither a rotator nor an earlier solve already gives it
        the frame's position angle. Caller is responsible for checking ``current_frame`` is set
        first — this assumes it is."""
        import tempfile
        from pathlib import Path

        from galileo.platesolve import _write_frame
        path = Path(tempfile.gettempdir()) / "galileo_solve_current.fits"
        await asyncio.to_thread(_write_frame, self.current_frame, path, self.frame_metadata())
        self.last_solve = await solver.solve(path)
        return self.last_solve

    async def annotate_current_frame(self, solver) -> None:
        """Plate-solve ``current_frame`` with *solver* and build the labelled overlay from the
        solution and Galileo's bundled star/DSO catalogs (`galileo.annotate`). Solving happens
        here — not reused from the Solve screen — so Annotate works on whatever is on screen
        without a separate solve step first. Sets ``annotated_preview``/``last_solve``/
        ``annotate_note``; ``current_frame`` and ``current_preview`` are never touched."""
        from galileo.annotate import annotate_preview
        frame, preview = self.current_frame, self.current_preview
        if frame is None or preview is None:
            self.annotate_note = "Capture or load a frame first."
            return
        await self.solve_current_frame(solver)
        overlay, note = annotate_preview(preview, self.last_solve)
        self.annotated_preview, self._annotated_frame, self.annotate_note = overlay, frame, note

    def set_annotate_enabled(self, enabled: bool) -> None:
        """Turn the Annotate overlay on or off. Turning it on does not itself solve or render —
        the page starts that (off the UI thread, since solving is an external process) via
        :meth:`annotate_current_frame` when there is no current overlay to show yet."""
        self.annotate_enabled = enabled

    @property
    def display_preview(self):
        """What the Imaging page should show: the annotated overlay when Annotate is on and
        still valid for ``current_frame``, else the plain auto-stretch preview."""
        if self.annotate_enabled and self._annotated_frame is self.current_frame and self.annotated_preview is not None:
            return self.annotated_preview
        return self.current_preview

    @property
    def save_preview(self):
        """The annotated overlay Save Frame/Save Stack should write instead of raw FITS, or
        ``None`` when Annotate is off or stale for ``current_frame`` (IMG-210) — never read by
        the Library paths, which always save the raw frame/stack regardless (IMG-220)."""
        if self.annotate_enabled and self._annotated_frame is self.current_frame:
            return self.annotated_preview
        return None

    @property
    def save_file_filter(self) -> str:
        """The Save Frame/Save Stack file dialog's filter: PNG while an annotated overlay is
        what will actually be written (IMG-210), else the ordinary FITS filter."""
        return "PNG files (*.png)" if self.save_preview is not None else "FITS files (*.fits *.fit)"

    # --- Framing Assistant (IMG-180, FRAME-070) ---------------------------

    def open_framing_assistant(self, profile=None):
        """Open a Framing Assistant against this tab's own optical train
        (FRAME-070's Imaging-tab entry point) — *profile* is the active Pier's
        optical-train data, when known, else reference defaults are used."""
        from galileo.planning.framing import open_from_imaging_tab
        return open_from_imaging_tab(self, profile=profile)

    def run_mosaic_from_framing(self, assistant) -> None:
        """Adopt *assistant*'s defined mosaic as this tab's active capture
        target (IMG-180, traces to FRAME-090) — a mosaic attaches as one unit,
        per FRAME-050."""
        self.active_mosaic = assistant.mosaic

    # --- Naming (IMG-140) ------------------------------------------------

    @property
    def file_stem(self) -> str:
        """What saved frames are called: the current object's name, else ``frame``."""
        return safe_file_stem(self.object_name) or "frame"

    def suggested_filename(self) -> str:
        """A name for the frame being saved, e.g. ``M_31_20260921T213045.fits`` — ``.png`` while
        Annotate will save the labelled overlay instead of the raw frame (IMG-210)."""
        ext = "png" if self.save_preview is not None else "fits"
        return f"{self.file_stem}_{datetime.datetime.now():%Y%m%dT%H%M%S}.{ext}"

    # --- FITS header (IMG-150) --------------------------------------------

    def frame_metadata(self) -> dict:
        """Every header value known for the frame in ``current_frame``, keyed as
        ``galileo.metadata.FitsMetadataWriter`` expects: the rig (``frame_context``, filled in by the
        page), the shot (exposure, times, gain, filter, frame type) and the sensor temperature.
        Includes each card the Library builds file and folder names from — ``IMAGETYP``, ``OBJECT``,
        ``TELESCOP``, ``INSTRUME``, ``FILTER``, ``DATE-OBS``, ``EXPTIME``, ``XBINNING``, ``YBINNING``
        and ``CCD-TEMP`` — wherever they can be known."""
        meta = {key: value for key, value in self.frame_context.items() if value not in (None, "")}
        meta["software"] = "Galileo"
        # The Library's own placeholder, so a frame is never filed under a blank telescope or camera.
        meta.setdefault("telescope", "Unknown")
        meta.setdefault("instrument", "Unknown")
        shot = self.last_shot
        if shot:
            frame_type = shot["frame_type"]
            meta.update(frame_type=frame_type, exposure_s=shot["duration"],
                        date_obs_utc=_fits_time(shot["started"]), date_end_utc=_fits_time(shot["ended"]))
            if shot.get("gain"):
                meta["gain"] = shot["gain"]
            if shot.get("offset"):
                meta["offset"] = shot["offset"]
            meta.setdefault("binning_x", 1)
            meta.setdefault("binning_y", 1)
            # Only light frames are of the object; the Library files calibration frames under their type.
            if frame_type.lower().startswith("light"):
                if self.object_name:
                    meta["object"] = self.object_name
            else:
                meta.pop("object", None)
            # Light and flat frames are filed by filter; the Library's own name for "none" is OSC.
            if not frame_type.lower().startswith(("dark", "bias")):
                meta["filter"] = shot["filter"] or "OSC"
        elif self.object_name:
            meta["object"] = self.object_name
        temperature = self._sensor_temperature()
        if temperature is not None:
            meta["ccd_temp_c"] = temperature
        return meta

    def _sensor_temperature(self) -> float | None:
        """The camera's sensor temperature in °C, or ``None`` if it can't say."""
        getter = getattr(self._camera, "get_temperature", None)
        if getter is None:
            return None
        try:
            value = getter()
        except Exception:
            return None
        return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None

    # --- Series capture and Library auto-save (IMG-150) ------------------

    def request_stop(self) -> None:
        """Ask a running series to end after the frame in progress (the caller aborts that exposure)."""
        self.stop_requested = True

    async def capture_series(
        self,
        count: int,
        duration: float,
        filter_name: str = "",
        frame_type: str = "Light",
        on_frame_start=None,
        on_frame_done=None,
    ) -> list:
        """Take *count* frames one after another with the settings given (and ``gain``), showing each
        as it arrives and — when ``auto_save_to_library`` is on — adding each to the Library before the
        next exposure starts. Returns the catalog ids of the frames added. *on_frame_start* and
        *on_frame_done* are called with ``(index, count)`` from the thread running this coroutine.
        A stop (``request_stop``) ends the series.

        With live stacking on and more than two frames asked for (IMG-160), each frame is instead
        registered onto the first and added to a running mean, which becomes the displayed frame —
        so the preview, statistics and histogram follow the stack as it builds. Each individual sub
        still goes to the Library; the stack is saved separately with Save Stack."""
        count = max(1, int(count))
        self.stop_requested = False
        self.series_total, self.series_done = count, 0
        self.library_ids, self.library_note = [], ""
        # Only a run of more than two frames stacks; below that there is nothing to build up.
        stacking = self.live_stack_enabled and count >= LIVE_STACK_MIN_FRAMES
        if stacking:
            self.stacker.reset()
            self.stack_started = None
        for index in range(1, count + 1):
            if self.stop_requested:
                break
            if on_frame_start is not None:
                on_frame_start(index, count)
            try:
                # When stacking, it's the stack that gets shown and measured, not each sub.
                await self.capture_and_preview(duration, filter_name, frame_type, gain=self.gain or None,
                                               offset=self.offset or None, analyse=not stacking)
            except Exception:
                if self.stop_requested:
                    break
                raise
            self.series_done = index
            # The sub is what goes to the Library; the stack is kept separately and saved on request.
            if self.auto_save_to_library:
                self._auto_save_to_library(index)
            if stacking:
                await self._stack_current_frame()
            if on_frame_done is not None:
                on_frame_done(index, count)
        return list(self.library_ids)

    # --- Mosaic capture (IMG-180, FRAME-090) ------------------------------

    async def capture_mosaic(
        self,
        exposures_per_pane: int,
        duration: float,
        filter_name: str = "",
        frame_type: str = "Light",
        on_slew_start=None,
        on_frame_start=None,
        on_frame_done=None,
    ) -> list:
        """Capture ``active_mosaic`` (set by :meth:`run_mosaic_from_framing`): one exposure per
        pane per pass, in the pane-major order ``galileo.planning.framing.mosaic_capture_order``
        returns, re-slewing the mount to each pane's centre before its exposure — the re-slew
        *is* the dither between passes, so no separate guider-dither command is sent. Needs a
        mount (set on ``_mount``, mirroring how the page refreshes ``_camera``) and a defined
        ``active_mosaic``; raises ``ValueError`` without either. *on_slew_start* is called with
        ``(index, count)`` before each re-slew, mirroring *on_frame_start*/*on_frame_done*
        around each exposure. Returns the catalog ids of the frames added, across every pane —
        stopping (``request_stop``) ends the series after the exposure in progress, same as
        ``capture_series``.

        With live stacking on (IMG-160/IMG-180), each pane's frame is registered onto that pane's
        own running stack and composited into a mosaic-sized canvas at its grid position, which
        becomes the displayed frame — so the preview (and its statistics/histogram) show the whole
        mosaic's extent filling in pane by pane, rather than one pane's own frame at a time. Unlike
        :meth:`capture_series`, this has no minimum-frame-count gate: a mosaic's point is the
        panes' geometry, not building signal-to-noise on one pointing, so it composites from the
        very first exposure. Each individual sub still goes to the Library; the mosaic composite
        is saved separately with Save Stack, same as a single-pointing stack."""
        if self.active_mosaic is None:
            raise ValueError("No mosaic is defined — define one from the Framing Assistant first.")
        if self._mount is None:
            raise ValueError("No mount is connected — a mosaic capture needs one to move between panes.")

        from galileo.planning.framing import mosaic_capture_order
        from galileo.planning.star_atlas import julian_date, precess_from_j2000
        from galileo.tracking import wait_for_slew
        import datetime as _dt

        mosaic = self.active_mosaic
        panels = {p.pane_index: p for p in mosaic.panels}
        steps = mosaic_capture_order(mosaic, max(1, int(exposures_per_pane)))
        count = len(steps)
        self.stop_requested = False
        self.series_total, self.series_done = count, 0
        self.library_ids, self.library_note = [], ""

        stacking = self.live_stack_enabled
        if stacking:
            self.mosaic_stacker = MosaicStacker(mosaic.cols, mosaic.rows, mosaic.overlap_pct)
            self.stack_started = None

        for index, step in enumerate(steps, start=1):
            if self.stop_requested:
                break
            if step.requires_reslew:
                if on_slew_start is not None:
                    on_slew_start(index, count)
                pane = panels[step.pane_index]
                ra_deg, dec_deg = pane.ra_deg, pane.dec_deg
                if (await self._mount.get_status() or {}).get("equatorial_system") != "J2000":
                    jd = julian_date(_dt.datetime.now(_dt.UTC).replace(tzinfo=None))
                    ra_deg, dec_deg = (float(v) for v in precess_from_j2000(ra_deg, dec_deg, jd))
                await self._mount.slew_to_coordinates(ra_deg, dec_deg)
                await wait_for_slew(self._mount)
            if on_frame_start is not None:
                on_frame_start(index, count)
            try:
                # When stacking, it's the mosaic composite that gets shown and measured, not each pane's sub.
                await self.capture_and_preview(duration, filter_name, frame_type, gain=self.gain or None,
                                               offset=self.offset or None, analyse=not stacking)
            except Exception:
                if self.stop_requested:
                    break
                raise
            self.series_done = index
            # The sub is what goes to the Library; the mosaic composite is kept separately.
            if self.auto_save_to_library:
                self._auto_save_to_library(index)
            if stacking:
                await self._stack_current_mosaic_pane(step.pane_index)
            if on_frame_done is not None:
                on_frame_done(index, count)
        return list(self.library_ids)

    async def _stack_current_mosaic_pane(self, pane_index: int) -> None:
        """Add the frame just captured to pane *pane_index*'s own running stack within the active
        mosaic composite, and show the whole composited canvas in the frame's place — so the
        preview, statistics and histogram track the growing mosaic rather than just that pane."""
        assert self.mosaic_stacker is not None
        if self.stack_started is None:
            self.stack_started = self.last_shot.get("started")
        canvas = await self.mosaic_stacker.add_async(pane_index, self.current_frame,
                                                      self.last_shot.get("duration", 0.0))
        if canvas is not None:
            self.current_frame = canvas
            await self._analyse_current_frame()

    async def _stack_current_frame(self) -> None:
        """Add the frame just captured to the live stack and show the stack in its place."""
        if self.stack_started is None:
            self.stack_started = self.last_shot.get("started")
        await self.stacker.add_async(self.current_frame, self.last_shot.get("duration", 0.0))
        stacked = self.stacker.result
        if stacked is not None:
            self.current_frame = stacked
            await self._analyse_current_frame()

    # --- The stack (IMG-160, IMG-180) --------------------------------------

    @property
    def active_stacker(self) -> LiveStacker | MosaicStacker:
        """Whichever stack currently holds frames: the mosaic composite from the most recent
        mosaic capture, or the single-pointing stack from ``capture_series``, whichever has data.
        A mosaic capture always takes priority once it has started one, since ``capture_series``
        and ``capture_mosaic`` are never run at once and the mosaic composite is what a mosaic's
        Save Stack should mean."""
        if self.mosaic_stacker is not None and self.mosaic_stacker.frames:
            return self.mosaic_stacker
        return self.stacker

    @property
    def stack_frame_count(self) -> int:
        return self.active_stacker.frames

    def stack_metadata(self) -> dict:
        """The header for the stack: the last sub's, with the exposure cards describing the stack —
        ``EXPTIME`` stays the single-sub exposure (which is what the Library files by), with the
        integration time in ``EXPTOTAL`` and the number of frames in ``NCOMBINE``."""
        meta = self.frame_metadata()
        meta["frames_combined"] = self.active_stacker.frames
        meta["total_exposure_s"] = self.active_stacker.total_exposure_s
        if self.stack_started is not None:
            meta["date_obs_utc"] = _fits_time(self.stack_started)      # the stack covers from the first sub
        return meta

    def save_stack(self, path: Path | str) -> None:
        """Write the stack to *path*: the annotated overlay as PNG while Annotate has one current
        for it (IMG-210), else plain FITS with the stack's own header (IMG-160)."""
        if self.active_stacker.result is None:
            raise ValueError("There is no stack to save.")
        overlay = self.save_preview
        if overlay is not None:
            _save_png(overlay, Path(path))
            return
        _save_fits(self.active_stacker.result, Path(path), self.object_name, self.stack_metadata(), self.bitpix)

    def stack_filename(self) -> str:
        """A name for the stack, e.g. ``M_31_stack_12x30s_20260921T213045.fits`` — ``.png`` while
        Annotate will save the labelled overlay instead (IMG-210). Only for Save Stack's own file
        dialog — the Library always uses :meth:`_stack_fits_filename` (IMG-220)."""
        ext = "png" if self.save_preview is not None else "fits"
        return self._stack_fits_filename(ext)

    def _stack_fits_filename(self, ext: str = "fits") -> str:
        exposure = self.last_shot.get("duration", 0.0)
        return (f"{self.file_stem}_stack_{self.active_stacker.frames}x{exposure:g}s_"
                f"{datetime.datetime.now():%Y%m%dT%H%M%S}.{ext}")

    def save_stack_to_library(self) -> str | None:
        """Write the stack to the scratch folder and register it in the Library, which files it in
        the repository. Always the raw stack as FITS, regardless of Annotate (IMG-220) — returns
        its catalog id, or ``None`` if it was not registered (the reason is in ``library_note``)."""
        if self.active_stacker.result is None:
            raise ValueError("There is no stack to save.")
        self.library_note = ""
        meta = self.stack_metadata()
        if not meta.get("object"):
            meta["object"] = "Unknown"
            self.library_note = "No current object, so the stack was filed under 'Unknown'."
        path = self._scratch_folder() / self._stack_fits_filename()
        _save_fits(self.active_stacker.result, path, self.object_name, meta, self.bitpix)
        if not path.exists():
            self.library_note = "The stack could not be written to the scratch folder — see the log."
            return None
        registrar = self.library_registrar
        if registrar is None:
            from galileo.library.registrar import LibraryRegistrar
            registrar = self.library_registrar = LibraryRegistrar()
        file_id = registrar.register_capture(path)
        if not file_id:
            self.library_note = f"The stack was not added to the Library and is at {path} — see the log."
        return file_id

    def _scratch_folder(self) -> Path:
        if self.scratch_dir is not None:
            return Path(self.scratch_dir)
        from galileo.library.config import get_temp_folder
        return Path(get_temp_folder()) / "galileo-capture"

    def _auto_save_to_library(self, index: int) -> None:
        """Write the current frame, with its full header, to the scratch folder and register it in
        the Library, which moves it into the repository. A frame that can't be registered stays in
        the scratch folder (``last_saved_path``) and ``library_note`` says why."""
        meta = self.frame_metadata()
        frame_type = meta.get("frame_type", "Light")
        if frame_type.lower().startswith("light") and not meta.get("object"):
            meta["object"] = "Unknown"          # the Library can't file a light frame without one
            self.library_note = "No current object, so frames were filed under 'Unknown' — pick one in the Star Atlas."
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S")
        stem = safe_file_stem(meta.get("object")) or self.file_stem
        path = self._scratch_folder() / f"{stem}_{frame_type}_{stamp}_{index:03d}.fits"
        _save_fits(self.current_frame, path, self.object_name, meta, self.bitpix)
        if not path.exists():
            self.library_note = "The frame could not be written to the scratch folder — see the log."
            return
        registrar = self.library_registrar
        if registrar is None:
            from galileo.library.registrar import LibraryRegistrar
            registrar = self.library_registrar = LibraryRegistrar()
        file_id = registrar.register_capture(path)
        if file_id:
            self.library_ids.append(file_id)
        else:
            self.last_saved_path = path
            self.library_note = f"The frame was not added to the Library and is at {path} — see the log."

    # --- Layout orientation (IMG-120) ------------------------------------

    @property
    def detected_orientation(self) -> str:
        """The current frame's own orientation, whatever the user chose."""
        return frame_orientation(self.current_frame)

    @property
    def orientation(self) -> str:
        """The orientation the page should be laid out for: the user's choice
        if they made one, else the current frame's."""
        return self.manual_orientation or self.detected_orientation

    def set_manual_orientation(self, orientation: str | None) -> None:
        """Force ``"portrait"`` or ``"landscape"``; ``None`` (or anything else)
        goes back to following the frame."""
        self.manual_orientation = orientation if orientation in (PORTRAIT, LANDSCAPE) else None

    # --- Capture ---------------------------------------------------------

    async def capture_and_preview(
        self,
        duration: float,
        filter_name: str = "",
        frame_type: str = "Light",
        save_dir: Path | str | None = None,
        gain: int | None = None,
        offset: int | None = None,
        analyse: bool = True,
    ) -> None:
        """Expose, download, stretch, and cache the current frame (IMG-010 … IMG-030).

        ``analyse=False`` skips the preview, statistics and histogram, for a caller that is about
        to replace the frame anyway (a live stack shows the stack, not the sub)."""

        self._capture_status = "exposing"
        self.capture_status = "exposing"

        started = datetime.datetime.now(datetime.UTC)
        options = {}
        if gain:
            options["gain"] = int(gain)
        if offset:
            options["offset"] = int(offset)
        await self._camera.start_exposure(duration=duration, frame_type=frame_type, **options)
        data = await self._camera.get_image_array()
        self.last_shot = {"started": started, "ended": datetime.datetime.now(datetime.UTC),
                          "duration": float(duration), "frame_type": frame_type,
                          "filter": filter_name, "gain": int(gain) if gain else None,
                          "offset": int(offset) if offset else None}

        self.current_frame = data
        self.last_saved_array = data

        if data is not None and analyse:
            await self._analyse_current_frame()

        self._capture_status = "preview_ready"
        self.capture_status = "preview_ready"

        if save_dir is not None:
            out_dir = Path(save_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / f"{self.file_stem}_{datetime.datetime.utcnow().strftime('%H%M%S')}.fits"
            _save_fits(data, p, self.object_name, self.frame_metadata(), self.bitpix)
            self.last_saved_path = p

    async def capture_single(self, duration: float, filter_name: str = "", frame_type: str = "Light"):
        """Manual single-exposure capture independent of any sequence (IMG-070)."""
        await self._camera.start_exposure(duration=duration, frame_type=frame_type)
        data = await self._camera.get_image_array()
        self.current_frame = data
        return data

    # --- Debayer (IMG-110) -----------------------------------------------

    def set_debayer(self, enabled: bool, rebuild: bool = True) -> None:
        """Turn debayering of the displayed frame on or off, re-rendering the
        current frame at once (no new exposure) unless ``rebuild`` is false —
        the Imaging page passes false and re-renders on a worker thread instead
        (:meth:`render_preview` / :meth:`apply_preview`), since a debayer and
        stretch takes seconds on a large frame (NFR-PERF-020). The raw frame —
        what statistics, the histogram and Save Frame use — is never changed."""
        self.debayer_enabled = enabled
        self._preview_generation += 1
        if rebuild:
            self._rebuild_preview()

    def render_preview(self) -> tuple | None:
        """Render the preview for the current frame and display settings, without showing it.
        Safe to call from a worker thread: it only reads the service. Returns an opaque result for
        :meth:`apply_preview`, or ``None`` if there is no frame."""
        generation, frame = self._preview_generation, self.current_frame
        if frame is None:
            return None
        preview, note = self._render_preview(frame)
        return generation, frame, preview, note

    def apply_preview(self, rendered: tuple | None) -> bool:
        """Show a preview from :meth:`render_preview`, unless the frame or display settings have
        changed since it was started (a newer render is on its way). Returns whether it was used."""
        if rendered is None:
            return False
        generation, frame, preview, note = rendered
        if generation != self._preview_generation or frame is not self.current_frame:
            return False
        self.current_preview, self.debayer_note = preview, note
        return True

    def set_stretch(self, level: int, rebuild: bool = True) -> None:
        """Set the auto-stretch slider's strength (0..100, IMG-190), re-rendering the current
        frame at once unless ``rebuild`` is false — the Imaging page passes false and re-renders
        on a worker thread instead, the same as :meth:`set_debayer`."""
        self.stretch_level = max(0, min(100, int(level)))
        self._preview_generation += 1
        if rebuild:
            self._rebuild_preview()

    def set_bayer_pattern(self, pattern: str | None, rebuild: bool = True) -> None:
        """Set the mosaic layout used to debayer (``RGGB``, ``GRBG``, ``GBRG``
        or ``BGGR``), re-rendering the current frame unless ``rebuild`` is
        false (e.g. just before a capture, which replaces it anyway).
        Anything else — ``None``, or a bad value in a saved config — falls
        back to the default."""
        pattern = (pattern or "").strip().upper()
        self.bayer_pattern = pattern if pattern in BAYER_PATTERNS else DEFAULT_PATTERN
        self._preview_generation += 1
        if rebuild:
            self._rebuild_preview()

    def _rebuild_preview(self) -> None:
        """Rebuild the 8-bit preview from ``current_frame``, debayered if asked to."""
        if self.current_frame is not None:
            self.current_preview, self.debayer_note = self._render_preview(self.current_frame)

    def _render_preview(self, data) -> tuple:
        """``(preview, debayer note)`` for *data*: the 8-bit stretch, debayered if asked to."""
        shown, note = data, ""
        if self.debayer_enabled:
            shown, note = self._debayered(data)
        return _auto_stretch(shown, self.stretch_level), note

    async def _analyse_current_frame(self) -> None:
        """Build the preview, statistics and histogram for ``current_frame``, all off the UI thread
        and at the same time (NFR-PERF-020).

        The statistics include SEP star detection, which holds the GIL for seconds on a full frame,
        so they go to the CPU worker pool. The preview and histogram are numpy, which releases the
        GIL, so a thread is enough for them and saves copying the frame to another process."""
        frame = self.current_frame
        if frame is None:
            return
        (preview, note), stats, histogram = await asyncio.gather(
            asyncio.to_thread(self._render_preview, frame),
            run_cpu(_compute_stats, frame),
            asyncio.to_thread(_compute_histogram, frame),
        )
        self.current_preview, self.debayer_note = preview, note
        self.frame_stats, self.frame_histogram, self._analysed_frame = stats, histogram, frame

    def _debayered(self, data) -> tuple:
        """``(image, note)``: *data* debayered with ``bayer_pattern``, or
        unchanged with a note saying why not. Wrong colours mean the pattern
        set on the camera's Equipment page doesn't match the sensor."""
        if data.ndim != 2:
            return data, "Frame is already colour — not debayered."
        return debayer(data, self.bayer_pattern), f"Debayered ({self.bayer_pattern})."

    # --- Statistics (IMG-040) --------------------------------------------

    def get_frame_stats(self) -> dict:
        """Statistics for ``current_frame``: the ones worked out when it arrived, or, for a frame
        that didn't come through the capture pipeline, computed now."""
        if self.current_frame is None:
            return {}
        if self.frame_stats is not None and self._analysed_frame is self.current_frame:
            return self.frame_stats
        return _compute_stats(self.current_frame)

    # --- Histogram (IMG-030) ---------------------------------------------

    def get_histogram(self) -> dict:
        if self.current_frame is None:
            return {"bins": [], "counts": []}
        if self.frame_histogram is not None and self._analysed_frame is self.current_frame:
            return self.frame_histogram
        return _compute_histogram(self.current_frame)

    # --- View controls (IMG-060) -----------------------------------------

    def set_zoom(self, factor: float) -> None:
        self.zoom_factor = factor

    def set_pan_offset(self, dx: int, dy: int) -> None:
        self.pan_offset = (dx, dy)

    def reset_view(self) -> None:
        self.zoom_factor = 1.0
        self.pan_offset = (0, 0)

    # --- Panel layout (IMG-080) ------------------------------------------

    def set_panel_layout(self, layout: dict) -> None:
        self._panel_layout = dict(layout)

    def get_panel_layout(self) -> dict:
        return dict(self._panel_layout)

    # --- Save current frame (IMG-100) ------------------------------------

    def save_current_frame(self, path: Path | str) -> None:
        """Write ``current_frame`` to *path*: the annotated overlay as PNG while Annotate has one
        current for it (IMG-210), else plain FITS as before."""
        overlay = self.save_preview
        if overlay is not None:
            _save_png(overlay, Path(path))
            return
        _save_fits(self.current_frame, Path(path), self.object_name, self.frame_metadata(), self.bitpix)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auto_stretch(data, stretch_level: int = DEFAULT_STRETCH_LEVEL):
    """Return an 8-bit auto-stretched preview array — ``(height, width)`` for
    a single plane, ``(height, width, 3)`` for colour. Each colour plane is
    stretched on its own, which also balances the background: a Bayer sensor
    has twice as many green pixels, so a common stretch would tint the image.

    *stretch_level* (0..100, IMG-190) sets how much of each plane's low/high
    tail is clipped to black/white before the remainder is stretched to fill
    the full range — higher clips more, giving a brighter, higher-contrast
    but more washed-out preview; lower keeps more of the original dynamic
    range."""
    try:
        import numpy as np
        if data is None:
            return None
        d = data.astype(np.float32)
        if d.ndim == 3:
            return np.stack([_auto_stretch(d[..., i], stretch_level) for i in range(d.shape[2])], axis=-1)
        margin = max(0, min(100, stretch_level)) / 40.0   # 0 .. 2.5% clipped from each tail
        lo, hi = float(np.percentile(d, margin)), float(np.percentile(d, 100.0 - margin))
        stretched = np.clip((d - lo) / (hi - lo + 1e-9), 0, 1)
        return (stretched * 255).astype(np.uint8)
    except Exception:
        return None


def _compute_stats(data) -> dict:
    try:
        import numpy as np
        from galileo.autofocus import _compute_hfr
        d = data.astype(np.float32)
        return {
            "mean": float(np.mean(d)),
            "median": float(np.median(d)),
            "min": float(np.min(d)),
            "max": float(np.max(d)),
            "star_count": 0,
            "hfr": _compute_hfr(d),
        }
    except Exception:
        return {"mean": 0, "median": 0, "min": 0, "max": 0, "star_count": 0, "hfr": 0}


def _compute_histogram(data) -> dict:
    try:
        import numpy as np
        counts, bins = np.histogram(data.flatten(), bins=256)
        return {"bins": bins[:-1].tolist(), "counts": counts.tolist()}
    except Exception:
        return {"bins": [], "counts": []}


def _fits_time(moment: datetime.datetime) -> str:
    """*moment* (UTC) as a FITS date-time, to the millisecond."""
    moment = moment.astimezone(datetime.UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}"


def _save_fits(data, path: Path, object_name: str = "", metadata: dict | None = None,
               bitpix: int | str | None = None) -> None:
    """Write *data* to *path* as FITS with every card *metadata* provides (see
    ``galileo.metadata.FitsMetadataWriter``), plus ``OBJECT`` from *object_name* if the metadata has
    none. *bitpix* is the desired sample format (IMG-170); ``None``/``"auto"`` picks one automatically.
    Failures are logged, not raised, so callers check that the file exists."""
    try:
        from galileo.metadata import FitsMetadataWriter
        meta = dict(metadata or {})
        if object_name and "object" not in meta:
            meta["object"] = object_name
        FitsMetadataWriter(output_dir=path.parent).write(data, meta, filename=path.name, bitpix=bitpix)
    except Exception:
        logger.exception("Failed to save FITS frame to %s", path)


def _save_png(data, path: Path) -> None:
    """Write *data* — an annotated RGB ``uint8`` overlay (IMG-210) — as PNG. An annotated view is
    a rendered picture, not scientific pixel data, so it never goes through the FITS pipeline the
    raw frame/stack use: a colour FITS cube is legal but inconsistently read across tools (see
    ``galileo.platesolve.frame_for_solver``), which is exactly the kind of file this must not
    produce. *path* is redirected to a ``.png`` name if it wasn't already one — the Save Frame/
    Save Stack dialogs already default to one (``ImagingService.save_file_filter``), but a path
    typed in by hand may not be. Failures are logged, not raised, so callers check the file exists."""
    try:
        import numpy as np
        from PIL import Image
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            path = path.with_suffix(".png")
        Image.fromarray(np.asarray(data).astype(np.uint8), mode="RGB").save(path)
    except Exception:
        logger.exception("Failed to save annotated image to %s", path)
