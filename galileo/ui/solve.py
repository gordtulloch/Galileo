# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Solve screen (PLT-070): plate solving, with the frame being solved and its results on show.

Laid out after the reference solve screen (assets/samples/solve.png): the solver controls,
telescope and solution coordinates and capture options down the left; the frame being solved
above a table of solutions and a plot of their error on the right; a timestamped log along
the bottom. The log along the bottom is the application's live log tail, as on the Equipment
screens; the workflow's progress reaches it through the ordinary logger.

The page shows *every* solve, not only the ones started from its own buttons: it listens for
``SolveStartedEvent``/``SolveCompleteEvent`` on the event bus, which ``PlateSolver`` publishes
for each solve. Bus handlers run on whichever thread is solving, so they only gather data
there and hand it to the UI thread by signal — no widget is touched off it.

While the page is not on screen it does no work on the UI: no image is decoded or drawn, the
mount is not polled, the log tail is not refreshed, no widget changes. The results themselves are still recorded (they are a
few numbers), and the page catches up from them when it is shown again.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import threading

import numpy as np
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QWidget,
)

from galileo.bus import SolveCompleteEvent, SolveStartedEvent, get_bus
from galileo.current_object import get_current_objects
from galileo.observatory import make_pier_solver
from galileo.platesolve import (
    PlateSolver,
    SolveAction,
    SolveSettings,
    SolveWorkflow,
    angular_offset_arcsec,
    j2000_to_mount_frame,
    mount_frame_to_j2000,
    nearest_object_name,
)
from galileo.polaralign import PolarAlignProgress, PolarAlignSettings, PolarAlignWorkflow, format_angle
from galileo.ui.solve_widgets import (  # noqa: F401  (re-exported: these used to live in this module)
    SolveErrorPlot,
    SolveImageView,
    SolveRow,
    _nice_step,
)
from galileo.ui.solve_build import (  # noqa: F401  (re-exported: constants/helpers that used to live in this module)
    SolveBuildMixin,
    _heading_box,
    _value_label,
)
from galileo.ui.solve_results import (  # noqa: F401  (re-exported: constants/helpers that used to live in this module)
    SolveResultsMixin,
    _ARCSEC_PER_RAD_UM_MM,
    _LOG_TAIL_LINES,
)

logger = logging.getLogger(__name__)

_LOG_REFRESH_MS = 1000
_MAX_PREVIEW_PX = 2400          # larger frames are shown subsampled; the solver always gets the full frame
_MOUNT_POLL_MS = 3000
_POLAR_GOOD_ARCSEC = 60.0        # polar error readout: green below this,
_POLAR_FAIR_ARCSEC = 300.0       # amber below this, red above


def load_preview(path: str, bayer_pattern: str | None = None) -> np.ndarray | None:
    """The frame at *path* as an auto-stretched 8-bit array ``(h, w)`` or ``(h, w, 3)``, sub-sampled
    if very large. With *bayer_pattern* a mono mosaic is debayered first (before sub-sampling, which
    would otherwise destroy the mosaic). ``None`` if it can't be read (the frame may be gone or half
    written)."""
    try:
        from astropy.io import fits

        from galileo.debayer import debayer
        from galileo.ui.imaging import _auto_stretch
        data = np.asarray(fits.getdata(path))
        if data.ndim == 3:                           # FITS stores colour plane-first
            data = np.moveaxis(data[:3], 0, -1) if data.shape[0] >= 3 else data[0]
        if bayer_pattern and data.ndim == 2:
            data = debayer(data, bayer_pattern)
        step = max(1, max(data.shape[:2]) // _MAX_PREVIEW_PX)
        return _auto_stretch(data[::step, ::step])
    except Exception:
        logger.debug("Could not load %s for the Solve screen", path, exc_info=True)
        return None


def frame_size(path: str) -> tuple[int, int]:
    """``(width, height)`` in pixels from the FITS header alone, ``(0, 0)`` if unreadable."""
    try:
        from astropy.io import fits
        header = fits.getheader(path)
        return int(header["NAXIS1"]), int(header["NAXIS2"])
    except Exception:
        return 0, 0


_UNSET = object()


class SolvePage(SolveResultsMixin, SolveBuildMixin, QWidget):
    """The Solve section."""

    # Emitted from worker threads, received on the UI thread.
    solve_started = Signal(object)
    solve_finished = Signal(object)
    preview_ready = Signal(object)
    mount_position = Signal(object, object)
    run_finished = Signal(object)
    polar_progress = Signal(object, object)       # pier key, PolarAlignProgress

    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("SolvePage")
        self._window = window
        # The results log and live preview are deliberately shared/global — this
        # page "shows every solve... not only the ones started from its own
        # buttons" (see the module docstring), and that doesn't change with two
        # Piers able to run concurrently. What DOES need to be per-Pier is which
        # Pier "owns" a run in progress, so starting one on a different Pier
        # doesn't stomp this Pier's own workflow/buttons, and vice versa.
        self._rows: list[SolveRow] = []
        self._workflows: dict = {}               # pier key -> the SolveWorkflow running there, if any
        self._running: dict = {}
        self._run_target_active: dict = {}       # pier key -> a workflow of ours owns that Pier's current target
        self._in_focus = False                   # read by worker threads; set only from showEvent/hideEvent
        self._latest_path: str | None = None
        self._shown_path: str | None = None
        self._loading_path: str | None = None
        self._mount_busy: dict = {}
        self._displayed_pier = _UNSET            # which Pier the results above belong to
        self.make_solver = self._default_solver  # replaced by tests

        self._build()
        self._set_running(False)
        self.refresh_view()
        self.refresh_target()
        self._select_saved_backend()
        self.refresh_filters()

        self.solve_started.connect(self._on_solve_started)
        self.solve_finished.connect(self._on_solve_finished)
        self.preview_ready.connect(self._on_preview_ready)
        self.mount_position.connect(self._on_mount_position)
        self.run_finished.connect(self._on_run_finished)
        self.polar_progress.connect(self._on_polar_progress)

        self._mount_timer = QTimer(self)
        self._mount_timer.timeout.connect(self.poll_mount)

        bus = get_bus()
        self._bus_handlers = ((SolveStartedEvent, self._on_bus_started), (SolveCompleteEvent, self._on_bus_complete))
        for event_type, handler in self._bus_handlers:
            bus.subscribe(event_type, handler)
        self.destroyed.connect(lambda _=None, handlers=self._bus_handlers: self._unsubscribe(handlers))

    # --- Layout -----------------------------------------------------------


    # --- Focus ------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._in_focus = True
        self.refresh_target()
        self.refresh_filters()
        self.refresh_view()
        self._show_latest_frame()
        self.poll_mount()
        self._mount_timer.start(_MOUNT_POLL_MS)
        self._refresh_log()
        self._log_timer.start(_LOG_REFRESH_MS)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._in_focus = False
        self._mount_timer.stop()
        self._log_timer.stop()

    def _pier_key(self):
        from galileo.current_object import pier_key
        return pier_key(self._window._current_pier)

    def current_object(self):
        """The selected Pier's current object (IMG-140), or ``None``."""
        return get_current_objects().get(self._window._current_pier)

    def refresh_target(self) -> None:
        """Say what Slew to Target will aim at."""
        obj = self.current_object()
        self.target_label.setText(
            f"Target: {obj.name}" if obj is not None
            else "Target: where the mount points when a run begins (pick an object in the Star Atlas to choose one)")

    def reload(self) -> None:
        """A different Pier was selected: its mount is not the one on show, and the
        Capture/Load/Stop buttons must reflect whether THIS Pier has its own run
        in progress — a different Pier's in-flight solve is untouched either way."""
        key = self._pier_key()
        previous, self._displayed_pier = self._displayed_pier, key
        if previous is not _UNSET and key != previous:
            # The results table, solution panel, error plot and preview are one shared view, so
            # they'd still be showing the previous Pier's solves; start the new Pier clean.
            # (Options > Solve also calls reload() with the Pier unchanged — that keeps them.)
            self._clear_for_pier_switch()
        self.refresh_target()
        self.scope_ra.clear()
        self.scope_dec.clear()
        self._set_running(self._running.get(key, False), key)
        self._select_saved_backend()
        self.refresh_filters()
        if self.isVisible():
            self.refresh_view()
            self.poll_mount()

    def _clear_for_pier_switch(self) -> None:
        """Drop every recorded solve and the preview. A solve still running keeps its row so its
        result has somewhere to land."""
        self._rows = [r for r in self._rows if r.status == "solving"]
        self._latest_path = self._rows[-1].fits_path if self._rows else None
        self._shown_path = None
        self._loading_path = None
        self.image_view.clear_image()
        if self.isVisible():
            self.refresh_view()

    def _select_saved_backend(self) -> None:
        """Preselect the Solver Mode saved for the current Pier in Options > Solve."""
        from galileo.observatory import get_solver_backend
        try:
            backend = get_solver_backend(self._window._current_pier)[0]
        except Exception:
            logger.exception("Could not read the saved solver backend")
            return
        for radio, name in self._mode_backends.items():
            if name == backend:
                radio.setChecked(True)

    def _selected_backend(self) -> str:
        return next((name for radio, name in self._mode_backends.items() if radio.isChecked()), "astap")

    def _filter_wheel(self):
        return (self._window._device_pages.get("filter_wheel") or {}).get("adapter")

    def refresh_filters(self) -> None:
        """List the filter wheel's filters in the Filter box, keeping the choice if it is still there."""
        wheel = self._filter_wheel()
        try:
            names = list(wheel.get_filter_names()) if wheel is not None else []
        except Exception:
            logger.debug("Could not read the filter names", exc_info=True)
            names = []
        chosen = self.filter_combo.currentText()
        self.filter_combo.clear()
        self.filter_combo.addItem("Current")
        self.filter_combo.addItems(names)
        index = self.filter_combo.findText(chosen)
        self.filter_combo.setCurrentIndex(max(index, 0))

    # --- Bus (worker threads) ---------------------------------------------

    def _emit(self, name: str, *args) -> None:
        try:
            getattr(self, name).emit(*args)
        except RuntimeError:
            self._unsubscribe(self._bus_handlers)     # the page was deleted (its window closed)

    @staticmethod
    def _unsubscribe(handlers) -> None:
        bus = get_bus()
        for event_type, handler in handlers:
            bus.unsubscribe(event_type, handler)

    def _on_bus_started(self, event) -> None:
        self._emit("solve_started", {"path": event.fits_path})
        if self._in_focus:
            self._load_preview_async(event.fits_path)

    def _on_bus_complete(self, event) -> None:
        result = event.result
        payload = {
            "path": event.fits_path, "result": result, "size": frame_size(event.fits_path), "name": "",
            "pier_key": getattr(event, "pier_key", None),
        }
        if result.success:
            payload["name"] = nearest_object_name(result.ra_deg, result.dec_deg)
        self._emit("solve_finished", payload)

    def _load_preview_async(self, path: str) -> None:
        if path == self._loading_path:
            return
        self._loading_path = path
        # Follow the Imaging tab's Debayer box (IMG-110): the preview is debayered when it is ticked.
        service = self._window._imaging_service
        pattern = service.bayer_pattern if service.debayer_enabled else None

        def work() -> None:
            self._emit("preview_ready", {"path": path, "array": load_preview(path, pattern)})
        threading.Thread(target=work, name="solve-preview", daemon=True).start()

    # --- UI-thread slots --------------------------------------------------

    def _on_solve_started(self, payload) -> None:
        self._rows.append(SolveRow(payload["path"]))
        self._latest_path = payload["path"]
        if self.isVisible():
            self.refresh_view()

    def _on_solve_finished(self, payload) -> None:
        row = next((r for r in reversed(self._rows) if r.fits_path == payload["path"] and r.status == "solving"), None)
        if row is None:                                   # a solve whose start we missed
            row = SolveRow(payload["path"])
            self._rows.append(row)
            self._latest_path = payload["path"]
        result = payload["result"]
        row.width_px, row.height_px = payload["size"]
        if result.success:
            row.status = "solved"
            row.ra_deg, row.dec_deg = result.ra_deg, result.dec_deg
            row.rotation_deg, row.scale_arcsec_px = result.rotation_deg, result.scale_arcsec_px
            row.name = payload["name"]
            # Attributed by the *originating* Pier's own workflow, not whichever Pier
            # happens to be displayed — a backgrounded Pier's run still gets its
            # target/error-offset filled in correctly even while another Pier's own
            # run (or none) is what the Solve screen currently shows.
            origin = payload.get("pier_key")
            workflow = self._workflows.get(origin)
            if self._run_target_active.get(origin) and workflow is not None and workflow.target is not None:
                row.target = workflow.target
                row.d_ra_arcsec, row.d_dec_arcsec = angular_offset_arcsec(row.ra_deg, row.dec_deg, *row.target)
        else:
            row.status = "failed"
            row.reason = result.failure_reason
        if self.isVisible():
            self.refresh_view()

    def _on_preview_ready(self, payload) -> None:
        if payload["path"] == self._loading_path:
            self._loading_path = None
        if payload["array"] is not None and self.isVisible() and payload["path"] == self._latest_path:
            self.image_view.show_array(payload["array"])
            self._shown_path = payload["path"]
            self._update_frame_label()

    def _on_mount_position(self, key, payload) -> None:
        """*payload* is the mount's position, or empty if there is no mount or it couldn't be read.
        *key* is the Pier that was current when the read started — a read for a Pier that
        isn't the one displayed any more is dropped rather than overwriting these fields."""
        self._mount_busy[key] = False
        if key != self._pier_key() or not self.isVisible():
            return
        if not payload:
            self.scope_ra.clear()
            self.scope_dec.clear()
            return
        from galileo.ui.app_window import _format_dms, _format_hms
        ra, dec = j2000_to_mount_frame(*mount_frame_to_j2000(payload["ra_deg"], payload["dec_deg"], payload["system"]), None)
        self.scope_ra.setText(_format_hms(ra / 15.0))
        self.scope_dec.setText(_format_dms(dec))

    def _on_run_finished(self, key) -> None:
        self._set_running(False, key)
        self._run_target_active[key] = False
        workflow = self._workflows.get(key)
        slewed_to = getattr(workflow, "slewed_to", None)
        if slewed_to is not None and key == self._pier_key():
            # Load & Slew: the mount now points at the loaded image's field, so it becomes the
            # Pier's current object — later solves and captures aim at it, not the previous one.
            ra, dec, name = slewed_to
            from galileo.ui.app_window import _format_dms, _format_hms
            self._window._set_current_object({
                "name": name or f"RA {_format_hms(ra / 15.0)} Dec {_format_dms(dec)}",
                "ra_deg": ra, "dec_deg": dec, "kind": "Solved image"})
            if workflow is not None:
                workflow.slewed_to = None

    # --- Rendering (only while visible) -----------------------------------


    # --- Optics -----------------------------------------------------------

    def _optics(self) -> tuple[float | None, float | None, float | None]:
        """``(focal length mm, aperture mm, camera pixel size µm)`` for the selected tube and camera;
        ``None`` for whatever isn't set."""
        tube = self._window.active_optical_tube()
        pixel_um = None
        pier = self._window._current_pier
        if pier is not None:
            from galileo.observatory import get_device_config
            try:
                cfg = get_device_config(pier, "camera", slot=self._window._active_camera_slot)
                pixel_um = cfg.pixel_size_um if cfg is not None else None
            except Exception:
                logger.exception("Could not load the camera's pixel size")
        return (getattr(tube, "focal_length_mm", None) or None, getattr(tube, "aperture_mm", None) or None,
                pixel_um or None)

    def _frame_metadata(self) -> dict:
        """What the solver should be told about the frames this page captures: the pixel size and
        focal length it can derive the image scale from, and the Bayer pattern of a one-shot-colour
        sensor. Anything not configured is left out rather than guessed at."""
        focal, aperture, pixel_um = self._optics()
        meta: dict = {"focal_length_mm": focal, "aperture_mm": aperture,
                      "pixel_size_x_um": pixel_um, "pixel_size_y_um": pixel_um,
                      "frame_type": "Light", "software": "Galileo"}
        tube = self._window.active_optical_tube()
        if tube is not None:
            meta["telescope"] = tube.name
        pier = self._window._current_pier
        if pier is not None:
            from galileo.observatory import get_device_config
            try:
                cfg = get_device_config(pier, "camera", slot=self._window._active_camera_slot)
            except Exception:
                logger.exception("Could not load the camera's configuration for the solve frame")
                cfg = None
            if cfg is not None:
                meta["instrument"] = cfg.device_name or cfg.sensor_name
                # The Bayer pattern is saved for every camera and defaults to RGGB, so it says
                # nothing about whether this sensor is actually colour. Claiming a mosaic a mono
                # camera does not have would only mislead the solver, so it is left out.
        return {key: value for key, value in meta.items() if value not in (None, "")}

    def _scale_hint(self) -> float | None:
        focal, _aperture, pixel_um = self._optics()
        return _ARCSEC_PER_RAD_UM_MM * pixel_um / focal if focal and pixel_um else None

    # --- Devices ----------------------------------------------------------

    def _camera(self):
        from galileo.ui.app_window import _camera_backend_key_for_slot
        return self._window._camera_backends.get(_camera_backend_key_for_slot(self._window._active_camera_slot))

    def _mount(self):
        return (self._window._device_pages.get("mount") or {}).get("adapter")

    def poll_mount(self) -> None:
        """Read the mount's position on a worker thread (a blocking device call must never run on the UI thread)."""
        key = self._pier_key()
        mount = self._mount()
        if mount is None:
            self._on_mount_position(key, {})
            return
        if self._mount_busy.get(key) or self._running.get(key):      # a running workflow reads the mount itself
            return
        self._mount_busy[key] = True

        def work() -> None:
            payload = None
            try:
                status = asyncio.run(mount.get_status()) or {}
                if status.get("right_ascension") is not None and status.get("declination") is not None:
                    payload = {"ra_deg": status["right_ascension"] * 15.0, "dec_deg": status["declination"],
                               "system": status.get("equatorial_system")}
            except Exception:
                logger.debug("Could not read the mount position for the Solve screen", exc_info=True)
            self._emit("mount_position", key, payload or {})

        threading.Thread(target=work, name="solve-mount", daemon=True).start()

    # --- Running ----------------------------------------------------------

    def _default_solver(self) -> PlateSolver | None:
        backend = self._selected_backend()
        solver = make_pier_solver(self._window._current_pier, pier_key=self._pier_key(), backend=backend)
        if not solver.is_available():
            title = {"astap": "ASTAP not found", "astrometry_local": "solve-field not found",
                     "tetra3": "tetra3 not installed"}.get(
                backend, "nova.astrometry.net API key needed")
            QMessageBox.information(self._window._window, title, solver.missing_message())
            return None
        return solver

    def _set_running(self, running: bool, key=None) -> None:
        key = key if key is not None else self._pier_key()
        self._running[key] = running
        if key != self._pier_key():
            return
        self.capture_btn.setEnabled(not running)
        self.load_btn.setEnabled(not running)
        self.polar_start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.busy.setVisible(running)

    def _selected_action(self) -> SolveAction:
        return next(action for action, radio in self.action_radios.items() if radio.isChecked())

    def _post(self, message: str) -> None:
        """The workflow's log callback — called on its thread. The log pane shows the application's
        log, so this is all it takes for a line to appear there."""
        logger.info("%s", message)

    def _begin(self, run, use_current_object: bool = False, make_workflow=None) -> None:
        # Re-entrancy is enforced by capture_and_solve()/load_and_slew() (the
        # only production entry points), not here — matching the original
        # single-Pier code, where _begin() itself never checked _running either.
        key = self._pier_key()
        solver = self.make_solver()
        if solver is None:
            return
        workflow = self._workflows[key] = (make_workflow or SolveWorkflow)(
            solver, camera=self._camera(), mount=self._mount(), log=self._post,
            frame_metadata=self._frame_metadata(), filter_wheel=self._filter_wheel())
        obj = self.current_object() if use_current_object else None   # Load & Slew has its own idea of where to go
        if obj is not None:
            workflow.set_target(obj.ra_deg, obj.dec_deg, obj.name)
        self._run_target_active[key] = make_workflow is None      # a polar-alignment run has no target to measure against
        self._set_running(True, key)

        def work() -> None:
            try:
                asyncio.run(run(workflow))
            except Exception:
                logger.exception("Plate-solve run failed")
            finally:
                self._emit("run_finished", key)
        threading.Thread(target=work, name="solve-run", daemon=True).start()

    def capture_and_solve(self) -> None:
        if self._running.get(self._pier_key()):
            return
        if self._camera() is None:
            QMessageBox.information(self._window._window, "No camera connected",
                                    self._window.camera_not_connected_message())
            return
        settings = SolveSettings(
            exposure_s=self.exposure_spin.value(), action=self._selected_action(),
            accuracy_arcsec=float(self.accuracy_spin.value()), settle_s=self.settle_spin.value() / 1000.0,
            scale_hint_arcsec_px=self._scale_hint(), binning=self.bin_combo.currentIndex() + 1,
            gain=self.gain_spin.value(),
            filter_name="" if self.filter_combo.currentIndex() <= 0 else self.filter_combo.currentText(),
            subtract_dark=self.dark_check.isChecked(),
        )
        self._begin(lambda workflow: workflow.capture_and_solve(settings), use_current_object=True)

    def load_and_slew(self) -> None:
        if self._running.get(self._pier_key()):
            return
        path, _ = QFileDialog.getOpenFileName(self._window._window, "Load & Slew", "", "FITS files (*.fits *.fit *.fts)")
        if not path:
            return
        self._begin(lambda workflow: workflow.solve_file(path, slew=True))

    def _site(self) -> tuple[float, float] | None:
        """``(latitude, longitude)`` of the Pier's Observatory, or ``None`` if it has none set. (Read from the record, not
        the mount: a device call here would block the UI thread.)"""
        try:
            observatory = self._window._current_pier.observatory
            if observatory.latitude is not None and observatory.longitude is not None:
                return float(observatory.latitude), float(observatory.longitude)
        except Exception:
            logger.debug("Could not read the Observatory's location", exc_info=True)
        return None

    def start_polar_alignment(self) -> None:
        key = self._pier_key()
        if self._running.get(key):
            return
        if self._camera() is None:
            QMessageBox.information(self._window._window, "No camera connected",
                                    self._window.camera_not_connected_message())
            return
        if self._mount() is None:
            QMessageBox.information(self._window._window, "No mount connected",
                                    "Polar alignment turns the mount to take its measurements, so it needs a connected mount.")
            return
        site = self._site()
        if site is None:
            QMessageBox.information(
                self._window._window, "Site location unknown",
                "Polar alignment needs the site's latitude and longitude. Set them on the Observatory.")
            return
        settings = PolarAlignSettings(
            exposure_s=self.exposure_spin.value(), settle_s=self.settle_spin.value() / 1000.0,
            scale_hint_arcsec_px=self._scale_hint(),
            step_deg=float(self.polar_step_spin.value()), direction=self.polar_direction.currentData(),
            refraction=self.polar_refraction.isChecked())

        def make(solver, **kwargs):
            return PolarAlignWorkflow(solver, latitude=site[0], longitude=site[1],
                                      on_progress=lambda progress: self._emit("polar_progress", key, progress), **kwargs)

        self.polar_status.setText("Starting…")
        self.polar_total.setText("—")
        self.polar_total.setStyleSheet("")
        self.polar_altitude.clear()
        self.polar_azimuth.clear()
        self.polar_target_hint.clear()
        self.polar_target.set_offset(None)
        self._begin(lambda workflow: workflow.align(settings), make_workflow=make)

    def _on_polar_progress(self, key, progress: PolarAlignProgress) -> None:
        if key != self._pier_key():
            return
        if progress.phase == "measuring" and progress.step:
            self.polar_status.setText(f"Measuring ({progress.step} of {progress.steps}): {progress.message}")
        else:
            self.polar_status.setText(progress.message)
        error = progress.error
        if error is None:
            return
        self.polar_total.setText(format_angle(error.total_arcsec))
        color = ("#31c24a" if error.total_arcsec < _POLAR_GOOD_ARCSEC
                 else "#e0c030" if error.total_arcsec < _POLAR_FAIR_ARCSEC else "#d63a3a")
        self.polar_total.setStyleSheet(f"color: {color};")
        self.polar_altitude.setText(error.altitude_advice())
        self.polar_azimuth.setText(error.azimuth_advice())
        self.polar_target.set_offset(progress.target_offset)
        self.polar_target_hint.setText(
            "Turn the altitude and azimuth adjusters to bring the X (the pole) into the circle (where the axis points)."
            if progress.target_offset is not None else
            "This solver gives no field geometry, so the X and circle can't be drawn; follow the adjustments above.")

    def stop(self) -> None:
        # Stops whichever Pier is currently displayed's own run — a different
        # Pier's in-flight solve is untouched.
        workflow = self._workflows.get(self._pier_key())
        if workflow is not None:
            workflow.stop()

    # --- Results ----------------------------------------------------------

    def clear_results(self) -> None:
        self._rows = [r for r in self._rows if r.status == "solving"]
        self.refresh_view()

    def remove_selected(self) -> None:
        drop = {index.row() for index in self.table.selectionModel().selectedRows()}
        self._rows = [r for i, r in enumerate(self._rows) if i not in drop or r.status == "solving"]
        self.refresh_view()

    def save_results(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self._window._window, "Save results", "solve-results.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["ra_deg_j2000", "dec_deg_j2000", "name", "solved", "d_ra_arcsec", "d_dec_arcsec",
                                 "rotation_deg", "scale_arcsec_px", "failure_reason", "fits_path"])
                for r in self._rows:
                    writer.writerow([r.ra_deg, r.dec_deg, r.name, r.status == "solved", r.d_ra_arcsec, r.d_dec_arcsec,
                                     r.rotation_deg, r.scale_arcsec_px, r.reason, r.fits_path])
        except OSError:
            logger.exception("Could not save the solve results to %s", path)
            self._window._window.statusBar().showMessage("Could not save the results — see log.", 6000)
            return
        self._window._window.statusBar().showMessage(f"Saved {len(self._rows)} results to {path}.", 4000)
