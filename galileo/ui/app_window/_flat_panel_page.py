# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Flat Panel device-category page."""

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


class AppWindowFlatPanelPageMixin:
    def _build_flat_panel_page(self: AppWindowState) -> QWidget:
        """Flat Panel device-category page (EQP-FP-010): the usual
        Driver/Server/Port/Scan + Device/Connect connection row, a Panel Type
        choice (``"Flat Panel"``/``"Observatory Panel"``, the same two names
        the Imaging page's Flats Assistant uses for these sources —
        galileo.calibration.FLAT_METHODS) — a motorized dust-cap + light
        (Flat Panel) has cover Park/Unpark and light controls; a fixed,
        light-only panel built into the observatory (Observatory Panel) has
        no motorized cover, so Park/Unpark is hidden — then the panel's
        controls — cover Park/Unpark, light On/Off, and a 0-1000 brightness
        level — each with its own live status readout, and a log tail."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame,
            QLabel, QTableWidget, QComboBox, QLineEdit, QSpinBox,
            QPushButton, QHeaderView, QMessageBox, QSlider,
        )
        from PySide6.QtCore import QTimer, Qt

        page = QWidget()
        page.setObjectName("FlatPanelPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Flat Panel")
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

        # Panel Type: whether the panel has a motorized cover at all. These
        # two names match galileo.calibration.FLAT_METHODS (the Imaging
        # page's Flats Assistant source dropdown) for the same two panels.
        # "Flat Panel" (an Alnitak Flip-Flat-style motorized dust cap +
        # light) has one; "Observatory Panel" (a fixed panel built into the
        # observatory, light-only) doesn't, so its Park/Unpark controls are
        # hidden below.
        panel_type_row = QHBoxLayout()
        panel_type_row.addWidget(QLabel("Panel Type"))
        panel_type_combo = QComboBox()
        panel_type_combo.addItems(["Flat Panel", "Observatory Panel"])
        panel_type_combo.setToolTip(
            "Flat Panel: a motorized dust cap + light (cover Park/Unpark and light "
            "controls). Observatory Panel: a fixed, light-only panel with no "
            "motorized cover, so Park/Unpark is hidden."
        )
        panel_type_row.addWidget(panel_type_combo, 1)
        panel_type_row.addStretch(2)
        layout.addLayout(panel_type_row)

        driver_info_row, apply_driver_info = self._build_driver_info_row()
        layout.addLayout(driver_info_row)

        # --- live status: Cover / Light -----------------------------------
        status_frame = QFrame()
        status_frame.setObjectName("DeviceSlotPanel")
        status_form = QFormLayout(status_frame)
        cover_status_value = QLabel("—")
        status_form.addRow("Cover", cover_status_value)
        light_status_value = QLabel("—")
        status_form.addRow("Light", light_status_value)
        layout.addWidget(status_frame)

        def _heading(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("CriteriaHeading")
            return label

        # --- controls: Cover, Light, Brightness ---------------------------
        controls_frame = QFrame()
        controls_frame.setObjectName("DeviceSlotPanel")
        controls = QVBoxLayout(controls_frame)
        controls.setSpacing(6)

        cover_heading = _heading("Cover")
        controls.addWidget(cover_heading)
        cover_row = QHBoxLayout()
        park_btn = QPushButton("Park")
        unpark_btn = QPushButton("Unpark")
        unpark_btn.setObjectName("AccentButton")
        cover_row.addWidget(park_btn)
        cover_row.addWidget(unpark_btn)
        controls.addLayout(cover_row)

        controls.addWidget(_heading("Flat Light"))
        light_row = QHBoxLayout()
        light_off_btn = QPushButton("Light Off")
        light_on_btn = QPushButton("Light On")
        light_on_btn.setObjectName("AccentButton")
        light_row.addWidget(light_off_btn)
        light_row.addWidget(light_on_btn)
        controls.addLayout(light_row)

        controls.addWidget(_heading("Brightness"))
        brightness_row = QHBoxLayout()
        brightness_slider = QSlider(Qt.Orientation.Horizontal)
        brightness_slider.setRange(0, 1000)
        brightness_spin = QSpinBox()
        brightness_spin.setProperty("helpKey", "brightness")
        brightness_spin.setRange(0, 1000)
        brightness_set_btn = QPushButton("Set")
        brightness_set_btn.setObjectName("AccentButton")
        brightness_row.addWidget(brightness_slider, 1)
        brightness_row.addWidget(brightness_spin)
        brightness_row.addWidget(brightness_set_btn)
        controls.addLayout(brightness_row)
        brightness_slider.valueChanged.connect(brightness_spin.setValue)
        brightness_spin.valueChanged.connect(brightness_slider.setValue)

        layout.addWidget(controls_frame)
        layout.addStretch(1)

        state: dict = {"adapter": None, "panel_type": "Flat Panel"}
        adapters_by_pier: dict = {}
        device_controls = (
            park_btn, unpark_btn, light_off_btn, light_on_btn,
            brightness_slider, brightness_spin, brightness_set_btn,
        )

        def _apply_panel_type(panel_type: str) -> None:
            """Observatory panels have every control except the motorized
            cover (there isn't one) — hide Park/Unpark and its status row,
            keep light and brightness as-is."""
            state["panel_type"] = panel_type
            has_cover = panel_type != "Observatory Panel"
            cover_heading.setVisible(has_cover)
            park_btn.setVisible(has_cover)
            unpark_btn.setVisible(has_cover)
            status_form.setRowVisible(cover_status_value, has_cover)

        panel_type_combo.currentTextChanged.connect(_apply_panel_type)
        _apply_panel_type(panel_type_combo.currentText())

        # --- device status / actions --------------------------------------
        def _call(method: str, *args, action: str) -> bool:
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the flat panel first.")
                return False
            import asyncio
            try:
                asyncio.run(getattr(adapter, method)(*args))
            except Exception:
                logger.exception("Flat panel %s failed", action)
                self._window.statusBar().showMessage(f"Flat panel {action} failed — see log.", 6000)
                return False
            return True

        def _apply_status(status: dict) -> None:
            connected = bool(status)
            if connected:  # an empty status is "not connected": keep what a device pick looked up
                apply_driver_info(status)
            for widget in device_controls:
                widget.setEnabled(connected)
            cover_state = status.get("cover_state")
            cover_status_value.setText(
                "Parked" if cover_state == "Closed" else "Unparked" if cover_state == "Open" else "—"
            )
            light_on = status.get("is_light_on")
            light_status_value.setText("On" if light_on else "Off" if light_on is not None else "—")
            brightness = status.get("brightness")
            if brightness is not None and not brightness_slider.isSliderDown():
                brightness_slider.blockSignals(True)
                brightness_spin.blockSignals(True)
                brightness_slider.setValue(int(brightness))
                brightness_spin.setValue(int(brightness))
                brightness_slider.blockSignals(False)
                brightness_spin.blockSignals(False)

        def _refresh_status() -> dict | None:
            adapter = state.get("adapter")
            if adapter is None:
                return None
            import asyncio
            try:
                status = asyncio.run(adapter.get_status())
            except Exception:
                logger.exception("Could not refresh flat panel status")
                return None
            _apply_status(status)
            return status

        def _park_clicked() -> None:
            if _call("close_cover", action="park"):
                logger.info("Flat panel: cover parked")
                _refresh_status()

        def _unpark_clicked() -> None:
            if _call("open_cover", action="unpark"):
                logger.info("Flat panel: cover unparked")
                _refresh_status()

        def _light_on_clicked() -> None:
            if _call("light_on", action="light on"):
                logger.info("Flat panel: light on")
                _refresh_status()

        def _light_off_clicked() -> None:
            if _call("light_off", action="light off"):
                logger.info("Flat panel: light off")
                _refresh_status()

        def _brightness_set_clicked() -> None:
            level = brightness_spin.value()
            if _call("set_brightness", level, action="set brightness"):
                logger.info("Flat panel: brightness set to %d", level)
                _refresh_status()

        park_btn.clicked.connect(_park_clicked)
        unpark_btn.clicked.connect(_unpark_clicked)
        light_on_btn.clicked.connect(_light_on_clicked)
        light_off_btn.clicked.connect(_light_off_clicked)
        brightness_set_btn.clicked.connect(_brightness_set_clicked)

        # --- connection: connect / scan ------------------------------------
        def _do_connect(device_name: str) -> None:
            from galileo.core.devices import DeviceCategory
            adapter = self._connect_device_adapter(
                DeviceCategory.FLAT_PANEL, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to Flat Panel {device_name!r} — see log.", 6000)
                return
            from galileo.current_object import pier_key
            state["adapter"] = adapter
            adapters_by_pier[pier_key(self._current_pier)] = adapter
            self._window.statusBar().showMessage(f"Connected to Flat Panel {device_name!r}.", 4000)
            _refresh_status()

        def _connect_clicked() -> None:
            device_name = device_combo.currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a flat panel device first.")
                return
            _do_connect(device_name)

        connect_btn.clicked.connect(_connect_clicked)

        def _device_picked() -> None:
            """Show the driver of the device just picked, without connecting it."""
            from galileo.core.devices import DeviceCategory
            apply_driver_info(self._lookup_driver_info(
                DeviceCategory.FLAT_PANEL, driver_combo.currentText(), server_edit.text().strip(),
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
                adapter = get_adapter_class(DeviceCategory.FLAT_PANEL)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.FLAT_PANEL))
            except Exception:
                logger.exception("Flat panel scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Flat panel scan failed — see log.", 6000)
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
                    "Detected %d %s flat panel device(s) at %s:%s: %s",
                    len(devices), driver, server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} flat panel device(s) — see log.", 4000)
            else:
                logger.info("No %s flat panel devices found at %s:%s.", driver, server, port)
                self._window.statusBar().showMessage(f"No {driver} flat panel devices found at {server}:{port}.", 4000)

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

        def save_flat_panel_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_device_config
            save_device_config(
                self._current_pier, "flat_panel",
                driver=driver_combo.currentText(), server=server_edit.text().strip(),
                port=port_spin.value(), device_name=device_combo.currentText().strip() or None,
                panel_type=panel_type_combo.currentText(),
            )
            logger.info(
                "Saved flat panel settings for Pier %r: %s %s:%s, device: %s, panel type: %s",
                self._current_pier.name, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip() or "(none)",
                panel_type_combo.currentText(),
            )
            self._window.statusBar().showMessage(
                f"Saved flat panel settings for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_flat_panel_config)

        def reload_page() -> None:
            cfg = None
            if self._current_pier is not None:
                from galileo.observatory import get_device_config
                try:
                    cfg = get_device_config(self._current_pier, "flat_panel")
                except Exception:
                    logger.exception("Could not load saved flat panel config")

            driver_combo.blockSignals(True)
            server_edit.blockSignals(True)
            port_spin.blockSignals(True)
            device_combo.blockSignals(True)
            panel_type_combo.blockSignals(True)
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
                    panel_type_combo.setCurrentText(cfg.panel_type or "Flat Panel")
                else:
                    driver_combo.setCurrentIndex(0)
                    server_edit.clear()
                    port_spin.setValue(_DEFAULT_PORTS.get(driver_combo.currentText(), _DEFAULT_PORTS["Alpaca"]))
                    panel_type_combo.setCurrentIndex(0)
            finally:
                driver_combo.blockSignals(False)
                server_edit.blockSignals(False)
                port_spin.blockSignals(False)
                device_combo.blockSignals(False)
                panel_type_combo.blockSignals(False)
            _apply_panel_type(panel_type_combo.currentText())

            apply_driver_info(None)  # refilled on connect / device pick

            from galileo.current_object import pier_key
            adapter = adapters_by_pier.get(pier_key(self._current_pier))
            state["adapter"] = adapter
            if adapter is not None:
                _refresh_status()
            else:
                _apply_status({})

        def autoconnect_page() -> None:
            from galileo.current_object import pier_key
            device_name = device_combo.currentText().strip()
            if device_name and adapters_by_pier.get(pier_key(self._current_pier)) is None:
                _do_connect(device_name)

        def disconnect_page() -> None:
            """Pier-level Disconnect button: tear down this Pier's flat panel connection."""
            from galileo.current_object import pier_key
            adapter = adapters_by_pier.pop(pier_key(self._current_pier), None)
            if adapter is None:
                return
            import asyncio
            try:
                asyncio.run(adapter.disconnect())
            except Exception:
                logger.exception("Could not disconnect Flat Panel")
            state["adapter"] = None
            _apply_status({})
            self._window.statusBar().showMessage("Flat panel disconnected.", 4000)

        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _refresh_status))
        status_timer.start(2000)

        state["reload"] = reload_page
        state["autoconnect"] = autoconnect_page
        state["disconnect"] = disconnect_page
        state["connected"] = lambda: state.get("adapter") is not None
        self._device_pages["flat_panel"] = state
        reload_page()
        if self._startup_autoconnect_allowed():
            autoconnect_page()

        return page
