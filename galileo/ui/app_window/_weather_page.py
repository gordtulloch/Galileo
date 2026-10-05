# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Weather device-category page (EQP-WX-010, EQP-WX-020)."""

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

# How long a Pier's weather-reading trend history is kept for the Safety
# Monitor screen's graphs (EQP-SAFE-020) — capped by count, not wall-clock
# time, since the poll interval is itself user-configurable.
_HISTORY_MAX_SAMPLES = 1000


class AppWindowWeatherPageMixin:
    def _build_weather_page(self: AppWindowState) -> QWidget:
        """Weather device-category page: the usual Driver/Server/Port/Scan +
        Device/Connect connection row, a live readings table, and — per
        reading — whether it counts toward safety and what crossing it means
        (EQP-WX-020, e.g. Rain is YES, Wind Speed >= 20 km/h). This
        evaluation is advisory/display-only: it never drives an automated
        abort itself (only a connected Safety Monitor device is authoritative
        for that, EQP-SAFE-010) — the readings marked safety-related here,
        and their trend over time, are instead surfaced read-only on the
        Equipment > Safety Monitor screen (EQP-SAFE-020)."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout,
            QLabel, QTableWidget, QTableWidgetItem, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox,
            QPushButton, QHeaderView, QMessageBox, QCheckBox, QAbstractItemView,
        )
        from PySide6.QtCore import Qt
        from galileo.safety import UNSAFE_OPERATORS, WEATHER_PARAMETER_INFO

        page = QWidget()
        page.setObjectName("WeatherPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Weather")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        subtitle = QLabel(
            "Connect a Weather Station device (e.g. an INDI ADS-WS1 or RG-11 rain sensor, or an "
            "Alpaca ObservingConditions device) and mark which readings count toward safety."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

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
        driver_combo.addItems(["Alpaca", "INDI"])
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
        layout.addWidget(banner)

        # --- readings + per-measure safety rules --------------------------
        parameters = list(WEATHER_PARAMETER_INFO.keys())
        rules_table = QTableWidget(len(parameters), 5)
        rules_table.setHorizontalHeaderLabels(["Measure", "Current", "Safety-Related", "Unsafe When", "Threshold"])
        rules_table.verticalHeader().setVisible(False)
        rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        rules_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = rules_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        row_widgets: dict[str, dict] = {}
        for row, parameter in enumerate(parameters):
            label, unit = WEATHER_PARAMETER_INFO[parameter]
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

        state: dict = {"adapter": None, "latest_readings": {}}
        adapters_by_pier: dict = {}

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
                banner.setText("Weather: SAFE (advisory only — see Safety Monitor for the authoritative state)")
            else:
                banner.setText("Weather: UNSAFE — " + "; ".join(status.violations))

        def _record_reading(readings: dict) -> None:
            from galileo.current_object import pier_key
            key = pier_key(self._current_pier)
            history = self._weather_history_by_pier.setdefault(key, [])
            history.append((time.time(), dict(readings)))
            if len(history) > _HISTORY_MAX_SAMPLES:
                del history[: len(history) - _HISTORY_MAX_SAMPLES]

        def _poll_once() -> dict | None:
            """Poll the connected adapter, update this page's display, and
            record the reading into this Pier's trend history — called by
            this page's own timer, and by the Safety Monitor page's timer
            when *it* is the one on screen (see _device_pages["weather"])."""
            adapter = state.get("adapter")
            if adapter is None:
                return None
            import asyncio
            from galileo.core.devices import WeatherController
            try:
                controller = WeatherController(adapter)
                asyncio.run(controller.poll())
                readings = controller.get_readings()
            except Exception:
                logger.exception("Could not poll weather station")
                return None
            _apply_readings(readings)
            _record_reading(readings)
            return readings

        def _refresh_display() -> None:
            if state.get("adapter") is not None:
                _poll_once()
            else:
                _apply_readings({})

        # --- connection: connect / scan ------------------------------------
        def _do_connect(device_name: str) -> None:
            from galileo.core.devices import DeviceCategory
            adapter = self._connect_device_adapter(
                DeviceCategory.WEATHER_STATION, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to Weather station {device_name!r} — see log.", 6000)
                return
            from galileo.current_object import pier_key
            state["adapter"] = adapter
            adapters_by_pier[pier_key(self._current_pier)] = adapter
            self._window.statusBar().showMessage(f"Connected to Weather station {device_name!r}.", 4000)
            _poll_once()

        def _connect_clicked() -> None:
            device_name = device_combo.currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a weather station device first.")
                return
            _do_connect(device_name)

        connect_btn.clicked.connect(_connect_clicked)

        def _device_picked() -> None:
            from galileo.core.devices import DeviceCategory
            apply_driver_info(self._lookup_driver_info(
                DeviceCategory.WEATHER_STATION, driver_combo.currentText(), server_edit.text().strip(),
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
                adapter = get_adapter_class(DeviceCategory.WEATHER_STATION)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.WEATHER_STATION))
            except Exception:
                logger.exception("Weather station scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Weather station scan failed — see log.", 6000)
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
                    "Detected %d %s weather device(s) at %s:%s: %s",
                    len(devices), driver, server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} weather device(s) — see log.", 4000)
            else:
                logger.info("No %s weather devices found at %s:%s.", driver, server, port)
                self._window.statusBar().showMessage(f"No {driver} weather devices found at {server}:{port}.", 4000)

        scan_btn.clicked.connect(run_scan)

        def _poll_interval_changed(value: int) -> None:
            status_timer.setInterval(value * 1000)

        poll_spin.valueChanged.connect(_poll_interval_changed)

        # --- footer: Save + Log ---------------------------------------------
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        save_btn.setToolTip("Save this device's settings and safety rules under the selected Observatory and Pier.")
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        layout.addWidget(log_heading)
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)
        layout.addWidget(log_pane)

        def save_weather_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_device_config, save_weather_safety_rule
            save_device_config(
                self._current_pier, "weather",
                driver=driver_combo.currentText(), server=server_edit.text().strip(),
                port=port_spin.value(), device_name=device_combo.currentText().strip() or None,
            )
            for rule in _current_rules():
                save_weather_safety_rule(self._current_pier, rule)
            logger.info(
                "Saved weather settings for Pier %r: %s %s:%s, device: %s, poll interval: %ds",
                self._current_pier.name, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip() or "(none)", poll_spin.value(),
            )
            self._window.statusBar().showMessage(
                f"Saved weather settings for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_weather_config)

        def reload_page() -> None:
            cfg = None
            rules = []
            if self._current_pier is not None:
                from galileo.observatory import get_device_config, get_weather_safety_rules
                try:
                    cfg = get_device_config(self._current_pier, "weather")
                    rules = get_weather_safety_rules(self._current_pier)
                except Exception:
                    logger.exception("Could not load saved weather config")

            if not rules and self._current_pier is not None:
                from galileo.safety import default_weather_safety_rules
                rules = default_weather_safety_rules()
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

            from galileo.current_object import pier_key
            adapter = adapters_by_pier.get(pier_key(self._current_pier))
            state["adapter"] = adapter
            _refresh_display()

        def autoconnect_page() -> None:
            from galileo.current_object import pier_key
            device_name = device_combo.currentText().strip()
            if device_name and adapters_by_pier.get(pier_key(self._current_pier)) is None:
                _do_connect(device_name)

        def disconnect_page() -> None:
            """Pier-level Disconnect button: tear down this Pier's weather connection."""
            from galileo.current_object import pier_key
            adapter = adapters_by_pier.pop(pier_key(self._current_pier), None)
            if adapter is None:
                return
            import asyncio
            try:
                asyncio.run(adapter.disconnect())
            except Exception:
                logger.exception("Could not disconnect Weather station")
            state["adapter"] = None
            _apply_readings({})
            self._window.statusBar().showMessage("Weather station disconnected.", 4000)

        from PySide6.QtCore import QTimer
        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _refresh_display))
        status_timer.start(poll_spin.value() * 1000)

        self._device_pages["weather"] = {
            "reload": reload_page, "autoconnect": autoconnect_page, "disconnect": disconnect_page,
            "connected": lambda: state.get("adapter") is not None,
            # Read-only accessors the Safety Monitor page uses (EQP-SAFE-020)
            # to surface the safety-related subset of these readings, and
            # their trend, without owning a second connection to the device.
            "poll_once": _poll_once,
            "get_rules": _current_rules,
            "get_latest_readings": lambda: state.get("latest_readings", {}),
        }
        reload_page()
        if self._startup_autoconnect_allowed():
            autoconnect_page()

        return page
