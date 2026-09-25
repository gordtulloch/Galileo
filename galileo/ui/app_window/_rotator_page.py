# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Rotator device-category page."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _when_visible, _DEFAULT_PORTS, QLabel, QWidget

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowRotatorPageMixin:
    def _build_rotator_page(self: AppWindowState) -> QWidget:
        """Rotator device-category page, modeled on the reference derotation
        screen (assets/samples/rot.png) but keeping this app's own
        Driver/Server/Port/Scan + Device/Connect line at the top like every
        other Equipment page. Left: backlash, the rotator's live position
        with Goto/Reverse/Set-as-zero (EQP-ROT-010), derotation-rate
        correction and Start/Stop Derotation. Right: the derotation target —
        site, date/UTC, target RA/Dec (typed, or synced from the
        newest FITS file in a folder) — with the resulting Alt/Az and field
        rotation rate from ``galileo.derotation``."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel,
            QTableWidget, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox,
            QPushButton, QCheckBox, QHeaderView, QMessageBox, QScrollArea,
            QSlider, QFileDialog,
        )
        from PySide6.QtCore import QTimer, Qt

        import datetime
        import time
        from galileo import derotation
        from galileo.exceptions import DevicePropertyError

        page = QWidget()
        page.setObjectName("RotatorPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Rotator")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        # --- connection row (same as every other Equipment page) --------
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

        # --- controls (left) + derotation target (right) ----------------
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

        main_content = QWidget()
        main_row = QHBoxLayout(main_content)
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(24)

        left_frame, left = _panel()

        # Backlash
        left.addWidget(_heading("Backlash"))
        backlash_row = QHBoxLayout()
        backlash_slider = QSlider(Qt.Horizontal)
        backlash_slider.setRange(0, 1000)  # tenths of a step: 0.0 – 100.0
        backlash_value = QLabel("0.0")
        backlash_ok = QPushButton("OK")
        backlash_ok.setObjectName("AccentButton")
        backlash_row.addWidget(backlash_slider, 1)
        backlash_row.addWidget(backlash_value)
        backlash_row.addWidget(backlash_ok)
        left.addLayout(backlash_row)
        backlash_slider.valueChanged.connect(lambda v: backlash_value.setText(f"{v / 10:.1f}"))

        # Position
        left.addWidget(_heading("Virtual Mechanical Position"))
        position_value = QLabel("—")
        position_value.setAlignment(Qt.AlignCenter)
        big = position_value.font()
        big.setPointSize(big.pointSize() + 8)
        big.setBold(True)
        position_value.setFont(big)
        left.addWidget(position_value)
        position_detail = QLabel("")
        position_detail.setAlignment(Qt.AlignCenter)
        left.addWidget(position_detail)

        goto_row = QHBoxLayout()
        goto_spin = QDoubleSpinBox()
        goto_spin.setRange(0.0, 359.99)
        goto_spin.setDecimals(2)
        goto_spin.setSuffix("°")
        goto_btn = QPushButton("Goto")
        goto_btn.setObjectName("AccentButton")
        goto_row.addWidget(goto_spin, 1)
        goto_row.addWidget(goto_btn)
        left.addLayout(goto_row)
        goto_hint = QLabel("(0 – 359.99)")
        goto_hint.setAlignment(Qt.AlignCenter)
        left.addWidget(goto_hint)

        reverse_check = QCheckBox("Reverse")
        reverse_check.setToolTip(
            "Reverse the rotator's direction of travel. While derotating this "
            "also flips the derotation direction, so a reversed rotator still "
            "compensates the field the right way."
        )
        left.addWidget(reverse_check)
        zero_btn = QPushButton("Set Current Position as Zero")
        zero_btn.setToolTip("Declare the rotator's current physical position to be 0°.")
        left.addWidget(zero_btn)

        # Derotation rate correction
        left.addWidget(_heading("Derotation Rate Correction"))
        correction_row = QHBoxLayout()
        correction_slider = QSlider(Qt.Horizontal)
        correction_slider.setRange(-100, 100)
        correction_label = QLabel("0%")
        correction_ok = QPushButton("OK")
        correction_ok.setObjectName("AccentButton")
        correction_ok.setToolTip("Scale the computed derotation rate by this percentage (trim for a drifting field).")
        correction_row.addWidget(correction_slider, 1)
        correction_row.addWidget(correction_label)
        correction_row.addWidget(correction_ok)
        left.addLayout(correction_row)
        correction_slider.valueChanged.connect(lambda v: correction_label.setText(f"{v}%"))

        derotate_btn = QPushButton("Start Derotation")
        derotate_btn.setObjectName("AccentButton")
        left.addWidget(derotate_btn)
        left.addStretch(1)
        main_row.addWidget(left_frame, 1)

        right_frame, right = _panel()
        right.addWidget(_heading("Derotation"))

        clock_row = QHBoxLayout()
        date_value = QLabel("—")
        utc_value = QLabel("—")
        for label in (date_value, utc_value):
            font = label.font()
            font.setBold(True)
            label.setFont(font)
        clock_row.addWidget(date_value)
        clock_row.addStretch(1)
        clock_row.addWidget(QLabel("UTC"))
        clock_row.addWidget(utc_value)
        right.addLayout(clock_row)

        site_row = QGridLayout()
        lat_spin = QDoubleSpinBox()
        lat_spin.setRange(-90.0, 90.0)
        lat_spin.setDecimals(4)
        lat_spin.setSuffix("° N")
        lon_spin = QDoubleSpinBox()
        lon_spin.setRange(-180.0, 180.0)
        lon_spin.setDecimals(4)
        lon_spin.setSuffix("° E")
        lat_spin.setToolTip("Site latitude (north positive). Filled from the selected Observatory when it has one.")
        lon_spin.setToolTip("Site longitude (east positive). Filled from the selected Observatory when it has one.")
        site_row.addWidget(QLabel("Latitude"), 0, 0)
        site_row.addWidget(QLabel("Longitude"), 0, 1)
        site_row.addWidget(lat_spin, 1, 0)
        site_row.addWidget(lon_spin, 1, 1)
        right.addLayout(site_row)

        right.addWidget(_heading("Target"))
        right.addWidget(QLabel("Sync from FITS"))
        fits_path_edit = QLineEdit()
        fits_path_edit.setPlaceholderText("Folder of FITS frames")
        right.addWidget(fits_path_edit)
        fits_row = QHBoxLayout()
        fits_browse_btn = QPushButton("Browse Folder")
        fits_sync_btn = QPushButton("Sync")
        fits_sync_btn.setToolTip("Use the pointing recorded in the newest FITS file in this folder.")
        fits_row.addWidget(fits_browse_btn, 1)
        fits_row.addWidget(fits_sync_btn, 1)
        right.addLayout(fits_row)

        ra_row = QHBoxLayout()
        ra_row.addWidget(QLabel("RA"))
        ra_h, ra_m = QSpinBox(), QSpinBox()
        ra_s = QDoubleSpinBox()
        ra_h.setRange(0, 23)
        ra_h.setSuffix(" h")
        ra_m.setRange(0, 59)
        ra_m.setSuffix(" m")
        ra_s.setRange(0.0, 59.9)
        ra_s.setDecimals(1)
        ra_s.setSuffix(" s")
        for widget in (ra_h, ra_m, ra_s):
            ra_row.addWidget(widget, 1)
        right.addLayout(ra_row)

        dec_row = QHBoxLayout()
        dec_row.addWidget(QLabel("DEC"))
        dec_sign = QComboBox()
        dec_sign.addItems(["+", "−"])
        dec_d, dec_m = QSpinBox(), QSpinBox()
        dec_s = QDoubleSpinBox()
        dec_d.setRange(0, 90)
        dec_d.setSuffix(" °")
        dec_m.setRange(0, 59)
        dec_m.setSuffix(" ′")
        dec_s.setRange(0.0, 59.9)
        dec_s.setDecimals(1)
        dec_s.setSuffix(" ″")
        dec_row.addWidget(dec_sign)
        for widget in (dec_d, dec_m, dec_s):
            dec_row.addWidget(widget, 1)
        right.addLayout(dec_row)

        altaz_row = QHBoxLayout()
        altaz_row.addWidget(QLabel("Altitude"))
        altitude_value = QLabel("—")
        altaz_row.addWidget(altitude_value, 1)
        altaz_row.addWidget(QLabel("Azimuth"))
        azimuth_value = QLabel("—")
        altaz_row.addWidget(azimuth_value, 1)
        right.addLayout(altaz_row)

        right.addWidget(_heading("Derotation Rate — Degrees/Minute"))
        rate_value = QLabel("—")
        rate_value.setAlignment(Qt.AlignCenter)
        rate_value.setFont(big)
        right.addWidget(rate_value)
        right.addStretch(1)
        main_row.addWidget(right_frame, 1)

        main_scroll = QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setFrameShape(QFrame.NoFrame)
        main_scroll.setWidget(main_content)
        layout.addWidget(main_scroll, 1)

        state: dict = {
            "adapter": None, "target": None, "correction": 0.0,
            "derotator": None, "position": None,
        }
        device_controls = (backlash_slider, backlash_ok, goto_spin, goto_btn, reverse_check, zero_btn)

        # --- target / derotation maths ----------------------------------
        def _spins_to_target() -> tuple:
            ra = (ra_h.value() + ra_m.value() / 60.0 + ra_s.value() / 3600.0) * 15.0
            dec = dec_d.value() + dec_m.value() / 60.0 + dec_s.value() / 3600.0
            return ra, (-dec if dec_sign.currentText() == "−" else dec)

        def _target_edited() -> None:
            state["target"] = _spins_to_target()
            _recompute()

        for widget in (ra_h, ra_m, ra_s, dec_d, dec_m, dec_s):
            widget.valueChanged.connect(_target_edited)
        dec_sign.currentIndexChanged.connect(_target_edited)
        lat_spin.valueChanged.connect(lambda _v: _recompute())
        lon_spin.valueChanged.connect(lambda _v: _recompute())

        def _set_target(ra_deg: float, dec_deg: float) -> None:
            _, h, m, s = derotation.to_sexagesimal((ra_deg / 15.0) % 24.0)
            sign, d, arcmin, arcsec = derotation.to_sexagesimal(dec_deg)
            widgets = (ra_h, ra_m, ra_s, dec_d, dec_m, dec_s, dec_sign)
            for widget in widgets:
                widget.blockSignals(True)
            try:
                ra_h.setValue(h % 24)
                ra_m.setValue(m)
                ra_s.setValue(s)
                dec_sign.setCurrentText("−" if sign < 0 else "+")
                dec_d.setValue(d)
                dec_m.setValue(arcmin)
                dec_s.setValue(arcsec)
            finally:
                for widget in widgets:
                    widget.blockSignals(False)
            state["target"] = (ra_deg % 360.0, dec_deg)
            _recompute()

        def _current_rate() -> tuple | None:
            """``(alt, az, effective deg/min)`` for the target now, or ``None``
            if there's no target. The rate is ``None`` while the target is
            below the horizon."""
            if state["target"] is None:
                return None
            alt, az = derotation.radec_to_altaz(
                state["target"][0], state["target"][1], lat_spin.value(), lon_spin.value(),
            )
            if alt <= 0.0:
                return alt, az, None
            rate = derotation.field_rotation_rate_deg_per_min(lat_spin.value(), alt, az)
            rate *= 1.0 + state["correction"] / 100.0
            if reverse_check.isChecked():
                rate = -rate
            return alt, az, rate

        def _recompute() -> None:
            now = datetime.datetime.now(datetime.UTC)
            date_value.setText(now.strftime("%Y - %m - %d"))
            utc_value.setText(now.strftime("%H : %M : %S"))
            result = _current_rate()
            if result is None:
                altitude_value.setText("—")
                azimuth_value.setText("—")
                rate_value.setText("—")
                return
            alt, az, rate = result
            altitude_value.setText(f"{alt:.2f}°")
            azimuth_value.setText(f"{az:.2f}°")
            rate_value.setText("below horizon" if rate is None else f"{rate:.4f}")

        clock_timer = QTimer(page)
        clock_timer.timeout.connect(_recompute)
        clock_timer.start(1000)

        # --- device actions ---------------------------------------------
        def _call(method: str, *args, action: str) -> bool:
            """Run one adapter command; report failure in the status bar/log."""
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the rotator first.")
                return False
            import asyncio
            try:
                asyncio.run(getattr(adapter, method)(*args))
            except DevicePropertyError as exc:
                logger.warning("Rotator %s not available: %s", action, exc)
                self._window.statusBar().showMessage(str(exc), 8000)
                return False
            except Exception:
                logger.exception("Rotator %s failed", action)
                self._window.statusBar().showMessage(f"Rotator {action} failed — see log.", 6000)
                return False
            return True

        def _apply_status(status: dict) -> None:
            connected = bool(status)
            if connected:  # an empty status is "not connected": keep what a device pick looked up
                apply_driver_info(status)
            derotating = state["derotator"] is not None
            for widget in device_controls:
                locked = derotating and widget in (goto_spin, goto_btn, zero_btn)
                widget.setEnabled(connected and not locked)
            position = status.get("position")
            state["position"] = position
            position_value.setText("—" if position is None else f"{position:.2f}")
            mechanical = status.get("mechanical_position")
            bits = []
            if mechanical is not None:
                bits.append(f"Mechanical {mechanical:.2f}°")
            if position is not None:
                bits.append(f"Sky {position:.2f}°")
            if status.get("is_moving"):
                bits.append("moving")
            position_detail.setText(" · ".join(bits))
            if status.get("reverse") is not None:
                reverse_check.blockSignals(True)
                reverse_check.setChecked(bool(status["reverse"]))
                reverse_check.blockSignals(False)
            supported = bool(status.get("backlash_supported"))
            backlash_slider.setEnabled(connected and supported)
            backlash_ok.setEnabled(connected and supported)
            tip = "" if supported or not connected else "This rotator's driver has no backlash setting."
            backlash_slider.setToolTip(tip)
            backlash_ok.setToolTip(tip)
            if supported and status.get("backlash") is not None and not backlash_slider.isSliderDown():
                backlash_slider.blockSignals(True)
                backlash_slider.setValue(int(round(status["backlash"] * 10)))
                backlash_slider.blockSignals(False)
                backlash_value.setText(f"{status['backlash']:.1f}")
            if connected and not derotating:
                zero_btn.setEnabled(bool(status.get("can_sync", True)))
            max_angle = status.get("max_angle")
            if max_angle:
                goto_hint.setText(f"(0 – {min(max_angle, 359.99):g})")

        def _refresh_status() -> dict | None:
            adapter = state.get("adapter")
            if adapter is None:
                return None
            import asyncio
            try:
                status = asyncio.run(adapter.get_status())
            except Exception:
                logger.exception("Could not refresh rotator status")
                return None
            _apply_status(status)
            return status

        def _goto_clicked() -> None:
            angle = goto_spin.value()
            if _call("move_to_angle", angle, action="move"):
                logger.info("Rotator: moving to %.2f°", angle)

        def _reverse_toggled(checked: bool) -> None:
            if _call("set_reverse", checked, action="reverse"):
                logger.info("Rotator: reverse %s", "on" if checked else "off")
                _recompute()  # reversing flips the derotation direction, so refresh the rate now
            else:
                reverse_check.blockSignals(True)
                reverse_check.setChecked(not checked)
                reverse_check.blockSignals(False)

        def _zero_clicked() -> None:
            if _call("sync_position", 0.0, action="sync"):
                logger.info("Rotator: current position set as zero")
                _refresh_status()

        def _backlash_ok() -> None:
            value = backlash_slider.value() / 10.0
            if _call("set_backlash", value, action="backlash"):
                logger.info("Rotator: backlash set to %.1f", value)

        def _correction_ok() -> None:
            state["correction"] = float(correction_slider.value())
            logger.info("Rotator: derotation rate correction set to %+d%%", correction_slider.value())
            _recompute()

        goto_btn.clicked.connect(_goto_clicked)
        reverse_check.toggled.connect(_reverse_toggled)
        zero_btn.clicked.connect(_zero_clicked)
        backlash_ok.clicked.connect(_backlash_ok)
        correction_ok.clicked.connect(_correction_ok)

        # --- derotation loop --------------------------------------------
        derotate_timer = QTimer(page)

        def _stop_derotation(reason: str = "") -> None:
            derotate_timer.stop()
            if state["derotator"] is not None:
                logger.info("Rotator: derotation stopped%s", f" ({reason})" if reason else "")
            state["derotator"] = None
            derotate_btn.setText("Start Derotation")
            if state["adapter"] is not None:
                _refresh_status()
            else:
                _apply_status({})

        def _derotate_tick() -> None:
            derotator = state["derotator"]
            result = _current_rate()
            if derotator is None or result is None or result[2] is None:
                return  # target gone or below the horizon: hold position, keep waiting
            command = derotator.update(result[2], time.monotonic())
            if command is not None and not _call("move_to_angle", command, action="derotation move"):
                _stop_derotation("move failed")

        derotate_timer.timeout.connect(_derotate_tick)

        def _derotate_clicked() -> None:
            if state["derotator"] is not None:
                _stop_derotation("user")
                return
            if state["adapter"] is None:
                QMessageBox.information(self._window, "Not connected", "Connect the rotator first.")
                return
            result = _current_rate()
            if result is None:
                QMessageBox.information(
                    self._window, "No target",
                    "Enter a target RA/Dec (or sync one from a FITS file) first.",
                )
                return
            if result[2] is None:
                QMessageBox.information(self._window, "Below horizon", "The target is below the horizon.")
                return
            status = _refresh_status() or {}
            state["derotator"] = derotation.Derotator(status.get("position") or 0.0)
            derotate_btn.setText("Stop Derotation")
            derotate_timer.start(2000)
            _apply_status(status)
            logger.info(
                "Rotator: derotation started (target alt %.1f° az %.1f°, %.4f°/min)",
                result[0], result[1], result[2],
            )

        derotate_btn.clicked.connect(_derotate_clicked)

        # --- target sources ---------------------------------------------
        def _browse_clicked() -> None:
            folder = QFileDialog.getExistingDirectory(self._window, "Select FITS folder", fits_path_edit.text())
            if folder:
                fits_path_edit.setText(folder)

        def _fits_sync_clicked() -> None:
            folder = fits_path_edit.text().strip()
            if not folder:
                QMessageBox.information(self._window, "No folder", "Choose a folder of FITS frames first.")
                return
            try:
                ra, dec, path = derotation.pointing_from_fits_folder(folder)
            except Exception as exc:
                logger.warning("Could not read pointing from FITS in %s: %s", folder, exc)
                self._window.statusBar().showMessage(f"FITS sync failed: {exc}", 8000)
                return
            _set_target(ra, dec)
            logger.info("Rotator: target synced from %s (RA %.4f° Dec %.4f°)", path.name, ra, dec)

        fits_browse_btn.clicked.connect(_browse_clicked)
        fits_sync_btn.clicked.connect(_fits_sync_clicked)

        # --- connection: connect / scan ----------------------------------
        def _do_connect(device_name: str) -> None:
            from galileo.core.devices import DeviceCategory
            adapter = self._connect_device_adapter(
                DeviceCategory.ROTATOR, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to Rotator {device_name!r} — see log.", 6000)
                return
            state["adapter"] = adapter
            self._window.statusBar().showMessage(f"Connected to Rotator {device_name!r}.", 4000)
            status = _refresh_status()
            if status and status.get("position") is not None:
                goto_spin.setValue(min(status["position"], 359.99))

        def _connect_clicked() -> None:
            device_name = device_combo.currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a rotator device first.")
                return
            _do_connect(device_name)

        connect_btn.clicked.connect(_connect_clicked)

        def _device_picked() -> None:
            """Show the driver of the device just picked, without connecting it."""
            from galileo.core.devices import DeviceCategory
            apply_driver_info(self._lookup_driver_info(
                DeviceCategory.ROTATOR, driver_combo.currentText(), server_edit.text().strip(),
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
                adapter = get_adapter_class(DeviceCategory.ROTATOR)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.ROTATOR))
            except Exception:
                logger.exception("Rotator scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Rotator scan failed — see log.", 6000)
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
                    "Detected %d %s rotator device(s) at %s:%s: %s",
                    len(devices), driver, server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} rotator device(s) — see log.", 4000)
            else:
                logger.info("No %s rotator devices found at %s:%s.", driver, server, port)
                self._window.statusBar().showMessage(f"No {driver} rotator devices found at {server}:{port}.", 4000)

        scan_btn.clicked.connect(run_scan)

        # --- footer: Save + Log ------------------------------------------
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

        def save_rotator_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_device_config
            save_device_config(
                self._current_pier, "rotator",
                driver=driver_combo.currentText(), server=server_edit.text().strip(),
                port=port_spin.value(), device_name=device_combo.currentText().strip() or None,
            )
            logger.info(
                "Saved rotator settings for Pier %r: %s %s:%s, device: %s",
                self._current_pier.name, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip() or "(none)",
            )
            self._window.statusBar().showMessage(
                f"Saved rotator settings for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_rotator_config)

        def reload_page() -> None:
            cfg = None
            if self._current_pier is not None:
                from galileo.observatory import get_device_config
                try:
                    cfg = get_device_config(self._current_pier, "rotator")
                except Exception:
                    logger.exception("Could not load saved rotator config")

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

            # Site for the derotation maths comes from the selected Observatory.
            if self._current_pier is not None:
                try:
                    observatory = self._current_pier.observatory
                    if observatory.latitude is not None:
                        lat_spin.setValue(observatory.latitude)
                    if observatory.longitude is not None:
                        lon_spin.setValue(observatory.longitude)
                except Exception:
                    logger.exception("Could not read the Observatory's site coordinates")

            _stop_derotation("Pier changed")
            state["adapter"] = None
            _apply_status({})
            _recompute()

        def autoconnect_page() -> None:
            device_name = device_combo.currentText().strip()
            if device_name:
                _do_connect(device_name)

        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _refresh_status))
        status_timer.start(2000)

        state["reload"] = reload_page
        state["autoconnect"] = autoconnect_page
        self._device_pages["rotator"] = state
        reload_page()
        autoconnect_page()

        return page
