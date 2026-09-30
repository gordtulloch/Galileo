# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Per-block-type parameter dialogs for the Sessions screen (SES-130/SES-140),
opened from a session block's own right-click "Edit Parameters…" menu entry
(``galileo.ui.sessions.BlockListWidget``). Each block type that has any
dataclass fields worth editing gets a small ``QDialog`` here; a block with no
fields (e.g. Dither, Park Mount) simply has no entry in ``_EDITORS`` below and
its menu entry is shown disabled instead.

Kept in its own module, separate from ``galileo.ui.sessions``, so that file
stays the model + drag-and-drop chrome it already documents itself as being,
without every block type's dialog-building code inline in it too.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from galileo.ui import sessions as sessions_mod

logger = logging.getLogger(__name__)

_UNSET_INT = -1  # sentinel spin-box value standing in for a None gain/offset


def _preceding_target(region: Any, block: Any) -> Any:
    """The nearest ``TargetBlock`` before *block* in *region*, if any — used to
    default a mosaic's centre RA/Dec to the session's own target."""
    target = None
    for b in region.blocks:
        if b is block:
            break
        if isinstance(b, sessions_mod.TargetBlock):
            target = b
    return target


def _edit_target_block(parent, block, region, window) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Target Parameters")
    form = QFormLayout(dialog)

    name_edit = QLineEdit(block.name)
    name_edit.setObjectName("name_edit")
    form.addRow("Name", name_edit)

    ra_spin = QDoubleSpinBox()
    ra_spin.setObjectName("ra_spin")
    ra_spin.setRange(0.0, 360.0)
    ra_spin.setDecimals(6)
    ra_spin.setSuffix(" °")
    ra_spin.setValue(block.ra_deg)
    form.addRow("RA", ra_spin)

    dec_spin = QDoubleSpinBox()
    dec_spin.setObjectName("dec_spin")
    dec_spin.setRange(-90.0, 90.0)
    dec_spin.setDecimals(6)
    dec_spin.setSuffix(" °")
    dec_spin.setValue(block.dec_deg)
    form.addRow("Dec", dec_spin)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    block.name = name_edit.text().strip()
    block.ra_deg = ra_spin.value()
    block.dec_deg = dec_spin.value()
    block.is_placeholder_target = False
    return True


_FRAME_TYPES = ["Light", "Dark", "Flat", "Bias"]


def _edit_image_block(parent, block, region, window) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Image Parameters")
    outer = QVBoxLayout(dialog)
    form = QFormLayout()
    outer.addLayout(form)

    exposure_spin = QDoubleSpinBox()
    exposure_spin.setObjectName("exposure_spin")
    exposure_spin.setRange(0.001, 99999.0)
    exposure_spin.setDecimals(3)
    exposure_spin.setSuffix(" s")
    exposure_spin.setValue(block.exposure)
    form.addRow("Exposure", exposure_spin)

    count_spin = QSpinBox()
    count_spin.setObjectName("count_spin")
    count_spin.setRange(1, 99999)
    count_spin.setValue(block.count)
    form.addRow("Count", count_spin)

    filter_edit = QLineEdit(block.filter)
    filter_edit.setObjectName("filter_edit")
    form.addRow("Filter", filter_edit)

    binning_combo = QComboBox()
    binning_combo.setObjectName("binning_combo")
    binning_combo.addItems(["1x1", "2x2", "3x3", "4x4"])
    binning_combo.setCurrentIndex(max(0, min(3, block.binning - 1)))
    form.addRow("Binning", binning_combo)

    gain_spin = QSpinBox()
    gain_spin.setObjectName("gain_spin")
    gain_spin.setRange(_UNSET_INT, 10000)
    gain_spin.setSpecialValueText("(camera default)")
    gain_spin.setValue(block.gain if block.gain is not None else _UNSET_INT)
    form.addRow("Gain", gain_spin)

    offset_spin = QSpinBox()
    offset_spin.setObjectName("offset_spin")
    offset_spin.setRange(_UNSET_INT, 10000)
    offset_spin.setSpecialValueText("(camera default)")
    offset_spin.setValue(block.offset if block.offset is not None else _UNSET_INT)
    form.addRow("Offset", offset_spin)

    frame_type_combo = QComboBox()
    frame_type_combo.setObjectName("frame_type_combo")
    frame_type_combo.addItems(_FRAME_TYPES)
    if block.frame_type in _FRAME_TYPES:
        frame_type_combo.setCurrentText(block.frame_type)
    form.addRow("Frame type", frame_type_combo)

    mosaic_label = QLabel()
    mosaic_label.setObjectName("StatusHint")
    mosaic_label.setWordWrap(True)

    def _refresh_mosaic_label() -> None:
        if block.has_mosaic:
            m = block.mosaic
            mosaic_label.setText(f"Mosaic: {m.cols}×{m.rows} ({m.total_panels} panels)")
        else:
            mosaic_label.setText("No mosaic defined — a single target frame.")

    _refresh_mosaic_label()
    form.addRow(mosaic_label)

    framing_btn = QPushButton("Framing / Mosaic…")
    framing_btn.setObjectName("framing_btn")
    framing_btn.clicked.connect(lambda: (_open_framing_assistant_for_block(dialog, block, region, window),
                                          _refresh_mosaic_label()))
    form.addRow(framing_btn)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    outer.addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    block.exposure = exposure_spin.value()
    block.count = count_spin.value()
    block.filter = filter_edit.text().strip()
    block.binning = binning_combo.currentIndex() + 1
    block.gain = None if gain_spin.value() == _UNSET_INT else gain_spin.value()
    block.offset = None if offset_spin.value() == _UNSET_INT else offset_spin.value()
    block.frame_type = frame_type_combo.currentText()
    return True


def _open_framing_assistant_for_block(parent, image_block, region, window) -> None:
    """Framing Assistant, opened against this Image block's own stored framing
    definition (SES-130, FRAME-070) — independent state from the Imaging tab's
    own Framing… control, per ``docs/SDD.md`` §4.9's "one design, two callers"
    note. Builds/updates the block's mosaic via the same ``FramingAssistant``
    model the Imaging tab uses, without that tab's rotator control (an
    ``ImageBlock`` has no rotation field of its own)."""
    from galileo.planning.framing import MosaicSettings, open_from_session_image_block

    profile_getter = getattr(window, "_imaging_optical_profile", None)
    profile = profile_getter() if callable(profile_getter) else None
    assistant = open_from_session_image_block(image_block, profile=profile)

    dialog = QDialog(parent)
    dialog.setWindowTitle("Framing / Mosaic")
    form = QFormLayout(dialog)

    target = _preceding_target(region, image_block)
    ra_spin = QDoubleSpinBox()
    ra_spin.setObjectName("ra_spin")
    ra_spin.setRange(0.0, 360.0)
    ra_spin.setDecimals(4)
    ra_spin.setSuffix(" °")
    ra_spin.setValue(target.ra_deg if target is not None else 0.0)
    form.addRow("Centre RA", ra_spin)

    dec_spin = QDoubleSpinBox()
    dec_spin.setObjectName("dec_spin")
    dec_spin.setRange(-90.0, 90.0)
    dec_spin.setDecimals(4)
    dec_spin.setSuffix(" °")
    dec_spin.setValue(target.dec_deg if target is not None else 0.0)
    form.addRow("Centre Dec", dec_spin)

    cols_spin = QSpinBox()
    cols_spin.setObjectName("cols_spin")
    cols_spin.setRange(1, 20)
    rows_spin = QSpinBox()
    rows_spin.setObjectName("rows_spin")
    rows_spin.setRange(1, 20)
    if image_block.has_mosaic:
        cols_spin.setValue(image_block.mosaic.cols)
        rows_spin.setValue(image_block.mosaic.rows)
    else:
        cols_spin.setValue(1)
        rows_spin.setValue(1)
    form.addRow("Mosaic cols", cols_spin)
    form.addRow("Mosaic rows", rows_spin)

    overlap_spin = QDoubleSpinBox()
    overlap_spin.setObjectName("overlap_spin")
    overlap_spin.setRange(0.0, 90.0)
    overlap_spin.setValue(MosaicSettings.instance().pane_overlap_pct)
    overlap_spin.setSuffix(" %")
    form.addRow("Overlap", overlap_spin)

    info_label = QLabel()
    info_label.setObjectName("StatusHint")
    info_label.setWordWrap(True)
    form.addRow(info_label)

    def refresh_info() -> None:
        fov = assistant.compute_fov()
        if cols_spin.value() > 1 or rows_spin.value() > 1:
            width_deg, height_deg = assistant.mosaic_footprint_deg(
                cols_spin.value(), rows_spin.value(), overlap_spin.value())
            info_label.setText(
                f"Frame FOV {fov.width_deg:.3f}° × {fov.height_deg:.3f}°  —  "
                f"mosaic footprint {width_deg:.3f}° × {height_deg:.3f}° "
                f"({cols_spin.value()}×{rows_spin.value()})"
            )
        else:
            info_label.setText(f"Frame FOV {fov.width_deg:.3f}° × {fov.height_deg:.3f}° (no mosaic)")

    cols_spin.valueChanged.connect(lambda _: refresh_info())
    rows_spin.valueChanged.connect(lambda _: refresh_info())
    overlap_spin.valueChanged.connect(lambda _: refresh_info())
    refresh_info()

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        assistant.close()
        return

    MosaicSettings.instance().set_pane_overlap_pct(overlap_spin.value())
    if cols_spin.value() > 1 or rows_spin.value() > 1:
        assistant.set_target(ra_spin.value(), dec_spin.value())
        mosaic = assistant.create_mosaic(
            center_ra=ra_spin.value(), center_dec=dec_spin.value(),
            cols=cols_spin.value(), rows=rows_spin.value(), overlap_pct=overlap_spin.value(),
        )
        assistant.set_mosaic(mosaic)
        image_block.set_mosaic(mosaic)
    else:
        image_block.set_mosaic(None)
    assistant.close()


def _edit_filter_change_block(parent, block, region, window) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Filter Change Parameters")
    form = QFormLayout(dialog)
    filter_edit = QLineEdit(block.filter)
    filter_edit.setObjectName("filter_edit")
    form.addRow("Filter", filter_edit)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    block.filter = filter_edit.text().strip()
    return True


def _edit_cool_camera_block(parent, block, region, window) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Cool Camera Parameters")
    form = QFormLayout(dialog)
    setpoint_spin = QDoubleSpinBox()
    setpoint_spin.setObjectName("setpoint_spin")
    setpoint_spin.setRange(-50.0, 30.0)
    setpoint_spin.setDecimals(1)
    setpoint_spin.setSuffix(" °C")
    setpoint_spin.setValue(block.setpoint_c)
    form.addRow("Setpoint", setpoint_spin)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    block.setpoint_c = setpoint_spin.value()
    return True


def _edit_autofocus_block(parent, block, region, window) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Autofocus Parameters")
    form = QFormLayout(dialog)
    use_current_check = QCheckBox("Focus on the current filter")
    use_current_check.setObjectName("use_current_check")
    use_current_check.setChecked(block.filter is None)
    filter_edit = QLineEdit(block.filter or "")
    filter_edit.setObjectName("filter_edit")
    filter_edit.setEnabled(not use_current_check.isChecked())
    use_current_check.toggled.connect(lambda checked: filter_edit.setEnabled(not checked))
    form.addRow(use_current_check)
    form.addRow("Filter", filter_edit)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    block.filter = None if use_current_check.isChecked() else filter_edit.text().strip() or None
    return True


def _edit_guide_start_block(parent, block, region, window) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Guide Start Parameters")
    form = QFormLayout(dialog)
    calibrate_check = QCheckBox("Calibrate before guiding")
    calibrate_check.setObjectName("calibrate_check")
    calibrate_check.setChecked(block.calibrate)
    form.addRow(calibrate_check)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    block.calibrate = calibrate_check.isChecked()
    return True


def _edit_flat_capture_block(parent, block, region, window) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Flat Capture Parameters")
    form = QFormLayout(dialog)
    count_spin = QSpinBox()
    count_spin.setObjectName("count_spin")
    count_spin.setRange(1, 9999)
    count_spin.setValue(block.count)
    form.addRow("Count", count_spin)
    adu_spin = QDoubleSpinBox()
    adu_spin.setObjectName("adu_spin")
    adu_spin.setRange(0.0, 65535.0)
    adu_spin.setValue(block.target_adu)
    form.addRow("Target ADU", adu_spin)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    block.count = count_spin.value()
    block.target_adu = adu_spin.value()
    return True


def _edit_notification_block(parent, block, region, window) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Notification Parameters")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Message"))
    message_edit = QPlainTextEdit(block.message)
    message_edit.setObjectName("message_edit")
    layout.addWidget(message_edit)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    block.message = message_edit.toPlainText()
    return True


# Block types with at least one editable parameter — anything not listed here
# (e.g. Dither, Park Mount, Meridian Flip: no fields at all) shows its "Edit
# Parameters…" menu entry disabled instead of opening an empty dialog.
_EDITORS: dict[type, Callable[..., bool]] = {
    sessions_mod.TargetBlock: _edit_target_block,
    sessions_mod.ImageBlock: _edit_image_block,
    sessions_mod.FilterChangeBlock: _edit_filter_change_block,
    sessions_mod.CoolCameraBlock: _edit_cool_camera_block,
    sessions_mod.AutofocusBlock: _edit_autofocus_block,
    sessions_mod.GuideStartBlock: _edit_guide_start_block,
    sessions_mod.FlatCaptureBlock: _edit_flat_capture_block,
    sessions_mod.NotificationBlock: _edit_notification_block,
}


def has_parameters(block_cls: type) -> bool:
    """Whether *block_cls* has a registered parameter dialog — used to grey out
    a block's "Edit Parameters…" menu entry when it has no fields at all."""
    return block_cls in _EDITORS


def open_block_parameter_dialog(parent, block: Any, region: Any, window: Any = None) -> bool:
    """Open *block*'s own parameter dialog, if it has one. Returns True if the
    block's fields were changed (the caller should refresh its display)."""
    editor = _EDITORS.get(type(block))
    if editor is None:
        return False
    try:
        return editor(parent, block, region, window)
    except Exception:
        logger.exception("Block parameter dialog failed for %s", type(block).__name__)
        return False
