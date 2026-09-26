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
import math
import threading
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from galileo.bus import SolveCompleteEvent, SolveStartedEvent, get_bus
from galileo.current_object import get_current_objects
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
from galileo.ui.guider import _PlotBase

logger = logging.getLogger(__name__)

_LOG_TAIL_LINES = 300
_LOG_REFRESH_MS = 1000
_MAX_PREVIEW_PX = 2400          # larger frames are shown subsampled; the solver always gets the full frame
_MOUNT_POLL_MS = 3000
_ARCSEC_PER_RAD_UM_MM = 206.265  # plate scale in ″/px = 206.265 × pixel size (µm) / focal length (mm)


@dataclass
class SolveRow:
    """One solve, as one row of the results table."""
    fits_path: str
    status: str = "solving"                      # "solving" | "solved" | "failed"
    ra_deg: float | None = None                  # J2000
    dec_deg: float | None = None
    rotation_deg: float | None = None
    scale_arcsec_px: float | None = None
    reason: str = ""
    name: str = ""
    width_px: int = 0
    height_px: int = 0
    target: tuple[float, float] | None = None    # J2000; what the solution is compared against
    d_ra_arcsec: float | None = None             # solution minus target, east positive
    d_dec_arcsec: float | None = None            # solution minus target, north positive

    @property
    def error_arcsec(self) -> float | None:
        if self.d_ra_arcsec is None or self.d_dec_arcsec is None:
            return None
        return math.hypot(self.d_ra_arcsec, self.d_dec_arcsec)


def load_preview(path: str) -> np.ndarray | None:
    """The frame at *path* as an auto-stretched 8-bit array ``(h, w)`` or ``(h, w, 3)``, sub-sampled
    if very large. ``None`` if it can't be read (the frame may be gone or half written)."""
    try:
        from astropy.io import fits

        from galileo.ui.imaging import _auto_stretch
        data = np.asarray(fits.getdata(path))
        if data.ndim == 3:                           # FITS stores colour plane-first
            data = np.moveaxis(data[:3], 0, -1) if data.shape[0] >= 3 else data[0]
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


def _nice_step(raw: float) -> float:
    """Round *raw* to 1, 2, 5 or 10 times a power of ten — an axis tick spacing people can read."""
    magnitude = 10 ** math.floor(math.log10(raw))
    fraction = raw / magnitude
    return magnitude * (1 if fraction < 1.5 else 2 if fraction < 3.5 else 5 if fraction < 7.5 else 10)


def _heading_box(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(8, 6, 8, 8)
    layout.setSpacing(4)
    return box, layout


def _value_label() -> QLabel:
    label = QLabel("—")
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class SolveErrorPlot(_PlotBase):
    """Where each solution landed relative to its target: dRA against dDE, with rings at
    1×, 2× and 3× the accuracy the user asked for. The newest solution is drawn brightest."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(220, 220)
        self.points: list[tuple[float, float]] = []
        self.ring = 30.0                # arcsec; radius of the green ring

    def set_points(self, points: list[tuple[float, float]]) -> None:
        self.points = points
        self.update()

    def set_ring(self, arcsec: float) -> None:
        self.ring = arcsec
        self.update()

    def paintEvent(self, event) -> None:
        painter = self._begin()
        side = min(self.width() - 56, self.height() - 44)
        if side < 40:
            painter.end()
            return
        plot = QRectF((self.width() - side) / 2 + 12, 8, side, side)
        c = plot.center()
        half = max(self.ring * 3.3, max((max(abs(x), abs(y)) for x, y in self.points), default=0.0) * 1.15)
        k = side / 2 / half

        # axes and ticks
        painter.setPen(QPen(QColor("#e0d030"), 1))
        painter.drawLine(QPointF(plot.left(), c.y()), QPointF(plot.right(), c.y()))
        painter.drawLine(QPointF(c.x(), plot.top()), QPointF(c.x(), plot.bottom()))
        step = _nice_step(half / 4)
        painter.setPen(QColor("#c8c8c8"))
        tick = step
        while tick < half:
            for sign in (1, -1):
                painter.drawText(QRectF(c.x() + sign * tick * k - 20, plot.bottom() + 2, 40, 14), Qt.AlignmentFlag.AlignCenter, f"{sign * tick:g}")
                painter.drawText(QRectF(plot.left() - 34, c.y() - sign * tick * k - 7, 30, 14),
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{sign * tick:g}")
            tick += step

        # accuracy rings
        for mult, color in ((1, "#31c24a"), (2, "#e0c030"), (3, "#d63a3a")):
            fill = QColor(color)
            fill.setAlpha(36)
            painter.setPen(QPen(QColor(color), 1.4))
            painter.setBrush(fill)
            radius = mult * self.ring * k
            painter.drawEllipse(c, radius, radius)

        # solutions
        n = len(self.points)
        for i, (x, y) in enumerate(self.points):
            dot = QColor("#ffffff")
            dot.setAlpha(80 + int(175 * (i + 1) / n))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot)
            painter.drawEllipse(QPointF(c.x() + x * k, c.y() - y * k), 2.6, 2.6)
        painter.setPen(QColor("#c8c8c8"))
        painter.drawText(QRectF(plot.left(), plot.bottom() + 14, side, 14), Qt.AlignmentFlag.AlignCenter, "dRA (arcsec)")
        painter.save()
        painter.translate(10, c.y())
        painter.rotate(-90)
        painter.drawText(QRectF(-50, -8, 100, 14), Qt.AlignmentFlag.AlignCenter, "dDE (arcsec)")
        painter.restore()
        painter.end()


class SolveImageView(QGraphicsView):
    """The frame being solved. Fits the window until the user zooms; drag to pan."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SolveImage")
        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self.setScene(self._scene)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.setMinimumHeight(200)
        self.fit = True
        self.has_image = False

    def show_array(self, array: np.ndarray) -> None:
        arr = np.ascontiguousarray(array)
        h, w = arr.shape[:2]
        if arr.ndim == 3:
            image = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        else:
            image = QImage(arr.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
        self._item.setPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(0, 0, w, h)
        self.has_image = True
        if self.fit:
            self.fit_to_window()

    def clear_image(self) -> None:
        self._item.setPixmap(QPixmap())
        self.has_image = False

    def fit_to_window(self) -> None:
        self.fit = True
        if self.has_image:
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self) -> None:
        self.fit = False
        self.resetTransform()

    def zoom(self, factor: float) -> None:
        self.fit = False
        self.scale(factor, factor)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.fit:
            self.fit_to_window()


class SolvePage(QWidget):
    """The Solve section."""

    # Emitted from worker threads, received on the UI thread.
    solve_started = Signal(object)
    solve_finished = Signal(object)
    preview_ready = Signal(object)
    mount_position = Signal(object)
    run_finished = Signal()

    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("SolvePage")
        self._window = window
        self._rows: list[SolveRow] = []
        self._workflow: SolveWorkflow | None = None
        self._running = False
        self._run_target_active = False          # a workflow of ours owns the current solves' target
        self._in_focus = False                   # read by worker threads; set only from showEvent/hideEvent
        self._latest_path: str | None = None
        self._shown_path: str | None = None
        self._loading_path: str | None = None
        self._mount_busy = False
        self.make_solver = self._default_solver  # replaced by tests

        self._build()
        self._set_running(False)
        self.refresh_view()
        self.refresh_target()

        self.solve_started.connect(self._on_solve_started)
        self.solve_finished.connect(self._on_solve_finished)
        self.preview_ready.connect(self._on_preview_ready)
        self.mount_position.connect(self._on_mount_position)
        self.run_finished.connect(self._on_run_finished)

        self._mount_timer = QTimer(self)
        self._mount_timer.timeout.connect(self.poll_mount)

        bus = get_bus()
        self._bus_handlers = ((SolveStartedEvent, self._on_bus_started), (SolveCompleteEvent, self._on_bus_complete))
        for event_type, handler in self._bus_handlers:
            bus.subscribe(event_type, handler)
        self.destroyed.connect(lambda _=None, handlers=self._bus_handlers: self._unsubscribe(handlers))

    # --- Layout -----------------------------------------------------------

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)

        root.addWidget(self._build_left_column())

        right = QVBoxLayout()
        right.setSpacing(8)
        upper = QVBoxLayout()
        upper.addLayout(self._build_image_tools())
        self.image_view = SolveImageView()
        upper.addWidget(self.image_view, 1)
        right.addLayout(upper, 3)
        right.addWidget(self._build_tabs(), 2)
        right.addWidget(self._build_log_pane())
        root.addLayout(right, 1)

    def _build_left_column(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(330)
        box = QVBoxLayout(column)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)

        title = QLabel("Solve")
        title.setObjectName("PageTitle")
        box.addWidget(title)

        # Solver Control ---------------------------------------------------
        control, layout = _heading_box("Solver Control")
        self.capture_btn = QPushButton("Capture && Solve")
        self.capture_btn.setObjectName("AccentButton")
        self.capture_btn.setToolTip(
            "Take an exposure with the selected camera, solve it, then do the Solver Action below.")
        self.capture_btn.clicked.connect(self.capture_and_solve)
        layout.addWidget(self.capture_btn)
        self.load_btn = QPushButton("Load && Slew…")
        self.load_btn.setToolTip("Solve a FITS file from disk and slew the mount to where it points.")
        self.load_btn.clicked.connect(self.load_and_slew)
        layout.addWidget(self.load_btn)
        stop_row = QHBoxLayout()
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop)
        stop_row.addWidget(self.stop_btn, 1)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedSize(46, 12)
        stop_row.addWidget(self.busy)
        layout.addLayout(stop_row)
        box.addWidget(control)

        # Solver Action ----------------------------------------------------
        action, layout = _heading_box("Solver Action")
        self.action_radios = {
            SolveAction.SYNC: QRadioButton("Sync"),
            SolveAction.SLEW_TO_TARGET: QRadioButton("Slew to Target"),
            SolveAction.NOTHING: QRadioButton("Nothing"),
        }
        self.action_radios[SolveAction.SYNC].setToolTip("Tell the mount where it is really pointing.")
        self.action_radios[SolveAction.SLEW_TO_TARGET].setToolTip(
            "Slew to the target, then solve, sync and slew again until within Accuracy. The target is the "
            "Pier's current object (picked in the Star Atlas); with none, it is where the mount was "
            "pointing when Capture & Solve began.")
        self.action_radios[SolveAction.NOTHING].setToolTip("Only solve; leave the mount alone.")
        self.action_radios[SolveAction.NOTHING].setChecked(True)
        for radio in self.action_radios.values():
            layout.addWidget(radio)
        self.target_label = QLabel()
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)
        box.addWidget(action)

        # Telescope Coordinates --------------------------------------------
        scope, layout = _heading_box("Telescope Coordinates (JNow)")
        grid = QGridLayout()
        grid.addWidget(QLabel("RA:"), 0, 0)
        self.scope_ra = QLineEdit()
        self.scope_ra.setReadOnly(True)
        grid.addWidget(self.scope_ra, 0, 1)
        grid.addWidget(QLabel("Accuracy:"), 0, 2)
        self.accuracy_spin = QSpinBox()
        self.accuracy_spin.setRange(1, 3600)
        self.accuracy_spin.setValue(30)
        self.accuracy_spin.setSuffix("″")
        self.accuracy_spin.setFixedWidth(84)
        self.accuracy_spin.setToolTip("Slew to Target repeats until the solution is within this many arcseconds of the target.")
        self.accuracy_spin.valueChanged.connect(lambda value: (self.error_plot.set_ring(float(value))))
        grid.addWidget(self.accuracy_spin, 0, 3)
        grid.addWidget(QLabel("DE:"), 1, 0)
        self.scope_dec = QLineEdit()
        self.scope_dec.setReadOnly(True)
        grid.addWidget(self.scope_dec, 1, 1)
        grid.addWidget(QLabel("Settle:"), 1, 2)
        self.settle_spin = QSpinBox()
        self.settle_spin.setRange(0, 60000)
        self.settle_spin.setSingleStep(100)
        self.settle_spin.setValue(1500)
        self.settle_spin.setSuffix(" ms")
        self.settle_spin.setFixedWidth(84)
        self.settle_spin.setToolTip("How long to wait after a slew before taking the next frame.")
        grid.addWidget(self.settle_spin, 1, 3)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        box.addWidget(scope)

        # Solution Coordinates ---------------------------------------------
        solution, layout = _heading_box("Solution Coordinates (JNow)")
        grid = QGridLayout()
        self.solution: dict[str, QLabel] = {key: _value_label() for key in
                                            ("ra", "dec", "err", "pix", "pa", "fov", "ratio", "fl", "fnum")}
        self.solution["ratio"].setToolTip("The solved pixel scale divided by the scale the optical train predicts.")
        for row, cells in enumerate((("RA:", "ra", "DE:", "dec"), ("Err:", "err", None, None),
                                     ("Pix:", "pix", "PA:", "pa"), ("FOV:", "fov", "R:", "ratio"),
                                     ("FL:", "fl", "F/:", "fnum"))):
            grid.addWidget(QLabel(cells[0]), row, 0)
            if cells[2] is None:
                grid.addWidget(self.solution[cells[1]], row, 1, 1, 3)
            else:
                grid.addWidget(self.solution[cells[1]], row, 1)
                grid.addWidget(QLabel(cells[2]), row, 2)
                grid.addWidget(self.solution[cells[3]], row, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
        box.addWidget(solution)

        # Capture Options --------------------------------------------------
        options, layout = _heading_box("Plate Solve Capture Options")
        form = QFormLayout()
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(0.001, 600.0)
        self.exposure_spin.setDecimals(2)
        self.exposure_spin.setValue(5.0)
        self.exposure_spin.setSuffix(" s")
        form.addRow("Exp:", self.exposure_spin)
        layout.addLayout(form)
        box.addWidget(options)

        # Solver Mode ------------------------------------------------------
        mode, layout = _heading_box("Solver Mode")
        mode_row = QHBoxLayout()
        self.astap_radio = QRadioButton("ASTAP")
        self.astap_radio.setChecked(True)
        self.astap_radio.setToolTip("The local ASTAP solver; works with no internet connection.")
        mode_row.addWidget(self.astap_radio)
        layout.addLayout(mode_row)
        box.addWidget(mode)

        box.addStretch(1)
        return column

    def _build_image_tools(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        self.frame_label = QLabel("No frame yet")
        row.addWidget(self.frame_label, 1)
        for text, tip, slot in (
            ("Fit", "Fit the whole frame in the window.", lambda: self.image_view.fit_to_window()),
            ("1:1", "Show the frame at actual size.", lambda: self.image_view.actual_size()),
            ("+", "Zoom in.", lambda: self.image_view.zoom(1.25)),
            ("−", "Zoom out.", lambda: self.image_view.zoom(0.8)),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.setFixedWidth(40)
            button.clicked.connect(slot)
            row.addWidget(button)
        return row

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()

        results = QWidget()
        layout = QVBoxLayout(results)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(QLabel("The results of each solve, from Capture & Solve, Load & Slew, or any other part of Galileo, appear below."))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["RA", "DEC", "Obj Name", "Result", "dRA", "dDE"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        left_box.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.clear_results_btn = QPushButton("Clear")
        self.clear_results_btn.setToolTip("Remove every result.")
        self.clear_results_btn.clicked.connect(self.clear_results)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setToolTip("Remove the selected results.")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.save_btn = QPushButton("Save…")
        self.save_btn.setToolTip("Save the results as a CSV file.")
        self.save_btn.clicked.connect(self.save_results)
        for button in (self.clear_results_btn, self.remove_btn, self.save_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        left_box.addLayout(buttons)
        splitter.addWidget(left)

        self.error_plot = SolveErrorPlot()
        splitter.addWidget(self.error_plot)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        tabs.addTab(results, "Solution Results")

        polar = QWidget()
        polar_layout = QVBoxLayout(polar)
        message = QLabel("Polar alignment is not implemented yet.")
        message.setObjectName("PageSubtitle")
        polar_layout.addWidget(message)
        polar_layout.addStretch(1)
        tabs.addTab(polar, "Polar Alignment")
        return tabs

    def _build_log_pane(self) -> QWidget:
        """The live log tail, the full width of the page. It is refreshed by a timer that only runs
        while the page is on screen (the Equipment screens' panes refresh whether shown or not)."""
        self.log_pane = self._window._build_log_pane()
        self.log_pane.setFixedHeight(self.log_pane.fontMetrics().lineSpacing() * 7 + 12)
        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._refresh_log)
        return self.log_pane

    # --- Focus ------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._in_focus = True
        self.refresh_target()
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
        """A different Pier was selected: its mount is not the one on show."""
        self.refresh_target()
        self.scope_ra.clear()
        self.scope_dec.clear()
        if self.isVisible():
            self.refresh_view()
            self.poll_mount()

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
        payload = {"path": event.fits_path, "result": result, "size": frame_size(event.fits_path), "name": ""}
        if result.success:
            payload["name"] = nearest_object_name(result.ra_deg, result.dec_deg)
        self._emit("solve_finished", payload)

    def _load_preview_async(self, path: str) -> None:
        if path == self._loading_path:
            return
        self._loading_path = path

        def work() -> None:
            self._emit("preview_ready", {"path": path, "array": load_preview(path)})
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
            workflow = self._workflow
            if self._run_target_active and workflow is not None and workflow.target is not None:
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

    def _on_mount_position(self, payload) -> None:
        """*payload* is the mount's position, or empty if there is no mount or it couldn't be read."""
        self._mount_busy = False
        if not self.isVisible():
            return
        if not payload:
            self.scope_ra.clear()
            self.scope_dec.clear()
            return
        from galileo.ui.app_window import _format_dms, _format_hms
        ra, dec = j2000_to_mount_frame(*mount_frame_to_j2000(payload["ra_deg"], payload["dec_deg"], payload["system"]), None)
        self.scope_ra.setText(_format_hms(ra / 15.0))
        self.scope_dec.setText(_format_dms(dec))

    def _on_run_finished(self) -> None:
        self._set_running(False)
        self._run_target_active = False

    # --- Rendering (only while visible) -----------------------------------

    def refresh_view(self) -> None:
        """Bring every widget up to date with the recorded solves. Called only while the page is on screen."""
        self._render_table()
        self.error_plot.set_points([(r.d_ra_arcsec, r.d_dec_arcsec) for r in self._rows
                                    if r.d_ra_arcsec is not None and r.d_dec_arcsec is not None])
        self._render_solution()
        self._update_frame_label()

    def _render_table(self) -> None:
        from galileo.ui.app_window import _format_dms, _format_hms
        table = self.table
        table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            if row.ra_deg is not None and row.dec_deg is not None:
                ra, dec = j2000_to_mount_frame(row.ra_deg, row.dec_deg, None)
                ra_text, dec_text = _format_hms(ra / 15.0), _format_dms(dec)
            else:
                ra_text = dec_text = ""
            status = {"solving": "…", "solved": "✔", "failed": "✘"}[row.status]
            cells = [
                ra_text, dec_text, row.name, status,
                "" if row.d_ra_arcsec is None else f"{row.d_ra_arcsec:+.1f}″",
                "" if row.d_dec_arcsec is None else f"{row.d_dec_arcsec:+.1f}″",
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if column != 2 else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                if column == 3 and row.status == "failed":
                    item.setToolTip(row.reason)
                table.setItem(i, column, item)
        table.scrollToBottom()

    def _render_solution(self) -> None:
        from galileo.ui.app_window import _format_dms, _format_hms
        values = self.solution
        row = next((r for r in reversed(self._rows) if r.status == "solved"), None)
        if row is None or row.ra_deg is None or row.dec_deg is None:
            for label in values.values():
                label.setText("—")
            return
        ra, dec = j2000_to_mount_frame(row.ra_deg, row.dec_deg, None)
        values["ra"].setText(_format_hms(ra / 15.0))
        values["dec"].setText(_format_dms(dec))
        error = row.error_arcsec
        values["err"].setText("—" if error is None else
                              f"{error:.1f}″  (dRA {row.d_ra_arcsec:+.1f}″, dDE {row.d_dec_arcsec:+.1f}″)")
        scale = row.scale_arcsec_px
        values["pix"].setText(f"{scale:.2f}″" if scale else "—")
        values["pa"].setText(f"{row.rotation_deg:.2f}°" if row.rotation_deg is not None else "—")
        if scale and row.width_px and row.height_px:
            values["fov"].setText(f"{row.width_px * scale / 60:.1f}′ × {row.height_px * scale / 60:.1f}′")
        else:
            values["fov"].setText("—")

        focal, aperture, pixel_um = self._optics()
        expected_scale = _ARCSEC_PER_RAD_UM_MM * pixel_um / focal if focal and pixel_um else None
        solved_focal = _ARCSEC_PER_RAD_UM_MM * pixel_um / scale if scale and pixel_um else None
        values["ratio"].setText(f"{scale / expected_scale:.2f}x" if scale and expected_scale else "—")
        values["fl"].setText(
            "—" if solved_focal is None else
            f"{solved_focal:.1f}" + (f" ({focal:g})" if focal else ""))
        if solved_focal and aperture:
            values["fnum"].setText(f"{solved_focal / aperture:.1f}" + (f" ({focal / aperture:.1f})" if focal else ""))
        else:
            values["fnum"].setText("—")

    def _refresh_log(self) -> None:
        from galileo.diagnostics import get_recent_log_lines
        self._window.set_log_pane_text(self.log_pane, "\n".join(get_recent_log_lines(_LOG_TAIL_LINES)))

    def _update_frame_label(self) -> None:
        latest = self._rows[-1] if self._rows else None
        if latest is None:
            self.frame_label.setText("No frame yet")
            return
        import os
        state = {"solving": "solving…", "solved": "solved", "failed": "failed"}[latest.status]
        self.frame_label.setText(f"{os.path.basename(latest.fits_path)} — {state}")

    def _show_latest_frame(self) -> None:
        """Bring the image up to date after being hidden."""
        if self._latest_path and self._shown_path != self._latest_path:
            self._load_preview_async(self._latest_path)

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
        mount = self._mount()
        if mount is None:
            self._on_mount_position({})
            return
        if self._mount_busy or self._running:      # a running workflow reads the mount itself
            return
        self._mount_busy = True

        def work() -> None:
            payload = None
            try:
                status = asyncio.run(mount.get_status()) or {}
                if status.get("right_ascension") is not None and status.get("declination") is not None:
                    payload = {"ra_deg": status["right_ascension"] * 15.0, "dec_deg": status["declination"],
                               "system": status.get("equatorial_system")}
            except Exception:
                logger.debug("Could not read the mount position for the Solve screen", exc_info=True)
            self._emit("mount_position", payload or {})

        threading.Thread(target=work, name="solve-mount", daemon=True).start()

    # --- Running ----------------------------------------------------------

    def _default_solver(self) -> PlateSolver | None:
        from galileo.observatory import get_solver_settings
        executable, params = get_solver_settings(self._window._current_pier)
        solver = PlateSolver(backend="astap", executable=executable, params=params)
        if not solver.executable:
            QMessageBox.information(
                self._window._window, "ASTAP not found",
                "Solving needs the ASTAP solver and a star database (both free from hnsky.org/astap.htm). "
                "Install them, then try again.")
            return None
        return solver

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.capture_btn.setEnabled(not running)
        self.load_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.busy.setVisible(running)

    def _selected_action(self) -> SolveAction:
        return next(action for action, radio in self.action_radios.items() if radio.isChecked())

    def _post(self, message: str) -> None:
        """The workflow's log callback — called on its thread. The log pane shows the application's
        log, so this is all it takes for a line to appear there."""
        logger.info("%s", message)

    def _begin(self, run, use_current_object: bool = False) -> None:
        solver = self.make_solver()
        if solver is None:
            return
        self._workflow = SolveWorkflow(solver, camera=self._camera(), mount=self._mount(), log=self._post,
                                       frame_metadata=self._frame_metadata())
        obj = self.current_object() if use_current_object else None   # Load & Slew has its own idea of where to go
        if obj is not None:
            self._workflow.set_target(obj.ra_deg, obj.dec_deg, obj.name)
        self._run_target_active = True
        self._set_running(True)

        def work() -> None:
            try:
                asyncio.run(run(self._workflow))
            except Exception:
                logger.exception("Plate-solve run failed")
            finally:
                self._emit("run_finished")
        threading.Thread(target=work, name="solve-run", daemon=True).start()

    def capture_and_solve(self) -> None:
        if self._running:
            return
        if self._camera() is None:
            QMessageBox.information(self._window._window, "No camera connected",
                                    self._window.camera_not_connected_message())
            return
        settings = SolveSettings(
            exposure_s=self.exposure_spin.value(), action=self._selected_action(),
            accuracy_arcsec=float(self.accuracy_spin.value()), settle_s=self.settle_spin.value() / 1000.0,
            scale_hint_arcsec_px=self._scale_hint(),
        )
        self._begin(lambda workflow: workflow.capture_and_solve(settings), use_current_object=True)

    def load_and_slew(self) -> None:
        if self._running:
            return
        path, _ = QFileDialog.getOpenFileName(self._window._window, "Load & Slew", "", "FITS files (*.fits *.fit *.fts)")
        if not path:
            return
        self._begin(lambda workflow: workflow.solve_file(path, slew=True))

    def stop(self) -> None:
        if self._workflow is not None:
            self._workflow.stop()

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
