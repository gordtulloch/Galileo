# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Window shell: construction, top bar container, primary nav sidebar, menu actions, and the generic submenu/placeholder page builders."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ._common import _NEW_OBSERVATORY_LABEL, _MANUAL_URL, PRIMARY_SECTIONS, OPTIONS_ITEMS, OPTIONS_SECTION, PLANNING_ITEMS, SCIENCE_ITEMS, _HAS_QT, QWidget
from ._widgets import _NavColumn

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState
    from galileo.planning.sky_atlas import SkyAtlas
    from ._threads import _ThumbnailCacheThread


class AppWindowCoreMixin:
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
        # Camera connections, keyed by Pier so two Piers can each have their own
        # connected (and possibly capturing) camera at once — see _camera_backends
        # property below. Slot label ("primary camera", "camera 2", ...) -> adapter,
        # per Pier key.
        self._camera_backends_by_pier: dict = {}
        # Per-Pier ImagingService instances and their in-flight capture threads —
        # see _imaging_page.py's _current_service()/_current_capture_thread(). One
        # ImagingService per Pier so two Piers can capture at once without their
        # mutable state (stop_requested, library_ids, current_frame, ...) colliding.
        self._imaging_services: dict = {}
        self._imaging_capture_threads: dict = {}
        self._imaging_filter_threads: dict = {}
        self._thumbnail_cache_worker: _ThumbnailCacheThread | None = None
        # A single persistent SkyAtlas instance, lazily created — see _shared_sky_atlas().
        self._sky_atlas: SkyAtlas | None = None
        # Where each Pier's telescope is pointing, for the Star Atlas reticles (SKYMAP-090):
        # {pier key: {"ra_deg", "dec_deg", "slewing"}}, refreshed by polling the connected mount.
        self._pier_pointing: dict = {}
        self._pier_poll_threads: dict = {}
        self._tracking_threads: dict = {}     # per-Pier: waits for a slew to end, then starts tracking (EQP-MNT-050)
        self._current_primary_section = "equipment"
        self._active_camera_slot: str = "primary"
        self._active_optics_position: int = 0

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

        outer.addWidget(cast("AppWindowState", self)._build_top_bar())

        body = QWidget()
        root = QHBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._primary_stack, primary_sidebar = cast("AppWindowState", self)._build_primary_nav()
        self._primary_nav = primary_sidebar
        cast("AppWindowState", self)._apply_horizon()     # the top bar picked the Observatory before the pages existed
        root.addWidget(primary_sidebar)
        root.addWidget(self._primary_stack, 1)
        outer.addWidget(body, 1)

        self._window.setCentralWidget(central)

        self._theme.set_theme(self._theme.current_theme)  # applies the stylesheet

    @property
    def _camera_backends(self: AppWindowState) -> dict:
        """The currently-selected Pier's own camera-adapter dict (slot label ->
        adapter), created on first use. Every reader/writer elsewhere just treats
        this as "the" dict, but each Pier gets its own — so connecting Pier B's
        camera never disturbs Pier A's, and switching back to a Pier with a live
        (possibly capturing) camera finds it exactly as it left it."""
        from galileo.current_object import pier_key
        return self._camera_backends_by_pier.setdefault(pier_key(self._current_pier), {})

    @property
    def _imaging_service(self: AppWindowState):
        """The currently-selected Pier's own ImagingService, created (with no
        camera set yet) on first use — so this is always available, including
        for a Pier selected by setting self._current_pier directly rather than
        through a full Pier switch. The real per-Pier storage is
        self._imaging_services; see _imaging_page.py's _current_service(), which
        also fills in the currently selected camera backend when it creates one
        during page-build or a real Pier switch."""
        from galileo.current_object import pier_key
        from galileo.ui.imaging import ImagingService
        key = pier_key(self._current_pier)
        svc = self._imaging_services.get(key)
        if svc is None:
            svc = self._imaging_services[key] = ImagingService()
        return svc

    def show(self: AppWindowState) -> None:
        if _HAS_QT and hasattr(self, "_window"):
            self._window.showMaximized()

    def _build_top_bar(self: AppWindowState) -> QWidget:
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

    def _build_primary_nav(self: AppWindowState):
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

    def _request_quit(self: AppWindowState) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _toggle_theme(self: AppWindowState) -> None:
        from galileo.ui.theme import Theme
        new_theme = Theme.LIGHT if self._theme.current_theme == Theme.DARK else Theme.DARK
        self._theme.set_theme(new_theme)
        p = self._theme.palette()
        for column in self._nav_columns:
            column.refresh_icons(dim_color=p["text_dim"], accent=self._theme.accent_color)

    def _open_manual(self: AppWindowState) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(_MANUAL_URL))

    def _show_about(self: AppWindowState) -> None:
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

    def _build_submenu_page(self: AppWindowState, items: list, builders: dict) -> QWidget:
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

    def _build_placeholder_page(self: AppWindowState, title: str) -> QWidget:
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
