# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Dome device-category page (EQP-DOME-010)."""

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

_READY_COLOR = "#2ecc71"
_NOT_READY_COLOR = "#e74c3c"
_UNKNOWN_COLOR = "#888888"


class AppWindowDomePageMixin:
    def _build_dome_page(self: AppWindowState) -> QWidget:
        """Dome device-category page, modeled on the reference dome control
        screen (assets/samples/dome.png) but keeping this app's own
        Driver/Server/Port/Scan + Device/Connect connection row like every
        other Equipment page. Shutter state/azimuth with Open/Close/Park/Abort
        (EQP-DOME-010), plus an Observatory Status readiness summary that
        reflects this Dome connection alongside whatever the Weather page
        (EQP-WX-010/020, galileo.safety.evaluate_weather_safety) already
        knows for this Pier — read-only here, not a second weather
        connection or a new alerting subsystem."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFrame,
            QLabel, QTableWidget, QComboBox, QLineEdit, QSpinBox,
            QPushButton, QHeaderView, QMessageBox,
        )
        from PySide6.QtCore import QTimer, Qt

        page = QWidget()
        page.setObjectName("DomePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Dome")
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

        driver_info_row, apply_driver_info = self._build_driver_info_row()
        layout.addLayout(driver_info_row)

        def _heading(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("CriteriaHeading")
            return label

        def _panel() -> tuple:
            frame = QFrame()
            frame.setObjectName("DeviceSlotPanel")
            box = QVBoxLayout(frame)
            box.setSpacing(6)
            return frame, box

        # --- Shutter/Position (left) + Motion/Park (right) ----------------
        main_row = QHBoxLayout()
        main_row.setSpacing(16)

        left_frame, left = _panel()
        left.addWidget(_heading("Shutter"))
        shutter_value = QLabel("—")
        shutter_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        big = shutter_value.font()
        big.setPointSize(big.pointSize() + 10)
        big.setBold(True)
        shutter_value.setFont(big)
        left.addWidget(shutter_value)
        azimuth_row = QHBoxLayout()
        azimuth_row.addWidget(QLabel("Azimuth"))
        azimuth_value = QLabel("—")
        azimuth_row.addWidget(azimuth_value, 1)
        left.addLayout(azimuth_row)
        left.addStretch(1)
        main_row.addWidget(left_frame, 1)

        right_frame, right = _panel()
        right.addWidget(_heading("Motion"))
        motion_row = QHBoxLayout()
        open_btn = QPushButton("Open")
        open_btn.setObjectName("AccentButton")
        close_btn = QPushButton("Close")
        motion_row.addWidget(open_btn)
        motion_row.addWidget(close_btn)
        right.addLayout(motion_row)

        park_row = QHBoxLayout()
        park_btn = QPushButton("Park")
        abort_btn = QPushButton("Abort")
        park_row.addWidget(park_btn)
        park_row.addWidget(abort_btn)
        right.addLayout(park_row)

        park_chip = QLabel("—")
        park_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(park_chip)
        right.addStretch(1)
        main_row.addWidget(right_frame, 1)

        layout.addLayout(main_row)

        # --- Observatory Status (read-only, EQP-DOME-010 + EQP-WX-020) ----
        obs_frame = QFrame()
        obs_frame.setObjectName("DeviceSlotPanel")
        obs_box = QVBoxLayout(obs_frame)
        obs_box.setSpacing(6)
        obs_box.addWidget(_heading("Observatory Status"))

        def _status_row(label_text: str) -> tuple:
            row = QHBoxLayout()
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            row.addWidget(swatch)
            row.addWidget(QLabel(label_text))
            status_label = QLabel("—")
            row.addWidget(status_label, 1)
            obs_box.addLayout(row)
            return swatch, status_label

        dome_swatch, dome_status_label = _status_row("Dome")
        weather_swatch, weather_status_label = _status_row("Weather")

        ready_row = QHBoxLayout()
        ready_row.addStretch(1)
        ready_value = QLabel("—")
        ready_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ready_font = ready_value.font()
        ready_font.setBold(True)
        ready_value.setFont(ready_font)
        ready_row.addWidget(ready_value)
        obs_box.addLayout(ready_row)

        layout.addWidget(obs_frame)
        layout.addStretch(1)

        def _set_indicator(swatch: QLabel, status_label: QLabel, text: str, color: str) -> None:
            swatch.setStyleSheet(f"background-color: {color}; border: 1px solid #555; border-radius: 2px;")
            status_label.setText(text)

        def _refresh_observatory_status() -> None:
            """Read-only readiness summary: this Dome connection plus
            whatever the Weather page already knows for this Pier
            (EQP-WX-020) — no second weather connection, no new alerting."""
            dome_connected = state.get("adapter") is not None
            _set_indicator(
                dome_swatch, dome_status_label,
                "Connected" if dome_connected else "Not connected",
                _READY_COLOR if dome_connected else _UNKNOWN_COLOR,
            )

            weather_state = self._device_pages.get("weather") or {}
            weather_connected_fn = weather_state.get("connected")
            weather_connected = bool(weather_connected_fn and weather_connected_fn())
            weather_ready = True
            if not weather_connected:
                _set_indicator(weather_swatch, weather_status_label, "Not configured", _UNKNOWN_COLOR)
            else:
                evaluate = weather_state.get("evaluate")
                if evaluate:  # every Safety-screen device, not just the first tab
                    _any, weather_ready, violations = evaluate()
                else:
                    get_readings = weather_state.get("get_latest_readings")
                    get_rules = weather_state.get("get_rules")
                    readings = get_readings() if get_readings else {}
                    rules = [r for r in (get_rules() if get_rules else []) if r.safety_related]
                    from galileo.safety import evaluate_weather_safety
                    status = evaluate_weather_safety(readings, rules)
                    weather_ready, violations = status.is_safe, status.violations
                _set_indicator(
                    weather_swatch, weather_status_label,
                    "Safe" if weather_ready else "Unsafe — " + "; ".join(violations),
                    _READY_COLOR if weather_ready else _NOT_READY_COLOR,
                )

            ready = dome_connected and weather_ready
            ready_value.setText("Ready" if ready else "Not Ready")
            if ready:
                ready_color = _READY_COLOR
            elif dome_connected:
                ready_color = _NOT_READY_COLOR
            else:
                ready_color = _UNKNOWN_COLOR
            ready_value.setStyleSheet(f"color: {ready_color};")

        state: dict = {"adapter": None}
        adapters_by_pier: dict = {}
        device_controls = (open_btn, close_btn, park_btn, abort_btn)

        # --- device status / actions --------------------------------------
        def _call(method: str, *args, action: str) -> bool:
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the dome first.")
                return False
            import asyncio
            try:
                asyncio.run(getattr(adapter, method)(*args))
            except Exception:
                logger.exception("Dome %s failed", action)
                self._window.statusBar().showMessage(f"Dome {action} failed — see log.", 6000)
                return False
            return True

        def _apply_status(status: dict) -> None:
            connected = bool(status)
            if connected:  # an empty status is "not connected": keep what a device pick looked up
                apply_driver_info(status)
            for widget in device_controls:
                widget.setEnabled(connected)
            shutter_value.setText(status.get("shutter_state") or "—")
            azimuth = status.get("azimuth")
            azimuth_value.setText("—" if azimuth is None else f"{azimuth:.1f}°")
            at_park = status.get("is_at_park")
            state["parked"] = bool(at_park)
            park_btn.setText("Unpark" if at_park else "Park")
            if at_park is None:
                park_chip.setText("—")
                park_chip.setStyleSheet("")
            else:
                park_chip.setText("Parked" if at_park else "Unparked")
                chip_color = _READY_COLOR if at_park else _NOT_READY_COLOR
                park_chip.setStyleSheet(
                    f"background-color: {chip_color}; color: white; font-weight: bold; "
                    "padding: 3px 10px; border-radius: 3px;"
                )
            _refresh_observatory_status()

        def _refresh_status() -> dict | None:
            adapter = state.get("adapter")
            if adapter is None:
                _refresh_observatory_status()
                return None
            import asyncio
            try:
                status = asyncio.run(adapter.get_status())
            except Exception:
                logger.exception("Could not refresh dome status")
                return None
            _apply_status(status)
            return status

        def _open_clicked() -> None:
            if _call("open_shutter", action="open"):
                logger.info("Dome: shutter opened")
                _refresh_status()

        def _close_clicked() -> None:
            if _call("close_shutter", action="close"):
                logger.info("Dome: shutter closed")
                _refresh_status()

        def _park_clicked() -> None:
            unparking = bool(state.get("parked"))
            if _call("unpark" if unparking else "park", action="unpark" if unparking else "park"):
                logger.info("Dome: %s", "unparked" if unparking else "parked")
                _refresh_status()

        def _abort_clicked() -> None:
            if _call("abort_slew", action="abort"):
                logger.info("Dome: motion aborted")
                _refresh_status()

        open_btn.clicked.connect(_open_clicked)
        close_btn.clicked.connect(_close_clicked)
        park_btn.clicked.connect(_park_clicked)
        abort_btn.clicked.connect(_abort_clicked)

        # --- connection: connect / scan ------------------------------------
        def _do_connect(device_name: str) -> None:
            from galileo.core.devices import DeviceCategory
            adapter = self._connect_device_adapter(
                DeviceCategory.DOME, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to Dome {device_name!r} — see log.", 6000)
                return
            from galileo.current_object import pier_key
            state["adapter"] = adapter
            adapters_by_pier[pier_key(self._current_pier)] = adapter
            self._window.statusBar().showMessage(f"Connected to Dome {device_name!r}.", 4000)
            _refresh_status()

        def _connect_clicked() -> None:
            device_name = device_combo.currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a dome device first.")
                return
            _do_connect(device_name)

        connect_btn.clicked.connect(_connect_clicked)

        def _device_picked() -> None:
            """Show the driver of the device just picked, without connecting it."""
            from galileo.core.devices import DeviceCategory
            apply_driver_info(self._lookup_driver_info(
                DeviceCategory.DOME, driver_combo.currentText(), server_edit.text().strip(),
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
                adapter = get_adapter_class(DeviceCategory.DOME)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.DOME))
            except Exception:
                logger.exception("Dome scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Dome scan failed — see log.", 6000)
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
                    "Detected %d %s dome device(s) at %s:%s: %s",
                    len(devices), driver, server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} dome device(s) — see log.", 4000)
            else:
                logger.info("No %s dome devices found at %s:%s.", driver, server, port)
                self._window.statusBar().showMessage(f"No {driver} dome devices found at {server}:{port}.", 4000)

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

        def save_dome_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_device_config
            save_device_config(
                self._current_pier, "dome",
                driver=driver_combo.currentText(), server=server_edit.text().strip(),
                port=port_spin.value(), device_name=device_combo.currentText().strip() or None,
            )
            logger.info(
                "Saved dome settings for Pier %r: %s %s:%s, device: %s",
                self._current_pier.name, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip() or "(none)",
            )
            self._window.statusBar().showMessage(
                f"Saved dome settings for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_dome_config)

        def reload_page() -> None:
            cfg = None
            if self._current_pier is not None:
                from galileo.observatory import get_device_config
                try:
                    cfg = get_device_config(self._current_pier, "dome")
                except Exception:
                    logger.exception("Could not load saved dome config")

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
                _refresh_status()
            else:
                _apply_status({})

        def autoconnect_page() -> None:
            from galileo.current_object import pier_key
            device_name = device_combo.currentText().strip()
            if device_name and adapters_by_pier.get(pier_key(self._current_pier)) is None:
                _do_connect(device_name)

        def disconnect_page() -> None:
            """Pier-level Disconnect button: tear down this Pier's dome connection."""
            from galileo.current_object import pier_key
            adapter = adapters_by_pier.pop(pier_key(self._current_pier), None)
            if adapter is None:
                return
            import asyncio
            try:
                asyncio.run(adapter.disconnect())
            except Exception:
                logger.exception("Could not disconnect Dome")
            state["adapter"] = None
            _apply_status({})
            self._window.statusBar().showMessage("Dome disconnected.", 4000)

        def _tick() -> None:
            if state.get("adapter") is not None:
                _refresh_status()
            else:
                _refresh_observatory_status()

        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _tick))
        status_timer.start(2000)

        state["reload"] = reload_page
        state["autoconnect"] = autoconnect_page
        state["disconnect"] = disconnect_page
        state["connected"] = lambda: state.get("adapter") is not None
        self._device_pages["dome"] = state
        reload_page()
        if self._startup_autoconnect_allowed():
            autoconnect_page()

        return page
