# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The generic device-category page builder used by categories that don't have a bespoke page yet, plus its shared load/save persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _CATEGORY_ENUM, _DEFAULT_PORTS, QWidget

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowDeviceConfigMixin:
    def _build_device_config_page(self: AppWindowState, cat_id: str, label: str) -> QWidget:
        """One Equipment device-category page: Driver/Server table + scan (ARCH-050)."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
            QComboBox, QLineEdit, QSpinBox, QPushButton, QListWidget, QListWidgetItem, QHeaderView,
        )
        from PySide6.QtCore import Qt

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel(label)
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        table = QTableWidget(1, 4)
        table.setHorizontalHeaderLabels(["Driver", "Server", "Port", ""])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.setMaximumHeight(70)
        table.setSelectionMode(QTableWidget.NoSelection)

        driver_combo = QComboBox()
        driver_combo.addItems(["Alpaca", "INDI"])
        table.setCellWidget(0, 0, driver_combo)

        server_edit = QLineEdit()
        server_edit.setPlaceholderText("FQDN or IP, e.g. seestar.local or 192.168.1.50")
        server_edit.setMaxLength(40)
        table.setCellWidget(0, 1, server_edit)

        # Alpaca has no single standard port — 11111 is the common ASCOM
        # Remote/simulator default, but plenty of real devices (e.g. Seestar's
        # Alpaca bridge, on 32323) use something else entirely, so this must
        # be a field the user can see and change rather than a silent guess
        # baked into the driver logic (a wrong guess here previously surfaced
        # as a confusing "connection actively refused" error).
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

        refresh_btn = QPushButton("Connect")
        refresh_btn.setObjectName("AccentButton")
        table.setCellWidget(0, 3, refresh_btn)

        layout.addWidget(table)

        driver_info_row, apply_driver_info = self._build_driver_info_row()
        layout.addLayout(driver_info_row)

        results = QListWidget()
        layout.addWidget(results, 1)

        # Tracks this page's live state (including the device picked from the
        # scan results) so it can be saved, reloaded, and refreshed whenever
        # the selected Pier changes — see _save_device_config/_on_pier_changed.
        page_state = {
            "driver": driver_combo,
            "server": server_edit,
            "port": port_spin,
            "results": results,
            "selected_device": None,
            "apply_driver_info": apply_driver_info,
        }

        def run_scan() -> None:
            results.clear()
            page_state["selected_device"] = None
            apply_driver_info(None)
            server = server_edit.text().strip() or "localhost"
            port = port_spin.value()
            driver = driver_combo.currentText()
            category = _CATEGORY_ENUM[cat_id]
            try:
                import asyncio
                if driver == "INDI":
                    from galileo.adapters.indi import get_adapter_class
                    adapter = get_adapter_class(category)(host=server, port=port)
                else:
                    from galileo.adapters.alpaca import get_adapter_class
                    adapter = get_adapter_class(category)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(category))
            except Exception as exc:
                logger.exception("Device scan failed for %s on %s:%s", cat_id, server, port)
                results.addItem(f"Scan failed: {exc}")
                return
            if not devices:
                results.addItem(f"No {driver} devices found for {label.lower()} at {server}:{port}.")
                return
            for name in devices:
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, True)
                results.addItem(item)

        refresh_btn.clicked.connect(run_scan)

        def _on_result_clicked(item: QListWidgetItem) -> None:
            # Only an actual scanned device is selectable — not the
            # "No devices found" / "Scan failed" info rows above.
            if item.data(Qt.UserRole):
                page_state["selected_device"] = item.text()
                apply_driver_info(self._lookup_driver_info(
                    _CATEGORY_ENUM[cat_id], driver_combo.currentText(),
                    server_edit.text().strip(), port_spin.value(), item.text(),
                ))

        results.itemClicked.connect(_on_result_clicked)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        save_btn.setToolTip("Save this device's settings under the selected Observatory and Pier.")
        save_btn.clicked.connect(lambda: self._save_device_config(cat_id, page_state))
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        layout.addWidget(log_heading)
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)
        layout.addWidget(log_pane)

        page_state["reload"] = lambda: self._load_device_config_into_page(cat_id, page_state)
        self._device_pages[cat_id] = page_state
        page_state["reload"]()

        return page

    def _load_device_config_into_page(self: AppWindowState, cat_id: str, state: dict) -> None:
        """Populate one device-category page's fields from the saved config
        for the current Pier, or reset it to defaults if there is none."""
        driver_combo = state["driver"]
        server_edit = state["server"]
        port_spin = state["port"]
        results = state["results"]

        cfg = None
        if self._current_pier is not None:
            from galileo.observatory import get_device_config
            try:
                cfg = get_device_config(self._current_pier, cat_id)
            except Exception:
                logger.exception("Could not load saved device config for %s", cat_id)

        # Not looked up here: a saved device may be unreachable, and blocking
        # the Pier switch on a network timeout per page isn't worth a label.
        # It fills in when the device is next picked from a scan.
        state["apply_driver_info"](None)

        driver_combo.blockSignals(True)
        server_edit.blockSignals(True)
        port_spin.blockSignals(True)
        try:
            results.clear()
            if cfg is not None:
                idx = driver_combo.findText(cfg.driver)
                if idx >= 0:
                    driver_combo.setCurrentIndex(idx)
                server_edit.setText(cfg.server)
                port_spin.setValue(cfg.port)
                state["selected_device"] = cfg.device_name
                if cfg.device_name:
                    from PySide6.QtWidgets import QListWidgetItem
                    from PySide6.QtCore import Qt
                    item = QListWidgetItem(cfg.device_name)
                    item.setData(Qt.UserRole, True)
                    results.addItem(item)
            else:
                driver_combo.setCurrentIndex(0)
                server_edit.clear()
                port_spin.setValue(_DEFAULT_PORTS.get(driver_combo.currentText(), _DEFAULT_PORTS["Alpaca"]))
                state["selected_device"] = None
        finally:
            driver_combo.blockSignals(False)
            server_edit.blockSignals(False)
            port_spin.blockSignals(False)

    def _save_device_config(self: AppWindowState, cat_id: str, state: dict) -> None:
        """Save button handler: persist one device-category page's settings
        under the currently selected Observatory and Pier."""
        if self._current_pier is None:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self._window,
                "No Pier selected",
                "Select (or create) an Observatory and Pier before saving equipment settings.",
            )
            return

        from galileo.observatory import save_device_config
        try:
            save_device_config(
                self._current_pier,
                cat_id,
                driver=state["driver"].currentText(),
                server=state["server"].text().strip(),
                port=state["port"].value(),
                device_name=state["selected_device"],
            )
        except Exception:
            logger.exception(
                "Could not save device config for %s on Pier %r", cat_id, self._current_pier.name
            )
            return
        logger.info(
            "Saved %s settings for Pier %r: %s %s:%s, device: %s",
            cat_id, self._current_pier.name, state["driver"].currentText(),
            state["server"].text().strip(), state["port"].value(),
            state["selected_device"] or "(none)",
        )
        self._window.statusBar().showMessage(
            f"Saved {cat_id} settings for Pier {self._current_pier.name!r}.", 4000
        )
