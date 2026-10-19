# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Builds the Solve page's controls (left column, tabs, polar-alignment tab, log pane)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton, QSpinBox, QSplitter, QTableWidget, QTabWidget, QVBoxLayout, QWidget
from galileo.platesolve import SolveAction
from galileo.ui._image_view import build_zoom_toolbar
from galileo.ui.solve_widgets import PolarTargetPlot, SolveErrorPlot, SolveImageView


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

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as _MixinBase  # type checkers see a widget (it is mixed into one)
else:
    _MixinBase = object




class SolveBuildMixin(_MixinBase):
    """Builds the Solve page's controls (left column, tabs, polar-alignment tab, log pane)."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)

        root.addWidget(self._build_left_column())

        right = QVBoxLayout()
        right.setSpacing(8)
        upper = QVBoxLayout()
        self.image_view = SolveImageView()
        upper.addLayout(self._build_image_tools())
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
        self.busy.setProperty("helpKey", "busy")
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
        self.action_radios[SolveAction.SLEW_TO_TARGET].setChecked(True)
        for radio in self.action_radios.values():
            layout.addWidget(radio)
        self.target_label = QLabel()
        self.target_label.setProperty("helpKey", "target")
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
        self.bin_combo = QComboBox()
        self.bin_combo.addItems(["1x1", "2x2", "3x3", "4x4"])
        self.bin_combo.setToolTip("Camera binning for solve frames. Binning makes stars brighter and the frame smaller, "
                                  "so it solves faster.")
        form.addRow("Bin:", self.bin_combo)
        self.gain_spin = QSpinBox()
        self.gain_spin.setRange(0, 100000)
        self.gain_spin.setSpecialValueText("Camera")
        self.gain_spin.setToolTip("Gain for solve frames (the ISO value for a DSLR). Camera leaves it as configured.")
        form.addRow("Gain/ISO:", self.gain_spin)
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("Current")
        self.filter_combo.setToolTip("Filter to solve through. Current leaves the filter wheel where it is.")
        form.addRow("Filter:", self.filter_combo)
        layout.addLayout(form)
        self.dark_check = QCheckBox("Dark")
        self.dark_check.setToolTip("Take a dark frame of the same exposure after each solve frame and subtract it, "
                                   "which removes hot pixels that can confuse the solver.")
        layout.addWidget(self.dark_check)
        box.addWidget(options)

        # Solver Mode ------------------------------------------------------
        mode, layout = _heading_box("Solver Mode")
        mode_row = QHBoxLayout()
        self.astap_radio = QRadioButton("ASTAP")
        self.astap_radio.setChecked(True)
        self.astap_radio.setToolTip("The local ASTAP solver; works with no internet connection.")
        mode_row.addWidget(self.astap_radio)
        self.astrometry_radio = QRadioButton("Astrometry.net")
        self.astrometry_radio.setToolTip("A local astrometry.net installation (solve-field) with its index files; "
                                         "works with no internet connection.")
        mode_row.addWidget(self.astrometry_radio)
        self.nova_radio = QRadioButton("Nova (web)")
        self.nova_radio.setToolTip("The nova.astrometry.net web service. Needs an internet connection and an API key "
                                   "(Options > Solve); the frame is uploaded to the service.")
        mode_row.addWidget(self.nova_radio)
        self.tetra3_radio = QRadioButton("Tetra3")
        self.tetra3_radio.setToolTip("ESA's tetra3 solver, run inside Galileo; works with no internet connection. "
                                     "Needs the tetra3 package (Options > Solve).")
        mode_row.addWidget(self.tetra3_radio)
        self._mode_backends = {self.astap_radio: "astap", self.astrometry_radio: "astrometry_local",
                               self.nova_radio: "astrometry_web", self.tetra3_radio: "tetra3"}
        layout.addLayout(mode_row)
        box.addWidget(mode)

        box.addStretch(1)
        return column

    def _build_image_tools(self) -> QHBoxLayout:
        self.frame_label = QLabel("No frame yet")
        self.frame_label.setProperty("helpKey", "frame")
        self.image_view.setProperty("helpKey", "frame")
        return build_zoom_toolbar(self.image_view, self.frame_label)

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
        self.table.setProperty("helpKey", "solution results")
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
        self.error_plot.setProperty("helpKey", "error plot")
        splitter.addWidget(self.error_plot)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        tabs.addTab(results, "Solution Results")

        polar = self._build_polar_tab()
        tabs.addTab(polar, "Polar Alignment")
        return tabs

    def _build_polar_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        intro = QLabel(
            "Point the scope at the pole to begin (roughly polar-aligned, Polaris in the field), then start. Galileo "
            "moves away from the pole to about Dec 70° (solves are unreliable at the pole), solves three frames while "
            "turning the mount in RA to find where the axis really points, then keeps solving. Turn the altitude and "
            "azimuth adjusters to bring the X (the celestial pole) into the circle (where the axis points now). The "
            "mount must be level, and should not be near the meridian, where it would flip.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QHBoxLayout()
        self.polar_start_btn = QPushButton("Start Polar Alignment")
        self.polar_start_btn.setObjectName("AccentButton")
        self.polar_start_btn.setToolTip("Uses the exposure under Plate Solve Capture Options. Stop ends it.")
        self.polar_start_btn.clicked.connect(self.start_polar_alignment)
        controls.addWidget(self.polar_start_btn)
        controls.addWidget(QLabel("Rotate:"))
        self.polar_step_spin = QSpinBox()
        self.polar_step_spin.setRange(10, 90)
        self.polar_step_spin.setValue(30)
        self.polar_step_spin.setSuffix("°")
        self.polar_step_spin.setToolTip("How far the mount turns in RA between the three measuring frames.")
        controls.addWidget(self.polar_step_spin)
        self.polar_direction = QComboBox()
        self.polar_direction.addItem("East", "east")
        self.polar_direction.addItem("West", "west")
        self.polar_direction.setProperty("helpKey", "direction")
        self.polar_direction.setToolTip("Which way the RA axis turns. Pick the side with clear sky and room before a mount limit.")
        controls.addWidget(self.polar_direction)
        self.polar_refraction = QCheckBox("Refraction")
        self.polar_refraction.setChecked(True)
        self.polar_refraction.setToolTip(
            "Allow for the atmosphere raising stars, so the mount is aimed where it must point to see them. The "
            "target stays the geometric pole.")
        controls.addWidget(self.polar_refraction)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.polar_status = QLabel("Not started.")
        self.polar_status.setProperty("helpKey", "polar alignment status")
        self.polar_status.setWordWrap(True)
        layout.addWidget(self.polar_status)
        self.polar_total = QLabel("—")
        self.polar_total.setProperty("helpKey", "total error")
        font = self.polar_total.font()
        font.setPointSize(font.pointSize() + 8)
        font.setBold(True)
        self.polar_total.setFont(font)
        layout.addWidget(self.polar_total)
        self.polar_altitude = QLabel("")
        self.polar_azimuth = QLabel("")
        self.polar_altitude.setProperty("helpKey", "altitude correction")
        self.polar_azimuth.setProperty("helpKey", "azimuth correction")
        layout.addWidget(self.polar_altitude)
        layout.addWidget(self.polar_azimuth)
        self.polar_target_hint = QLabel("")
        self.polar_target_hint.setWordWrap(True)
        self.polar_target_hint.setProperty("helpKey", "polar target")
        layout.addWidget(self.polar_target_hint)
        self.polar_target = PolarTargetPlot()
        self.polar_target.setProperty("helpKey", "polar target")
        self.polar_target.setToolTip(
            "The circle is where the mount's polar axis points now; the X is the celestial pole. Turn the altitude "
            "and azimuth adjusters to bring the X into the circle.")
        layout.addWidget(self.polar_target, 1)
        return tab

    def _build_log_pane(self) -> QWidget:
        """The live log tail, the full width of the page. It is refreshed by a timer that only runs
        while the page is on screen (the Equipment screens' panes refresh whether shown or not)."""
        self.log_pane = self._window._build_log_pane()
        self.log_pane.setFixedHeight(self.log_pane.fontMetrics().lineSpacing() * 7 + 12)
        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._refresh_log)
        return self.log_pane
