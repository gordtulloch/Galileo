# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Main application window (PySide6).

A sidebar-driven shell: a primary icon sidebar on the left selects the
active section; the Equipment section additionally shows a context-sensitive
secondary icon sidebar for the device category (Camera, Mount, ...); the
remaining space is the content panel for whatever is selected. Thin shell
only — it wires the domain services to the UI panels, it does not contain
domain logic itself.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from galileo.exceptions import MountParkedError, SlewObstructedError

if TYPE_CHECKING:
    from PySide6.QtWidgets import QButtonGroup

logger = logging.getLogger(__name__)

# How often the Star Atlas re-reads a mount's position for its reticle (SKYMAP-090).
_POINTING_POLL_MS = 3000
_SLEWING_POLL_MS = 1000

_PARKED_MESSAGE = "The mount is parked — unpark it first."
_OBSTRUCTED_MESSAGE = "Unable to slew to that area, it is obstructed"

# The Targets page's click-to-enlarge full-image overlay (SKY-080): fetched
# at this pixel size — over the same field of view the small result-tile
# thumbnail uses, just far more pixels of it — rather than upscaling the
# already-small 150px thumbnail, which would just look blurry this large.
_FULL_IMAGE_SIZE_PX = 640

# Derived from this repository's own git remote — the docs/ folder doubles as
# the online manual until a dedicated documentation site exists.
_MANUAL_URL = "https://github.com/gordtulloch/Galileo/tree/main/docs"

try:
    from PySide6.QtCore import QThread, Signal
    from PySide6.QtWidgets import QLabel, QMainWindow, QPlainTextEdit, QWidget
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
    ("star_atlas", "Star Atlas", "star_atlas"),
    ("planning", "Planning", "sky_atlas"),
    ("imaging", "Imaging", "imaging"),
    ("guiding", "Guiding", "guider"),
    ("focus", "Focus", "focus"),
    ("solve", "Solve", "solve"),
    ("library", "Library", "library"),
    ("science", "Science", "variable_stars"),
]

OPTIONS_SECTION = ("options", "Options", "options")

# Options opens onto one settings page per primary section, in the same order.
OPTIONS_ITEMS = list(PRIMARY_SECTIONS)

# Sections that open onto a secondary menu of their own, like Equipment does:
# section_id -> [(item_id, label, icon_name)].
PLANNING_ITEMS = [
    ("targets", "Targets", "sky_atlas"),
    ("sessions", "Sessions", "sequencer"),
    ("scheduler", "Scheduler", "scheduler"),
]
SCIENCE_ITEMS = [
    ("variable_stars", "Variable Stars", "variable_stars"),
]
# The Library is AstroFiler's screens: the image catalog, the imaging sessions
# built from it, header-value mappings, duplicate/merge clean-up, and cloud
# backup. Its settings are under Options > Library.
LIBRARY_ITEMS = [
    ("images", "Images", "images"),
    ("sessions", "Sessions", "sessions"),
    ("mappings", "Mappings", "mappings"),
    ("dedup", "Dedup", "dedup"),
    ("merge", "Merge Objects", "merge"),
    ("cloud", "Cloud", "cloud"),
]

# Primary sections that work with one of the Pier's optical tubes, and so show
# the top bar's Optics selector. Framing is a contextual dialog opened from
# Imaging (FRAME-070), not its own section, so it isn't listed here — the
# Optics selector it needs is already visible while Imaging itself is open.
_OPTICS_SECTIONS = ("imaging", "solve")

# Primary sections that take frames from one of the Pier's cameras, and so show
# the top bar's Camera selector (when the Pier has more than one).
# The camera selector appears wherever the optics selector does: an optical train is the tube
# *and* the camera it feeds, so a screen that needs one needs the other.
_CAMERA_SECTIONS = _OPTICS_SECTIONS

EQUIPMENT_CATEGORIES = [
    ("camera", "Camera", "camera"),
    ("mount", "Mount", "mount"),
    ("filter_wheel", "Filter Wheel", "filter_wheel"),
    ("focuser", "Focuser", "focuser"),
    ("rotator", "Rotator", "rotator"),
    ("optics", "Optics", "optics"),
    ("switch", "Switches", "switch"),
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


def _camera_slot_label(slot: str) -> str:
    """Friendly name for a camera DeviceConfigRecord slot id, matching the
    Camera page's own panel numbering (_build_camera_page's _renumber_panels:
    "Primary Camera" for slot "primary", "Camera N" for slot "camera_N")."""
    if slot == "primary":
        return "Primary Camera"
    if slot.startswith("camera_"):
        return f"Camera {slot.rsplit('_', 1)[1]}"
    return slot


def _camera_backend_key_for_slot(slot: str) -> str:
    """Map a camera DeviceConfigRecord slot id to its ``_camera_backends``
    dict key, which uses the Camera page's own auto-connect slot labels
    ("primary camera", "camera 2", ...) rather than the DB slot id."""
    if slot == "primary":
        return "primary camera"
    if slot.startswith("camera_"):
        return f"camera {slot.rsplit('_', 1)[1]}"
    return slot


def _device_association_label(category: str, slot: str, device_name: str | None) -> str:
    """Display label for a saved device in the Optics page's "Associated"
    list — e.g. ``Camera 2: ZWO ASI120MM`` — built from its category, slot
    (see ``DeviceConfigRecord``) and the device name picked on its own page."""
    category_label = next(
        (label for cat_id, label, _ in EQUIPMENT_CATEGORIES if cat_id == category),
        # Guiding is a top-level section now, but its device is still saved under the "guider" category.
        "Guider" if category == "guider" else category,
    )
    if slot == "primary":
        name = category_label
    elif slot.rsplit("_", 1)[-1].isdigit():
        name = f"{category_label} {slot.rsplit('_', 1)[-1]}"
    else:
        name = f"{category_label} ({slot})"
    return f"{name}: {device_name or 'no device selected'}"


def _optical_tube_label(tube, index: int) -> str:
    """Top-bar Optics selector entry for a saved optical tube: its name (or
    "Optical Tube N", matching the Optics page's panel title, if unnamed),
    plus focal length and focal ratio when both dimensions are set."""
    label = tube.name or f"Optical Tube {index + 1}"
    if tube.focal_length_mm and tube.aperture_mm:
        label += f" — {tube.focal_length_mm:g} mm f/{tube.focal_length_mm / tube.aperture_mm:.1f}"
    return label


def _parse_alpaca_device_number(device_name: str | None) -> int | None:
    """Extract the Alpaca device number from a scan-result label such as
    "ZWO ASI294MM Pro (#0)" (see AlpacaAdapter.list_available_devices)."""
    if not device_name:
        return None
    import re
    match = re.search(r"\(#(\d+)\)\s*$", device_name)
    return int(match.group(1)) if match else None


def _format_hms(hours: float | None) -> str:
    """Format an hour-angle-like value (Right Ascension, Sidereal Time,
    time-to-meridian) as ``HH:MM:SS`` — the Mount page's status display
    convention for astronomy software."""
    if hours is None:
        return "—"
    total_seconds = round((hours % 24.0) * 3600.0)
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_dms(degrees: float | None) -> str:
    """Format a degree value (Declination, Altitude, Azimuth, Site
    Latitude/Longitude) as ``±DD° MM' SS"`` — the Mount page's status
    display convention, matching how these are conventionally shown in
    astronomy software."""
    if degrees is None:
        return "—"
    sign = "-" if degrees < 0 else ""
    total_seconds = round(abs(degrees) * 3600.0)
    d, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{sign}{d:02d}° {m:02d}' {s:02d}\""


def _when_visible(page, refresh):
    """Wrap a status-poll callback so it only runs while ``page`` is on
    screen. The device pages poll their hardware on a timer, and each poll is
    a blocking call on the UI thread; polling a page nobody is looking at
    only makes the visible one sluggish."""
    def tick() -> None:
        if page.isVisible():
            refresh()
    return tick


class AppWindow:
    """Main Galileo application window."""

    def __init__(self) -> None:
        if not _HAS_QT:
            return

        from galileo.ui.theme import ThemeManager
        self._theme = ThemeManager()
        self._nav_columns: list[_NavColumn] = []
        self._observatories: dict[str, object] = {}
        self._current_observatory = None
        self._current_pier = None
        self._log_panes: list = []
        self._device_pages: dict[str, dict] = {}
        # One ObservatoryScheduler per Pier, shared by Planning > Sessions (Schedule/Deschedule)
        # and Planning > Scheduler (the job-queue view) — both must see the same jobs.
        self._schedulers: dict[str, object] = {}
        self._camera_backends: dict[str, object] = {}
        self._imaging_capture_thread = None
        self._imaging_filter_thread = None
        self._thumbnail_cache_worker = None
        # A single persistent SkyAtlas instance, lazily created — see _shared_sky_atlas().
        self._sky_atlas = None
        # Where each Pier's telescope is pointing, for the Star Atlas reticles (SKYMAP-090):
        # {pier key: {"ra_deg", "dec_deg", "slewing"}}, refreshed by polling the connected mount.
        self._pier_pointing: dict = {}
        self._pier_poll_thread = None
        self._tracking_thread = None     # waits for a slew to end, then starts tracking (EQP-MNT-050)
        self._current_primary_section = "equipment"
        self._active_camera_slot = "primary"
        self._active_optics_position = 0

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
        self._primary_nav = primary_sidebar
        self._apply_horizon()     # the top bar picked the Observatory before the pages existed
        root.addWidget(primary_sidebar)
        root.addWidget(self._primary_stack, 1)
        outer.addWidget(body, 1)

        self._window.setCentralWidget(central)

        self._theme.set_theme(self._theme.current_theme)  # applies the stylesheet

    def show(self) -> None:
        if _HAS_QT and hasattr(self, "_window"):
            self._window.showMaximized()

    # --- Top bar: Observatory / Pier selection -------------------------------

    def _build_top_bar(self) -> QWidget:
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

        self._pier_label = QLabel("Pier:")
        layout.addWidget(self._pier_label)
        self._pier_combo = QComboBox()
        self._pier_combo.setMinimumWidth(180)
        self._pier_combo.setEnabled(False)
        self._pier_combo.activated.connect(self._on_pier_activated)
        layout.addWidget(self._pier_combo)

        layout.addSpacing(16)

        # Which of the selected Pier's optical tubes (defined on the Equipment >
        # Optics page) this screen is working with. Only shown on the screens
        # that depend on the optics — Imaging and Solve — see _OPTICS_SECTIONS.
        self._optics_label = QLabel("Optics:")
        self._optics_label.setVisible(False)
        layout.addWidget(self._optics_label)
        self._optics_combo = QComboBox()
        self._optics_combo.setMinimumWidth(220)
        self._optics_combo.setVisible(False)
        self._optics_combo.activated.connect(self._on_optics_activated)
        layout.addWidget(self._optics_combo)

        layout.addSpacing(16)

        # Only shown on the screens that capture frames — Imaging and Solve —
        # and only when the selected Pier has more than one configured camera
        # (e.g. a Seestar S30 Pro's primary + wide-field second camera) — with
        # a single camera there's nothing to choose between, so it stays out
        # of the way.
        self._camera_label = QLabel("Camera:")
        self._camera_label.setVisible(False)
        layout.addWidget(self._camera_label)
        self._camera_combo = QComboBox()
        self._camera_combo.setMinimumWidth(180)
        self._camera_combo.setVisible(False)
        self._camera_combo.activated.connect(self._on_camera_activated)
        layout.addWidget(self._camera_combo)

        layout.addStretch(1)

        # The selected Pier's current object (IMG-140): whatever was last picked in the Star Atlas.
        self._current_object_label = QLabel()
        self._current_object_label.setObjectName("CurrentObjectLabel")
        self._current_object_label.setToolTip(
            "The current object of this Pier, set by selecting an item in the Star Atlas. Captured frames "
            "are named after it, and Solve's Slew to Target slews to it.")
        layout.addWidget(self._current_object_label)
        self._refresh_current_object()

        self._load_observatories()
        return bar

    def current_object(self):
        """The selected Pier's current object (IMG-140), or ``None``."""
        from galileo.current_object import get_current_objects
        return get_current_objects().get(self._current_pier)

    def _set_current_object(self, atlas_obj: dict) -> None:
        """A Star Atlas item was selected (any click — left, double, or right):
        it becomes the selected Pier's current object (IMG-140). Does *not*
        create a session — clicking a star only identifies/selects it
        (SKYMAP-010); a session is a deliberate, separate action the user
        takes via "Add to Session" (the Star Atlas's right-click context
        menu, or the Targets page's own button), both going through
        :meth:`_add_to_session`. This used to also auto-create a session on
        every click, which was surprising — reported as "incorrect" since a
        plain click looked identical to actually building a session."""
        from galileo.current_object import CurrentObject, get_current_objects
        if self._current_pier is None:
            self._window.statusBar().showMessage("Create a Pier to keep a current object.", 4000)
            return
        get_current_objects().set(self._current_pier, CurrentObject.from_atlas(atlas_obj))
        self._refresh_current_object()

    def _add_to_session(self, name: str, ra_deg: float, dec_deg: float) -> None:
        """Create a new session pre-populated with a Target block for
        (*name*, *ra_deg*, *dec_deg*) (SES-160) — the one shared entry point
        for every explicit "Add to Session" action (the Star Atlas's
        right-click context menu, the Targets page's own button), so the two
        never drift apart. Needs the Sessions screen (Planning > Sessions) to
        have been opened at least once this run; shows a status-bar message
        rather than silently doing nothing otherwise."""
        create_session = (self._device_pages.get("sessions") or {}).get("create_session_for_target")
        if create_session is None:
            self._window.statusBar().showMessage("Add to Session needs Planning > Sessions opened first.", 6000)
            return
        create_session(str(name), float(ra_deg), float(dec_deg))
        self._window.statusBar().showMessage(f"New session created for {name}.", 4000)

    def _shared_sky_atlas(self) -> SkyAtlas:
        """A single persistent ``SkyAtlas`` instance, reused across calls that
        need its *state* to actually persist — `add_to_target_list`'s own
        target-list accumulation (SKY-080) needs this, unlike the throwaway
        per-call instances the Targets-page search/filter code elsewhere in
        this file constructs, which are fine since the catalog itself is
        read-only and nothing those calls do needs to be remembered between
        one another."""
        if self._sky_atlas is None:
            from galileo.planning.sky_atlas import SkyAtlas
            self._sky_atlas = SkyAtlas()
        return self._sky_atlas

    def _select_result(self, obj: DeepSkyObject) -> None:
        """"Select" (a Targets-page result tile's own action button, SKY-050):
        makes *obj* the Pier's current target (IMG-140) and also adds it to
        `SkyAtlas`'s own target list (SKY-080) — reconciling two mechanisms
        this codebase previously carried in parallel with neither calling the
        other (`TODO.md`'s former "Planning (SKY-080)" gap note). A thumbnail-
        caching failure here is never fatal to Select itself, matching every
        other place in this app where a thumbnail fetch can fail silently."""
        self._set_current_object(obj.as_sequence_target())
        import asyncio
        try:
            asyncio.run(self._shared_sky_atlas().add_to_target_list(obj))
        except Exception:
            logger.debug("Could not add %s to the target list", obj.primary_name, exc_info=True)

    def _show_full_image(self, obj: DeepSkyObject) -> None:
        """Clicking a Targets-page result tile's thumbnail (SKY-080) opens a
        larger view of the same survey-image field — fetched at
        `_FULL_IMAGE_SIZE_PX`, a separate cache entry from the small 150px
        tile thumbnail (`SkyAtlas._fetch_thumbnail`'s `size_px`), not an
        upscaled copy of it, which would just look blurry this large. Shows
        the dialog immediately with a "Loading…" placeholder — the fetch
        itself is a blocking call, same as every other single-object
        thumbnail fetch in this app, but a dialog with nothing in it while
        that runs would look broken rather than just slow."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

        dialog = QDialog(self._window)
        dialog.setWindowTitle(obj.primary_name)
        layout = QVBoxLayout(dialog)
        image_label = QLabel("Loading…")
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setMinimumSize(_FULL_IMAGE_SIZE_PX, _FULL_IMAGE_SIZE_PX)
        layout.addWidget(image_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.show()
        QApplication.processEvents()

        import asyncio
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data = asyncio.run(self._shared_sky_atlas()._fetch_thumbnail(obj, size_px=_FULL_IMAGE_SIZE_PX))
        except Exception:
            logger.exception("Could not fetch full-size image for %s", obj.primary_name)
            data = b""
        finally:
            QApplication.restoreOverrideCursor()

        pixmap = QPixmap()
        if data and pixmap.loadFromData(data) and not pixmap.isNull():
            image_label.setPixmap(pixmap)
            image_label.setText("")
        else:
            image_label.setText("No image available.")
        dialog.exec()

    def _refresh_current_object(self) -> None:
        """Show the current object at the top right, and tell the Solve page what it now targets."""
        obj = self.current_object()
        self._current_object_label.setText(f"Current object: {obj.name}" if obj is not None else "Current object: none")
        solve = self._device_pages.get("solve") or {}
        if "refresh_target" in solve:
            solve["refresh_target"]()
        refresh_markers = getattr(self, "_star_atlas_refresh_markers", None)
        if refresh_markers is not None:
            refresh_markers()

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

    def _prompt_new_name(self, title: str, label_text: str) -> str | None:
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

    def _prompt_new_observatory(self) -> dict | None:
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

    # --- Top bar: Optics selection (Imaging and Solve screens) ------------

    def _refresh_optics_combo(self) -> None:
        """Repopulate the top-bar Optics selector from the current Pier's
        saved optical tubes, and show it only on the screens that work with
        one (``_OPTICS_SECTIONS``). With no tubes defined it stays visible
        but disabled, pointing the user at where to define one."""
        from galileo.observatory import list_optical_tubes

        combo = self._optics_combo
        tubes = []
        if self._current_pier is not None:
            try:
                tubes = list_optical_tubes(self._current_pier)
            except Exception:
                logger.exception("Could not load optical tubes for Pier %r", self._current_pier.name)

        combo.blockSignals(True)
        combo.clear()
        if tubes:
            for i, tube in enumerate(tubes):
                combo.addItem(_optical_tube_label(tube, i), i)
            if not 0 <= self._active_optics_position < len(tubes):
                self._active_optics_position = 0
            combo.setCurrentIndex(self._active_optics_position)
        else:
            combo.addItem("None defined — see Equipment > Optics")
            self._active_optics_position = 0
        combo.setEnabled(bool(tubes))
        combo.blockSignals(False)

        show = self._current_primary_section in _OPTICS_SECTIONS
        combo.setVisible(show)
        self._optics_label.setVisible(show)

    def _on_optics_activated(self, index: int) -> None:
        position = self._optics_combo.itemData(index)
        if position is not None:
            self._active_optics_position = position
        self._refresh_imaging_filters()

    def _active_filter_wheel(self):
        """The connected filter wheel that belongs to the active optical tube, or
        ``None``. A tube with a filter wheel associated on the Optics page owns
        it. If no tube on the Pier has one associated the wheel is unassigned, so
        it is offered to whichever tube is selected; if another tube owns it,
        this one has no wheel."""
        adapter = (self._device_pages.get("filter_wheel") or {}).get("adapter")
        if adapter is None or self._current_pier is None:
            return None
        from galileo.observatory import list_optical_tubes
        try:
            tubes = list_optical_tubes(self._current_pier)
        except Exception:
            logger.exception("Could not load optical tubes for Pier %r", self._current_pier.name)
            return adapter
        def has_wheel(tube) -> bool:
            return any(key.startswith("filter_wheel:") for key in (tube.associated or []))
        tube = self.active_optical_tube()
        if tube is not None and has_wheel(tube):
            return adapter
        return None if any(has_wheel(t) for t in tubes) else adapter

    def _refresh_imaging_filters(self) -> None:
        """Fill the Imaging page's Filter selector from the filter wheel that
        belongs to the active optical tube (see ``_active_filter_wheel``). The
        list is the wheel's own filter names, led by a blank for "no filter";
        with no wheel it is just the blank, and the box stays editable. Reads
        the names the adapter already holds rather than querying the device."""
        combo = getattr(self, "_imaging_filter_combo", None)
        if combo is None:
            return
        wheel = self._active_filter_wheel()
        names = [str(n) for n in (getattr(wheel, "filter_names", None) or [])] if wheel is not None else []
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(["", *names])
        position = getattr(wheel, "position", None)
        if current in names:
            combo.setCurrentText(current)
        elif isinstance(position, int) and 0 <= position < len(names):
            combo.setCurrentText(names[position])     # start on what the wheel is showing now
        combo.blockSignals(False)

    def _on_imaging_filter_activated(self, _index: int = -1) -> None:
        """The user picked (or typed and confirmed) a filter on the Imaging page:
        move the active tube's wheel to that slot. Text that isn't one of the
        wheel's filters, or no wheel, leaves the box as a plain frame label. Runs
        the move on a worker thread; ``_refresh_imaging_filters`` doesn't fire
        this, so re-populating the list never moves the wheel."""
        combo = getattr(self, "_imaging_filter_combo", None)
        wheel = self._active_filter_wheel()
        if combo is None or wheel is None:
            return
        names = [str(n) for n in (getattr(wheel, "filter_names", None) or [])]
        name = combo.currentText().strip()
        if name not in names or getattr(wheel, "position", None) == names.index(name):
            return
        if self._imaging_filter_thread is not None:
            self._window.statusBar().showMessage("The filter wheel is still moving.", 4000)
            return
        index = names.index(name)

        def done() -> None:
            self._imaging_filter_thread = None
            logger.info("Filter wheel: moved to %r (#%d)", name, index)
            self._window.statusBar().showMessage(f"Filter wheel at {name}.", 4000)

        def failed(message: str) -> None:
            self._imaging_filter_thread = None
            logger.error("Filter wheel move to %r (#%d) failed: %s", name, index, message)
            self._window.statusBar().showMessage("Filter change failed — see log.", 6000)

        thread = _FilterMoveThread(wheel, index, self._window)
        thread.finished_ok.connect(done)
        thread.failed.connect(failed)
        self._imaging_filter_thread = thread
        self._window.statusBar().showMessage(f"Moving filter wheel to {name}…")
        thread.start()

    def active_optical_tube(self):
        """The optical tube currently chosen in the top-bar Optics selector,
        or ``None`` if the Pier has none defined."""
        if self._current_pier is None:
            return None
        from galileo.observatory import list_optical_tubes
        try:
            tubes = list_optical_tubes(self._current_pier)
        except Exception:
            logger.exception("Could not load optical tubes for Pier %r", self._current_pier.name)
            return None
        return tubes[self._active_optics_position] if 0 <= self._active_optics_position < len(tubes) else None

    # --- Top bar: Camera selection (Imaging screen, multi-camera Piers) -----

    def _refresh_camera_combo(self) -> None:
        """Fill the top-bar Camera selector and show it on every screen that also chooses the
        optics (``_CAMERA_SECTIONS``). It is shown even when the Pier has only one camera: the
        screens that capture frames can do nothing without it, so which camera they will use — and
        whether it is connected — has to be visible rather than inferred. With none configured it
        stays visible but disabled, pointing at where to configure one."""
        from galileo.observatory import list_device_config_slots, get_device_config

        combo = self._camera_combo
        slots: list[str] = []
        if self._current_pier is not None:
            try:
                slots = list_device_config_slots(self._current_pier, "camera")
            except Exception:
                logger.exception("Could not load camera slots for Pier %r", self._current_pier.name)

        combo.blockSignals(True)
        combo.clear()
        for slot in slots:
            label = _camera_slot_label(slot)
            cfg = None
            if self._current_pier is not None:
                try:
                    cfg = get_device_config(self._current_pier, "camera", slot=slot)
                except Exception:
                    cfg = None
            if cfg is not None and cfg.device_name:
                label = f"{label} — {cfg.device_name}"
            if self._camera_backends.get(_camera_backend_key_for_slot(slot)) is None:
                # Without this the selector looks the same whether or not the camera answered,
                # and a screen refusing to capture looks like it has no reason to.
                label = f"{label} (not connected)"
            combo.addItem(label, slot)
        if not slots:
            combo.addItem("None configured — see Equipment > Camera")

        if self._active_camera_slot not in slots:
            self._active_camera_slot = slots[0] if slots else "primary"
        idx = slots.index(self._active_camera_slot) if self._active_camera_slot in slots else -1
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

        combo.setEnabled(bool(slots))
        show = self._current_primary_section in _CAMERA_SECTIONS
        combo.setVisible(show)
        self._camera_label.setVisible(show)

    def _on_camera_activated(self, index: int) -> None:
        slot = self._camera_combo.itemData(index)
        if slot:
            self._active_camera_slot = slot

    # --- Primary sidebar ----------------------------------------------------

    def _build_primary_nav(self):
        from PySide6.QtWidgets import QStackedWidget
        stack = QStackedWidget()
        stack.setObjectName("PrimaryStack")

        page_builders = {
            "equipment": self._build_equipment_page,
            "star_atlas": self._build_star_atlas_page,
            "planning": lambda: self._build_submenu_page(
                PLANNING_ITEMS, {"targets": self._build_sky_atlas_page,
                                  "sessions": self._build_sessions_page,
                                  "scheduler": self._build_scheduler_page}),
            "science": lambda: self._build_submenu_page(SCIENCE_ITEMS, {}),
            "library": self._build_library_page,
            "imaging": self._build_imaging_page,
            "guiding": self._build_guider_page,
            "focus": self._build_focus_page,
            "solve": self._build_solve_page,
        }
        pages: dict[str, int] = {}
        for section_id, label, icon_name in PRIMARY_SECTIONS:
            builder = page_builders.get(section_id)
            page = builder() if builder else self._build_placeholder_page(label)
            pages[section_id] = stack.addWidget(page)

        option_builders = {
            item_id: (lambda label=label: self._build_placeholder_page(f"{label} settings"))
            for item_id, label, _icon in OPTIONS_ITEMS
        }
        option_builders["library"] = self._build_library_settings_page
        option_builders["star_atlas"] = self._build_star_atlas_settings_page
        option_builders["planning"] = self._build_planning_settings_page
        option_builders["imaging"] = self._build_imaging_settings_page
        option_builders["focus"] = self._build_focus_settings_page
        option_builders["solve"] = self._build_solve_settings_page
        options_page = self._build_submenu_page(OPTIONS_ITEMS, option_builders)
        self._options_page = options_page
        pages[OPTIONS_SECTION[0]] = stack.addWidget(options_page)

        def _on_section_selected(section_id: str) -> None:
            self._current_primary_section = section_id
            stack.setCurrentIndex(pages[section_id])
            # The library is about the whole catalog, not any one Pier's equipment.
            for widget in (self._pier_label, self._pier_combo):
                widget.setVisible(section_id != "library")
            self._refresh_optics_combo()
            self._refresh_camera_combo()
            self._refresh_imaging_filters()

        sidebar = _NavColumn(
            object_name="Sidebar",
            button_object_name="NavButton",
            items=PRIMARY_SECTIONS,
            bottom_items=[OPTIONS_SECTION],
            icon_size=26,
            button_min_height=64,
            accent=self._theme.accent_color,
            dim_color=self._theme.palette()["text_dim"],
            on_select=_on_section_selected,
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
        from galileo import __version__
        from galileo.copyright import COPYRIGHT_NOTICE, LICENSE_NOTICE
        QMessageBox.about(
            self._window,
            "About Galileo",
            f"<h3>Galileo {__version__}</h3>"
            f"<p>Cross-platform astrophotography imaging suite, built on INDI and ASCOM Alpaca.</p>"
            f"<p>{COPYRIGHT_NOTICE}<br>{LICENSE_NOTICE}</p>",
        )

    def _build_submenu_page(self, items: list, builders: dict) -> QWidget:
        """A primary section with a secondary icon menu down its left edge
        (the same layout as Equipment): one page per ``(id, label, icon)`` in
        ``items``, built by ``builders[id]`` or, if none is given, a
        placeholder."""
        from PySide6.QtWidgets import QWidget, QHBoxLayout, QStackedWidget

        page = QWidget()
        page.setObjectName("SubmenuPage")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        stack = QStackedWidget()
        indexes: dict[str, int] = {}
        for item_id, label, _icon in items:
            builder = builders.get(item_id)
            indexes[item_id] = stack.addWidget(builder() if builder else self._build_placeholder_page(label))

        secondary = _NavColumn(
            object_name="SecondarySidebar",
            button_object_name="SecondaryNavButton",
            items=items,
            bottom_items=[],
            icon_size=20,
            button_min_height=52,
            accent=self._theme.accent_color,
            dim_color=self._theme.palette()["text_dim"],
            on_select=lambda item_id: stack.setCurrentIndex(indexes[item_id]),
        )
        self._nav_columns.append(secondary)
        page._secondary_nav = secondary
        stack.setCurrentIndex(indexes[items[0][0]])

        layout.addWidget(secondary)
        layout.addWidget(stack, 1)
        return page

    # --- Library page (AstroFiler's screens) ---------------------------------

    def _build_library_page(self) -> QWidget:
        """Library section: Images, Sessions, Mappings, Dedup and Cloud — see
        ``galileo.ui.library.pages``. The screens read the whole catalog, so
        they are only built when the section is first opened."""
        from galileo.ui.library.pages import LibraryScreens

        screens = LibraryScreens(on_configure=self._open_library_settings)
        self._library_screens = screens
        return self._build_submenu_page(
            LIBRARY_ITEMS, {item_id: (lambda item_id=item_id: screens.page(item_id)) for item_id, _l, _i in LIBRARY_ITEMS})

    def _build_library_settings_page(self) -> QWidget:
        """Options > Library: repository folders, cloud, compression, telescope
        credentials and the rest of ``library.ini`` — see
        ``galileo.ui.library.config_widget``."""
        from galileo.ui.library.config_widget import ConfigWidget
        return ConfigWidget()

    def _open_library_settings(self) -> None:
        """Jump to Options > Library (e.g. from the Cloud page's Configure button)."""
        self._primary_nav.select(OPTIONS_SECTION[0])
        self._options_page._secondary_nav.select("library")

    # --- Equipment page (primary + secondary nav example) -------------------

    def _build_equipment_page(self) -> QWidget:
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
            elif cat_id == "mount":
                page_widget = self._build_mount_page()
            elif cat_id == "filter_wheel":
                page_widget = self._build_filter_wheel_page()
            elif cat_id == "rotator":
                page_widget = self._build_rotator_page()
            elif cat_id == "optics":
                page_widget = self._build_optics_page()
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

    def _build_log_pane(self) -> QPlainTextEdit:
        """A read-only, scrollable pane showing the tail of the run's log
        (LOG-020) — 10 lines tall, but keeps more history to scroll back
        through than that."""
        from PySide6.QtWidgets import QPlainTextEdit
        from PySide6.QtGui import QFontDatabase

        pane = _LogPane()
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
            self.set_log_pane_text(pane, text)

    @staticmethod
    def set_log_pane_text(pane: QPlainTextEdit, text: str) -> None:
        """Show *text* in a log pane, staying scrolled to the newest line if it was
        (and otherwise where the user left it). Shared by every screen with a live log tail."""
        if pane.toPlainText() == text:
            return
        bar = pane.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 2
        previous_value = bar.value()
        pane.setPlainText(text)
        bar.setValue(bar.maximum() if at_bottom else previous_value)

    # --- Camera page (shared connection, N independent camera slots) --------

    def _build_camera_page(self) -> QWidget:
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

    # --- Focuser page (shared connection, N independent focuser slots) ------

    def _build_focuser_page(self) -> QWidget:
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

    def _build_mount_page(self) -> QWidget:
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
            QPushButton, QCheckBox, QHeaderView, QMessageBox, QScrollArea,
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

        main_row.addWidget(status_frame, 1)

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

        rates_form = QFormLayout()
        rates_form.setVerticalSpacing(2)
        primary_rate_spin = QDoubleSpinBox()
        primary_rate_spin.setRange(0.01, 10.0)
        primary_rate_spin.setDecimals(2)
        primary_rate_spin.setValue(1.0)
        rates_form.addRow("Primary rate", primary_rate_spin)
        secondary_rate_spin = QDoubleSpinBox()
        secondary_rate_spin.setRange(0.01, 10.0)
        secondary_rate_spin.setDecimals(2)
        secondary_rate_spin.setValue(1.0)
        rates_form.addRow("Secondary rate", secondary_rate_spin)
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
        home_park_col.addWidget(home_btn)
        home_park_col.addWidget(park_btn)
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
        main_scroll.setFrameShape(QFrame.NoFrame)
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
            at_park = status.get("at_park")
            state["at_park"] = at_park
            park_btn.setText("Unpark" if at_park else "Park")

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
            from galileo.core.devices import DeviceCategory
            adapter = self._connect_device_adapter(
                DeviceCategory.MOUNT, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to Mount {device_name!r} — see log.", 6000)
                return
            state["adapter"] = adapter
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
            primary_rate = primary_rate_spin.value() * (-1.0 if primary_reversed_check.isChecked() else 1.0)
            secondary_rate = secondary_rate_spin.value() * (-1.0 if secondary_reversed_check.isChecked() else 1.0)
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
                if state.get("at_park"):
                    asyncio.run(adapter.unpark())
                    logger.info("Mount: Unpark requested")
                else:
                    asyncio.run(adapter.park())
                    logger.info("Mount: Park requested")
            except Exception:
                logger.exception("Mount park/unpark failed")
                self._window.statusBar().showMessage("Park/Unpark failed — see log.", 6000)
                return
            _refresh_status()

        park_btn.clicked.connect(_park_clicked)

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
            state["adapter"] = None
            _apply_status({})

        def autoconnect_page() -> None:
            device_name = device_combo.currentText().strip()
            if device_name:
                _do_connect(device_name)

        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _refresh_status))
        status_timer.start(2000)

        state["reload"] = reload_page
        state["autoconnect"] = autoconnect_page
        # The jog pad's axis reversal, so the Imaging page's nudge pad points the same way.
        state["axis_reversed"] = lambda: (primary_reversed_check.isChecked(), secondary_reversed_check.isChecked())
        self._device_pages["mount"] = state
        reload_page()
        autoconnect_page()

        return page

    def _build_rotator_page(self) -> QWidget:
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

    def _build_filter_wheel_page(self) -> QWidget:
        """Filter Wheel device-category page: a live status display
        (Name/Description/Driver info/version — EQP-FW-010/020) plus a
        current-filter selector with an explicit Change action, and a
        Filters list showing every filter the wheel reports with the
        current one highlighted, matching the reference Filter
        Wheel layout (assets/samples/wheel.png) laid out with this app's
        own Driver/Server/Port/Scan connection convention rather than its
        icon toolbar."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame,
            QLabel, QTableWidget, QComboBox, QLineEdit, QSpinBox,
            QPushButton, QHeaderView, QMessageBox, QListWidget, QListWidgetItem,
        )
        from PySide6.QtCore import QTimer

        page = QWidget()
        page.setObjectName("FilterWheelPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Filter Wheel")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        # --- connection row --------------------------------------------
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

        # --- status (left) + filters list (right) ------------------------
        main_row = QHBoxLayout()
        main_row.setSpacing(24)

        left_col = QVBoxLayout()

        status_frame = QFrame()
        status_frame.setObjectName("DeviceSlotPanel")
        status_form = QFormLayout(status_frame)

        name_value = QLabel("—")
        name_value.setWordWrap(True)
        status_form.addRow("Name", name_value)
        description_value = QLabel("—")
        description_value.setWordWrap(True)
        status_form.addRow("Description", description_value)

        driver_row = QHBoxLayout()
        driver_info_form = QFormLayout()
        driver_info_value = QLabel("—")
        driver_info_form.addRow("Driver info", driver_info_value)
        driver_row.addLayout(driver_info_form)
        driver_version_form = QFormLayout()
        driver_version_value = QLabel("—")
        driver_version_form.addRow("Driver version", driver_version_value)
        driver_row.addLayout(driver_version_form)
        status_form.addRow(driver_row)

        left_col.addWidget(status_frame)

        current_row = QHBoxLayout()
        filter_combo = QComboBox()
        current_row.addWidget(filter_combo, 1)
        change_btn = QPushButton("Change")
        change_btn.setObjectName("AccentButton")
        current_row.addWidget(change_btn, 3)
        left_col.addLayout(current_row)

        left_col.addStretch(1)
        main_row.addLayout(left_col, 1)

        right_col = QVBoxLayout()
        filters_heading = QLabel("Filters")
        filters_heading.setObjectName("PageTitle")
        right_col.addWidget(filters_heading)
        filters_list_heading = QLabel("Filter name")
        filters_list_heading.setObjectName("CriteriaHeading")
        right_col.addWidget(filters_list_heading)
        filters_list = QListWidget()
        right_col.addWidget(filters_list, 1)
        main_row.addLayout(right_col, 1)

        layout.addLayout(main_row, 1)

        settings_heading = QLabel("Settings")
        settings_heading.setObjectName("CriteriaHeading")
        layout.addWidget(settings_heading)
        layout.addWidget(QLabel("None"))

        state: dict = {"adapter": None}

        def _apply_status(status: dict) -> None:
            name_value.setText(status.get("name") or "—")
            description_value.setText(status.get("description") or "—")
            driver_info_value.setText(status.get("driver_info") or "—")
            driver_version_value.setText(status.get("driver_version") or "—")
            names = status.get("filter_names") or []
            position = status.get("position")

            current = filter_combo.currentText()
            filter_combo.blockSignals(True)
            filter_combo.clear()
            filter_combo.addItems(names)
            if position is not None and 0 <= position < len(names):
                filter_combo.setCurrentIndex(position)
            elif current and filter_combo.findText(current) >= 0:
                filter_combo.setCurrentText(current)
            filter_combo.blockSignals(False)

            filters_list.clear()
            for i, filter_name in enumerate(names):
                item = QListWidgetItem(filter_name)
                filters_list.addItem(item)
                if i == position:
                    filters_list.setCurrentItem(item)

        def _refresh_status() -> dict | None:
            adapter = state.get("adapter")
            if adapter is None:
                return None
            import asyncio
            try:
                status = asyncio.run(adapter.get_status())
            except Exception:
                logger.exception("Could not refresh filter wheel status")
                return None
            _apply_status(status)
            return status

        def _do_connect(device_name: str) -> None:
            from galileo.core.devices import DeviceCategory
            adapter = self._connect_device_adapter(
                DeviceCategory.FILTER_WHEEL, driver_combo.currentText(),
                server_edit.text().strip() or "localhost", port_spin.value(), device_name,
            )
            if adapter is None:
                self._window.statusBar().showMessage(f"Could not connect to Filter Wheel {device_name!r} — see log.", 6000)
                return
            state["adapter"] = adapter
            self._window.statusBar().showMessage(f"Connected to Filter Wheel {device_name!r}.", 4000)
            _refresh_status()

        def _connect_clicked() -> None:
            device_name = device_combo.currentText().strip()
            if not device_name:
                QMessageBox.information(self._window, "No device selected", "Select a filter wheel device first.")
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
                    adapter = get_adapter_class(DeviceCategory.FILTER_WHEEL)(host=server, port=port)
                else:
                    from galileo.adapters.alpaca import get_adapter_class
                    adapter = get_adapter_class(DeviceCategory.FILTER_WHEEL)(host=server, port=port)
                devices = asyncio.run(adapter.list_available_devices(DeviceCategory.FILTER_WHEEL))
            except Exception:
                logger.exception("Filter wheel scan failed on %s:%s", server, port)
                self._window.statusBar().showMessage("Filter wheel scan failed — see log.", 6000)
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
                    "Detected %d %s filter wheel device(s) at %s:%s: %s",
                    len(devices), driver, server, port, ", ".join(devices),
                )
                self._window.statusBar().showMessage(f"Found {len(devices)} filter wheel device(s) — see log.", 4000)
            else:
                logger.info("No %s filter wheel devices found at %s:%s.", driver, server, port)
                self._window.statusBar().showMessage(f"No {driver} filter wheel devices found at {server}:{port}.", 4000)

        scan_btn.clicked.connect(run_scan)

        def _filters_list_clicked(item: QListWidgetItem) -> None:
            idx = filters_list.row(item)
            if idx < 0:
                return
            filter_combo.setCurrentIndex(idx)

        filters_list.itemClicked.connect(_filters_list_clicked)

        def _change_clicked() -> None:
            adapter = state.get("adapter")
            if adapter is None:
                QMessageBox.information(self._window, "Not connected", "Connect the filter wheel first.")
                return
            index = filter_combo.currentIndex()
            if index < 0:
                return
            filter_name = filter_combo.currentText()
            import asyncio
            try:
                asyncio.run(adapter.move_to(index))
            except Exception:
                logger.exception("Filter wheel move_to failed (index=%s)", index)
                self._window.statusBar().showMessage("Filter change failed — see log.", 6000)
                return
            logger.info("Filter wheel: changed to %r (#%d)", filter_name, index)
            _refresh_status()

        change_btn.clicked.connect(_change_clicked)

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

        def save_filter_wheel_config() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_device_config
            save_device_config(
                self._current_pier, "filter_wheel",
                driver=driver_combo.currentText(), server=server_edit.text().strip(),
                port=port_spin.value(), device_name=device_combo.currentText().strip() or None,
            )
            logger.info(
                "Saved filter wheel settings for Pier %r: %s %s:%s, device: %s",
                self._current_pier.name, driver_combo.currentText(), server_edit.text().strip(),
                port_spin.value(), device_combo.currentText().strip() or "(none)",
            )
            self._window.statusBar().showMessage(
                f"Saved filter wheel settings for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_filter_wheel_config)

        def reload_page() -> None:
            cfg = None
            if self._current_pier is not None:
                from galileo.observatory import get_device_config
                try:
                    cfg = get_device_config(self._current_pier, "filter_wheel")
                except Exception:
                    logger.exception("Could not load saved filter wheel config")

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
            state["adapter"] = None
            _apply_status({})

        def autoconnect_page() -> None:
            device_name = device_combo.currentText().strip()
            if device_name:
                _do_connect(device_name)

        status_timer = QTimer(page)
        status_timer.timeout.connect(_when_visible(page, _refresh_status))
        status_timer.start(2000)

        state["reload"] = reload_page
        state["autoconnect"] = autoconnect_page
        self._device_pages["filter_wheel"] = state
        reload_page()
        autoconnect_page()

        return page

    def _build_optics_page(self) -> QWidget:
        """Optics page (PROF-070): one panel per optical tube on the current
        Pier — focal length, aperture, optical design, and image alignment
        (reversed/inverted) — plus an "Associated" list of the Pier's other
        configured devices (camera, guider, focuser, ...) that sit behind
        that tube. A "+" next to the title adds another tube; the "+" next
        to each tube's "Associated:" label picks from the devices already
        saved on the other Equipment pages."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QLabel, QComboBox,
            QDoubleSpinBox, QPushButton, QCheckBox, QScrollArea, QMessageBox, QInputDialog,
            QLineEdit,
        )
        from galileo.library.models.optical_tube import OPTICAL_SYSTEMS

        page = QWidget()
        page.setObjectName("OpticsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        heading = QLabel("Optics")
        heading.setObjectName("PageTitle")
        heading_row.addWidget(heading)
        add_tube_btn = QPushButton("+")
        add_tube_btn.setObjectName("AccentButton")
        add_tube_btn.setFixedWidth(28)
        add_tube_btn.setToolTip("Add another optical tube.")
        heading_row.addWidget(add_tube_btn)
        heading_row.addStretch(1)
        layout.addLayout(heading_row)

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

        def _device_labels() -> dict:
            """``"<category>:<slot>"`` -> display label for every device saved on the current Pier."""
            if self._current_pier is None:
                return {}
            from galileo.observatory import list_device_configs
            try:
                configs = list_device_configs(self._current_pier)
            except Exception:
                logger.exception("Could not load saved device configs for the Optics page")
                return {}
            return {
                f"{c.category}:{c.slot}": _device_association_label(c.category, c.slot, c.device_name)
                for c in configs
            }

        def _render_associations(panel: dict) -> None:
            box = panel["assoc_layout"]
            while box.count():
                row = box.takeAt(0).layout()
                while row is not None and row.count():
                    widget = row.takeAt(0).widget()
                    if widget is not None:
                        widget.setParent(None)
                        widget.deleteLater()
            labels = _device_labels()
            for key in panel["assoc_keys"]:
                row = QHBoxLayout()
                row.addWidget(QLabel(labels.get(key, f"{key} (not configured)")), 1)
                remove = QPushButton("Remove")
                remove.clicked.connect(lambda _c=False, k=key: _dissociate(panel, k))
                row.addWidget(remove)
                box.addLayout(row)

        def _associate(panel: dict) -> None:
            labels = _device_labels()
            choices = {k: v for k, v in labels.items() if k not in panel["assoc_keys"]}
            if not choices:
                QMessageBox.information(
                    self._window, "No devices to associate",
                    "Save a device on one of the other Equipment pages first — every "
                    "device saved on this Pier is already associated with this tube.",
                )
                return
            picked, ok = QInputDialog.getItem(
                self._window, "Associate device", "Device:", list(choices.values()), 0, False
            )
            if not ok:
                return
            key = next(k for k, v in choices.items() if v == picked)
            panel["assoc_keys"].append(key)
            _render_associations(panel)

        def _dissociate(panel: dict, key: str) -> None:
            if key in panel["assoc_keys"]:
                panel["assoc_keys"].remove(key)
                _render_associations(panel)

        def _build_tube_panel(removable: bool) -> dict:
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

            name_edit = QLineEdit()
            name_edit.setPlaceholderText("e.g. Esprit 100ED")
            name_edit.setMaxLength(60)
            form.addRow("Name", name_edit)

            focal = QDoubleSpinBox()
            focal.setRange(0.0, 50000.0)
            focal.setDecimals(1)
            focal.setSuffix(" mm")
            form.addRow("Focal Length", focal)

            aperture = QDoubleSpinBox()
            aperture.setRange(0.0, 5000.0)
            aperture.setDecimals(1)
            aperture.setSuffix(" mm")
            form.addRow("Aperture", aperture)

            system = QComboBox()
            system.addItems(OPTICAL_SYSTEMS)
            form.addRow("Optical System", system)

            alignment_row = QHBoxLayout()
            reversed_check = QCheckBox("Reversed")
            reversed_check.setToolTip("The image is mirrored left-to-right (e.g. a refractor with a star diagonal).")
            inverted_check = QCheckBox("Inverted")
            inverted_check.setToolTip("The image is flipped top-to-bottom (e.g. a Newtonian).")
            alignment_row.addWidget(reversed_check)
            alignment_row.addWidget(inverted_check)
            alignment_row.addStretch(1)
            form.addRow("Image Alignment", alignment_row)

            assoc_header = QHBoxLayout()
            assoc_title = QLabel("Associated:")
            assoc_title.setObjectName("CriteriaHeading")
            assoc_header.addWidget(assoc_title)
            associate_btn = QPushButton("+")
            associate_btn.setObjectName("AccentButton")
            associate_btn.setFixedWidth(28)
            associate_btn.setToolTip("Associate a device already configured on this Pier with this tube.")
            assoc_header.addWidget(associate_btn)
            assoc_header.addStretch(1)
            outer.addLayout(assoc_header)

            assoc_layout = QVBoxLayout()
            outer.addLayout(assoc_layout)

            return {
                "frame": frame, "title_label": title_label, "remove_btn": remove_btn,
                "name": name_edit, "focal": focal, "aperture": aperture, "system": system,
                "reversed": reversed_check, "inverted": inverted_check,
                "associate_btn": associate_btn, "assoc_layout": assoc_layout, "assoc_keys": [],
            }

        def _renumber_panels() -> None:
            for i, panel in enumerate(panels):
                panel["title_label"].setText(f"Optical Tube {i + 1}")

        def _remove_panel(panel: dict) -> None:
            if panel not in panels or panel is panels[0]:
                return
            panels.remove(panel)
            panel["frame"].setParent(None)
            panel["frame"].deleteLater()
            _renumber_panels()

        def _add_panel() -> dict:
            panel = _build_tube_panel(removable=len(panels) > 0)
            panels.append(panel)
            panels_layout.insertWidget(panels_layout.count() - 1, panel["frame"])
            _renumber_panels()
            if panel["remove_btn"] is not None:
                panel["remove_btn"].clicked.connect(lambda: _remove_panel(panel))
            panel["associate_btn"].clicked.connect(lambda: _associate(panel))
            return panel

        def _set_panel_count(count: int) -> None:
            count = max(count, 1)
            while len(panels) < count:
                _add_panel()
            while len(panels) > count:
                _remove_panel(panels[-1])

        add_tube_btn.clicked.connect(_add_panel)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        save_btn.setToolTip("Save every optical tube under the selected Observatory and Pier.")
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        layout.addWidget(log_heading)
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)
        layout.addWidget(log_pane)

        def save_optics() -> None:
            if self._current_pier is None:
                QMessageBox.warning(
                    self._window, "No Pier selected",
                    "Select (or create) an Observatory and Pier before saving equipment settings.",
                )
                return
            from galileo.observatory import save_optical_tubes
            try:
                save_optical_tubes(self._current_pier, [
                    {
                        "name": p["name"].text().strip(),
                        "focal_length_mm": p["focal"].value(),
                        "aperture_mm": p["aperture"].value(),
                        "optical_system": p["system"].currentText(),
                        "image_reversed": p["reversed"].isChecked(),
                        "image_inverted": p["inverted"].isChecked(),
                        "associated": list(p["assoc_keys"]),
                    }
                    for p in panels
                ])
            except Exception:
                logger.exception("Could not save optical tubes for Pier %r", self._current_pier.name)
                return
            logger.info("Saved %d optical tube(s) for Pier %r.", len(panels), self._current_pier.name)
            self._refresh_optics_combo()  # the top-bar selector lists what was just saved
            self._window.statusBar().showMessage(
                f"Saved optics for Pier {self._current_pier.name!r}.", 4000
            )

        save_btn.clicked.connect(save_optics)

        def reload_page() -> None:
            tubes = []
            if self._current_pier is not None:
                from galileo.observatory import list_optical_tubes
                try:
                    tubes = list_optical_tubes(self._current_pier)
                except Exception:
                    logger.exception("Could not load saved optical tubes")
            _set_panel_count(len(tubes))
            for i, panel in enumerate(panels):
                tube = tubes[i] if i < len(tubes) else None
                panel["name"].setText(tube.name if tube else "")
                panel["focal"].setValue(tube.focal_length_mm if tube else 0.0)
                panel["aperture"].setValue(tube.aperture_mm if tube else 0.0)
                idx = panel["system"].findText(tube.optical_system) if tube else 0
                panel["system"].setCurrentIndex(max(idx, 0))
                panel["reversed"].setChecked(bool(tube and tube.image_reversed))
                panel["inverted"].setChecked(bool(tube and tube.image_inverted))
                panel["assoc_keys"] = list(tube.associated) if tube else []
                _render_associations(panel)

        self._device_pages["optics"] = {"reload": reload_page}
        reload_page()

        return page

    def _build_guider_page(self) -> QWidget:
        """Guiding page (a primary sidebar section): a live view onto PHD2
        (GUIDE-070 … GUIDE-090) — see ``galileo.ui.guider``. Unlike the
        Equipment categories there is no device
        to scan for; PHD2 is reached by host and port, and does its own
        camera/mount handling."""
        from galileo.ui.guider import GuiderPage
        page = GuiderPage(self)
        self._device_pages["guider"] = {"reload": page.reload, "autoconnect": page.autoconnect}
        page.reload()
        return page

    def _build_focus_page(self) -> QWidget:
        """Focus page (a primary sidebar section): follows autofocus runs and
        can start one — see ``galileo.ui.focus``. It only redraws while a run
        is in progress."""
        from galileo.ui.focus import FocusPage
        page = FocusPage(self)
        self._device_pages["focus"] = {"reload": page.reload}
        return page

    def _scheduler_for_pier(self, pier_name: str | None) -> ObservatoryScheduler:
        """The one ``ObservatoryScheduler`` for *pier_name* — shared by Planning >
        Sessions and Planning > Scheduler, created lazily, one per Pier. Persists to
        (and, on first use, loads from) the shared database (SCHED-100) so a Pier's
        job queue survives an application restart."""
        from galileo.scheduler import ObservatoryScheduler
        key = pier_name or ""
        if key not in self._schedulers:
            scheduler = ObservatoryScheduler()
            scheduler.set_persistence(key)
            scheduler.load()
            self._schedulers[key] = scheduler
        return self._schedulers[key]

    def _build_sessions_page(self) -> QWidget:
        """Planning > Sessions (SES-100 … SES-230): per-Pier, block-based session
        authoring — see ``galileo.ui.sessions``."""
        from galileo.ui.sessions import SessionsPageWidget
        page = SessionsPageWidget(self)
        self._device_pages["sessions"] = {
            "reload": page.reload,
            "create_session_for_target": page.create_session_for_target,
        }
        return page

    def _build_scheduler_page(self) -> QWidget:
        """Planning > Scheduler (SCHED-010 … SCHED-100): the per-Pier job queue —
        see ``galileo.ui.scheduler``."""
        from galileo.ui.scheduler import SchedulerPageWidget
        page = SchedulerPageWidget(self)
        self._device_pages["scheduler"] = {"reload": page.reload}
        return page

    def _build_solve_page(self) -> QWidget:
        """Solve page (a primary sidebar section): plate solving, with the frame
        being solved and its results on show (PLT-070) — see ``galileo.ui.solve``.
        It follows every solve, whoever started it, but only while it is on
        screen."""
        from galileo.ui.solve import SolvePage
        page = SolvePage(self)
        self._device_pages["solve"] = {"reload": page.reload, "refresh_target": page.refresh_target}
        return page

    def _build_device_config_page(self, cat_id: str, label: str) -> QWidget:
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
        logger.info(
            "Saved %s settings for Pier %r: %s %s:%s, device: %s",
            cat_id, self._current_pier.name, state["driver"].currentText(),
            state["server"].text().strip(), state["port"].value(),
            state["selected_device"] or "(none)",
        )
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
        self._refresh_optics_combo()
        self._refresh_camera_combo()
        self._refresh_imaging_filters()
        self._refresh_current_object()
        refresh_star_atlas_site = getattr(self, "_star_atlas_refresh_site", None)
        if refresh_star_atlas_site is not None:
            refresh_star_atlas_site()
        self._apply_horizon()
        for refresh_name in ("_focus_settings_refresh", "_solve_settings_refresh"):
            refresh = getattr(self, refresh_name, None)
            if refresh is not None:
                refresh()

    def _apply_horizon(self) -> None:
        """Load the current Observatory's horizon obstruction table and hand it to
        everything that uses it: the Star Atlas shading, the Options > Star Atlas
        table, and the slew guard the mount adapters consult (together with the
        site, and the Options > Planning switch)."""
        from galileo.core.slew_guard import get_slew_guard
        from galileo.observatory import list_horizon_points
        from galileo.planning.settings import load_planning_settings
        from galileo.planning.visibility import HorizonProfile

        observatory = getattr(self, "_current_observatory", None)
        points: list = []
        if observatory is not None:
            try:
                points = list_horizon_points(observatory)
            except Exception:
                logger.exception("Could not load the horizon obstructions for Observatory %r", observatory.name)
        horizon = HorizonProfile(points) if points else None

        guard = get_slew_guard()
        guard.enabled = bool(load_planning_settings()["block_obstructed_slews"])
        guard.horizon = horizon
        guard.latitude = getattr(observatory, "latitude", None)
        guard.longitude = getattr(observatory, "longitude", None)

        set_atlas_horizon = getattr(self, "_star_atlas_set_horizon", None)
        if set_atlas_horizon is not None:
            set_atlas_horizon(horizon)
        refresh_table = getattr(self, "_horizon_table_refresh", None)
        if refresh_table is not None:
            refresh_table(points)

    def pier_markers(self) -> list:
        """A telescope reticle for each Pier in the current Observatory (SKYMAP-090).

        A Pier whose mount Galileo has read reports where it is actually pointing, so its reticle
        moves across the sky as it slews; its current object is shown as the target it is heading
        for. A Pier with no reading falls back to its current object's position, labelled as the
        target rather than the telescope. Only the selected Pier's mount is connected at a time
        (the Equipment pages reconnect on every Pier change), so the other Piers normally show
        their target alone."""
        from galileo.current_object import get_current_objects, pier_key
        from galileo.observatory import list_piers

        if self._current_observatory is None:
            return []
        try:
            piers = list_piers(self._current_observatory)
        except Exception:
            logger.exception("Could not load the Piers for the Star Atlas markers")
            return []

        objects = get_current_objects()
        markers = []
        for pier in piers:
            target = objects.get(pier)
            target_point = {"ra_deg": target.ra_deg, "dec_deg": target.dec_deg} if target is not None else None
            pointing = self._pier_pointing.get(pier_key(pier))
            if pointing is not None:
                label = f"{pier.name} → {target.name}" if target is not None else pier.name
                if pointing.get("slewing"):
                    label += " (slewing)"
                markers.append({"ra_deg": pointing["ra_deg"], "dec_deg": pointing["dec_deg"],
                                "label": label, "slewing": bool(pointing.get("slewing")),
                                "target": target_point})
            elif target_point is not None:
                markers.append({**target_point, "label": f"{pier.name} → {target.name}", "slewing": False})
        return markers

    def _poll_pier_pointing(self, on_done=None) -> None:
        """Read the connected mount's position off the Qt UI thread and remember it for the Star
        Atlas reticles (SKYMAP-090). One poll at a time; a mount that can't be read is forgotten,
        so its reticle falls back to the Pier's target rather than freezing where it last was."""
        from galileo.current_object import pier_key

        mount = (self._device_pages.get("mount") or {}).get("adapter")
        key = pier_key(self._current_pier)
        if mount is None or key is None:
            if self._pier_pointing.pop(key, None) is not None and on_done is not None:
                on_done()
            return
        if self._pier_poll_thread is not None:
            return

        def done(status) -> None:
            self._pier_poll_thread = None
            pointing = None
            if status:
                ra_hours, dec = status.get("right_ascension"), status.get("declination")
                if ra_hours is not None and dec is not None:
                    from galileo.platesolve import mount_frame_to_j2000
                    ra_deg, dec_deg = mount_frame_to_j2000(ra_hours * 15.0, dec, status.get("equatorial_system"))
                    pointing = {"ra_deg": ra_deg, "dec_deg": dec_deg, "slewing": bool(status.get("slewing"))}
            if pointing is None:
                self._pier_pointing.pop(key, None)
            else:
                self._pier_pointing[key] = pointing
            if on_done is not None:
                on_done()

        thread = _MountPositionThread(mount, self._window)
        thread.position.connect(done)
        self._pier_poll_thread = thread
        thread.start()

    def _track_when_slew_finishes(self, mount, target=None) -> None:
        """Once the slew that was just started finishes, track at the rate the target needs
        (EQP-MNT-050) — solar for the Sun, lunar for the Moon, sidereal for everything else.

        Waiting for a slew can take minutes, so it happens on a worker thread. With no *target*
        given (the Mount page's own coordinate slews, which name nothing) the Pier's current
        object stands in, since that is what the user last said they were working on."""
        if mount is None:
            return
        if self._tracking_thread is not None:
            return          # a slew already has one waiting; the later one wins by finishing later
        target = target if target is not None else self.current_object()

        def done(rate: str) -> None:
            self._tracking_thread = None
            if rate:
                self._window.statusBar().showMessage(f"Slew finished — tracking at the {rate} rate.", 5000)

        def failed(message: str) -> None:
            self._tracking_thread = None
            logger.error("Could not start tracking after the slew: %s", message)
            self._window.statusBar().showMessage("Slew finished, but tracking could not be started — see log.", 8000)

        thread = _ResumeTrackingThread(mount, target, self._window)
        thread.done.connect(done)
        thread.failed.connect(failed)
        self._tracking_thread = thread
        thread.start()

    def camera_not_connected_message(self) -> str:
        """Why a screen can't capture: which camera the top-bar selector is on, and what to do."""
        from galileo.observatory import get_device_config
        name = _camera_slot_label(self._active_camera_slot)
        if self._current_pier is not None:
            try:
                cfg = get_device_config(self._current_pier, "camera", slot=self._active_camera_slot)
            except Exception:
                cfg = None
            if cfg is None:
                return (f"No {name} is configured for this Pier. Set one up on Equipment > Camera, "
                        "then choose it in the Camera selector at the top of the window.")
            if cfg.device_name:
                name = f"{name} ({cfg.device_name})"
        return (f"{name} is selected but not connected. Connect it on Equipment > Camera, or pick "
                "another camera in the Camera selector at the top of the window.")

    def _imaging_frame_context(self) -> dict:
        """What the Imaging page knows about the rig, as FITS header values for
        ``ImagingService.frame_context`` (IMG-150): telescope and camera, optics, the site, where the
        mount is pointing and what it is aiming at, and the focuser position. Whatever can't be found
        is left out; nothing here may stop a capture."""
        import asyncio
        from galileo.ui.imaging import format_dec_dms, format_ra_hms

        context: dict = {}
        tube = self.active_optical_tube()
        if tube is not None:
            context.update(telescope=tube.name, focal_length_mm=tube.focal_length_mm or None,
                           aperture_mm=tube.aperture_mm or None)
        camera_backend = self._camera_backends.get(_camera_backend_key_for_slot(self._active_camera_slot))
        pier = self._current_pier
        camera_cfg = None
        if pier is not None:
            from galileo.observatory import get_device_config
            try:
                camera_cfg = get_device_config(pier, "camera", slot=self._active_camera_slot)
            except Exception:
                logger.exception("Could not load the camera's configuration for the FITS header")
        if camera_cfg is not None:
            context.update(instrument=camera_cfg.device_name or camera_cfg.sensor_name,
                           pixel_size_x_um=camera_cfg.pixel_size_um, pixel_size_y_um=camera_cfg.pixel_size_um,
                           bayer_pattern=camera_cfg.bayer_pattern)
        context.setdefault("instrument", getattr(camera_backend, "device_name", None))

        site_lat = site_long = None
        if pier is not None:
            try:
                observatory = pier.observatory
                site_lat, site_long = observatory.latitude, observatory.longitude
                context.update(site=observatory.name, observer=observatory.owner)
            except Exception:
                logger.exception("Could not read the Observatory for the FITS header")

        pointing = None
        mount = (self._device_pages.get("mount") or {}).get("adapter")
        if mount is not None:
            try:
                status = asyncio.run(mount.get_status()) or {}
                ra_hours, dec = status.get("right_ascension"), status.get("declination")
                if ra_hours is not None and dec is not None:
                    from galileo.platesolve import mount_frame_to_j2000
                    pointing = mount_frame_to_j2000(ra_hours * 15.0, dec, status.get("equatorial_system"))
                context["pier_side"] = status.get("side_of_pier")
                if site_lat is None:
                    site_lat, site_long = status.get("site_latitude"), status.get("site_longitude")
            except Exception:
                logger.warning("Could not read the mount's position for the FITS header", exc_info=True)
        context.update(site_lat_deg=site_lat, site_long_deg=site_long)

        target = self.current_object()
        if target is not None:
            context.update(objctra=format_ra_hms(target.ra_deg), objctdec=format_dec_dms(target.dec_deg))
        aim = pointing or ((target.ra_deg, target.dec_deg) if target is not None else None)
        if aim is not None:
            context.update(ra_deg=aim[0], dec_deg=aim[1])

        focuser = ((self._device_pages.get("focuser") or {}).get("get_adapter") or (lambda: None))()
        position = getattr(focuser, "position", None)
        if isinstance(position, int) and position > 0:
            context["focus_position"] = position
        return {key: value for key, value in context.items() if value not in (None, "")}

    def _mount_to_object(self, action: str, obj: dict) -> bool:
        """Point the current Pier's mount at a Star Atlas *obj*: ``"goto"`` slews
        to it, ``"sync"`` tells the mount it is already pointing there. Uses the
        connection made on the Equipment > Mount page (which is reset whenever
        the Pier changes) and reports the outcome on the status bar. Returns
        whether the command was sent."""
        import asyncio
        import datetime as dt
        from galileo.planning import star_atlas as sa

        verb = "Goto" if action == "goto" else "Sync"
        adapter = (self._device_pages.get("mount") or {}).get("adapter")
        if adapter is None:
            logger.warning("Mount %s to %s not sent: no mount is connected", action, obj["name"])
            self._window.statusBar().showMessage(
                f"{verb}: no mount is connected — connect it on Equipment > Mount.", 6000)
            return False
        if obj["alt"] < 0:
            logger.warning("Mount %s to %s not sent: it is below the horizon (alt %.1f°)", action, obj["name"], obj["alt"])
            self._window.statusBar().showMessage(
                f"{verb}: {obj['name']} is below the horizon at this time and place.", 6000)
            return False
        ra_deg, dec_deg = obj["ra_deg"], obj["dec_deg"]      # the atlas holds J2000
        try:
            if (asyncio.run(adapter.get_status()) or {}).get("equatorial_system") != "J2000":
                # Every other mount takes coordinates of date (JNow).
                jd = sa.julian_date(dt.datetime.now(dt.UTC).replace(tzinfo=None))
                ra_deg, dec_deg = (float(v) for v in sa.precess_from_j2000(ra_deg, dec_deg, jd))
            if action == "goto":
                asyncio.run(adapter.slew_to_coordinates(ra_deg, dec_deg))
            else:
                asyncio.run(adapter.sync_to_coordinates(ra_deg, dec_deg))
        except MountParkedError:
            self._window.statusBar().showMessage(f"{verb}: {_PARKED_MESSAGE}", 6000)
            return False
        except SlewObstructedError:
            self._window.statusBar().showMessage(f"{verb}: {_OBSTRUCTED_MESSAGE}", 6000)
            return False
        except Exception:
            logger.exception("Mount %s to %s failed", action, obj["name"])
            self._window.statusBar().showMessage(f"{verb} to {obj['name']} failed — see log.", 6000)
            return False
        logger.info("Mount: %s to %s (RA %.4fh Dec %.4f°)", action, obj["name"], ra_deg / 15.0, dec_deg)
        self._window.statusBar().showMessage(
            f"Slewing the mount to {obj['name']}." if action == "goto" else f"Mount synced to {obj['name']}.", 4000)
        if action == "goto":
            self._track_when_slew_finishes(adapter, obj)
        return True

    def _connect_device_adapter(self, category, driver: str, server: str, port: int, device_name: str):
        """Instantiate and connect one device backend for *category*, or
        return ``None`` (having logged why) on failure. Shared by any
        Equipment page that needs a live per-device connection — the
        Camera page's auto-connect and the Focuser page's per-panel Connect
        and status polling."""
        import asyncio
        try:
            adapter = self._make_adapter(category, driver, server, port, device_name)
            asyncio.run(adapter.connect())
        except Exception:
            logger.exception("Could not connect %s %r at %s:%s", category, device_name, server, port)
            return None
        return adapter

    @staticmethod
    def _make_adapter(category, driver: str, server: str, port: int, device_name: str):
        """Instantiate (without connecting) the INDI or Alpaca backend for one
        scanned device. *device_name* is the scan-result label: an INDI device
        name, or an Alpaca ``"Name (#N)"`` label carrying the device number."""
        if driver == "INDI":
            from galileo.adapters.indi import get_adapter_class
            return get_adapter_class(category)(host=server, port=port, device_name=device_name)
        from galileo.adapters.alpaca import get_adapter_class
        kwargs = {}
        device_number = _parse_alpaca_device_number(device_name)
        if device_number is not None:
            kwargs["device_number"] = device_number
        return get_adapter_class(category)(host=server, port=port, **kwargs)

    def _lookup_driver_info(self, category, driver: str, server: str, port: int, device_name: str) -> dict:
        """Read one device's driver name/version *without connecting it* (see
        ``DeviceBackend.get_driver_info``), for the Equipment pages' "Driver
        info" row as soon as a device is picked. Returns ``{}`` if no device is
        chosen or the lookup fails (logged; the row then shows a dash)."""
        if not device_name:
            return {}
        import asyncio
        try:
            adapter = self._make_adapter(category, driver, server or "localhost", port, device_name)
            return asyncio.run(adapter.get_driver_info()) or {}
        except Exception:
            logger.exception("Could not read driver info for %r at %s:%s", device_name, server, port)
            return {}

    @staticmethod
    def _build_driver_info_row() -> tuple:
        """The "Driver info" / "Driver version" pair every Equipment page
        shows (laid out as on the Filter Wheel page). Returns ``(layout,
        apply)`` where ``apply(info)`` fills it from a ``get_driver_info()``
        dict — a dash for anything missing, or for ``None``/``{}`` when
        nothing is known yet."""
        from PySide6.QtWidgets import QHBoxLayout, QFormLayout, QLabel

        row = QHBoxLayout()
        info_form = QFormLayout()
        info_value = QLabel("—")
        info_form.addRow("Driver info", info_value)
        row.addLayout(info_form)
        version_form = QFormLayout()
        version_value = QLabel("—")
        version_form.addRow("Driver version", version_value)
        row.addLayout(version_form)
        row.addStretch(1)

        def apply(info: dict | None) -> None:
            info = info or {}
            info_value.setText(info.get("driver_info") or "—")
            version_value.setText(info.get("driver_version") or "—")

        return row, apply

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
        self._refresh_camera_combo()      # the selector shows which cameras are connected
        self._window.statusBar().showMessage(f"Connected to {slot_label} {device_name!r}.", 4000)

    # --- Imaging page (live preview / histogram / stats / manual capture) ---

    def _build_imaging_page(self) -> QWidget:
        """Imaging tab (IMG-010 … IMG-100): a live, pan/zoomable auto-stretch
        preview with histogram and per-frame statistics, plus manual
        single-exposure capture — modeled on the classic CCD-capture-tool
        split of capture settings on the left against preview/progress/log
        on the right (see assets/samples/ccd.png). Sequencing itself lives
        in the separate Sequence section; this page is for live preview and
        one-off manual shots, not a queue."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QGroupBox,
            QComboBox, QDoubleSpinBox, QSpinBox, QPushButton, QCheckBox, QProgressBar,
            QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QFrame,
            QFileDialog, QMessageBox, QGridLayout, QScrollArea, QMenu,
        )
        from PySide6.QtCore import Qt, QTimer, QObject, QEvent
        from PySide6.QtGui import QPixmap, QImage

        from galileo.livestack import LIVE_STACK_MIN_FRAMES
        from galileo.ui.imaging import DEFAULT_GAIN, ImagingService, NUDGE_RATES, PORTRAIT, LANDSCAPE

        page = QWidget()
        page.setObjectName("ImagingPage")
        root = QHBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- left: capture + view settings ----------------------------------
        # In a scroll area because the panel also holds the nudge pad and, for a
        # portrait frame, the histogram, progress bar and log (IMG-120).
        settings_scroll = QScrollArea()
        settings_scroll.setFixedWidth(300)
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        settings_panel = QFrame()
        settings_panel.setObjectName("ImagingSettingsPanel")
        settings_scroll.setWidget(settings_panel)
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(10)

        heading = QLabel("Imaging")
        heading.setObjectName("PageTitle")
        settings_layout.addWidget(heading)

        capture_group = QGroupBox("Capture Settings")
        capture_form = QFormLayout(capture_group)

        exposure_spin = QDoubleSpinBox()
        exposure_spin.setRange(0.001, 3600.0)
        exposure_spin.setDecimals(3)
        exposure_spin.setValue(5.0)
        exposure_spin.setSuffix(" s")
        capture_form.addRow("Exposure", exposure_spin)

        quantity_spin = QSpinBox()
        quantity_spin.setRange(1, 9999)
        quantity_spin.setValue(1)
        quantity_spin.setToolTip("How many frames Capture takes, one after another, with these settings (IMG-150).")
        capture_form.addRow("Quantity", quantity_spin)

        gain_spin = QSpinBox()
        gain_spin.setRange(0, 100000)
        gain_spin.setValue(DEFAULT_GAIN)
        gain_spin.setToolTip("Camera gain for each exposure. 0 leaves the camera as it is configured (IMG-150).")
        capture_form.addRow("Gain", gain_spin)

        live_stack_check = QCheckBox("Live Stack")
        live_stack_check.setToolTip(
            f"Build the frames of one Capture into a single image instead of each replacing the last "
            f"(IMG-160): every frame is aligned to the first and added to a running mean, so the preview, "
            f"statistics and histogram improve as the run goes on. Applies to runs of "
            f"{LIVE_STACK_MIN_FRAMES} frames or more. Each frame still goes to the Library on its own; "
            f"use Save Stack for the stacked image.")
        capture_form.addRow(live_stack_check)

        frame_type_combo = QComboBox()
        frame_type_combo.addItems(["Light", "Dark", "Flat", "Bias"])
        capture_form.addRow("Type", frame_type_combo)

        filter_combo = QComboBox()
        filter_combo.setEditable(True)
        filter_combo.setToolTip(
            "The filters of the filter wheel associated with the selected optics "
            "(Equipment > Optics). Connect the wheel on Equipment > Filter Wheel to fill this in."
        )
        capture_form.addRow("Filter", filter_combo)
        self._imaging_filter_combo = filter_combo
        self._refresh_imaging_filters()
        filter_combo.activated.connect(self._on_imaging_filter_activated)

        settings_layout.addWidget(capture_group)

        mosaic_indicator = QLabel("")
        mosaic_indicator.setObjectName("StatusHint")
        mosaic_indicator.setWordWrap(True)
        mosaic_indicator.setVisible(False)
        settings_layout.addWidget(mosaic_indicator)

        capture_row = QHBoxLayout()
        capture_btn = QPushButton("Capture")
        capture_btn.setObjectName("AccentButton")
        capture_row.addWidget(capture_btn, 1)
        stop_capture_btn = QPushButton("Stop")
        stop_capture_btn.setToolTip("Abandon the exposure in progress and take no more frames.")
        stop_capture_btn.setEnabled(False)
        capture_row.addWidget(stop_capture_btn)
        settings_layout.addLayout(capture_row)

        framing_row = QHBoxLayout()
        framing_btn = QPushButton("Framing…")
        framing_btn.setToolTip("Open the Framing Assistant against the selected optical train: compute the "
                               "field of view, or define and run a mosaic grid directly from this tab "
                               "(IMG-180, FRAME-070).")
        framing_row.addWidget(framing_btn, 1)
        clear_mosaic_btn = QPushButton("Clear Mosaic")
        clear_mosaic_btn.setToolTip("Discard the active mosaic (IMG-180) and go back to capturing a single frame.")
        clear_mosaic_btn.setVisible(False)
        framing_row.addWidget(clear_mosaic_btn)
        settings_layout.addLayout(framing_row)

        save_frame_btn = QPushButton("Save Frame…")
        save_frame_btn.setToolTip("Save the currently displayed frame to disk as a FITS file, with all the "
                                  "header cards Galileo can fill in (IMG-100, IMG-150).")
        save_frame_btn.setEnabled(False)
        settings_layout.addWidget(save_frame_btn)

        save_stack_btn = QPushButton("Save Stack…")
        save_stack_btn.setToolTip("Save the live stack to the Library or to a FITS file (IMG-160).")
        save_stack_btn.setEnabled(False)
        settings_layout.addWidget(save_stack_btn)

        auto_save_check = QCheckBox("Auto-Save to Library")
        auto_save_check.setChecked(True)
        auto_save_check.setToolTip(
            "Write each captured frame to a scratch folder and register it in the Library, which files it "
            "in the repository — it then appears on Library > Images (IMG-150). Needs the repository folder "
            "set in Options > Library.")
        settings_layout.addWidget(auto_save_check)

        view_group = QGroupBox("View")
        view_form = QFormLayout(view_group)

        debayer_check = QCheckBox("Debayer")
        debayer_check.setToolTip(
            "Show the frame from a one-shot-colour camera in colour, using the Bayer pattern set for "
            "the camera on Equipment > Camera (RGGB by default) (IMG-110). Only the preview changes: "
            "statistics, the histogram and Save Frame keep the camera's raw data."
        )
        view_form.addRow(debayer_check)

        star_overlay_check = QCheckBox("Star overlay")
        star_overlay_check.setToolTip("Overlay stars detected for HFR computation (IMG-050).")
        view_form.addRow(star_overlay_check)

        zoom_spin = QDoubleSpinBox()
        zoom_spin.setRange(0.1, 8.0)
        zoom_spin.setSingleStep(0.1)
        zoom_spin.setValue(1.0)
        zoom_spin.setSuffix("x")
        view_form.addRow("Zoom", zoom_spin)

        reset_view_btn = QPushButton("Reset View")
        view_form.addRow(reset_view_btn)

        orientation_check = QCheckBox("Choose layout manually")
        orientation_check.setToolTip(
            "By default the page lays itself out for the shape of the frame: a portrait frame gets the "
            "whole right side, with the histogram and log moved to the left (IMG-120). Tick this to "
            "pick the layout yourself."
        )
        view_form.addRow(orientation_check)
        orientation_combo = QComboBox()
        orientation_combo.addItem("Landscape", LANDSCAPE)
        orientation_combo.addItem("Portrait", PORTRAIT)
        orientation_combo.setEnabled(False)
        view_form.addRow("Layout", orientation_combo)

        settings_layout.addWidget(view_group)

        stats_group = QGroupBox("Statistics")
        stats_form = QFormLayout(stats_group)
        stats_labels: dict = {}
        for key, label_text in (
            ("mean", "Mean"), ("median", "Median"), ("min", "Min"),
            ("max", "Max"), ("star_count", "Star count"), ("hfr", "HFR"),
        ):
            value_label = QLabel("—")
            stats_labels[key] = value_label
            stats_form.addRow(label_text, value_label)
        settings_layout.addWidget(stats_group)

        nudge_group = QGroupBox("Mount Nudge")
        nudge_layout = QVBoxLayout(nudge_group)
        nudge_grid = QGridLayout()
        nudge_north_btn, nudge_west_btn = QPushButton("N"), QPushButton("W")
        nudge_stop_btn = QPushButton("Stop")
        nudge_east_btn, nudge_south_btn = QPushButton("E"), QPushButton("S")
        nudge_dir_buttons = {"N": nudge_north_btn, "S": nudge_south_btn, "E": nudge_east_btn, "W": nudge_west_btn}
        for btn in (*nudge_dir_buttons.values(), nudge_stop_btn):
            btn.setObjectName("AccentButton")
            btn.setFixedSize(44, 44)
        nudge_grid.addWidget(nudge_north_btn, 0, 1)
        nudge_grid.addWidget(nudge_west_btn, 1, 0)
        nudge_grid.addWidget(nudge_stop_btn, 1, 1)
        nudge_grid.addWidget(nudge_east_btn, 1, 2)
        nudge_grid.addWidget(nudge_south_btn, 2, 1)
        nudge_grid.setAlignment(Qt.AlignHCenter)
        nudge_layout.addLayout(nudge_grid)
        nudge_form = QFormLayout()
        nudge_rate_combo = QComboBox()
        for name, rate in NUDGE_RATES.items():
            nudge_rate_combo.addItem(f"{name} ({rate:g}°/s)", rate)
        nudge_rate_combo.setCurrentIndex(1)
        nudge_rate_combo.setToolTip("How fast the mount moves during a nudge.")
        nudge_form.addRow("Speed", nudge_rate_combo)
        nudge_duration_spin = QDoubleSpinBox()
        nudge_duration_spin.setRange(0.1, 10.0)
        nudge_duration_spin.setSingleStep(0.1)
        nudge_duration_spin.setDecimals(1)
        nudge_duration_spin.setValue(0.5)
        nudge_duration_spin.setSuffix(" s")
        nudge_duration_spin.setToolTip("How long the mount moves for each press.")
        nudge_form.addRow("Duration", nudge_duration_spin)
        nudge_layout.addLayout(nudge_form)
        nudge_group.setToolTip(
            "Nudge the telescope while exposing (IMG-130). Uses the mount connected on Equipment > Mount, "
            "with the same axis directions as its jog pad."
        )
        settings_layout.addWidget(nudge_group)

        settings_layout.addStretch(1)
        root.addWidget(settings_scroll)

        # A column between the settings and the preview, used only for a portrait
        # frame (IMG-120): it takes the width the narrow preview leaves free and
        # holds the histogram, progress bar and log.
        dock_panel = QWidget()
        dock_layout = QVBoxLayout(dock_panel)
        dock_layout.setContentsMargins(8, 16, 8, 16)
        dock_layout.setSpacing(6)
        dock_layout.addStretch(1)
        dock_panel.setVisible(False)
        root.addWidget(dock_panel, 1)

        # --- right: live preview, histogram, progress, log ------------------
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(10)

        scene = QGraphicsScene()
        pixmap_item = QGraphicsPixmapItem()
        scene.addItem(pixmap_item)
        preview_view = QGraphicsView(scene)
        preview_view.setObjectName("ImagingPreview")
        preview_view.setDragMode(QGraphicsView.ScrollHandDrag)
        preview_view.setBackgroundBrush(Qt.black)
        content_layout.addWidget(preview_view, 1)

        histogram = _HistogramWidget()
        histogram.setFixedHeight(80)
        histogram.set_color(self._theme.accent_color)
        content_layout.addWidget(histogram)

        progress_widget = QWidget()   # a widget, not a bare layout, so it can move with the rest (IMG-120)
        progress_row = QHBoxLayout(progress_widget)
        progress_row.setContentsMargins(0, 0, 0, 0)
        status_label = QLabel("Idle")
        progress_row.addWidget(status_label)
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 1000)
        progress_bar.setValue(0)
        progress_bar.setTextVisible(False)
        progress_row.addWidget(progress_bar, 1)

        log_heading = QLabel("Log")
        log_heading.setObjectName("CriteriaHeading")
        log_pane = self._build_log_pane()
        self._log_panes.append(log_pane)

        root.addWidget(content, 1)

        # --- landscape / portrait layout (IMG-120) -----------------------------
        # Landscape: preview on top of the right side, histogram/progress/log
        # beneath it. Portrait: the preview is a full-height column one third of
        # the page wide, and the nudge pad, histogram, progress and log sit in the
        # column to its left, beside the settings.
        secondary_widgets = (histogram, progress_widget, log_heading, log_pane)
        nudge_slot = settings_layout.indexOf(nudge_group)   # where the nudge pad sits in landscape
        layout_state = {"orientation": None}
        unlimited_width = 16777215   # QWIDGETSIZE_MAX

        def _log_height(lines: int) -> int:
            return log_pane.fontMetrics().lineSpacing() * lines + log_pane.frameWidth() * 2 + 8

        def _fit_preview_width() -> None:
            """Portrait: the preview column is a third of the page's width."""
            if layout_state["orientation"] == PORTRAIT:
                content.setFixedWidth(max(1, page.width() // 3))
            else:
                content.setMinimumWidth(0)
                content.setMaximumWidth(unlimited_width)

        def _apply_orientation() -> None:
            orientation = service.orientation
            if orientation == layout_state["orientation"]:
                return
            layout_state["orientation"] = orientation
            portrait = orientation == PORTRAIT
            for widget in (*secondary_widgets, nudge_group):
                content_layout.removeWidget(widget)
                dock_layout.removeWidget(widget)
                settings_layout.removeWidget(widget)
            if portrait:
                # The nudge pad leads the middle column; the rest follow, above its trailing stretch.
                for i, widget in enumerate((nudge_group, *secondary_widgets)):
                    dock_layout.insertWidget(i, widget)
                    widget.setVisible(True)
            else:
                settings_layout.insertWidget(nudge_slot, nudge_group)
                nudge_group.setVisible(True)
                for widget in secondary_widgets:
                    content_layout.addWidget(widget)
                    widget.setVisible(True)
            dock_panel.setVisible(portrait)
            histogram.setFixedHeight(120 if portrait else 80)
            log_pane.setFixedHeight(_log_height(12 if portrait else 10))
            content_layout.setContentsMargins(*((8, 8, 8, 8) if portrait else (24, 20, 24, 20)))
            _fit_preview_width()

        class _PageResizeWatcher(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Resize:
                    _fit_preview_width()
                return False

        resize_watcher = _PageResizeWatcher(page)
        page.installEventFilter(resize_watcher)

        # --- wiring -----------------------------------------------------------
        def _selected_camera_backend():
            # Reads the top-bar Camera selector (shown only when the current
            # Pier has more than one configured camera) fresh each time,
            # rather than caching it at page-build time.
            key = _camera_backend_key_for_slot(self._active_camera_slot)
            return self._camera_backends.get(key)

        service = ImagingService(camera=_selected_camera_backend())
        self._imaging_service = service

        def _refresh_preview() -> None:
            import numpy as np
            data = service.current_preview
            if data is None:
                return
            arr = np.ascontiguousarray(data)
            h, w = arr.shape[:2]
            if arr.ndim == 3:
                image = QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()
            else:
                image = QImage(arr.data, w, h, w, QImage.Format_Grayscale8).copy()
            pixmap_item.setPixmap(QPixmap.fromImage(image))
            scene.setSceneRect(0, 0, w, h)
            preview_view.resetTransform()
            preview_view.scale(zoom_spin.value(), zoom_spin.value())

        def _refresh_stats() -> None:
            stats = service.get_frame_stats()
            for key, value_label in stats_labels.items():
                value = stats.get(key)
                if value is None:
                    value_label.setText("—")
                elif isinstance(value, float):
                    value_label.setText(f"{value:.2f}")
                else:
                    value_label.setText(str(value))

        def _refresh_histogram() -> None:
            hist = service.get_histogram()
            histogram.set_data(hist.get("counts", []))

        def apply_zoom(factor: float) -> None:
            service.set_zoom(factor)
            preview_view.resetTransform()
            preview_view.scale(factor, factor)

        zoom_spin.valueChanged.connect(apply_zoom)

        def reset_view() -> None:
            service.reset_view()
            zoom_spin.blockSignals(True)
            zoom_spin.setValue(1.0)
            zoom_spin.blockSignals(False)
            preview_view.resetTransform()

        reset_view_btn.clicked.connect(reset_view)

        star_overlay_check.toggled.connect(service.set_star_overlay)

        def _use_camera_bayer_pattern(rebuild: bool) -> None:
            # The pattern saved for the selected camera on Equipment > Camera (RGGB until changed).
            from galileo.observatory import get_device_config
            pattern = None
            if self._current_pier is not None:
                try:
                    cfg = get_device_config(self._current_pier, "camera", slot=self._active_camera_slot)
                    pattern = cfg.bayer_pattern if cfg is not None else None
                except Exception:
                    logger.exception("Could not load the camera's Bayer pattern")
            service.set_bayer_pattern(pattern, rebuild=rebuild)

        def _debayer_toggled(checked: bool) -> None:
            _use_camera_bayer_pattern(rebuild=False)
            service.set_debayer(checked)
            _refresh_preview()
            if service.current_frame is not None:
                status_label.setText(service.debayer_note or "Debayer off.")

        debayer_check.toggled.connect(_debayer_toggled)
        self._imaging_debayer_check = debayer_check

        def _orientation_choice_changed(*_args) -> None:
            if orientation_check.isChecked():
                service.set_manual_orientation(orientation_combo.currentData())
            else:
                service.set_manual_orientation(None)
            _apply_orientation()

        def _manual_orientation_toggled(checked: bool) -> None:
            orientation_combo.setEnabled(checked)
            if checked:
                # Start from what the page is showing now, so ticking the box doesn't move anything.
                orientation_combo.blockSignals(True)
                orientation_combo.setCurrentIndex(orientation_combo.findData(service.orientation))
                orientation_combo.blockSignals(False)
            _orientation_choice_changed()

        orientation_check.toggled.connect(_manual_orientation_toggled)
        orientation_combo.currentIndexChanged.connect(_orientation_choice_changed)

        # --- mount nudge (IMG-130) ---------------------------------------------
        nudge_state = {"thread": None}

        def _nudge_mount_adapter():
            return (self._device_pages.get("mount") or {}).get("adapter")

        def _set_nudge_busy(busy: bool) -> None:
            for btn in nudge_dir_buttons.values():
                btn.setEnabled(not busy)

        def _nudge(direction: str) -> None:
            mount = _nudge_mount_adapter()
            if mount is None:
                self._window.statusBar().showMessage("Connect the mount on Equipment > Mount to nudge it.", 4000)
                return
            if nudge_state["thread"] is not None:
                return
            reversed_getter = (self._device_pages.get("mount") or {}).get("axis_reversed")
            reversed_axes = reversed_getter() if reversed_getter is not None else (False, False)
            rate, duration = nudge_rate_combo.currentData(), nudge_duration_spin.value()

            def done() -> None:
                nudge_state["thread"] = None
                _set_nudge_busy(False)

            def failed(message: str) -> None:
                done()
                if "parked" in message.lower():
                    self._window.statusBar().showMessage(_PARKED_MESSAGE, 6000)
                else:
                    self._window.statusBar().showMessage("Nudge failed — see log.", 6000)
                logger.error("Mount nudge %s failed: %s", direction, message)

            thread = _NudgeThread(mount, direction, rate, duration, reversed_axes, self._window)
            thread.finished_ok.connect(done)
            thread.failed.connect(failed)
            nudge_state["thread"] = thread
            _set_nudge_busy(True)
            logger.info("Mount: nudge %s at %g°/s for %.1fs", direction, rate, duration)
            thread.start()

        for direction, btn in nudge_dir_buttons.items():
            btn.clicked.connect(lambda _checked=False, d=direction: _nudge(d))

        def _nudge_stop() -> None:
            mount = _nudge_mount_adapter()
            if mount is None:
                return
            import asyncio
            try:
                asyncio.run(mount.move_axis(0, 0.0))
                asyncio.run(mount.move_axis(1, 0.0))
            except Exception:
                logger.exception("Mount nudge stop failed")
            logger.info("Mount: nudge Stop requested")

        nudge_stop_btn.clicked.connect(_nudge_stop)

        self._imaging_ui = {
            "settings_panel": settings_panel, "dock_panel": dock_panel, "page": page,
            "fit_preview_width": _fit_preview_width, "content": content, "preview": preview_view,
            "histogram": histogram, "progress": progress_widget, "log": log_pane,
            "orientation_check": orientation_check, "orientation_combo": orientation_combo,
            "apply_orientation": _apply_orientation, "layout_state": layout_state,
            "quantity": quantity_spin, "gain": gain_spin, "auto_save": auto_save_check,
            "capture_button": capture_btn, "stop_button": stop_capture_btn, "status": status_label,
            "nudge_group": nudge_group, "nudge_buttons": nudge_dir_buttons, "nudge_stop": nudge_stop_btn,
            "nudge_rate": nudge_rate_combo, "nudge_duration": nudge_duration_spin,
            "nudge_state": nudge_state,
        }

        countdown = {"timer": None, "start": 0.0, "duration": 0.0, "frame": 1, "total": 1}

        def _tick_countdown() -> None:
            import time
            elapsed = time.monotonic() - countdown["start"]
            remaining = max(0.0, countdown["duration"] - elapsed)
            fraction = min(1.0, elapsed / countdown["duration"]) if countdown["duration"] else 1.0
            frame, total = countdown["frame"], countdown["total"]
            progress_bar.setValue(int((frame - 1 + fraction) / total * 1000))
            prefix = f"Frame {frame} of {total} — " if total > 1 else ""
            status_label.setText(f"{prefix}Exposing… {remaining:0.1f}s left" if remaining > 0 else f"{prefix}Downloading…")

        def on_slew_started(index: int, total: int) -> None:
            # Mosaic capture only (IMG-180): the re-slew to each pane can take as long as an
            # exposure, so it gets its own status text rather than looking like a stall.
            status_label.setText(f"Slewing to pane {index} of {total}…")

        def on_frame_started(frame: int, total: int) -> None:
            import time
            countdown["start"], countdown["frame"], countdown["total"] = time.monotonic(), frame, total

        def on_frame_done(_frame: int, _total: int) -> None:
            # Each frame is shown as it arrives, not only the last one of a series.
            _refresh_preview()
            _refresh_stats()
            _refresh_histogram()
            _apply_orientation()
            save_frame_btn.setEnabled(service.current_frame is not None)
            save_stack_btn.setEnabled(service.stack_frame_count > 0)

        def _refresh_library_images() -> None:
            images = getattr(getattr(self, "_library_screens", None), "images", None)
            if images is None:
                return              # the Library hasn't been opened yet; it reads the catalog when it is
            try:
                images.load_fits_data()
            except Exception:
                logger.exception("Could not refresh Library > Images")

        def _end_capture() -> None:
            timer = countdown["timer"]
            if timer is not None:
                timer.stop()
            capture_btn.setEnabled(True)
            stop_capture_btn.setEnabled(False)
            self._imaging_capture_thread = None

        def _series_summary() -> str:
            done, total = service.series_done, service.series_total
            text = ("Stopped" if service.stop_requested else "Complete") + (f" — {done} of {total} frames" if total > 1 or service.stop_requested else "")
            if service.debayer_note:
                text += f" — {service.debayer_note}"
            if service.auto_save_to_library:
                added = len(service.library_ids)
                text += f" — {added} added to the Library" if added else " — none added to the Library"
                if service.library_note:
                    text += f". {service.library_note}"
            if service.stacker.summary:
                text += f" — {service.stacker.summary}"
            return text

        def on_capture_finished() -> None:
            _end_capture()
            progress_bar.setValue(1000)
            save_stack_btn.setEnabled(service.stack_frame_count > 0)
            summary = _series_summary()
            status_label.setText(summary)
            status_label.setToolTip(summary)
            on_frame_done(0, 0)
            if service.library_ids:
                _refresh_library_images()
            self._window.statusBar().showMessage(summary, 6000)

        def on_capture_failed(message: str) -> None:
            _end_capture()
            status_label.setText("Idle")
            progress_bar.setValue(0)
            logger.error("Manual capture failed: %s", message)
            if service.library_ids:
                _refresh_library_images()
            self._window.statusBar().showMessage("Capture failed — see log.", 6000)

        def _refresh_mosaic_indicator() -> None:
            # IMG-180: makes it visible, before Capture is pressed, that a mosaic is active and
            # Capture will run the whole thing rather than a single frame (reported as missing —
            # a plain "Capture" button gave no hint a mosaic was about to be shot pane by pane).
            mosaic = service.active_mosaic
            active = mosaic is not None
            mosaic_indicator.setVisible(active)
            clear_mosaic_btn.setVisible(active)
            if active:
                mosaic_indicator.setText(
                    f"Mosaic active — {mosaic.cols}×{mosaic.rows} panels ({mosaic.total_panels} total). "
                    "Capture will slew to and expose every pane in turn, Quantity exposures each."
                )
                capture_btn.setText("Capture Mosaic")
                capture_btn.setToolTip(
                    "Slew to and expose every pane of the active mosaic in turn, Quantity exposures "
                    "at each, in pane-major order (IMG-180, FRAME-090). Clear Mosaic returns to a "
                    "single frame.")
                quantity_spin.setToolTip(
                    "How many exposures Capture takes at each pane before re-slewing to the next (IMG-180).")
            else:
                capture_btn.setText("Capture")
                capture_btn.setToolTip(
                    "Take Quantity frames one after another with these settings, independent of any "
                    "running sequence (IMG-070, IMG-150).")
                quantity_spin.setToolTip(
                    "How many frames Capture takes, one after another, with these settings (IMG-150).")

        def _clear_mosaic() -> None:
            service.active_mosaic = None
            _refresh_mosaic_indicator()
            self._window.statusBar().showMessage("Mosaic cleared — Capture will take a single frame.", 4000)

        clear_mosaic_btn.clicked.connect(_clear_mosaic)
        _refresh_mosaic_indicator()

        def do_capture() -> None:
            service._camera = _selected_camera_backend()
            if service._camera is None:
                QMessageBox.information(
                    self._window, "No camera connected", self.camera_not_connected_message(),
                )
                return
            if self._imaging_filter_thread is not None:
                self._window.statusBar().showMessage("Wait for the filter wheel to finish moving.", 4000)
                return

            mosaic_mode = service.active_mosaic is not None
            if mosaic_mode:
                service._mount = _nudge_mount_adapter()
                if service._mount is None:
                    QMessageBox.information(
                        self._window, "No mount connected",
                        "Capturing a mosaic needs a connected mount to move between panes — connect "
                        "one on Equipment > Mount, or use Clear Mosaic to take a single frame instead.",
                    )
                    return

            current = self.current_object()
            service.object_name = current.name if current is not None else ""
            duration = exposure_spin.value()
            quantity = quantity_spin.value()
            frame_type = frame_type_combo.currentText()
            filter_name = filter_combo.currentText().strip()
            service.gain = gain_spin.value()
            service.auto_save_to_library = auto_save_check.isChecked()
            service.live_stack_enabled = live_stack_check.isChecked()
            service.frame_context = self._imaging_frame_context()
            _use_camera_bayer_pattern(rebuild=False)

            import time
            countdown.update(start=time.monotonic(), duration=duration, frame=1, total=quantity)
            capture_btn.setEnabled(False)
            stop_capture_btn.setEnabled(True)
            progress_bar.setValue(0)
            status_label.setToolTip("")
            _tick_countdown()

            timer = QTimer(page)
            timer.timeout.connect(_tick_countdown)
            timer.start(100)
            countdown["timer"] = timer

            if mosaic_mode:
                thread = _MosaicCaptureThread(service, quantity, duration, filter_name, frame_type, page)
                thread.slew_started.connect(on_slew_started)
            else:
                thread = _CaptureThread(service, quantity, duration, filter_name, frame_type, page)
            thread.frame_started.connect(on_frame_started)
            thread.frame_done.connect(on_frame_done)
            thread.finished_ok.connect(on_capture_finished)
            thread.failed.connect(on_capture_failed)
            self._imaging_capture_thread = thread
            thread.start()

        capture_btn.clicked.connect(do_capture)

        def stop_capture() -> None:
            service.request_stop()
            status_label.setText("Stopping…")
            camera = service._camera
            if camera is not None:
                import asyncio
                try:
                    asyncio.run(camera.abort_exposure())
                except Exception:
                    logger.exception("Could not abort the exposure")

        stop_capture_btn.clicked.connect(stop_capture)

        def _open_framing() -> None:
            self._open_framing_dialog(service)
            _refresh_mosaic_indicator()

        framing_btn.clicked.connect(_open_framing)

        def save_frame() -> None:
            if service.current_frame is None:
                return
            current = self.current_object()
            service.object_name = current.name if current is not None else ""
            path, _ = QFileDialog.getSaveFileName(
                self._window, "Save Frame", service.suggested_filename(), "FITS files (*.fits *.fit)",
            )
            if not path:
                return
            try:
                service.save_current_frame(path)
            except Exception:
                logger.exception("Could not save frame to %s", path)
                self._window.statusBar().showMessage("Could not save frame — see log.", 6000)
                return
            logger.info("Saved frame to %s", path)
            self._window.statusBar().showMessage(f"Saved frame to {path}.", 4000)

        save_frame_btn.clicked.connect(save_frame)

        def save_stack_to_file() -> None:
            path, _ = QFileDialog.getSaveFileName(
                self._window, "Save Stack", service.stack_filename(), "FITS files (*.fits *.fit)",
            )
            if not path:
                return
            try:
                service.save_stack(path)
            except Exception:
                logger.exception("Could not save the stack to %s", path)
                self._window.statusBar().showMessage("Could not save the stack — see log.", 6000)
                return
            logger.info("Saved the stack of %d frames to %s", service.stack_frame_count, path)
            self._window.statusBar().showMessage(f"Saved the stack to {path}.", 4000)

        def save_stack_to_library() -> None:
            current = self.current_object()
            service.object_name = current.name if current is not None else ""
            try:
                file_id = service.save_stack_to_library()
            except Exception:
                logger.exception("Could not add the stack to the Library")
                self._window.statusBar().showMessage("Could not add the stack to the Library — see log.", 6000)
                return
            if file_id:
                _refresh_library_images()
                message = f"Added the stack of {service.stack_frame_count} frames to the Library."
                if service.library_note:
                    message += f" {service.library_note}"
                self._window.statusBar().showMessage(message, 6000)
            else:
                self._window.statusBar().showMessage(
                    service.library_note or "The stack was not added to the Library — see log.", 8000)

        def save_stack() -> None:
            """Ask where the stack should go — the Library files it in the repository, a file
            puts it wherever the user says."""
            if service.stack_frame_count == 0:
                return
            menu = QMenu(page)
            to_library = menu.addAction("Save to Library")
            to_file = menu.addAction("Save to File…")
            to_library.triggered.connect(save_stack_to_library)
            to_file.triggered.connect(save_stack_to_file)
            menu.exec(save_stack_btn.mapToGlobal(save_stack_btn.rect().bottomLeft()))

        save_stack_btn.clicked.connect(save_stack)
        self._imaging_ui.update({
            "live_stack": live_stack_check, "save_stack_button": save_stack_btn,
            "save_stack_to_library": save_stack_to_library, "save_stack_to_file": save_stack_to_file,
        })

        _apply_orientation()
        return page

    # --- Star Atlas page (planetarium) ------------------------------------

    def _build_star_atlas_page(self) -> QWidget:
        """Star Atlas page: a basic planetarium (``galileo.ui.star_atlas``) with
        the time, site and display controls in the left panel and the sky view
        filling the rest. The site follows the selected Pier's Observatory."""
        import calendar
        import datetime as dt
        from PySide6.QtCore import QDateTime, Qt, QTimer
        from PySide6.QtWidgets import (
            QCheckBox, QDateTimeEdit, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout,
            QLabel, QLineEdit, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget,
        )
        from galileo.planning.sky_atlas import DSO_CATALOGS
        from galileo.ui.star_atlas import (
            StarAtlasView, format_dec, format_ra, load_display_prefs, save_display_prefs,
        )

        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        criteria, form = self._build_criteria_panel("Sky View")
        view = StarAtlasView()
        for attr, value in load_display_prefs().items():
            setattr(view, attr, set(value) if attr == "dso_catalogs" else value)

        find_edit = QLineEdit()
        find_edit.setPlaceholderText("e.g. Vega, Jupiter, M31")
        form.addRow("Find", find_edit)

        when_edit = QDateTimeEdit()
        when_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        when_edit.setTimeSpec(Qt.UTC)
        when_edit.setToolTip("Date and time shown, in UTC.")
        # The label sits on its own line so the field has the panel's full
        # width — beside the label it was too narrow to show the whole time.
        form.addRow(QLabel("Time (UTC)"))
        form.addRow(when_edit)

        step_row = QHBoxLayout()
        step_buttons = []
        for label, delta in (("−1d", dt.timedelta(days=-1)), ("−1h", dt.timedelta(hours=-1)),
                             ("+1h", dt.timedelta(hours=1)), ("+1d", dt.timedelta(days=1))):
            btn = QPushButton(label)
            btn.setToolTip(f"Step the time by {label.replace('−', '-')}")
            step_row.addWidget(btn)
            step_buttons.append((btn, delta))
        form.addRow(step_row)

        live_check = QCheckBox("Live (follow the clock)")
        live_check.setChecked(True)
        form.addRow(live_check)

        lat_spin = QDoubleSpinBox()
        lat_spin.setRange(-90.0, 90.0)
        lat_spin.setDecimals(4)
        lat_spin.setSuffix("° N")
        lon_spin = QDoubleSpinBox()
        lon_spin.setRange(-180.0, 180.0)
        lon_spin.setDecimals(4)
        lon_spin.setSuffix("° E")
        form.addRow("Latitude", lat_spin)
        form.addRow("Longitude", lon_spin)

        mag_spin = QDoubleSpinBox()
        mag_spin.setRange(0.0, 7.0)
        mag_spin.setDecimals(1)
        mag_spin.setSingleStep(0.5)
        mag_spin.setValue(view.mag_limit)
        form.addRow("Star magnitude limit", mag_spin)

        dso_mag_spin = QDoubleSpinBox()
        dso_mag_spin.setRange(0.0, 16.0)
        dso_mag_spin.setDecimals(1)
        dso_mag_spin.setValue(view.dso_mag_limit)
        form.addRow("Deep-sky magnitude limit", dso_mag_spin)

        toggles = (("Coordinate grid", "show_grid"), ("Constellation boundaries", "show_boundaries"),
                   ("Constellation outlines", "show_lines"),
                   ("Abbreviate constellation names", "abbreviate_constellations"),
                   ("Deep-sky objects", "show_dsos"),
                   ("Sun, Moon && planets", "show_bodies"), ("Labels", "show_labels"),
                   ("Ground", "show_ground"), ("Daylight sky", "daylight_sky"),
                   ("Horizon", "show_horizon"),
                   ("Telescope markers", "show_pier_markers"))
        for text, attr in toggles:
            box = QCheckBox(text)
            box.setChecked(getattr(view, attr))
            box.toggled.connect(lambda checked, a=attr: (view.set_option(a, checked), save_display_prefs(view)))
            form.addRow(box)

        status = QLabel("Loading catalogs…")
        status.setObjectName("StatusHint")
        status.setWordWrap(True)
        form.addRow(status)

        # Deep-sky catalogs: the "+" adds one to the map, each listed catalog has a "×" to remove it.
        catalogs_header = QHBoxLayout()
        catalogs_header.addWidget(QLabel("Catalogs"))
        catalogs_header.addStretch(1)
        add_catalog_btn = QToolButton()
        add_catalog_btn.setText("+")
        add_catalog_btn.setToolTip("Add a deep-sky catalog to the map")
        catalogs_header.addWidget(add_catalog_btn)
        form.addRow(catalogs_header)
        catalog_rows = QVBoxLayout()
        catalog_rows.setSpacing(2)
        form.addRow(catalog_rows)

        def refresh_catalog_rows() -> None:
            while catalog_rows.count():
                item = catalog_rows.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
            counts = view.dso_catalog_counts()
            for cat in DSO_CATALOGS:
                if cat not in view.dso_catalogs:
                    continue
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.addWidget(QLabel(f"{cat} ({counts[cat]:,})" if counts else cat))
                row_layout.addStretch(1)
                remove = QToolButton()
                remove.setText("×")
                remove.setToolTip(f"Remove {cat} from the map")
                remove.clicked.connect(lambda _=False, c=cat: set_catalogs(view.dso_catalogs - {c}))
                row_layout.addWidget(remove)
                catalog_rows.addWidget(row)
            add_catalog_btn.setEnabled(any(c not in view.dso_catalogs for c in DSO_CATALOGS))

        def set_catalogs(chosen) -> None:
            view.set_dso_catalogs(chosen)
            save_display_prefs(view)
            refresh_catalog_rows()

        def show_catalog_menu() -> None:
            menu = QMenu(add_catalog_btn)
            for cat in DSO_CATALOGS:
                if cat not in view.dso_catalogs:
                    menu.addAction(cat, lambda c=cat: set_catalogs(view.dso_catalogs | {c}))
            menu.exec(add_catalog_btn.mapToGlobal(add_catalog_btn.rect().bottomLeft()))

        add_catalog_btn.clicked.connect(show_catalog_menu)
        refresh_catalog_rows()

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)

        heading = QLabel("Star Atlas")
        heading.setObjectName("PageTitle")
        content_layout.addWidget(heading)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(view, 1)

        details = QFrame()
        details.setObjectName("DeviceSlotPanel")
        details.setFixedWidth(230)
        details_layout = QVBoxLayout(details)
        details_form = QFormLayout()
        detail_values = {}
        for key, label in (("name", "Name"), ("type", "Type"), ("mag", "Magnitude"), ("const", "Constellation"),
                           ("ra", "RA (J2000)"), ("dec", "Dec (J2000)"), ("alt", "Altitude"), ("az", "Azimuth")):
            value = QLabel("—")
            value.setWordWrap(True)
            detail_values[key] = value
            details_form.addRow(label, value)
        details_layout.addLayout(details_form)
        hint = QLabel("Click an object to identify it. Double-click to centre and track it. "
                      "Drag to pan, scroll to zoom. Right-click for Goto and Sync.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        details_layout.addWidget(hint)
        details_layout.addStretch(1)
        body.addWidget(details)
        content_layout.addLayout(body, 1)

        layout.addWidget(criteria)
        layout.addWidget(content, 1)

        # --- wiring -----------------------------------------------------------

        def show_object(obj: dict) -> None:
            from galileo.planning.sky_atlas import constellation_for
            detail_values["name"].setText(obj["name"] + (f" ({obj['designation']})" if obj.get("designation") else ""))
            detail_values["type"].setText(obj["type"])
            detail_values["mag"].setText(f"{obj['mag']:.1f}")
            try:
                detail_values["const"].setText(constellation_for(obj["ra_deg"], obj["dec_deg"]))
            except Exception:
                logger.exception("Could not compute constellation for %s", obj["name"])
                detail_values["const"].setText("—")
            detail_values["ra"].setText(format_ra(obj["ra_deg"]))
            detail_values["dec"].setText(format_dec(obj["dec_deg"]))
            refresh_altaz()

        def refresh_altaz() -> None:
            obj = view.selected
            if obj is None:
                return
            alt, az = view._altaz_of(obj)
            detail_values["alt"].setText(f"{alt:.1f}°" + ("  (below horizon)" if alt < 0 else ""))
            detail_values["az"].setText(f"{az:.1f}°")

        def find_object() -> None:
            query = find_edit.text().strip()
            if not query:
                return
            obj = view.find(query)
            if obj is None:
                self._window.statusBar().showMessage(f"Nothing called {query!r} in the loaded catalogs.", 6000)
                return
            view.select(obj)
            view.center_on(obj)
            if obj["alt"] < 0:
                self._window.statusBar().showMessage(f"{obj['name']} is below the horizon at this time and place.", 6000)

        def set_view_time() -> None:
            view.set_time(when_edit.dateTime().toUTC().toPython().replace(tzinfo=None))

        def on_time_edited() -> None:
            live_check.setChecked(False)
            set_view_time()

        def on_step(delta: dt.timedelta) -> None:
            live_check.setChecked(False)
            when_edit.setDateTime(when_edit.dateTime().addSecs(int(delta.total_seconds())))  # -> dateTimeChanged

        def on_live(live: bool) -> None:
            when_edit.setEnabled(not live)
            for btn, _ in step_buttons:
                btn.setEnabled(not live)
            view.set_live(live)

        def sync_time_field() -> None:
            when_edit.blockSignals(True)
            when_edit.setDateTime(QDateTime.fromSecsSinceEpoch(
                calendar.timegm(view.when.replace(second=0, microsecond=0).timetuple()), Qt.UTC))
            when_edit.blockSignals(False)

        def set_site() -> None:
            view.set_location(lat_spin.value(), lon_spin.value())
            if view.selected is not None:
                refresh_altaz()

        def refresh_site() -> None:
            """Take latitude/longitude from the selected Pier's Observatory."""
            pier = self._current_pier
            if pier is None:
                return
            try:
                observatory = pier.observatory
                lat = observatory.latitude if observatory.latitude is not None else lat_spin.value()
                lon = observatory.longitude if observatory.longitude is not None else lon_spin.value()
            except Exception:
                logger.exception("Could not read the Observatory's site coordinates")
                return
            for spin, value in ((lat_spin, lat), (lon_spin, lon)):
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
            view.set_location(lat, lon)
            if lat < 0:
                view.center_on_altaz(40.0, 0.0)   # look north from the southern hemisphere

        find_edit.returnPressed.connect(find_object)
        when_edit.dateTimeChanged.connect(lambda _dt: on_time_edited())
        for btn, delta in step_buttons:
            btn.clicked.connect(lambda _checked=False, d=delta: on_step(d))
        live_check.toggled.connect(on_live)
        lat_spin.editingFinished.connect(set_site)
        lon_spin.editingFinished.connect(set_site)
        mag_spin.valueChanged.connect(lambda v: view.set_option("mag_limit", v))
        dso_mag_spin.valueChanged.connect(lambda v: view.set_option("dso_mag_limit", v))
        view.objectSelected.connect(show_object)
        view.objectSelected.connect(self._set_current_object)

        def show_context_menu(obj, global_pos) -> None:
            menu = QMenu(view)
            goto = menu.addAction("Goto")
            goto.setToolTip("Slew the current Pier's mount to this object")
            sync = menu.addAction("Sync")
            sync.setToolTip("Tell the current Pier's mount it is pointing at this object")
            menu.addSeparator()
            add_to_session = menu.addAction("Add to Session")
            add_to_session.setToolTip(
                "Create a new session pre-populated with a Target block for this object (SES-160). "
                "A plain click only selects it — this is the explicit way to build a session from it."
            )
            goto.setEnabled(obj is not None)
            sync.setEnabled(obj is not None)
            add_to_session.setEnabled(obj is not None)
            goto.triggered.connect(lambda: self._mount_to_object("goto", obj))
            sync.triggered.connect(lambda: self._mount_to_object("sync", obj))
            add_to_session.triggered.connect(
                lambda: self._add_to_session(obj["name"], obj["ra_deg"], obj["dec_deg"])
            )
            menu.exec(global_pos)

        view.contextMenuRequested.connect(show_context_menu)
        view.viewChanged.connect(lambda: (sync_time_field() if live_check.isChecked() else None, refresh_altaz()))
        def show_catalog_status(stars: int, dsos: int) -> None:
            text = f"{stars:,} stars · {dsos:,} deep-sky objects"
            offline = stars < 200 or dsos == 0 or len(view._bounds) == 0 or len(view._lines) == 0
            if offline:
                text += (" (offline — connect to the internet once to load the full star and"
                         " deep-sky catalogs, constellation boundaries and outlines)")
            status.setText(text)
            refresh_catalog_rows()

        view.catalogsLoaded.connect(show_catalog_status)

        # Telescope reticles (SKYMAP-090). The mount is polled only while this page is on
        # screen, and more often while a slew is running so the reticle keeps up with it.
        def refresh_markers() -> None:
            view.set_pier_markers(self.pier_markers())

        def poll_markers() -> None:
            self._poll_pier_pointing(on_done=refresh_markers)
            slewing = any(m.get("slewing") for m in view.pier_markers)
            marker_timer.setInterval(_SLEWING_POLL_MS if slewing else _POINTING_POLL_MS)

        marker_timer = QTimer(page)
        marker_timer.timeout.connect(_when_visible(page, poll_markers))
        marker_timer.start(_POINTING_POLL_MS)

        self._star_atlas_refresh_site = refresh_site
        self._star_atlas_set_horizon = view.set_horizon
        self._star_atlas_refresh_markers = refresh_markers
        refresh_markers()
        refresh_site()
        sync_time_field()
        on_live(True)
        view.load_catalogs()
        return page

    # --- Options > Star Atlas / Planning ------------------------------------

    def _build_star_atlas_settings_page(self) -> QWidget:
        """Options > Star Atlas: upload a file of azimuth/altitude pairs describing the
        horizon obstructions at the current Observatory, or edit them point by point
        (SKY-040). They are kept in a table shown here, shaded on the Star Atlas by its
        "Horizon" checkbox, and (with Options > Planning) used to refuse slews into them."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
            QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
        )
        from galileo.observatory import save_horizon_points
        from galileo.planning.visibility import parse_horizon_text

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Star Atlas settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        subtitle = QLabel("Horizon obstructions")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)

        hint = QLabel(
            "Upload a text file with one “azimuth altitude” pair per line, or edit points directly "
            "in the table below (degrees; azimuth from north through east, 0–360; altitude 0–90). "
            "Each altitude is the height of the obstruction at that azimuth — the sky below it is "
            "blocked. The values are joined by straight lines, wrapping through north. Turn on "
            "“Horizon” on the Star Atlas to see them shaded.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        upload_btn = QPushButton("Upload horizon file…")
        upload_btn.setObjectName("AccentButton")
        clear_btn = QPushButton("Clear")
        clear_btn.setToolTip("Delete this Observatory's horizon obstruction table")
        add_point_btn = QPushButton("Add Point")
        add_point_btn.setToolTip("Add a new azimuth/altitude row to edit")
        remove_point_btn = QPushButton("Remove Selected")
        remove_point_btn.setToolTip("Remove the selected row(s)")
        save_points_btn = QPushButton("Save Changes")
        save_points_btn.setObjectName("AccentButton")
        save_points_btn.setToolTip("Save edits made directly in the table")
        buttons.addWidget(upload_btn)
        buttons.addWidget(clear_btn)
        buttons.addWidget(add_point_btn)
        buttons.addWidget(remove_point_btn)
        buttons.addWidget(save_points_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        status = QLabel("")
        status.setObjectName("StatusHint")
        layout.addWidget(status)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Azimuth (°)", "Altitude (°)"])
        table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(table, 1)

        def refresh(points: list) -> None:
            table.setRowCount(len(points))
            for row, (az, alt) in enumerate(points):
                for col, value in enumerate((az, alt)):
                    item = QTableWidgetItem(f"{value:g}")
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(row, col, item)
            observatory = self._current_observatory
            if observatory is None:
                status.setText("Create an Observatory first — the horizon belongs to one.")
            elif points:
                status.setText(f"{len(points)} obstruction points for {observatory.name}.")
            else:
                status.setText(f"No horizon obstructions defined for {observatory.name}.")
            has_observatory = observatory is not None
            upload_btn.setEnabled(has_observatory)
            clear_btn.setEnabled(bool(points))
            add_point_btn.setEnabled(has_observatory)
            remove_point_btn.setEnabled(has_observatory and table.rowCount() > 0)
            save_points_btn.setEnabled(has_observatory)

        def store(points: list) -> None:
            try:
                save_horizon_points(self._current_observatory, points)
            except Exception:
                logger.exception("Could not save the horizon obstructions")
                QMessageBox.warning(self._window, "Horizon", "Could not save the horizon — see the log.")
                return
            self._apply_horizon()

        def upload() -> None:
            path, _ = QFileDialog.getOpenFileName(
                self._window, "Upload horizon file", "", "Text files (*.txt *.csv *.hzn *.dat);;All files (*)")
            if not path:
                return
            try:
                with open(path, encoding="utf-8-sig") as f:
                    points = parse_horizon_text(f.read())
            except (OSError, UnicodeDecodeError) as exc:
                logger.exception("Could not read horizon file %s", path)
                QMessageBox.warning(self._window, "Horizon", f"Could not read {path}:\n{exc}")
                return
            except ValueError as exc:
                QMessageBox.warning(self._window, "Horizon", f"{path} is not a valid horizon file.\n\n{exc}")
                return
            store(points)
            self._window.statusBar().showMessage(f"Loaded {len(points)} horizon obstruction points.", 5000)

        def add_point() -> None:
            row = table.rowCount()
            table.setRowCount(row + 1)
            for col in (0, 1):
                item = QTableWidgetItem("0")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row, col, item)
            remove_point_btn.setEnabled(True)
            table.editItem(table.item(row, 0))

        def remove_selected() -> None:
            for row in sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True):
                table.removeRow(row)
            remove_point_btn.setEnabled(table.rowCount() > 0)

        def save_edits() -> None:
            points: list[tuple[float, float]] = []
            for row in range(table.rowCount()):
                az_item, alt_item = table.item(row, 0), table.item(row, 1)
                try:
                    az, alt = float(az_item.text() if az_item else ""), float(alt_item.text() if alt_item else "")
                except ValueError:
                    QMessageBox.warning(self._window, "Horizon",
                                         f"Row {row + 1}: azimuth and altitude must both be numbers.")
                    return
                if not (0.0 <= az <= 360.0) or not (0.0 <= alt <= 90.0):
                    QMessageBox.warning(self._window, "Horizon",
                                         f"Row {row + 1}: azimuth must be 0–360° and altitude 0–90° "
                                         f"(got {az:g}, {alt:g}).")
                    return
                points.append((az, alt))
            points.sort(key=lambda p: p[0])
            store(points)
            self._window.statusBar().showMessage(f"Saved {len(points)} horizon obstruction points.", 5000)

        upload_btn.clicked.connect(upload)
        clear_btn.clicked.connect(lambda: store([]))
        add_point_btn.clicked.connect(add_point)
        remove_point_btn.clicked.connect(remove_selected)
        save_points_btn.clicked.connect(save_edits)
        self._horizon_table_refresh = refresh
        refresh([])
        return page

    def _build_planning_settings_page(self) -> QWidget:
        """Options > Planning: whether slews into the Star Atlas horizon
        obstructions are refused, and bulk-caching every catalog object's
        survey-image thumbnail ahead of time (SKY-080)."""
        from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QVBoxLayout, QWidget
        from galileo.planning.settings import load_planning_settings, save_planning_settings

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Planning settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        settings = load_planning_settings()
        block = QCheckBox("Do not slew where obstructed (see Star Atlas)")
        block.setToolTip("Refuse any slew whose altitude/azimuth is below the horizon obstructions "
                         "defined under Options > Star Atlas.")
        block.setChecked(settings["block_obstructed_slews"])
        layout.addWidget(block)

        hint = QLabel(f"A refused slew reports “{_OBSTRUCTED_MESSAGE}”, whether it was asked for from "
                      "the Mount page, the Star Atlas, a sequence or plate solving. Needs a horizon "
                      "uploaded under Options > Star Atlas.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        def changed(checked: bool) -> None:
            settings["block_obstructed_slews"] = checked
            save_planning_settings(settings)
            self._apply_horizon()

        block.toggled.connect(changed)

        cache_heading = QLabel("Sky-survey thumbnails")
        cache_heading.setObjectName("PageSubtitle")
        layout.addWidget(cache_heading)

        cache_btn = QPushButton("Cache All Catalog Thumbnails…")
        cache_btn.setToolTip(
            "Pre-fetches every catalog object's survey-image thumbnail (SKY-080), so a later Planning "
            "> Targets search shows its result-tile images immediately instead of fetching them then."
        )
        layout.addWidget(cache_btn)

        cache_hint = QLabel(
            "Fetches a thumbnail for every object in the offline catalog not already cached — tens of "
            "thousands of objects, one network request each, so this can take hours. Already-cached "
            "objects (from an earlier run, or from having shown up in a search) are skipped instantly, "
            "so it's safe to cancel and resume later, or run again after the catalog updates."
        )
        cache_hint.setObjectName("StatusHint")
        cache_hint.setWordWrap(True)
        layout.addWidget(cache_hint)
        layout.addStretch(1)

        cache_btn.clicked.connect(lambda: self._cache_all_catalog_thumbnails(page))
        return page

    def _cache_all_catalog_thumbnails(self, parent: QWidget) -> None:
        """Options > Planning's "Cache All Catalog Thumbnails…" button
        (SKY-080): confirms the scale of the operation (this is a real,
        potentially hours-long bulk network fetch, not a quick local task),
        then runs `_ThumbnailCacheThread` behind a cancellable progress
        dialog — the same worker-thread/`QProgressDialog` pattern
        `galileo.ui.library.download_dialog`'s telescope download already
        uses, not a new one."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox, QProgressDialog

        try:
            from galileo.planning.sky_atlas import SkyAtlas
            total = len(SkyAtlas()._catalog)
        except Exception:
            logger.exception("Could not load the catalog to size the thumbnail-caching confirmation")
            total = 0

        confirmed = QMessageBox.question(
            parent, "Cache All Catalog Thumbnails",
            f"This fetches a survey-image thumbnail for every object in the catalog not already "
            f"cached ({total:,} objects total) — one network request each, so it can take hours. "
            f"You can cancel at any time; progress made so far stays cached. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirmed != QMessageBox.Yes:
            return

        progress_dialog = QProgressDialog("Starting…", "Cancel", 0, max(total, 1), parent)
        progress_dialog.setWindowTitle("Caching Thumbnails")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setValue(0)
        progress_dialog.show()

        worker = _ThumbnailCacheThread(parent)
        self._thumbnail_cache_worker = worker  # keep a live reference so it isn't GC'd mid-run

        def on_progress(done: int, of_total: int) -> None:
            progress_dialog.setMaximum(max(of_total, 1))
            progress_dialog.setValue(done)
            progress_dialog.setLabelText(f"Caching thumbnails: {done:,} / {of_total:,}")

        def on_finished(cached: int, failed: int) -> None:
            progress_dialog.close()
            self._window.statusBar().showMessage(
                f"Thumbnail caching complete: {cached:,} cached/already-cached, {failed:,} failed.", 8000)
            self._thumbnail_cache_worker = None

        def on_failed(message: str) -> None:
            progress_dialog.close()
            QMessageBox.critical(parent, "Thumbnail Caching Failed", message)
            self._thumbnail_cache_worker = None

        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_finished)
        worker.failed.connect(on_failed)
        progress_dialog.canceled.connect(worker.stop)
        worker.start()

    # --- Options > Imaging ---------------------------------------------------

    def _build_imaging_settings_page(self) -> QWidget:
        """Options > Imaging: the FITS sample format (BITPIX) saved frames are written in (IMG-170)."""
        from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget
        from galileo.imaging_settings import load_imaging_settings, save_imaging_settings
        from galileo.metadata import BITPIX_AUTO, BITPIX_CHOICES

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Imaging settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        form = QFormLayout()
        form.setSpacing(8)
        layout.addLayout(form)

        # Label -> stored value. "Auto" writes unsigned 16-bit where the data fits and 32-bit
        # float otherwise — the pre-existing, still the default, behaviour.
        labels = {
            BITPIX_AUTO: "Auto (recommended)",
            8: "8 (unsigned integer)",
            16: "16 (unsigned integer)",
            32: "32 (signed integer)",
            -32: "-32 (floating point)",
        }
        bitpix_combo = QComboBox()
        for value in BITPIX_CHOICES:
            bitpix_combo.addItem(labels[value], value)
        bitpix_combo.setToolTip(
            "The pixel format frames are saved in — Save Frame, Auto-Save to Library and Save Stack "
            "on the Imaging tab (IMG-170). Auto picks the smallest of these that fits each frame "
            "without losing data. A fixed value writes every frame in that one format instead, for "
            "downstream tools that expect one consistent format; values outside its range are clipped "
            "and a float is rounded to the nearest integer. Every value here is one other astronomy "
            "software actually reads — Galileo never writes a 64-bit FITS, which ASTAP and Tenmon "
            "both refuse as an unsupported sample format."
        )
        settings = load_imaging_settings()
        idx = bitpix_combo.findData(settings["bitpix"])
        bitpix_combo.setCurrentIndex(max(idx, 0))
        form.addRow("Desired BITPIX", bitpix_combo)

        hint = QLabel(
            "Applies to frames the Imaging tab saves. Frames captured for plate solving always use "
            "whichever of these formats best fits, regardless of this setting, since that is about "
            "what the solver can read rather than a preference."
        )
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        def changed(index: int) -> None:
            settings["bitpix"] = bitpix_combo.itemData(index)
            save_imaging_settings(settings)
            # Take effect on the page already built, not only on the next launch.
            service = getattr(self, "_imaging_service", None)
            if service is not None:
                service.bitpix = settings["bitpix"]

        bitpix_combo.currentIndexChanged.connect(changed)
        return page

    # --- Options > Focus -------------------------------------------------------

    def _build_focus_settings_page(self) -> QWidget:
        """Options > Focus: the current Pier's saved autofocus defaults
        (step size, points, exposure, backlash — FOC-070), which seed the
        Focus screen's own controls. Scoped per Pier, like the Equipment
        pages' saved device configuration."""
        from PySide6.QtWidgets import (
            QDoubleSpinBox, QFormLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
        )
        from galileo.autofocus import AutofocusParams
        from galileo.observatory import get_autofocus_params, save_autofocus_params

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Focus settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        status = QLabel("")
        status.setObjectName("StatusHint")
        layout.addWidget(status)

        form = QFormLayout()
        form.setSpacing(8)
        layout.addLayout(form)

        step_spin = QSpinBox()
        step_spin.setRange(1, 100000)
        step_spin.setSuffix(" steps")
        step_spin.setToolTip("Focuser steps between successive exposures during a sweep.")
        form.addRow("Step size", step_spin)

        points_spin = QSpinBox()
        points_spin.setRange(3, 41)
        points_spin.setToolTip("Number of exposures across the sweep, centred on the current position.")
        form.addRow("Number of points", points_spin)

        exposure_spin = QDoubleSpinBox()
        exposure_spin.setRange(0.01, 600.0)
        exposure_spin.setDecimals(2)
        exposure_spin.setSuffix(" s")
        exposure_spin.setToolTip("Exposure time of each frame measured during a sweep.")
        form.addRow("Exposure time", exposure_spin)

        backlash_spin = QSpinBox()
        backlash_spin.setRange(0, 100000)
        backlash_spin.setSuffix(" steps")
        backlash_spin.setToolTip(
            "Overshoot then return by this many steps before every focuser move during a run "
            "(0 disables compensation).")
        form.addRow("Backlash compensation", backlash_spin)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        layout.addWidget(save_btn)

        hint = QLabel("Applies to the next autofocus run started from the Focus screen, whether "
                      "started there or by a sequencer trigger. Saved per Pier.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        def refresh() -> None:
            pier = self._current_pier
            params = get_autofocus_params(pier)
            step_spin.setValue(params.step_size)
            points_spin.setValue(params.num_points)
            exposure_spin.setValue(params.exposure_s)
            backlash_spin.setValue(params.backlash_compensation)
            status.setText(f"Editing defaults for Pier {pier.name!r}." if pier is not None
                           else "Select a Pier first — these settings are saved per Pier.")
            save_btn.setEnabled(pier is not None)
            for widget in (step_spin, points_spin, exposure_spin, backlash_spin):
                widget.setEnabled(pier is not None)

        def save() -> None:
            if self._current_pier is None:
                return
            params = AutofocusParams(
                step_size=step_spin.value(), num_points=points_spin.value(),
                exposure_s=exposure_spin.value(), backlash_compensation=backlash_spin.value(),
            )
            save_autofocus_params(self._current_pier, params)
            focus_state = self._device_pages.get("focus")
            if focus_state is not None:
                focus_state["reload"]()
            self._window.statusBar().showMessage(f"Saved Focus settings for Pier {self._current_pier.name!r}.", 4000)

        save_btn.clicked.connect(save)
        self._focus_settings_refresh = refresh
        refresh()
        return page

    # --- Options > Solve --------------------------------------------------------

    def _build_solve_settings_page(self) -> QWidget:
        """Options > Solve: the current Pier's saved solver defaults —
        an ASTAP executable-path override, field-of-view hint, search radius
        and downsample factor (PLT-060). Scoped per Pier, like Options > Focus."""
        from PySide6.QtWidgets import (
            QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
            QPushButton, QSpinBox, QVBoxLayout, QWidget,
        )
        from galileo.observatory import get_solver_settings, save_solver_settings
        from galileo.platesolve import SolverParams

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Solve settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        status = QLabel("")
        status.setObjectName("StatusHint")
        layout.addWidget(status)

        form = QFormLayout()
        form.setSpacing(8)
        layout.addLayout(form)

        exe_row = QHBoxLayout()
        exe_edit = QLineEdit()
        exe_edit.setPlaceholderText("Auto-detected if left blank")
        exe_edit.setToolTip("Path to the ASTAP executable. Leave blank to auto-detect it on PATH "
                            "or in its usual install location.")
        browse_btn = QPushButton("Browse…")
        exe_row.addWidget(exe_edit, 1)
        exe_row.addWidget(browse_btn)
        form.addRow("ASTAP executable", exe_row)

        fov_spin = QDoubleSpinBox()
        fov_spin.setRange(0.0, 60.0)
        fov_spin.setDecimals(2)
        fov_spin.setSuffix(" °")
        fov_spin.setSpecialValueText("Auto (from optical train)")
        fov_spin.setToolTip("Field-of-view hint given to the solver. 0 derives it from the active "
                            "optical train's focal length and pixel size instead of a fixed value.")
        form.addRow("Field-of-view hint", fov_spin)

        radius_spin = QDoubleSpinBox()
        radius_spin.setRange(0.5, 180.0)
        radius_spin.setDecimals(1)
        radius_spin.setSuffix(" °")
        radius_spin.setToolTip("The solver searches only within this radius of the hinted position.")
        form.addRow("Search radius", radius_spin)

        downsample_spin = QSpinBox()
        downsample_spin.setRange(0, 8)
        downsample_spin.setSpecialValueText("Off")
        downsample_spin.setToolTip("Downsample the frame by this factor before solving, for a faster "
                                   "but less precise solve (0 solves at full resolution).")
        form.addRow("Downsample", downsample_spin)

        def browse() -> None:
            path, _ = QFileDialog.getOpenFileName(self._window, "ASTAP executable")
            if path:
                exe_edit.setText(path)

        browse_btn.clicked.connect(browse)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("AccentButton")
        layout.addWidget(save_btn)

        hint = QLabel("Applies to solves started from the Solve screen. Saved per Pier.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        def refresh() -> None:
            pier = self._current_pier
            executable, params = get_solver_settings(pier)
            exe_edit.setText(executable)
            fov_spin.setValue(params.fov_hint_deg)
            radius_spin.setValue(params.search_radius_deg)
            downsample_spin.setValue(params.downsample)
            status.setText(f"Editing defaults for Pier {pier.name!r}." if pier is not None
                           else "Select a Pier first — these settings are saved per Pier.")
            save_btn.setEnabled(pier is not None)
            for widget in (exe_edit, browse_btn, fov_spin, radius_spin, downsample_spin):
                widget.setEnabled(pier is not None)

        def save() -> None:
            if self._current_pier is None:
                return
            params = SolverParams(
                fov_hint_deg=fov_spin.value(), search_radius_deg=radius_spin.value(),
                downsample=downsample_spin.value(),
            )
            save_solver_settings(self._current_pier, exe_edit.text().strip(), params)
            self._window.statusBar().showMessage(f"Saved Solve settings for Pier {self._current_pier.name!r}.", 4000)

        save_btn.clicked.connect(save)
        self._solve_settings_refresh = refresh
        refresh()
        return page

    # --- Planning page (formerly Sky Atlas; secondary panel = search criteria, not icons) ---

    def _build_sky_atlas_page(self) -> QWidget:
        """Planning page — the catalog lookup formerly labelled Sky Atlas
        (SKY-010 … SKY-120): search criteria on the left, one result tile
        per row filling the rest of the page — no separate details panel,
        and no grid (each row's item widget always spans the full list
        width in Qt's default list mode, so the visible, white-bordered tile
        is narrowed to ``_TILE_WIDTH_FRACTION`` of that width and
        left-aligned within its row via ``_tile_row``, rather than switching
        the list itself to a wrapping icon/grid view). Each tile carries
        everything the removed details panel used to show — name/type,
        magnitude/size/constellation/RA/Dec, rise/transit/set, and a mini
        altitude-over-the-night chart with a labelled time axis — plus a
        thumbnail for the first few (``_MAX_AUTO_THUMBNAILS`` below) and,
        rightmost, per-tile action buttons (Select/Slew To/Add to Session —
        see ``_build_result_card``), matching what Obsy's target search was
        set up to show for a Simbad hit (its ``target_query`` view plus
        ``Target.save()``'s DSS-cutout fetch, ADR-005), extended past what
        Obsy had per SKY-020/030's own requirement text.

        The altitude chart/rise-transit-set for every tile is computed in one
        batch (``SkyAtlas.altitude_charts_batch``, a single vectorized astropy
        transform) rather than per tile — computing it individually for up to
        200 results measured at ~10s, genuinely UI-blocking; batched, the same
        200 results measure at ~1s. Thumbnails stay individually fetched and
        capped, unlike the chart/rise-set data — each is a real network
        request (hips2fits), not a local computation, so the same batching
        approach doesn't apply and the existing bound still holds."""
        from PySide6.QtWidgets import (
            QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QComboBox,
            QDoubleSpinBox, QPushButton, QListWidget, QListWidgetItem,
            QApplication, QCheckBox,
        )
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
        from galileo.ui.scheduler import _AltitudeChart

        # Auto-fetched result-card thumbnails (below) are capped at this many —
        # each one is a real network request (hips2fits), and a filtered search
        # can return up to 200 matches; fetching all of them up front would
        # freeze the UI for a long time and hammer the survey-image service for
        # results the user may never scroll to. The rest of a large result set
        # still gets a card with every other detail, just without an image.
        # The altitude chart/rise-transit-set data, unlike thumbnails, is a
        # local computation (batched — see the method docstring) cheap enough
        # to compute for every card, not just the first few.
        _MAX_AUTO_THUMBNAILS = 12
        _CARD_THUMB_PX = 44
        _CARD_CHART_SIZE = (130, 74)
        # Each result tile is sized to this fraction of the results list's own
        # width, with a floor so thumbnail+text+chart+buttons still fit at a
        # narrow window size — computed per search (`_tile_width()` below),
        # not once, since the list's width isn't final until the page is
        # actually shown. Raised from 340 alongside the action buttons
        # becoming content-sized (below) rather than a too-narrow fixed
        # width, which was clipping "Add to Session".
        _TILE_WIDTH_FRACTION = 0.50
        _TILE_MIN_WIDTH_PX = 420

        def _fmt_rise_set_time(iso: str | None) -> str:
            if iso is None:
                return "—"
            import datetime as _dt
            return _dt.datetime.fromisoformat(iso).strftime("%H:%M")

        def _build_result_card(obj, rise_set_text: str, chart: dict | None) -> tuple[QWidget, QLabel]:
            """One result's card: thumbnail slot, name/type/magnitude/size/
            constellation/RA/Dec/rise-transit-set, and (rightmost) a mini
            altitude chart — everything the removed details panel used to
            show, now per card. *rise_set_text* and *chart* (this object's
            pre-batched altitude data, or ``None`` with no Observatory
            location configured) are computed once by the caller, across all
            results together, not per card. The thumbnail starts blank; the
            caller fills it in later for the first ``_MAX_AUTO_THUMBNAILS``
            cards only."""
            card = QWidget()
            card.setObjectName("ResultTile")
            card.setStyleSheet("QWidget#ResultTile { border: 1px solid white; border-radius: 4px; }")
            row = QHBoxLayout(card)
            row.setContentsMargins(6, 4, 6, 4)
            row.setSpacing(8)

            # Left: thumbnail beside name/type on one line, then the rest of
            # the details full-width below — makes better use of a narrow
            # tile's width than a single thumb-then-text row would.
            left_col = QVBoxLayout()
            left_col.setSpacing(2)

            top_row = QHBoxLayout()
            top_row.setSpacing(6)
            thumb_label = _ClickableThumbnail()
            thumb_label.setFixedSize(_CARD_THUMB_PX, _CARD_THUMB_PX)
            thumb_label.setAlignment(Qt.AlignCenter)
            thumb_label.setObjectName("DeviceSlotPanel")
            thumb_label.setCursor(Qt.PointingHandCursor)
            thumb_label.setToolTip("Click for a full-size view.")
            thumb_label.clicked.connect(lambda o=obj: self._show_full_image(o))
            top_row.addWidget(thumb_label)
            name_label = QLabel(f"{obj.primary_name} · {obj.object_type.value}")
            name_label.setObjectName("PageSubtitle")
            name_label.setWordWrap(True)
            top_row.addWidget(name_label, 1)
            left_col.addLayout(top_row)

            try:
                from galileo.planning.sky_atlas import constellation_for
                constellation = constellation_for(obj.ra_deg, obj.dec_deg)
            except Exception:
                logger.debug("Could not compute constellation for %s", obj.primary_name, exc_info=True)
                constellation = "—"
            mag_text = f"mag {obj.magnitude:.1f}" if obj.magnitude < 90.0 else "mag unknown"
            size_text = f"  ·  {obj.size_arcmin:.1f}′" if obj.size_arcmin > 0 else ""
            subtitle_label = QLabel(
                f"{mag_text}{size_text}  ·  {constellation}  ·  RA {obj.ra_deg:.3f}°  Dec {obj.dec_deg:.3f}°"
            )
            subtitle_label.setObjectName("StatusHint")
            subtitle_label.setWordWrap(True)
            left_col.addWidget(subtitle_label)

            rise_set_label = QLabel(rise_set_text)
            rise_set_label.setObjectName("StatusHint")
            rise_set_label.setWordWrap(True)
            left_col.addWidget(rise_set_label)
            left_col.addStretch(1)
            row.addLayout(left_col, 1)

            chart_widget = _AltitudeChart()
            chart_widget.setFixedSize(*_CARD_CHART_SIZE)
            if chart is not None and chart.get("altitudes"):
                chart_widget.set_data(chart["times"], chart["altitudes"])
            row.addWidget(chart_widget)

            # Rightmost: this result's own action buttons — select it as the
            # Pier's current target, slew the mount straight to it, or spin
            # up a brand-new session pre-populated with a Target block for it.
            button_col = QVBoxLayout()
            button_col.setSpacing(4)
            select_btn = QPushButton("Select")
            select_btn.setToolTip("Make this the Pier's current object (IMG-140) — captured frames "
                                  "are named after it, and Solve's Slew to Target slews to it — and "
                                  "add it to the target list (SKY-080).")
            select_btn.clicked.connect(lambda _=None, o=obj: self._select_result(o))
            button_col.addWidget(select_btn)

            slew_btn = QPushButton("Slew To")
            slew_btn.setToolTip("Immediately slew the connected mount to this object.")
            slew_btn.clicked.connect(lambda _=None, o=obj: _slew_to_result(o))
            button_col.addWidget(slew_btn)

            session_btn = QPushButton("Add to Session")
            session_btn.setToolTip("Create a new session pre-populated with a Target block for this "
                                   "object (SES-160).")
            session_btn.clicked.connect(lambda _=None, o=obj: _add_result_to_new_session(o))
            button_col.addWidget(session_btn)
            button_col.addStretch(1)

            # Size every button to fit its own text (a hardcoded fixed width previously clipped
            # "Add to Session", the longest label) — all three made uniform to the widest one's
            # actual sizeHint, not a guessed constant, so this stays correct across fonts/platforms.
            button_width = max(b.sizeHint().width() for b in (select_btn, slew_btn, session_btn))
            for b in (select_btn, slew_btn, session_btn):
                b.setFixedWidth(button_width)

            row.addLayout(button_col)

            return card, thumb_label

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

        catalog_checks: dict = {}
        catalog_row = QHBoxLayout()
        try:
            from galileo.planning.sky_atlas import DSO_CATALOGS
            for cat in DSO_CATALOGS:
                cb = QCheckBox(cat)
                catalog_checks[cat] = cb
                catalog_row.addWidget(cb)
        except ImportError:
            pass
        catalog_row_widget = QWidget()
        catalog_row_widget.setLayout(catalog_row)
        catalog_row_widget.setToolTip(
            "None checked = every catalog. Any checked = only objects belonging to at least one "
            "of them — the same Messier/Caldwell/NGC membership the Star Atlas's own catalog "
            "overlay toggles use."
        )
        form.addRow("Catalog", catalog_row_widget)

        max_mag = QDoubleSpinBox()
        max_mag.setRange(-5.0, 30.0)
        max_mag.setValue(99.0)
        form.addRow("Max magnitude", max_mag)

        min_size = QDoubleSpinBox()
        min_size.setRange(0.0, 500.0)
        min_size.setSuffix(" arcmin")
        form.addRow("Min size", min_size)

        max_size = QDoubleSpinBox()
        max_size.setRange(0.0, 500.0)
        max_size.setSuffix(" arcmin")
        max_size.setSpecialValueText("No max")
        form.addRow("Max size", max_size)

        visible_tonight_check = QCheckBox("Visible tonight")
        visible_tonight_check.setToolTip(
            "Needs the current Observatory's latitude/longitude set (top bar); ignored otherwise."
        )
        form.addRow(visible_tonight_check)

        min_altitude = QDoubleSpinBox()
        min_altitude.setRange(0.0, 90.0)
        min_altitude.setValue(20.0)
        min_altitude.setSuffix(" °")
        min_altitude.setToolTip("Only used when Visible tonight is checked (SKY-020).")
        form.addRow("Reach an altitude of", min_altitude)

        min_duration = QDoubleSpinBox()
        min_duration.setRange(0.0, 12.0)
        min_duration.setSuffix(" hr")
        min_duration.setSpecialValueText("Any moment")
        min_duration.setToolTip(
            "How long it must stay at/above that altitude, continuously — \"Any moment\" (0) just "
            "needs one moment tonight, matching the original Visible tonight check. Only used when "
            "Visible tonight is checked (SKY-020)."
        )
        form.addRow("...for at least", min_duration)

        min_moon_sep = QDoubleSpinBox()
        min_moon_sep.setRange(0.0, 180.0)
        min_moon_sep.setSuffix(" °")
        min_moon_sep.setSpecialValueText("No minimum")
        min_moon_sep.setToolTip(
            "Excludes anything closer to the Moon than this, at local midnight tonight (SKY-020) — "
            "needs the current Observatory's latitude/longitude set (top bar); ignored otherwise."
        )
        form.addRow("Min. Moon separation", min_moon_sep)

        search_btn = QPushButton("Search")
        search_btn.setObjectName("AccentButton")
        form.addRow(search_btn)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)

        heading = QLabel("Planning")
        heading.setObjectName("PageTitle")
        content_layout.addWidget(heading)

        results = QListWidget()
        results.setSpacing(4)
        results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content_layout.addWidget(results, 1)

        def _tile_row(card: QWidget) -> tuple[QWidget, object]:
            """Wrap *card* in a full-row container so results stay one
            per row (a plain vertical list, not a grid), while the visible
            tile itself is narrowed to ``_TILE_WIDTH_FRACTION`` of the
            results list's own width (floored at ``_TILE_MIN_WIDTH_PX`` so
            thumbnail/text/chart still fit at a narrow window) and left-
            aligned — a ``QListWidget`` row's item widget otherwise always
            stretches to the full viewport width regardless of the card's
            own size, so narrowing the card alone (without this wrapper)
            has no visible effect."""
            from PySide6.QtCore import QSize
            width = max(_TILE_MIN_WIDTH_PX, int(results.viewport().width() * _TILE_WIDTH_FRACTION))
            card.setFixedWidth(width)
            row_container = QWidget()
            row_layout = QHBoxLayout(row_container)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(card)
            row_layout.addStretch(1)
            return row_container, QSize(results.viewport().width(), card.sizeHint().height())

        def _current_location():
            """The active Observatory's location (top-bar selector), for
            visibility filtering and each card's altitude chart/rise-
            transit-set (SKY-020/SKY-030) — ``None`` when no Observatory is
            selected or it has no latitude/longitude configured yet."""
            obs = getattr(self, "_current_observatory", None)
            if obs is None or getattr(obs, "latitude", None) is None or getattr(obs, "longitude", None) is None:
                return None
            from galileo.planning.visibility import ObservingLocation
            return ObservingLocation(
                name=getattr(obs, "name", ""), latitude=obs.latitude, longitude=obs.longitude,
                timezone=getattr(obs, "timezone", None) or "UTC",
            )

        def _slew_to_result(obj) -> None:
            """"Slew To" (a result tile's own action button): immediately
            command the connected mount to this object, via the same
            ``_mount_to_object`` the Star Atlas/skymap's own slew-to-clicked-
            location uses (SKYMAP-060) — needs the current altitude (its
            below-horizon guard) computed fresh for *now*, the same
            precess-then-horizontal-transform technique
            ``galileo.ui.star_atlas``'s live renderer already uses."""
            location = _current_location()
            if location is None:
                self._window.statusBar().showMessage(
                    "Slew To needs the Observatory's latitude/longitude set (top bar).", 5000)
                return
            import datetime as _dt
            from galileo.planning import star_atlas as sa
            jd = sa.julian_date(_dt.datetime.now(_dt.UTC))
            lst = sa.local_sidereal_deg(jd, location.longitude)
            ra_of_date, dec_of_date = sa.precess_from_j2000(obj.ra_deg, obj.dec_deg, jd)
            alt, _az = sa.equatorial_to_horizontal(ra_of_date, dec_of_date, lst, location.latitude)
            target = obj.as_sequence_target()
            target["alt"] = float(alt)
            self._mount_to_object("goto", target)

        def _add_result_to_new_session(obj) -> None:
            """"Add to Session" (a result tile's own action button, SES-160) —
            goes through the shared :meth:`AppWindow._add_to_session`, the same
            entry point the Star Atlas's right-click context menu action uses,
            so the two never drift apart."""
            self._add_to_session(obj.primary_name, obj.ra_deg, obj.dec_deg)

        def run_search() -> None:
            import asyncio
            results.clear()
            self._window.statusBar().showMessage("Searching…")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            location = _current_location()
            try:
                from galileo.planning.sky_atlas import SkyAtlas, ObjectType
                atlas = SkyAtlas()
                name = name_edit.text().strip()
                if name:
                    matches = asyncio.run(atlas.search_online(name))
                else:
                    object_types = None
                    if type_combo.currentText() != "Any":
                        object_types = [ObjectType(type_combo.currentText())]
                    if (visible_tonight_check.isChecked() or min_moon_sep.value() > 0) and location is None:
                        self._window.statusBar().showMessage(
                            "Visible tonight/Moon separation need the Observatory's latitude/longitude "
                            "set (top bar) — showing all matches instead.", 6000)
                    selected_catalogs = {cat for cat, cb in catalog_checks.items() if cb.isChecked()} or None
                    matches = atlas.filter(
                        object_types=object_types,
                        max_magnitude=max_mag.value(),
                        min_size_arcmin=min_size.value(),
                        max_size_arcmin=max_size.value(),
                        location=location,
                        visible_tonight=visible_tonight_check.isChecked() and location is not None,
                        min_altitude_deg=min_altitude.value(),
                        min_duration_hours=min_duration.value(),
                        min_moon_separation_deg=min_moon_sep.value(),
                        catalogs=selected_catalogs,
                    )
            except Exception:
                logger.exception("Sky Atlas search failed")
                results.addItem("Search failed — see log for details.")
                self._window.statusBar().showMessage("Planning search failed — see log.", 6000)
                return
            finally:
                QApplication.restoreOverrideCursor()
            if not matches:
                results.addItem("No matching objects.")
                self._window.statusBar().showMessage("No matching objects.", 4000)
                return

            shown = matches[:200]

            # One batched astropy transform for every card's altitude chart,
            # not one per card (~1s for 200 vs. ~10s individually — see the
            # method docstring). rise/transit/set for each is then read off
            # its own already-computed chart, not recalculated.
            charts: list = [None] * len(shown)
            rise_set_texts = ["Set an Observatory location (top bar) for rise/transit/set."] * len(shown)
            if location is not None:
                self._window.statusBar().showMessage(f"Found {len(matches)} object(s) — computing altitude charts…")
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    charts = atlas.altitude_charts_batch(shown, location)
                    for i, (obj, chart) in enumerate(zip(shown, charts)):
                        if not chart.get("altitudes"):
                            rise_set_texts[i] = "Rise/transit/set unavailable."
                            continue
                        try:
                            rts = atlas.rise_transit_set(obj, location, chart=chart)
                            rise_set_texts[i] = (
                                f"Rise {_fmt_rise_set_time(rts['rise'])}  "
                                f"Transit {_fmt_rise_set_time(rts['transit'])}  "
                                f"Set {_fmt_rise_set_time(rts['set'])} UTC"
                            )
                        except Exception:
                            logger.debug("Could not compute rise/transit/set for %s", obj.primary_name, exc_info=True)
                            rise_set_texts[i] = "Rise/transit/set unavailable."
                except Exception:
                    logger.exception("Could not batch-compute altitude charts")
                    charts = [None] * len(shown)
                finally:
                    QApplication.restoreOverrideCursor()

            thumb_labels = []
            for obj, rise_set_text, chart in zip(shown, rise_set_texts, charts):
                item = QListWidgetItem()
                item.setData(Qt.UserRole, obj)
                card, thumb_label = _build_result_card(obj, rise_set_text, chart)
                row_container, size_hint = _tile_row(card)
                item.setSizeHint(size_hint)
                results.addItem(item)
                results.setItemWidget(item, row_container)
                thumb_labels.append(thumb_label)
            self._window.statusBar().showMessage(f"Found {len(matches)} object(s).", 4000)

            # Fill in the first few cards' thumbnails now (bounded — see
            # _MAX_AUTO_THUMBNAILS above, a real network request each); the
            # rest still show every other detail, just without an image.
            if thumb_labels:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    for obj, thumb_label in zip(shown[:_MAX_AUTO_THUMBNAILS], thumb_labels):
                        try:
                            data = asyncio.run(atlas._fetch_thumbnail(obj))
                        except Exception:
                            logger.debug("Could not fetch card thumbnail for %s", obj.primary_name, exc_info=True)
                            continue
                        pixmap = QPixmap()
                        if data and pixmap.loadFromData(data) and not pixmap.isNull():
                            thumb_label.setPixmap(pixmap.scaled(
                                _CARD_THUMB_PX, _CARD_THUMB_PX, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                            ))
                finally:
                    QApplication.restoreOverrideCursor()

        search_btn.clicked.connect(run_search)
        name_edit.returnPressed.connect(run_search)

        layout.addWidget(criteria)
        layout.addWidget(content, 1)
        return page

    # --- Framing Assistant (IMG-180, FRAME-070) ------------------------------
    #
    # Contextual only, per FRAME-070 — no primary-navigation section of its own.
    # This is the Imaging tab's own entry point; galileo.ui.sessions' Image
    # block gets its own, independent one (its own Framing… control is not yet
    # built — see TODO.md).

    def _imaging_optical_profile(self) -> dict:
        """Profile-shaped dict for ``FramingAssistant.from_profile()`` (FRAME-010,
        FRAME-030), built from the Imaging tab's own active optical train, camera,
        and rotator configuration — falls back to reference defaults wherever a
        piece of it isn't configured yet."""
        tube = self.active_optical_tube()
        pier = self._current_pier
        camera_cfg = rotator_cfg = None
        if pier is not None:
            from galileo.observatory import get_device_config
            try:
                camera_cfg = get_device_config(pier, "camera", slot=self._active_camera_slot)
            except Exception:
                logger.exception("Could not load the camera's configuration for Framing")
            try:
                rotator_cfg = get_device_config(pier, "rotator")
            except Exception:
                logger.exception("Could not load the rotator's configuration for Framing")
        camera = {}
        if camera_cfg is not None:
            camera = {key: value for key, value in {
                "sensor_width_px": camera_cfg.sensor_width_px,
                "sensor_height_px": camera_cfg.sensor_height_px,
                "pixel_size_um": camera_cfg.pixel_size_um,
            }.items() if value is not None}
        return {
            "piers": [{
                "optical_trains": [{
                    "focal_length_mm": getattr(tube, "focal_length_mm", None) or 1000,
                    "camera": camera,
                    "rotator": {"configured": True} if rotator_cfg is not None else {},
                }]
            }]
        }

    def _framing_dialog_initial_target(self) -> tuple[str, float, float] | None:
        """The Imaging tab's current object (IMG-140), if any — used to pre-fill the
        Framing Assistant dialog's Name/RA/Dec fields, so a target already picked
        on the Star Atlas doesn't need retyping into Framing's own fields too."""
        current = self.current_object()
        if current is None:
            return None
        return current.name, current.ra_deg, current.dec_deg

    def _open_framing_dialog(self, service) -> None:
        """Open the Framing Assistant against the Imaging tab's own optical train
        (IMG-180's Framing… control): compute the FOV, or define and run a mosaic
        grid directly from this tab (traces to FRAME-090). Shows the survey image
        for the target with the FOV/mosaic rectangle overlaid (FRAME-020/FRAME-040),
        redrawn immediately as rotation or the mosaic grid is adjusted.

        Rotation (FRAME-030) is always editable, regardless of whether a rotator
        is connected: with one connected, accepting the dialog moves it to the
        requested angle; with none connected, the requested tilt can't be achieved
        by the camera directly, so it's instead covered by an auto-sized mosaic of
        (un-rotated) panels — an explicit mosaic grid the user set themselves takes
        priority over that fallback.

        A "Show mosaic overlay" checkbox controls only what the canvas *draws* —
        the mosaic panel grid, or a single (possibly tilted) frame rectangle when
        unchecked — never what's actually captured on accept: an explicit or
        rotation-fallback mosaic is still used whenever one is needed, whether or
        not its panels are shown here."""
        import asyncio
        from PySide6.QtWidgets import (
            QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
            QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
        )
        from galileo.planning.framing import MosaicSettings

        assistant = service.open_framing_assistant(profile=self._imaging_optical_profile())
        rotator_state = self._device_pages.get("rotator") or {}
        rotator_adapter = rotator_state.get("adapter")
        rotator_connected = rotator_adapter is not None

        dialog = QDialog(self._window)
        dialog.setWindowTitle("Framing Assistant")
        outer = QHBoxLayout(dialog)

        left = QVBoxLayout()
        outer.addLayout(left)
        form = QFormLayout()
        left.addLayout(form)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Target name")
        form.addRow("Name", name_edit)

        ra_spin = QDoubleSpinBox()
        ra_spin.setRange(0.0, 360.0)
        ra_spin.setDecimals(4)
        ra_spin.setSuffix(" °")
        form.addRow("RA", ra_spin)

        dec_spin = QDoubleSpinBox()
        dec_spin.setRange(-90.0, 90.0)
        dec_spin.setDecimals(4)
        dec_spin.setSuffix(" °")
        form.addRow("Dec", dec_spin)

        initial_target = self._framing_dialog_initial_target()
        if initial_target is not None:
            name_edit.setText(initial_target[0])
            ra_spin.setValue(initial_target[1])
            dec_spin.setValue(initial_target[2])

        rotation_spin = QDoubleSpinBox()
        rotation_spin.setRange(0.0, 359.9)
        rotation_spin.setSuffix(" °")
        form.addRow("Rotation", rotation_spin)

        rotator_status = QLabel(
            "Rotator detected — OK will move it to this angle." if rotator_connected else
            "No rotator detected — rotation will be captured as a mosaic covering the tilted field."
        )
        rotator_status.setObjectName("StatusHint")
        rotator_status.setWordWrap(True)
        form.addRow(rotator_status)

        cols_spin = QSpinBox()
        cols_spin.setRange(1, 20)
        cols_spin.setValue(1)
        form.addRow("Mosaic cols", cols_spin)

        rows_spin = QSpinBox()
        rows_spin.setRange(1, 20)
        rows_spin.setValue(1)
        form.addRow("Mosaic rows", rows_spin)

        overlap_spin = QDoubleSpinBox()
        overlap_spin.setRange(0.0, 90.0)
        overlap_spin.setValue(MosaicSettings.instance().pane_overlap_pct)
        overlap_spin.setSuffix(" %")
        overlap_spin.setToolTip("Shared with the Session Image block's own Framing… control (FRAME-040).")
        form.addRow("Overlap", overlap_spin)

        show_mosaic_check = QCheckBox("Show mosaic overlay")
        show_mosaic_check.setChecked(True)
        show_mosaic_check.setToolTip(
            "Preview only — hides the mosaic panel grid on the image below, showing just a single "
            "(possibly tilted) frame rectangle instead. Doesn't change what's actually captured: a "
            "covering mosaic is still used whenever one is needed (an explicit grid, or rotating with "
            "no rotator connected) whether or not it's drawn here."
        )
        form.addRow(show_mosaic_check)

        load_image_btn = QPushButton("Load Sky Image")
        load_image_btn.setToolTip("Fetch a survey image for this RA/Dec (FRAME-020) — not refetched "
                                  "automatically as RA/Dec change, to avoid a network call per keystroke.")
        form.addRow(load_image_btn)

        fov_label = QLabel("")
        fov_label.setObjectName("StatusHint")
        fov_label.setWordWrap(True)
        left.addWidget(fov_label)

        canvas = _FramingCanvas()
        outer.addWidget(canvas, 1)

        def mosaic_grid() -> tuple | None:
            """The grid the user explicitly set, if any."""
            return ((cols_spin.value(), rows_spin.value(), overlap_spin.value())
                    if cols_spin.value() > 1 or rows_spin.value() > 1 else None)

        def effective_grid() -> tuple | None:
            """The grid actually in effect: the user's own explicit choice, else —
            with no rotator connected and a nonzero rotation — one auto-sized to
            cover the tilted frame's bounding box (FRAME-030's fallback), else
            ``None`` for a plain single frame."""
            explicit = mosaic_grid()
            if explicit is not None:
                return explicit
            if not rotator_connected and rotation_spin.value() != 0:
                bbox = assistant.rotated_frame_bounding_box_deg(rotation_spin.value())
                cols, rows = assistant.mosaic_grid_to_cover_deg(*bbox, overlap_spin.value())
                return cols, rows, overlap_spin.value()
            return None

        def refresh_overlay() -> None:
            fov = assistant.compute_fov()
            grid = effective_grid()
            auto_mosaic = grid is not None and mosaic_grid() is None
            if grid is not None:
                footprint = assistant.mosaic_footprint_deg(*grid)
                if auto_mosaic:
                    extra = (f"  —  no rotator: {grid[0]}×{grid[1]} mosaic covering the "
                             f"{rotation_spin.value():.0f}° tilted field")
                else:
                    extra = f"  —  mosaic footprint {footprint[0]:.3f}° × {footprint[1]:.3f}° ({grid[0]}×{grid[1]})"
                    if rotation_spin.value() != 0:
                        extra += "  (rotation ignored while a mosaic grid is set)"
            else:
                footprint = (fov.width_deg, fov.height_deg)
                extra = ""
            show_mosaic = show_mosaic_check.isChecked()
            if grid is not None and not show_mosaic:
                extra += "  (mosaic preview hidden — still captured)"
            display_grid = grid if show_mosaic else None
            pane_rotation = 0.0 if display_grid is not None else rotation_spin.value()
            reference_rotation = rotation_spin.value() if (auto_mosaic and show_mosaic) else None
            suffix = f" at rotation {rotation_spin.value():.1f}°" if pane_rotation or reference_rotation else ""
            fov_label.setText(f"Field of view: {fov.width_deg:.3f}° × {fov.height_deg:.3f}°{suffix}{extra}")
            canvas.set_overlay(fov.width_deg, fov.height_deg, pane_rotation, display_grid,
                               footprint_deg=footprint, reference_rotation_deg=reference_rotation)

        def load_sky_image() -> None:
            grid = effective_grid()
            footprint = assistant.mosaic_footprint_deg(*grid) if grid is not None else None
            extent = assistant.survey_cutout_extent_deg(*footprint) if footprint else assistant.survey_cutout_extent_deg()
            width_deg, height_deg = footprint or (None, None)
            try:
                data = assistant.fetch_survey_image_sync(ra_spin.value(), dec_spin.value(), width_deg, height_deg)
            except Exception:
                logger.exception("Framing Assistant survey-image fetch failed")
                data = b""
            canvas.set_image(data, extent)

        rotation_spin.valueChanged.connect(lambda _: refresh_overlay())
        cols_spin.valueChanged.connect(lambda _: refresh_overlay())
        rows_spin.valueChanged.connect(lambda _: refresh_overlay())
        overlap_spin.valueChanged.connect(lambda _: refresh_overlay())
        show_mosaic_check.toggled.connect(lambda _: refresh_overlay())
        load_image_btn.clicked.connect(load_sky_image)
        refresh_overlay()
        if initial_target is not None:
            load_sky_image()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        left.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            assistant.close()
            return

        MosaicSettings.instance().set_pane_overlap_pct(overlap_spin.value())
        assistant.set_target(ra=ra_spin.value(), dec=dec_spin.value(), name=name_edit.text())

        grid = effective_grid()
        auto_mosaic = grid is not None and mosaic_grid() is None
        if grid is None:
            # A previously active mosaic (from an earlier visit to this dialog) no longer applies
            # once the user dials the grid back down to a single frame — Capture must not keep
            # shooting the old mosaic silently.
            service.active_mosaic = None
        if grid is not None:
            cols, rows, overlap_pct = grid
            mosaic = assistant.create_mosaic(
                center_ra=ra_spin.value(), center_dec=dec_spin.value(),
                cols=cols, rows=rows, overlap_pct=overlap_pct,
            )
            assistant.set_mosaic(mosaic)
            service.run_mosaic_from_framing(assistant)
            if auto_mosaic:
                self._window.statusBar().showMessage(
                    f"No rotator: capturing a {cols}×{rows} mosaic to cover the "
                    f"{rotation_spin.value():.0f}° tilted field.", 6000)
            else:
                self._window.statusBar().showMessage(
                    f"Mosaic defined: {mosaic.total_panels} panels ({cols}×{rows}).", 5000)
        elif rotator_connected and rotation_spin.value() != 0:
            try:
                asyncio.run(rotator_adapter.move_to_angle(rotation_spin.value()))
                self._window.statusBar().showMessage(
                    f"Framing target set: {name_edit.text() or 'unnamed'}; rotator moved to "
                    f"{rotation_spin.value():.1f}°.", 5000)
            except Exception:
                logger.exception("Framing Assistant could not move the rotator")
                self._window.statusBar().showMessage(
                    "Framing target set, but the rotator move failed — see log.", 6000)
        else:
            self._window.statusBar().showMessage(
                f"Framing target set: {name_edit.text() or 'unnamed'}.", 4000)
        assistant.close()

    def _build_criteria_panel(self, heading: str):
        """A fixed-width form panel holding search/input criteria, used
        instead of a secondary icon column (Planning, Star Atlas)."""
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

    def _build_placeholder_page(self, title: str) -> QWidget:
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

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


class _CaptureThread(QThread if _HAS_QT else object):
    """Runs one manual capture (IMG-070) off the Qt UI thread, so the
    Imaging page's countdown/status display (IMG-090) keeps updating while
    the async expose/download call is in flight — the rest of this window
    calls device adapters with a blocking ``asyncio.run`` directly on the UI
    thread since those calls are quick (scan/connect/status), but a manual
    exposure can run for minutes and would otherwise freeze the whole app."""

    finished_ok = Signal() if _HAS_QT else None
    failed = Signal(str) if _HAS_QT else None
    frame_started = Signal(int, int) if _HAS_QT else None     # (frame number, frames in the series)
    frame_done = Signal(int, int) if _HAS_QT else None

    def __init__(self, service, quantity: int, duration: float, filter_name: str, frame_type: str,
                 parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._quantity = quantity
        self._duration = duration
        self._filter_name = filter_name
        self._frame_type = frame_type

    def run(self) -> None:
        import asyncio
        try:
            asyncio.run(self._service.capture_series(
                self._quantity, self._duration, self._filter_name, self._frame_type,
                on_frame_start=self.frame_started.emit, on_frame_done=self.frame_done.emit,
            ))
        except Exception as exc:
            if not self._service.stop_requested:
                self.failed.emit(str(exc))
                return
        self.finished_ok.emit()


class _MosaicCaptureThread(QThread if _HAS_QT else object):
    """Runs one mosaic capture (IMG-180, FRAME-090) off the Qt UI thread — mirrors
    ``_CaptureThread``, but drives ``ImagingService.capture_mosaic`` instead of
    ``capture_series``, since a mosaic's per-pane re-slews can each take as long as
    the exposures themselves and must not freeze the window either."""

    finished_ok = Signal() if _HAS_QT else None
    failed = Signal(str) if _HAS_QT else None
    slew_started = Signal(int, int) if _HAS_QT else None      # (step number, steps in the mosaic)
    frame_started = Signal(int, int) if _HAS_QT else None
    frame_done = Signal(int, int) if _HAS_QT else None

    def __init__(self, service, exposures_per_pane: int, duration: float, filter_name: str, frame_type: str,
                 parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._exposures_per_pane = exposures_per_pane
        self._duration = duration
        self._filter_name = filter_name
        self._frame_type = frame_type

    def run(self) -> None:
        import asyncio
        try:
            asyncio.run(self._service.capture_mosaic(
                self._exposures_per_pane, self._duration, self._filter_name, self._frame_type,
                on_slew_start=self.slew_started.emit,
                on_frame_start=self.frame_started.emit, on_frame_done=self.frame_done.emit,
            ))
        except Exception as exc:
            if not self._service.stop_requested:
                self.failed.emit(str(exc))
                return
        self.finished_ok.emit()


class _FilterMoveThread(QThread if _HAS_QT else object):
    """Moves the filter wheel to a slot off the Qt UI thread — a wheel can take
    several seconds to settle (INDI waits up to a minute), which would otherwise
    freeze the window the way a blocking ``asyncio.run`` on the UI thread does."""

    finished_ok = Signal() if _HAS_QT else None
    failed = Signal(str) if _HAS_QT else None

    def __init__(self, wheel, index: int, parent=None) -> None:
        super().__init__(parent)
        self._wheel = wheel
        self._index = index

    def run(self) -> None:
        import asyncio
        try:
            asyncio.run(self._wheel.move_to(self._index))
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit()


class _ResumeTrackingThread(QThread if _HAS_QT else object):
    """Waits for a slew to finish and then starts tracking at the target's rate (EQP-MNT-050).

    Off the Qt UI thread because the wait lasts as long as the slew does — minutes, for a mount
    crossing the sky — and the window must stay responsive throughout."""

    done = Signal(str) if _HAS_QT else None          # the rate set, or "" if the mount never settled
    failed = Signal(str) if _HAS_QT else None

    def __init__(self, mount, target=None, parent=None) -> None:
        super().__init__(parent)
        self._mount = mount
        self._target = target

    def run(self) -> None:
        import asyncio
        from galileo.tracking import resume_tracking
        try:
            rate = asyncio.run(resume_tracking(self._mount, self._target))
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(rate or "")


class _MountPositionThread(QThread if _HAS_QT else object):
    """Reads one mount's position off the Qt UI thread, for the Star Atlas telescope reticles
    (SKYMAP-090). A mount that can't be read reports nothing rather than failing: the reticle is
    a convenience, and a slow or absent mount must not stall the sky view."""

    position = Signal(object) if _HAS_QT else None      # the mount's status dict, or None

    def __init__(self, mount, parent=None) -> None:
        super().__init__(parent)
        self._mount = mount

    def run(self) -> None:
        import asyncio
        try:
            status = asyncio.run(self._mount.get_status()) or {}
        except Exception:
            logger.debug("Could not read the mount position for the Star Atlas", exc_info=True)
            status = None
        self.position.emit(status)


class _NudgeThread(QThread if _HAS_QT else object):
    """Runs one mount nudge (IMG-130) off the Qt UI thread: the mount moves for
    the nudge's duration, and blocking the UI for that long would freeze the
    Imaging page's exposure countdown while the user is watching it."""

    finished_ok = Signal() if _HAS_QT else None
    failed = Signal(str) if _HAS_QT else None

    def __init__(self, mount, direction: str, rate: float, duration: float,
                 reversed_axes: tuple, parent=None) -> None:
        super().__init__(parent)
        self._args = (mount, direction, rate, duration, reversed_axes)

    def run(self) -> None:
        import asyncio
        from galileo.ui.imaging import nudge_mount
        try:
            asyncio.run(nudge_mount(*self._args))
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit()


class _ThumbnailCacheThread(QThread if _HAS_QT else object):
    """Bulk-caches every catalog object's survey-image thumbnail off the Qt UI
    thread (Options > Planning's "Cache all thumbnails" button, SKY-080), so a
    later search's result-tile thumbnails load from disk instead of each
    needing its own hips2fits round trip. Reuses ``SkyAtlas._fetch_thumbnail``'s
    own ra/dec/field-size-keyed disk cache unchanged — an object already cached
    (from a prior run, from having shown up in a search's result tiles, or from
    being added to a target list) returns instantly with no network call, so
    resuming after Cancel, or re-running later, only fetches what's still
    missing. Runs one object at a time, sequentially, matching every other
    thumbnail fetch already in this codebase — no added concurrency, so this
    doesn't hit the free hips2fits service any harder than normal use already
    does; for the full catalog (tens of thousands of objects) that means this
    can genuinely take hours, which is why it's cancellable and why the
    confirmation dialog before starting says so."""

    progress = Signal(int, int) if _HAS_QT else None        # (done, total)
    finished_ok = Signal(int, int) if _HAS_QT else None      # (cached, failed)
    failed = Signal(str) if _HAS_QT else None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        import asyncio
        try:
            from galileo.planning.sky_atlas import SkyAtlas
            atlas = SkyAtlas()
            catalog = atlas._catalog
            total = len(catalog)
            cached_count = 0
            failed_count = 0
            for i, obj in enumerate(catalog):
                if self._stop_requested:
                    break
                try:
                    data = asyncio.run(atlas._fetch_thumbnail(obj))
                except Exception:
                    data = b""
                if data:
                    cached_count += 1
                else:
                    failed_count += 1
                if i % 5 == 0 or i == total - 1:
                    self.progress.emit(i + 1, total)
        except Exception as exc:
            logger.exception("Bulk thumbnail caching failed")
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(cached_count, failed_count)


class _FramingCanvas(QWidget if _HAS_QT else object):
    """Survey image with the FOV rectangle — and, where a mosaic grid is defined,
    every pane's rectangle — overlaid (FRAME-020/030/040), redrawn live as the
    Framing Assistant dialog's fields change. The image itself only needs
    refetching for a new sky position (``set_image``); rotation/mosaic changes
    just move the overlay (``set_overlay``), no new fetch needed. RA offsets are
    drawn increasing to the left (conventional sky orientation) and rotation's
    on-screen sense hasn't been validated against a real rotator, matching this
    codebase's existing caveat for ``galileo.derotation``.

    A survey cutout is capped at a sanity ceiling
    (``galileo.planning.framing._MAX_HIPS_FOV_DEG``), which can be smaller
    than the FOV or mosaic footprint it's meant to frame (a wide-field optical
    train, or a large mosaic grid). Rather than clip the overlay to the image or
    stretch the image to the overlay, the canvas fits *whichever is larger* —
    image extent or overlay footprint — into the visible area, so the FOV/mosaic
    rectangle's true size always stays fully visible, with the actual survey
    pixels shown at their real relative size and a dashed border marking where
    they end."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 360)
        self._pixmap = None
        self._image_extent_deg: tuple = (0.0, 0.0)
        self._fov_deg: tuple = (0.0, 0.0)
        self._footprint_deg: tuple = (0.0, 0.0)  # overlay's own overall extent (>= _fov_deg for a mosaic)
        self._rotation_deg: float = 0.0
        self._mosaic_grid: tuple | None = None  # (cols, rows, overlap_pct)
        self._reference_rotation_deg: float | None = None
        self._message = "Set a target and click Load Sky Image."

    def set_image(self, data: bytes, extent_deg: tuple) -> None:
        from PySide6.QtGui import QPixmap
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            self._pixmap = pixmap
            self._image_extent_deg = extent_deg
        else:
            self._pixmap = None
            self._message = "No sky image available (offline, or the fetch failed)."
        self.update()

    def set_overlay(self, fov_width_deg: float, fov_height_deg: float, rotation_deg: float,
                    mosaic_grid: tuple | None = None, footprint_deg: tuple | None = None,
                    reference_rotation_deg: float | None = None) -> None:
        """*rotation_deg* is what the drawn pane(s) are actually rotated by (0 for
        an auto-mosaic covering a tilt no rotator can achieve); *reference_rotation_deg*,
        when given, additionally draws the originally-requested tilted single-frame
        rectangle as a thin dashed outline for context, without affecting the panes."""
        self._fov_deg = (fov_width_deg, fov_height_deg)
        self._rotation_deg = rotation_deg
        self._mosaic_grid = mosaic_grid
        self._footprint_deg = footprint_deg or (fov_width_deg, fov_height_deg)
        self._reference_rotation_deg = reference_rotation_deg
        self.update()

    def paintEvent(self, event) -> None:
        from PySide6.QtCore import QRectF, Qt as _Qt
        from PySide6.QtGui import QColor, QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1a1a1a"))

        if self._pixmap is None:
            painter.setPen(QColor("#cccccc"))
            painter.drawText(self.rect(), _Qt.AlignCenter | _Qt.TextWordWrap, self._message)
            painter.end()
            return

        ext_w_deg, ext_h_deg = self._image_extent_deg
        fov_w_deg, fov_h_deg = self._fov_deg
        fp_w_deg, fp_h_deg = self._footprint_deg
        if ext_w_deg <= 0 or ext_h_deg <= 0 or fov_w_deg <= 0 or fov_h_deg <= 0:
            painter.end()
            return

        # Fit whichever is larger per axis — the fetched image, or the overlay's
        # own footprint — with a little margin so the border/rectangle isn't
        # flush against the widget's edge (FRAME-020/040: the field must stay
        # fully visible even when the survey source couldn't cover all of it).
        target = self.rect().adjusted(4, 4, -4, -4)
        world_w_deg = max(ext_w_deg, fp_w_deg) * 1.1
        world_h_deg = max(ext_h_deg, fp_h_deg) * 1.1
        px_per_deg_x = target.width() / world_w_deg
        px_per_deg_y = target.height() / world_h_deg

        img_w_px = max(1, round(ext_w_deg * px_per_deg_x))
        img_h_px = max(1, round(ext_h_deg * px_per_deg_y))
        scaled = self._pixmap.scaled(img_w_px, img_h_px, _Qt.IgnoreAspectRatio, _Qt.SmoothTransformation)
        origin_x = target.x() + (target.width() - scaled.width()) / 2
        origin_y = target.y() + (target.height() - scaled.height()) / 2
        painter.drawPixmap(int(origin_x), int(origin_y), scaled)

        if scaled.width() < target.width() - 1 or scaled.height() < target.height() - 1:
            # The field extends beyond what the survey cutout covers — mark
            # where the actual image data ends, so that's not mistaken for the
            # edge of the field itself.
            border_pen = QPen(QColor("#666666"), 1, _Qt.DashLine)
            painter.setPen(border_pen)
            painter.drawRect(QRectF(origin_x, origin_y, scaled.width(), scaled.height()))

        cx = origin_x + scaled.width() / 2
        cy = origin_y + scaled.height() / 2

        painter.setPen(QPen(QColor("#4da6ff"), 2))

        def draw_rect(offset_ra_deg: float, offset_dec_deg: float, rotation_deg: float) -> None:
            painter.save()
            painter.translate(cx - offset_ra_deg * px_per_deg_x, cy - offset_dec_deg * px_per_deg_y)
            painter.rotate(rotation_deg)
            painter.drawRect(QRectF(
                -fov_w_deg * px_per_deg_x / 2, -fov_h_deg * px_per_deg_y / 2,
                fov_w_deg * px_per_deg_x, fov_h_deg * px_per_deg_y,
            ))
            painter.restore()

        if self._mosaic_grid is not None:
            cols, rows, overlap_pct = self._mosaic_grid
            step_ra = fov_w_deg * (1.0 - overlap_pct / 100.0)
            step_dec = fov_h_deg * (1.0 - overlap_pct / 100.0)
            for row in range(rows):
                for col in range(cols):
                    draw_rect((col - (cols - 1) / 2.0) * step_ra, (row - (rows - 1) / 2.0) * step_dec,
                             self._rotation_deg)
        else:
            draw_rect(0.0, 0.0, self._rotation_deg)

        if self._reference_rotation_deg is not None:
            # The originally-requested tilted frame no rotator can achieve directly
            # — shown for context against the covering mosaic drawn above, not
            # itself a pane that will be captured.
            painter.setPen(QPen(QColor("#ffa64d"), 1, _Qt.DashLine))
            draw_rect(0.0, 0.0, self._reference_rotation_deg)
        painter.end()


class _ClickableThumbnail(QLabel if _HAS_QT else object):
    """A ``QLabel`` that emits ``clicked`` on a left-button press — used for
    the Targets page's result-tile thumbnails (SKY-080), so clicking one opens
    a full-size view (`AppWindow._show_full_image`) rather than the small
    result-tile crop being the only size ever shown."""

    clicked = Signal() if _HAS_QT else None

    def mousePressEvent(self, event) -> None:
        from PySide6.QtCore import Qt as _Qt
        if event.button() == _Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _HistogramWidget(QWidget if _HAS_QT else object):
    """Bar-chart rendering of the current frame's histogram (IMG-030), on a
    log scale so low-population bins stay visible next to a saturated peak."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._counts: list = []
        self._color = None

    def set_data(self, counts) -> None:
        self._counts = list(counts or [])
        self.update()

    def set_color(self, color) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        from PySide6.QtGui import QPainter, QColor
        from PySide6.QtCore import Qt as _Qt
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1a1a1a"))
        if self._counts:
            import math
            painter.setPen(_Qt.NoPen)
            painter.setBrush(QColor(self._color or "#4da3ff"))
            w, h = self.width(), self.height()
            n = len(self._counts)
            max_count = max(self._counts) or 1
            bar_w = w / n
            for i, count in enumerate(self._counts):
                bar_h = (math.log1p(count) / math.log1p(max_count)) * h if count else 0
                painter.drawRect(int(i * bar_w), int(h - bar_h), max(1, math.ceil(bar_w)), int(bar_h))
        painter.end()


class _LogPane(QPlainTextEdit if _HAS_QT else object):
    """A read-only QPlainTextEdit that ignores Ctrl+Wheel text-zoom.

    A fixed-height log tail has no use for interactive font zoom, and Qt's
    built-in zoom (QWidgetTextControl::zoomIn/zoomOut) does arithmetic on
    QFont::pointSize() — which can be -1 for the system fixed-width font on
    some Windows configurations, since a system font may be defined only by
    pixel size — and can end up calling QFont::setPointSize() with a
    non-positive result, printing "QFont::setPointSize: Point size <= 0" to
    the console. Ignoring Ctrl+Wheel here (regular scroll still works)
    avoids that regardless of the underlying font's point-size validity.
    """

    def wheelEvent(self, event) -> None:
        from PySide6.QtCore import Qt
        if event.modifiers() & Qt.ControlModifier:
            event.ignore()
            return
        super().wheelEvent(event)


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
        utility_actions: list[tuple[str, str, object]] | None = None,
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

        self._icon_entries: list[tuple[QToolButton, str]] = []

        group = QButtonGroup(self)
        group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}

        def _set_icon_pair(btn, icon_name: str, size: int) -> None:
            btn.setIconSize(QSize(size, size))
            btn._icon_dim = make_icon(icon_name, dim_color, size)
            btn._icon_accent = make_icon(icon_name, accent, size)
            btn.setIcon(btn._icon_accent if btn.isChecked() else btn._icon_dim)
            self._icon_entries.append((btn, icon_name))

        def add_button(section_id: str, label: str, icon_name: str) -> QToolButton:
            btn = QToolButton()
            btn.setObjectName(button_object_name)
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setMinimumHeight(button_min_height)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setText(label)
            # QToolButton never wraps its own text, so a label wider than the
            # column (e.g. "Variable Stars", "Safety Monitor") is clipped with an
            # ellipsis. Break it onto one line per word instead, but only when it
            # actually overflows, judged with the real stylesheet font/padding.
            btn.ensurePolished()
            if " " in label and btn.sizeHint().width() > self.width():
                btn.setText(label.replace(" ", "\n"))
            _set_icon_pair(btn, icon_name, icon_size)
            btn.toggled.connect(lambda checked, b=btn: b.setIcon(b._icon_accent if checked else b._icon_dim))
            btn.clicked.connect(lambda _checked=False, sid=section_id: on_select(sid))
            group.addButton(btn)
            layout.addWidget(btn)
            self._buttons[section_id] = btn
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
            # Span the full column like every other nav button, so the icon and
            # label are centred rather than shrink-wrapped against the left edge.
            power_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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

    def select(self, item_id: str) -> None:
        """Select *item_id* as if its button had been clicked."""
        self._buttons[item_id].click()

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
    def _first_button(group: QButtonGroup):
        buttons = group.buttons()
        return buttons[0] if buttons else None
