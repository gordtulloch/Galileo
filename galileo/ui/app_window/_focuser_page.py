# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Focuser device-category page."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _new_form_layout, _when_visible, _DEFAULT_PORTS, QWidget

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowFocuserPageMixin:
    def _build_focuser_page(self: AppWindowState) -> QWidget:
        """Focuser device-category page: one shared Driver/Server/Port
        connection plus any number of independently configured focuser
        panels (a telescope can expose more than one focuser). Each panel is
        its own live status screen — Is Moving/Is Settling, Max Increment,
        Max Step, Position (current/target), Temperature Compensation, and
        Temperature — refreshed on a timer once connected, mirroring the
        Camera page's shared-connection/scroll-area/scan-to-log pattern."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QTableWidget,
            QComboBox, QLineEdit, QSpinBox, QPushButton, QCheckBox, QHeaderView,
            QScrollArea, QMessageBox,
        )
        from PySide6.QtCore import QTimer

        page = QWidget()
        page.setObjectName("FocuserPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        heading = QLabel("Focuser")
        heading.setObjectName("PageTitle")
        heading_row.addWidget(heading)
        add_focuser_btn = QPushButton("+")
        add_focuser_btn.setObjectName("AccentButton")
        add_focuser_btn.setFixedWidth(28)
        add_focuser_btn.setToolTip("Add another focuser sharing this connection.")
        heading_row.addWidget(add_focuser_btn)
        heading_row.addStretch(1)
        layout.addLayout(heading_row)

        # --- shared connection row (one Driver/Server/Port for every panel) -
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

        # --- N independent focuser panels, sharing the connection above ----
        panels: list[dict] = []

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        panels_container = QWidget()
        panels_layout = QVBoxLayout(panels_container)
        panels_layout.setContentsMargins(0, 0, 0, 0)
        panels_layout.setSpacing(10)
        panels_layout.addStretch(1)
        scroll_area.setWidget(panels_container)
        layout.addWidget(scroll_area, 1)

        def _build_focuser_panel(removable: bool) -> dict:
            frame = QFrame()
            frame.setObjectName("DeviceSlotPanel")
            outer = QVBoxLayout(frame)

            header = QHBoxLayout()
            title_label = QLabel()
            title_label.setObjectName("CriteriaHeading")
            header.addWidget(title_label)
            header.addStretch(1)
            connect_btn = QPushButton("Connect")
            header.addWidget(connect_btn)
            remove_btn = None
            if removable:
                remove_btn = QPushButton("Remove")
                header.addWidget(remove_btn)
            outer.addLayout(header)

            form = _new_form_layout()
            outer.addLayout(form)

            device_combo = QComboBox()
            device_combo.setEditable(True)
            device_combo.addItem("")
            form.addRow("Device", device_combo)

            driver_info_row, apply_driver_info = self._build_driver_info_row()
            form.addRow(driver_info_row)

            is_moving_value = QLabel("—")
            form.addRow("Is Moving", is_moving_value)

            is_settling_value = QLabel("—")
            form.addRow("Is Settling", is_settling_value)

            max_increment_value = QLabel("—")
            form.addRow("Max Increment", max_increment_value)

            max_step_value = QLabel("—")
            form.addRow("Max Step", max_step_value)

            position_value = QLabel("—")
            form.addRow("Position (current)", position_value)

            target_row = QHBoxLayout()
            target_position = QSpinBox()
            target_position.setRange(0, 1_000_000)
            target_row.addWidget(target_position, 1)
            move_btn = QPushButton("Move")
            target_row.addWidget(move_btn)
            form.addRow("Position (target)", target_row)

            temp_comp_check = QCheckBox("Enabled")
            form.addRow("Temperature Compensation", temp_comp_check)

            temperature_value = QLabel("—")
            form.addRow("Temperature", temperature_value)

            return {
                "frame": frame, "title_label": title_label, "remove_btn": remove_btn,
                "connect_btn": connect_btn, "device": device_combo,
                "apply_driver_info": apply_driver_info,
                "is_moving_value": is_moving_value, "is_settling_value": is_settling_value,
                "max_increment_value": max_increment_value, "max_step_value": max_step_value,
                "position_value": position_value, "target_position": target_position,
                "move_btn": move_btn, "temp_comp_check": temp_comp_check,
                "temperature_value": temperature_value, "adapter": None,
                "_last_is_moving": None, "_last_is_settling": None,
            }

        def _renumber_panels() -> None:
            for i, panel in enumerate(panels):
                panel["title_label"].setText("Primary Focuser" if i == 0 else f"Focuser {i + 1}")

        def _remove_panel(panel: dict) -> None:
            if panel not in panels or panel is panels[0]:
                return
            panels.remove(panel)
            panel["frame"].setParent(None)
            panel["frame"].deleteLater()
            _renumber_panels()

        last_scanned_devices: list[str] = []

        def _populate_device_combo(combo: QComboBox, devices: list[str]) -> None:
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            for name in devices:
                combo.addItem(name)
            if current and combo.findText(current) < 0:
                combo.addItem(current)
            idx = combo.findText(current)
            combo.setCurrentIndex(max(idx, 0))
            combo.blockSignals(False)

        def _apply_status(panel: dict, status: dict) -> None:
            def _yes_no(value) -> str:
                return "—" if value is None else ("Yes" if value else "No")

            panel["is_moving_value"].setText(_yes_no(status.get("is_moving")))
            panel["is_settling_value"].setText(_yes_no(status.get("is_settling")))
            max_increment = status.get("max_increment")
            panel["max_increment_value"].setText("—" if max_increment is None else str(max_increment))
            max_step = status.get("max_step")
            panel["max_step_value"].setText("—" if max_step is None else str(max_step))
            position = status.get("position")
            panel["position_value"].setText("—" if position is None else str(position))
            if position is not None and not panel["target_position"].hasFocus():
                panel["target_position"].blockSignals(True)
                panel["target_position"].setValue(int(position))
                panel["target_position"].blockSignals(False)
            temp_comp = status.get("temp_comp")
            if temp_comp is not None:
                panel["temp_comp_check"].blockSignals(True)
                panel["temp_comp_check"].setChecked(bool(temp_comp))
                panel["temp_comp_check"].blockSignals(False)
            temperature = status.get("temperature")
            panel["temperature_value"].setText("—" if temperature is None else f"{temperature:.1f} °C")

        def _log_status_transitions(panel: dict, status: dict) -> None:
            """Log is_moving/is_settling *changes* at INFO — the result side
            of a move transaction — rather than every 2-second poll, which
            would otherwise flood the log while a move is in progress."""
            title = panel["title_label"].text()
            position = status.get("position")
            was_moving, is_moving = panel["_last_is_moving"], status.get("is_moving")
            was_settling, is_settling = panel["_last_is_settling"], status.get("is_settling")
            if is_moving and not was_moving:
                logger.info("Focuser %s: started moving (target position %s)", title, panel["target_position"].value())
            elif was_moving and not is_moving:
                logger.info("Focuser %s: stopped moving at position %s", title, position)
            if is_settling and not was_settling:
                logger.info("Focuser %s: settling at position %s", title, position)
            elif was_settling and not is_settling:
                logger.info("Focuser %s: finished settling at position %s", title, position)
            panel["_last_is_moving"] = is_moving
            panel["_last_is_settling"] = is_settling

        def _refresh_panel_status(panel: dict) -> dict | None:
            adapter = panel.get("adapter")
            if adapter is None:
                return None
            import asyncio
            try:
                status = asyncio.run(adapter.get_status())
            except Exception:
                logger.exception("Could not refresh status for %s", panel["title_label"].text())
                return None
            _log_status_transitions(panel, status)
            _apply_status(panel, status)
            return status

        def _do_connect(panel: dict, device_name: str, slot_label: str) -> None:
            from galileo.core.devices import DeviceCategory
            adapter = self._connect_device_adapter(
                DeviceCategory.FOCUSER, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to {slot_label} {device_name!r} — see log.", 6000)
                return
            panel["adapter"] = adapter
            self._window.statusBar().showMessage(f"Connected to {slot_label} {device_name!r}.", 4000)
            import asyncio
            try:
                panel["apply_driver_info"](asyncio.run(adapter.get_driver_info()))
            except Exception:
                logger.exception("Could not read driver info from connected %s", slot_label)
            _refresh_panel_status(panel)

        def _lookup_panel_driver_info(panel: dict) -> None:
            """Show the driver of the device just picked in *panel*, without connecting it."""
            from galileo.core.devices import DeviceCategory
            panel["apply_driver_info"](self._lookup_driver_info(
                DeviceCategory.FOCUSER, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), panel["device"].currentText().strip(),
            ))

        def _connect_clicked(panel: dict) -> None:
            device_name = panel["device"].currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a focuser device first.")
                return
            _do_connect(panel, device_name, panel["title_label"].text())

        def _move_clicked(panel: dict) -> None:
            adapter = panel.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect this focuser first.")
                return
            target = panel["target_position"].value()
            title = panel["title_label"].text()
            logger.info("Focuser %s: move requested to position %s", title, target)
            import asyncio
            try:
                asyncio.run(adapter.move_to(target))
            except Exception:
                logger.exception("Could not move focuser to %s", target)
                self._window.statusBar().showMessage("Move failed — see log.", 6000)
                return
            _refresh_panel_status(panel)

        def _temp_comp_toggled(panel: dict, checked: bool) -> None:
            adapter = panel.get("adapter")
            if adapter is None:
                return
            import asyncio
            try:
                asyncio.run(adapter.set_temp_comp(checked))
            except Exception:
                logger.exception("Could not set temperature compensation")

        def _add_panel() -> dict:
            panel = _build_focuser_panel(removable=len(panels) > 0)
            panels.append(panel)
            panels_layout.insertWidget(panels_layout.count() - 1, panel["frame"])
            _renumber_panels()
            _populate_device_combo(panel["device"], last_scanned_devices)
            if panel["remove_btn"] is not None:
                panel["remove_btn"].clicked.connect(lambda: _remove_panel(panel))
            panel["connect_btn"].clicked.connect(lambda: _connect_clicked(panel))
            panel["device"].activated.connect(lambda _index: _lookup_panel_driver_info(panel))
            panel["move_btn"].clicked.connect(lambda: _move_clicked(panel))
            panel["temp_comp_check"].toggled.connect(lambda checked: _temp_comp_toggled(panel, checked))
            return panel

        def _set_panel_count(count: int) -> None:
            count = max(count, 1)
            while len(panels) < count:
                _add_panel()
            while len(panels) > count:
                _remove_panel(panels[-1])

        add_focuser_btn.clicked.connect(_add_panel)

        def _refresh_slot_choices(devices: list[str]) -> None:
            last_scanned_devices[:] = devices
            for panel in panels:
                _populate_device_combo(panel["device"], devices)

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
                    adapter = get_adapter_class(DeviceCategory.FOCUSER)(host=server, port=port)
                else:
                    from galileo.adapters.alpaca import get_adapter_class
                    adapter = get_adapter_class(DeviceCategory.FOCUSER)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.FOCUSER))
            except Exception:
                logger.exception("Focuser scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Focuser scan failed — see log.", 6000)
                _refresh_slot_choices([])
                return
            if devices:
                logger.info(
                    "Detected %d %s focuser device(s) at %s:%s: %s",
                    len(devices), driver, server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} focuser device(s) — see log.", 4000)
            else:
                logger.info("No %s focuser devices found at %s:%s.", driver, server, port)
                self._window.statusBar().showMessage(f"No {driver} focuser devices found at {server}:{port}.", 4000)
            _refresh_slot_choices(devices)

        scan_btn.clicked.connect(run_scan)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        save_btn.setToolTip("Save every focuser's settings under the selected Observatory and Pier.")
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        layout.addWidget(log_heading)
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)
        layout.addWidget(log_pane)

        def _slot_for_index(i: int) -> str:
            return "primary" if i == 0 else f"focuser_{i + 1}"

        def save_focuser_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return

            from galileo.observatory import save_device_config, delete_device_config, list_device_config_slots
            driver = driver_combo.currentText()
            server = server_edit.text().strip()
            port = port_spin.value()

            used_slots = set()
            for i, panel in enumerate(panels):
                slot = _slot_for_index(i)
                used_slots.add(slot)
                save_device_config(
                    self._current_pier, "focuser", driver=driver, server=server, port=port,
                    device_name=panel["device"].currentText().strip() or None, slot=slot,
                )

            for stale_slot in set(list_device_config_slots(self._current_pier, "focuser")) - used_slots:
                delete_device_config(self._current_pier, "focuser", slot=stale_slot)

            logger.info(
                "Saved focuser settings for Pier %r: %s %s:%s, device(s): %s",
                self._current_pier.name, driver, server, port,
                ", ".join(p["device"].currentText().strip() or "(none)" for p in panels),
            )
            self._window.statusBar().showMessage(
                f"Saved focuser settings for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_focuser_config)

        def _load_panel(panel: dict, cfg) -> None:
            combo = panel["device"]
            combo.blockSignals(True)
            if cfg is not None and cfg.device_name and combo.findText(cfg.device_name) < 0:
                combo.addItem(cfg.device_name)
            combo.setCurrentText(cfg.device_name if cfg is not None and cfg.device_name else "")
            combo.blockSignals(False)
            panel["adapter"] = None
            _apply_status(panel, {})
            panel["apply_driver_info"](None)  # refilled on connect / device pick

        def reload_page() -> None:
            from galileo.observatory import get_device_config, list_device_config_slots

            saved_slots: list[str] = []
            if self._current_pier is not None:
                try:
                    saved_slots = list_device_config_slots(self._current_pier, "focuser")
                except Exception:
                    logger.exception("Could not load saved focuser config")

            extra_count = 0
            for slot in saved_slots:
                if slot.startswith("focuser_"):
                    try:
                        extra_count = max(extra_count, int(slot.rsplit("_", 1)[1]) - 1)
                    except ValueError:
                        pass
            _set_panel_count(1 + extra_count)

            primary_cfg = None
            if self._current_pier is not None:
                try:
                    primary_cfg = get_device_config(self._current_pier, "focuser", slot="primary")
                except Exception:
                    logger.exception("Could not load saved focuser config")

            driver_combo.blockSignals(True)
            server_edit.blockSignals(True)
            port_spin.blockSignals(True)
            try:
                if primary_cfg is not None:
                    idx = driver_combo.findText(primary_cfg.driver)
                    if idx >= 0:
                        driver_combo.setCurrentIndex(idx)
                    server_edit.setText(primary_cfg.server)
                    port_spin.setValue(primary_cfg.port)
                else:
                    driver_combo.setCurrentIndex(0)
                    server_edit.clear()
                    port_spin.setValue(_DEFAULT_PORTS.get(driver_combo.currentText(), _DEFAULT_PORTS["Alpaca"]))
            finally:
                driver_combo.blockSignals(False)
                server_edit.blockSignals(False)
                port_spin.blockSignals(False)

            for i, panel in enumerate(panels):
                cfg = primary_cfg if i == 0 else (
                    get_device_config(self._current_pier, "focuser", slot=_slot_for_index(i))
                    if self._current_pier is not None else None
                )
                _load_panel(panel, cfg)

        def autoconnect_page() -> None:
            for panel in panels:
                device_name = panel["device"].currentText().strip()
                if device_name:
                    _do_connect(panel, device_name, panel["title_label"].text())

        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, lambda: [_refresh_panel_status(p) for p in panels]))
        status_timer.start(2000)

        def connected_adapter():
            # The first connected focuser — what the Focus page drives.
            return next((p["adapter"] for p in panels if p.get("adapter") is not None), None)

        state = {"reload": reload_page, "autoconnect": autoconnect_page, "get_adapter": connected_adapter}
        self._device_pages["focuser"] = state
        reload_page()
        autoconnect_page()

        return page
