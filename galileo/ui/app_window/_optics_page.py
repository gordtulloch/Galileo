# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Optics (optical tube) device-category page."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _device_association_label, QWidget

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowOpticsPageMixin:
    def _build_optics_page(self: AppWindowState) -> QWidget:
        """Optics page (PROF-070): one panel per optical tube on the current
        Pier — focal length, aperture, optical design, and image alignment
        (reversed/inverted) — plus an "Associated" list of the Pier's other
        configured devices (camera, guider, focuser, ...) that sit behind
        that tube. A "+" next to the title adds another tube; the "+" next
        to each tube's "Associated:" label picks from the devices already
        saved on the other Equipment pages."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QLabel, QComboBox,
            QDoubleSpinBox, QPushButton, QCheckBox, QScrollArea, QMessageBox, QInputDialog,
            QLineEdit,
        )
        from galileo.library.models.optical_tube import OPTICAL_SYSTEMS

        page = QWidget()
        page.setObjectName("OpticsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        heading = QLabel("Optics")
        heading.setObjectName("PageTitle")
        heading_row.addWidget(heading)
        add_tube_btn = QPushButton("+")
        add_tube_btn.setObjectName("AccentButton")
        add_tube_btn.setFixedWidth(28)
        add_tube_btn.setToolTip("Add another optical tube.")
        heading_row.addWidget(add_tube_btn)
        heading_row.addStretch(1)
        layout.addLayout(heading_row)

        panels: list[dict] = []

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        panels_container = QWidget()
        panels_layout = QVBoxLayout(panels_container)
        panels_layout.setContentsMargins(0, 0, 0, 0)
        panels_layout.setSpacing(10)
        panels_layout.addStretch(1)
        scroll_area.setWidget(panels_container)
        layout.addWidget(scroll_area, 1)

        def _device_labels() -> dict:
            """``"<category>:<slot>"`` -> display label for every device saved on the current Pier."""
            if self._current_pier is None:
                return {}
            from galileo.observatory import list_device_configs
            try:
                configs = list_device_configs(self._current_pier)
            except Exception:
                logger.exception("Could not load saved device configs for the Optics page")
                return {}
            return {
                f"{c.category}:{c.slot}": _device_association_label(c.category, c.slot, c.device_name)
                for c in configs
            }

        def _render_associations(panel: dict) -> None:
            box = panel["assoc_layout"]
            while box.count():
                row = box.takeAt(0).layout()
                while row is not None and row.count():
                    widget = row.takeAt(0).widget()
                    if widget is not None:
                        widget.setParent(None)
                        widget.deleteLater()
            labels = _device_labels()
            for key in panel["assoc_keys"]:
                row = QHBoxLayout()
                row.addWidget(QLabel(labels.get(key, f"{key} (not configured)")), 1)
                remove = QPushButton("Remove")
                remove.clicked.connect(lambda _c=False, k=key: _dissociate(panel, k))
                row.addWidget(remove)
                box.addLayout(row)

        def _associate(panel: dict) -> None:
            labels = _device_labels()
            choices = {k: v for k, v in labels.items() if k not in panel["assoc_keys"]}
            if not choices:
                QMessageBox.information(
                    self._window, "No devices to associate",
                    "Save a device on one of the other Equipment pages first — every "
                    "device saved on this Pier is already associated with this tube.",
                )
                return
            picked, ok = QInputDialog.getItem(
                self._window, "Associate device", "Device:", list(choices.values()), 0, False
            )
            if not ok:
                return
            key = next(k for k, v in choices.items() if v == picked)
            panel["assoc_keys"].append(key)
            _render_associations(panel)

        def _dissociate(panel: dict, key: str) -> None:
            if key in panel["assoc_keys"]:
                panel["assoc_keys"].remove(key)
                _render_associations(panel)

        def _build_tube_panel(removable: bool) -> dict:
            frame = QFrame()
            frame.setObjectName("DeviceSlotPanel")
            outer = QVBoxLayout(frame)

            header = QHBoxLayout()
            title_label = QLabel()
            title_label.setObjectName("CriteriaHeading")
            header.addWidget(title_label)
            header.addStretch(1)
            remove_btn = None
            if removable:
                remove_btn = QPushButton("Remove")
                header.addWidget(remove_btn)
            outer.addLayout(header)

            form = QFormLayout()
            outer.addLayout(form)

            name_edit = QLineEdit()
            name_edit.setPlaceholderText("e.g. Esprit 100ED")
            name_edit.setMaxLength(60)
            form.addRow("Name", name_edit)

            focal = QDoubleSpinBox()
            focal.setRange(0.0, 50000.0)
            focal.setDecimals(1)
            focal.setSuffix(" mm")
            form.addRow("Focal Length", focal)

            aperture = QDoubleSpinBox()
            aperture.setRange(0.0, 5000.0)
            aperture.setDecimals(1)
            aperture.setSuffix(" mm")
            form.addRow("Aperture", aperture)

            system = QComboBox()
            system.addItems(OPTICAL_SYSTEMS)
            form.addRow("Optical System", system)

            alignment_row = QHBoxLayout()
            reversed_check = QCheckBox("Reversed")
            reversed_check.setToolTip("The image is mirrored left-to-right (e.g. a refractor with a star diagonal).")
            inverted_check = QCheckBox("Inverted")
            inverted_check.setToolTip("The image is flipped top-to-bottom (e.g. a Newtonian).")
            alignment_row.addWidget(reversed_check)
            alignment_row.addWidget(inverted_check)
            alignment_row.addStretch(1)
            form.addRow("Image Alignment", alignment_row)

            assoc_header = QHBoxLayout()
            assoc_title = QLabel("Associated:")
            assoc_title.setObjectName("CriteriaHeading")
            assoc_header.addWidget(assoc_title)
            associate_btn = QPushButton("+")
            associate_btn.setObjectName("AccentButton")
            associate_btn.setFixedWidth(28)
            associate_btn.setToolTip("Associate a device already configured on this Pier with this tube.")
            assoc_header.addWidget(associate_btn)
            assoc_header.addStretch(1)
            outer.addLayout(assoc_header)

            assoc_layout = QVBoxLayout()
            outer.addLayout(assoc_layout)

            return {
                "frame": frame, "title_label": title_label, "remove_btn": remove_btn,
                "name": name_edit, "focal": focal, "aperture": aperture, "system": system,
                "reversed": reversed_check, "inverted": inverted_check,
                "associate_btn": associate_btn, "assoc_layout": assoc_layout, "assoc_keys": [],
            }

        def _renumber_panels() -> None:
            for i, panel in enumerate(panels):
                panel["title_label"].setText(f"Optical Tube {i + 1}")

        def _remove_panel(panel: dict) -> None:
            if panel not in panels or panel is panels[0]:
                return
            panels.remove(panel)
            panel["frame"].setParent(None)
            panel["frame"].deleteLater()
            _renumber_panels()

        def _add_panel() -> dict:
            panel = _build_tube_panel(removable=len(panels) > 0)
            panels.append(panel)
            panels_layout.insertWidget(panels_layout.count() - 1, panel["frame"])
            _renumber_panels()
            if panel["remove_btn"] is not None:
                panel["remove_btn"].clicked.connect(lambda: _remove_panel(panel))
            panel["associate_btn"].clicked.connect(lambda: _associate(panel))
            return panel

        def _set_panel_count(count: int) -> None:
            count = max(count, 1)
            while len(panels) < count:
                _add_panel()
            while len(panels) > count:
                _remove_panel(panels[-1])

        add_tube_btn.clicked.connect(_add_panel)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        save_btn.setToolTip("Save every optical tube under the selected Observatory and Pier.")
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        layout.addWidget(log_heading)
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)
        layout.addWidget(log_pane)

        def save_optics() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_optical_tubes
            try:
                save_optical_tubes(self._current_pier, [
                    {
                        "name": p["name"].text().strip(),
                        "focal_length_mm": p["focal"].value(),
                        "aperture_mm": p["aperture"].value(),
                        "optical_system": p["system"].currentText(),
                        "image_reversed": p["reversed"].isChecked(),
                        "image_inverted": p["inverted"].isChecked(),
                        "associated": list(p["assoc_keys"]),
                    }
                    for p in panels
                ])
            except Exception:
                logger.exception("Could not save optical tubes for Pier %r", self._current_pier.name)
                return
            logger.info("Saved %d optical tube(s) for Pier %r.", len(panels), self._current_pier.name)
            self._refresh_optics_combo()  # the top-bar selector lists what was just saved
            self._window.statusBar().showMessage(
                f"Saved optics for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_optics)

        def reload_page() -> None:
            tubes = []
            if self._current_pier is not None:
                from galileo.observatory import list_optical_tubes
                try:
                    tubes = list_optical_tubes(self._current_pier)
                except Exception:
                    logger.exception("Could not load saved optical tubes")
            _set_panel_count(len(tubes))
            for i, panel in enumerate(panels):
                tube = tubes[i] if i < len(tubes) else None
                panel["name"].setText(tube.name if tube else "")
                panel["focal"].setValue(tube.focal_length_mm if tube else 0.0)
                panel["aperture"].setValue(tube.aperture_mm if tube else 0.0)
                idx = panel["system"].findText(tube.optical_system) if tube else 0
                panel["system"].setCurrentIndex(max(idx, 0))
                panel["reversed"].setChecked(bool(tube and tube.image_reversed))
                panel["inverted"].setChecked(bool(tube and tube.image_inverted))
                panel["assoc_keys"] = list(tube.associated) if tube else []
                _render_associations(panel)

        self._device_pages["optics"] = {"reload": reload_page}
        reload_page()

        return page
