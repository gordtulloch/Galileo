# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Library section's own submenu/settings pages and the Equipment section's device-category submenu, plus the shared recent-log pane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import EQUIPMENT_CATEGORIES, OPTIONS_SECTION, LIBRARY_ITEMS, QWidget, QPlainTextEdit
from ._widgets import _LogPane, _NavColumn

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowLibraryEquipmentMixin:
    def _build_library_page(self: AppWindowState) -> QWidget:
        """Library section: Images, Sessions, Mappings, Dedup and Cloud — see
        ``galileo.ui.library.pages``. The screens read the whole catalog, so
        they are only built when the section is first opened."""
        from galileo.ui.library.pages import LibraryScreens

        screens = LibraryScreens(on_configure=self._open_library_settings)
        self._library_screens = screens
        return self._build_submenu_page(
            LIBRARY_ITEMS, {item_id: (lambda item_id=item_id: screens.page(item_id)) for item_id, _l, _i in LIBRARY_ITEMS})

    def _build_library_settings_page(self: AppWindowState) -> QWidget:
        """Options > Library: repository folders, cloud, compression, telescope
        credentials and the rest of ``library.ini`` — see
        ``galileo.ui.library.config_widget``."""
        from galileo.ui.library.config_widget import ConfigWidget
        return ConfigWidget()

    def _open_library_settings(self: AppWindowState) -> None:
        """Jump to Options > Library (e.g. from the Cloud page's Configure button)."""
        self._primary_nav.select(OPTIONS_SECTION[0])
        self._options_page._secondary_nav.select("library")

    def _build_equipment_page(self: AppWindowState) -> QWidget:
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

    def _build_log_pane(self: AppWindowState) -> QPlainTextEdit:
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

    def _refresh_log_panes(self: AppWindowState) -> None:
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
