# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Safety device-category page (EQP-WX-010, EQP-WX-020).

One tab per safety device — weather stations and safety monitors — each with
its own connection and its own per-reading rules for what makes the dome
unsafe to open. A "+" button adds a device in a new tab."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging
import time

from ._common import _when_visible, _DEFAULT_PORTS, QWidget

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState

# How long a Pier's weather-reading trend history is kept — capped by count,
# not wall-clock time, since the poll interval is itself user-configurable.
_HISTORY_MAX_SAMPLES = 1000


#: Safety-device types a tab can hold: type id (also its device-config
#: category) -> (tab/menu label, driver choices).
_SAFETY_DEVICE_TYPES = {
    "weather": ("Weather Station", ["Alpaca", "INDI"]),
    "safety_monitor": ("Safety Monitor", ["Alpaca"]),
}

#: The one reading a Safety Monitor device has: its own SAFE/NOT-SAFE verdict.
_SAFETY_MONITOR_PARAMETER_INFO = {"is_safe": ("Device reports safe", "bool")}


def _safety_parameter_info(device_type: str) -> dict:
    from galileo.safety import WEATHER_PARAMETER_INFO
    return _SAFETY_MONITOR_PARAMETER_INFO if device_type == "safety_monitor" else WEATHER_PARAMETER_INFO


def _default_safety_rules(device_type: str) -> list:
    from galileo.safety import WeatherSafetyRule, default_weather_safety_rules
    if device_type == "safety_monitor":
        # Unsafe whenever the device reports not-safe (is_safe is 1.0/0.0).
        return [WeatherSafetyRule("is_safe", safety_related=True, operator="<", threshold=1.0,
                                  label="Device reports safe", unit="bool")]
    return default_weather_safety_rules()


class AppWindowWeatherPageMixin:
    def _safety_observatory(self: AppWindowState):
        """The Observatory the Safety page belongs to: the selected one, or — when only a Pier
        has been set — that Pier's own. ``None`` while neither exists."""
        if self._current_observatory is not None:
            return self._current_observatory
        try:
            return self._current_pier.observatory if self._current_pier is not None else None
        except Exception:
            return None

    def _safety_observatory_key(self: AppWindowState):
        """What identifies the Safety page's Observatory in per-Observatory dictionaries."""
        observatory = self._safety_observatory()
        return getattr(observatory, "id", None)

    def _build_safety_device_panel(self: AppWindowState, device_type: str = "weather", slot: str = "primary"):
        """One safety device's tab: the usual Driver/Server/Port/Scan +
        Device/Connect connection row, a live readings table, and — per
        reading — whether it makes the dome unsafe to open and what crossing
        it means (EQP-WX-020, e.g. Rain is YES, Wind Speed >= 20 km/h).
        *device_type* picks the device category and which readings exist (a
        weather station has many, a safety monitor just its own SAFE
        verdict); *slot* is the device-config/rule key within the Observatory.
        Returns ``(widget, api)``."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout,
            QLabel, QTableWidget, QTableWidgetItem, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox,
            QPushButton, QHeaderView, QMessageBox, QCheckBox, QAbstractItemView,
        )
        from PySide6.QtCore import Qt
        from galileo.core.devices import DeviceCategory
        from galileo.safety import UNSAFE_OPERATORS

        param_info = _safety_parameter_info(device_type)
        kind_label, driver_choices = _SAFETY_DEVICE_TYPES[device_type]
        category_enum = (
            DeviceCategory.SAFETY_MONITOR if device_type == "safety_monitor" else DeviceCategory.WEATHER_STATION
        )

        page = QWidget()
        page.setObjectName("SafetyDevicePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        # --- connection row (same as every other Equipment page) --------
        table = QTableWidget(1, 5)
        table.setHorizontalHeaderLabels(["Driver", "Server", "Port", "Poll (s)", ""])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        table.setMaximumHeight(70)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        driver_combo = QComboBox()
        driver_combo.addItems(driver_choices)
        table.setCellWidget(0, 0, driver_combo)

        server_edit = QLineEdit()
        server_edit.setPlaceholderText("FQDN or IP, e.g. weather.local or 192.168.1.60")
        server_edit.setMaxLength(40)
        table.setCellWidget(0, 1, server_edit)

        port_spin = QSpinBox()
        port_spin.setRange(1, 65535)
        port_spin.setValue(_DEFAULT_PORTS["Alpaca"])

        def _apply_default_port(driver_name: str) -> None:
            port_spin.setValue(_DEFAULT_PORTS.get(driver_name, _DEFAULT_PORTS["Alpaca"]))

        driver_combo.currentTextChanged.connect(_apply_default_port)
        table.setCellWidget(0, 2, port_spin)

        poll_spin = QSpinBox()
        poll_spin.setRange(5, 600)
        poll_spin.setValue(60)
        poll_spin.setToolTip(
            "How often to re-read the connected weather station (EQP-WX-010). Applies the "
            "moment it is changed; Save also persists it with the rest of this device's settings."
        )
        table.setCellWidget(0, 3, poll_spin)

        scan_btn = QPushButton("Scan")
        scan_btn.setObjectName("AccentButton")
        table.setCellWidget(0, 4, scan_btn)
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

        banner = QLabel("—")
        banner.setObjectName("CriteriaHeading")
        banner.setProperty("helpKey", "status banner")
        layout.addWidget(banner)

        # --- readings + per-measure safety rules --------------------------
        parameters = list(param_info.keys())
        rules_table = QTableWidget(len(parameters), 5)
        rules_table.setHorizontalHeaderLabels(["Measure", "Current", "Blocks Dome Opening", "Unsafe When", "Threshold"])
        rules_table.verticalHeader().setVisible(False)
        rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        rules_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = rules_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        row_widgets: dict[str, dict] = {}
        for row, parameter in enumerate(parameters):
            label, unit = param_info[parameter]
            name_item = QTableWidgetItem(f"{label} ({unit})" if unit and unit != "bool" else label)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            rules_table.setItem(row, 0, name_item)

            current_item = QTableWidgetItem("—")
            rules_table.setItem(row, 1, current_item)

            safety_cell = QWidget()
            safety_layout = QHBoxLayout(safety_cell)
            safety_layout.setContentsMargins(0, 0, 0, 0)
            safety_box = QCheckBox()
            safety_layout.addWidget(safety_box)
            rules_table.setCellWidget(row, 2, safety_cell)

            operator_combo = QComboBox()
            operator_combo.addItems(list(UNSAFE_OPERATORS))
            rules_table.setCellWidget(row, 3, operator_combo)

            threshold_spin = QDoubleSpinBox()
            threshold_spin.setRange(-1000.0, 10000.0)
            threshold_spin.setDecimals(2)
            rules_table.setCellWidget(row, 4, threshold_spin)

            def _apply_enabled(checked: bool, operator_combo=operator_combo, threshold_spin=threshold_spin) -> None:
                operator_combo.setEnabled(checked)
                threshold_spin.setEnabled(checked)

            safety_box.toggled.connect(_apply_enabled)
            _apply_enabled(False)

            row_widgets[parameter] = {
                "current": current_item, "safety": safety_box,
                "operator": operator_combo, "threshold": threshold_spin,
                "label": label, "unit": unit,
            }

        rules_table.resizeRowsToContents()
        layout.addWidget(rules_table, 1)

        def _current_rules() -> list:
            from galileo.safety import WeatherSafetyRule
            rules = []
            for parameter, widgets in row_widgets.items():
                rules.append(WeatherSafetyRule(
                    parameter=parameter, label=widgets["label"], unit=widgets["unit"],
                    safety_related=widgets["safety"].isChecked(),
                    operator=widgets["operator"].currentText(),
                    threshold=widgets["threshold"].value(),
                ))
            return rules

        state: dict = {"adapter": None, "latest_readings": {}, "read_at": None}
        # Safety devices belong to the Observatory (OBS-030): one connection, shared by every
        # Pier under the roof, and kept when another Pier is selected.
        adapters_by_observatory: dict = {}

        def _format_value(value, unit: str) -> str:
            if value is None:
                return "—"
            if unit == "bool":
                return "Yes" if value else "No"
            try:
                return f"{float(value):.1f} {unit}".strip()
            except (TypeError, ValueError):
                return str(value)

        def _apply_readings(readings: dict) -> None:
            state["latest_readings"] = readings
            for parameter, widgets in row_widgets.items():
                widgets["current"].setText(_format_value(readings.get(parameter), widgets["unit"]))
            from galileo.safety import evaluate_weather_safety
            status = evaluate_weather_safety(readings, _current_rules())
            if not readings:
                banner.setText("Not connected.")
            elif status.is_safe:
                banner.setText(f"{kind_label}: SAFE")
            else:
                banner.setText(f"{kind_label}: UNSAFE — " + "; ".join(status.violations))

        def _record_reading(readings: dict) -> None:
            if device_type != "weather":
                return
            history = self._weather_history_by_observatory.setdefault(self._safety_observatory_key(), [])
            history.append((time.time(), dict(readings)))
            if len(history) > _HISTORY_MAX_SAMPLES:
                del history[: len(history) - _HISTORY_MAX_SAMPLES]

        def _read_adapter(adapter) -> dict:
            """Poll *adapter* once and return its readings; raises if the device can't be read."""
            import asyncio
            from galileo.core.devices import WeatherController
            if device_type == "safety_monitor":
                asyncio.run(adapter.poll())
                return {"is_safe": 1.0 if adapter.is_safe else 0.0}
            controller = WeatherController(adapter)
            asyncio.run(controller.poll())
            return controller.get_readings()

        def _poll_once() -> dict | None:
            """Poll the connected adapter, update this tab's display, and
            record the reading into this Observatory's trend history."""
            adapter = state.get("adapter")
            if adapter is None:
                return None
            try:
                readings = _read_adapter(adapter)
            except Exception:
                logger.exception("Could not poll %s", kind_label.lower())
                return None
            state["read_at"] = time.monotonic()
            _apply_readings(readings)
            _record_reading(readings)
            return readings

        def _evaluate_one() -> tuple[bool, list[str]]:
            """``(connected, violations)`` for this tab's device, judged on a reading no older
            than the poll interval. The tab only polls itself while it is on screen, but the
            scheduler and the dome ask at any time, so a stale reading is refreshed here first.
            A connected device that can't be read counts as unsafe."""
            from galileo.safety import evaluate_weather_safety
            if state.get("adapter") is None:
                return False, []
            read_at = state.get("read_at")
            if read_at is not None and time.monotonic() - read_at < poll_spin.value():
                readings = state.get("latest_readings", {})
            else:
                readings = _poll_once()
            if readings is None:
                return True, [f"{kind_label} could not be read"]
            rules = [r for r in _current_rules() if r.safety_related]
            return True, evaluate_weather_safety(readings, rules).violations

        def _refresh_display() -> None:
            if state.get("adapter") is not None:
                _poll_once()
            else:
                _apply_readings({})

        # --- connection: connect / scan ------------------------------------
        def _do_connect(device_name: str) -> None:
            adapter = self._connect_device_adapter(
                category_enum, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to {kind_label} {device_name!r} — see log.", 6000)
                return
            state["adapter"] = adapter
            state["read_at"] = None
            adapters_by_observatory[self._safety_observatory_key()] = adapter
            _sync_connect_button()
            self._window.statusBar().showMessage(f"Connected to {kind_label} {device_name!r}.", 4000)
            _device_picked()
            _poll_once()

        def _sync_connect_button() -> None:
            connect_btn.setText("Disconnect" if state.get("adapter") is not None else "Connect")

        def _connect_clicked() -> None:
            if state.get("adapter") is not None:
                disconnect_page()
                return
            device_name = device_combo.currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", f"Select a {kind_label.lower()} device first.")
                return
            _do_connect(device_name)

        connect_btn.clicked.connect(_connect_clicked)

        def _device_picked() -> None:
            apply_driver_info(self._lookup_driver_info(
                category_enum, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip(),
            ))

        device_combo.activated.connect(lambda _index: _device_picked())

        def run_scan() -> None:
            server = server_edit.text().strip() or "localhost"
            port = port_spin.value()
            driver = driver_combo.currentText()
            devices: list[str] = []
            try:
                import asyncio
                if driver == "INDI":
                    from galileo.adapters.indi import get_adapter_class
                else:
                    from galileo.adapters.alpaca import get_adapter_class
                adapter = get_adapter_class(category_enum)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(category_enum))
            except Exception:
                logger.exception("%s scan failed on %s:%s", kind_label, server, port)
                self._window.statusBar().showMessage(f"{kind_label} scan failed — see log.", 6000)
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
                    "Detected %d %s %s device(s) at %s:%s: %s",
                    len(devices), driver, kind_label.lower(), server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} {kind_label.lower()} device(s) — see log.", 4000)
            else:
                logger.info("No %s %s devices found at %s:%s.", driver, kind_label.lower(), server, port)
                self._window.statusBar().showMessage(f"No {driver} {kind_label.lower()} devices found at {server}:{port}.", 4000)

        scan_btn.clicked.connect(run_scan)

        def _poll_interval_changed(value: int) -> None:
            status_timer.setInterval(value * 1000)

        poll_spin.valueChanged.connect(_poll_interval_changed)

        # --- footer: Save + Log ---------------------------------------------
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        save_btn.setToolTip("Save this device's settings and safety rules under the selected Observatory (shared by all its Piers).")
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        layout.addWidget(log_heading)
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)
        layout.addWidget(log_pane)

        def save_weather_config() -> None:
            observatory = self._safety_observatory()
            if observatory is None:
                QMessageBox.warning(
                    self._window, "No Observatory selected",
                    "Select (or create) an Observatory before saving safety device settings.",
                )
                return
            from galileo.observatory import save_safety_device_config, save_weather_safety_rule
            save_safety_device_config(
                observatory, device_type, slot=slot,
                driver=driver_combo.currentText(), server=server_edit.text().strip(),
                port=port_spin.value(), device_name=device_combo.currentText().strip() or None,
            )
            for rule in _current_rules():
                save_weather_safety_rule(observatory, rule, slot=slot)
            logger.info(
                "Saved %s settings for Observatory %r: %s %s:%s, device: %s, poll interval: %ds",
                kind_label.lower(), observatory.name, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip() or "(none)", poll_spin.value(),
            )
            self._window.statusBar().showMessage(
                f"Saved {kind_label.lower()} settings for Observatory {observatory.name!r}.", 4000
            )

        save_btn.clicked.connect(save_weather_config)

        def reload_page() -> None:
            cfg = None
            rules = []
            observatory = self._safety_observatory()
            if observatory is not None:
                from galileo.observatory import get_safety_device_config, get_weather_safety_rules
                try:
                    cfg = get_safety_device_config(observatory, device_type, slot=slot)
                    rules = get_weather_safety_rules(observatory, slot=slot)
                except Exception:
                    logger.exception("Could not load saved %s config", kind_label.lower())

            if not rules and observatory is not None:
                rules = _default_safety_rules(device_type)
            rules_by_parameter = {rule.parameter: rule for rule in rules}

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

            for parameter, widgets in row_widgets.items():
                rule = rules_by_parameter.get(parameter)
                widgets["safety"].blockSignals(True)
                widgets["operator"].blockSignals(True)
                widgets["threshold"].blockSignals(True)
                widgets["safety"].setChecked(bool(rule and rule.safety_related))
                if rule is not None:
                    idx = widgets["operator"].findText(rule.operator)
                    if idx >= 0:
                        widgets["operator"].setCurrentIndex(idx)
                    widgets["threshold"].setValue(rule.threshold)
                widgets["operator"].setEnabled(widgets["safety"].isChecked())
                widgets["threshold"].setEnabled(widgets["safety"].isChecked())
                widgets["safety"].blockSignals(False)
                widgets["operator"].blockSignals(False)
                widgets["threshold"].blockSignals(False)

            apply_driver_info(None)  # refilled on connect / device pick

            state["adapter"] = adapters_by_observatory.get(self._safety_observatory_key())
            _sync_connect_button()
            _refresh_display()

        def autoconnect_page() -> None:
            device_name = device_combo.currentText().strip()
            if device_name and adapters_by_observatory.get(self._safety_observatory_key()) is None:
                _do_connect(device_name)

        def disconnect_page() -> None:
            """Tear down this Observatory's connection to the device (shared by all its Piers)."""
            adapter = adapters_by_observatory.pop(self._safety_observatory_key(), None)
            if adapter is None:
                return
            import asyncio
            try:
                asyncio.run(adapter.disconnect())
            except Exception:
                logger.exception("Could not disconnect %s", kind_label)
            state["adapter"] = None
            state["read_at"] = None
            _apply_readings({})
            _sync_connect_button()
            self._window.statusBar().showMessage(f"{kind_label} disconnected.", 4000)

        from PySide6.QtCore import QTimer
        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _refresh_display))
        status_timer.start(poll_spin.value() * 1000)

        api = {
            "reload": reload_page, "autoconnect": autoconnect_page, "disconnect": disconnect_page,
            "connected": lambda: state.get("adapter") is not None,
            "poll_once": _poll_once,
            "evaluate_one": _evaluate_one,
            "get_rules": _current_rules,
            "get_latest_readings": lambda: state.get("latest_readings", {}),
            "device_type": device_type, "slot": slot,
        }
        reload_page()
        if self._startup_autoconnect_allowed():
            autoconnect_page()

        return page, api

    def _build_weather_page(self: AppWindowState) -> QWidget:
        """Equipment > Safety page: a tab per safety device (the first is the
        Observatory's weather station, shared by all its Piers), and a "+" button that adds another — a
        further weather station or a Safety Monitor — in a new tab. The dome
        is unsafe to open when any connected device breaks a rule marked
        "Blocks Dome Opening" on its tab."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QPushButton, QMenu, QMessageBox, QTabBar,
        )

        page = QWidget()
        page.setObjectName("WeatherPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        header = QHBoxLayout()
        heading = QLabel("Safety")
        heading.setObjectName("PageTitle")
        header.addWidget(heading)
        header.addStretch(1)
        add_btn = QPushButton("+")
        add_btn.setToolTip("Add a safety device (weather station or safety monitor) in a new tab")
        add_btn.setObjectName("AccentButton")
        add_btn.setProperty("helpKey", "add safety device")
        add_btn.setFixedWidth(28)
        header.addWidget(add_btn)
        layout.addLayout(header)

        tabs = QTabWidget()
        tabs.setTabsClosable(True)
        layout.addWidget(tabs, 1)

        panels: list[dict] = []  # api dicts, parallel to tabs

        def _add_panel(device_type: str, slot: str) -> None:
            widget, api = self._build_safety_device_panel(device_type, slot)
            api["widget"] = widget
            panels.append(api)
            index = tabs.addTab(widget, _SAFETY_DEVICE_TYPES[device_type][0])
            if slot == "primary":  # the Observatory's own weather station can't be closed
                tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
            tabs.setCurrentIndex(index)

        def _next_slot(device_type: str) -> str:
            used = {panel["slot"] for panel in panels}
            n = 2
            while f"{device_type}_{n}" in used:
                n += 1
            return f"{device_type}_{n}"

        add_menu = QMenu(add_btn)
        for type_id, (label, _drivers) in _SAFETY_DEVICE_TYPES.items():
            add_menu.addAction(label).triggered.connect(
                lambda _checked=False, type_id=type_id: _add_panel(type_id, _next_slot(type_id))
            )
        # Popped up on click rather than via setMenu(): a menu button reserves
        # room for a drop-down arrow, which squeezes the "+" out of a 28px button.
        add_btn.clicked.connect(lambda: add_menu.exec(add_btn.mapToGlobal(add_btn.rect().bottomLeft())))

        def _close_tab(index: int) -> None:
            if not 0 <= index < len(panels):
                return
            api = panels[index]
            if api["slot"] == "primary":
                return
            if QMessageBox.question(
                self._window, "Remove safety device", "Remove this device and its saved settings?",
            ) != QMessageBox.StandardButton.Yes:
                return
            api["disconnect"]()
            observatory = self._safety_observatory()
            if observatory is not None:
                from galileo.observatory import delete_safety_device_config, delete_weather_safety_rules
                delete_safety_device_config(observatory, api["device_type"], slot=api["slot"])
                delete_weather_safety_rules(observatory, api["slot"])
            panels.pop(index)
            tabs.removeTab(index)
            api["widget"].deleteLater()

        tabs.tabCloseRequested.connect(_close_tab)

        def _saved_extra_slots() -> list[tuple[str, str]]:
            observatory = self._safety_observatory()
            if observatory is None:
                return []
            from galileo.observatory import list_safety_device_slots
            extra = []
            for type_id in _SAFETY_DEVICE_TYPES:
                try:
                    slots = list_safety_device_slots(observatory, type_id)
                except Exception:
                    logger.exception("Could not list saved %s devices", type_id)
                    continue
                extra += [(type_id, s) for s in slots if s != "primary"]
            return extra

        loaded: dict = {"built": False, "key": None}

        def reload_page() -> None:
            # Safety devices belong to the Observatory, so selecting another Pier of the same
            # Observatory changes nothing here — the tabs, their connections and any unsaved
            # edits stay as they are. Only another Observatory rebuilds the page.
            key = self._safety_observatory_key()
            if loaded["built"] and loaded["key"] == key:
                return
            loaded["built"], loaded["key"] = True, key
            # Rebuild the extra tabs from what the selected Observatory has saved;
            # the primary weather tab is permanent and just reloads.
            for api in panels[1:]:
                api["widget"].deleteLater()
            for index in range(tabs.count() - 1, 0, -1):
                tabs.removeTab(index)
            del panels[1:]
            for type_id, slot in _saved_extra_slots():
                _add_panel(type_id, slot)
            tabs.setCurrentIndex(0)
            panels[0]["reload"]()

        def autoconnect_page() -> None:
            for api in panels:
                api["autoconnect"]()

        def disconnect_page() -> None:
            for api in panels:
                api["disconnect"]()

        def evaluate() -> tuple[bool, bool, list[str]]:
            """``(any device connected, safe, reasons it is not)`` across every tab — one verdict
            for the whole Observatory, whichever Pier asks. Readings are refreshed when stale."""
            connected = False
            violations: list[str] = []
            for api in panels:
                is_connected, found = api["evaluate_one"]()
                connected = connected or is_connected
                violations += found
            return connected, not violations, violations

        _add_panel("weather", "primary")

        primary = panels[0]
        self._device_pages["weather"] = {
            "reload": reload_page, "autoconnect": autoconnect_page, "disconnect": disconnect_page,
            "connected": lambda: any(api["connected"]() for api in panels),
            "evaluate": evaluate,
            # Not a Pier's devices: the top-bar Pier Connect/Disconnect leave these alone, since
            # tearing them down would blind every other Pier of the Observatory.
            "observatory_scoped": True,
            # The first tab's accessors, kept for callers that predate tabs.
            "poll_once": primary["poll_once"],
            "get_rules": primary["get_rules"],
            "get_latest_readings": primary["get_latest_readings"],
        }
        reload_page()

        return page
