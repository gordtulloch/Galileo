# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Mount device-category page."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from galileo.exceptions import MountLimitError, MountParkedError, SlewObstructedError

from ._common import _format_hms, _format_dms, _when_visible, _DEFAULT_PORTS, _PARKED_MESSAGE, _OBSTRUCTED_MESSAGE, QLabel, QWidget

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowMountPageMixin:
    def _build_mount_page(self: AppWindowState) -> QWidget:
        """Mount device-category page: a live ASCOM/INDI status display
        (Name/Description/Driver info/version, Site latitude/longitude/
        elevation, Sidereal time, Epoch, time-to-meridian, Right Ascension/
        Declination, Altitude/Azimuth, Side of Pier, Tracking — EQP-MNT-020)
        plus manual RA/Dec and Alt/Az coordinate slewing, tracking-rate
        selection, N/S/E/W jog with Stop, Home/Park, and axis-reversal
        controls (EQP-MNT-010), matching the field set of the reference
        Mount layout (assets/samples/mount.png) laid out with this
        app's own Driver/Server/Port/Scan connection convention rather than
        its icon toolbar."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QFrame,
            QLabel, QTableWidget, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox,
            QPushButton, QCheckBox, QHeaderView, QMessageBox, QScrollArea, QGroupBox,
        )
        from PySide6.QtCore import QTimer

        page = QWidget()
        page.setObjectName("MountPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Mount")
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

        # --- status (left) + manual coordinates/control (right), scrollable
        # so a shorter window scrolls just this region rather than clipping
        # the Settings/Save/Log below it (which stay fixed at the bottom of
        # the page, always visible, matching the Camera/Focuser pages).
        main_content = QWidget()
        main_row = QHBoxLayout(main_content)
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(24)

        status_frame = QFrame()
        status_frame.setObjectName("DeviceSlotPanel")
        status_row = QHBoxLayout(status_frame)
        form_left = QFormLayout()
        form_right = QFormLayout()
        status_row.addLayout(form_left)
        status_row.addLayout(form_right)

        def _status_row(form: QFormLayout, label: str) -> QLabel:
            value = QLabel("—")
            form.addRow(label, value)
            return value

        name_value = _status_row(form_left, "Name")
        description_value = _status_row(form_left, "Description")
        driver_info_value = _status_row(form_left, "Driver info")
        site_latitude_value = _status_row(form_left, "Site latitude")
        site_elevation_value = _status_row(form_left, "Site elevation")
        sidereal_time_value = _status_row(form_left, "Sidereal time")
        right_ascension_value = _status_row(form_left, "Right Ascension")
        altitude_value = _status_row(form_left, "Altitude")
        side_of_pier_value = _status_row(form_left, "Side of pier")

        driver_version_value = _status_row(form_right, "Driver version")
        site_longitude_value = _status_row(form_right, "Site longitude")
        epoch_value = _status_row(form_right, "Epoch")
        meridian_in_value = _status_row(form_right, "Meridian in")
        declination_value = _status_row(form_right, "Declination")
        azimuth_value = _status_row(form_right, "Azimuth")
        tracking_value = _status_row(form_right, "Tracking")

        left_col = QVBoxLayout()
        left_col.addWidget(status_frame)

        # --- Meridian Flip + Limits (EQP-MNT-060 / EQP-MNT-070) --------------
        flip_box = QGroupBox("Meridian Flip")
        flip_layout = QVBoxLayout(flip_box)
        flip_row = QHBoxLayout()
        flip_check = QCheckBox("Flip if HA >:")
        flip_check.setToolTip(
            "While the mount is tracking, flip it to the other side of the pier once the target is "
            "this far past the meridian."
        )
        flip_ha_spin = QDoubleSpinBox()
        flip_ha_spin.setRange(0.0, 90.0)
        flip_ha_spin.setDecimals(2)
        flip_ha_spin.setValue(5.0)
        flip_row.addWidget(flip_check)
        flip_row.addWidget(flip_ha_spin)
        flip_row.addWidget(QLabel("deg"))
        flip_row.addStretch(1)
        flip_layout.addLayout(flip_row)
        flip_state_label = QLabel("Meridian flip inactive (flip not requested)")
        flip_layout.addWidget(flip_state_label)
        pier_side_label = QLabel("Pier Side: —")
        flip_layout.addWidget(pier_side_label)
        left_col.addWidget(flip_box)

        limits_box = QGroupBox("Limits")
        limits_layout = QVBoxLayout(limits_box)
        alt_row = QHBoxLayout()
        alt_limits_check = QCheckBox("Enable Alt limits")
        alt_tracking_only_check = QCheckBox("Tracking only")
        alt_tracking_only_check.setToolTip(
            "Only enforce the altitude limits while tracking; a slew in progress is not interrupted. "
            "A slew command whose target is outside the limits is still refused."
        )
        alt_row.addWidget(alt_limits_check)
        alt_row.addStretch(1)
        alt_row.addWidget(alt_tracking_only_check)
        limits_layout.addLayout(alt_row)
        alt_form = QFormLayout()
        min_alt_spin = QDoubleSpinBox()
        min_alt_spin.setRange(-90.0, 90.0)
        min_alt_spin.setDecimals(2)
        min_alt_spin.setValue(0.0)
        max_alt_spin = QDoubleSpinBox()
        max_alt_spin.setRange(-90.0, 90.0)
        max_alt_spin.setDecimals(2)
        max_alt_spin.setValue(90.0)
        alt_form.addRow("Min. Alt:", min_alt_spin)
        alt_form.addRow("Max. Alt:", max_alt_spin)
        limits_layout.addLayout(alt_form)
        ha_limits_check = QCheckBox("Enable HA limits")
        limits_layout.addWidget(ha_limits_check)
        ha_form = QFormLayout()
        max_ha_spin = QDoubleSpinBox()
        max_ha_spin.setRange(0.0, 12.0)
        max_ha_spin.setDecimals(2)
        max_ha_spin.setValue(2.0)
        ha_form.addRow("Max. HA (hours):", max_ha_spin)
        limits_layout.addLayout(ha_form)
        left_col.addWidget(limits_box)
        left_col.addStretch(1)

        main_row.addLayout(left_col, 1)

        controls_col = QVBoxLayout()
        controls_col.setSpacing(4)

        coords_heading = QLabel("Manual Coordinates")
        coords_heading.setObjectName("CriteriaHeading")
        controls_col.addWidget(coords_heading)

        def _hms_spins() -> tuple:
            h = QSpinBox(); h.setRange(0, 23); h.setSuffix(" h")
            m = QSpinBox(); m.setRange(0, 59); m.setSuffix(" m")
            s = QDoubleSpinBox(); s.setRange(0.0, 59.999); s.setDecimals(1); s.setSuffix(" s")
            return h, m, s

        def _dms_spins() -> tuple:
            d = QSpinBox(); d.setRange(-359, 359); d.setSuffix(" d")
            m = QSpinBox(); m.setRange(0, 59); m.setSuffix(" m")
            s = QSpinBox(); s.setRange(0, 59); s.setSuffix(" s")
            return d, m, s

        ra_h, ra_m, ra_s = _hms_spins()
        dec_d, dec_m, dec_s = _dms_spins()
        alt_d, alt_m, alt_s = _dms_spins()
        az_d, az_m, az_s = _dms_spins()

        # Single-spaced, one row each, with each row's own Slew button
        # beside it (rather than one button spanning two rows) — keeps
        # this block as short as possible so the N/S/E/W jog pad below
        # has room without the whole page needing to scroll.
        coords_grid = QGridLayout()
        coords_grid.setVerticalSpacing(4)

        def _coord_row(row: int, label: str, spins: tuple) -> QPushButton:
            coords_grid.addWidget(QLabel(label), row, 0)
            for i, spin in enumerate(spins):
                coords_grid.addWidget(spin, row, 1 + i)
            slew_btn = QPushButton("Slew")
            slew_btn.setObjectName("AccentButton")
            coords_grid.addWidget(slew_btn, row, 1 + len(spins))
            return slew_btn

        ra_slew_btn = _coord_row(0, "Target RA", (ra_h, ra_m, ra_s))
        dec_slew_btn = _coord_row(1, "Target Dec", (dec_d, dec_m, dec_s))
        alt_slew_btn = _coord_row(2, "Target Alt", (alt_d, alt_m, alt_s))
        az_slew_btn = _coord_row(3, "Target Az", (az_d, az_m, az_s))
        controls_col.addLayout(coords_grid)

        controls_col.addSpacing(8)

        manual_heading = QLabel("Manual control")
        manual_heading.setObjectName("CriteriaHeading")
        controls_col.addWidget(manual_heading)

        tracking_rate_row = QHBoxLayout()
        set_rate_btn = QPushButton("Set tracking rate")
        set_rate_btn.setObjectName("AccentButton")
        tracking_rate_row.addWidget(set_rate_btn)
        tracking_rate_combo = QComboBox()
        tracking_rate_combo.addItems(["Sidereal", "Lunar", "Solar", "King"])
        tracking_rate_row.addWidget(tracking_rate_combo)
        tracking_rate_row.addStretch(1)
        controls_col.addLayout(tracking_rate_row)

        tracking_onoff_row = QHBoxLayout()
        tracking_on_btn = QPushButton("Tracking On")
        tracking_on_btn.setObjectName("AccentButton")
        tracking_off_btn = QPushButton("Tracking Off")
        tracking_status_value = QLabel("Tracking: —")
        tracking_onoff_row.addWidget(tracking_on_btn)
        tracking_onoff_row.addWidget(tracking_off_btn)
        tracking_onoff_row.addWidget(tracking_status_value)
        tracking_onoff_row.addStretch(1)
        controls_col.addLayout(tracking_onoff_row)

        rates_form = QFormLayout()
        rates_form.setVerticalSpacing(2)
        from galileo.ui.imaging import NUDGE_RATES
        jog_rate_combo = QComboBox()
        for rate_name, rate_value in NUDGE_RATES.items():
            jog_rate_combo.addItem(f"{rate_name} ({rate_value:g}°/s)", rate_value)
        jog_rate_combo.setCurrentIndex(1)
        jog_rate_combo.setToolTip("How fast the N/S/E/W buttons move the mount (same speeds as the Imaging page's nudge).")
        rates_form.addRow("Rate", jog_rate_combo)
        controls_col.addLayout(rates_form)

        pad_row = QHBoxLayout()
        pad_grid = QGridLayout()
        north_btn = QPushButton("N")
        west_btn = QPushButton("W")
        stop_btn = QPushButton("Stop")
        east_btn = QPushButton("E")
        south_btn = QPushButton("S")
        for btn in (north_btn, west_btn, stop_btn, east_btn, south_btn):
            btn.setObjectName("AccentButton")
            btn.setFixedSize(44, 44)
        pad_grid.addWidget(north_btn, 0, 1)
        pad_grid.addWidget(west_btn, 1, 0)
        pad_grid.addWidget(stop_btn, 1, 1)
        pad_grid.addWidget(east_btn, 1, 2)
        pad_grid.addWidget(south_btn, 2, 1)
        pad_row.addLayout(pad_grid)
        pad_row.addStretch(1)
        home_park_col = QVBoxLayout()
        home_btn = QPushButton("Home")
        park_btn = QPushButton("Park")
        park_btn.setObjectName("AccentButton")
        unpark_btn = QPushButton("Unpark")
        park_status_value = QLabel("Park status: —")
        home_park_col.addWidget(home_btn)
        home_park_col.addWidget(park_btn)
        home_park_col.addWidget(unpark_btn)
        home_park_col.addWidget(park_status_value)
        home_park_col.addStretch(1)
        pad_row.addLayout(home_park_col)
        controls_col.addLayout(pad_row)

        reversed_row = QHBoxLayout()
        primary_reversed_check = QCheckBox("Primary reversed")
        secondary_reversed_check = QCheckBox("Secondary reversed")
        reversed_row.addWidget(primary_reversed_check)
        reversed_row.addWidget(secondary_reversed_check)
        reversed_row.addStretch(1)
        controls_col.addLayout(reversed_row)

        controls_col.addStretch(1)
        main_row.addLayout(controls_col, 1)

        main_scroll = QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setFrameShape(QFrame.Shape.NoFrame)
        main_scroll.setWidget(main_content)
        layout.addWidget(main_scroll, 1)

        settings_row = QHBoxLayout()
        settings_heading = QLabel("Settings")
        settings_heading.setObjectName("CriteriaHeading")
        settings_row.addWidget(settings_heading)
        settings_row.addWidget(QLabel("None"))
        settings_row.addStretch(1)
        layout.addLayout(settings_row)

        state: dict = {"adapter": None, "at_park": None}
        # This Pier's mount adapter persists here across a Pier switch, keyed by
        # pier_key() — state["adapter"] is just "whichever Pier is displayed right
        # now"'s adapter, kept in sync with this on every reload (see reload_page()).
        adapters_by_pier: dict = {}

        import time as _time
        from galileo.mount_limits import MountLimits, pier_side_text

        FLIP_COOLDOWN_S = 600.0         # don't re-attempt a flip the driver didn't carry out
        NOTE_SHOW_S = 120.0
        guard_state: dict = {"thread": None, "last_flip": None, "note": None}

        def _current_limits() -> MountLimits:
            return MountLimits(
                flip_enabled=flip_check.isChecked(), flip_ha_deg=flip_ha_spin.value(),
                alt_limits_enabled=alt_limits_check.isChecked(),
                min_alt=min_alt_spin.value(), max_alt=max_alt_spin.value(),
                alt_tracking_only=alt_tracking_only_check.isChecked(),
                ha_limits_enabled=ha_limits_check.isChecked(), max_ha_hours=max_ha_spin.value(),
            )

        limit_widgets = (flip_check, alt_limits_check, alt_tracking_only_check, ha_limits_check,
                         flip_ha_spin, min_alt_spin, max_alt_spin, max_ha_spin)

        def _show_limits(limits: MountLimits) -> None:
            for widget, value in (
                (flip_check, limits.flip_enabled), (alt_limits_check, limits.alt_limits_enabled),
                (alt_tracking_only_check, limits.alt_tracking_only), (ha_limits_check, limits.ha_limits_enabled),
            ):
                widget.setChecked(bool(value))
            for widget, value in (
                (flip_ha_spin, limits.flip_ha_deg), (min_alt_spin, limits.min_alt),
                (max_alt_spin, limits.max_alt), (max_ha_spin, limits.max_ha_hours),
            ):
                widget.setValue(float(value))

        def _update_flip_label(tracking: bool | None = None) -> None:
            note = guard_state["note"]
            if note is not None and _time.monotonic() - note[1] < NOTE_SHOW_S:
                flip_state_label.setText(note[0])
            elif not flip_check.isChecked():
                flip_state_label.setText("Meridian flip inactive (flip not requested)")
            elif tracking:
                flip_state_label.setText(f"Meridian flip armed — flips at HA > {flip_ha_spin.value():.2f} deg")
            else:
                flip_state_label.setText("Meridian flip requested — waiting for the mount to track")

        def _limits_changed(*_args) -> None:
            """Apply the page's limits to this Pier's slew guard right away, so slews are
            checked against what is on screen (Save only makes them survive a restart)."""
            from galileo.core.slew_guard import get_slew_guard
            from galileo.current_object import pier_key
            for widget, enabled in (
                (alt_tracking_only_check, alt_limits_check.isChecked()),
                (min_alt_spin, alt_limits_check.isChecked()), (max_alt_spin, alt_limits_check.isChecked()),
                (max_ha_spin, ha_limits_check.isChecked()), (flip_ha_spin, flip_check.isChecked()),
            ):
                widget.setEnabled(enabled)
            get_slew_guard(pier_key(self._current_pier)).limits = _current_limits()
            _update_flip_label(state.get("tracking"))

        def _flip_toggled(*_args) -> None:
            guard_state["note"] = None
            _limits_changed()

        for check in (alt_limits_check, ha_limits_check, alt_tracking_only_check):
            check.toggled.connect(_limits_changed)
        flip_check.toggled.connect(_flip_toggled)
        for spin in (flip_ha_spin, min_alt_spin, max_alt_spin, max_ha_spin):
            spin.valueChanged.connect(_limits_changed)

        def _guard_tick() -> None:
            """Every few seconds, off the UI thread: stop the mount if it is outside its limits
            while tracking or slewing, and flip it when a requested flip is due."""
            adapter = state.get("adapter")
            limits = _current_limits()
            if adapter is None or guard_state["thread"] is not None:
                return
            if not (limits.flip_enabled or limits.alt_limits_enabled or limits.ha_limits_enabled):
                return
            last_flip = guard_state["last_flip"]
            if last_flip is not None and _time.monotonic() - last_flip < FLIP_COOLDOWN_S:
                import dataclasses
                limits = dataclasses.replace(limits, flip_enabled=False)
            from ._threads import _MountGuardThread
            thread = _MountGuardThread(adapter, limits, self._window)
            thread.finished_with.connect(_guard_done)
            guard_state["thread"] = thread
            thread.start()

        def _guard_done(result: dict) -> None:
            guard_state["thread"] = None
            status = result.get("status")
            if status:
                _apply_status(status)
            reasons = "; ".join(result.get("reasons") or ())
            kind = result.get("kind")
            if kind == "stopped":
                message = f"Mount stopped — {reasons}."
                logger.warning("Mount: %s", message)
                guard_state["note"] = (message, _time.monotonic())
                self._window.statusBar().showMessage(message, 10000)
            elif kind == "flipped":
                guard_state["last_flip"] = _time.monotonic()
                if result.get("error"):
                    message = "Meridian flip failed — see log."
                    logger.error("Mount: meridian flip failed: %s", result["error"])
                else:
                    message = "Meridian flip completed."
                    logger.info("Mount: meridian flip completed (%s)", reasons)
                guard_state["note"] = (message, _time.monotonic())
                self._window.statusBar().showMessage(message, 8000)
            elif result.get("error"):
                logger.error("Mount limit monitor error: %s", result["error"])
            _update_flip_label(bool(status.get("tracking")) if status else None)

        def _apply_status(status: dict) -> None:
            name_value.setText(status.get("name") or "—")
            description_value.setText(status.get("description") or "—")
            driver_info_value.setText(status.get("driver_info") or "—")
            driver_version_value.setText(status.get("driver_version") or "—")
            site_latitude_value.setText(_format_dms(status.get("site_latitude")))
            site_longitude_value.setText(_format_dms(status.get("site_longitude")))
            elevation = status.get("site_elevation")
            site_elevation_value.setText("—" if elevation is None else f"{elevation:.1f} m")
            epoch_value.setText(status.get("equatorial_system") or "—")
            lst = status.get("sidereal_time")
            sidereal_time_value.setText(_format_hms(lst))
            ra = status.get("right_ascension")
            right_ascension_value.setText(_format_hms(ra))
            declination_value.setText(_format_dms(status.get("declination")))
            altitude_value.setText(_format_dms(status.get("altitude")))
            azimuth_value.setText(_format_dms(status.get("azimuth")))
            side_of_pier_value.setText(status.get("side_of_pier") or "—")
            tracking = status.get("tracking")
            tracking_value.setText("—" if tracking is None else ("Tracking" if tracking else "Stopped"))
            meridian_in_value.setText(_format_hms((ra - lst) % 24.0) if ra is not None and lst is not None else "—")
            pier_side_label.setText("Pier Side: " + pier_side_text(status.get("side_of_pier")))
            state["tracking"] = bool(tracking) if tracking is not None else None
            _update_flip_label(state["tracking"])
            at_park = status.get("at_park")
            state["at_park"] = at_park
            park_status_value.setText("Park status: —" if at_park is None else ("Park status: Parked" if at_park else "Park status: Unparked"))
            park_btn.setEnabled(not at_park)
            unpark_btn.setEnabled(at_park is not False)
            rate = status.get("tracking_rate")
            if tracking is None:
                tracking_status_value.setText("Tracking: —")
            elif tracking:
                tracking_status_value.setText(f"Tracking: On ({rate} rate)" if rate else "Tracking: On")
            else:
                tracking_status_value.setText("Tracking: Off" + (f" ({rate} rate selected)" if rate else ""))

        def _refresh_status() -> dict | None:
            adapter = state.get("adapter")
            if adapter is None:
                return None
            import asyncio
            try:
                status = asyncio.run(adapter.get_status())
            except Exception:
                logger.exception("Could not refresh mount status")
                return None
            _apply_status(status)
            return status

        def _do_connect(device_name: str) -> None:
            import asyncio
            from galileo.core.devices import DeviceCategory
            from galileo.core.slew_guard import get_slew_guard
            from galileo.current_object import pier_key
            driver = driver_combo.currentText()
            server = server_edit.text().strip() or "localhost"
            port = port_spin.value()
            try:
                adapter = self._make_adapter(DeviceCategory.MOUNT, driver, server, port, device_name)
                obs = self._current_observatory
                if obs is not None:
                    adapter.site_lat = getattr(obs, "latitude", None)
                    adapter.site_lon = getattr(obs, "longitude", None)
                    adapter.site_elevation = getattr(obs, "elevation_m", None)
                asyncio.run(adapter.connect())
            except Exception:
                logger.exception("Could not connect to Mount %r at %s:%d", device_name, server, port)
                self._window.statusBar().showMessage(f"Could not connect to Mount {device_name!r} — see log.", 6000)
                return
            # Bind this adapter to its own Pier's slew guard (not whichever
            # Observatory happens to be selected elsewhere), so obstruction
            # checks stay correct even if a different Pier's horizon is
            # current by the time this mount actually slews.
            adapter.slew_guard = get_slew_guard(pier_key(self._current_pier))
            state["adapter"] = adapter
            adapters_by_pier[pier_key(self._current_pier)] = adapter
            self._window.statusBar().showMessage(f"Connected to Mount {device_name!r}.", 4000)
            _refresh_status()

        def _connect_clicked() -> None:
            device_name = device_combo.currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a mount device first.")
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
                    adapter = get_adapter_class(DeviceCategory.MOUNT)(host=server, port=port)
                else:
                    from galileo.adapters.alpaca import get_adapter_class
                    adapter = get_adapter_class(DeviceCategory.MOUNT)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.MOUNT))
            except Exception:
                logger.exception("Mount scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Mount scan failed — see log.", 6000)
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
                    "Detected %d %s mount device(s) at %s:%s: %s",
                    len(devices), driver, server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} mount device(s) — see log.", 4000)
            else:
                logger.info("No %s mount devices found at %s:%s.", driver, server, port)
                self._window.statusBar().showMessage(f"No {driver} mount devices found at {server}:{port}.", 4000)

        scan_btn.clicked.connect(run_scan)

        def _target_ra_dec() -> tuple:
            ra_hours = ra_h.value() + ra_m.value() / 60.0 + ra_s.value() / 3600.0
            dec_mag = abs(dec_d.value()) + dec_m.value() / 60.0 + dec_s.value() / 3600.0
            dec_deg = -dec_mag if dec_d.value() < 0 else dec_mag
            return ra_hours, dec_deg

        def _target_alt_az() -> tuple:
            alt_mag = abs(alt_d.value()) + alt_m.value() / 60.0 + alt_s.value() / 3600.0
            alt_deg = -alt_mag if alt_d.value() < 0 else alt_mag
            az_deg = az_d.value() + az_m.value() / 60.0 + az_s.value() / 3600.0
            return alt_deg, az_deg

        def _slew_radec_clicked() -> None:
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the mount first.")
                return
            ra_hours, dec_deg = _target_ra_dec()
            import asyncio
            try:
                asyncio.run(adapter.slew_to_coordinates(ra_hours * 15.0, dec_deg))
            except MountParkedError:
                self._window.statusBar().showMessage(_PARKED_MESSAGE, 6000)
                return
            except SlewObstructedError:
                self._window.statusBar().showMessage(_OBSTRUCTED_MESSAGE, 6000)
                return
            except MountLimitError as exc:
                self._window.statusBar().showMessage(str(exc), 8000)
                return
            except Exception:
                logger.exception("Mount slew-to-coordinates failed")
                self._window.statusBar().showMessage("Slew failed — see log.", 6000)
                return
            logger.info("Mount: slew requested to RA %.4fh Dec %.4f°", ra_hours, dec_deg)
            self._track_when_slew_finishes(adapter)

        ra_slew_btn.clicked.connect(_slew_radec_clicked)
        dec_slew_btn.clicked.connect(_slew_radec_clicked)

        def _slew_altaz_clicked() -> None:
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the mount first.")
                return
            alt_deg, az_deg = _target_alt_az()
            import asyncio
            try:
                asyncio.run(adapter.slew_to_altaz(alt_deg, az_deg))
            except MountParkedError:
                self._window.statusBar().showMessage(_PARKED_MESSAGE, 6000)
                return
            except SlewObstructedError:
                self._window.statusBar().showMessage(_OBSTRUCTED_MESSAGE, 6000)
                return
            except MountLimitError as exc:
                self._window.statusBar().showMessage(str(exc), 8000)
                return
            except Exception:
                logger.exception("Mount slew-to-altaz failed")
                self._window.statusBar().showMessage("Slew failed — see log.", 6000)
                return
            logger.info("Mount: slew requested to Alt %.4f° Az %.4f°", alt_deg, az_deg)
            self._track_when_slew_finishes(adapter)

        alt_slew_btn.clicked.connect(_slew_altaz_clicked)
        az_slew_btn.clicked.connect(_slew_altaz_clicked)

        def _move_axis(axis: int, rate: float) -> None:
            adapter = state.get("adapter")
            if adapter is None:
                return
            import asyncio
            try:
                asyncio.run(adapter.move_axis(axis, rate))
            except MountParkedError:
                self._window.statusBar().showMessage(_PARKED_MESSAGE, 6000)
            except Exception:
                logger.exception("Mount move_axis failed (axis=%s rate=%s)", axis, rate)

        def _jog(direction: str) -> None:
            rate = float(jog_rate_combo.currentData())
            primary_rate = rate * (-1.0 if primary_reversed_check.isChecked() else 1.0)
            secondary_rate = rate * (-1.0 if secondary_reversed_check.isChecked() else 1.0)
            if direction == "N":
                _move_axis(1, secondary_rate)
            elif direction == "S":
                _move_axis(1, -secondary_rate)
            elif direction == "E":
                _move_axis(0, primary_rate)
            elif direction == "W":
                _move_axis(0, -primary_rate)

        north_btn.clicked.connect(lambda: _jog("N"))
        south_btn.clicked.connect(lambda: _jog("S"))
        east_btn.clicked.connect(lambda: _jog("E"))
        west_btn.clicked.connect(lambda: _jog("W"))

        def _stop_clicked() -> None:
            adapter = state.get("adapter")
            if adapter is None:
                return
            import asyncio
            try:
                asyncio.run(adapter.move_axis(0, 0.0))
                asyncio.run(adapter.move_axis(1, 0.0))
                asyncio.run(adapter.abort_slew())
            except Exception:
                logger.exception("Mount stop failed")
            logger.info("Mount: Stop requested")

        stop_btn.clicked.connect(_stop_clicked)

        def _home_clicked() -> None:
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the mount first.")
                return
            import asyncio
            try:
                asyncio.run(adapter.find_home())
            except MountParkedError:
                self._window.statusBar().showMessage(_PARKED_MESSAGE, 6000)
                return
            except Exception:
                logger.exception("Mount find_home failed")
                self._window.statusBar().showMessage("Find Home failed — see log.", 6000)
                return
            logger.info("Mount: Find Home requested")
            _refresh_status()

        home_btn.clicked.connect(_home_clicked)

        def _park_clicked() -> None:
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the mount first.")
                return
            import asyncio
            try:
                asyncio.run(adapter.park())
                logger.info("Mount: Park requested")
            except Exception:
                logger.exception("Mount park failed")
                self._window.statusBar().showMessage("Park failed — see log.", 6000)
                return
            _refresh_status()

        park_btn.clicked.connect(_park_clicked)

        def _unpark_clicked() -> None:
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the mount first.")
                return
            import asyncio
            try:
                asyncio.run(adapter.unpark())
                logger.info("Mount: Unpark requested")
            except Exception:
                logger.exception("Mount unpark failed")
                self._window.statusBar().showMessage("Unpark failed — see log.", 6000)
                return
            _refresh_status()

        unpark_btn.clicked.connect(_unpark_clicked)

        def _set_tracking_clicked(enabled: bool) -> None:
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the mount first.")
                return
            import asyncio
            try:
                asyncio.run(adapter.set_tracking(enabled))
                logger.info("Mount: tracking %s requested", "on" if enabled else "off")
            except MountParkedError:
                self._window.statusBar().showMessage(_PARKED_MESSAGE, 6000)
                return
            except Exception:
                logger.exception("Mount set_tracking failed")
                self._window.statusBar().showMessage("Tracking change failed — see log.", 6000)
                return
            _refresh_status()

        tracking_on_btn.clicked.connect(lambda: _set_tracking_clicked(True))
        tracking_off_btn.clicked.connect(lambda: _set_tracking_clicked(False))

        def _set_tracking_rate_clicked() -> None:
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the mount first.")
                return
            mode = tracking_rate_combo.currentText()
            import asyncio
            try:
                asyncio.run(adapter.set_tracking_rate_mode(mode))
            except Exception:
                logger.exception("Mount set_tracking_rate_mode failed")
                self._window.statusBar().showMessage("Set tracking rate failed — see log.", 6000)
                return
            logger.info("Mount: tracking rate set to %s", mode)

        set_rate_btn.clicked.connect(_set_tracking_rate_clicked)

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

        def save_mount_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_device_config
            save_device_config(
                self._current_pier, "mount",
                driver=driver_combo.currentText(), server=server_edit.text().strip(),
                port=port_spin.value(), device_name=device_combo.currentText().strip() or None,
                mount_limits=_current_limits(),
            )
            logger.info(
                "Saved mount settings for Pier %r: %s %s:%s, device: %s",
                self._current_pier.name, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip() or "(none)",
            )
            self._window.statusBar().showMessage(
                f"Saved mount settings for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_mount_config)

        def reload_page() -> None:
            cfg = None
            if self._current_pier is not None:
                from galileo.observatory import get_device_config
                try:
                    cfg = get_device_config(self._current_pier, "mount")
                except Exception:
                    logger.exception("Could not load saved mount config")

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
            from galileo.current_object import pier_key
            from galileo.observatory import mount_limits_from_config
            guard_state["note"] = None
            guard_state["last_flip"] = None
            for widget in limit_widgets:
                widget.blockSignals(True)
            try:
                _show_limits(mount_limits_from_config(cfg))
            finally:
                for widget in limit_widgets:
                    widget.blockSignals(False)
            _limits_changed()
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
            """Pier-level Disconnect button: tear down this Pier's mount connection."""
            from galileo.current_object import pier_key
            adapter = adapters_by_pier.pop(pier_key(self._current_pier), None)
            if adapter is None:
                return
            import asyncio
            try:
                asyncio.run(adapter.disconnect())
            except Exception:
                logger.exception("Could not disconnect Mount")
            state["adapter"] = None
            _apply_status({})
            self._window.statusBar().showMessage("Mount disconnected.", 4000)

        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _refresh_status))
        status_timer.start(2000)

        # Unlike the status display above, the limit/flip monitor must keep watching while another
        # page (Imaging, Sessions) is in front, so it is not gated on this page being visible.
        guard_timer = QTimer(page)
        guard_timer.timeout.connect(_guard_tick)
        guard_timer.start(5000)

        state["reload"] = reload_page
        state["autoconnect"] = autoconnect_page
        state["disconnect"] = disconnect_page
        state["connected"] = lambda: state.get("adapter") is not None
        # The jog pad's axis reversal, so the Imaging page's nudge pad points the same way.
        state["axis_reversed"] = lambda: (primary_reversed_check.isChecked(), secondary_reversed_check.isChecked())
        self._device_pages["mount"] = state
        reload_page()
        if self._startup_autoconnect_allowed():
            autoconnect_page()

        return page
