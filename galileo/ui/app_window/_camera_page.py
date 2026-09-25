# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Camera device-category page."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _parse_alpaca_device_number, _DEFAULT_PORTS, QWidget

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowCameraPageMixin:
    def _build_camera_page(self: AppWindowState) -> QWidget:
        """Camera device-category page: one shared Driver/Server/Port
        connection plus any number of independently configured camera
        panels — a Primary imaging camera, always present, and additional
        non-guide cameras (e.g. a Seestar S30 Pro's wide-field camera) added
        one at a time via the "+" button next to the heading, each sharing
        the connection above but otherwise a separate device. Panels live in
        a scroll area since the list has no fixed upper bound."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QLabel, QTableWidget,
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton, QHeaderView,
            QScrollArea, QMessageBox,
        )

        page = QWidget()
        page.setObjectName("CameraPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        heading = QLabel("Camera")
        heading.setObjectName("PageTitle")
        heading_row.addWidget(heading)
        add_camera_btn = QPushButton("+")
        add_camera_btn.setObjectName("AccentButton")
        add_camera_btn.setFixedWidth(28)
        add_camera_btn.setToolTip(
            "Add another camera sharing this connection (e.g. a Seestar "
            "S30 Pro's second, wide-field camera)."
        )
        heading_row.addWidget(add_camera_btn)
        heading_row.addStretch(1)
        layout.addLayout(heading_row)

        # --- shared connection row (one Driver/Server/Port for every panel) -
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

        # --- N independent camera panels, sharing the connection above -----
        # A scroll area since the panel count has no fixed upper bound (the
        # connection table, Save button, and log pane below all stay fixed
        # in place while this area scrolls internally). Scan results aren't
        # shown here — they go to the log pane below and populate each
        # panel's Device combo directly (see run_scan/_refresh_slot_choices).
        panels: list[dict] = []

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        panels_container = QWidget()
        panels_layout = QVBoxLayout(panels_container)
        panels_layout.setContentsMargins(0, 0, 0, 0)
        panels_layout.setSpacing(10)
        panels_layout.addStretch(1)
        scroll_area.setWidget(panels_container)
        layout.addWidget(scroll_area, 1)

        def _build_camera_panel(removable: bool) -> dict:
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

            form = QFormLayout()
            outer.addLayout(form)

            device_combo = QComboBox()
            device_combo.setEditable(True)
            device_combo.addItem("")
            form.addRow("Device", device_combo)

            driver_info_row, apply_driver_info = self._build_driver_info_row()
            form.addRow(driver_info_row)

            pixel_size = QDoubleSpinBox()
            pixel_size.setRange(0.0, 50.0)
            pixel_size.setDecimals(3)
            pixel_size.setSuffix(" µm")
            form.addRow("Pixel size", pixel_size)

            sensor_w = QSpinBox()
            sensor_w.setRange(0, 20000)
            sensor_w.setSuffix(" px")
            form.addRow("Sensor width", sensor_w)

            sensor_h = QSpinBox()
            sensor_h.setRange(0, 20000)
            sensor_h.setSuffix(" px")
            form.addRow("Sensor height", sensor_h)

            sensor_name = QLineEdit()
            sensor_name.setReadOnly(True)
            sensor_name.setPlaceholderText("—")
            form.addRow("Sensor name", sensor_name)

            from galileo.debayer import BAYER_PATTERNS
            bayer_combo = QComboBox()
            bayer_combo.addItems(BAYER_PATTERNS)
            bayer_combo.setToolTip(
                "The layout of a one-shot-colour sensor's colour-filter mosaic, read from the top-left "
                "2x2 pixels (RGGB is the most common). Used by the Imaging tab's Debayer option; "
                "if the colours look wrong, try another. Ignored for a monochrome camera."
            )
            form.addRow("Bayer pattern", bayer_combo)

            download_btn = QPushButton("Download Info")
            download_btn.setToolTip(
                "Live-query this device's pixel size and sensor dimensions "
                "over its own connection (works today for Alpaca/ASCOM "
                "devices; INDI support depends on the driver)."
            )
            form.addRow(download_btn)

            return {
                "frame": frame, "title_label": title_label, "remove_btn": remove_btn,
                "connect_btn": connect_btn,
                "device": device_combo, "apply_driver_info": apply_driver_info,
                "pixel_size": pixel_size,
                "sensor_w": sensor_w, "sensor_h": sensor_h, "sensor_name": sensor_name,
                "bayer": bayer_combo, "download": download_btn,
            }

        def _renumber_panels() -> None:
            for i, panel in enumerate(panels):
                panel["title_label"].setText("Primary Camera" if i == 0 else f"Camera {i + 1}")

        def _remove_panel(panel: dict) -> None:
            if panel not in panels or panel is panels[0]:
                return
            panels.remove(panel)
            panel["frame"].setParent(None)
            panel["frame"].deleteLater()
            _renumber_panels()

        # The most recent scan's results, kept so a camera panel added *after*
        # scanning (e.g. the user scans, sees a second device, then clicks
        # "+" to add a panel for it) starts with that device already
        # selectable, instead of an empty, unpopulated combo.
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

        def _add_panel() -> dict:
            panel = _build_camera_panel(removable=len(panels) > 0)
            panels.append(panel)
            panels_layout.insertWidget(panels_layout.count() - 1, panel["frame"])
            _renumber_panels()
            _populate_device_combo(panel["device"], last_scanned_devices)
            if panel["remove_btn"] is not None:
                panel["remove_btn"].clicked.connect(lambda: _remove_panel(panel))
            panel["connect_btn"].clicked.connect(lambda: _connect_clicked(panel))
            panel["download"].clicked.connect(lambda: _download_info(panel))
            panel["device"].activated.connect(lambda _index: _lookup_panel_driver_info(panel))
            return panel

        def _set_panel_count(count: int) -> None:
            count = max(count, 1)
            while len(panels) < count:
                _add_panel()
            while len(panels) > count:
                _remove_panel(panels[-1])

        add_camera_btn.clicked.connect(_add_panel)

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
                    adapter = get_adapter_class(DeviceCategory.CAMERA)(host=server, port=port)
                else:
                    from galileo.adapters.alpaca import get_adapter_class
                    adapter = get_adapter_class(DeviceCategory.CAMERA)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.CAMERA))
            except Exception:
                logger.exception("Camera scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Camera scan failed — see log.", 6000)
                _refresh_slot_choices([])
                return
            if devices:
                logger.info(
                    "Detected %d %s camera device(s) at %s:%s: %s",
                    len(devices), driver, server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} camera device(s) — see log.", 4000)
            else:
                logger.info("No %s camera devices found at %s:%s.", driver, server, port)
                self._window.statusBar().showMessage(f"No {driver} camera devices found at {server}:{port}.", 4000)
            _refresh_slot_choices(devices)

        scan_btn.clicked.connect(run_scan)

        def _lookup_panel_driver_info(panel: dict) -> None:
            """Show the driver of the device just picked in *panel*, without connecting it."""
            from galileo.core.devices import DeviceCategory
            panel["apply_driver_info"](self._lookup_driver_info(
                DeviceCategory.CAMERA, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), panel["device"].currentText().strip(),
            ))

        def _show_connected_driver_info(panel: dict, slot_label: str) -> None:
            """Fill *panel*'s driver info from its live, just-connected backend."""
            adapter = self._camera_backends.get(slot_label)
            if adapter is None:
                return
            import asyncio
            try:
                panel["apply_driver_info"](asyncio.run(adapter.get_driver_info()))
            except Exception:
                logger.exception("Could not read driver info from connected %s", slot_label)

        def _connect_clicked(panel: dict) -> None:
            """Manually connect one camera panel — previously the Camera page
            had no way to do this at all: a device only ever got connected by
            ``autoconnect_page()`` at page build or Pier switch, so a camera
            just configured and saved stayed "not connected" (Imaging tab
            included) until one of those happened to run again."""
            device_name = panel["device"].currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a camera device first.")
                return
            index = panels.index(panel)
            slot_label = "primary camera" if index == 0 else f"camera {index + 1}"
            self._connect_camera_device(
                slot_label, driver_combo.currentText(), server_edit.text().strip() or "localhost",
                port_spin.value(), device_name,
            )
            _show_connected_driver_info(panel, slot_label)

        def _download_info(panel: dict) -> None:
            device_name = panel["device"].currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a camera device first.")
                return
            driver = driver_combo.currentText()
            server = server_edit.text().strip() or "localhost"
            port = port_spin.value()

            import asyncio
            from galileo.core.devices import DeviceCategory
            try:
                if driver == "INDI":
                    from galileo.adapters.indi import get_adapter_class
                    adapter = get_adapter_class(DeviceCategory.CAMERA)(
                        host=server, port=port, device_name=device_name,
                    )
                else:
                    from galileo.adapters.alpaca import get_adapter_class
                    kwargs = {}
                    device_number = _parse_alpaca_device_number(device_name)
                    if device_number is not None:
                        kwargs["device_number"] = device_number
                    adapter = get_adapter_class(DeviceCategory.CAMERA)(host=server, port=port, **kwargs)

                async def _fetch():
                    await adapter.connect()
                    try:
                        return await adapter.get_sensor_info()
                    finally:
                        await adapter.disconnect()

                info = asyncio.run(_fetch())
            except Exception:
                logger.exception(
                    "Could not download sensor info for %r at %s:%s", device_name, server, port
                )
                self._window.statusBar().showMessage(
                    f"Could not download info for {device_name!r} — see log.", 6000
                )
                return

            if info.get("pixel_size_um") is not None:
                panel["pixel_size"].setValue(float(info["pixel_size_um"]))
            if info.get("sensor_width_px") is not None:
                panel["sensor_w"].setValue(int(info["sensor_width_px"]))
            if info.get("sensor_height_px") is not None:
                panel["sensor_h"].setValue(int(info["sensor_height_px"]))
            panel["sensor_name"].setText(str(info.get("sensor_name") or ""))
            self._window.statusBar().showMessage(f"Downloaded sensor info for {device_name!r}.", 4000)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        save_btn.setToolTip("Save every camera's settings under the selected Observatory and Pier.")
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        layout.addWidget(log_heading)
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)
        layout.addWidget(log_pane)

        def _slot_for_index(i: int) -> str:
            return "primary" if i == 0 else f"camera_{i + 1}"

        def save_camera_config() -> None:
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
                    self._current_pier, "camera", driver=driver, server=server, port=port,
                    device_name=panel["device"].currentText().strip() or None, slot=slot,
                    pixel_size_um=panel["pixel_size"].value() or None,
                    sensor_width_px=panel["sensor_w"].value() or None,
                    sensor_height_px=panel["sensor_h"].value() or None,
                    sensor_name=panel["sensor_name"].text().strip() or None,
                    bayer_pattern=panel["bayer"].currentText(),
                )

            # Prune slots from cameras that were since removed from the page.
            for stale_slot in set(list_device_config_slots(self._current_pier, "camera")) - used_slots:
                delete_device_config(self._current_pier, "camera", slot=stale_slot)

            logger.info(
                "Saved camera settings for Pier %r: %s %s:%s, device(s): %s",
                self._current_pier.name, driver, server, port,
                ", ".join(p["device"].currentText().strip() or "(none)" for p in panels),
            )
            self._window.statusBar().showMessage(
                f"Saved camera settings for Pier {self._current_pier.name!r}.", 4000
            )
            # A newly configured camera previously stayed "not connected"
            # (Imaging tab included) until the next Pier switch or page
            # rebuild, since nothing but those two ever called autoconnect —
            # Save is exactly when a device becomes connectable, so attempt
            # it now too. autoconnect_page() skips slots already connected,
            # so this doesn't disrupt an unrelated panel's live connection.
            autoconnect_page()

        save_btn.clicked.connect(save_camera_config)

        def _load_panel(panel: dict, cfg) -> None:
            combo = panel["device"]
            combo.blockSignals(True)
            if cfg is not None and cfg.device_name and combo.findText(cfg.device_name) < 0:
                combo.addItem(cfg.device_name)
            combo.setCurrentText(cfg.device_name if cfg is not None and cfg.device_name else "")
            combo.blockSignals(False)
            panel["pixel_size"].setValue(cfg.pixel_size_um if cfg is not None and cfg.pixel_size_um else 0.0)
            panel["sensor_w"].setValue(cfg.sensor_width_px if cfg is not None and cfg.sensor_width_px else 0)
            panel["sensor_h"].setValue(cfg.sensor_height_px if cfg is not None and cfg.sensor_height_px else 0)
            panel["sensor_name"].setText(cfg.sensor_name if cfg is not None and cfg.sensor_name else "")
            from galileo.debayer import BAYER_PATTERNS, DEFAULT_PATTERN
            saved_pattern = cfg.bayer_pattern if cfg is not None else DEFAULT_PATTERN
            panel["bayer"].setCurrentText(saved_pattern if saved_pattern in BAYER_PATTERNS else DEFAULT_PATTERN)
            # Filled by autoconnect (below) or when a device is next picked —
            # not looked up here, so a Pier switch never waits on the network.
            panel["apply_driver_info"](None)

        def reload_page() -> None:
            from galileo.observatory import get_device_config, list_device_config_slots

            saved_slots: list[str] = []
            if self._current_pier is not None:
                try:
                    saved_slots = list_device_config_slots(self._current_pier, "camera")
                except Exception:
                    logger.exception("Could not load saved camera config")

            extra_count = 0
            for slot in saved_slots:
                if slot.startswith("camera_"):
                    try:
                        extra_count = max(extra_count, int(slot.rsplit("_", 1)[1]) - 1)
                    except ValueError:
                        pass
            _set_panel_count(1 + extra_count)

            primary_cfg = None
            if self._current_pier is not None:
                try:
                    primary_cfg = get_device_config(self._current_pier, "camera", slot="primary")
                except Exception:
                    logger.exception("Could not load saved camera config")

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
                    get_device_config(self._current_pier, "camera", slot=_slot_for_index(i))
                    if self._current_pier is not None else None
                )
                _load_panel(panel, cfg)

        def autoconnect_page() -> None:
            for i, panel in enumerate(panels):
                device_name = panel["device"].currentText().strip()
                if not device_name:
                    continue
                slot_label = "primary camera" if i == 0 else f"camera {i + 1}"
                if slot_label in self._camera_backends:
                    # Already connected — called from more than just page-build/
                    # Pier-switch now (also after Save), so this must be safe to
                    # call again without disrupting an unrelated panel's live
                    # connection (or this one's, mid-exposure).
                    continue
                self._connect_camera_device(
                    slot_label, driver_combo.currentText(), server_edit.text().strip(),
                    port_spin.value(), device_name,
                )
                _show_connected_driver_info(panel, slot_label)

        state = {"reload": reload_page, "autoconnect": autoconnect_page}
        self._device_pages["camera"] = state
        reload_page()
        autoconnect_page()

        return page
