# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Safety Monitor device-category page (EQP-SAFE-010, EQP-SAFE-020)."""

from __future__ import annotations

from typing import TYPE_CHECKING

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

_SAFE_COLOR = "#2ecc71"
_UNSAFE_COLOR = "#e74c3c"
_UNKNOWN_COLOR = "#888888"


class AppWindowSafetyMonitorPageMixin:
    def _build_safety_monitor_page(self: AppWindowState) -> QWidget:
        """Safety Monitor device-category page: the connected Safety Monitor
        device's own SAFE/NOT-SAFE state and explanation (EQP-SAFE-010,
        authoritative for SAFE-010 — see galileo.safety's trust-tier note),
        plus — broken out separately, read-only — the subset of the
        connected Weather Station's readings marked safety-related on the
        Equipment > Weather screen (EQP-WX-020), each with its current value
        and verdict, and a trend graph of recent readings (e.g. wind speed,
        temperature, dew point) so the user can see a developing unsafe
        condition coming rather than just a final Yes/No (EQP-SAFE-020).
        This weather-derived section is advisory/display-only, same trust
        tier as the Weather screen's own banner — it never drives an
        automated abort; only the Safety Monitor device above does."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame,
            QLabel, QTableWidget, QTableWidgetItem, QComboBox, QLineEdit, QSpinBox,
            QPushButton, QHeaderView, QMessageBox, QAbstractItemView,
        )
        from PySide6.QtCore import QTimer

        page = QWidget()
        page.setObjectName("SafetyMonitorPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Safety Monitor")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

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
        server_edit.setPlaceholderText("FQDN or IP, e.g. safety.local or 192.168.1.61")
        server_edit.setMaxLength(40)
        table.setCellWidget(0, 1, server_edit)

        port_spin = QSpinBox()
        port_spin.setRange(1, 65535)
        port_spin.setValue(_DEFAULT_PORTS["Alpaca"])

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

        # --- live status: the device's own SAFE/NOT-SAFE (EQP-SAFE-010) ---
        status_frame = QFrame()
        status_frame.setObjectName("DeviceSlotPanel")
        status_form = QFormLayout(status_frame)
        status_value = QLabel("—")
        status_form.addRow("Status", status_value)
        explanation_value = QLabel("—")
        explanation_value.setWordWrap(True)
        status_form.addRow("Explanation", explanation_value)
        layout.addWidget(status_frame)

        # --- weather-derived safety measures, read-only (EQP-SAFE-020) ----
        measures_heading = QLabel("Weather Safety Measures")
        measures_heading.setObjectName("CriteriaHeading")
        layout.addWidget(measures_heading)
        measures_hint = QLabel(
            "Readings marked safety-related on the Equipment > Weather screen. Advisory "
            "only — the Status above is what actually gates an automated abort."
        )
        measures_hint.setWordWrap(True)
        layout.addWidget(measures_hint)

        measures_table = QTableWidget(0, 4)
        measures_table.setHorizontalHeaderLabels(["Measure", "Current", "Unsafe When", "Verdict"])
        measures_table.verticalHeader().setVisible(False)
        measures_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        measures_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        mheader = measures_table.horizontalHeader()
        mheader.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            mheader.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        measures_table.setMaximumHeight(200)
        layout.addWidget(measures_table)

        # --- trend graph (EQP-SAFE-020) -------------------------------------
        trend_row = QHBoxLayout()
        trend_row.addWidget(QLabel("Trend"))
        trend_combo = QComboBox()
        trend_row.addWidget(trend_combo, 1)
        layout.addLayout(trend_row)

        chart_view, update_chart = self._build_weather_trend_chart()
        layout.addWidget(chart_view, 1)

        def _current_weather_snapshot() -> tuple[dict, list, list]:
            """``(latest_readings, safety_related_rules, history)`` from the
            Weather page (EQP-SAFE-020) — empty if no Weather device has ever
            been built/connected for this Pier."""
            weather_state = self._device_pages.get("weather")
            if not weather_state:
                return {}, [], []
            poll_once = weather_state.get("poll_once")
            if poll_once is not None:
                poll_once()  # keep history fresh while this page is the one on screen
            get_rules = weather_state.get("get_rules")
            get_readings = weather_state.get("get_latest_readings")
            rules = [r for r in (get_rules() if get_rules else []) if r.safety_related]
            readings = get_readings() if get_readings else {}
            from galileo.current_object import pier_key
            history = self._weather_history_by_pier.get(pier_key(self._current_pier), [])
            return readings, rules, history

        def _refresh_measures() -> None:
            readings, rules, history = _current_weather_snapshot()

            measures_table.setRowCount(len(rules))
            for row, rule in enumerate(rules):
                measures_table.setItem(row, 0, QTableWidgetItem(rule.label))
                value = readings.get(rule.parameter)
                if value is None:
                    text = "—"
                elif rule.unit == "bool":
                    text = "Yes" if value else "No"
                else:
                    text = f"{value:.1f} {rule.unit}".strip()
                measures_table.setItem(row, 1, QTableWidgetItem(text))
                measures_table.setItem(row, 2, QTableWidgetItem(f"{rule.operator} {rule.threshold:g}"))
                verdict_item = QTableWidgetItem("—")
                if value is not None:
                    from galileo.safety import evaluate_weather_safety
                    unsafe = not evaluate_weather_safety(readings, [rule]).is_safe
                    verdict_item.setText("UNSAFE" if unsafe else "SAFE")
                measures_table.setItem(row, 3, verdict_item)

            # Trend parameter choices follow whichever readings have ever
            # been seen in this Pier's history, so a driver lacking (say)
            # dew point never offers an always-empty chart for it.
            seen_parameters: list[str] = []
            for _timestamp, sample in history:
                for parameter in sample:
                    if sample.get(parameter) is not None and parameter not in seen_parameters:
                        seen_parameters.append(parameter)
            current_choice = trend_combo.currentText()
            trend_combo.blockSignals(True)
            trend_combo.clear()
            from galileo.safety import WEATHER_PARAMETER_INFO
            for parameter in seen_parameters:
                label, unit = WEATHER_PARAMETER_INFO.get(parameter, (parameter, ""))
                trend_combo.addItem(f"{label} ({unit})" if unit and unit != "bool" else label, parameter)
            if current_choice:
                idx = trend_combo.findText(current_choice)
                if idx >= 0:
                    trend_combo.setCurrentIndex(idx)
            trend_combo.blockSignals(False)

            selected_parameter = trend_combo.currentData()
            update_chart(history, selected_parameter)

        trend_combo.currentIndexChanged.connect(
            lambda _index: update_chart(_current_weather_snapshot()[2], trend_combo.currentData())
        )

        # --- device status / actions --------------------------------------
        state: dict = {"adapter": None}
        adapters_by_pier: dict = {}

        def _apply_status(status: dict) -> None:
            is_safe = status.get("is_safe")
            if is_safe is None:
                status_value.setText("—")
                status_value.setStyleSheet("")
            elif is_safe:
                status_value.setText("SAFE")
                status_value.setStyleSheet(f"color: {_SAFE_COLOR}; font-weight: bold;")
            else:
                status_value.setText("NOT SAFE")
                status_value.setStyleSheet(f"color: {_UNSAFE_COLOR}; font-weight: bold;")
            explanation_value.setText(status.get("explanation") or "—")

        def _refresh_status() -> None:
            adapter = state.get("adapter")
            if adapter is not None:
                import asyncio
                from galileo.core.devices import SafetyMonitorController
                try:
                    controller = SafetyMonitorController(adapter)
                    asyncio.run(controller.poll())
                    _apply_status({"is_safe": controller.is_safe, "explanation": controller.explanation})
                except Exception:
                    logger.exception("Could not poll safety monitor")
            else:
                _apply_status({})
            _refresh_measures()

        def _do_connect(device_name: str) -> None:
            from galileo.core.devices import DeviceCategory
            adapter = self._connect_device_adapter(
                DeviceCategory.SAFETY_MONITOR, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to Safety Monitor {device_name!r} — see log.", 6000)
                return
            from galileo.current_object import pier_key
            state["adapter"] = adapter
            adapters_by_pier[pier_key(self._current_pier)] = adapter
            self._window.statusBar().showMessage(f"Connected to Safety Monitor {device_name!r}.", 4000)
            _refresh_status()

        def _connect_clicked() -> None:
            device_name = device_combo.currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a safety monitor device first.")
                return
            _do_connect(device_name)

        connect_btn.clicked.connect(_connect_clicked)

        def _device_picked() -> None:
            from galileo.core.devices import DeviceCategory
            apply_driver_info(self._lookup_driver_info(
                DeviceCategory.SAFETY_MONITOR, driver_combo.currentText(), server_edit.text().strip(),
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
                adapter = get_adapter_class(DeviceCategory.SAFETY_MONITOR)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.SAFETY_MONITOR))
            except Exception:
                logger.exception("Safety monitor scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Safety monitor scan failed — see log.", 6000)
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
                    "Detected %d %s safety monitor device(s) at %s:%s: %s",
                    len(devices), driver, server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} device(s) — see log.", 4000)
            else:
                logger.info("No %s safety monitor devices found at %s:%s.", driver, server, port)
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

        def save_safety_monitor_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_device_config
            save_device_config(
                self._current_pier, "safety_monitor",
                driver=driver_combo.currentText(), server=server_edit.text().strip(),
                port=port_spin.value(), device_name=device_combo.currentText().strip() or None,
            )
            logger.info(
                "Saved safety monitor settings for Pier %r: %s %s:%s, device: %s",
                self._current_pier.name, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip() or "(none)",
            )
            self._window.statusBar().showMessage(
                f"Saved safety monitor settings for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_safety_monitor_config)

        def reload_page() -> None:
            cfg = None
            if self._current_pier is not None:
                from galileo.observatory import get_device_config
                try:
                    cfg = get_device_config(self._current_pier, "safety_monitor")
                except Exception:
                    logger.exception("Could not load saved safety monitor config")

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
            _refresh_status()

        def autoconnect_page() -> None:
            from galileo.current_object import pier_key
            device_name = device_combo.currentText().strip()
            if device_name and adapters_by_pier.get(pier_key(self._current_pier)) is None:
                _do_connect(device_name)

        def disconnect_page() -> None:
            """Pier-level Disconnect button: tear down this Pier's safety monitor connection."""
            from galileo.current_object import pier_key
            adapter = adapters_by_pier.pop(pier_key(self._current_pier), None)
            if adapter is None:
                return
            import asyncio
            try:
                asyncio.run(adapter.disconnect())
            except Exception:
                logger.exception("Could not disconnect Safety Monitor")
            state["adapter"] = None
            _apply_status({})
            self._window.statusBar().showMessage("Safety monitor disconnected.", 4000)

        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _refresh_status))
        status_timer.start(5000)

        self._device_pages["safety_monitor"] = {
            "reload": reload_page, "autoconnect": autoconnect_page, "disconnect": disconnect_page,
            "connected": lambda: state.get("adapter") is not None,
        }
        reload_page()
        if self._startup_autoconnect_allowed():
            autoconnect_page()

        return page

    @staticmethod
    def _build_weather_trend_chart() -> tuple:
        """One shared line-chart widget for the Safety Monitor screen's
        weather trend (EQP-SAFE-020). Returns ``(chart_view, update)`` where
        ``update(history, parameter)`` redraws it from a Pier's weather
        history (``[(unix timestamp, readings dict), ...]``) for one
        reading key — rebuilt on every call rather than incrementally
        appended to, since both the selected parameter and the underlying
        history can change between calls."""
        from PySide6.QtCharts import QChart, QChartView, QLineSeries, QDateTimeAxis, QValueAxis
        from PySide6.QtCore import Qt, QDateTime
        from PySide6.QtGui import QPainter

        chart = QChart()
        chart.legend().hide()
        chart_view = QChartView(chart)
        chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart_view.setMinimumHeight(220)

        def update(history: list, parameter: str | None) -> None:
            chart.removeAllSeries()
            for axis in list(chart.axes()):
                chart.removeAxis(axis)
            if not parameter:
                return
            series = QLineSeries()
            points = [
                (timestamp, sample.get(parameter)) for timestamp, sample in history
                if sample.get(parameter) is not None
            ]
            for timestamp, value in points:
                series.append(QDateTime.fromSecsSinceEpoch(int(timestamp)).toMSecsSinceEpoch(), float(value))
            chart.addSeries(series)

            axis_x = QDateTimeAxis()
            axis_x.setFormat("hh:mm")
            axis_x.setTitleText("Time")
            chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
            series.attachAxis(axis_x)

            axis_y = QValueAxis()
            chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
            series.attachAxis(axis_y)

        return chart_view, update
