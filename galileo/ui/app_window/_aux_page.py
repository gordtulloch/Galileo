# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Control Panel page: an INDI server browser (EQP-AUX-020)."""

from __future__ import annotations

import math

from galileo.ui.qt_helpers import take_widget
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

import logging

from ._common import _when_visible, _DEFAULT_PORTS, QWidget, guard_loopback_edit
from galileo.device_ops import NOT_CONNECTED
from galileo.ui.help import KEY_PROPERTY
from galileo.simple_device_ops import AuxServerOps, aux_needs_rebuild

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState

# INDI property state -> state-dot color (the INDI convention: Idle=grey, Ok=green, Busy=yellow, Alert=red).
_STATE_COLOR = {"Ok": "#2ecc71", "Busy": "#f1c40f", "Alert": "#e74c3c"}
_AUX_SLIDER_STEPS = 10_000
_PROP_LABEL_WIDTH = 220   # fixed label column so every property's controls start at the same x
_PROP_SLIDER_WIDTH = 220


class AppWindowAuxPageMixin:
    def _build_aux_page(self: AppWindowState) -> QWidget:
        """Control Panel page (the "aux" Equipment category): connect to an INDI server and browse and edit
        every property of every device it reports - one tab per device, one sub-tab per INDI property
        group, like the EKOS INDI Control Panel (EQP-AUX-020). Alpaca Switch devices are driven from the
        Switches page instead. The panel is built from ``AuxServerPanel.get_all_property_groups()`` once
        connected, then refreshed in place on a timer."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QLabel,
            QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton,
            QMessageBox, QSlider, QTabWidget, QButtonGroup,
            QScrollArea, QFrame, QSizePolicy,
        )
        from PySide6.QtCore import QTimer, Qt

        page = QWidget()
        page.setObjectName("AuxPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Control Panel")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        subtitle = QLabel(
            "Connect to an INDI server to browse and edit every property of every device it reports — "
            "one tab per device, one sub-tab per property group, like the EKOS INDI Control Panel."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # --- connection line: Server (takes the spare width), Port, Connect --------
        top = QHBoxLayout()
        top.setSpacing(8)

        def _captioned(text: str, widget, stretch: int = 0) -> None:
            top.addWidget(QLabel(text))
            widget.setProperty(KEY_PROPERTY, text)  # the field is documented under its label
            top.addWidget(widget, stretch)

        server_edit = QLineEdit()
        guard_loopback_edit(server_edit)
        server_edit.setPlaceholderText("FQDN or IP, e.g. stellarmate.local or 192.168.1.50")
        server_edit.setMaxLength(40)
        _captioned("Server", server_edit, 1)

        port_spin = QSpinBox()
        port_spin.setRange(1, 65535)
        port_spin.setValue(_DEFAULT_PORTS["INDI"])
        port_spin.setToolTip("The INDI server's port - 7624 unless you started it on another one.")
        _captioned("Port", port_spin)

        connect_btn = QPushButton("Connect")
        connect_btn.setObjectName("AccentButton")
        top.addWidget(connect_btn)
        layout.addLayout(top)

        # --- live control panel: one tab per driver-defined property group ---
        panel_container = QVBoxLayout()
        layout.addLayout(panel_container, 1)

        state: dict[str, Any] = {"server": None}
        from galileo.current_object import pier_key
        servers_by_pier: dict[Any, Any] = {}  # INDI server panels, one per Pier (EQP-AUX-020)

        def _set_accent(button, active: bool) -> None:
            button.setObjectName("AccentButton" if active else "")
            button.style().unpolish(button)
            button.style().polish(button)

        def _build_switch_row(prop, write) -> tuple[QWidget, Callable]:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("●")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            name_label = QLabel(prop.label)
            name_label.setFixedWidth(_PROP_LABEL_WIDTH)
            name_label.setToolTip(prop.label)
            row.addWidget(name_label)

            exclusive = prop.rule in ("OneOfMany", "AtMostOne")
            group = QButtonGroup(row_widget)
            group.setExclusive(exclusive)
            buttons: list[tuple[Any, str]] = []
            for el in prop.elements:
                btn = QPushButton(el.label)
                btn.setCheckable(True)
                btn.setChecked(bool(el.value))
                btn.setEnabled(prop.perm != "ro")
                group.addButton(btn)
                row.addWidget(btn)
                buttons.append((btn, el.name))
                _set_accent(btn, bool(el.value))

            for btn, el_name in buttons:
                def _on_clicked(checked: bool, el_name=el_name) -> None:
                    write(prop.name, {el_name: checked})
                btn.clicked.connect(_on_clicked)

            def _refresh(p) -> None:
                dot.setStyleSheet(f"color: {_STATE_COLOR.get(p.state, '#888888')}; font-size: 14px;")
                live = {el.name: el.value for el in p.elements}
                for btn, el_name in buttons:
                    checked = bool(live.get(el_name, btn.isChecked()))
                    btn.blockSignals(True)
                    btn.setChecked(checked)
                    btn.blockSignals(False)
                    _set_accent(btn, checked)

            row.addStretch(1)  # controls sit left, beside the label column
            return row_widget, _refresh

        def _build_number_row(prop, write) -> tuple[QWidget, Callable]:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("●")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            name_label = QLabel(prop.label)
            name_label.setFixedWidth(_PROP_LABEL_WIDTH)
            name_label.setToolTip(prop.label)
            row.addWidget(name_label)

            multi = len(prop.elements) > 1
            # (slider, spin, element name, numeric minimum, numeric maximum)
            controls: list[tuple[Any, Any, str, float, float]] = []
            for el in prop.elements:
                if multi:
                    row.addWidget(QLabel(el.label))
                lo = el.min if el.min is not None and math.isfinite(el.min) else 0.0
                raw_value = float(el.value) if el.value is not None else lo
                value = raw_value if math.isfinite(raw_value) else lo
                hi = el.max if el.max is not None and math.isfinite(el.max) else max(lo + 1.0, value * 2.0, 100.0)
                step = el.step if el.step is not None and math.isfinite(el.step) and el.step > 0 else 1.0
                if hi <= lo:
                    hi = lo + step
                value = min(max(value, lo), hi)

                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(0, _AUX_SLIDER_STEPS)
                spin = QDoubleSpinBox()
                spin.setRange(lo, hi)
                spin.setSingleStep(step)
                spin.setDecimals(3 if step < 1 else 1)
                spin.setValue(value)
                fraction = ((value / 2 - lo / 2) / (hi / 2 - lo / 2)) if hi != lo else 0.0
                slider.setValue(round(fraction * _AUX_SLIDER_STEPS))
                if not math.isfinite(raw_value):
                    spin.setToolTip(
                        "The driver reported a non-finite value. Edit this field and click Set to send a valid value."
                    )
                spin.setEnabled(prop.perm != "ro")
                slider.setEnabled(prop.perm != "ro")

                slider.valueChanged.connect(
                    lambda v, spin=spin, lo=lo, hi=hi:
                        spin.setValue(lo * (1 - v / _AUX_SLIDER_STEPS) + hi * (v / _AUX_SLIDER_STEPS))
                )
                spin.valueChanged.connect(
                    lambda v, slider=slider, lo=lo, hi=hi:
                        slider.setValue(round(((v / 2 - lo / 2) / (hi / 2 - lo / 2)) * _AUX_SLIDER_STEPS))
                )

                slider.setFixedWidth(_PROP_SLIDER_WIDTH)
                row.addWidget(slider)
                row.addWidget(spin)
                controls.append((slider, spin, el.name, lo, hi))

            set_btn = QPushButton("Set")
            set_btn.setObjectName("AccentButton")
            set_btn.setEnabled(prop.perm != "ro")
            row.addWidget(set_btn)

            def _on_set() -> None:
                values = {name: spin.value() for _slider, spin, name, _lo, _hi in controls}
                write(prop.name, values)

            set_btn.clicked.connect(_on_set)

            def _refresh(p) -> None:
                dot.setStyleSheet(f"color: {_STATE_COLOR.get(p.state, '#888888')}; font-size: 14px;")
                live = {el.name: el.value for el in p.elements}
                for slider, spin, name, lo, hi in controls:
                    if spin.hasFocus() or slider.isSliderDown():
                        continue  # don't clobber a value the user is mid-edit on
                    value = live.get(name)
                    if value is None:
                        continue
                    numeric_value = float(value)
                    if not math.isfinite(numeric_value):
                        continue
                    spin.blockSignals(True)
                    slider.blockSignals(True)
                    spin.setValue(numeric_value)
                    fraction = ((spin.value() / 2 - lo / 2) / (hi / 2 - lo / 2)) if hi != lo else 0.0
                    slider.setValue(round(fraction * _AUX_SLIDER_STEPS))
                    spin.blockSignals(False)
                    slider.blockSignals(False)

            row.addStretch(1)  # controls sit left, beside the label column
            return row_widget, _refresh

        def _build_text_row(prop, write) -> tuple[QWidget, Callable]:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("●")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            name_label = QLabel(prop.label)
            name_label.setFixedWidth(_PROP_LABEL_WIDTH)
            name_label.setToolTip(prop.label)
            row.addWidget(name_label)

            edits: list[tuple[Any, str]] = []
            for el in prop.elements:
                if len(prop.elements) > 1:
                    row.addWidget(QLabel(el.label))
                edit = QLineEdit(str(el.value) if el.value is not None else "")
                edit.setEnabled(prop.perm != "ro")
                row.addWidget(edit, 1)
                edits.append((edit, el.name))

            set_btn = QPushButton("Set")
            set_btn.setObjectName("AccentButton")
            set_btn.setEnabled(prop.perm != "ro")
            row.addWidget(set_btn)

            def _on_set() -> None:
                write(prop.name, {name: edit.text() for edit, name in edits})

            set_btn.clicked.connect(_on_set)

            def _refresh(p) -> None:
                dot.setStyleSheet(f"color: {_STATE_COLOR.get(p.state, '#888888')}; font-size: 14px;")
                live = {el.name: el.value for el in p.elements}
                for edit, name in edits:
                    if edit.hasFocus():
                        continue
                    value = live.get(name)
                    if value is not None and edit.text() != str(value):
                        edit.setText(str(value))

            row.addStretch(1)  # controls sit left, beside the label column
            return row_widget, _refresh

        def _build_light_row(prop, write) -> tuple[QWidget, Callable]:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("●")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            name_label = QLabel(prop.label)
            name_label.setFixedWidth(_PROP_LABEL_WIDTH)
            name_label.setToolTip(prop.label)
            row.addWidget(name_label)
            element_dots = []
            for el in prop.elements:
                row.addWidget(QLabel(el.label))
                el_dot = QLabel("●")
                el_dot.setFixedWidth(16)
                row.addWidget(el_dot)
                element_dots.append((el_dot, el.name))

            def _refresh(p) -> None:
                dot.setStyleSheet(f"color: {_STATE_COLOR.get(p.state, '#888888')}; font-size: 14px;")
                live = {el.name: el.value for el in p.elements}
                for el_dot, name in element_dots:
                    el_dot.setStyleSheet(
                        f"color: {_STATE_COLOR.get(str(live.get(name)), '#888888')}; font-size: 14px;"
                    )

            row.addStretch(1)  # controls sit left, beside the label column
            return row_widget, _refresh

        _row_builders = {
            "number": _build_number_row, "switch": _build_switch_row,
            "text": _build_text_row, "light": _build_light_row,
        }

        def _new_tab_widget() -> Any:
            """A tab widget that cannot grow the window: a server can report dozens of devices and
            properties, so its size hints are ignored, the tab bar scrolls and long names are elided."""
            tabs = QTabWidget()
            tabs.setUsesScrollButtons(True)
            tabs.setElideMode(Qt.TextElideMode.ElideRight)
            tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
            tabs.setMinimumSize(0, 0)
            return tabs

        def _make_tabs(groups: list, write: Callable) -> tuple[Any, list]:
            """One tab per property group, each with a row per property; returns the tab widget and
            its ``(property name, refresh)`` pairs. *write* sends a ``(property name, values)`` edit."""
            tabs = _new_tab_widget()
            rows: list = []
            for group in groups:
                tab = QWidget()
                tab_layout = QVBoxLayout(tab)
                tab_layout.setSpacing(8)
                for prop in group.properties:
                    widget, refresh = _row_builders.get(prop.kind, _build_light_row)(prop, write)
                    tab_layout.addWidget(widget)
                    rows.append((prop.name, refresh))
                tab_layout.addStretch(1)
                # Scrolled, so a wide or long property list never sets the window's minimum size.
                scroller = QScrollArea()
                scroller.setWidgetResizable(True)
                scroller.setFrameShape(QFrame.Shape.NoFrame)
                scroller.setWidget(tab)
                tabs.addTab(scroller, group.name)
            return tabs, rows

        def _selected_tab_text(tabs) -> str | None:
            return tabs.tabText(tabs.currentIndex()) if tabs is not None and tabs.count() else None

        def _select_tab_text(tabs, text: str | None) -> None:
            if text is None:
                return
            for index in range(tabs.count()):
                if tabs.tabText(index) == text:
                    tabs.setCurrentIndex(index)
                    return

        # INDI server view (EQP-AUX-020): an outer tab per device, an inner tab per property group.
        # ``devices`` maps a device name to {"layout", "tabs", "rows", "names"}.
        state["indi"] = {"outer": None, "devices": {}}

        def _clear_container() -> None:
            while panel_container.count():
                widget = take_widget(panel_container)
                if widget is not None:
                    widget.setParent(None)
            state["indi"] = {"outer": None, "devices": {}}

        def _show_placeholder(text: str = "Connect to an INDI server to show its devices.") -> None:
            _clear_container()
            placeholder = QLabel(text)
            placeholder.setObjectName("CriteriaHeading")
            panel_container.addWidget(placeholder)

        server_ops = AuxServerOps(lambda: state.get("server"))

        def _write_indi(device: str, prop_name: str, values: dict) -> None:
            outcome = server_ops.write_property(device, prop_name, values)
            if outcome.kind == NOT_CONNECTED:
                return
            if not outcome.ok:
                self._window.statusBar().showMessage(outcome.message, 6000)
                return
            # The server confirms a change a moment later; refreshing now would flip the control back.
            QTimer.singleShot(400, _refresh_server_panel)

        def _fill_device_tab(device: str, groups: list) -> None:
            """(Re)build one device's category tabs, keeping the category the user had open."""
            dev = state["indi"]["devices"][device]
            previous = _selected_tab_text(dev["tabs"])
            while dev["layout"].count():
                widget = take_widget(dev["layout"])
                if widget is not None:
                    widget.setParent(None)
            dev["tabs"], dev["rows"] = None, []
            dev["names"] = {p.name for g in groups for p in g.properties}
            if not groups:
                note = QLabel("This device has not reported any properties yet.")
                note.setObjectName("CriteriaHeading")
                dev["layout"].addWidget(note)
                return
            tabs, rows = _make_tabs(groups, lambda name, values, device=device: _write_indi(device, name, values))
            _select_tab_text(tabs, previous)
            dev["layout"].addWidget(tabs)
            dev["tabs"], dev["rows"] = tabs, rows

        def _build_device_tabs(snapshot: dict) -> None:
            """INDI server view: one tab per device the server reports."""
            previous = _selected_tab_text(state["indi"]["outer"])
            if not snapshot:
                _show_placeholder("The INDI server reports no devices.")
                return
            _clear_container()
            outer = _new_tab_widget()
            state["indi"]["outer"] = outer
            for device, groups in snapshot.items():
                holder = QWidget()
                holder_layout = QVBoxLayout(holder)
                holder_layout.setContentsMargins(0, 6, 0, 0)
                state["indi"]["devices"][device] = {
                    "layout": holder_layout, "tabs": None, "rows": [], "names": set(),
                }
                _fill_device_tab(device, groups)
                outer.addTab(holder, device)
            _select_tab_text(outer, previous)
            panel_container.addWidget(outer)

        def _refresh_server_panel() -> None:
            if state.get("server") is None:
                return
            snapshot = server_ops.read_devices()
            if snapshot is None:
                _server_lost()
                return
            indi = state["indi"]
            if indi["outer"] is None or list(snapshot) != list(indi["devices"]):
                _build_device_tabs(snapshot)
                return
            for device, groups in snapshot.items():
                dev = indi["devices"][device]
                if not groups and dev["tabs"] is None:
                    continue
                if aux_needs_rebuild(dev["names"], groups, dev["tabs"] is not None):
                    _fill_device_tab(device, groups)
                    continue
                by_name = {p.name: p for g in groups for p in g.properties}
                for name, refresh in dev["rows"]:
                    prop = by_name.get(name)
                    if prop is not None:
                        refresh(prop)

        _show_placeholder()

        # --- connection ----------------------------------------------------
        def _is_connected() -> bool:
            return servers_by_pier.get(pier_key(self._current_pier)) is not None

        def _do_connect_server() -> None:
            import asyncio
            server = server_edit.text().strip() or "localhost"
            port = port_spin.value()
            panel = self._make_aux_server_panel(server, port)
            try:
                asyncio.run(panel.connect())
            except Exception:
                logger.exception("Could not connect to INDI server %s:%s", server, port)
                self._window.statusBar().showMessage(f"Could not connect to INDI server {server}:{port} — see log.", 6000)
                return
            servers_by_pier[pier_key(self._current_pier)] = panel
            state["server"] = panel
            logger.info("Aux: connected to INDI server %s:%s", server, port)
            self._window.statusBar().showMessage(f"Connected to INDI server {server}:{port}.", 4000)
            _clear_container()
            _refresh_server_panel()

        def _drop_server() -> None:
            import asyncio
            panel = servers_by_pier.pop(pier_key(self._current_pier), None)
            state["server"] = None
            if panel is not None:
                try:
                    asyncio.run(panel.disconnect())
                except Exception:
                    logger.exception("Aux: error closing the INDI server connection")

        def _server_lost() -> None:
            _drop_server()
            _show_placeholder("The connection to the INDI server was lost. Connect again to reload its devices.")
            self._window.statusBar().showMessage("INDI server connection lost — see log.", 6000)
            if "sync_connect" in state:
                state["sync_connect"]()

        from ._connect_toggle import install_connect_toggle
        state["sync_connect"] = install_connect_toggle(
            connect_btn, _is_connected, _do_connect_server, lambda: state["disconnect"](),
        )

        # --- footer: Save + Log ---------------------------------------------
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        save_btn.setToolTip("Save this server and port under the selected Observatory and Pier.")
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        layout.addWidget(log_heading)
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)
        layout.addWidget(log_pane)

        def save_aux_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_device_config
            # The Pier browses its whole server, so no single device is saved with it.
            save_device_config(
                self._current_pier, "aux",
                driver="INDI", server=server_edit.text().strip(), port=port_spin.value(), device_name=None,
            )
            logger.info(
                "Saved Control Panel settings for Pier %r: INDI %s:%s",
                self._current_pier.name, server_edit.text().strip(), port_spin.value(),
            )
            self._window.statusBar().showMessage(
                f"Saved Control Panel settings for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_aux_config)

        def reload_page() -> None:
            cfg = None
            if self._current_pier is not None:
                from galileo.observatory import get_device_config
                try:
                    cfg = get_device_config(self._current_pier, "aux")
                except Exception:
                    logger.exception("Could not load saved Aux config")

            server_edit.blockSignals(True)
            port_spin.blockSignals(True)
            try:
                if cfg is not None and cfg.driver == "INDI":  # an Alpaca setting from an older version is ignored
                    server_edit.setText(cfg.server)
                    port_spin.setValue(cfg.port)
                else:
                    server_edit.clear()
                    port_spin.setValue(_DEFAULT_PORTS["INDI"])
            finally:
                server_edit.blockSignals(False)
                port_spin.blockSignals(False)

            state["server"] = servers_by_pier.get(pier_key(self._current_pier))
            if state["server"] is not None:
                _clear_container()  # the Pier's server panel is rebuilt from the live property cache
                _refresh_server_panel()
            else:
                _show_placeholder()

        def autoconnect_page() -> None:
            # Only reconnect when a server was saved; never guess localhost at start-up.
            if not _is_connected() and server_edit.text().strip():
                _do_connect_server()

        def disconnect_page() -> None:
            """Pier-level Disconnect button: close this Pier's INDI server connection."""
            if not _is_connected():
                return
            _drop_server()
            _show_placeholder()
            self._window.statusBar().showMessage("INDI server disconnected.", 4000)

        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _refresh_server_panel))
        status_timer.start(2000)

        state["refresh"] = _refresh_server_panel
        state["reload"] = reload_page
        state["autoconnect"] = autoconnect_page
        state["disconnect"] = disconnect_page
        state["connected"] = _is_connected
        self._device_pages["aux"] = state
        reload_page()
        if self._startup_autoconnect_allowed():
            autoconnect_page()

        return page
