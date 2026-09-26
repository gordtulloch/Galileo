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

        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_finished)
        worker.failed.connect(on_failed)
        progress_dialog.canceled.connect(worker.stop)
        worker.start()

    def _build_imaging_settings_page(self: AppWindowState) -> QWidget:
        """Options > Imaging: the FITS sample format (BITPIX) saved frames are written in (IMG-170)."""
        from PySide6.QtWidgets import QComboBox, QLabel, QVBoxLayout, QWidget
        from galileo.imaging_settings import load_imaging_settings, save_imaging_settings
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
            # Take effect on the page already built, not only on the next launch.
            service = getattr(self, "_imaging_service", None)
            if service is not None:
                service.bitpix = settings["bitpix"]

        bitpix_combo.currentIndexChanged.connect(changed)
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
                      "started there or by a sequencer trigger. Saved per Pier.")
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
        and downsample factor (PLT-060). Scoped per Pier, like Options > Focus."""
        from PySide6.QtWidgets import (
            QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
            QPushButton, QSpinBox, QVBoxLayout, QWidget,
        )
        from galileo.observatory import get_solver_settings, save_solver_settings
        from galileo.platesolve import SolverParams

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

        exe_row = QHBoxLayout()
        exe_edit = QLineEdit()
        exe_edit.setPlaceholderText("Auto-detected if left blank")
        exe_edit.setToolTip("Path to the ASTAP executable. Leave blank to auto-detect it on PATH "
                            "or in its usual install location.")
        browse_btn = QPushButton("Browse…")
        exe_row.addWidget(exe_edit, 1)
        exe_row.addWidget(browse_btn)
        form.addRow("ASTAP executable", exe_row)

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

        def browse() -> None:
            path, _ = QFileDialog.getOpenFileName(self._window, "ASTAP executable")
            if path:
                exe_edit.setText(path)

        browse_btn.clicked.connect(browse)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        layout.addWidget(save_btn)

        hint = QLabel("Applies to solves started from the Solve screen. Saved per Pier.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        def refresh() -> None:
            pier = self._current_pier
            executable, params = get_solver_settings(pier)
            exe_edit.setText(executable)
            fov_spin.setValue(params.fov_hint_deg)
            radius_spin.setValue(params.search_radius_deg)
            downsample_spin.setValue(params.downsample)
            status.setText(f"Editing defaults for Pier {pier.name!r}." if pier is not None
                           else "Select a Pier first — these settings are saved per Pier.")
            save_btn.setEnabled(pier is not None)
            for widget in (exe_edit, browse_btn, fov_spin, radius_spin, downsample_spin):
                widget.setEnabled(pier is not None)

        def save() -> None:
            if self._current_pier is None:
                return
            params = SolverParams(
                fov_hint_deg=fov_spin.value(), search_radius_deg=radius_spin.value(),
                downsample=downsample_spin.value(),
            )
            save_solver_settings(self._current_pier, exe_edit.text().strip(), params)
            self._window.statusBar().showMessage(f"Saved Solve settings for Pier {self._current_pier.name!r}.", 4000)

        save_btn.clicked.connect(save)
        self._solve_settings_refresh = refresh
        refresh()
        return page
