# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Main application window (PySide6).

A sidebar-driven shell: a primary icon sidebar on the left selects the
active section; the Equipment section additionally shows a context-sensitive
secondary icon sidebar for the device category (Camera, Mount, ...); the
remaining space is the content panel for whatever is selected. Thin shell
only — it wires the domain services to the UI panels, it does not contain
domain logic itself.

``AppWindow`` itself is assembled from a set of per-area mixins (one module
each, named after the page/section it builds) rather than being one single
class — the previous single-file, single-class version of this module grew
to nearly 8,000 lines and mixed window chrome, every device-category dialog,
and Pier/Observatory CRUD in one place, which made it a disproportionate
share of this codebase's mypy findings and hard to navigate. Splitting along
the module's own pre-existing section comments keeps every method exactly
where it was, in a file scoped to the one page/concern it builds.
"""

from __future__ import annotations

from ._common import (
    EQUIPMENT_CATEGORIES,
    LIBRARY_ITEMS,
    OPTIONS_ITEMS,
    OPTIONS_SECTION,
    PLANNING_ITEMS,
    PRIMARY_SECTIONS,
    SCIENCE_ITEMS,
    _CATEGORY_ENUM,
    _camera_backend_key_for_slot,
    _camera_slot_label,
    _device_association_label,
    _format_dms,
    _format_hms,
    _optical_tube_label,
    _parse_alpaca_device_number,
)
from ._widgets import _ClickableThumbnail
from ._core import AppWindowCoreMixin
from ._current_object import AppWindowCurrentObjectMixin
from ._observatory_pier import AppWindowObservatoryPierMixin
from ._topbar_optics_camera import AppWindowTopbarOpticsCameraMixin
from ._library_equipment import AppWindowLibraryEquipmentMixin
from ._camera_page import AppWindowCameraPageMixin
from ._focuser_page import AppWindowFocuserPageMixin
from ._mount_page import AppWindowMountPageMixin
from ._rotator_page import AppWindowRotatorPageMixin
from ._filter_wheel_page import AppWindowFilterWheelPageMixin
from ._optics_page import AppWindowOpticsPageMixin
from ._misc_device_pages import AppWindowMiscDevicePagesMixin
from ._device_config_page import AppWindowDeviceConfigMixin
from ._imaging_support import AppWindowImagingSupportMixin
from ._imaging_page import AppWindowImagingPageMixin
from ._star_atlas_page import AppWindowStarAtlasPageMixin
from ._settings_pages import AppWindowSettingsPagesMixin
from ._planning_page import AppWindowPlanningPageMixin
from ._framing import AppWindowFramingMixin

# Re-exported for other galileo.ui modules and tests that import them
# straight off galileo.ui.app_window, as they did before this split.
__all__ = [
    "EQUIPMENT_CATEGORIES",
    "LIBRARY_ITEMS",
    "OPTIONS_ITEMS",
    "OPTIONS_SECTION",
    "PLANNING_ITEMS",
    "PRIMARY_SECTIONS",
    "SCIENCE_ITEMS",
    "_CATEGORY_ENUM",
    "AppWindow",
    "_ClickableThumbnail",
    "_camera_backend_key_for_slot",
    "_camera_slot_label",
    "_device_association_label",
    "_format_dms",
    "_format_hms",
    "_optical_tube_label",
    "_parse_alpaca_device_number",
]


class AppWindow(
    AppWindowCoreMixin,
    AppWindowCurrentObjectMixin,
    AppWindowObservatoryPierMixin,
    AppWindowTopbarOpticsCameraMixin,
    AppWindowLibraryEquipmentMixin,
    AppWindowCameraPageMixin,
    AppWindowFocuserPageMixin,
    AppWindowMountPageMixin,
    AppWindowRotatorPageMixin,
    AppWindowFilterWheelPageMixin,
    AppWindowOpticsPageMixin,
    AppWindowMiscDevicePagesMixin,
    AppWindowDeviceConfigMixin,
    AppWindowImagingSupportMixin,
    AppWindowImagingPageMixin,
    AppWindowStarAtlasPageMixin,
    AppWindowSettingsPagesMixin,
    AppWindowPlanningPageMixin,
    AppWindowFramingMixin,
):
    """Main Galileo application window."""
