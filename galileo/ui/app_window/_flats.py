# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Flats Assistant dialog (CAL-060/CAL-070), opened from the Imaging page's Flats button."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import logging

from ._common import _camera_backend_key_for_slot, _new_form_layout, _QDialogBase
from ._threads import _FlatsThread

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._state import AppWindowState


class _FlatsDialog(_QDialogBase):
    """A plain ``QDialog`` except that ESC, the title bar's X, and the button box's
    Close button are all refused while ``running`` is set — a Sky Flats run underway
    on a background ``_FlatsThread`` is still updating this dialog's own widgets
    through connected signals, so closing out from under it would leave those signal
    handlers firing against a destroyed window."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.running = False

    def reject(self) -> None:
        if self.running:
            return
        super().reject()


class AppWindowFlatsMixin:
    def _flats_observing_location(self: AppWindowState, pier=None):
        """The Pier's (default: the selected one's) Observatory as a
        ``galileo.planning.visibility.ObservingLocation`` — needed for Sky
        Flats' twilight check and its East-vantage-point slew (CAL-070).
        ``None`` if no Pier is selected or its Observatory has no
        latitude/longitude set yet (Planning > the Observatory's own fields)."""
        pier = self._current_pier if pier is None else pier
        if pier is None:
            return None
        try:
            observatory = pier.observatory
        except Exception:
            return None
        if observatory.latitude is None or observatory.longitude is None:
            return None
        from galileo.planning.visibility import ObservingLocation
        return ObservingLocation(
            name=observatory.name, latitude=observatory.latitude, longitude=observatory.longitude,
            elevation_m=getattr(observatory, "elevation_m", None) or 0.0,
        )

    def _open_flats_dialog(self: AppWindowState, service) -> None:
        """Open the Flats Assistant (CAL-060): Flat Method (Sky Flats /
        Observatory Panel / Flat Panel), an Exposure field left blank to
        calculate it, Number of Frames, a Filter field (with an All option
        that repeats the run for every filter, CAL-020), an Average/Median
        ADU Method, and an Exposure Increment step.

        Sky Flats (CAL-070) checks the sky is currently within local
        dawn/dusk twilight, slews the mount to a star-poor vantage point in
        the East and turns tracking off, then adaptively converges each
        frame's exposure toward 50% of the camera's Max Well Depth
        (Equipment > Camera) before saving it. Flat Panel and Observatory
        Panel (CAL-090) run ``CalibrationService.run_panel_flats_all_filters``;
        Flat Panel is only selectable while a flat panel is connected. The
        run is off-thread (``_FlatsThread``); a ``FlatCalibrationError`` is
        shown to the user."""
        from PySide6.QtWidgets import (
            QComboBox, QDialogButtonBox, QDoubleSpinBox, QHBoxLayout,
            QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
        )
        from galileo.calibration import ADU_METHODS, FLAT_METHODS, CalibrationService
        from galileo.current_object import pier_key

        key = pier_key(self._current_pier)
        if self._flats_threads.get(key) is not None:
            self._window.statusBar().showMessage("A Flats run is already in progress on this Pier.", 4000)
            return

        camera = self._camera_backends.get(_camera_backend_key_for_slot(self._active_camera_slot))
        if camera is None:
            QMessageBox.information(self._window, "No camera connected", self.camera_not_connected_message())
            return

        from galileo.ui.help import tag_help_screen
        dialog = tag_help_screen(_FlatsDialog(self._window), "imaging.flats")
        dialog.setWindowTitle("Flats Assistant")
        outer = QVBoxLayout(dialog)
        form = _new_form_layout()
        outer.addLayout(form)

        method_combo = QComboBox()
        method_combo.addItems(FLAT_METHODS)
        form.addRow("Flat Method", method_combo)

        exposure_spin = QDoubleSpinBox()
        exposure_spin.setRange(0.0, 3600.0)
        exposure_spin.setDecimals(3)
        exposure_spin.setSuffix(" s")
        exposure_spin.setSpecialValueText("Calculate")
        exposure_spin.setToolTip(
            "Leave at Calculate to have Sky Flats work out the exposure itself from the camera's "
            "Max Well Depth (Equipment > Camera); set a value to fix it instead."
        )
        form.addRow("Exposure", exposure_spin)

        count_spin = QSpinBox()
        count_spin.setRange(1, 999)
        count_spin.setValue(10)
        form.addRow("Number of Frames", count_spin)

        filter_combo = QComboBox()
        wheel = self._active_filter_wheel()
        filter_names = [str(n) for n in (getattr(wheel, "filter_names", None) or [])] if wheel is not None else []
        filter_combo.addItem("All")
        filter_combo.addItems(filter_names)
        filter_combo.setToolTip(
            "All repeats the run for every filter in turn, cycling the filter wheel (CAL-020)."
            if filter_names else "No filter wheel connected — Sky Flats will run with no filter selection."
        )
        form.addRow("Filter", filter_combo)

        adu_method_combo = QComboBox()
        adu_method_combo.addItems(ADU_METHODS)
        form.addRow("Method", adu_method_combo)

        increment_spin = QDoubleSpinBox()
        increment_spin.setRange(0.001, 10.0)
        increment_spin.setDecimals(3)
        increment_spin.setValue(0.1)
        increment_spin.setSuffix(" s")
        increment_spin.setToolTip(
            "The minimum exposure-time step Sky Flats moves by while hunting for the right exposure."
        )
        form.addRow("Exposure Increment", increment_spin)

        status_label = QLabel("")
        status_label.setObjectName("StatusHint")
        status_label.setWordWrap(True)
        outer.addWidget(status_label)

        fields = (method_combo, exposure_spin, count_spin, filter_combo, adu_method_combo, increment_spin)

        button_row = QHBoxLayout()
        start_btn = QPushButton("Start")
        start_btn.setObjectName("AccentButton")
        button_row.addWidget(start_btn)
        stop_btn = QPushButton("Stop")
        stop_btn.setEnabled(False)
        button_row.addWidget(stop_btn)
        button_row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_row.addWidget(buttons)
        outer.addLayout(button_row)

        run_state: dict[str, Any] = {"service": None, "method": "Sky Flats"}

        def _connected_flat_panel():
            return (self._device_pages.get("flat_panel") or {}).get("adapter")

        # Flat Panel needs a connected panel device (CAL-090); disable that entry otherwise.
        panel_index = method_combo.findText("Flat Panel")
        if panel_index >= 0 and _connected_flat_panel() is None:
            item = method_combo.model().item(panel_index)
            if item is not None:
                item.setEnabled(False)
                item.setToolTip("Connect a flat panel on Equipment > Flat Panel to use this method.")

        def set_running(running: bool) -> None:
            dialog.running = running
            start_btn.setEnabled(not running)
            stop_btn.setEnabled(running)
            for field in fields:
                field.setEnabled(not running)
            buttons.button(QDialogButtonBox.StandardButton.Close).setEnabled(not running)

        def on_filter_start(filter_name: str, index: int, total: int) -> None:
            status_label.setText(f"Filter {filter_name or '(none)'} ({index} of {total})…")

        def on_frame_done(filter_name: str, frame_index: int, frame_total: int) -> None:
            status_label.setText(
                f"Filter {filter_name or '(none)'}: frame {frame_index} of {frame_total} captured."
            )

        def finished(results) -> None:
            self._flats_threads.pop(key, None)
            set_running(False)
            total_frames = sum(r.frames_captured for r in results)
            summary = f"{run_state['method']} done — {total_frames} frame(s) captured."
            status_label.setText(summary)
            self._window.statusBar().showMessage(summary, 6000)

        def failed(message: str) -> None:
            self._flats_threads.pop(key, None)
            set_running(False)
            name = run_state["method"]
            logger.error("%s failed: %s", name, message)
            status_label.setText(f"Failed: {message}")
            self._window.statusBar().showMessage(f"{name} failed — see log.", 6000)
            QMessageBox.warning(dialog, f"{name} failed", message)

        def start() -> None:
            method = method_combo.currentText()
            run_state["method"] = method
            panel = _connected_flat_panel()
            if method == "Flat Panel" and panel is None:
                QMessageBox.warning(
                    self._window, "No flat panel connected",
                    "Flat Panel flats need a connected flat panel (Equipment > Flat Panel).",
                )
                return

            location = None
            if method == "Sky Flats":
                location = self._flats_observing_location()
                from galileo.planning.visibility import is_twilight
                if location is None or not is_twilight(location):
                    QMessageBox.warning(
                        self._window, "Outside twilight",
                        "Sky Flats only works during local dawn or dusk twilight — the sky is either "
                        "still bright (daylight) or already fully dark right now. Set the Observatory's "
                        "latitude/longitude if this looks wrong.",
                    )
                    return

            camera_cfg = None
            try:
                from galileo.observatory import get_device_config
                camera_cfg = get_device_config(self._current_pier, "camera", slot=self._active_camera_slot)
            except Exception:
                logger.exception("Could not load the camera's configuration for %s", method)
            max_well_depth = camera_cfg.max_well_depth if camera_cfg is not None else None
            if not max_well_depth:
                QMessageBox.warning(
                    self._window, "No Max Well Depth set",
                    f"{method} needs the camera's Max Well Depth set on Equipment > Camera to work "
                    "out the target ADU (exposure, or panel brightness for a Flat Panel).",
                )
                return

            mount = (self._device_pages.get("mount") or {}).get("adapter")
            svc = CalibrationService(
                camera=camera, filter_wheel=wheel, flat_panel=panel if method == "Flat Panel" else None,
                mount=mount, output_dir=service._scratch_folder() / "flats",
            )
            run_state["service"] = svc

            filter_selected = filter_combo.currentText()
            filters = None if filter_selected == "All" else [filter_selected]
            exposure_s = exposure_spin.value() or None

            thread = _FlatsThread(
                svc, filters, count_spin.value(), max_well_depth, location,
                adu_method_combo.currentText(), exposure_s, increment_spin.value(), dialog,
                method=method,
            )
            thread.filter_started.connect(on_filter_start)
            thread.frame_done.connect(on_frame_done)
            thread.finished_ok.connect(finished)
            thread.failed.connect(failed)
            self._flats_threads[key] = thread
            set_running(True)
            status_label.setText("Starting…")
            thread.start()

        def stop() -> None:
            svc = run_state["service"]
            if svc is not None:
                svc.request_stop()
            status_label.setText("Stopping after the current frame…")

        start_btn.clicked.connect(start)
        stop_btn.clicked.connect(stop)
        buttons.rejected.connect(dialog.reject)

        dialog.exec()
