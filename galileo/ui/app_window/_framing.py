# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Framing Assistant dialog (IMG-180, FRAME-070), opened from the Imaging page."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _new_form_layout
from ._threads import _DetermineRotationThread
from ._widgets import _FramingCanvas

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowFramingMixin:
    def _imaging_optical_profile(self: AppWindowState) -> dict:
        """Profile-shaped dict for ``FramingAssistant.from_profile()`` (FRAME-010,
        FRAME-030), built from the Imaging tab's own active optical train, camera,
        and rotator configuration — falls back to reference defaults wherever a
        piece of it isn't configured yet."""
        tube = self.active_optical_tube()
        pier = self._current_pier
        camera_cfg = rotator_cfg = None
        if pier is not None:
            from galileo.observatory import get_device_config
            try:
                camera_cfg = get_device_config(pier, "camera", slot=self._active_camera_slot)
            except Exception:
                logger.exception("Could not load the camera's configuration for Framing")
            try:
                rotator_cfg = get_device_config(pier, "rotator")
            except Exception:
                logger.exception("Could not load the rotator's configuration for Framing")
        camera = {}
        if camera_cfg is not None:
            camera = {key: value for key, value in {
                "sensor_width_px": camera_cfg.sensor_width_px,
                "sensor_height_px": camera_cfg.sensor_height_px,
                "pixel_size_um": camera_cfg.pixel_size_um,
            }.items() if value is not None}
        return {
            "piers": [{
                "optical_trains": [{
                    "focal_length_mm": getattr(tube, "focal_length_mm", None) or 1000,
                    "camera": camera,
                    "rotator": {"configured": True} if rotator_cfg is not None else {},
                }]
            }]
        }

    def _framing_dialog_initial_target(self: AppWindowState) -> tuple[str, float, float] | None:
        """The Imaging tab's current object (IMG-140), if any — used to pre-fill the
        Framing Assistant dialog's Name/RA/Dec fields, so a target already picked
        on the Star Atlas doesn't need retyping into Framing's own fields too."""
        current = self.current_object()
        if current is None:
            return None
        return current.name, current.ra_deg, current.dec_deg

    def _open_framing_dialog(self: AppWindowState, service) -> None:
        """Open the Framing Assistant against the Imaging tab's own optical train
        (IMG-180's Framing… control): compute the FOV, or define and run a mosaic
        grid directly from this tab (traces to FRAME-090). Shows the survey image
        for the target with the FOV/mosaic rectangle overlaid (FRAME-020/FRAME-040),
        redrawn immediately as rotation or the mosaic grid is adjusted.

        Rotation (FRAME-030) is always editable, regardless of whether a rotator
        is connected: with one connected, accepting the dialog moves it to the
        requested angle; with none connected, the requested tilt can't be achieved
        by the camera directly, so it's instead covered by an auto-sized mosaic of
        (un-rotated) panels — an explicit mosaic grid the user set themselves takes
        priority over that fallback.

        The rotation field is pre-filled, where already known, from the connected
        rotator's live position or from the Imaging tab's last plate solve
        (FRAME-100) — Determine Rotation only needs a click when neither applies:
        it plate-solves the Imaging tab's current frame and reads the position
        angle back out of the solution.

        A "Show mosaic overlay" checkbox controls only what the canvas *draws* —
        the mosaic panel grid, or a single (possibly tilted) frame rectangle when
        unchecked — never what's actually captured on accept: an explicit or
        rotation-fallback mosaic is still used whenever one is needed, whether or
        not its panels are shown here."""
        import asyncio
        from PySide6.QtWidgets import (
            QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QHBoxLayout, QLabel,
            QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
        )
        from galileo.planning.framing import MosaicSettings

        assistant = service.open_framing_assistant(profile=self._imaging_optical_profile())
        rotator_state = self._device_pages.get("rotator") or {}
        rotator_adapter = rotator_state.get("adapter")
        rotator_connected = rotator_adapter is not None

        dialog = QDialog(self._window)
        dialog.setWindowTitle("Framing Assistant")
        outer = QHBoxLayout(dialog)

        left = QVBoxLayout()
        outer.addLayout(left)
        form = _new_form_layout()
        left.addLayout(form)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Target name")
        form.addRow("Name", name_edit)

        ra_spin = QDoubleSpinBox()
        ra_spin.setRange(0.0, 360.0)
        ra_spin.setDecimals(4)
        ra_spin.setSuffix(" °")
        form.addRow("RA", ra_spin)

        dec_spin = QDoubleSpinBox()
        dec_spin.setRange(-90.0, 90.0)
        dec_spin.setDecimals(4)
        dec_spin.setSuffix(" °")
        form.addRow("Dec", dec_spin)

        initial_target = self._framing_dialog_initial_target()
        if initial_target is not None:
            name_edit.setText(initial_target[0])
            ra_spin.setValue(initial_target[1])
            dec_spin.setValue(initial_target[2])

        rotation_spin = QDoubleSpinBox()
        rotation_spin.setRange(0.0, 359.9)
        rotation_spin.setSuffix(" °")
        form.addRow("Rotation", rotation_spin)

        # Rotation (FRAME-100) is pre-filled wherever it's already known — the connected
        # rotator's live position takes priority (it's the current physical truth), falling
        # back to the Imaging tab's last plate solve — so Determine Rotation is only ever
        # needed when neither is available.
        known_rotation: float | None = None
        known_rotation_source = ""
        if rotator_connected:
            try:
                status = asyncio.run(rotator_adapter.get_status())
                position = status.get("position")
            except Exception:
                logger.exception("Could not read the rotator's current position for Framing")
                position = None
            if position is not None:
                known_rotation, known_rotation_source = float(position) % 360.0, "the rotator"
        if known_rotation is None:
            last_solve = getattr(service, "last_solve", None)
            if last_solve is not None and getattr(last_solve, "success", False) and last_solve.rotation_deg is not None:
                known_rotation = float(last_solve.rotation_deg) % 360.0
                known_rotation_source = "the last plate solve"
        if known_rotation is not None:
            rotation_spin.setValue(known_rotation)

        def _rotator_status_text() -> str:
            if known_rotation is not None:
                suffix = " — OK will move it to this angle." if rotator_connected else ""
                return f"Rotation known from {known_rotation_source}: {known_rotation:.1f}°.{suffix}"
            if rotator_connected:
                return "Rotator detected — OK will move it to this angle."
            return ("Rotation unknown — click Determine Rotation to plate-solve the current frame, "
                    "or set it manually. No rotator detected, so a nonzero rotation is captured as "
                    "a mosaic covering the tilted field.")

        rotator_status = QLabel(_rotator_status_text())
        rotator_status.setObjectName("StatusHint")
        rotator_status.setWordWrap(True)
        form.addRow(rotator_status)

        cols_spin = QSpinBox()
        cols_spin.setRange(1, 20)
        cols_spin.setValue(1)
        form.addRow("Mosaic cols", cols_spin)

        rows_spin = QSpinBox()
        rows_spin.setRange(1, 20)
        rows_spin.setValue(1)
        form.addRow("Mosaic rows", rows_spin)

        overlap_spin = QDoubleSpinBox()
        overlap_spin.setRange(0.0, 90.0)
        overlap_spin.setValue(MosaicSettings.instance().pane_overlap_pct)
        overlap_spin.setSuffix(" %")
        overlap_spin.setToolTip("Shared with the Session Image block's own Framing… control (FRAME-040).")
        form.addRow("Overlap", overlap_spin)

        show_mosaic_check = QCheckBox("Show mosaic overlay")
        show_mosaic_check.setChecked(True)
        show_mosaic_check.setToolTip(
            "Preview only — hides the mosaic panel grid on the image below, showing just a single "
            "(possibly tilted) frame rectangle instead. Doesn't change what's actually captured: a "
            "covering mosaic is still used whenever one is needed (an explicit grid, or rotating with "
            "no rotator connected) whether or not it's drawn here."
        )
        form.addRow(show_mosaic_check)

        determine_rotation_btn = QPushButton("Determine Rotation")
        determine_rotation_btn.setToolTip(
            "Plate-solve the Imaging tab's current frame to read back the sensor's actual rotation "
            "(FRAME-100) — only needed when it isn't already known from a connected rotator or an "
            "earlier plate solve."
        )
        form.addRow(determine_rotation_btn)

        fov_label = QLabel("")
        fov_label.setObjectName("StatusHint")
        fov_label.setWordWrap(True)
        left.addWidget(fov_label)

        canvas = _FramingCanvas()
        outer.addWidget(canvas, 1)

        def mosaic_grid() -> tuple | None:
            """The grid the user explicitly set, if any."""
            return ((cols_spin.value(), rows_spin.value(), overlap_spin.value())
                    if cols_spin.value() > 1 or rows_spin.value() > 1 else None)

        def effective_grid() -> tuple | None:
            """The grid actually in effect: the user's own explicit choice, else —
            with no rotator connected and a nonzero rotation — one auto-sized to
            cover the tilted frame's bounding box (FRAME-030's fallback), else
            ``None`` for a plain single frame."""
            explicit = mosaic_grid()
            if explicit is not None:
                return explicit
            if not rotator_connected and rotation_spin.value() != 0:
                bbox = assistant.rotated_frame_bounding_box_deg(rotation_spin.value())
                cols, rows = assistant.mosaic_grid_to_cover_deg(*bbox, overlap_spin.value())
                return cols, rows, overlap_spin.value()
            return None

        def refresh_overlay() -> None:
            fov = assistant.compute_fov()
            grid = effective_grid()
            auto_mosaic = grid is not None and mosaic_grid() is None
            if grid is not None:
                footprint = assistant.mosaic_footprint_deg(*grid)
                if auto_mosaic:
                    extra = (f"  —  no rotator: {grid[0]}×{grid[1]} mosaic covering the "
                             f"{rotation_spin.value():.0f}° tilted field")
                else:
                    extra = f"  —  mosaic footprint {footprint[0]:.3f}° × {footprint[1]:.3f}° ({grid[0]}×{grid[1]})"
                    if rotation_spin.value() != 0:
                        extra += "  (rotation ignored while a mosaic grid is set)"
            else:
                footprint = (fov.width_deg, fov.height_deg)
                extra = ""
            show_mosaic = show_mosaic_check.isChecked()
            if grid is not None and not show_mosaic:
                extra += "  (mosaic preview hidden — still captured)"
            display_grid = grid if show_mosaic else None
            pane_rotation = 0.0 if display_grid is not None else rotation_spin.value()
            reference_rotation = rotation_spin.value() if (auto_mosaic and show_mosaic) else None
            suffix = f" at rotation {rotation_spin.value():.1f}°" if pane_rotation or reference_rotation else ""
            fov_label.setText(f"Field of view: {fov.width_deg:.3f}° × {fov.height_deg:.3f}°{suffix}{extra}")
            canvas.set_overlay(fov.width_deg, fov.height_deg, pane_rotation, display_grid,
                               footprint_deg=footprint, reference_rotation_deg=reference_rotation)

        def load_sky_image() -> None:
            grid = effective_grid()
            footprint = assistant.mosaic_footprint_deg(*grid) if grid is not None else None
            extent = assistant.survey_cutout_extent_deg(*footprint) if footprint else assistant.survey_cutout_extent_deg()
            width_deg, height_deg = footprint or (None, None)
            try:
                data = assistant.fetch_survey_image_sync(ra_spin.value(), dec_spin.value(), width_deg, height_deg)
            except Exception:
                logger.exception("Framing Assistant survey-image fetch failed")
                data = b""
            canvas.set_image(data, extent)

        # Keeps the running Determine Rotation thread alive for the dialog's lifetime (a local
        # PySide6 QThread can otherwise be garbage-collected mid-run once nothing else references
        # it) — mirrors the Imaging page's own annotate_threads set (_imaging_page.py).
        rotation_threads: set = set()

        def determine_rotation() -> None:
            if service.current_frame is None:
                rotator_status.setText("Determine Rotation needs a captured frame on the Imaging tab first.")
                return
            from galileo.observatory import get_solver_settings
            from galileo.platesolve import PlateSolver
            executable, params = get_solver_settings(self._current_pier)
            solver = PlateSolver(backend="astap", executable=executable, params=params)
            determine_rotation_btn.setEnabled(False)
            rotator_status.setText("Solving the current frame for its rotation…")

            def _succeeded() -> None:
                determine_rotation_btn.setEnabled(True)
                result = service.last_solve
                rotation_spin.setValue(result.rotation_deg % 360.0)
                rotator_status.setText(f"Rotation determined by plate solve: {result.rotation_deg:.1f}°.")
                refresh_overlay()

            def _failed(reason: str) -> None:
                determine_rotation_btn.setEnabled(True)
                rotator_status.setText(f"Could not determine rotation: {reason}")

            thread = _DetermineRotationThread(service, solver, dialog)
            thread.finished_ok.connect(_succeeded)
            thread.failed.connect(_failed)
            thread.finished.connect(lambda: rotation_threads.discard(thread))
            thread.finished.connect(thread.deleteLater)
            rotation_threads.add(thread)
            thread.start()

        rotation_spin.valueChanged.connect(lambda _: refresh_overlay())
        cols_spin.valueChanged.connect(lambda _: refresh_overlay())
        rows_spin.valueChanged.connect(lambda _: refresh_overlay())
        overlap_spin.valueChanged.connect(lambda _: refresh_overlay())
        show_mosaic_check.toggled.connect(lambda _: refresh_overlay())
        # Not refetched on every RA/Dec keystroke (FRAME-020) — only once editing settles
        # (editingFinished), to avoid a network call per digit typed.
        ra_spin.editingFinished.connect(load_sky_image)
        dec_spin.editingFinished.connect(load_sky_image)
        determine_rotation_btn.clicked.connect(determine_rotation)
        refresh_overlay()
        if initial_target is not None:
            load_sky_image()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        left.addWidget(buttons)

        # Opens at double its natural (layout-driven) size — the form-plus-canvas sizeHint is
        # comfortable for the form alone but leaves the survey image cramped; doubling both
        # dimensions keeps the canvas's own aspect-ratio-preserving paint (_FramingCanvas) from
        # starting out squeezed into a sliver.
        natural_size = dialog.sizeHint()
        dialog.resize(natural_size.width() * 2, natural_size.height() * 2)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            assistant.close()
            return

        MosaicSettings.instance().set_pane_overlap_pct(overlap_spin.value())
        assistant.set_target(ra=ra_spin.value(), dec=dec_spin.value(), name=name_edit.text())

        grid = effective_grid()
        auto_mosaic = grid is not None and mosaic_grid() is None
        if grid is None:
            # A previously active mosaic (from an earlier visit to this dialog) no longer applies
            # once the user dials the grid back down to a single frame — Capture must not keep
            # shooting the old mosaic silently.
            service.active_mosaic = None
        if grid is not None:
            cols, rows, overlap_pct = grid
            mosaic = assistant.create_mosaic(
                center_ra=ra_spin.value(), center_dec=dec_spin.value(),
                cols=cols, rows=rows, overlap_pct=overlap_pct,
            )
            assistant.set_mosaic(mosaic)
            service.run_mosaic_from_framing(assistant)
            if auto_mosaic:
                self._window.statusBar().showMessage(
                    f"No rotator: capturing a {cols}×{rows} mosaic to cover the "
                    f"{rotation_spin.value():.0f}° tilted field.", 6000)
            else:
                self._window.statusBar().showMessage(
                    f"Mosaic defined: {mosaic.total_panels} panels ({cols}×{rows}).", 5000)
        elif rotator_connected and rotation_spin.value() != 0:
            try:
                asyncio.run(rotator_adapter.move_to_angle(rotation_spin.value()))
                self._window.statusBar().showMessage(
                    f"Framing target set: {name_edit.text() or 'unnamed'}; rotator moved to "
                    f"{rotation_spin.value():.1f}°.", 5000)
            except Exception:
                logger.exception("Framing Assistant could not move the rotator")
                self._window.statusBar().showMessage(
                    "Framing target set, but the rotator move failed — see log.", 6000)
        else:
            self._window.statusBar().showMessage(
                f"Framing target set: {name_edit.text() or 'unnamed'}.", 4000)
        assistant.close()
