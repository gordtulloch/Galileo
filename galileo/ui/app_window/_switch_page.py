# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Switches page (EQP-SW-090, EQP-SW-110).

Renders a connected power box or relay board from its :class:`~galileo.core.switches.SwitchPanel` — a section
per group, a toggle per switchable channel, a read-out per display-only channel, a slider or field per dew
duty, voltage and generic value, the device's readings, and an "Other" group for driver properties no mapping
claimed. The page cannot tell INDI from Alpaca, or a standard power box from a profiled one: all of that is in
the adapters. Plugin panels contributed for this page (``PLUG-070``: the Kasa, Relay and SwitchBot panels)
still sit above it, unchanged.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from galileo.ui.qt_helpers import take_widget

from ._common import _DEFAULT_PORTS, QWidget, _when_visible

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._state import AppWindowState

_STATE_COLOR = {"Ok": "#2ecc71", "Busy": "#f1c40f", "Alert": "#e74c3c"}
_REFRESH_MS = 2000          # EQP-SW-090: no longer than 5 s


def panel_signature(panel: Any) -> tuple:
    """What decides whether the widgets must be rebuilt rather than refreshed in place."""
    return (
        panel.recognised, panel.message, panel.profile,
        tuple((g.name, tuple((c.id, c.kind, c.switchable, c.available, c.writable) for c in g.channels))
              for g in panel.groups),
        tuple(s.id for s in panel.sensors),
        tuple((g.name, tuple((p.name, p.kind) for p in g.properties)) for g in panel.other),
    )


def format_reading(value: float | None, unit: str) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:.2f} {unit}".strip()


class AppWindowSwitchPageMixin:
    def _build_switch_page(self: AppWindowState, label: str) -> QWidget:
        """The Switches page: pick a power/switch device (INDI or Alpaca), connect, and control it."""
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import (
            QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
            QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTableWidget, QVBoxLayout,
        )

        page = QWidget()
        page.setObjectName("SwitchesPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel(label)
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        subtitle = QLabel(
            "Control a power box or relay board: switch its ports, set dew heaters and regulated outputs, "
            "and read its voltage and current."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Plugin-contributed panels for this category (e.g. the Kasa plugin's) sit under the heading.
        pm = getattr(self, "_plugin_manager", None)
        if pm is not None:
            from galileo import help as help_content
            from galileo.ui.help import SCREEN_PROPERTY
            for panel_def in pm.get_ui_registry().get_equipment_panels("switch"):
                panel_page = self._build_plugin_page(panel_def.plugin, panel_def.label)
                plugin_screen = f"plugin.{panel_def.plugin.name}"
                if help_content.load(plugin_screen) is not None:
                    panel_page.setProperty(SCREEN_PROPERTY, plugin_screen)
                layout.addWidget(panel_page)

        # --- connection row (same as every other Equipment page) --------
        table = QTableWidget(1, 4)
        table.setHorizontalHeaderLabels(["Driver", "Server", "Port", ""])
        table.verticalHeader().setVisible(False)
        for col, mode in enumerate((
            QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch,
            QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.ResizeToContents,
        )):
            table.horizontalHeader().setSectionResizeMode(col, mode)
        table.setMaximumHeight(70)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        driver_combo = QComboBox()
        driver_combo.addItems(["Alpaca", "INDI"])
        table.setCellWidget(0, 0, driver_combo)
        server_edit = QLineEdit()
        server_edit.setPlaceholderText("FQDN or IP, e.g. stellarmate.local or 192.168.1.50")
        server_edit.setMaxLength(40)
        table.setCellWidget(0, 1, server_edit)
        port_spin = QSpinBox()
        port_spin.setRange(1, 65535)
        port_spin.setValue(_DEFAULT_PORTS["Alpaca"])
        driver_combo.currentTextChanged.connect(
            lambda name: port_spin.setValue(_DEFAULT_PORTS.get(name, _DEFAULT_PORTS["Alpaca"])))
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

        # --- live panel --------------------------------------------------
        panel_container = QVBoxLayout()
        panel_container.setSpacing(8)
        layout.addLayout(panel_container)

        state: dict[str, Any] = {"adapter": None, "signature": None, "refreshers": [], "panel": None}
        adapters_by_pier: dict = {}

        def dot_style(prop_state: str) -> str:
            return f"color: {_STATE_COLOR.get(prop_state, '#888888')}; font-size: 14px;"

        def set_accent(button, active: bool) -> None:
            button.setObjectName("AccentButton" if active else "")
            button.style().unpolish(button)
            button.style().polish(button)

        # -- writing -------------------------------------------------------
        def session_running() -> bool:
            from galileo.current_object import pier_key
            from galileo.ui.session_runner import get_session_controller
            try:
                return pier_key(self._current_pier) in get_session_controller(self).run_snapshot()
            except Exception:
                logger.exception("Switches: could not tell whether a session is running")
                return False

        def confirm_off(channel_label: str) -> bool:
            """EQP-SW-110: ask before switching a channel off while a session runs on this Pier."""
            if not session_running():
                return True
            answer = QMessageBox.question(
                self._window, "Switch off during a session",
                f"A session is running on this Pier. Switch off {channel_label!r}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            return answer == QMessageBox.StandardButton.Yes

        def write_channel(channel, **kwargs) -> bool:
            adapter = state.get("adapter")
            if adapter is None:
                return False
            import asyncio

            from galileo.core.devices import SwitchController
            try:
                asyncio.run(SwitchController(adapter).set_channel(channel.id, **kwargs))
            except Exception as exc:
                logger.exception("Switches: setting %s failed", channel.id)
                self._window.statusBar().showMessage(f"Could not set {channel.label}: {exc}", 8000)
                refresh_panel()
                return False
            logger.info("Switches: set %s %s", channel.label, kwargs)
            refresh_panel()
            return True

        def write_property(prop_name: str, values: dict) -> None:
            adapter = state.get("adapter")
            writer = getattr(adapter, "write_property", None)
            if writer is None:
                return
            import asyncio
            try:
                asyncio.run(writer(prop_name, values))
            except Exception as exc:
                logger.exception("Switches: writing %s failed", prop_name)
                self._window.statusBar().showMessage(f"Could not set {prop_name}: {exc}", 8000)
            refresh_panel()

        # -- rows ----------------------------------------------------------
        def row_shell(channel) -> tuple[QWidget, QHBoxLayout, QLabel]:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("●")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            name = QLabel(channel.label)
            if channel.note:
                name.setToolTip(channel.note)
            row.addWidget(name)
            row.addStretch(1)
            return row_widget, row, dot

        def channel_row(channel) -> tuple[QWidget, Callable]:
            row_widget, row, dot = row_shell(channel)
            enabled = channel.writable and channel.available
            parts: dict[str, Any] = {}

            if not channel.switchable and channel.kind != "value":
                state_text = "On" if channel.on else ("Off" if channel.on is False else "—")
                row.addWidget(QLabel(f"{state_text} (not switchable)"))
                amps = QLabel("")
                row.addWidget(amps)
                parts["amps"] = amps
            elif channel.kind == "action":
                run_btn = QPushButton("Run")
                run_btn.setEnabled(enabled)
                run_btn.clicked.connect(lambda: write_channel(channel, on=True))
                row.addWidget(run_btn)
            elif channel.kind == "value":
                spin = QDoubleSpinBox()
                lo = channel.min if channel.min is not None and math.isfinite(channel.min) else -1e9
                hi = channel.max if channel.max is not None and math.isfinite(channel.max) else 1e9
                spin.setRange(lo, hi)
                spin.setSingleStep(channel.step or 1.0)
                spin.setDecimals(3 if (channel.step or 1.0) < 1 else 1)
                spin.setValue(channel.value if channel.value is not None and math.isfinite(channel.value) else lo)
                spin.setEnabled(enabled)
                row.addWidget(spin)
                set_btn = QPushButton("Set")
                set_btn.setObjectName("AccentButton")
                set_btn.setEnabled(enabled)
                set_btn.clicked.connect(lambda: write_channel(channel, value=spin.value()))
                row.addWidget(set_btn)
                parts["spin"] = spin
            else:
                toggle = QPushButton("On" if channel.on else "Off")
                toggle.setCheckable(True)
                toggle.setChecked(bool(channel.on))
                toggle.setEnabled(enabled)
                set_accent(toggle, bool(channel.on))

                def on_toggle(checked: bool) -> None:
                    if not checked and not confirm_off(channel.label):
                        toggle.blockSignals(True)
                        toggle.setChecked(True)
                        toggle.blockSignals(False)
                        return
                    write_channel(channel, on=checked)

                toggle.clicked.connect(on_toggle)
                row.addWidget(toggle)
                parts["toggle"] = toggle
                if channel.kind == "dew":
                    duty_spin = QSpinBox()
                    duty_spin.setRange(0, 100)
                    duty_spin.setSuffix(" %")
                    duty_spin.setSingleStep(max(1, round(channel.step or 1)))
                    duty_spin.setValue(round(channel.duty or 0))
                    duty_spin.setEnabled(enabled)
                    row.addWidget(duty_spin)
                    set_btn = QPushButton("Set")
                    set_btn.setObjectName("AccentButton")
                    set_btn.setEnabled(enabled)
                    set_btn.clicked.connect(lambda: write_channel(channel, duty=float(duty_spin.value())))
                    row.addWidget(set_btn)
                    parts["duty"] = duty_spin
                elif channel.kind == "variable":
                    spin_v = QDoubleSpinBox()
                    spin_v.setRange(channel.min if channel.min is not None else 0.0,
                                    channel.max if channel.max is not None else 100.0)
                    spin_v.setSingleStep(channel.step or 0.1)
                    spin_v.setDecimals(1)
                    spin_v.setSuffix(" V")
                    spin_v.setValue(channel.volts if channel.volts is not None else spin_v.minimum())
                    spin_v.setEnabled(enabled)
                    row.addWidget(spin_v)
                    set_btn = QPushButton("Set")
                    set_btn.setObjectName("AccentButton")
                    set_btn.setEnabled(enabled)
                    set_btn.clicked.connect(lambda: write_channel(channel, volts=spin_v.value()))
                    row.addWidget(set_btn)
                    parts["volts"] = spin_v
                amps = QLabel("")
                row.addWidget(amps)
                parts["amps"] = amps
            if not channel.available and channel.note:
                row_widget.setToolTip(channel.note)

            def refresh(fresh) -> None:
                dot.setStyleSheet(dot_style(fresh.state))
                toggle = parts.get("toggle")
                if toggle is not None:
                    toggle.blockSignals(True)
                    toggle.setChecked(bool(fresh.on))
                    toggle.setText("On" if fresh.on else "Off")
                    toggle.blockSignals(False)
                    set_accent(toggle, bool(fresh.on))
                for key, value in (("duty", fresh.duty), ("volts", fresh.volts), ("spin", fresh.value)):
                    spin = parts.get(key)
                    if spin is None or value is None or not math.isfinite(value) or spin.hasFocus():
                        continue
                    spin.blockSignals(True)
                    spin.setValue(round(value) if key == "duty" else value)
                    spin.blockSignals(False)
                amps = parts.get("amps")
                if amps is not None:
                    amps.setText("" if fresh.current_a is None else f"{fresh.current_a:.2f} A")

            refresh(channel)
            return row_widget, refresh

        def group_box(title: str) -> tuple[QGroupBox, QVBoxLayout]:
            box = QGroupBox(title)
            box_layout = QVBoxLayout(box)
            box_layout.setSpacing(6)
            return box, box_layout

        def sensors_box(sensors) -> tuple[QGroupBox, Callable]:
            box = QGroupBox("Readings")
            grid = QGridLayout(box)
            values: dict[str, QLabel] = {}
            for i, sensor in enumerate(sensors):
                grid.addWidget(QLabel(sensor.label), i // 3, (i % 3) * 2)
                value_label = QLabel(format_reading(sensor.value, sensor.unit))
                value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
                grid.addWidget(value_label, i // 3, (i % 3) * 2 + 1)
                values[sensor.id] = value_label

            def refresh(panel) -> None:
                for sensor in panel.sensors:
                    if sensor.id in values:
                        values[sensor.id].setText(format_reading(sensor.value, sensor.unit))

            return box, refresh

        def other_box(groups) -> tuple[QGroupBox, Callable]:
            """The driver's own properties no mapping claimed (EQP-SW-070), kept deliberately plain."""
            box, box_layout = group_box("Other")
            refreshers: dict[str, Callable] = {}
            for group in groups:
                box_layout.addWidget(QLabel(f"<b>{group.name}</b>"))
                for prop in group.properties:
                    row_widget = QWidget()
                    row = QHBoxLayout(row_widget)
                    row.setContentsMargins(0, 0, 0, 0)
                    dot = QLabel("●")
                    dot.setFixedWidth(16)
                    row.addWidget(dot)
                    row.addWidget(QLabel(prop.label))
                    row.addStretch(1)
                    editable = prop.perm != "ro"
                    inputs: list[tuple[Any, str]] = []
                    for el in prop.elements:
                        widget: Any
                        if prop.kind == "switch":
                            widget = QPushButton(el.label)
                            widget.setCheckable(True)
                            widget.setChecked(bool(el.value))
                            widget.setEnabled(editable)
                            widget.clicked.connect(
                                lambda checked, p=prop.name, e=el.name: write_property(p, {e: checked}))
                        elif prop.kind == "number":
                            widget = QDoubleSpinBox()
                            lo = el.min if el.min is not None and math.isfinite(el.min) else -1e9
                            hi = el.max if el.max is not None and math.isfinite(el.max) else 1e9
                            widget.setRange(lo, hi)
                            widget.setDecimals(3 if (el.step or 1.0) < 1 else 1)
                            if el.value is not None and math.isfinite(float(el.value)):
                                widget.setValue(float(el.value))
                            widget.setEnabled(editable)
                        elif prop.kind == "text":
                            widget = QLineEdit(str(el.value) if el.value is not None else "")
                            widget.setEnabled(editable)
                        else:
                            widget = QLabel(f"{el.label}: {el.value}")
                        row.addWidget(widget)
                        inputs.append((widget, el.name))
                    if prop.kind in ("number", "text") and editable:
                        set_btn = QPushButton("Set")
                        set_btn.setObjectName("AccentButton")

                        def send(_checked=False, p=prop, ins=inputs) -> None:
                            values = {name: (w.value() if hasattr(w, "value") else w.text()) for w, name in ins}
                            write_property(p.name, values)

                        set_btn.clicked.connect(send)
                        row.addWidget(set_btn)
                    box_layout.addWidget(row_widget)

                    def refresh_prop(fresh, dot=dot, ins=inputs) -> None:
                        dot.setStyleSheet(dot_style(fresh.state))
                        live = {el.name: el.value for el in fresh.elements}
                        for widget, name in ins:
                            value = live.get(name)
                            if value is None or getattr(widget, "hasFocus", lambda: False)():
                                continue
                            widget.blockSignals(True)
                            if isinstance(widget, QPushButton):
                                widget.setChecked(bool(value))
                            elif isinstance(widget, QDoubleSpinBox):
                                if math.isfinite(float(value)):
                                    widget.setValue(float(value))
                            elif isinstance(widget, QLineEdit):
                                widget.setText(str(value))
                            widget.blockSignals(False)

                    refresh_prop(prop)
                    refreshers[prop.name] = refresh_prop

            def refresh(panel) -> None:
                for group in panel.other:
                    for prop in group.properties:
                        fn = refreshers.get(prop.name)
                        if fn is not None:
                            fn(prop)

            return box, refresh

        # -- building and refreshing the whole panel -----------------------
        def clear_panel() -> None:
            while panel_container.count():
                widget = take_widget(panel_container)
                if widget is not None:
                    widget.setParent(None)
            state["signature"] = None
            state["refreshers"] = []

        def show_placeholder(text: str) -> None:
            clear_panel()
            placeholder = QLabel(text)
            placeholder.setObjectName("CriteriaHeading")
            placeholder.setWordWrap(True)
            panel_container.addWidget(placeholder)

        def build_panel(panel) -> None:
            clear_panel()
            refreshers: list[Callable] = []
            if panel.message:
                note = QLabel(panel.message)
                note.setWordWrap(True)
                panel_container.addWidget(note)
            elif panel.profile:
                panel_container.addWidget(QLabel(f"Recognised as: {panel.profile}"))
            for group in panel.groups:
                box, box_layout = group_box(group.name)
                by_id: dict[str, Callable] = {}
                for channel in group.channels:
                    widget, refresh = channel_row(channel)
                    box_layout.addWidget(widget)
                    by_id[channel.id] = refresh

                def refresh_group(fresh_panel, name=group.name, by_id=by_id) -> None:
                    fresh_group = next((g for g in fresh_panel.groups if g.name == name), None)
                    if fresh_group is None:
                        return
                    for fresh in fresh_group.channels:
                        fn = by_id.get(fresh.id)
                        if fn is not None:
                            fn(fresh)

                refreshers.append(refresh_group)
                panel_container.addWidget(box)
            if panel.sensors:
                box, refresh = sensors_box(panel.sensors)
                panel_container.addWidget(box)
                refreshers.append(refresh)
            if panel.other:
                box, refresh = other_box(panel.other)
                panel_container.addWidget(box)
                refreshers.append(refresh)
            state["signature"] = panel_signature(panel)
            state["refreshers"] = refreshers

        def refresh_panel() -> None:
            adapter = state.get("adapter")
            if adapter is None:
                return
            import asyncio

            from galileo.core.devices import SwitchController
            try:
                panel = asyncio.run(SwitchController(adapter).get_panel())
            except Exception as exc:
                # EQP-SW-120: a lost server or a device that stopped answering degrades the panel, nothing more.
                logger.warning("Switches: could not refresh the panel: %s", exc)
                state["signature"] = None
                show_placeholder(f"Cannot read the device right now: {exc}")
                return
            state["panel"] = panel
            if state["signature"] != panel_signature(panel):
                build_panel(panel)
                return
            for refresh in state["refreshers"]:
                refresh(panel)

        show_placeholder("Connect a device to show its controls.")

        # --- connection: connect / scan ------------------------------------
        def do_connect(device_name: str) -> None:
            from galileo.core.devices import DeviceCategory
            adapter = self._connect_device_adapter(
                DeviceCategory.SWITCH, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to switch device {device_name!r} — see log.", 6000)
                return
            from galileo.current_object import pier_key
            state["adapter"] = adapter
            adapters_by_pier[pier_key(self._current_pier)] = adapter
            self._window.statusBar().showMessage(f"Connected to switch device {device_name!r}.", 4000)
            refresh_panel()

        def connect_clicked() -> None:
            device_name = device_combo.currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a switch device first.")
                return
            do_connect(device_name)

        connect_btn.clicked.connect(connect_clicked)

        def device_picked() -> None:
            from galileo.core.devices import DeviceCategory
            apply_driver_info(self._lookup_driver_info(
                DeviceCategory.SWITCH, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip(),
            ))

        device_combo.activated.connect(lambda _index: device_picked())

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
                adapter = get_adapter_class(DeviceCategory.SWITCH)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.SWITCH))
            except Exception:
                logger.exception("Switch scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Switch scan failed — see log.", 6000)
            current = device_combo.currentText()
            device_combo.blockSignals(True)
            device_combo.clear()
            device_combo.addItem("")
            for name in devices:
                device_combo.addItem(name)
            if current and device_combo.findText(current) < 0:
                device_combo.addItem(current)
            device_combo.setCurrentIndex(max(device_combo.findText(current), 0))
            device_combo.blockSignals(False)
            if devices:
                logger.info("Detected %d %s switch device(s) at %s:%s: %s", len(devices), driver, server, port, ", ".join(devices))
                self._window.statusBar().showMessage(f"Found {len(devices)} device(s) — see log.", 4000)
            else:
                logger.info("No %s switch devices found at %s:%s.", driver, server, port)
                self._window.statusBar().showMessage(f"No {driver} switch devices found at {server}:{port}.", 4000)

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

        def save_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_device_config
            save_device_config(
                self._current_pier, "switch",
                driver=driver_combo.currentText(), server=server_edit.text().strip(),
                port=port_spin.value(), device_name=device_combo.currentText().strip() or None,
            )
            logger.info(
                "Saved switch settings for Pier %r: %s %s:%s, device: %s",
                self._current_pier.name, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip() or "(none)",
            )
            self._window.statusBar().showMessage(f"Saved switch settings for Pier {self._current_pier.name!r}.", 4000)

        save_btn.clicked.connect(save_config)

        def reload_page() -> None:
            cfg = None
            if self._current_pier is not None:
                from galileo.observatory import get_device_config
                try:
                    cfg = get_device_config(self._current_pier, "switch")
                except Exception:
                    logger.exception("Could not load saved switch config")
            widgets = (driver_combo, server_edit, port_spin, device_combo)
            for w in widgets:
                w.blockSignals(True)
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
                for w in widgets:
                    w.blockSignals(False)
            apply_driver_info(None)

            from galileo.current_object import pier_key
            adapter = adapters_by_pier.get(pier_key(self._current_pier))
            state["adapter"] = adapter
            if adapter is not None:
                refresh_panel()
            else:
                show_placeholder("Connect a device to show its controls.")

        def autoconnect_page() -> None:
            from galileo.current_object import pier_key
            device_name = device_combo.currentText().strip()
            if device_name and adapters_by_pier.get(pier_key(self._current_pier)) is None:
                do_connect(device_name)

        def disconnect_page() -> None:
            """Pier-level Disconnect: tear down this Pier's switch connection."""
            from galileo.current_object import pier_key
            adapter = adapters_by_pier.pop(pier_key(self._current_pier), None)
            if adapter is None:
                return
            import asyncio
            try:
                asyncio.run(adapter.disconnect())
            except Exception:
                logger.exception("Could not disconnect the switch device")
            state["adapter"] = None
            show_placeholder("Connect a device to show its controls.")
            self._window.statusBar().showMessage("Switch device disconnected.", 4000)

        timer = QTimer(page)
        timer.timeout.connect(_when_visible(page, refresh_panel))
        timer.start(_REFRESH_MS)

        state["reload"] = reload_page
        state["autoconnect"] = autoconnect_page
        state["disconnect"] = disconnect_page
        state["connected"] = lambda: state.get("adapter") is not None
        state["adapter_for"] = adapters_by_pier.get          # any Pier's connection, by pier_key
        self._device_pages["switch"] = state
        reload_page()
        if self._startup_autoconnect_allowed():
            autoconnect_page()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll
