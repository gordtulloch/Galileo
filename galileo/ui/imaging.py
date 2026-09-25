# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Imaging tab service — preview, statistics, manual capture (IMG-010 … IMG-100)."""

from __future__ import annotations

import asyncio
import datetime
import logging
import math
from pathlib import Path

from galileo.current_object import safe_file_stem
from galileo.debayer import BAYER_PATTERNS, DEFAULT_PATTERN, debayer
from galileo.livestack import LIVE_STACK_MIN_FRAMES, LiveStacker

logger = logging.getLogger(__name__)

DEFAULT_GAIN = 110      # what the Imaging page's Gain field starts at (IMG-150)

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
        self.last_saved_array = None
        self.last_saved_path: Path | None = None
        self.zoom_factor: float = 1.0
        self.pan_offset: tuple[int, int] = (0, 0)
        self.star_overlay_enabled: bool = False
        self.capture_status: str = "idle"
        self._panel_layout: dict = {}
        self._capture_status: str = "idle"
        # Debayering (IMG-110) only changes the preview; current_frame stays the camera's raw mosaic.
        self.debayer_enabled: bool = False
        self.bayer_pattern: str = DEFAULT_PATTERN  # the camera's mosaic layout, as set on its Equipment page
        self.debayer_note: str = ""                # what the last preview did, for the UI to show
        # The Pier's current object (IMG-140): names saved frames and is written to their OBJECT keyword.
        self.object_name: str = ""
        # Page layout (IMG-120): follows the frame's shape unless the user picks one.
        self.manual_orientation: str | None = None
        # Capture settings and header context (IMG-150). Gain 0 means "leave the camera as configured".
        self.gain: int = 0
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
        self.stack_started = None              # when the stack's first sub began, for its DATE-OBS
        # The FITS sample format saved frames are written in (IMG-170, Options > Imaging).
        # "auto" (the default) is the pre-existing behaviour; loaded fresh per instance so a
        # changed setting takes effect on the next screen build rather than needing a restart.
        from galileo.imaging_settings import load_imaging_settings
        self.bitpix: int | str = load_imaging_settings()["bitpix"]
        # Framing Assistant (IMG-180): a mosaic defined and run directly from this tab.
        self.active_mosaic = None
        self._mount = None      # set by the page (Equipment > Mount's adapter) before a mosaic capture

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
        """A name for the frame being saved, e.g. ``M_31_20260921T213045.fits``."""
        return f"{self.file_stem}_{datetime.datetime.now():%Y%m%dT%H%M%S}.fits"

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
                await self.capture_and_preview(duration, filter_name, frame_type, gain=self.gain or None)
            except Exception:
                if self.stop_requested:
                    break
                raise
            self.series_done = index
            # The sub is what goes to the Library; the stack is kept separately and saved on request.
            if self.auto_save_to_library:
                self._auto_save_to_library(index)
            if stacking:
                self._stack_current_frame()
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
        ``capture_series``."""
        if self.active_mosaic is None:
            raise ValueError("No mosaic is defined — define one from the Framing Assistant first.")
        if self._mount is None:
            raise ValueError("No mount is connected — a mosaic capture needs one to move between panes.")

        from galileo.planning.framing import mosaic_capture_order
        from galileo.planning.star_atlas import julian_date, precess_from_j2000
        from galileo.tracking import wait_for_slew
        import datetime as _dt

        panels = {p.pane_index: p for p in self.active_mosaic.panels}
        steps = mosaic_capture_order(self.active_mosaic, max(1, int(exposures_per_pane)))
        count = len(steps)
        self.stop_requested = False
        self.series_total, self.series_done = count, 0
        self.library_ids, self.library_note = [], ""

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
                await self.capture_and_preview(duration, filter_name, frame_type, gain=self.gain or None)
            except Exception:
                if self.stop_requested:
                    break
                raise
            self.series_done = index
            if self.auto_save_to_library:
                self._auto_save_to_library(index)
            if on_frame_done is not None:
                on_frame_done(index, count)
        return list(self.library_ids)

    def _stack_current_frame(self) -> None:
        """Add the frame just captured to the live stack and show the stack in its place."""
        if self.stack_started is None:
            self.stack_started = self.last_shot.get("started")
        self.stacker.add(self.current_frame, self.last_shot.get("duration", 0.0))
        stacked = self.stacker.result
        if stacked is not None:
            self.current_frame = stacked
            self._rebuild_preview()

    # --- The stack (IMG-160) ----------------------------------------------

    @property
    def stack_frame_count(self) -> int:
        return self.stacker.frames

    def stack_metadata(self) -> dict:
        """The header for the stack: the last sub's, with the exposure cards describing the stack —
        ``EXPTIME`` stays the single-sub exposure (which is what the Library files by), with the
        integration time in ``EXPTOTAL`` and the number of frames in ``NCOMBINE``."""
        meta = self.frame_metadata()
        meta["frames_combined"] = self.stacker.frames
        meta["total_exposure_s"] = self.stacker.total_exposure_s
        if self.stack_started is not None:
            meta["date_obs_utc"] = _fits_time(self.stack_started)      # the stack covers from the first sub
        return meta

    def save_stack(self, path: Path | str) -> None:
        """Write the stack to *path* as FITS, with the stack's own header (IMG-160)."""
        if self.stacker.result is None:
            raise ValueError("There is no stack to save.")
        _save_fits(self.stacker.result, Path(path), self.object_name, self.stack_metadata(), self.bitpix)

    def stack_filename(self) -> str:
        """A name for the stack, e.g. ``M_31_stack_12x30s_20260921T213045.fits``."""
        exposure = self.last_shot.get("duration", 0.0)
        return (f"{self.file_stem}_stack_{self.stacker.frames}x{exposure:g}s_"
                f"{datetime.datetime.now():%Y%m%dT%H%M%S}.fits")

    def save_stack_to_library(self) -> str | None:
        """Write the stack to the scratch folder and register it in the Library, which files it in
        the repository. Returns its catalog id, or ``None`` if it was not registered (the reason is
        in ``library_note``)."""
        if self.stacker.result is None:
            raise ValueError("There is no stack to save.")
        self.library_note = ""
        meta = self.stack_metadata()
        if not meta.get("object"):
            meta["object"] = "Unknown"
            self.library_note = "No current object, so the stack was filed under 'Unknown'."
        path = self._scratch_folder() / self.stack_filename()
        _save_fits(self.stacker.result, path, self.object_name, meta, self.bitpix)
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
    ) -> None:
        """Expose, download, stretch, and cache the current frame (IMG-010 … IMG-030)."""

        self._capture_status = "exposing"
        self.capture_status = "exposing"

        started = datetime.datetime.now(datetime.UTC)
        options = {"gain": int(gain)} if gain else {}
        await self._camera.start_exposure(duration=duration, frame_type=frame_type, **options)
        data = await self._camera.get_image_array()
        self.last_shot = {"started": started, "ended": datetime.datetime.now(datetime.UTC),
                          "duration": float(duration), "frame_type": frame_type,
                          "filter": filter_name, "gain": int(gain) if gain else None}

        self.current_frame = data
        self.last_saved_array = data

        if data is not None:
            self._rebuild_preview()

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

    def set_debayer(self, enabled: bool) -> None:
        """Turn debayering of the displayed frame on or off, re-rendering the
        current frame at once (no new exposure). The raw frame — what
        statistics, the histogram and Save Frame use — is never changed."""
        self.debayer_enabled = enabled
        self._rebuild_preview()

    def set_bayer_pattern(self, pattern: str | None, rebuild: bool = True) -> None:
        """Set the mosaic layout used to debayer (``RGGB``, ``GRBG``, ``GBRG``
        or ``BGGR``), re-rendering the current frame unless ``rebuild`` is
        false (e.g. just before a capture, which replaces it anyway).
        Anything else — ``None``, or a bad value in a saved config — falls
        back to the default."""
        pattern = (pattern or "").strip().upper()
        self.bayer_pattern = pattern if pattern in BAYER_PATTERNS else DEFAULT_PATTERN
        if rebuild:
            self._rebuild_preview()

    def _rebuild_preview(self) -> None:
        """Rebuild the 8-bit preview from ``current_frame``, debayered if asked to."""
        data = self.current_frame
        if data is None:
            return
        shown = data
        self.debayer_note = ""
        if self.debayer_enabled:
            shown, self.debayer_note = self._debayered(data)
        self.current_preview = _auto_stretch(shown)

    def _debayered(self, data) -> tuple:
        """``(image, note)``: *data* debayered with ``bayer_pattern``, or
        unchanged with a note saying why not. Wrong colours mean the pattern
        set on the camera's Equipment page doesn't match the sensor."""
        if data.ndim != 2:
            return data, "Frame is already colour — not debayered."
        return debayer(data, self.bayer_pattern), f"Debayered ({self.bayer_pattern})."

    # --- Statistics (IMG-040) --------------------------------------------

    def get_frame_stats(self) -> dict:
        if self.current_frame is None:
            return {}
        return _compute_stats(self.current_frame)

    # --- Histogram (IMG-030) ---------------------------------------------

    def get_histogram(self) -> dict:
        if self.current_frame is None:
            return {"bins": [], "counts": []}
        return _compute_histogram(self.current_frame)

    # --- View controls (IMG-060) -----------------------------------------

    def set_zoom(self, factor: float) -> None:
        self.zoom_factor = factor

    def set_pan_offset(self, dx: int, dy: int) -> None:
        self.pan_offset = (dx, dy)

    def reset_view(self) -> None:
        self.zoom_factor = 1.0
        self.pan_offset = (0, 0)

    # --- Star overlay (IMG-050) -------------------------------------------

    def set_star_overlay(self, enabled: bool) -> None:
        self.star_overlay_enabled = enabled

    # --- Panel layout (IMG-080) ------------------------------------------

    def set_panel_layout(self, layout: dict) -> None:
        self._panel_layout = dict(layout)

    def get_panel_layout(self) -> dict:
        return dict(self._panel_layout)

    # --- Save current frame (IMG-100) ------------------------------------

    def save_current_frame(self, path: Path | str) -> None:
        _save_fits(self.current_frame, Path(path), self.object_name, self.frame_metadata(), self.bitpix)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auto_stretch(data):
    """Return an 8-bit auto-stretched preview array — ``(height, width)`` for
    a single plane, ``(height, width, 3)`` for colour. Each colour plane is
    stretched on its own, which also balances the background: a Bayer sensor
    has twice as many green pixels, so a common stretch would tint the image."""
    try:
        import numpy as np
        if data is None:
            return None
        d = data.astype(np.float32)
        if d.ndim == 3:
            return np.stack([_auto_stretch(d[..., i]) for i in range(d.shape[2])], axis=-1)
        lo, hi = float(np.percentile(d, 0.5)), float(np.percentile(d, 99.5))
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
