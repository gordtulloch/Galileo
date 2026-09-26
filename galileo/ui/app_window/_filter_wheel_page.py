# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Filter Wheel device-category page."""

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


class AppWindowFilterWheelPageMixin:
    def _build_filter_wheel_page(self: AppWindowState) -> QWidget:
        """Filter Wheel device-category page: a live status display
        (Name/Description/Driver info/version — EQP-FW-010/020) plus a
        current-filter selector with an explicit Change action, and a
        Filters list showing every filter the wheel reports with the
        current one highlighted, matching the reference Filter
        Wheel layout (assets/samples/wheel.png) laid out with this app's
        own Driver/Server/Port/Scan connection convention rather than its
        icon toolbar."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame,
            QLabel, QTableWidget, QComboBox, QLineEdit, QSpinBox,
            QPushButton, QHeaderView, QMessageBox, QListWidget, QListWidgetItem,
        )
        from PySide6.QtCore import QTimer

        page = QWidget()
        page.setObjectName("FilterWheelPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Filter Wheel")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        # --- connection row --------------------------------------------
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

        # --- status (left) + filters list (right) ------------------------
        main_row = QHBoxLayout()
        main_row.setSpacing(24)

        left_col = QVBoxLayout()

        status_frame = QFrame()
        status_frame.setObjectName("DeviceSlotPanel")
        status_form = QFormLayout(status_frame)

        name_value = QLabel("—")
        name_value.setWordWrap(True)
        status_form.addRow("Name", name_value)
        description_value = QLabel("—")
        description_value.setWordWrap(True)
        status_form.addRow("Description", description_value)

        driver_row = QHBoxLayout()
        driver_info_form = QFormLayout()
        driver_info_value = QLabel("—")
        driver_info_form.addRow("Driver info", driver_info_value)
        driver_row.addLayout(driver_info_form)
        driver_version_form = QFormLayout()
        driver_version_value = QLabel("—")
        driver_version_form.addRow("Driver version", driver_version_value)
        driver_row.addLayout(driver_version_form)
        status_form.addRow(driver_row)

        left_col.addWidget(status_frame)

        current_row = QHBoxLayout()
        filter_combo = QComboBox()
        current_row.addWidget(filter_combo, 1)
        change_btn = QPushButton("Change")
        change_btn.setObjectName("AccentButton")
        current_row.addWidget(change_btn, 3)
        left_col.addLayout(current_row)

        left_col.addStretch(1)
        main_row.addLayout(left_col, 1)

        right_col = QVBoxLayout()
        filters_heading = QLabel("Filters")
        filters_heading.setObjectName("PageTitle")
        right_col.addWidget(filters_heading)
        filters_list_heading = QLabel("Filter name")
        filters_list_heading.setObjectName("CriteriaHeading")
        right_col.addWidget(filters_list_heading)
        filters_list = QListWidget()
        right_col.addWidget(filters_list, 1)
        main_row.addLayout(right_col, 1)

        layout.addLayout(main_row, 1)

        settings_heading = QLabel("Settings")
        settings_heading.setObjectName("CriteriaHeading")
        layout.addWidget(settings_heading)
        layout.addWidget(QLabel("None"))

        state: dict = {"adapter": None}

        def _apply_status(status: dict) -> None:
            name_value.setText(status.get("name") or "—")
            description_value.setText(status.get("description") or "—")
            driver_info_value.setText(status.get("driver_info") or "—")
            driver_version_value.setText(status.get("driver_version") or "—")
            names = status.get("filter_names") or []
            position = status.get("position")

            current = filter_combo.currentText()
            filter_combo.blockSignals(True)
            filter_combo.clear()
            filter_combo.addItems(names)
            if position is not None and 0 <= position < len(names):
                filter_combo.setCurrentIndex(position)
            elif current and filter_combo.findText(current) >= 0:
                filter_combo.setCurrentText(current)
            filter_combo.blockSignals(False)

            filters_list.clear()
            for i, filter_name in enumerate(names):
                item = QListWidgetItem(filter_name)
                filters_list.addItem(item)
                if i == position:
                    filters_list.setCurrentItem(item)

        def _refresh_status() -> dict | None:
            adapter = state.get("adapter")
            if adapter is None:
                return None
            import asyncio
            try:
                status = asyncio.run(adapter.get_status())
            except Exception:
                logger.exception("Could not refresh filter wheel status")
                return None
            _apply_status(status)
            return status

        def _do_connect(device_name: str) -> None:
            from galileo.core.devices import DeviceCategory
            adapter = self._connect_device_adapter(
                DeviceCategory.FILTER_WHEEL, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to Filter Wheel {device_name!r} — see log.", 6000)
                return
            state["adapter"] = adapter
            self._window.statusBar().showMessage(f"Connected to Filter Wheel {device_name!r}.", 4000)
            _refresh_status()

        def _connect_clicked() -> None:
            device_name = device_combo.currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a filter wheel device first.")
                return
            _do_connect(device_name)

        connect_btn.clicked.connect(_connect_clicked)

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
                    adapter = get_adapter_class(DeviceCategory.FILTER_WHEEL)(host=server, port=port)
                else:
                    from galileo.adapters.alpaca import get_adapter_class
                    adapter = get_adapter_class(DeviceCategory.FILTER_WHEEL)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.FILTER_WHEEL))
            except Exception:
                logger.exception("Filter wheel scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Filter wheel scan failed — see log.", 6000)
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
                    "Detected %d %s filter wheel device(s) at %s:%s: %s",
                    len(devices), driver, server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} filter wheel device(s) — see log.", 4000)
            else:
                logger.info("No %s filter wheel devices found at %s:%s.", driver, server, port)
                self._window.statusBar().showMessage(f"No {driver} filter wheel devices found at {server}:{port}.", 4000)

        scan_btn.clicked.connect(run_scan)

        def _filters_list_clicked(item: QListWidgetItem) -> None:
            idx = filters_list.row(item)
            if idx < 0:
                return
            filter_combo.setCurrentIndex(idx)

        filters_list.itemClicked.connect(_filters_list_clicked)

        def _change_clicked() -> None:
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the filter wheel first.")
                return
            index = filter_combo.currentIndex()
            if index < 0:
                return
            filter_name = filter_combo.currentText()
            import asyncio
            try:
                asyncio.run(adapter.move_to(index))
            except Exception:
                logger.exception("Filter wheel move_to failed (index=%s)", index)
                self._window.statusBar().showMessage("Filter change failed — see log.", 6000)
                return
            logger.info("Filter wheel: changed to %r (#%d)", filter_name, index)
            _refresh_status()

        change_btn.clicked.connect(_change_clicked)

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

        def save_filter_wheel_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_device_config
            save_device_config(
                self._current_pier, "filter_wheel",
                driver=driver_combo.currentText(), server=server_edit.text().strip(),
                port=port_spin.value(), device_name=device_combo.currentText().strip() or None,
            )
            logger.info(
                "Saved filter wheel settings for Pier %r: %s %s:%s, device: %s",
                self._current_pier.name, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip() or "(none)",
            )
            self._window.statusBar().showMessage(
                f"Saved filter wheel settings for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_filter_wheel_config)

        def reload_page() -> None:
            cfg = None
            if self._current_pier is not None:
                from galileo.observatory import get_device_config
                try:
                    cfg = get_device_config(self._current_pier, "filter_wheel")
                except Exception:
                    logger.exception("Could not load saved filter wheel config")

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
            state["adapter"] = None
            _apply_status({})

        def autoconnect_page() -> None:
            device_name = device_combo.currentText().strip()
            if device_name:
                _do_connect(device_name)

        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _refresh_status))
        status_timer.start(2000)

        state["reload"] = reload_page
        state["autoconnect"] = autoconnect_page
        self._device_pages["filter_wheel"] = state
        reload_page()
        autoconnect_page()

        return page
