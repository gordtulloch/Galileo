# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Library section's pages: Images, Sessions, Mappings, Dedup and Cloud.

The five screens share state (Images refreshes after a Merge or a Mappings
change, and asks Sessions to regenerate after an import), so they are built
together, once, the first time any of them is shown — opening Galileo on
another section doesn't pay for reading the whole catalog.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtWidgets import QVBoxLayout, QWidget

logger = logging.getLogger(__name__)


class LibraryScreens:
    """Builds the Library screens together on first use and hands out a page per menu item."""

    def __init__(self, on_configure: Callable[[], None] | None = None) -> None:
        """*on_configure* opens Options > Library (the Cloud page's "Configure..." button)."""
        self._on_configure = on_configure
        self._pages: dict[str, QWidget] | None = None
        self.images = None
        self.sessions = None
        self.mappings = None
        self.duplicates = None
        self.merge = None
        self.cloud = None

    def page(self, item_id: str) -> QWidget:
        """A placeholder for *item_id* that fills in with the real screen when first shown."""
        return _LazyPage(self, item_id)

    def widget(self, item_id: str) -> QWidget:
        """The real screen for *item_id*, building all of them if this is the first call."""
        self._build()
        assert self._pages is not None
        return self._pages[item_id]

    def _build(self) -> None:
        if self._pages is not None:
            return
        from galileo.ui.library.cloud_sync_dialog import CloudSyncWidget
        from galileo.ui.library.duplicates_widget import DuplicatesWidget
        from galileo.ui.library.images_widget import ImagesWidget
        from galileo.ui.library.mappings_dialog import MappingsWidget
        from galileo.ui.library.merge_widget import MergeWidget
        from galileo.ui.library.sessions_widget import SessionsWidget

        self.images = ImagesWidget()
        self.sessions = SessionsWidget()
        self.mappings = MappingsWidget()
        self.duplicates = DuplicatesWidget()
        self.merge = MergeWidget()
        self.cloud = CloudSyncWidget()

        self.images.sessions_widget = self.sessions
        self.merge.set_images_widget(self.images)
        self.mappings.mappings_applied.connect(self.images.load_fits_data)
        if self._on_configure is not None:
            self.cloud.configure_requested.connect(self._on_configure)

        self._pages = {
            "images": self.images,
            "sessions": self.sessions,
            "mappings": self.mappings,
            "dedup": self.duplicates,
            "merge": self.merge,
            "cloud": self.cloud,
        }
        logger.debug("Library screens built")


class _LazyPage(QWidget):
    """An empty page that adopts its real screen the first time it is shown."""

    def __init__(self, screens: LibraryScreens, item_id: str) -> None:
        super().__init__()
        self._screens = screens
        self._item_id = item_id
        self._filled = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

    def showEvent(self, event) -> None:
        if not self._filled:
            self._filled = True
            self.layout().addWidget(self._screens.widget(self._item_id))
        super().showEvent(event)
