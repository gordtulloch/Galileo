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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
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
    wheel_getter = getattr(window, "_active_filter_wheel", None)
    wheel = wheel_getter() if callable(wheel_getter) else None
    names = [str(n) for n in (getattr(wheel, "filter_names", None) or [])] if wheel is not None else []
    filter_combo = QComboBox()
    filter_combo.setObjectName("filter_combo")
    filter_combo.setEditable(True)  # still typeable when no wheel is connected / for a template's filter
    filter_combo.addItems(names)
    filter_combo.setCurrentText(block.filter)
    filter_combo.setToolTip(
        "Filters on the active imager's filter wheel." if names
        else "No filter wheel connected — type a filter name.")
    form.addRow("Filter", filter_combo)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    block.filter = filter_combo.currentText().strip()
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


def _wheel_filter_names(window) -> list[str]:
    wheel_getter = getattr(window, "_active_filter_wheel", None)
    wheel = wheel_getter() if callable(wheel_getter) else None
    return [str(n) for n in (getattr(wheel, "filter_names", None) or [])] if wheel is not None else []


def _edit_flat_capture_block(parent, block, region, window) -> bool:
    """Mirrors the Imaging page's Flats Assistant fields (CAL-060)."""
    from galileo.calibration import ADU_METHODS, FLAT_METHODS

    dialog = QDialog(parent)
    dialog.setWindowTitle("Flat Capture Parameters")
    form = QFormLayout(dialog)
    method_combo = QComboBox()
    method_combo.setObjectName("method_combo")
    method_combo.addItems(FLAT_METHODS)
    method_combo.setCurrentText(block.method)
    form.addRow("Flat Method", method_combo)
    exposure_spin = QDoubleSpinBox()
    exposure_spin.setObjectName("exposure_spin")
    exposure_spin.setRange(0.0, 3600.0)
    exposure_spin.setDecimals(3)
    exposure_spin.setSuffix(" s")
    exposure_spin.setSpecialValueText("Calculate")
    exposure_spin.setValue(block.exposure)
    exposure_spin.setToolTip("Leave at Calculate to work the exposure out from the camera's Max Well Depth.")
    form.addRow("Exposure", exposure_spin)
    count_spin = QSpinBox()
    count_spin.setObjectName("count_spin")
    count_spin.setRange(1, 999)
    count_spin.setValue(block.count)
    form.addRow("Number of Frames", count_spin)
    filter_combo = QComboBox()
    filter_combo.setObjectName("filter_combo")
    filter_combo.setEditable(True)
    names = _wheel_filter_names(window)
    filter_combo.addItems(["All"] + [n for n in names if n != "All"])
    filter_combo.setCurrentText(block.filter or "All")
    filter_combo.setToolTip("All repeats the run for every filter in turn.")
    form.addRow("Filter", filter_combo)
    adu_combo = QComboBox()
    adu_combo.setObjectName("adu_method_combo")
    adu_combo.addItems(ADU_METHODS)
    adu_combo.setCurrentText(block.adu_method)
    form.addRow("Method", adu_combo)
    increment_spin = QDoubleSpinBox()
    increment_spin.setObjectName("increment_spin")
    increment_spin.setRange(0.001, 10.0)
    increment_spin.setDecimals(3)
    increment_spin.setSuffix(" s")
    increment_spin.setValue(block.exposure_increment)
    form.addRow("Exposure Increment", increment_spin)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    block.method = method_combo.currentText()
    block.exposure = exposure_spin.value()
    block.count = count_spin.value()
    block.filter = filter_combo.currentText().strip() or "All"
    block.adu_method = adu_combo.currentText()
    block.exposure_increment = increment_spin.value()
    return True


def _edit_dark_capture_block(parent, block, region, window) -> bool:
    """Mirrors the Imaging page's Darks Assistant fields: an optional filter and a
    comma-separated list of exposure lengths."""
    from galileo.ui.app_window._darks import _parse_exposures

    dialog = QDialog(parent)
    dialog.setWindowTitle("Dark Capture Parameters")
    form = QFormLayout(dialog)
    filter_combo = QComboBox()
    filter_combo.setObjectName("filter_combo")
    filter_combo.setEditable(True)
    filter_combo.addItem("(none)")
    filter_combo.addItems(_wheel_filter_names(window))
    filter_combo.setCurrentText(block.filter or "(none)")
    form.addRow("Filter", filter_combo)
    exposures_edit = QLineEdit(", ".join(f"{e:g}" for e in block.exposures))
    exposures_edit.setObjectName("exposures_edit")
    exposures_edit.setToolTip("Comma-separated exposure lengths in seconds; one dark per value. Example: 10,20,30,60")
    form.addRow("Exposures (s)", exposures_edit)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    exposures = _parse_exposures(exposures_edit.text())
    if not exposures:
        return False
    chosen = filter_combo.currentText().strip()
    block.filter = "" if chosen == "(none)" else chosen
    block.exposures = exposures
    return True


def _edit_for_filter_block(parent, block, region, window) -> bool:
    """Pick the filters the loop iterates over, from the active filter wheel's own
    names (plus any already on the block, e.g. from a template made on other kit)."""
    wheel_getter = getattr(window, "_active_filter_wheel", None)
    wheel = wheel_getter() if callable(wheel_getter) else None
    wheel_names = [str(n) for n in (getattr(wheel, "filter_names", None) or [])] if wheel is not None else []
    names = wheel_names + [f for f in block.filters if f not in wheel_names]

    dialog = QDialog(parent)
    dialog.setWindowTitle("FOR Filter Parameters")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(
        "Repeat the indented blocks for each checked filter, in this order."
        if names else "No filter wheel connected — enter filter names below."))
    filter_list = QListWidget()
    filter_list.setObjectName("filter_list")
    for name in names:
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if name in block.filters else Qt.CheckState.Unchecked)
        filter_list.addItem(item)
    layout.addWidget(filter_list)
    extra_edit = QLineEdit()
    extra_edit.setObjectName("extra_edit")
    extra_edit.setPlaceholderText("Other filters, comma-separated")
    layout.addWidget(extra_edit)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    chosen = [filter_list.item(i).text() for i in range(filter_list.count())
              if filter_list.item(i).checkState() == Qt.CheckState.Checked]
    for extra in (e.strip() for e in extra_edit.text().split(",")):
        if extra and extra not in chosen:
            chosen.append(extra)
    block.filters = chosen
    return True


_MAX_SEARCH_RESULTS = 25


def _edit_for_object_block(parent, block, region, window) -> bool:
    """Build the loop's object list: search the sky atlas catalog, pick a result to
    add it, and remove entries with the ✕ beside each."""
    atlas_getter = getattr(window, "_shared_sky_atlas", None)
    if callable(atlas_getter):
        atlas = atlas_getter()
    else:
        from galileo.planning.sky_atlas import SkyAtlas
        atlas = SkyAtlas()
    objects: list[dict] = [dict(o) for o in block.objects]

    dialog = QDialog(parent)
    dialog.setWindowTitle("FOR Object Parameters")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Search for an object, then pick a result to add it. "
                            "The indented blocks repeat for each object, in order."))
    search_edit = QLineEdit()
    search_edit.setObjectName("search_edit")
    search_edit.setPlaceholderText("Search objects (e.g. M31, NGC 7000, Veil)…")
    search_edit.setClearButtonEnabled(True)
    layout.addWidget(search_edit)

    results_list = QListWidget()
    results_list.setObjectName("results_list")
    results_list.setMaximumHeight(130)
    layout.addWidget(results_list)

    layout.addWidget(QLabel("Objects"))
    objects_list = QListWidget()
    objects_list.setObjectName("objects_list")
    layout.addWidget(objects_list)

    def refresh_objects() -> None:
        objects_list.clear()
        for obj in objects:
            item = QListWidgetItem()
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 2, 6, 2)
            row_layout.addWidget(QLabel(obj["name"]), 1)
            remove_btn = QToolButton()
            remove_btn.setText("✕")
            remove_btn.setToolTip(f"Remove {obj['name']}")
            remove_btn.clicked.connect(lambda _=False, o=obj: (objects.remove(o), refresh_objects()))
            row_layout.addWidget(remove_btn)
            item.setSizeHint(row.sizeHint())
            objects_list.addItem(item)
            objects_list.setItemWidget(item, row)

    def refresh_results() -> None:
        results_list.clear()
        query = search_edit.text().strip()
        if not query:
            return
        for found in atlas.search(query)[:_MAX_SEARCH_RESULTS]:
            item = QListWidgetItem(found.primary_name)
            item.setData(Qt.ItemDataRole.UserRole, found)
            results_list.addItem(item)

    def add_result(item: QListWidgetItem | None) -> None:
        if item is None:
            return
        found = item.data(Qt.ItemDataRole.UserRole)
        if not any(o["name"] == found.primary_name for o in objects):
            objects.append({"name": found.primary_name, "ra_deg": found.ra_deg, "dec_deg": found.dec_deg})
            refresh_objects()
        search_edit.clear()

    search_edit.textChanged.connect(lambda _: refresh_results())
    search_edit.returnPressed.connect(lambda: add_result(results_list.currentItem() or results_list.item(0)))
    results_list.itemActivated.connect(add_result)
    results_list.itemClicked.connect(add_result)
    refresh_objects()

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    block.objects = objects
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
    sessions_mod.DarkCaptureBlock: _edit_dark_capture_block,
    sessions_mod.NotificationBlock: _edit_notification_block,
    sessions_mod.ForFilterBlock: _edit_for_filter_block,
    sessions_mod.ForObjectBlock: _edit_for_object_block,
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
