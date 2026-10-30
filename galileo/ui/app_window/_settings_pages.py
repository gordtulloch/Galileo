# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Options section's per-section settings pages (Star Atlas/Planning, Imaging, Focus, Solve) and the bulk thumbnail-caching action they share."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _new_form_layout, _OBSTRUCTED_MESSAGE, QWidget
from ._threads import _ThumbnailCacheThread

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowSettingsPagesMixin:
    def _build_star_atlas_settings_page(self: AppWindowState) -> QWidget:
        """Options > Star Atlas: upload a file of azimuth/altitude pairs describing the
        horizon obstructions at the current Observatory, or edit them point by point
        (SKY-040). They are kept in a table shown here, shaded on the Star Atlas by its
        "Horizon" checkbox, and (with Options > Planning) used to refuse slews into them."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
            QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
        )
        from galileo.observatory import save_horizon_points
        from galileo.planning.visibility import parse_horizon_text

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Star Atlas settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        subtitle = QLabel("Horizon obstructions")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)

        hint = QLabel(
            "Upload a text file with one “azimuth altitude” pair per line, or edit points directly "
            "in the table below (degrees; azimuth from north through east, 0–360; altitude 0–90). "
            "Each altitude is the height of the obstruction at that azimuth — the sky below it is "
            "blocked. The values are joined by straight lines, wrapping through north. Turn on "
            "“Horizon” on the Star Atlas to see them shaded.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        upload_btn = QPushButton("Upload horizon file…")
        upload_btn.setObjectName("AccentButton")
        clear_btn = QPushButton("Clear")
        clear_btn.setToolTip("Delete this Observatory's horizon obstruction table")
        add_point_btn = QPushButton("Add Point")
        add_point_btn.setToolTip("Add a new azimuth/altitude row to edit")
        remove_point_btn = QPushButton("Remove Selected")
        remove_point_btn.setToolTip("Remove the selected row(s)")
        save_points_btn = QPushButton("Save Changes")
        save_points_btn.setObjectName("AccentButton")
        save_points_btn.setToolTip("Save edits made directly in the table")
        buttons.addWidget(upload_btn)
        buttons.addWidget(clear_btn)
        buttons.addWidget(add_point_btn)
        buttons.addWidget(remove_point_btn)
        buttons.addWidget(save_points_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        status = QLabel("")
        status.setObjectName("StatusHint")
        layout.addWidget(status)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Azimuth (°)", "Altitude (°)"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)

        def refresh(points: list) -> None:
            table.setRowCount(len(points))
            for row, (az, alt) in enumerate(points):
                for col, value in enumerate((az, alt)):
                    item = QTableWidgetItem(f"{value:g}")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    table.setItem(row, col, item)
            observatory = self._current_observatory
            if observatory is None:
                status.setText("Create an Observatory first — the horizon belongs to one.")
            elif points:
                status.setText(f"{len(points)} obstruction points for {observatory.name}.")
            else:
                status.setText(f"No horizon obstructions defined for {observatory.name}.")
            has_observatory = observatory is not None
            upload_btn.setEnabled(has_observatory)
            clear_btn.setEnabled(bool(points))
            add_point_btn.setEnabled(has_observatory)
            remove_point_btn.setEnabled(has_observatory and table.rowCount() > 0)
            save_points_btn.setEnabled(has_observatory)

        def store(points: list) -> None:
            try:
                save_horizon_points(self._current_observatory, points)
            except Exception:
                logger.exception("Could not save the horizon obstructions")
                QMessageBox.warning(self._window, "Horizon", "Could not save the horizon — see the log.")
                return
            self._apply_horizon()

        def upload() -> None:
            path, _ = QFileDialog.getOpenFileName(
                self._window, "Upload horizon file", "", "Text files (*.txt *.csv *.hzn *.dat);;All files (*)")
            if not path:
                return
            try:
                with open(path, encoding="utf-8-sig") as f:
                    points = parse_horizon_text(f.read())
            except (OSError, UnicodeDecodeError) as exc:
                logger.exception("Could not read horizon file %s", path)
                QMessageBox.warning(self._window, "Horizon", f"Could not read {path}:\n{exc}")
                return
            except ValueError as exc:
                QMessageBox.warning(self._window, "Horizon", f"{path} is not a valid horizon file.\n\n{exc}")
                return
            store(points)
            self._window.statusBar().showMessage(f"Loaded {len(points)} horizon obstruction points.", 5000)

        def add_point() -> None:
            row = table.rowCount()
            table.setRowCount(row + 1)
            for col in (0, 1):
                item = QTableWidgetItem("0")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, col, item)
            remove_point_btn.setEnabled(True)
            table.editItem(table.item(row, 0))

        def remove_selected() -> None:
            for row in sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True):
                table.removeRow(row)
            remove_point_btn.setEnabled(table.rowCount() > 0)

        def save_edits() -> None:
            points: list[tuple[float, float]] = []
            for row in range(table.rowCount()):
                az_item, alt_item = table.item(row, 0), table.item(row, 1)
                try:
                    az, alt = float(az_item.text() if az_item else ""), float(alt_item.text() if alt_item else "")
                except ValueError:
                    QMessageBox.warning(self._window, "Horizon",
                                         f"Row {row + 1}: azimuth and altitude must both be numbers.")
                    return
                if not (0.0 <= az <= 360.0) or not (0.0 <= alt <= 90.0):
                    QMessageBox.warning(self._window, "Horizon",
                                         f"Row {row + 1}: azimuth must be 0–360° and altitude 0–90° "
                                         f"(got {az:g}, {alt:g}).")
                    return
                points.append((az, alt))
            points.sort(key=lambda p: p[0])
            store(points)
            self._window.statusBar().showMessage(f"Saved {len(points)} horizon obstruction points.", 5000)

        upload_btn.clicked.connect(upload)
        clear_btn.clicked.connect(lambda: store([]))
        add_point_btn.clicked.connect(add_point)
        remove_point_btn.clicked.connect(remove_selected)
        save_points_btn.clicked.connect(save_edits)
        self._horizon_table_refresh = refresh
        refresh([])
        return page

    def _build_planning_settings_page(self: AppWindowState) -> QWidget:
        """Options > Planning: whether slews into the Star Atlas horizon
        obstructions are refused, and bulk-caching every catalog object's
        survey-image thumbnail ahead of time (SKY-080)."""
        from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QVBoxLayout, QWidget
        from galileo.planning.settings import load_planning_settings, save_planning_settings

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Planning settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        settings = load_planning_settings()
        block = QCheckBox("Do not slew where obstructed (see Star Atlas)")
        block.setToolTip("Refuse any slew whose altitude/azimuth is below the horizon obstructions "
                         "defined under Options > Star Atlas.")
        block.setChecked(settings["block_obstructed_slews"])
        layout.addWidget(block)

        hint = QLabel(f"A refused slew reports “{_OBSTRUCTED_MESSAGE}”, whether it was asked for from "
                      "the Mount page, the Star Atlas, a sequence or plate solving. Needs a horizon "
                      "uploaded under Options > Star Atlas.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        def changed(checked: bool) -> None:
            settings["block_obstructed_slews"] = checked
            save_planning_settings(settings)
            self._apply_horizon()

        block.toggled.connect(changed)

        cache_heading = QLabel("Sky-survey thumbnails")
        cache_heading.setObjectName("PageSubtitle")
        layout.addWidget(cache_heading)

        cache_btn = QPushButton("Cache All Catalog Thumbnails…")
        cache_btn.setToolTip(
            "Pre-fetches every catalog object's survey-image thumbnail (SKY-080), so a later Planning "
            "> Targets search shows its result-tile images immediately instead of fetching them then."
        )
        layout.addWidget(cache_btn)

        cache_hint = QLabel(
            "Fetches a thumbnail for every object in the offline catalog not already cached — tens of "
            "thousands of objects, one network request each, so this can take hours. Already-cached "
            "objects (from an earlier run, or from having shown up in a search) are skipped instantly, "
            "so it's safe to cancel and resume later, or run again after the catalog updates."
        )
        cache_hint.setObjectName("StatusHint")
        cache_hint.setWordWrap(True)
        layout.addWidget(cache_hint)
        layout.addStretch(1)

        cache_btn.clicked.connect(lambda: self._cache_all_catalog_thumbnails(page))
        return page

    def _cache_all_catalog_thumbnails(self: AppWindowState, parent: QWidget) -> None:
        """Options > Planning's "Cache All Catalog Thumbnails…" button
        (SKY-080): confirms the scale of the operation (this is a real,
        potentially hours-long bulk network fetch, not a quick local task),
        then runs `_ThumbnailCacheThread` behind a cancellable progress
        dialog — the same worker-thread/`QProgressDialog` pattern
        `galileo.ui.library.download_dialog`'s telescope download already
        uses, not a new one."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox, QProgressDialog

        try:
            from galileo.planning.sky_atlas import SkyAtlas
            total = len(SkyAtlas()._catalog)
        except Exception:
            logger.exception("Could not load the catalog to size the thumbnail-caching confirmation")
            total = 0

        confirmed = QMessageBox.question(
            parent, "Cache All Catalog Thumbnails",
            f"This fetches a survey-image thumbnail for every object in the catalog not already "
            f"cached ({total:,} objects total) — one network request each, so it can take hours. "
            f"You can cancel at any time; progress made so far stays cached. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return

        progress_dialog = QProgressDialog("Starting…", "Cancel", 0, max(total, 1), parent)
        progress_dialog.setWindowTitle("Caching Thumbnails")
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setValue(0)
        progress_dialog.show()

        worker = _ThumbnailCacheThread(parent)
        self._thumbnail_cache_worker = worker  # keep a live reference so it isn't GC'd mid-run

        def on_progress(done: int, of_total: int) -> None:
            progress_dialog.setMaximum(max(of_total, 1))
            progress_dialog.setValue(done)
            progress_dialog.setLabelText(f"Caching thumbnails: {done:,} / {of_total:,}")

        def on_finished(cached: int, failed: int) -> None:
            progress_dialog.close()
            self._window.statusBar().showMessage(
                f"Thumbnail caching complete: {cached:,} cached/already-cached, {failed:,} failed.", 8000)
            self._thumbnail_cache_worker = None

        def on_failed(message: str) -> None:
            progress_dialog.close()
            QMessageBox.critical(parent, "Thumbnail Caching Failed", message)
            self._thumbnail_cache_worker = None

        worker.progress.connect(on_progress, Qt.ConnectionType.QueuedConnection)
        worker.finished_ok.connect(on_finished, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(on_failed, Qt.ConnectionType.QueuedConnection)
        progress_dialog.canceled.connect(worker.stop)
        worker.start()

    def _build_imaging_settings_page(self: AppWindowState) -> QWidget:
        """Options > Imaging: the FITS sample format (BITPIX) saved frames are written in (IMG-170)
        and how much neighbouring mosaic panes overlap (FRAME-040)."""
        from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel, QVBoxLayout, QWidget
        from galileo.imaging_settings import MOSAIC_OVERLAP_RANGE, load_imaging_settings, save_imaging_settings
        from galileo.metadata import BITPIX_AUTO, BITPIX_CHOICES

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Imaging settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        form = _new_form_layout()
        form.setSpacing(8)
        layout.addLayout(form)

        # Label -> stored value. "Auto" writes unsigned 16-bit where the data fits and 32-bit
        # float otherwise — the pre-existing, still the default, behaviour.
        labels = {
            BITPIX_AUTO: "Auto (recommended)",
            8: "8 (unsigned integer)",
            16: "16 (unsigned integer)",
            32: "32 (signed integer)",
            -32: "-32 (floating point)",
        }
        bitpix_combo = QComboBox()
        for value in BITPIX_CHOICES:
            bitpix_combo.addItem(labels[value], value)
        bitpix_combo.setToolTip(
            "The pixel format frames are saved in — Save Frame, Auto-Save to Library and Save Stack "
            "on the Imaging tab (IMG-170). Auto picks the smallest of these that fits each frame "
            "without losing data. A fixed value writes every frame in that one format instead, for "
            "downstream tools that expect one consistent format; values outside its range are clipped "
            "and a float is rounded to the nearest integer. Every value here is one other astronomy "
            "software actually reads — Galileo never writes a 64-bit FITS, which ASTAP and Tenmon "
            "both refuse as an unsupported sample format."
        )
        settings = load_imaging_settings()
        idx = bitpix_combo.findData(settings["bitpix"])
        bitpix_combo.setCurrentIndex(max(idx, 0))
        form.addRow("Desired BITPIX", bitpix_combo)

        overlap_spin = QDoubleSpinBox()
        overlap_spin.setRange(*MOSAIC_OVERLAP_RANGE)
        overlap_spin.setDecimals(1)
        overlap_spin.setSuffix(" %")
        overlap_spin.setValue(settings["mosaic_overlap_pct"])
        overlap_spin.setToolTip(
            "How much neighbouring panes of a mosaic overlap, as a percentage of a pane (FRAME-040). "
            "Used by the Framing Assistant opened from the Imaging tab and from a Session's Image block."
        )
        form.addRow("Mosaic pane overlap", overlap_spin)

        hint = QLabel(
            "Applies to frames the Imaging tab saves. Frames captured for plate solving always use "
            "whichever of these formats best fits, regardless of this setting, since that is about "
            "what the solver can read rather than a preference."
        )
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        def changed(index: int) -> None:
            settings["bitpix"] = bitpix_combo.itemData(index)
            save_imaging_settings(settings)
            # Take effect on every Pier's already-built ImagingService, not only on
            # the next launch — this is a single app-wide setting, not per-Pier.
            for service in getattr(self, "_imaging_services", {}).values():
                service.bitpix = settings["bitpix"]

        def overlap_changed(value: float) -> None:
            from galileo.planning.framing import MosaicSettings
            settings["mosaic_overlap_pct"] = value
            MosaicSettings.instance().set_pane_overlap_pct(value)   # remembers it too

        bitpix_combo.currentIndexChanged.connect(changed)
        overlap_spin.valueChanged.connect(overlap_changed)
        return page

    def _build_focus_settings_page(self: AppWindowState) -> QWidget:
        """Options > Focus: the current Pier's saved autofocus defaults
        (step size, points, exposure, backlash — FOC-070), which seed the
        Focus screen's own controls. Scoped per Pier, like the Equipment
        pages' saved device configuration."""
        from PySide6.QtWidgets import (
            QDoubleSpinBox, QFormLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
        )
        from galileo.autofocus import AutofocusParams
        from galileo.observatory import get_autofocus_params, save_autofocus_params

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Focus settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        status = QLabel("")
        status.setObjectName("StatusHint")
        layout.addWidget(status)

        form = QFormLayout()
        form.setSpacing(8)
        layout.addLayout(form)

        step_spin = QSpinBox()
        step_spin.setRange(1, 100000)
        step_spin.setSuffix(" steps")
        step_spin.setToolTip("Focuser steps between successive exposures during a sweep.")
        form.addRow("Step size", step_spin)

        points_spin = QSpinBox()
        points_spin.setRange(3, 41)
        points_spin.setToolTip("Number of exposures across the sweep, centred on the current position.")
        form.addRow("Number of points", points_spin)

        exposure_spin = QDoubleSpinBox()
        exposure_spin.setRange(0.01, 600.0)
        exposure_spin.setDecimals(2)
        exposure_spin.setSuffix(" s")
        exposure_spin.setToolTip("Exposure time of each frame measured during a sweep.")
        form.addRow("Exposure time", exposure_spin)

        backlash_spin = QSpinBox()
        backlash_spin.setRange(0, 100000)
        backlash_spin.setSuffix(" steps")
        backlash_spin.setToolTip(
            "Overshoot then return by this many steps before every focuser move during a run "
            "(0 disables compensation).")
        form.addRow("Backlash compensation", backlash_spin)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        layout.addWidget(save_btn)

        hint = QLabel("Applies to the next autofocus run started from the Focus screen, whether "
                      "started there or by a session trigger. Saved per Pier.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        def refresh() -> None:
            pier = self._current_pier
            params = get_autofocus_params(pier)
            step_spin.setValue(params.step_size)
            points_spin.setValue(params.num_points)
            exposure_spin.setValue(params.exposure_s)
            backlash_spin.setValue(params.backlash_compensation)
            status.setText(f"Editing defaults for Pier {pier.name!r}." if pier is not None
                           else "Select a Pier first — these settings are saved per Pier.")
            save_btn.setEnabled(pier is not None)
            for widget in (step_spin, points_spin, exposure_spin, backlash_spin):
                widget.setEnabled(pier is not None)

        def save() -> None:
            if self._current_pier is None:
                return
            params = AutofocusParams(
                step_size=step_spin.value(), num_points=points_spin.value(),
                exposure_s=exposure_spin.value(), backlash_compensation=backlash_spin.value(),
            )
            save_autofocus_params(self._current_pier, params)
            focus_state = self._device_pages.get("focus")
            if focus_state is not None:
                focus_state["reload"]()
            self._window.statusBar().showMessage(f"Saved Focus settings for Pier {self._current_pier.name!r}.", 4000)

        save_btn.clicked.connect(save)
        self._focus_settings_refresh = refresh
        refresh()
        return page

    def _build_solve_settings_page(self: AppWindowState) -> QWidget:
        """Options > Solve: the current Pier's saved solver defaults —
        an ASTAP executable-path override, field-of-view hint, search radius
        and downsample factor (PLT-060), plus the solver backend (ASTAP, local astrometry.net or
        nova.astrometry.net). Scoped per Pier, like Options > Focus."""
        from PySide6.QtWidgets import (
            QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
            QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget,
        )
        from PySide6.QtCore import QTimer
        from galileo.observatory import (
            get_solver_backend,
            get_solver_settings,
            get_tetra3_database,
            save_solver_backend,
            save_solver_settings,
            save_tetra3_database,
        )
        from galileo.platesolve import BACKENDS, SolverParams

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Solve settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        status = QLabel("")
        status.setObjectName("StatusHint")
        layout.addWidget(status)

        form = QFormLayout()
        form.setSpacing(8)
        layout.addLayout(form)

        backend_combo = QComboBox()
        for key, label in BACKENDS.items():
            backend_combo.addItem(label, key)
        backend_combo.setToolTip("Which solver the application uses by default: ASTAP, a local astrometry.net "
                                 "installation, the nova.astrometry.net web service, or ESA's tetra3.")
        form.addRow("Solver", backend_combo)

        exe_row = QHBoxLayout()
        exe_edit = QLineEdit()
        exe_edit.setPlaceholderText("Auto-detected if left blank")
        exe_edit.setToolTip("Path to the ASTAP executable. Leave blank to auto-detect it on PATH "
                            "or in its usual install location.")
        browse_btn = QPushButton("Browse…")
        exe_row.addWidget(exe_edit, 1)
        exe_row.addWidget(browse_btn)
        form.addRow("ASTAP executable", exe_row)

        astrometry_row = QHBoxLayout()
        astrometry_edit = QLineEdit()
        astrometry_edit.setPlaceholderText("Auto-detected if left blank")
        astrometry_edit.setToolTip("Path to astrometry.net's solve-field program. Leave blank to auto-detect it on PATH.")
        astrometry_browse_btn = QPushButton("Browse…")
        astrometry_row.addWidget(astrometry_edit, 1)
        astrometry_row.addWidget(astrometry_browse_btn)
        form.addRow("solve-field executable", astrometry_row)

        tetra3_row = QHBoxLayout()
        tetra3_edit = QLineEdit()
        tetra3_edit.setPlaceholderText("tetra3's own database if left blank")
        tetra3_edit.setToolTip("Path to a tetra3 star-pattern database (.npz) built for your field of view. "
                               "Leave blank to use the database that comes with tetra3.")
        tetra3_browse_btn = QPushButton("Browse…")
        tetra3_row.addWidget(tetra3_edit, 1)
        tetra3_row.addWidget(tetra3_browse_btn)
        form.addRow("tetra3 database", tetra3_row)

        api_key_edit = QLineEdit()
        api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_edit.setToolTip("Your nova.astrometry.net API key (from your profile on nova.astrometry.net).")
        form.addRow("nova.astrometry.net API key", api_key_edit)

        fov_spin = QDoubleSpinBox()
        fov_spin.setRange(0.0, 60.0)
        fov_spin.setDecimals(2)
        fov_spin.setSuffix(" °")
        fov_spin.setSpecialValueText("Auto (from optical train)")
        fov_spin.setToolTip("Field-of-view hint given to the solver. 0 derives it from the active "
                            "optical train's focal length and pixel size instead of a fixed value.")
        form.addRow("Field-of-view hint", fov_spin)

        radius_spin = QDoubleSpinBox()
        radius_spin.setRange(0.5, 180.0)
        radius_spin.setDecimals(1)
        radius_spin.setSuffix(" °")
        radius_spin.setToolTip("The solver searches only within this radius of the hinted position.")
        form.addRow("Search radius", radius_spin)

        downsample_spin = QSpinBox()
        downsample_spin.setRange(0, 8)
        downsample_spin.setSpecialValueText("Off")
        downsample_spin.setToolTip("Downsample the frame by this factor before solving, for a faster "
                                   "but less precise solve (0 solves at full resolution).")
        form.addRow("Downsample", downsample_spin)

        scope_combo = QComboBox()
        scope_combo.addItem("Current Pier", "current")
        scope_combo.addItem("All Piers in all Observatories", "all")
        scope_combo.setToolTip("Which Piers to build tetra3 star databases for: the current Pier, or every Pier of "
                               "every Observatory. Each Pier's database is sized to the field of view its optical "
                               "tubes and cameras give.")
        form.addRow("Generate for", scope_combo)

        build_row = QHBoxLayout()
        generate_btn = QPushButton("Generate tetra3 databases")
        generate_btn.setToolTip("Build tetra3 star databases matched to the chosen Piers' fields of view, and "
                                "select each for its Pier. Downloads a star catalogue the first time; a narrow "
                                "field can take hours.")
        cancel_build_btn = QPushButton("Cancel build")
        cancel_build_btn.setEnabled(False)
        cancel_build_btn.setToolTip("Stop building databases. Ones already finished are kept.")
        build_row.addWidget(generate_btn)
        build_row.addWidget(cancel_build_btn)
        build_row.addStretch(1)
        build_busy = QProgressBar()
        build_busy.setRange(0, 0)
        build_busy.setTextVisible(False)
        build_busy.setMaximumHeight(8)
        build_busy.setVisible(False)
        build_status = QLabel("")
        build_status.setObjectName("StatusHint")
        build_status.setWordWrap(True)

        def browse() -> None:
            path, _ = QFileDialog.getOpenFileName(self._window, "ASTAP executable")
            if path:
                exe_edit.setText(path)

        browse_btn.clicked.connect(browse)

        def browse_astrometry() -> None:
            path, _ = QFileDialog.getOpenFileName(self._window, "solve-field executable")
            if path:
                astrometry_edit.setText(path)

        astrometry_browse_btn.clicked.connect(browse_astrometry)

        def browse_tetra3() -> None:
            path, _ = QFileDialog.getOpenFileName(self._window, "tetra3 database", "", "tetra3 database (*.npz)")
            if path:
                tetra3_edit.setText(path)

        tetra3_browse_btn.clicked.connect(browse_tetra3)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        layout.addWidget(save_btn)

        hint = QLabel("Applies to solves started from the Solve screen. Saved per Pier.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addSpacing(12)
        layout.addLayout(build_row)
        layout.addWidget(build_busy)
        layout.addWidget(build_status)
        layout.addStretch(1)

        build = {"builder": None, "built": 0, "failures": []}
        poll_timer = QTimer(page)
        poll_timer.setInterval(500)

        def finish_build() -> None:
            poll_timer.stop()
            build["builder"] = None
            generate_btn.setEnabled(True)
            cancel_build_btn.setEnabled(False)
            build_busy.setVisible(False)
            failures = build["failures"]
            summary = f"Built {build['built']} database(s) and selected them for their Piers." if build["built"] else "No database was built."
            build_status.setText(summary + ("\n" + "\n".join(failures) if failures else ""))
            refresh()

        def poll_build() -> None:
            from galileo.library.models.observatory import PierRecord
            builder = build["builder"]
            if builder is None:
                return
            for message in builder.poll():
                kind = message[0]
                if kind == "log":
                    build_status.setText(message[1])
                elif kind == "built":
                    plan = builder.plans[message[1]]
                    for pier_id in plan.pier_ids:
                        save_tetra3_database(PierRecord.get_by_id(pier_id), message[2])
                    build["built"] += len(plan.pier_ids)
                elif kind == "failed":
                    label = builder.plans[message[1]].fov_text + " database" if message[1] >= 0 else "Build"
                    build["failures"].append(f"{label}: {message[2]}")
                elif kind == "finished":
                    finish_build()
                    return

        poll_timer.timeout.connect(poll_build)

        def generate() -> None:
            from galileo.tetra3_db import DatabaseBuilder, all_piers, download_size_mb, plan_databases
            piers = all_piers() if scope_combo.currentData() == "all" else [self._current_pier]
            plans, skipped = plan_databases([p for p in piers if p is not None])
            skipped_text = ("\n\nSkipped:\n" + "\n".join(skipped)) if skipped else ""
            if not plans:
                QMessageBox.information(self._window, "tetra3 databases",
                                        "Nothing to build." + (skipped_text or " Select a Pier first."))
                return
            lines = "\n".join(f"• {plan.fov_text} field from {plan.catalog} for {', '.join(plan.pier_labels)}"
                              for plan in plans)
            download_mb = download_size_mb(plans)
            answer = QMessageBox.question(
                self._window, "Generate tetra3 databases",
                f"Build {len(plans)} database(s):\n{lines}{skipped_text}\n\n"
                + (f"This downloads about {download_mb} MB of star catalogue. " if download_mb else "")
                + "A narrow field can take hours to build; you can keep using Galileo meanwhile, or cancel.\n\nContinue?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            builder = DatabaseBuilder(plans)
            build.update(builder=builder, built=0, failures=[])
            generate_btn.setEnabled(False)
            cancel_build_btn.setEnabled(True)
            build_busy.setVisible(True)
            build_status.setText("Starting…")
            builder.start()
            poll_timer.start()

        def cancel_build() -> None:
            if build["builder"] is not None:
                build["builder"].cancel()
                build_status.setText("Cancelling…")

        generate_btn.clicked.connect(generate)
        cancel_build_btn.clicked.connect(cancel_build)

        def refresh() -> None:
            pier = self._current_pier
            executable, params = get_solver_settings(pier)
            exe_edit.setText(executable)
            fov_spin.setValue(params.fov_hint_deg)
            radius_spin.setValue(params.search_radius_deg)
            downsample_spin.setValue(params.downsample)
            backend, astrometry_exe, api_key = get_solver_backend(pier)
            backend_combo.setCurrentIndex(max(backend_combo.findData(backend), 0))
            astrometry_edit.setText(astrometry_exe)
            api_key_edit.setText(api_key)
            tetra3_edit.setText(get_tetra3_database(pier))
            status.setText(f"Editing defaults for Pier {pier.name!r}." if pier is not None
                           else "Select a Pier first — these settings are saved per Pier.")
            save_btn.setEnabled(pier is not None)
            for widget in (backend_combo, exe_edit, browse_btn, astrometry_edit, astrometry_browse_btn,
                           tetra3_edit, tetra3_browse_btn, api_key_edit, fov_spin, radius_spin, downsample_spin):
                widget.setEnabled(pier is not None)

        def save() -> None:
            if self._current_pier is None:
                return
            params = SolverParams(
                fov_hint_deg=fov_spin.value(), search_radius_deg=radius_spin.value(),
                downsample=downsample_spin.value(),
            )
            save_solver_settings(self._current_pier, exe_edit.text().strip(), params)
            save_solver_backend(self._current_pier, backend_combo.currentData(),
                                astrometry_edit.text().strip(), api_key_edit.text().strip())
            save_tetra3_database(self._current_pier, tetra3_edit.text().strip())
            solve_page = self._device_pages.get("solve")
            if solve_page is not None:
                solve_page["reload"]()
            self._window.statusBar().showMessage(f"Saved Solve settings for Pier {self._current_pier.name!r}.", 4000)

        save_btn.clicked.connect(save)
        self._solve_settings_refresh = refresh
        refresh()
        return page
