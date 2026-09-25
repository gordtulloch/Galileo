# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Constants and small helper functions shared by app_window's mixin modules: the optional PySide6 imports (``_HAS_QT``), the primary/secondary nav menu definitions, per-driver defaults, and the handful of pure functions (label/format helpers) several pages use."""

from __future__ import annotations

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
    from PySide6.QtWidgets import QLabel, QPlainTextEdit, QWidget
    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    QThread = Signal = QLabel = QPlainTextEdit = QWidget = None  # type: ignore[assignment,misc]

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
