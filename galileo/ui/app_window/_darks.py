# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Darks Assistant dialog, opened from the Imaging page's Darks… button."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _camera_backend_key_for_slot, _new_form_layout, _QDialogBase
from ._threads import _DarksThread

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._state import AppWindowState


class _DarksDialog(_QDialogBase):
    """Refuses close while a darks run is in progress, the same way _FlatsDialog does."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.running = False

    def reject(self) -> None:
        if self.running:
            return
        super().reject()


class AppWindowDarksMixin:
    def _open_darks_dialog(self: AppWindowState) -> None:
        """Open the Darks Assistant: capture N dark frames (the "Darks per exposure" count) at
        each exposure length in the user-supplied comma-separated list (default 10, 20, 30,
        60 s), optionally selecting a filter first, and auto-save each frame to the Library."""
        from PySide6.QtWidgets import (
            QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
            QMessageBox, QPushButton, QComboBox, QSpinBox, QVBoxLayout,
        )
        from galileo.current_object import pier_key
        from galileo.ui.imaging import ImagingService

        key = pier_key(self._current_pier)
        if self._darks_threads.get(key) is not None:
            self._window.statusBar().showMessage("A Darks run is already in progress on this Pier.", 4000)
            return
        if self._imaging_capture_threads.get(key) is not None:
            self._window.statusBar().showMessage(
                "A capture is already running on this Pier — stop it first.", 4000,
            )
            return

        camera = self._camera_backends.get(_camera_backend_key_for_slot(self._active_camera_slot))
        if camera is None:
            QMessageBox.information(self._window, "No camera connected", self.camera_not_connected_message())
            return

        from galileo.ui.help import tag_help_screen
        dialog = tag_help_screen(_DarksDialog(self._window), "imaging.darks")
        dialog.setWindowTitle("Darks Assistant")
        outer = QVBoxLayout(dialog)
        form = _new_form_layout()
        outer.addLayout(form)

        wheel = self._active_filter_wheel()
        filter_names = [str(n) for n in (getattr(wheel, "filter_names", None) or [])] if wheel is not None else []
        filter_combo = QComboBox()
        filter_combo.addItem("(none)")
        filter_combo.addItems(filter_names)
        filter_combo.setToolTip(
            "Filter to select on the wheel before each exposure. "
            "Leave at (none) for unfiltered darks or when no filter wheel is connected."
        )
        form.addRow("Filter", filter_combo)

        exposures_edit = QLineEdit("10,20,30,60")
        exposures_edit.setToolTip(
            "Comma-separated exposure lengths in seconds — one dark frame is captured at each "
            "value in the order given. Example: 10,20,30,60"
        )
        form.addRow("Exposures (s)", exposures_edit)

        count_spin = QSpinBox()
        count_spin.setRange(1, 999)
        count_spin.setValue(10)
        count_spin.setToolTip("Number of dark frames to capture at each exposure length in the list.")
        form.addRow("Darks per exposure", count_spin)

        status_label = QLabel("")
        status_label.setObjectName("StatusHint")
        status_label.setWordWrap(True)
        outer.addWidget(status_label)

        fields = (filter_combo, exposures_edit, count_spin)
        run_state: dict = {"service": None, "frames_captured": 0}

        def set_running(running: bool) -> None:
            dialog.running = running
            start_btn.setEnabled(not running)
            stop_btn.setEnabled(running)
            park_btn.setEnabled(not running)
            for field in fields:
                field.setEnabled(not running)
            buttons.button(QDialogButtonBox.StandardButton.Close).setEnabled(not running)

        def on_frame_started(exp_i: int, exp_n: int, exposure_s: float, frame_i: int, frame_n: int) -> None:
            status_label.setText(
                f"Exposing {exposure_s:g} s dark {frame_i} of {frame_n} "
                f"(exposure {exp_i} of {exp_n}; {run_state['frames_captured']} of "
                f"{run_state['frames_total']} frame(s) done)…"
            )

        def on_frame_done(exp_i: int, exp_n: int, exposure_s: float, frame_i: int, frame_n: int) -> None:
            run_state["frames_captured"] += 1
            status_label.setText(
                f"Captured {exposure_s:g} s dark {frame_i} of {frame_n} "
                f"(exposure {exp_i} of {exp_n}; {run_state['frames_captured']} of "
                f"{run_state['frames_total']} frame(s) done)."
            )

        def finished() -> None:
            self._darks_threads.pop(key, None)
            set_running(False)
            count = run_state["frames_captured"]
            summary = f"Darks done — {count} frame(s) captured."
            status_label.setText(summary)
            self._window.statusBar().showMessage(summary, 6000)
            _refresh_library()

        def failed(message: str) -> None:
            self._darks_threads.pop(key, None)
            set_running(False)
            logger.error("Darks capture failed: %s", message)
            status_label.setText(f"Failed: {message}")
            self._window.statusBar().showMessage("Darks capture failed — see log.", 6000)

        def _refresh_library() -> None:
            images = getattr(getattr(self, "_library_screens", None), "images", None)
            if images is None:
                return
            try:
                images.load_fits_data()
            except Exception:
                logger.exception("Could not refresh Library > Images after Darks run")

        button_row = QHBoxLayout()
        start_btn = QPushButton("Start")
        start_btn.setObjectName("AccentButton")
        button_row.addWidget(start_btn)
        stop_btn = QPushButton("Stop")
        stop_btn.setEnabled(False)
        button_row.addWidget(stop_btn)
        park_btn = QPushButton("Park Flat Panel")
        park_btn.setToolTip("Close the flat panel's cover so it is dark before you capture darks.")
        button_row.addWidget(park_btn)
        button_row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_row.addWidget(buttons)
        outer.addLayout(button_row)

        def start() -> None:
            exposures = _parse_exposures(exposures_edit.text())
            if not exposures:
                QMessageBox.warning(
                    self._window, "No valid exposures",
                    "Enter at least one positive exposure length in seconds, e.g. '10,20,30,60'.",
                )
                return
            run_state["frames_captured"] = 0
            run_state["frames_total"] = len(exposures) * count_spin.value()
            svc = ImagingService(camera=camera)
            svc.auto_save_to_library = True
            svc.frame_context = self._imaging_frame_context()
            run_state["service"] = svc

            filter_name = filter_combo.currentText() if filter_combo.currentIndex() > 0 else ""
            thread = _DarksThread(svc, exposures, filter_name, count_spin.value(), dialog)
            thread.frame_started.connect(on_frame_started)
            thread.frame_done.connect(on_frame_done)
            thread.finished_ok.connect(finished)
            thread.failed.connect(failed)
            self._darks_threads[key] = thread
            set_running(True)
            status_label.setText("Starting…")
            thread.start()

        def stop() -> None:
            svc = run_state["service"]
            if svc is not None:
                svc.request_stop()
            status_label.setText("Stopping after the current frame…")

        def park_flat_panel() -> None:
            import asyncio
            panel = (self._device_pages.get("flat_panel") or {}).get("adapter")
            if panel is None:
                QMessageBox.information(
                    dialog, "No flat panel connected",
                    "Connect a flat panel on Equipment > Flat Panel first.",
                )
                return
            try:
                asyncio.run(panel.close_cover())
            except Exception:
                logger.exception("Darks Assistant: flat panel park failed")
                status_label.setText("Flat panel park failed — see log.")
                return
            status_label.setText("Flat panel parked.")

        start_btn.clicked.connect(start)
        park_btn.clicked.connect(park_flat_panel)
        stop_btn.clicked.connect(stop)
        buttons.rejected.connect(dialog.reject)

        dialog.exec()


def _parse_exposures(text: str) -> list:
    """Parse "10, 20, 30.5, 60" → [10.0, 20.0, 30.5, 60.0], dropping non-positive or invalid entries."""
    result = []
    for part in text.split(","):
        part = part.strip()
        try:
            v = float(part)
        except ValueError:
            continue
        if v > 0:
            result.append(v)
    return result
