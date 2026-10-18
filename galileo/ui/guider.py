# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Guider screen (GUIDE-070 … GUIDE-090): a live view onto PHD2.

Laid out after the reference guiding screen (assets/samples/guide.png): control
panel, scope info and guide statistics on the left; the guide-star image, the
guide graph and the mount-drift / calibration plots on the right; PHD2's event
log along the bottom.

Everything shown comes from ``galileo.guiding.GuideModel`` — the page polls a
snapshot on a timer instead of being called from PHD2's reader thread, so no
Qt object is ever touched off the UI thread. Commands go out through
``GuidingService`` and return immediately; a rejected command shows up in the
log pane.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from galileo.guiding import DEC_GUIDE_MODES, GuideSnapshot, GuidingService
from galileo.ui._image_view import build_zoom_toolbar
from galileo.ui.guider_plots import (  # noqa: F401  (re-exported: these used to live in this module)
    CalibrationPlot,
    DriftGraph,
    DriftScatter,
    StarView,
    _DEC,
    _Lamp,
    _PLOT_BG,
    _PLOT_FG,
    _PlotBase,
    _RA,
    _SNR,
    _Y_RANGES,
    _format_ago,
)

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 4400
DRIVER_NAME = "PHD2"  # what the Guider's saved DeviceConfigRecord.driver holds


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("CriteriaHeading")
    return label


class GuiderPage(QWidget):
    """The Guiding section. One PHD2 connection per Pier (GUIDE-060)."""

    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("GuiderPage")
        self._window = window
        self._services: dict = {}
        self._connecting: set = set()
        self._saved_phd2 = False
        self._last_key: tuple | None = None
        self._ticks = 0
        self._build()
        self.refresh_view(None)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(250)

    # --- Layout -----------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        title = QLabel("Guiding")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        # connection row: PHD2 has no device list to scan — it is one host:port
        row = QHBoxLayout()
        row.addWidget(QLabel("PHD2 host"))
        self.host_edit = QLineEdit(DEFAULT_HOST)
        self.host_edit.setPlaceholderText("FQDN or IP of the machine running PHD2, e.g. localhost or 192.168.1.50")
        self.host_edit.setMaxLength(60)
        row.addWidget(self.host_edit, 1)
        row.addWidget(QLabel("Port"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_PORT)
        self.port_spin.setToolTip("PHD2's event-server port: 4400 for the first PHD2 instance, 4401 for the second, …")
        row.addWidget(self.port_spin)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("AccentButton")
        self.connect_btn.clicked.connect(self.connect_to_phd2)
        row.addWidget(self.connect_btn)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.disconnect_from_phd2)
        row.addWidget(self.disconnect_btn)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("AccentButton")
        self.save_btn.setToolTip("Save this host and port under the selected Observatory and Pier.")
        self.save_btn.clicked.connect(self.save)
        row.addWidget(self.save_btn)
        layout.addLayout(row)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        content = QWidget()
        grid = QHBoxLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        grid.addWidget(self._build_left_column())
        grid.addLayout(self._build_right_column(), 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # PHD2's own event log (newest first), not the application log the other pages tail.
        self.event_log = self._window._build_log_pane()
        self.event_log.setFixedHeight(self.event_log.fontMetrics().lineSpacing() * 7 + 12)
        layout.addWidget(self.event_log)

    def _build_left_column(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(340)
        box = QVBoxLayout(column)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)

        train_row = QHBoxLayout()
        train_row.addWidget(QLabel("Optic:"))
        self.train_combo = QComboBox()
        self.train_combo.currentIndexChanged.connect(lambda _i: self._force_render())
        train_row.addWidget(self.train_combo, 1)
        box.addLayout(train_row)

        box.addWidget(_heading("Control"))
        buttons = QGridLayout()
        self.loop_btn = QPushButton("Loop")
        self.guide_btn = QPushButton("Guide")
        self.guide_btn.setObjectName("AccentButton")
        self.stop_btn = QPushButton("Stop")
        self.find_btn = QPushButton("Auto Star")
        self.dither_btn = QPushButton("Dither")
        for i, button in enumerate((self.loop_btn, self.guide_btn, self.stop_btn)):
            buttons.addWidget(button, 0, i)
        buttons.addWidget(self.find_btn, 1, 0)
        buttons.addWidget(self.dither_btn, 1, 1)
        box.addLayout(buttons)
        self.loop_btn.clicked.connect(lambda: self._send("loop"))
        self.guide_btn.clicked.connect(lambda: self._send("guide", recalibrate=self.recal_check.isChecked()))
        self.stop_btn.clicked.connect(lambda: self._send("stop"))
        self.find_btn.clicked.connect(lambda: self._send("find_star"))
        self.dither_btn.clicked.connect(lambda: self._send("request_dither"))

        form = QGridLayout()
        form.addWidget(QLabel("Exp:"), 0, 0)
        self.exposure_combo = QComboBox()
        self.exposure_combo.activated.connect(self._on_exposure_chosen)
        form.addWidget(self.exposure_combo, 0, 1)
        form.addWidget(QLabel("Dec:"), 1, 0)
        self.dec_combo = QComboBox()
        self.dec_combo.addItems(DEC_GUIDE_MODES)
        self.dec_combo.setProperty("helpKey", "dec guide mode")
        self.dec_combo.setToolTip("Which Dec corrections PHD2 may send: Off, Auto (both), or North / South only.")
        self.dec_combo.activated.connect(lambda _i: self._send("set_dec_guide_mode", self.dec_combo.currentText()))
        form.addWidget(self.dec_combo, 1, 1)
        self.recal_check = QCheckBox("Recalibrate on Guide")
        form.addWidget(self.recal_check, 2, 0, 1, 2)
        self.clear_cal_btn = QPushButton("Clear Calibration")
        self.clear_cal_btn.clicked.connect(lambda: self._send("clear_calibration"))
        form.addWidget(self.clear_cal_btn, 3, 0, 1, 2)
        box.addLayout(form)

        equip = QHBoxLayout()
        self.equip_connect_btn = QPushButton("Connect Equipment")
        self.equip_connect_btn.setToolTip("Tell PHD2 to connect its own camera and mount.")
        self.equip_disconnect_btn = QPushButton("Disconnect Equipment")
        self.equip_connect_btn.clicked.connect(lambda: self._send("set_equipment_connected", True))
        self.equip_disconnect_btn.clicked.connect(lambda: self._send("set_equipment_connected", False))
        equip.addWidget(self.equip_connect_btn)
        equip.addWidget(self.equip_disconnect_btn)
        box.addLayout(equip)

        box.addWidget(_heading("Scope / Lens Info"))
        scope = QGridLayout()
        self.scope_values = {}
        for i, (key, text) in enumerate((
            ("focal", "Focal length"), ("aperture", "Aperture"), ("ratio", "Focal ratio"),
            ("scale", "Guide scale"), ("fov", "Guide FOV"),
        )):
            scope.addWidget(QLabel(text), i, 0)
            self.scope_values[key] = QLabel("—")
            scope.addWidget(self.scope_values[key], i, 1)
        box.addLayout(scope)

        box.addWidget(_heading("Guide Info"))
        info = QGridLayout()
        self.info_unit_labels = {}
        info.addWidget(QLabel("RA"), 0, 1)
        info.addWidget(QLabel("DEC"), 0, 2)
        self.info: dict[str, tuple[QLabel, ...]] = {}
        rows = (("delta", "Guiding delta"), ("pulse", "Pulse length (ms)"), ("rms", "RMS (RA/DEC)"))
        for i, (key, text) in enumerate(rows, start=1):
            label = QLabel(text)
            self.info_unit_labels[key] = label
            info.addWidget(label, i, 0)
            self.info[key] = (QLabel("—"), QLabel("—"))
            info.addWidget(self.info[key][0], i, 1)
            info.addWidget(self.info[key][1], i, 2)
        for i, (key, text) in enumerate((("total", "Total RMS"), ("snr", "Guide SNR"), ("star", "Star mass / HFD")), start=4):
            info.addWidget(QLabel(text), i, 0)
            self.info[key] = (QLabel("—"),)
            info.addWidget(self.info[key][0], i, 1, 1, 2)
        box.addLayout(info)

        lamps = QHBoxLayout()
        self.lamps = {"idle": _Lamp("#31c24a"), "prep": _Lamp("#f0d020"), "run": _Lamp("#e04040")}
        for key, text in (("idle", "Idle"), ("prep", "Prep"), ("run", "Run")):
            lamps.addWidget(self.lamps[key])
            lamps.addWidget(QLabel(text))
            lamps.addStretch(1)
        box.addLayout(lamps)
        self.state_label = QLabel("")
        self.state_label.setProperty("helpKey", "guiding state")
        box.addWidget(self.state_label)
        box.addStretch(1)
        return column

    def _build_right_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)
        self.star_view = StarView()
        self.star_view.setProperty("helpKey", "guide star")
        column.addLayout(build_zoom_toolbar(self.star_view))
        column.addWidget(self.star_view, 3)

        lower = QHBoxLayout()
        graph_box = QVBoxLayout()
        self.graph = DriftGraph()
        self.graph.setProperty("helpKey", "guide graph")
        graph_box.addWidget(self.graph, 1)

        toggles = QGridLayout()
        self.toggle_checks = {}
        for i, (key, text) in enumerate((
            ("ra", "RA"), ("dec", "DEC"), ("snr", "SNR"), ("corr_ra", "Corr RA"), ("corr_dec", "Corr DEC"), ("rms", "RMS"),
        )):
            check = QCheckBox(text)
            check.setChecked(self.graph.series[key])
            check.toggled.connect(lambda on, k=key: self._toggle_series(k, on))
            self.toggle_checks[key] = check
            toggles.addWidget(check, i // 3, i % 3)
        zoom_in, zoom_out = QPushButton("+"), QPushButton("−")
        zoom_in.setProperty("helpKey", "graph zoom in")
        zoom_out.setProperty("helpKey", "graph zoom out")
        zoom_in.setToolTip("Zoom the guide graph in (smaller error range).")
        zoom_out.setToolTip("Zoom the guide graph out (larger error range).")
        zoom_in.clicked.connect(lambda: self.graph.zoom(1))
        zoom_out.clicked.connect(lambda: self.graph.zoom(-1))
        toggles.addWidget(zoom_in, 0, 3)
        toggles.addWidget(zoom_out, 1, 3)
        toggles.addWidget(QLabel("Trace:"), 0, 4)
        trace = QSlider(Qt.Orientation.Horizontal)
        trace.setRange(30, 600)
        trace.setValue(int(self.graph.window_s))
        trace.setToolTip("How many seconds of history the graph shows.")
        trace.valueChanged.connect(self._set_window)
        toggles.addWidget(trace, 1, 4)
        toggles.setColumnStretch(4, 1)
        graph_box.addLayout(toggles)
        lower.addLayout(graph_box, 1)

        self.plot_tabs = QTabWidget()
        self.scatter = DriftScatter()
        self.scatter.setProperty("helpKey", "mount drift")
        self.calibration_plot = CalibrationPlot()
        self.calibration_plot.setProperty("helpKey", "calibration plot")
        drift_tab = QWidget()
        drift_box = QVBoxLayout(drift_tab)
        drift_box.setContentsMargins(0, 0, 0, 0)
        drift_box.addWidget(self.scatter, 1)
        ring_row = QHBoxLayout()
        ring_row.addStretch(1)
        ring_row.addWidget(QLabel("Ring:"))
        self.ring_spin = QDoubleSpinBox()
        self.ring_spin.setRange(0.1, 10.0)
        self.ring_spin.setSingleStep(0.5)
        self.ring_spin.setValue(self.scatter.ring)
        self.ring_spin.setToolTip("Radius of the green target ring; the yellow and red rings are 2× and 3× this.")
        self.ring_spin.valueChanged.connect(self._set_ring)
        ring_row.addWidget(self.ring_spin)
        drift_box.addLayout(ring_row)
        self.plot_tabs.addTab(drift_tab, "Mount Drift")
        self.plot_tabs.addTab(self.calibration_plot, "Calibration Plot")
        self.plot_tabs.setFixedWidth(300)
        lower.addWidget(self.plot_tabs)
        column.addLayout(lower, 2)
        return column

    # --- Small handlers ---------------------------------------------------

    def _toggle_series(self, key: str, on: bool) -> None:
        self.graph.series[key] = on
        self.graph.update()

    def _set_window(self, seconds: int) -> None:
        self.graph.window_s = float(seconds)
        self.graph.update()

    def _set_ring(self, value: float) -> None:
        self.scatter.ring = value
        self.scatter.update()

    def _force_render(self) -> None:
        self._last_key = None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_tubes()

    # --- Pier persistence (registered as the page's "reload"/"autoconnect") ----

    def _pier_key(self):
        return getattr(self._window._current_pier, "id", None)

    def reload(self) -> None:
        """Load this Pier's saved PHD2 host/port, and forget nothing about its live connection."""
        cfg = None
        if self._window._current_pier is not None:
            from galileo.observatory import get_device_config
            try:
                cfg = get_device_config(self._window._current_pier, "guider")
            except Exception:
                logger.exception("Could not load saved guider config")
        self._saved_phd2 = cfg is not None and cfg.driver == DRIVER_NAME
        # A guider saved before PHD2 support (an INDI/Alpaca device) has no PHD2 host to offer.
        host, port = (cfg.server or DEFAULT_HOST, cfg.port) if cfg is not None and self._saved_phd2 else (DEFAULT_HOST, DEFAULT_PORT)
        service = self._services.get(self._pier_key())
        if service is not None and service.is_connected:
            host, port = service.host, service.port
        self.host_edit.setText(host)
        self.port_spin.setValue(port)
        self.refresh_tubes()
        self._force_render()

    def autoconnect(self) -> None:
        """Reconnect to a saved PHD2 host after a Pier switch or at startup."""
        service = self._services.get(self._pier_key())
        if self._saved_phd2 and (service is None or not service.is_connected):
            self.connect_to_phd2()

    def save(self) -> None:
        pier = self._window._current_pier
        if pier is None:
            QMessageBox.warning(
                self._window._window, "No Pier selected",
                "Select (or create) an Observatory and Pier before saving equipment settings.",
            )
            return
        from galileo.observatory import save_device_config
        host = self.host_edit.text().strip() or DEFAULT_HOST
        try:
            save_device_config(pier, "guider", driver=DRIVER_NAME, server=host,
                               port=self.port_spin.value(), device_name=DRIVER_NAME)
        except Exception:
            logger.exception("Could not save guider config for Pier %r", pier.name)
            return
        self._saved_phd2 = True
        logger.info("Saved guider settings for Pier %r: PHD2 at %s:%s", pier.name, host, self.port_spin.value())
        self._window._window.statusBar().showMessage(f"Saved guider settings for Pier {pier.name!r}.", 4000)

    def refresh_tubes(self) -> None:
        """Repopulate the Train selector from the Pier's saved optical tubes."""
        from galileo.ui.app_window import _optical_tube_label
        tubes = []
        if self._window._current_pier is not None:
            from galileo.observatory import list_optical_tubes
            try:
                tubes = list_optical_tubes(self._window._current_pier)
            except Exception:
                logger.exception("Could not load optical tubes for the Guider screen")
        previous = self.train_combo.currentIndex()
        self.train_combo.blockSignals(True)
        self.train_combo.clear()
        for i, tube in enumerate(tubes):
            self.train_combo.addItem(_optical_tube_label(tube, i), tube)
        if not tubes:
            self.train_combo.addItem("None defined — see Equipment > Optics", None)
        self.train_combo.setCurrentIndex(previous if 0 <= previous < self.train_combo.count() else 0)
        self.train_combo.blockSignals(False)
        self._force_render()

    # --- Connection and commands ------------------------------------------

    def _service(self) -> GuidingService | None:
        return self._services.get(self._pier_key())

    def connect_to_phd2(self) -> None:
        key = self._pier_key()
        host = self.host_edit.text().strip() or DEFAULT_HOST
        port = self.port_spin.value()
        service = self._services.get(key)
        if service is not None and service.is_connected:
            return
        if key in self._connecting:
            return
        if service is None or (service.host, service.port) != (host, port):
            service = self._services[key] = GuidingService(host, port)
        self._connecting.add(key)
        service.model.log(f"Connecting to PHD2 at {host}:{port}…")
        threading.Thread(target=self._connect_worker, args=(key, service), name="phd2-connect", daemon=True).start()
        self._force_render()

    def _connect_worker(self, key, service: GuidingService) -> None:
        import asyncio
        try:
            asyncio.run(service.connect())
            service.sync_state()
        except Exception as exc:
            logger.warning("Could not connect to PHD2 at %s:%s: %s", service.host, service.port, exc)
            service.model.log(f"Could not connect to PHD2 at {service.host}:{service.port}: {exc}")
        finally:
            self._connecting.discard(key)

    def disconnect_from_phd2(self) -> None:
        service = self._service()
        if service is not None:
            import asyncio
            asyncio.run(service.disconnect())
        self._force_render()

    def _send(self, command: str, *args, **kwargs) -> None:
        service = self._service()
        if service is None or not service.is_connected:
            return
        method: Callable[..., object] = {"guide": service.guide, "loop": service.loop, "stop": service.stop,
                  "find_star": service.find_star, "request_dither": service.request_dither,
                  "set_dec_guide_mode": service.set_dec_guide_mode, "clear_calibration": service.clear_calibration,
                  "set_equipment_connected": service.set_equipment_connected}[command]
        method(*args, **kwargs)

    def _on_exposure_chosen(self, index: int) -> None:
        ms = self.exposure_combo.itemData(index)
        service = self._service()
        if ms is not None and service is not None and service.is_connected:
            service.set_exposure(ms)

    # --- Refresh ----------------------------------------------------------

    def _tick(self) -> None:
        service = self._service()
        self._ticks += 1
        if service is not None and self._ticks % 4 == 0:
            service.poll(want_star_image=self.isVisible())
        key = (id(service), service.model.version if service else None, self._pier_key() in self._connecting)
        if key != self._last_key:
            self._last_key = key
            self.refresh_view(service.model.snapshot() if service else None)

    def refresh_view(self, snap: GuideSnapshot | None) -> None:
        connected = snap is not None and snap.connected
        equipment = snap is not None and snap.connected and snap.equipment_connected
        state = snap.app_state if snap else "Stopped"

        self._apply_connection_controls(snap, connected, equipment)
        self._apply_state_buttons(connected, equipment, state)

        self._render_choices(snap)
        for key, lamp in self.lamps.items():
            lamp.set_on(snap is not None and connected and snap.phase == key)
        self.state_label.setText(f"State: {state}{' (settling)' if snap and snap.settling else ''}" if connected else "")

        tube = self.train_combo.currentData()
        self._render_scope(tube, snap)
        self._render_info(snap)
        self._render_plots(snap)

        text = "\n".join(reversed(snap.log)) if snap else ""  # newest first, like the reference screen
        if self.event_log.toPlainText() != text:
            self.event_log.setPlainText(text)

    def _apply_connection_controls(self, snap: GuideSnapshot | None, connected: bool, equipment: bool) -> None:
        """The PHD2 host/port/Connect/Disconnect controls and the one-line connection status."""
        connecting = self._pier_key() in self._connecting
        self.host_edit.setEnabled(not connected and not connecting)
        self.port_spin.setEnabled(not connected and not connecting)
        self.connect_btn.setEnabled(not connected and not connecting)
        self.connect_btn.setText("Connecting…" if connecting else "Connect")
        self.disconnect_btn.setEnabled(connected)
        if snap is not None and connected:
            version = f" (PHD2 {snap.phd_version})" if snap.phd_version else ""
            equip = "equipment connected" if equipment else "equipment not connected — use Connect Equipment"
            self.status_label.setText(f"Connected to PHD2{version} — {equip}.")
        else:
            self.status_label.setText("Not connected to PHD2. Start PHD2, then enter its host and click Connect.")

    def _apply_state_buttons(self, connected: bool, equipment: bool, state: str) -> None:
        """Enable each guiding control only in the PHD2 states where it makes sense."""
        idle_states = ("Stopped", "Selected", "LostLock", "Paused")
        self.equip_connect_btn.setEnabled(connected and not equipment)
        self.equip_disconnect_btn.setEnabled(equipment)
        self.loop_btn.setEnabled(equipment and state in idle_states)
        self.guide_btn.setEnabled(equipment and state in ("Stopped", "Selected", "Looping", "LostLock", "Paused"))
        self.stop_btn.setEnabled(equipment and state != "Stopped")
        self.find_btn.setEnabled(equipment and state in ("Looping", "Selected", "LostLock"))
        self.dither_btn.setEnabled(equipment and state == "Guiding")
        self.exposure_combo.setEnabled(connected)
        self.dec_combo.setEnabled(connected)
        self.clear_cal_btn.setEnabled(equipment and state not in ("Calibrating", "Guiding"))

    def _render_plots(self, snap: GuideSnapshot | None) -> None:
        """Feed the drift graph, scatter plot, calibration plot and star view from the snapshot (or clear them)."""
        samples = snap.samples if snap else []
        pixel_scale = snap.pixel_scale if snap else None
        unit = snap.unit if snap else "px"
        self.graph.set_data(samples, pixel_scale, unit, snap.rms_ra if snap else 0.0, snap.rms_dec if snap else 0.0)
        self.scatter.set_data(samples, pixel_scale, unit)
        self.calibration_plot.set_data(snap.calibration_points if snap else [], snap.calibration if snap else None)
        self.star_view.set_star_image(snap.star_image if snap else None)

    def _render_choices(self, snap: GuideSnapshot | None) -> None:
        options = list(snap.exposure_options_ms) if snap else []
        current = snap.exposure_ms if snap else None
        if current is not None and current not in options:
            options = sorted([*options, current])
        self.exposure_combo.blockSignals(True)
        self.exposure_combo.clear()
        for ms in options:
            self.exposure_combo.addItem(f"{ms / 1000:g} s", ms)
        if current is not None:
            self.exposure_combo.setCurrentIndex(options.index(current))
        self.exposure_combo.blockSignals(False)
        if snap and snap.dec_mode in DEC_GUIDE_MODES:
            self.dec_combo.setCurrentText(snap.dec_mode)

    def _render_scope(self, tube, snap: GuideSnapshot | None) -> None:
        focal = getattr(tube, "focal_length_mm", None)
        aperture = getattr(tube, "aperture_mm", None)
        scale = snap.pixel_scale if snap else None
        values = self.scope_values
        values["focal"].setText(f"{focal:g} mm" if focal else "—")
        values["aperture"].setText(f"{aperture:g} mm" if aperture else "—")
        values["ratio"].setText(f"f/{focal / aperture:.1f}" if focal and aperture else "—")
        values["scale"].setText(f"{scale:.2f} ″/px" if scale else "—")
        if snap and scale and snap.frame_size:
            width, height = (px * scale / 60 for px in snap.frame_size)
            values["fov"].setText(f"{width:.1f}′ × {height:.1f}′")
        else:
            values["fov"].setText("—")

    def _render_info(self, snap: GuideSnapshot | None) -> None:
        unit = "″" if snap and snap.pixel_scale else " px"
        self.info_unit_labels["delta"].setText(f"Guiding delta ({unit.strip()}):")
        last = snap.samples[-1] if snap and snap.samples else None
        scale = (snap.pixel_scale or 1.0) if snap else 1.0

        def put(key: str, *texts: str) -> None:
            for label, text in zip(self.info[key], texts, strict=False):
                label.setText(text)

        if last is None:
            put("delta", "—", "—")
            put("pulse", "—", "—")
            put("snr", "—")
            put("star", "—")
        else:
            put("delta", f"{last.ra * scale:+.2f}", f"{last.dec * scale:+.2f}")
            put("pulse", f"{last.ra_pulse_ms:+.0f}", f"{last.dec_pulse_ms:+.0f}")
            put("snr", f"{last.snr:.1f}")
            put("star", f"{last.star_mass:.0f} / {last.hfd:.1f}")
        if snap and snap.samples:
            put("rms", f"{snap.rms_ra:.2f}", f"{snap.rms_dec:.2f}")
            put("total", f"{snap.rms_total:.2f} {unit.strip()}")
        else:
            put("rms", "—", "—")
            put("total", "—")
