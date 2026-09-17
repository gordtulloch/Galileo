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

        from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStatusBar
        self._window = QMainWindow()
        self._window.setWindowTitle("Galileo")
        self._window.resize(1400, 900)

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

        status_bar = QStatusBar()
        status_bar.setObjectName("StatusBar")
        status_bar.showMessage("Galileo ready — no equipment connected")
        self._window.setStatusBar(status_bar)

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
        else:
            self._current_pier = next(
                p for p in list_piers(self._current_observatory) if p.name == combo.itemText(index)
            )

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
            device_pages[cat_id] = device_stack.addWidget(self._build_device_config_page(cat_id, label))

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

    def _build_device_config_page(self, cat_id: str, label: str) -> "QWidget":
        """One Equipment device-category page: Driver/Server table + scan (ARCH-050)."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QLabel, QTableWidget,
            QComboBox, QLineEdit, QSpinBox, QPushButton, QListWidget, QHeaderView,
        )

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

        def run_scan() -> None:
            results.clear()
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
                results.addItem(name)

        refresh_btn.clicked.connect(run_scan)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        layout.addWidget(log_heading)
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)
        layout.addWidget(log_pane)

        return page

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
