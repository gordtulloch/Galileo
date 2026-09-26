# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Imaging page: live preview, histogram/stats, manual capture and mosaic capture."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _camera_backend_key_for_slot, _new_form_layout, _PARKED_MESSAGE, QWidget
from ._threads import _PreviewRenderThread, _NudgeThread, _CaptureThread, _MosaicCaptureThread
from ._widgets import _HistogramWidget

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowImagingPageMixin:
    def _build_imaging_page(self: AppWindowState) -> QWidget:
        """Imaging tab (IMG-010 … IMG-100): a live, pan/zoomable auto-stretch
        preview with histogram and per-frame statistics, plus manual
        single-exposure capture — modeled on the classic CCD-capture-tool
        split of capture settings on the left against preview/progress/log
        on the right (see assets/samples/ccd.png). Sequencing itself lives
        in the separate Sequence section; this page is for live preview and
        one-off manual shots, not a queue."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QGroupBox,
            QComboBox, QDoubleSpinBox, QSpinBox, QPushButton, QCheckBox, QProgressBar,
            QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QFrame,
            QFileDialog, QMessageBox, QGridLayout, QScrollArea, QMenu,
        )
        from PySide6.QtCore import Qt, QTimer, QObject, QEvent
        from PySide6.QtGui import QPixmap, QImage

        from galileo.livestack import LIVE_STACK_MIN_FRAMES
        from galileo.ui.imaging import DEFAULT_GAIN, ImagingService, NUDGE_RATES, PORTRAIT, LANDSCAPE

        page = QWidget()
        page.setObjectName("ImagingPage")
        root = QHBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- left: capture + view settings ----------------------------------
        # In a scroll area because the panel also holds the nudge pad and, for a
        # portrait frame, the histogram, progress bar and log (IMG-120).
        settings_scroll = QScrollArea()
        settings_scroll.setFixedWidth(300)
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_panel = QFrame()
        settings_panel.setObjectName("ImagingSettingsPanel")
        settings_scroll.setWidget(settings_panel)
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(10)

        heading = QLabel("Imaging")
        heading.setObjectName("PageTitle")
        settings_layout.addWidget(heading)

        capture_group = QGroupBox("Capture Settings")
        capture_form = _new_form_layout(capture_group)

        exposure_spin = QDoubleSpinBox()
        exposure_spin.setRange(0.001, 3600.0)
        exposure_spin.setDecimals(3)
        exposure_spin.setValue(5.0)
        exposure_spin.setSuffix(" s")
        capture_form.addRow("Exposure", exposure_spin)

        quantity_spin = QSpinBox()
        quantity_spin.setRange(1, 9999)
        quantity_spin.setValue(1)
        quantity_spin.setToolTip("How many frames Capture takes, one after another, with these settings (IMG-150).")
        capture_form.addRow("Quantity", quantity_spin)

        gain_spin = QSpinBox()
        gain_spin.setRange(0, 100000)
        gain_spin.setValue(DEFAULT_GAIN)
        gain_spin.setToolTip("Camera gain for each exposure. 0 leaves the camera as it is configured (IMG-150).")
        capture_form.addRow("Gain", gain_spin)

        live_stack_check = QCheckBox("Live Stack")
        live_stack_check.setToolTip(
            f"Build the frames of one Capture into a single image instead of each replacing the last "
            f"(IMG-160): every frame is aligned to the first and added to a running mean, so the preview, "
            f"statistics and histogram improve as the run goes on. Applies to runs of "
            f"{LIVE_STACK_MIN_FRAMES} frames or more. Each frame still goes to the Library on its own; "
            f"use Save Stack for the stacked image.")
        capture_form.addRow(live_stack_check)

        frame_type_combo = QComboBox()
        frame_type_combo.addItems(["Light", "Dark", "Flat", "Bias"])
        capture_form.addRow("Type", frame_type_combo)

        filter_combo = QComboBox()
        filter_combo.setEditable(True)
        filter_combo.setToolTip(
            "The filters of the filter wheel associated with the selected optics "
            "(Equipment > Optics). Connect the wheel on Equipment > Filter Wheel to fill this in."
        )
        capture_form.addRow("Filter", filter_combo)
        self._imaging_filter_combo = filter_combo
        self._refresh_imaging_filters()
        filter_combo.activated.connect(self._on_imaging_filter_activated)

        settings_layout.addWidget(capture_group)

        mosaic_indicator = QLabel("")
        mosaic_indicator.setObjectName("StatusHint")
        mosaic_indicator.setWordWrap(True)
        mosaic_indicator.setVisible(False)
        settings_layout.addWidget(mosaic_indicator)

        capture_row = QHBoxLayout()
        capture_btn = QPushButton("Capture")
        capture_btn.setObjectName("AccentButton")
        capture_row.addWidget(capture_btn, 1)
        stop_capture_btn = QPushButton("Stop")
        stop_capture_btn.setToolTip("Abandon the exposure in progress and take no more frames.")
        stop_capture_btn.setEnabled(False)
        capture_row.addWidget(stop_capture_btn)
        settings_layout.addLayout(capture_row)

        framing_row = QHBoxLayout()
        framing_btn = QPushButton("Framing…")
        framing_btn.setToolTip("Open the Framing Assistant against the selected optical train: compute the "
                               "field of view, or define and run a mosaic grid directly from this tab "
                               "(IMG-180, FRAME-070).")
        framing_row.addWidget(framing_btn, 1)
        clear_mosaic_btn = QPushButton("Clear Mosaic")
        clear_mosaic_btn.setToolTip("Discard the active mosaic (IMG-180) and go back to capturing a single frame.")
        clear_mosaic_btn.setVisible(False)
        framing_row.addWidget(clear_mosaic_btn)
        settings_layout.addLayout(framing_row)

        save_frame_btn = QPushButton("Save Frame…")
        save_frame_btn.setToolTip("Save the currently displayed frame to disk as a FITS file, with all the "
                                  "header cards Galileo can fill in (IMG-100, IMG-150).")
        save_frame_btn.setEnabled(False)
        settings_layout.addWidget(save_frame_btn)

        save_stack_btn = QPushButton("Save Stack…")
        save_stack_btn.setToolTip("Save the live stack to the Library or to a FITS file (IMG-160).")
        save_stack_btn.setEnabled(False)
        settings_layout.addWidget(save_stack_btn)

        auto_save_check = QCheckBox("Auto-Save to Library")
        auto_save_check.setChecked(True)
        auto_save_check.setToolTip(
            "Write each captured frame to a scratch folder and register it in the Library, which files it "
            "in the repository — it then appears on Library > Images (IMG-150). Needs the repository folder "
            "set in Options > Library.")
        settings_layout.addWidget(auto_save_check)

        view_group = QGroupBox("View")
        view_form = _new_form_layout(view_group)

        debayer_check = QCheckBox("Debayer")
        debayer_check.setToolTip(
            "Show the frame from a one-shot-colour camera in colour, using the Bayer pattern set for "
            "the camera on Equipment > Camera (RGGB by default) (IMG-110). Only the preview changes: "
            "statistics, the histogram and Save Frame keep the camera's raw data."
        )
        view_form.addRow(debayer_check)

        star_overlay_check = QCheckBox("Star overlay")
        star_overlay_check.setToolTip("Overlay stars detected for HFR computation (IMG-050).")
        view_form.addRow(star_overlay_check)

        zoom_spin = QDoubleSpinBox()
        zoom_spin.setRange(0.1, 8.0)
        zoom_spin.setSingleStep(0.1)
        zoom_spin.setValue(1.0)
        zoom_spin.setSuffix("x")
        view_form.addRow("Zoom", zoom_spin)

        reset_view_btn = QPushButton("Reset View")
        view_form.addRow(reset_view_btn)

        orientation_check = QCheckBox("Choose layout manually")
        orientation_check.setToolTip(
            "By default the page lays itself out for the shape of the frame: a portrait frame gets the "
            "whole right side, with the histogram and log moved to the left (IMG-120). Tick this to "
            "pick the layout yourself."
        )
        view_form.addRow(orientation_check)
        orientation_combo = QComboBox()
        orientation_combo.addItem("Landscape", LANDSCAPE)
        orientation_combo.addItem("Portrait", PORTRAIT)
        orientation_combo.setEnabled(False)
        view_form.addRow("Layout", orientation_combo)

        settings_layout.addWidget(view_group)

        stats_group = QGroupBox("Statistics")
        stats_form = QFormLayout(stats_group)
        stats_labels: dict = {}
        for key, label_text in (
            ("mean", "Mean"), ("median", "Median"), ("min", "Min"),
            ("max", "Max"), ("star_count", "Star count"), ("hfr", "HFR"),
        ):
            value_label = QLabel("—")
            stats_labels[key] = value_label
            stats_form.addRow(label_text, value_label)
        settings_layout.addWidget(stats_group)

        nudge_group = QGroupBox("Mount Nudge")
        nudge_layout = QVBoxLayout(nudge_group)
        nudge_grid = QGridLayout()
        nudge_north_btn, nudge_west_btn = QPushButton("N"), QPushButton("W")
        nudge_stop_btn = QPushButton("Stop")
        nudge_east_btn, nudge_south_btn = QPushButton("E"), QPushButton("S")
        nudge_dir_buttons = {"N": nudge_north_btn, "S": nudge_south_btn, "E": nudge_east_btn, "W": nudge_west_btn}
        for btn in (*nudge_dir_buttons.values(), nudge_stop_btn):
            btn.setObjectName("AccentButton")
            btn.setFixedSize(44, 44)
        nudge_grid.addWidget(nudge_north_btn, 0, 1)
        nudge_grid.addWidget(nudge_west_btn, 1, 0)
        nudge_grid.addWidget(nudge_stop_btn, 1, 1)
        nudge_grid.addWidget(nudge_east_btn, 1, 2)
        nudge_grid.addWidget(nudge_south_btn, 2, 1)
        nudge_grid.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        nudge_layout.addLayout(nudge_grid)
        nudge_form = _new_form_layout()
        nudge_rate_combo = QComboBox()
        for name, rate in NUDGE_RATES.items():
            nudge_rate_combo.addItem(f"{name} ({rate:g}°/s)", rate)
        nudge_rate_combo.setCurrentIndex(1)
        nudge_rate_combo.setToolTip("How fast the mount moves during a nudge.")
        nudge_form.addRow("Speed", nudge_rate_combo)
        nudge_duration_spin = QDoubleSpinBox()
        nudge_duration_spin.setRange(0.1, 10.0)
        nudge_duration_spin.setSingleStep(0.1)
        nudge_duration_spin.setDecimals(1)
        nudge_duration_spin.setValue(0.5)
        nudge_duration_spin.setSuffix(" s")
        nudge_duration_spin.setToolTip("How long the mount moves for each press.")
        nudge_form.addRow("Duration", nudge_duration_spin)
        nudge_layout.addLayout(nudge_form)
        nudge_group.setToolTip(
            "Nudge the telescope while exposing (IMG-130). Uses the mount connected on Equipment > Mount, "
            "with the same axis directions as its jog pad."
        )
        settings_layout.addWidget(nudge_group)

        settings_layout.addStretch(1)
        root.addWidget(settings_scroll)

        # A column between the settings and the preview, used only for a portrait
        # frame (IMG-120): it takes the width the narrow preview leaves free and
        # holds the histogram, progress bar and log.
        dock_panel = QWidget()
        dock_layout = QVBoxLayout(dock_panel)
        dock_layout.setContentsMargins(8, 16, 8, 16)
        dock_layout.setSpacing(6)
        dock_layout.addStretch(1)
        dock_panel.setVisible(False)
        root.addWidget(dock_panel, 1)

        # --- right: live preview, histogram, progress, log ------------------
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(10)

        scene = QGraphicsScene()
        pixmap_item = QGraphicsPixmapItem()
        scene.addItem(pixmap_item)
        preview_view = QGraphicsView(scene)
        preview_view.setObjectName("ImagingPreview")
        preview_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        preview_view.setBackgroundBrush(Qt.GlobalColor.black)
        content_layout.addWidget(preview_view, 1)

        histogram = _HistogramWidget()
        histogram.setFixedHeight(80)
        histogram.set_color(self._theme.accent_color)
        content_layout.addWidget(histogram)

        progress_widget = QWidget()   # a widget, not a bare layout, so it can move with the rest (IMG-120)
        progress_row = QHBoxLayout(progress_widget)
        progress_row.setContentsMargins(0, 0, 0, 0)
        status_label = QLabel("Idle")
        progress_row.addWidget(status_label)
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 1000)
        progress_bar.setValue(0)
        progress_bar.setTextVisible(False)
        progress_row.addWidget(progress_bar, 1)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)

        root.addWidget(content, 1)

        # --- landscape / portrait layout (IMG-120) -----------------------------
        # Landscape: preview on top of the right side, histogram/progress/log
        # beneath it. Portrait: the preview is a full-height column one third of
        # the page wide, and the nudge pad, histogram, progress and log sit in the
        # column to its left, beside the settings.
        secondary_widgets = (histogram, progress_widget, log_heading, log_pane)
        nudge_slot = settings_layout.indexOf(nudge_group)   # where the nudge pad sits in landscape
        layout_state = {"orientation": None}
        unlimited_width = 16777215   # QWIDGETSIZE_MAX

        def _log_height(lines: int) -> int:
            return log_pane.fontMetrics().lineSpacing() * lines + log_pane.frameWidth() * 2 + 8

        def _fit_preview_width() -> None:
            """Portrait: the preview column is a third of the page's width."""
            if layout_state["orientation"] == PORTRAIT:
                content.setFixedWidth(max(1, page.width() // 3))
            else:
                content.setMinimumWidth(0)
                content.setMaximumWidth(unlimited_width)

        def _apply_orientation() -> None:
            orientation = service.orientation
            if orientation == layout_state["orientation"]:
                return
            layout_state["orientation"] = orientation
            portrait = orientation == PORTRAIT
            for widget in (*secondary_widgets, nudge_group):
                content_layout.removeWidget(widget)
                dock_layout.removeWidget(widget)
                settings_layout.removeWidget(widget)
            if portrait:
                # The nudge pad leads the middle column; the rest follow, above its trailing stretch.
                for i, widget in enumerate((nudge_group, *secondary_widgets)):
                    dock_layout.insertWidget(i, widget)
                    widget.setVisible(True)
            else:
                settings_layout.insertWidget(nudge_slot, nudge_group)
                nudge_group.setVisible(True)
                for widget in secondary_widgets:
                    content_layout.addWidget(widget)
                    widget.setVisible(True)
            dock_panel.setVisible(portrait)
            histogram.setFixedHeight(120 if portrait else 80)
            log_pane.setFixedHeight(_log_height(12 if portrait else 10))
            content_layout.setContentsMargins(*((8, 8, 8, 8) if portrait else (24, 20, 24, 20)))
            _fit_preview_width()

        class _PageResizeWatcher(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Resize:
                    _fit_preview_width()
                return False

        resize_watcher = _PageResizeWatcher(page)
        page.installEventFilter(resize_watcher)

        # --- wiring -----------------------------------------------------------
        def _selected_camera_backend():
            # Reads the top-bar Camera selector (shown only when the current
            # Pier has more than one configured camera) fresh each time,
            # rather than caching it at page-build time.
            key = _camera_backend_key_for_slot(self._active_camera_slot)
            return self._camera_backends.get(key)

        service = ImagingService(camera=_selected_camera_backend())
        self._imaging_service = service

        def _refresh_preview() -> None:
            import numpy as np
            data = service.current_preview
            if data is None:
                return
            arr = np.ascontiguousarray(data)
            h, w = arr.shape[:2]
            if arr.ndim == 3:
                image = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
            else:
                image = QImage(arr.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
            pixmap_item.setPixmap(QPixmap.fromImage(image))
            scene.setSceneRect(0, 0, w, h)
            preview_view.resetTransform()
            preview_view.scale(zoom_spin.value(), zoom_spin.value())

        def _refresh_stats() -> None:
            stats = service.get_frame_stats()
            for key, value_label in stats_labels.items():
                value = stats.get(key)
                if value is None:
                    value_label.setText("—")
                elif isinstance(value, float):
                    value_label.setText(f"{value:.2f}")
                else:
                    value_label.setText(str(value))

        def _refresh_histogram() -> None:
            hist = service.get_histogram()
            histogram.set_data(hist.get("counts", []))

        def apply_zoom(factor: float) -> None:
            service.set_zoom(factor)
            preview_view.resetTransform()
            preview_view.scale(factor, factor)

        zoom_spin.valueChanged.connect(apply_zoom)

        def reset_view() -> None:
            service.reset_view()
            zoom_spin.blockSignals(True)
            zoom_spin.setValue(1.0)
            zoom_spin.blockSignals(False)
            preview_view.resetTransform()

        reset_view_btn.clicked.connect(reset_view)

        star_overlay_check.toggled.connect(service.set_star_overlay)

        def _use_camera_bayer_pattern(rebuild: bool) -> None:
            # The pattern saved for the selected camera on Equipment > Camera (RGGB until changed).
            from galileo.observatory import get_device_config
            pattern = None
            if self._current_pier is not None:
                try:
                    cfg = get_device_config(self._current_pier, "camera", slot=self._active_camera_slot)
                    pattern = cfg.bayer_pattern if cfg is not None else None
                except Exception:
                    logger.exception("Could not load the camera's Bayer pattern")
            service.set_bayer_pattern(pattern, rebuild=rebuild)

        # Debayer + stretch takes seconds on a large frame, so it renders on a worker thread
        # (numpy releases the GIL, so a thread is enough — NFR-PERF-020). Each toggle starts a
        # new render; the service drops any that finish after a newer toggle.
        preview_renders: set = set()

        def _preview_rendered(thread, rendered) -> None:
            preview_renders.discard(thread)
            if service.apply_preview(rendered):
                _refresh_preview()
                status_label.setText(service.debayer_note or "Debayer off.")

        def _debayer_toggled(checked: bool) -> None:
            _use_camera_bayer_pattern(rebuild=False)
            service.set_debayer(checked, rebuild=False)
            if service.current_frame is None:
                return
            status_label.setText("Debayering…" if checked else "Removing debayer…")
            thread = _PreviewRenderThread(service, self._window)
            thread.rendered.connect(lambda rendered, t=thread: _preview_rendered(t, rendered))
            thread.finished.connect(thread.deleteLater)
            preview_renders.add(thread)
            thread.start()

        debayer_check.toggled.connect(_debayer_toggled)
        self._imaging_preview_renders = preview_renders
        self._imaging_debayer_check = debayer_check

        def _orientation_choice_changed(*_args) -> None:
            if orientation_check.isChecked():
                service.set_manual_orientation(orientation_combo.currentData())
            else:
                service.set_manual_orientation(None)
            _apply_orientation()

        def _manual_orientation_toggled(checked: bool) -> None:
            orientation_combo.setEnabled(checked)
            if checked:
                # Start from what the page is showing now, so ticking the box doesn't move anything.
                orientation_combo.blockSignals(True)
                orientation_combo.setCurrentIndex(orientation_combo.findData(service.orientation))
                orientation_combo.blockSignals(False)
            _orientation_choice_changed()

        orientation_check.toggled.connect(_manual_orientation_toggled)
        orientation_combo.currentIndexChanged.connect(_orientation_choice_changed)

        # --- mount nudge (IMG-130) ---------------------------------------------
        nudge_state = {"thread": None}

        def _nudge_mount_adapter():
            return (self._device_pages.get("mount") or {}).get("adapter")

        def _set_nudge_busy(busy: bool) -> None:
            for btn in nudge_dir_buttons.values():
                btn.setEnabled(not busy)

        def _nudge(direction: str) -> None:
            mount = _nudge_mount_adapter()
            if mount is None:
                self._window.statusBar().showMessage("Connect the mount on Equipment > Mount to nudge it.", 4000)
                return
            if nudge_state["thread"] is not None:
                return
            reversed_getter = (self._device_pages.get("mount") or {}).get("axis_reversed")
            reversed_axes = reversed_getter() if reversed_getter is not None else (False, False)
            rate, duration = nudge_rate_combo.currentData(), nudge_duration_spin.value()

            def done() -> None:
                nudge_state["thread"] = None
                _set_nudge_busy(False)

            def failed(message: str) -> None:
                done()
                if "parked" in message.lower():
                    self._window.statusBar().showMessage(_PARKED_MESSAGE, 6000)
                else:
                    self._window.statusBar().showMessage("Nudge failed — see log.", 6000)
                logger.error("Mount nudge %s failed: %s", direction, message)

            thread = _NudgeThread(mount, direction, rate, duration, reversed_axes, self._window)
            thread.finished_ok.connect(done)
            thread.failed.connect(failed)
            nudge_state["thread"] = thread
            _set_nudge_busy(True)
            logger.info("Mount: nudge %s at %g°/s for %.1fs", direction, rate, duration)
            thread.start()

        for direction, btn in nudge_dir_buttons.items():
            btn.clicked.connect(lambda _checked=False, d=direction: _nudge(d))

        def _nudge_stop() -> None:
            mount = _nudge_mount_adapter()
            if mount is None:
                return
            import asyncio
            try:
                asyncio.run(mount.move_axis(0, 0.0))
                asyncio.run(mount.move_axis(1, 0.0))
            except Exception:
                logger.exception("Mount nudge stop failed")
            logger.info("Mount: nudge Stop requested")

        nudge_stop_btn.clicked.connect(_nudge_stop)

        self._imaging_ui = {
            "settings_panel": settings_panel, "dock_panel": dock_panel, "page": page,
            "fit_preview_width": _fit_preview_width, "content": content, "preview": preview_view,
            "histogram": histogram, "progress": progress_widget, "log": log_pane,
            "orientation_check": orientation_check, "orientation_combo": orientation_combo,
            "apply_orientation": _apply_orientation, "layout_state": layout_state,
            "quantity": quantity_spin, "gain": gain_spin, "auto_save": auto_save_check,
            "capture_button": capture_btn, "stop_button": stop_capture_btn, "status": status_label,
            "nudge_group": nudge_group, "nudge_buttons": nudge_dir_buttons, "nudge_stop": nudge_stop_btn,
            "nudge_rate": nudge_rate_combo, "nudge_duration": nudge_duration_spin,
            "nudge_state": nudge_state,
        }

        countdown = {"timer": None, "start": 0.0, "duration": 0.0, "frame": 1, "total": 1}

        def _tick_countdown() -> None:
            import time
            elapsed = time.monotonic() - countdown["start"]
            remaining = max(0.0, countdown["duration"] - elapsed)
            fraction = min(1.0, elapsed / countdown["duration"]) if countdown["duration"] else 1.0
            frame, total = countdown["frame"], countdown["total"]
            progress_bar.setValue(int((frame - 1 + fraction) / total * 1000))
            prefix = f"Frame {frame} of {total} — " if total > 1 else ""
            status_label.setText(f"{prefix}Exposing… {remaining:0.1f}s left" if remaining > 0 else f"{prefix}Downloading…")

        def on_slew_started(index: int, total: int) -> None:
            # Mosaic capture only (IMG-180): the re-slew to each pane can take as long as an
            # exposure, so it gets its own status text rather than looking like a stall.
            status_label.setText(f"Slewing to pane {index} of {total}…")

        def on_frame_started(frame: int, total: int) -> None:
            import time
            countdown["start"], countdown["frame"], countdown["total"] = time.monotonic(), frame, total

        def on_frame_done(_frame: int, _total: int) -> None:
            # Each frame is shown as it arrives, not only the last one of a series.
            _refresh_preview()
            _refresh_stats()
            _refresh_histogram()
            _apply_orientation()
            save_frame_btn.setEnabled(service.current_frame is not None)
            save_stack_btn.setEnabled(service.stack_frame_count > 0)

        def _refresh_library_images() -> None:
            images = getattr(getattr(self, "_library_screens", None), "images", None)
            if images is None:
                return              # the Library hasn't been opened yet; it reads the catalog when it is
            try:
                images.load_fits_data()
            except Exception:
                logger.exception("Could not refresh Library > Images")

        def _end_capture() -> None:
            timer = countdown["timer"]
            if timer is not None:
                timer.stop()
            capture_btn.setEnabled(True)
            stop_capture_btn.setEnabled(False)
            self._imaging_capture_thread = None

        def _series_summary() -> str:
            done, total = service.series_done, service.series_total
            text = ("Stopped" if service.stop_requested else "Complete") + (f" — {done} of {total} frames" if total > 1 or service.stop_requested else "")
            if service.debayer_note:
                text += f" — {service.debayer_note}"
            if service.auto_save_to_library:
                added = len(service.library_ids)
                text += f" — {added} added to the Library" if added else " — none added to the Library"
                if service.library_note:
                    text += f". {service.library_note}"
            if service.stacker.summary:
                text += f" — {service.stacker.summary}"
            return text

        def on_capture_finished() -> None:
            _end_capture()
            progress_bar.setValue(1000)
            save_stack_btn.setEnabled(service.stack_frame_count > 0)
            summary = _series_summary()
            status_label.setText(summary)
            status_label.setToolTip(summary)
            on_frame_done(0, 0)
            if service.library_ids:
                _refresh_library_images()
            self._window.statusBar().showMessage(summary, 6000)

        def on_capture_failed(message: str) -> None:
            _end_capture()
            status_label.setText("Idle")
            progress_bar.setValue(0)
            logger.error("Manual capture failed: %s", message)
            if service.library_ids:
                _refresh_library_images()
            self._window.statusBar().showMessage("Capture failed — see log.", 6000)

        def _refresh_mosaic_indicator() -> None:
            # IMG-180: makes it visible, before Capture is pressed, that a mosaic is active and
            # Capture will run the whole thing rather than a single frame (reported as missing —
            # a plain "Capture" button gave no hint a mosaic was about to be shot pane by pane).
            mosaic = service.active_mosaic
            active = mosaic is not None
            mosaic_indicator.setVisible(active)
            clear_mosaic_btn.setVisible(active)
            if active:
                mosaic_indicator.setText(
                    f"Mosaic active — {mosaic.cols}×{mosaic.rows} panels ({mosaic.total_panels} total). "
                    "Capture will slew to and expose every pane in turn, Quantity exposures each."
                )
                capture_btn.setText("Capture Mosaic")
                capture_btn.setToolTip(
                    "Slew to and expose every pane of the active mosaic in turn, Quantity exposures "
                    "at each, in pane-major order (IMG-180, FRAME-090). Clear Mosaic returns to a "
                    "single frame.")
                quantity_spin.setToolTip(
                    "How many exposures Capture takes at each pane before re-slewing to the next (IMG-180).")
            else:
                capture_btn.setText("Capture")
                capture_btn.setToolTip(
                    "Take Quantity frames one after another with these settings, independent of any "
                    "running sequence (IMG-070, IMG-150).")
                quantity_spin.setToolTip(
                    "How many frames Capture takes, one after another, with these settings (IMG-150).")

        def _clear_mosaic() -> None:
            service.active_mosaic = None
            _refresh_mosaic_indicator()
            self._window.statusBar().showMessage("Mosaic cleared — Capture will take a single frame.", 4000)

        clear_mosaic_btn.clicked.connect(_clear_mosaic)
        _refresh_mosaic_indicator()

        def do_capture() -> None:
            service._camera = _selected_camera_backend()
            if service._camera is None:
                QMessageBox.information(
                    self._window, "No camera connected", self.camera_not_connected_message(),
                )
                return
            if self._imaging_filter_thread is not None:
                self._window.statusBar().showMessage("Wait for the filter wheel to finish moving.", 4000)
                return

            mosaic_mode = service.active_mosaic is not None
            if mosaic_mode:
                service._mount = _nudge_mount_adapter()
                if service._mount is None:
                    QMessageBox.information(
                        self._window, "No mount connected",
                        "Capturing a mosaic needs a connected mount to move between panes — connect "
                        "one on Equipment > Mount, or use Clear Mosaic to take a single frame instead.",
                    )
                    return

            current = self.current_object()
            service.object_name = current.name if current is not None else ""
            duration = exposure_spin.value()
            quantity = quantity_spin.value()
            frame_type = frame_type_combo.currentText()
            filter_name = filter_combo.currentText().strip()
            service.gain = gain_spin.value()
            service.auto_save_to_library = auto_save_check.isChecked()
            service.live_stack_enabled = live_stack_check.isChecked()
            service.frame_context = self._imaging_frame_context()
            _use_camera_bayer_pattern(rebuild=False)

            import time
            countdown.update(start=time.monotonic(), duration=duration, frame=1, total=quantity)
            capture_btn.setEnabled(False)
            stop_capture_btn.setEnabled(True)
            progress_bar.setValue(0)
            status_label.setToolTip("")
            _tick_countdown()

            timer = QTimer(page)
            timer.timeout.connect(_tick_countdown)
            timer.start(100)
            countdown["timer"] = timer

            if mosaic_mode:
                thread = _MosaicCaptureThread(service, quantity, duration, filter_name, frame_type, page)
                thread.slew_started.connect(on_slew_started)
            else:
                thread = _CaptureThread(service, quantity, duration, filter_name, frame_type, page)
            thread.frame_started.connect(on_frame_started)
            thread.frame_done.connect(on_frame_done)
            thread.finished_ok.connect(on_capture_finished)
            thread.failed.connect(on_capture_failed)
            self._imaging_capture_thread = thread
            thread.start()

        capture_btn.clicked.connect(do_capture)

        def stop_capture() -> None:
            service.request_stop()
            status_label.setText("Stopping…")
            camera = service._camera
            if camera is not None:
                import asyncio
                try:
                    asyncio.run(camera.abort_exposure())
                except Exception:
                    logger.exception("Could not abort the exposure")

        stop_capture_btn.clicked.connect(stop_capture)

        def _open_framing() -> None:
            self._open_framing_dialog(service)
            _refresh_mosaic_indicator()

        framing_btn.clicked.connect(_open_framing)

        def save_frame() -> None:
            if service.current_frame is None:
                return
            current = self.current_object()
            service.object_name = current.name if current is not None else ""
            path, _ = QFileDialog.getSaveFileName(
                self._window, "Save Frame", service.suggested_filename(), "FITS files (*.fits *.fit)",
            )
            if not path:
                return
            try:
                service.save_current_frame(path)
            except Exception:
                logger.exception("Could not save frame to %s", path)
                self._window.statusBar().showMessage("Could not save frame — see log.", 6000)
                return
            logger.info("Saved frame to %s", path)
            self._window.statusBar().showMessage(f"Saved frame to {path}.", 4000)

        save_frame_btn.clicked.connect(save_frame)

        def save_stack_to_file() -> None:
            path, _ = QFileDialog.getSaveFileName(
                self._window, "Save Stack", service.stack_filename(), "FITS files (*.fits *.fit)",
            )
            if not path:
                return
            try:
                service.save_stack(path)
            except Exception:
                logger.exception("Could not save the stack to %s", path)
                self._window.statusBar().showMessage("Could not save the stack — see log.", 6000)
                return
            logger.info("Saved the stack of %d frames to %s", service.stack_frame_count, path)
            self._window.statusBar().showMessage(f"Saved the stack to {path}.", 4000)

        def save_stack_to_library() -> None:
            current = self.current_object()
            service.object_name = current.name if current is not None else ""
            try:
                file_id = service.save_stack_to_library()
            except Exception:
                logger.exception("Could not add the stack to the Library")
                self._window.statusBar().showMessage("Could not add the stack to the Library — see log.", 6000)
                return
            if file_id:
                _refresh_library_images()
                message = f"Added the stack of {service.stack_frame_count} frames to the Library."
                if service.library_note:
                    message += f" {service.library_note}"
                self._window.statusBar().showMessage(message, 6000)
            else:
                self._window.statusBar().showMessage(
                    service.library_note or "The stack was not added to the Library — see log.", 8000)

        def save_stack() -> None:
            """Ask where the stack should go — the Library files it in the repository, a file
            puts it wherever the user says."""
            if service.stack_frame_count == 0:
                return
            menu = QMenu(page)
            to_library = menu.addAction("Save to Library")
            to_file = menu.addAction("Save to File…")
            to_library.triggered.connect(save_stack_to_library)
            to_file.triggered.connect(save_stack_to_file)
            menu.exec(save_stack_btn.mapToGlobal(save_stack_btn.rect().bottomLeft()))

        save_stack_btn.clicked.connect(save_stack)
        self._imaging_ui.update({
            "live_stack": live_stack_check, "save_stack_button": save_stack_btn,
            "save_stack_to_library": save_stack_to_library, "save_stack_to_file": save_stack_to_file,
        })

        _apply_orientation()
        return page
