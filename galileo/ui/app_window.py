"""Main application window (PySide6).

A N.I.N.A.-style shell: a primary icon sidebar on the left selects the
active section; the Equipment section additionally shows a context-sensitive
secondary icon sidebar for the device category (Camera, Mount, ...); the
remaining space is the content panel for whatever is selected. Thin shell
only — it wires the domain services to the UI panels, it does not contain
domain logic itself.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Derived from this repository's own git remote — the docs/ folder doubles as
# the online manual until a dedicated documentation site exists.
_MANUAL_URL = "https://github.com/gordtulloch/Galileo/tree/main/docs"

try:
    from PySide6.QtWidgets import QMainWindow, QWidget
    _HAS_QT = True
except ImportError:
    _HAS_QT = False

_NEW_OBSERVATORY_LABEL = "New Observatory…"
_NEW_PIER_LABEL = "New Pier…"

# Per-driver default port shown in the Equipment device pages' Port field.
# Alpaca has no single standard port across devices — 11111 is the common
# ASCOM Remote/simulator default, but the project's own reference hardware
# (PSD §6.8: a Seestar S30 and S30 Pro) exposes its Alpaca bridge on 32323,
# so that's the more useful default here; either way this is only a
# starting value, editable in the UI (a wrong port surfaces as a "connection
# actively refused" error, not a silent failure).
_DEFAULT_PORTS = {"Alpaca": 32323, "INDI": 7624}


# (section_id, label, icon_name)
PRIMARY_SECTIONS = [
    ("equipment", "Equipment", "equipment"),
    ("sky_atlas", "Sky Atlas", "sky_atlas"),
    ("framing", "Framing", "framing"),
    ("flat_wizard", "Flat Wizard", "flat_wizard"),
    ("sequencer", "Sequence", "sequencer"),
    ("imaging", "Imaging", "imaging"),
    ("scheduler", "Scheduler", "scheduler"),
    ("library", "Library", "library"),
    ("variable_stars", "Variable Stars", "variable_stars"),
]

OPTIONS_SECTION = ("options", "Options", "options")

EQUIPMENT_CATEGORIES = [
    ("camera", "Camera", "camera"),
    ("mount", "Mount", "mount"),
    ("filter_wheel", "Filter Wheel", "filter_wheel"),
    ("focuser", "Focuser", "focuser"),
    ("rotator", "Rotator", "rotator"),
    ("guider", "Guider", "guider"),
    ("switch", "Switch", "switch"),
    ("flat_panel", "Flat Panel", "flat_panel"),
    ("weather", "Weather", "weather"),
    ("dome", "Dome", "dome"),
    ("safety_monitor", "Safety Monitor", "safety_monitor"),
]


def _category_enum_map() -> dict:
    from galileo.core.devices import DeviceCategory
    return {
        "camera": DeviceCategory.CAMERA,
        "mount": DeviceCategory.MOUNT,
        "filter_wheel": DeviceCategory.FILTER_WHEEL,
        "focuser": DeviceCategory.FOCUSER,
        "rotator": DeviceCategory.ROTATOR,
        "guider": DeviceCategory.GUIDER,
        "switch": DeviceCategory.SWITCH,
        "flat_panel": DeviceCategory.FLAT_PANEL,
        "weather": DeviceCategory.WEATHER_STATION,
        "dome": DeviceCategory.DOME,
        "safety_monitor": DeviceCategory.SAFETY_MONITOR,
    }


_CATEGORY_ENUM = _category_enum_map()


def _parse_alpaca_device_number(device_name: "str | None") -> "int | None":
    """Extract the Alpaca device number from a scan-result label such as
    "ZWO ASI294MM Pro (#0)" (see AlpacaAdapter.list_available_devices)."""
    if not device_name:
        return None
    import re
    match = re.search(r"\(#(\d+)\)\s*$", device_name)
    return int(match.group(1)) if match else None


class AppWindow:
    """Main Galileo application window."""

    def __init__(self) -> None:
        if not _HAS_QT:
            return

        from galileo.ui.theme import ThemeManager
        self._theme = ThemeManager()
        self._nav_columns: list["_NavColumn"] = []
        self._observatories: dict[str, object] = {}
        self._current_observatory = None
        self._current_pier = None
        self._log_panes: list = []
        self._device_pages: dict[str, dict] = {}
        self._camera_backends: dict[str, object] = {}

        from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStatusBar
        self._window = QMainWindow()
        self._window.setWindowTitle("Galileo")
        self._window.resize(1400, 900)

        # Set up before the Equipment page is built below, since building it
        # can immediately show a camera auto-connect result there.
        status_bar = QStatusBar()
        status_bar.setObjectName("StatusBar")
        status_bar.showMessage("Galileo ready — no equipment connected")
        self._window.setStatusBar(status_bar)

        central = QWidget()
        central.setObjectName("ContentArea")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_top_bar())

        body = QWidget()
        root = QHBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._primary_stack, primary_sidebar = self._build_primary_nav()
        root.addWidget(primary_sidebar)
        root.addWidget(self._primary_stack, 1)
        outer.addWidget(body, 1)

        self._window.setCentralWidget(central)

        self._theme.set_theme(self._theme.current_theme)  # applies the stylesheet

    def show(self) -> None:
        if _HAS_QT and hasattr(self, "_window"):
            self._window.showMaximized()

    # --- Top bar: Observatory / Pier selection -------------------------------

    def _build_top_bar(self) -> "QWidget":
        from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox

        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(42)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 4, 14, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Observatory:"))
        self._observatory_combo = QComboBox()
        self._observatory_combo.setMinimumWidth(180)
        self._observatory_combo.addItem(_NEW_OBSERVATORY_LABEL)
        self._observatory_combo.activated.connect(self._on_observatory_activated)
        layout.addWidget(self._observatory_combo)

        layout.addSpacing(16)

        layout.addWidget(QLabel("Pier:"))
        self._pier_combo = QComboBox()
        self._pier_combo.setMinimumWidth(180)
        self._pier_combo.setEnabled(False)
        self._pier_combo.activated.connect(self._on_pier_activated)
        layout.addWidget(self._pier_combo)

        layout.addStretch(1)
        self._load_observatories()
        return bar

    def _load_observatories(self) -> None:
        """Populate the Observatory combo from persisted records (settings
        survive restarts — see galileo.observatory.list_observatories)."""
        from galileo.observatory import list_observatories

        combo = self._observatory_combo
        try:
            records = list_observatories()
        except Exception:
            logger.exception("Could not load saved Observatories")
            records = []

        combo.blockSignals(True)
        for record in records:
            self._observatories[record.name] = record
            combo.insertItem(combo.count() - 1, record.name)
        combo.blockSignals(False)

        if records:
            combo.setCurrentIndex(0)
            self._select_observatory(records[0])
        else:
            self._refresh_pier_combo()

    def _prompt_new_name(self, title: str, label_text: str) -> "str | None":
        """Modal Name / OK / Cancel dialog used for New Pier."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QDialogButtonBox

        dialog = QDialog(self._window)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(label_text))
        name_edit = QLineEdit()
        layout.addWidget(name_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        name_edit.setFocus()

        if dialog.exec() == QDialog.Accepted:
            name = name_edit.text().strip()
            return name or None
        return None

    def _prompt_new_observatory(self) -> "dict | None":
        """Modal Name/Lat/Long/Timezone/Physical Address/Owner dialog for New Observatory."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox, QDialogButtonBox,
        )

        dialog = QDialog(self._window)
        dialog.setWindowTitle("New Observatory")
        outer = QVBoxLayout(dialog)
        form = QFormLayout()
        outer.addLayout(form)

        name_edit = QLineEdit()
        form.addRow("Name", name_edit)

        lat_edit = QDoubleSpinBox()
        lat_edit.setRange(-90.0, 90.0)
        lat_edit.setDecimals(6)
        form.addRow("Latitude", lat_edit)

        long_edit = QDoubleSpinBox()
        long_edit.setRange(-180.0, 180.0)
        long_edit.setDecimals(6)
        form.addRow("Longitude", long_edit)

        tz_edit = QLineEdit()
        tz_edit.setPlaceholderText("e.g. America/Toronto")
        form.addRow("Timezone", tz_edit)

        address_edit = QLineEdit()
        form.addRow("Physical Address", address_edit)

        owner_edit = QLineEdit()
        form.addRow("Owner", owner_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        outer.addWidget(buttons)
        name_edit.setFocus()

        if dialog.exec() != QDialog.Accepted:
            return None
        name = name_edit.text().strip()
        if not name:
            return None
        return {
            "name": name,
            "latitude": lat_edit.value(),
            "longitude": long_edit.value(),
            "timezone": tz_edit.text().strip() or None,
            "physical_address": address_edit.text().strip() or None,
            "owner": owner_edit.text().strip() or None,
        }

    def _on_observatory_activated(self, index: int) -> None:
        from galileo.observatory import create_observatory

        combo = self._observatory_combo
        if combo.itemText(index) == _NEW_OBSERVATORY_LABEL:
            fields = self._prompt_new_observatory()
            if fields and fields["name"] not in self._observatories:
                try:
                    observatory = create_observatory(**fields)
                except Exception:
                    logger.exception("Could not save new Observatory %r", fields["name"])
                    combo.setCurrentIndex(self._index_of_current_observatory(combo))
                    return
                self._observatories[observatory.name] = observatory
                combo.insertItem(combo.count() - 1, observatory.name)
                combo.setCurrentIndex(combo.count() - 2)
                self._select_observatory(observatory)
            else:
                combo.setCurrentIndex(self._index_of_current_observatory(combo))
        else:
            self._select_observatory(self._observatories[combo.itemText(index)])

    def _index_of_current_observatory(self, combo) -> int:
        if self._current_observatory is None:
            return combo.count() - 1
        idx = combo.findText(self._current_observatory.name)
        return idx if idx >= 0 else combo.count() - 1

    def _select_observatory(self, observatory) -> None:
        self._current_observatory = observatory
        self._current_pier = None
        self._refresh_pier_combo()

    def _refresh_pier_combo(self) -> None:
        from galileo.observatory import list_piers

        combo = self._pier_combo
        combo.blockSignals(True)
        combo.clear()
        if self._current_observatory is not None:
            try:
                piers = list_piers(self._current_observatory)
            except Exception:
                logger.exception("Could not load saved Piers for Observatory %r", self._current_observatory.name)
                piers = []
            for pier in piers:
                combo.addItem(pier.name)
            combo.addItem(_NEW_PIER_LABEL)
            combo.setEnabled(True)
            if piers:
                combo.setCurrentIndex(0)
                self._current_pier = piers[0]
        else:
            combo.setEnabled(False)
        combo.blockSignals(False)
        self._on_pier_changed()

    def _on_pier_activated(self, index: int) -> None:
        from galileo.observatory import create_pier, list_piers

        combo = self._pier_combo
        if combo.itemText(index) == _NEW_PIER_LABEL:
            name = self._prompt_new_name("New Pier", "Pier name:")
            existing = {p.name for p in list_piers(self._current_observatory)}
            if name and name not in existing:
                try:
                    pier = create_pier(self._current_observatory, name)
                except Exception:
                    logger.exception("Could not save new Pier %r", name)
                    combo.setCurrentIndex(self._index_of_current_pier(combo))
                    return
                combo.insertItem(combo.count() - 1, name)
                combo.setCurrentIndex(combo.count() - 2)
                self._current_pier = pier
            else:
                combo.setCurrentIndex(self._index_of_current_pier(combo))
                return
        else:
            self._current_pier = next(
                p for p in list_piers(self._current_observatory) if p.name == combo.itemText(index)
            )
        self._on_pier_changed()

    def _index_of_current_pier(self, combo) -> int:
        if self._current_pier is None:
            return combo.count() - 1
        idx = combo.findText(self._current_pier.name)
        return idx if idx >= 0 else combo.count() - 1

    # --- Primary sidebar ----------------------------------------------------

    def _build_primary_nav(self):
        from PySide6.QtWidgets import QStackedWidget
        stack = QStackedWidget()
        stack.setObjectName("PrimaryStack")

        page_builders = {
            "equipment": self._build_equipment_page,
            "sky_atlas": self._build_sky_atlas_page,
            "framing": self._build_framing_page,
        }
        pages: dict[str, int] = {}
        for section_id, label, icon_name in PRIMARY_SECTIONS:
            builder = page_builders.get(section_id)
            page = builder() if builder else self._build_placeholder_page(label)
            pages[section_id] = stack.addWidget(page)

        options_page = self._build_placeholder_page(OPTIONS_SECTION[1])
        pages[OPTIONS_SECTION[0]] = stack.addWidget(options_page)

        sidebar = _NavColumn(
            object_name="Sidebar",
            button_object_name="NavButton",
            items=PRIMARY_SECTIONS,
            bottom_items=[OPTIONS_SECTION],
            icon_size=26,
            button_min_height=64,
            accent=self._theme.accent_color,
            dim_color=self._theme.palette()["text_dim"],
            on_select=lambda section_id: stack.setCurrentIndex(pages[section_id]),
            power_action=self._request_quit,
            utility_actions=[
                ("theme", "Toggle dark/light theme", self._toggle_theme),
                ("manual", "Open online manual", self._open_manual),
                ("about", "About Galileo", self._show_about),
            ],
        )
        self._nav_columns.append(sidebar)
        stack.setCurrentIndex(pages["equipment"])
        return stack, sidebar

    def _request_quit(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _toggle_theme(self) -> None:
        from galileo.ui.theme import Theme
        new_theme = Theme.LIGHT if self._theme.current_theme == Theme.DARK else Theme.DARK
        self._theme.set_theme(new_theme)
        p = self._theme.palette()
        for column in self._nav_columns:
            column.refresh_icons(dim_color=p["text_dim"], accent=self._theme.accent_color)

    def _open_manual(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(_MANUAL_URL))

    def _show_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from galileo import __author__, __license__, __version__
        QMessageBox.about(
            self._window,
            "About Galileo",
            f"<h3>Galileo {__version__}</h3>"
            f"<p>Cross-platform astrophotography imaging suite, built on INDI and ASCOM Alpaca.</p>"
            f"<p>© {__author__} — {__license__}</p>",
        )

    # --- Equipment page (primary + secondary nav example) -------------------

    def _build_equipment_page(self) -> "QWidget":
        from PySide6.QtWidgets import QWidget, QHBoxLayout, QStackedWidget

        page = QWidget()
        page.setObjectName("EquipmentPage")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        device_stack = QStackedWidget()
        device_pages = {}
        for cat_id, label, _icon in EQUIPMENT_CATEGORIES:
            if cat_id == "camera":
                page_widget = self._build_camera_page()
            elif cat_id == "focuser":
                page_widget = self._build_focuser_page()
            else:
                page_widget = self._build_device_config_page(cat_id, label)
            device_pages[cat_id] = device_stack.addWidget(page_widget)

        secondary = _NavColumn(
            object_name="SecondarySidebar",
            button_object_name="SecondaryNavButton",
            items=EQUIPMENT_CATEGORIES,
            bottom_items=[],
            icon_size=20,
            button_min_height=52,
            accent=self._theme.accent_color,
            dim_color=self._theme.palette()["text_dim"],
            on_select=lambda cat_id: device_stack.setCurrentIndex(device_pages[cat_id]),
        )
        self._nav_columns.append(secondary)
        device_stack.setCurrentIndex(device_pages["camera"])

        layout.addWidget(secondary)
        layout.addWidget(device_stack, 1)

        from PySide6.QtCore import QTimer
        log_timer = QTimer(page)
        log_timer.timeout.connect(self._refresh_log_panes)
        log_timer.start(1000)
        self._refresh_log_panes()

        return page

    def _build_log_pane(self) -> "QPlainTextEdit":
        """A read-only, scrollable pane showing the tail of the run's log
        (LOG-020) — 10 lines tall, but keeps more history to scroll back
        through than that."""
        from PySide6.QtWidgets import QPlainTextEdit
        from PySide6.QtGui import QFontDatabase

        pane = QPlainTextEdit()
        pane.setObjectName("LogPane")
        pane.setReadOnly(True)
        pane.setUndoRedoEnabled(False)
        pane.setLineWrapMode(QPlainTextEdit.NoWrap)
        pane.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        line_height = pane.fontMetrics().lineSpacing()
        pane.setFixedHeight(line_height * 10 + pane.frameWidth() * 2 + 8)
        return pane

    def _refresh_log_panes(self) -> None:
        from galileo.diagnostics import get_recent_log_lines

        if not self._log_panes:
            return
        text = "\n".join(get_recent_log_lines(300))
        for pane in self._log_panes:
            if pane.toPlainText() == text:
                continue
            bar = pane.verticalScrollBar()
            at_bottom = bar.value() >= bar.maximum() - 2
            previous_value = bar.value()
            pane.setPlainText(text)
            bar.setValue(bar.maximum() if at_bottom else previous_value)

    # --- Camera page (shared connection, N independent camera slots) --------

    def _build_camera_page(self) -> "QWidget":
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

            download_btn = QPushButton("Download Info")
            download_btn.setToolTip(
                "Live-query this device's pixel size and sensor dimensions "
                "over its own connection (works today for Alpaca/ASCOM "
                "devices; INDI support depends on the driver)."
            )
            form.addRow(download_btn)

            return {
                "frame": frame, "title_label": title_label, "remove_btn": remove_btn,
                "device": device_combo, "pixel_size": pixel_size,
                "sensor_w": sensor_w, "sensor_h": sensor_h, "sensor_name": sensor_name,
                "download": download_btn,
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

        def _populate_device_combo(combo: "QComboBox", devices: list[str]) -> None:
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            for name in devices:
                combo.addItem(name)
            if current and combo.findText(current) < 0:
                combo.addItem(current)
            idx = combo.findText(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

        def _add_panel() -> dict:
            panel = _build_camera_panel(removable=len(panels) > 0)
            panels.append(panel)
            panels_layout.insertWidget(panels_layout.count() - 1, panel["frame"])
            _renumber_panels()
            _populate_device_combo(panel["device"], last_scanned_devices)
            if panel["remove_btn"] is not None:
                panel["remove_btn"].clicked.connect(lambda: _remove_panel(panel))
            panel["download"].clicked.connect(lambda: _download_info(panel))
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
            except Exception as exc:
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
                )

            # Prune slots from cameras that were since removed from the page.
            for stale_slot in set(list_device_config_slots(self._current_pier, "camera")) - used_slots:
                delete_device_config(self._current_pier, "camera", slot=stale_slot)

            self._window.statusBar().showMessage(
                f"Saved camera settings for Pier {self._current_pier.name!r}.", 4000
            )

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
                self._connect_camera_device(
                    slot_label, driver_combo.currentText(), server_edit.text().strip(),
                    port_spin.value(), device_name,
                )

        state = {"reload": reload_page, "autoconnect": autoconnect_page}
        self._device_pages["camera"] = state
        reload_page()
        autoconnect_page()

        return page

    # --- Focuser page (shared connection, N independent focuser slots) ------

    def _build_focuser_page(self) -> "QWidget":
        """Focuser device-category page: one shared Driver/Server/Port
        connection plus any number of independently configured focuser
        panels (a telescope can expose more than one focuser). Each panel is
        its own live status screen — Is Moving/Is Settling, Max Increment,
        Max Step, Position (current/target), Temperature Compensation, and
        Temperature — refreshed on a timer once connected, mirroring the
        Camera page's shared-connection/scroll-area/scan-to-log pattern."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QLabel, QTableWidget,
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

        # --- N independent focuser panels, sharing the connection above ----
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

            form = QFormLayout()
            outer.addLayout(form)

            device_combo = QComboBox()
            device_combo.setEditable(True)
            device_combo.addItem("")
            form.addRow("Device", device_combo)

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
                "is_moving_value": is_moving_value, "is_settling_value": is_settling_value,
                "max_increment_value": max_increment_value, "max_step_value": max_step_value,
                "position_value": position_value, "target_position": target_position,
                "move_btn": move_btn, "temp_comp_check": temp_comp_check,
                "temperature_value": temperature_value, "adapter": None,
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

        def _populate_device_combo(combo: "QComboBox", devices: list[str]) -> None:
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            for name in devices:
                combo.addItem(name)
            if current and combo.findText(current) < 0:
                combo.addItem(current)
            idx = combo.findText(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
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

        def _refresh_panel_status(panel: dict) -> None:
            adapter = panel.get("adapter")
            if adapter is None:
                return
            import asyncio
            try:
                status = asyncio.run(adapter.get_status())
            except Exception:
                logger.exception("Could not refresh status for %s", panel["title_label"].text())
                return
            _apply_status(panel, status)

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
            _refresh_panel_status(panel)

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
            except Exception as exc:
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
        status_timer.timeout.connect(lambda: [_refresh_panel_status(p) for p in panels])
        status_timer.start(2000)

        state = {"reload": reload_page, "autoconnect": autoconnect_page}
        self._device_pages["focuser"] = state
        reload_page()
        autoconnect_page()

        return page

    def _build_device_config_page(self, cat_id: str, label: str) -> "QWidget":
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
        }

        def run_scan() -> None:
            results.clear()
            page_state["selected_device"] = None
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
                results.addItem(f"No {driver} {label.lower()} devices found at {server}:{port}.")
                return
            for name in devices:
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, True)
                results.addItem(item)

        refresh_btn.clicked.connect(run_scan)

        def _on_result_clicked(item: "QListWidgetItem") -> None:
            # Only an actual scanned device is selectable — not the
            # "No devices found" / "Scan failed" info rows above.
            if item.data(Qt.UserRole):
                page_state["selected_device"] = item.text()

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

    # --- Per-Pier device configuration persistence ---------------------------

    def _load_device_config_into_page(self, cat_id: str, state: dict) -> None:
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

    def _save_device_config(self, cat_id: str, state: dict) -> None:
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
        self._window.statusBar().showMessage(
            f"Saved {cat_id} settings for Pier {self._current_pier.name!r}.", 4000
        )

    def _on_pier_changed(self) -> None:
        """Reload every built Equipment page's fields for the newly selected
        Pier, then re-attempt each page's auto-connect (currently the Camera
        and Focuser pages') for it. Reload happens for all pages first so a
        page that auto-connects never does so against another page's stale
        fields."""
        for state in self._device_pages.values():
            state["reload"]()
        for state in self._device_pages.values():
            autoconnect = state.get("autoconnect")
            if autoconnect is not None:
                autoconnect()

    def _connect_device_adapter(self, category, driver: str, server: str, port: int, device_name: str):
        """Instantiate and connect one device backend for *category*, or
        return ``None`` (having logged why) on failure. Shared by any
        Equipment page that needs a live per-device connection — the
        Camera page's auto-connect and the Focuser page's per-panel Connect
        and status polling."""
        import asyncio
        try:
            if driver == "INDI":
                from galileo.adapters.indi import get_adapter_class
                adapter = get_adapter_class(category)(host=server, port=port, device_name=device_name)
            else:
                from galileo.adapters.alpaca import get_adapter_class
                kwargs = {}
                device_number = _parse_alpaca_device_number(device_name)
                if device_number is not None:
                    kwargs["device_number"] = device_number
                adapter = get_adapter_class(category)(host=server, port=port, **kwargs)
            asyncio.run(adapter.connect())
        except Exception:
            logger.exception("Could not connect %s %r at %s:%s", category, device_name, server, port)
            return None
        return adapter

    def _connect_camera_device(self, slot_label: str, driver: str, server: str, port: int, device_name: str) -> None:
        """Connect one camera device — shared by the Camera page's Primary
        and any additional camera panels, which share a connection
        (driver/server/port) but are otherwise independent devices, each
        connected separately."""
        from galileo.core.devices import DeviceCategory
        adapter = self._connect_device_adapter(DeviceCategory.CAMERA, driver, server, port, device_name)
        if adapter is None:
            self._window.statusBar().showMessage(
                f"Could not connect to saved {slot_label} {device_name!r} — see log.", 6000
            )
            return
        self._camera_backends[slot_label] = adapter
        self._window.statusBar().showMessage(f"Connected to {slot_label} {device_name!r}.", 4000)

    # --- Sky Atlas page (secondary panel = search criteria, not icons) ------

    def _build_sky_atlas_page(self) -> "QWidget":
        from PySide6.QtWidgets import (
            QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QComboBox,
            QDoubleSpinBox, QPushButton, QListWidget, QFormLayout,
        )

        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        criteria, form = self._build_criteria_panel("Search Criteria")

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("e.g. M31")
        form.addRow("Object name", name_edit)

        type_combo = QComboBox()
        type_combo.addItem("Any")
        try:
            from galileo.planning.sky_atlas import ObjectType
            for t in ObjectType:
                type_combo.addItem(t.value)
        except ImportError:
            pass
        form.addRow("Object type", type_combo)

        max_mag = QDoubleSpinBox()
        max_mag.setRange(-5.0, 30.0)
        max_mag.setValue(99.0)
        form.addRow("Max magnitude", max_mag)

        min_size = QDoubleSpinBox()
        min_size.setRange(0.0, 500.0)
        min_size.setSuffix(" arcmin")
        form.addRow("Min size", min_size)

        search_btn = QPushButton("Search")
        search_btn.setObjectName("AccentButton")
        form.addRow(search_btn)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)

        heading = QLabel("Sky Atlas")
        heading.setObjectName("PageTitle")
        content_layout.addWidget(heading)

        results = QListWidget()
        content_layout.addWidget(results, 1)

        def run_search() -> None:
            results.clear()
            try:
                from galileo.planning.sky_atlas import SkyAtlas, ObjectType
                atlas = SkyAtlas()
                name = name_edit.text().strip()
                if name:
                    matches = atlas.search(name)
                else:
                    object_types = None
                    if type_combo.currentText() != "Any":
                        object_types = [ObjectType(type_combo.currentText())]
                    matches = atlas.filter(
                        object_types=object_types,
                        max_magnitude=max_mag.value(),
                        min_size_arcmin=min_size.value(),
                    )
            except Exception:
                logger.exception("Sky Atlas search failed")
                results.addItem("Search failed — see log for details.")
                return
            if not matches:
                results.addItem("No matching objects.")
                return
            for obj in matches[:200]:
                results.addItem(f"{obj.primary_name}   RA {obj.ra_deg:.3f}°  Dec {obj.dec_deg:.3f}°  mag {obj.magnitude:.1f}")

        search_btn.clicked.connect(run_search)
        name_edit.returnPressed.connect(run_search)

        layout.addWidget(criteria)
        layout.addWidget(content, 1)
        return page

    # --- Framing page (secondary panel = target/mosaic input criteria) ------

    def _build_framing_page(self) -> "QWidget":
        from PySide6.QtWidgets import (
            QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit,
            QDoubleSpinBox, QSpinBox, QPushButton,
        )

        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        criteria, form = self._build_criteria_panel("Target")

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Target name")
        form.addRow("Name", name_edit)

        ra_edit = QLineEdit()
        ra_edit.setPlaceholderText("HH:MM:SS")
        form.addRow("RA", ra_edit)

        dec_edit = QLineEdit()
        dec_edit.setPlaceholderText("+DD:MM:SS")
        form.addRow("Dec", dec_edit)

        rotation = QDoubleSpinBox()
        rotation.setRange(0.0, 359.9)
        rotation.setSuffix(" °")
        form.addRow("Rotation", rotation)

        cols = QSpinBox()
        cols.setRange(1, 20)
        cols.setValue(1)
        form.addRow("Mosaic cols", cols)

        rows = QSpinBox()
        rows.setRange(1, 20)
        rows.setValue(1)
        form.addRow("Mosaic rows", rows)

        overlap = QDoubleSpinBox()
        overlap.setRange(0.0, 90.0)
        overlap.setValue(10.0)
        overlap.setSuffix(" %")
        form.addRow("Overlap", overlap)

        set_target_btn = QPushButton("Set Target")
        set_target_btn.setObjectName("AccentButton")
        form.addRow(set_target_btn)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(6)

        heading = QLabel("Framing")
        heading.setObjectName("PageTitle")
        content_layout.addWidget(heading)

        fov_label = QLabel("Set a target to compute the field of view.")
        fov_label.setObjectName("PageSubtitle")
        content_layout.addWidget(fov_label)
        content_layout.addStretch(1)

        def apply_target() -> None:
            try:
                from galileo.planning.framing import FramingAssistant
                assistant = FramingAssistant.from_profile({})
                assistant.set_rotation_angle(rotation.value())
                fov = assistant.compute_fov()
                if cols.value() > 1 or rows.value() > 1:
                    mosaic = assistant.create_mosaic(
                        center_ra=0.0, center_dec=0.0,
                        cols=cols.value(), rows=rows.value(), overlap_pct=overlap.value(),
                    )
                    fov_label.setText(
                        f"FOV {fov.width_deg:.3f}° × {fov.height_deg:.3f}°  —  "
                        f"mosaic {mosaic.total_panels} panels ({cols.value()}×{rows.value()}, {overlap.value():.0f}% overlap)"
                    )
                else:
                    fov_label.setText(f"FOV {fov.width_deg:.3f}° × {fov.height_deg:.3f}° at rotation {rotation.value():.1f}°")
            except Exception:
                logger.exception("Framing FOV computation failed")
                fov_label.setText("Could not compute FOV — see log for details.")

        set_target_btn.clicked.connect(apply_target)

        layout.addWidget(criteria)
        layout.addWidget(content, 1)
        return page

    def _build_criteria_panel(self, heading: str):
        """A fixed-width form panel used where N.I.N.A. shows search/input
        criteria instead of a secondary icon column (Sky Atlas, Framing)."""
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel

        panel = QWidget()
        panel.setObjectName("CriteriaPanel")
        panel.setFixedWidth(260)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(14, 16, 14, 16)
        outer.setSpacing(10)

        title = QLabel(heading)
        title.setObjectName("CriteriaHeading")
        outer.addWidget(title)

        form = QFormLayout()
        form.setSpacing(8)
        outer.addLayout(form)
        outer.addStretch(1)
        return panel, form

    # --- Generic placeholder content -----------------------------------------

    def _build_placeholder_page(self, title: str) -> "QWidget":
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
        from PySide6.QtCore import Qt

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(6)

        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        subtitle = QLabel("This panel is not implemented yet.")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)
        layout.addStretch(1)
        return page


class _NavColumn(QWidget if _HAS_QT else object):
    """One vertical icon+label navigation column (used for both the primary
    sidebar and the Equipment section's secondary device-category sidebar).

    The primary sidebar additionally pins a Power (quit) button at the very
    bottom, with three small icon-only utility buttons (theme toggle, online
    manual, about) beneath it.
    """

    def __init__(
        self,
        object_name: str,
        button_object_name: str,
        items: list[tuple[str, str, str]],
        bottom_items: list[tuple[str, str, str]],
        icon_size: int,
        button_min_height: int,
        accent: str,
        dim_color: str,
        on_select,
        power_action=None,
        utility_actions: "list[tuple[str, str, object]] | None" = None,
    ) -> None:
        super().__init__()
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QToolButton, QButtonGroup, QSizePolicy
        from PySide6.QtCore import Qt, QSize
        from galileo.ui.icons import make_icon

        self.setObjectName(object_name)
        self.setFixedWidth(74)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(0)

        self._icon_entries: list[tuple["QToolButton", str]] = []

        group = QButtonGroup(self)
        group.setExclusive(True)

        def _set_icon_pair(btn, icon_name: str, size: int) -> None:
            btn.setIconSize(QSize(size, size))
            btn._icon_dim = make_icon(icon_name, dim_color, size)
            btn._icon_accent = make_icon(icon_name, accent, size)
            btn.setIcon(btn._icon_accent if btn.isChecked() else btn._icon_dim)
            self._icon_entries.append((btn, icon_name))

        def add_button(section_id: str, label: str, icon_name: str) -> "QToolButton":
            btn = QToolButton()
            btn.setObjectName(button_object_name)
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setMinimumHeight(button_min_height)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setText(label)
            _set_icon_pair(btn, icon_name, icon_size)
            btn.toggled.connect(lambda checked, b=btn: b.setIcon(b._icon_accent if checked else b._icon_dim))
            btn.clicked.connect(lambda _checked=False, sid=section_id: on_select(sid))
            group.addButton(btn)
            layout.addWidget(btn)
            return btn

        for section_id, label, icon_name in items:
            add_button(section_id, label, icon_name)
        if self._first_button(group) is not None:
            self._first_button(group).setChecked(True)

        layout.addStretch(1)

        for section_id, label, icon_name in bottom_items:
            add_button(section_id, label, icon_name)

        if power_action is not None:
            power_btn = QToolButton()
            power_btn.setObjectName(button_object_name)
            power_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            power_btn.setMinimumHeight(button_min_height)
            power_btn.setText("Quit")
            _set_icon_pair(power_btn, "power", icon_size)
            power_btn.clicked.connect(power_action)
            layout.addWidget(power_btn)

        if utility_actions:
            small_size = max(14, icon_size - 8)
            utility_row = QHBoxLayout()
            utility_row.setContentsMargins(4, 6, 4, 0)
            utility_row.setSpacing(2)
            for icon_name, tooltip, callback in utility_actions:
                util_btn = QToolButton()
                util_btn.setObjectName(button_object_name)
                util_btn.setToolTip(tooltip)
                util_btn.setMinimumHeight(24)
                _set_icon_pair(util_btn, icon_name, small_size)
                util_btn.clicked.connect(callback)
                utility_row.addWidget(util_btn)
            layout.addLayout(utility_row)

    def refresh_icons(self, dim_color: str, accent: str) -> None:
        """Regenerate every icon in this column after a theme/accent change."""
        from galileo.ui.icons import make_icon
        for btn, icon_name in self._icon_entries:
            size = btn.iconSize().width()
            btn._icon_dim = make_icon(icon_name, dim_color, size)
            btn._icon_accent = make_icon(icon_name, accent, size)
            checked = btn.isCheckable() and btn.isChecked()
            btn.setIcon(btn._icon_accent if checked else btn._icon_dim)

    @staticmethod
    def _first_button(group: "QButtonGroup"):
        buttons = group.buttons()
        return buttons[0] if buttons else None
