# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Portrait / landscape page layout shared by the Focus and Solve screens (the Imaging screen's
IMG-120 facility).

By default a page lays itself out for the shape of the frame it is showing: a portrait frame gets
a full-height column about a third of the page wide, with everything else beside it. Ticking
"Choose layout manually" lets the user pick instead. The page supplies the function that actually
rearranges its widgets; this module holds the decision and the two controls.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QWidget

from galileo.ui.imaging import LANDSCAPE, PORTRAIT, frame_orientation

_UNLIMITED_WIDTH = 16777215   # QWIDGETSIZE_MAX


class FrameLayoutChoice:
    """The orientation a page should use, and the "View" box that overrides it."""

    def __init__(self, page: QWidget, image_column: QWidget, apply: Callable[[str], None]) -> None:
        self._apply = apply
        self.detected = LANDSCAPE
        self._applied: str | None = None
        self.group = QGroupBox("View")
        form = QFormLayout(self.group)
        self.check = QCheckBox("Choose layout manually")
        self.check.setToolTip(
            "By default the page lays itself out for the shape of the frame: a portrait frame gets "
            "a full-height column on the right. Tick this to pick the layout yourself."
        )
        form.addRow(self.check)
        self.combo = QComboBox()
        self.combo.addItem("Landscape", LANDSCAPE)
        self.combo.addItem("Portrait", PORTRAIT)
        self.combo.setEnabled(False)
        form.addRow("Layout", self.combo)
        self.check.toggled.connect(self._manual_toggled)
        self.combo.currentIndexChanged.connect(lambda _i: self.refresh())
        self._page, self._image_column = page, image_column

    @property
    def orientation(self) -> str:
        return str(self.combo.currentData()) if self.check.isChecked() else self.detected

    def _manual_toggled(self, checked: bool) -> None:
        self.combo.setEnabled(checked)
        self.refresh()

    def set_frame(self, data) -> None:
        """Follow the shape of *data* (an image array); ``None`` leaves the layout as it is."""
        if data is None:
            return
        self.detected = frame_orientation(data)
        self.refresh()

    def refresh(self) -> None:
        orientation = self.orientation
        if orientation != self._applied:
            self._applied = orientation
            self._apply(orientation)
        self.fit_width()

    def fit_width(self) -> None:
        """Portrait: the image column is a third of the page's width. The page calls this from its
        ``resizeEvent``; it is also run after every layout change."""
        if self.orientation == PORTRAIT:
            self._image_column.setFixedWidth(max(1, self._page.width() // 3))
        else:
            self._image_column.setMinimumWidth(0)
            self._image_column.setMaximumWidth(_UNLIMITED_WIDTH)
