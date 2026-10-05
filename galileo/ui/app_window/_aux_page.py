# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Aux device-category page (EQP-AUX-010)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from collections.abc import Callable

import logging

from ._common import _when_visible, _DEFAULT_PORTS, QWidget

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState

# INDI/driver property state -> state-dot color (matching the INDI convention:
# Idle=grey, Ok=green, Busy=yellow, Alert=red). Alpaca's generic Aux adapter
# never reports anything but "Idle" (ISwitchV2 has no equivalent state), so
# Alpaca Aux panels show a steady grey dot — not a regression, there's simply
# nothing else to show.
_STATE_COLOR = {"Ok": "#2ecc71", "Busy": "#f1c40f", "Alert": "#e74c3c"}


class AppWindowAuxPageMixin:
    def _build_aux_page(self: AppWindowState) -> QWidget:
        """Aux device-category page: load a miscellaneous INDI device, or an
        ASCOM Alpaca Switch device, and control whatever fields and switches
        its driver defines, grouped into tabs the same way the driver itself
        groups them (INDI property groups; a single "Switches" tab for
        Alpaca). Unlike every other Equipment page, there is no fixed set of
        controls — the panel is rebuilt from ``AuxController.get_property_groups()``
        once connected, then refreshed in place on a timer."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton,
            QHeaderView, QMessageBox, QSlider, QTabWidget, QButtonGroup,
        )
        from PySide6.QtCore import QTimer, Qt

        page = QWidget()
        page.setObjectName("AuxPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Aux")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        subtitle = QLabel(
            "Load a miscellaneous INDI driver, or an ASCOM Alpaca Switch device, "
            "and control whatever fields and switches it defines."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # --- connection row (same as every other Equipment page) --------
        table = QTableWidget(1, 4)
        table.setHorizontalHeaderLabels(["Driver", "Server", "Port", ""])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.setMaximumHeight(70)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        driver_combo = QComboBox()
        driver_combo.addItems(["Alpaca", "INDI"])
        table.setCellWidget(0, 0, driver_combo)

        server_edit = QLineEdit()
        server_edit.setPlaceholderText("FQDN or IP, e.g. seestar.local or 192.168.1.50")
        server_edit.setMaxLength(40)
        table.setCellWidget(0, 1, server_edit)

        port_spin = QSpinBox()
        port_spin.setRange(1, 65535)
        port_spin.setValue(_DEFAULT_PORTS["Alpaca"])
        port_spin.setToolTip(
            "Alpaca has no single standard port — 32323 for a Seestar's "
            "Alpaca bridge, 11111 for ASCOM Remote/simulators, or whatever "
            "your device's own driver documents."
        )

        def _apply_default_port(driver_name: str) -> None:
            port_spin.setValue(_DEFAULT_PORTS.get(driver_name, _DEFAULT_PORTS["Alpaca"]))

        driver_combo.currentTextChanged.connect(_apply_default_port)
        table.setCellWidget(0, 2, port_spin)

        scan_btn = QPushButton("Scan")
        scan_btn.setObjectName("AccentButton")
        table.setCellWidget(0, 3, scan_btn)
        layout.addWidget(table)

        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("Device"))
        device_combo = QComboBox()
        device_combo.setEditable(True)
        device_combo.addItem("")
        device_row.addWidget(device_combo, 1)
        connect_btn = QPushButton("Connect")
        connect_btn.setObjectName("AccentButton")
        device_row.addWidget(connect_btn)
        layout.addLayout(device_row)

        driver_info_row, apply_driver_info = self._build_driver_info_row()
        layout.addLayout(driver_info_row)

        # --- live control panel: one tab per driver-defined property group ---
        panel_container = QVBoxLayout()
        layout.addLayout(panel_container, 1)

        state: dict[str, Any] = {"adapter": None, "tabs": None, "rows": []}
        adapters_by_pier: dict = {}

        def _set_accent(button, active: bool) -> None:
            button.setObjectName("AccentButton" if active else "")
            button.style().unpolish(button)
            button.style().polish(button)

        def _build_switch_row(prop) -> tuple[QWidget, Callable]:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("●")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            row.addWidget(QLabel(prop.label))
            row.addStretch(1)

            exclusive = prop.rule in ("OneOfMany", "AtMostOne")
            group = QButtonGroup(row_widget)
            group.setExclusive(exclusive)
            buttons: list[tuple[Any, str]] = []
            for el in prop.elements:
                btn = QPushButton(el.label)
                btn.setCheckable(True)
                btn.setChecked(bool(el.value))
                btn.setEnabled(prop.perm != "ro")
                group.addButton(btn)
                row.addWidget(btn)
                buttons.append((btn, el.name))
                _set_accent(btn, bool(el.value))

            for btn, el_name in buttons:
                def _on_clicked(checked: bool, el_name=el_name) -> None:
                    _write(prop.name, {el_name: checked})
                btn.clicked.connect(_on_clicked)

            def _refresh(p) -> None:
                dot.setStyleSheet(f"color: {_STATE_COLOR.get(p.state, '#888888')}; font-size: 14px;")
                live = {el.name: el.value for el in p.elements}
                for btn, el_name in buttons:
                    checked = bool(live.get(el_name, btn.isChecked()))
                    btn.blockSignals(True)
                    btn.setChecked(checked)
                    btn.blockSignals(False)
                    _set_accent(btn, checked)

            return row_widget, _refresh

        def _build_number_row(prop) -> tuple[QWidget, Callable]:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("●")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            row.addWidget(QLabel(prop.label))
            row.addStretch(1)

            multi = len(prop.elements) > 1
            # (slider, spin, element name, slider-per-unit scale)
            controls: list[tuple[Any, Any, str, float]] = []
            for el in prop.elements:
                if multi:
                    row.addWidget(QLabel(el.label))
                lo = el.min if el.min is not None else 0.0
                value = float(el.value) if el.value is not None else lo
                hi = el.max if el.max is not None else max(lo + 1.0, value * 2.0, 100.0)
                step = el.step or 1.0
                scale = (1.0 / step) if step > 0 else 1.0

                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(round(lo * scale), round(hi * scale))
                spin = QDoubleSpinBox()
                spin.setRange(lo, hi)
                spin.setSingleStep(step)
                spin.setDecimals(3 if step < 1 else 1)
                spin.setValue(value)
                slider.setValue(round(value * scale))
                spin.setEnabled(prop.perm != "ro")
                slider.setEnabled(prop.perm != "ro")

                slider.valueChanged.connect(lambda v, spin=spin, scale=scale: spin.setValue(v / scale))
                spin.valueChanged.connect(lambda v, slider=slider, scale=scale: slider.setValue(round(v * scale)))

                row.addWidget(slider, 1)
                row.addWidget(spin)
                controls.append((slider, spin, el.name, scale))

            set_btn = QPushButton("Set")
            set_btn.setObjectName("AccentButton")
            set_btn.setEnabled(prop.perm != "ro")
            row.addWidget(set_btn)

            def _on_set() -> None:
                values = {name: spin.value() for _slider, spin, name, _scale in controls}
                _write(prop.name, values)

            set_btn.clicked.connect(_on_set)

            def _refresh(p) -> None:
                dot.setStyleSheet(f"color: {_STATE_COLOR.get(p.state, '#888888')}; font-size: 14px;")
                live = {el.name: el.value for el in p.elements}
                for slider, spin, name, scale in controls:
                    if spin.hasFocus() or slider.isSliderDown():
                        continue  # don't clobber a value the user is mid-edit on
                    value = live.get(name)
                    if value is None:
                        continue
                    spin.blockSignals(True)
                    slider.blockSignals(True)
                    spin.setValue(float(value))
                    slider.setValue(round(spin.value() * scale))
                    spin.blockSignals(False)
                    slider.blockSignals(False)

            return row_widget, _refresh

        def _build_text_row(prop) -> tuple[QWidget, Callable]:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("●")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            row.addWidget(QLabel(prop.label))
            row.addStretch(1)

            edits: list[tuple[Any, str]] = []
            for el in prop.elements:
                if len(prop.elements) > 1:
                    row.addWidget(QLabel(el.label))
                edit = QLineEdit(str(el.value) if el.value is not None else "")
                edit.setEnabled(prop.perm != "ro")
                row.addWidget(edit, 1)
                edits.append((edit, el.name))

            set_btn = QPushButton("Set")
            set_btn.setObjectName("AccentButton")
            set_btn.setEnabled(prop.perm != "ro")
            row.addWidget(set_btn)

            def _on_set() -> None:
                _write(prop.name, {name: edit.text() for edit, name in edits})

            set_btn.clicked.connect(_on_set)

            def _refresh(p) -> None:
                dot.setStyleSheet(f"color: {_STATE_COLOR.get(p.state, '#888888')}; font-size: 14px;")
                live = {el.name: el.value for el in p.elements}
                for edit, name in edits:
                    if edit.hasFocus():
                        continue
                    value = live.get(name)
                    if value is not None and edit.text() != str(value):
                        edit.setText(str(value))

            return row_widget, _refresh

        def _build_light_row(prop) -> tuple[QWidget, Callable]:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("●")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            row.addWidget(QLabel(prop.label))
            row.addStretch(1)
            element_dots = []
            for el in prop.elements:
                row.addWidget(QLabel(el.label))
                el_dot = QLabel("●")
                el_dot.setFixedWidth(16)
                row.addWidget(el_dot)
                element_dots.append((el_dot, el.name))

            def _refresh(p) -> None:
                dot.setStyleSheet(f"color: {_STATE_COLOR.get(p.state, '#888888')}; font-size: 14px;")
                live = {el.name: el.value for el in p.elements}
                for el_dot, name in element_dots:
                    el_dot.setStyleSheet(
                        f"color: {_STATE_COLOR.get(str(live.get(name)), '#888888')}; font-size: 14px;"
                    )

            return row_widget, _refresh

        def _build_group_tabs(groups: list) -> None:
            while panel_container.count():
                item = panel_container.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
            state["tabs"] = None
            state["rows"] = []
            if not groups:
                placeholder = QLabel("Connect a device to show its control panel.")
                placeholder.setObjectName("CriteriaHeading")
                panel_container.addWidget(placeholder)
                return
            tabs = QTabWidget()
            for group in groups:
                tab = QWidget()
                tab_layout = QVBoxLayout(tab)
                tab_layout.setSpacing(8)
                for prop in group.properties:
                    if prop.kind == "number":
                        widget, refresh = _build_number_row(prop)
                    elif prop.kind == "switch":
                        widget, refresh = _build_switch_row(prop)
                    elif prop.kind == "text":
                        widget, refresh = _build_text_row(prop)
                    else:
                        widget, refresh = _build_light_row(prop)
                    tab_layout.addWidget(widget)
                    state["rows"].append((prop.name, refresh))
                tab_layout.addStretch(1)
                tabs.addTab(tab, group.name)
            panel_container.addWidget(tabs)
            state["tabs"] = tabs

        def _write(prop_name: str, values: dict) -> None:
            adapter = state.get("adapter")
            if adapter is None:
                return
            import asyncio
            from galileo.core.devices import AuxController
            try:
                asyncio.run(AuxController(adapter).write_property(prop_name, values))
            except Exception:
                logger.exception("Aux: writing %s failed", prop_name)
                self._window.statusBar().showMessage(f"Could not set {prop_name} — see log.", 6000)
                return
            logger.info("Aux: set %s = %s", prop_name, values)
            _refresh_panel()

        def _refresh_panel() -> None:
            adapter = state.get("adapter")
            if adapter is None:
                return
            import asyncio
            from galileo.core.devices import AuxController
            try:
                groups = asyncio.run(AuxController(adapter).get_property_groups())
            except Exception:
                logger.exception("Aux: could not refresh control panel")
                return
            incoming_names = {p.name for g in groups for p in g.properties}
            current_names = {name for name, _refresh in state["rows"]}
            if state["tabs"] is None or current_names != incoming_names:
                _build_group_tabs(groups)
                return
            by_name = {p.name: p for g in groups for p in g.properties}
            for name, refresh in state["rows"]:
                prop = by_name.get(name)
                if prop is not None:
                    refresh(prop)

        _build_group_tabs([])

        # --- connection: connect / scan ------------------------------------
        def _do_connect(device_name: str) -> None:
            from galileo.core.devices import DeviceCategory
            adapter = self._connect_device_adapter(
                DeviceCategory.AUX, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to Aux device {device_name!r} — see log.", 6000)
                return
            from galileo.current_object import pier_key
            state["adapter"] = adapter
            adapters_by_pier[pier_key(self._current_pier)] = adapter
            self._window.statusBar().showMessage(f"Connected to Aux device {device_name!r}.", 4000)
            _refresh_panel()

        def _connect_clicked() -> None:
            device_name = device_combo.currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select an Aux device first.")
                return
            _do_connect(device_name)

        connect_btn.clicked.connect(_connect_clicked)

        def _device_picked() -> None:
            """Show the driver of the device just picked, without connecting it."""
            from galileo.core.devices import DeviceCategory
            apply_driver_info(self._lookup_driver_info(
                DeviceCategory.AUX, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip(),
            ))

        device_combo.activated.connect(lambda _index: _device_picked())

        def run_scan() -> None:
            server = server_edit.text().strip() or "localhost"
            port = port_spin.value()
            driver = driver_combo.currentText()
            from galileo.core.devices import DeviceCategory
            devices: list[str] = []
            try:
                import asyncio
                if driver == "INDI":
                    from galileo.adapters.indi import get_adapter_class
                else:
                    from galileo.adapters.alpaca import get_adapter_class
                adapter = get_adapter_class(DeviceCategory.AUX)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.AUX))
            except Exception:
                logger.exception("Aux scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Aux scan failed — see log.", 6000)
                devices = []
            current = device_combo.currentText()
            device_combo.blockSignals(True)
            device_combo.clear()
            device_combo.addItem("")
            for name in devices:
                device_combo.addItem(name)
            if current and device_combo.findText(current) < 0:
                device_combo.addItem(current)
            idx = device_combo.findText(current)
            device_combo.setCurrentIndex(max(idx, 0))
            device_combo.blockSignals(False)
            if devices:
                logger.info(
                    "Detected %d %s Aux-eligible device(s) at %s:%s: %s",
                    len(devices), driver, server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} device(s) — see log.", 4000)
            else:
                logger.info("No %s Aux-eligible devices found at %s:%s.", driver, server, port)
                self._window.statusBar().showMessage(f"No {driver} devices found at {server}:{port}.", 4000)

        scan_btn.clicked.connect(run_scan)

        # --- footer: Save + Log ---------------------------------------------
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        save_btn.setToolTip("Save this device's settings under the selected Observatory and Pier.")
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        layout.addWidget(log_heading)
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)
        layout.addWidget(log_pane)

        def save_aux_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_device_config
            save_device_config(
                self._current_pier, "aux",
                driver=driver_combo.currentText(), server=server_edit.text().strip(),
                port=port_spin.value(), device_name=device_combo.currentText().strip() or None,
            )
            logger.info(
                "Saved Aux settings for Pier %r: %s %s:%s, device: %s",
                self._current_pier.name, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip() or "(none)",
            )
            self._window.statusBar().showMessage(
                f"Saved Aux settings for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_aux_config)

        def reload_page() -> None:
            cfg = None
            if self._current_pier is not None:
                from galileo.observatory import get_device_config
                try:
                    cfg = get_device_config(self._current_pier, "aux")
                except Exception:
                    logger.exception("Could not load saved Aux config")

            driver_combo.blockSignals(True)
            server_edit.blockSignals(True)
            port_spin.blockSignals(True)
            device_combo.blockSignals(True)
            try:
                device_combo.clear()
                device_combo.addItem("")
                if cfg is not None:
                    idx = driver_combo.findText(cfg.driver)
                    if idx >= 0:
                        driver_combo.setCurrentIndex(idx)
                    server_edit.setText(cfg.server)
                    port_spin.setValue(cfg.port)
                    if cfg.device_name:
                        device_combo.addItem(cfg.device_name)
                        device_combo.setCurrentText(cfg.device_name)
                else:
                    driver_combo.setCurrentIndex(0)
                    server_edit.clear()
                    port_spin.setValue(_DEFAULT_PORTS.get(driver_combo.currentText(), _DEFAULT_PORTS["Alpaca"]))
            finally:
                driver_combo.blockSignals(False)
                server_edit.blockSignals(False)
                port_spin.blockSignals(False)
                device_combo.blockSignals(False)

            apply_driver_info(None)  # refilled on connect / device pick

            from galileo.current_object import pier_key
            adapter = adapters_by_pier.get(pier_key(self._current_pier))
            state["adapter"] = adapter
            if adapter is not None:
                _refresh_panel()
            else:
                _build_group_tabs([])

        def autoconnect_page() -> None:
            from galileo.current_object import pier_key
            device_name = device_combo.currentText().strip()
            if device_name and adapters_by_pier.get(pier_key(self._current_pier)) is None:
                _do_connect(device_name)

        def disconnect_page() -> None:
            """Pier-level Disconnect button: tear down this Pier's Aux connection."""
            from galileo.current_object import pier_key
            adapter = adapters_by_pier.pop(pier_key(self._current_pier), None)
            if adapter is None:
                return
            import asyncio
            try:
                asyncio.run(adapter.disconnect())
            except Exception:
                logger.exception("Could not disconnect Aux device")
            state["adapter"] = None
            _build_group_tabs([])
            self._window.statusBar().showMessage("Aux device disconnected.", 4000)

        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _refresh_panel))
        status_timer.start(2000)

        state["reload"] = reload_page
        state["autoconnect"] = autoconnect_page
        state["disconnect"] = disconnect_page
        state["connected"] = lambda: state.get("adapter") is not None
        self._device_pages["aux"] = state
        reload_page()
        if self._startup_autoconnect_allowed():
            autoconnect_page()

        return page
