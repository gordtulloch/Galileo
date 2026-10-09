# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Shared pan/zoom image-preview widget and its Fit/1:1/+/− toolbar.

Used by the Solve, Imaging, Guiding and Focus screens so the same frame
view behaves — and is driven — the same way everywhere: fits the window
until the user zooms, drag to pan, with a small toolbar of Fit/1:1/+/−
buttons in the top-right corner of the preview.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
)


class ImagePreviewView(QGraphicsView):
    """A frame preview: fits the window until the user zooms; drag to pan."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self.setScene(self._scene)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.setMinimumHeight(200)
        self.fit = True
        self.has_image = False

    def show_array(self, array: np.ndarray) -> None:
        arr = np.ascontiguousarray(array)
        h, w = arr.shape[:2]
        if arr.ndim == 3:
            image = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        else:
            image = QImage(arr.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
        self._item.setPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(0, 0, w, h)
        self.has_image = True
        if self.fit:
            self.fit_to_window()

    def clear_image(self) -> None:
        self._item.setPixmap(QPixmap())
        self.has_image = False

    def fit_to_window(self) -> None:
        self.fit = True
        if self.has_image:
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self) -> None:
        self.fit = False
        self.resetTransform()

    def zoom(self, factor: float) -> None:
        self.fit = False
        self.scale(factor, factor)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.fit:
            self.fit_to_window()


def build_zoom_toolbar(image_view: ImagePreviewView, label: QLabel | None = None) -> QHBoxLayout:
    """A row for the top-right corner of a preview: *label* (if given, stretched
    to the left) followed by Fit / 1:1 / + / − buttons wired to *image_view*."""
    row = QHBoxLayout()
    row.setSpacing(4)
    if label is not None:
        row.addWidget(label, 1)
    else:
        row.addStretch(1)
    for text, tip, slot in (
        ("Fit", "Fit the whole frame in the window.", image_view.fit_to_window),
        ("1:1", "Show the frame at actual size.", image_view.actual_size),
        ("+", "Zoom in.", lambda: image_view.zoom(1.25)),
        ("−", "Zoom out.", lambda: image_view.zoom(0.8)),
    ):
        button = QPushButton(text)
        button.setToolTip(tip)
        button.setProperty("helpKey", {"+": "zoom in", "−": "zoom out"}.get(text, text))
        button.setFixedWidth(40)
        button.clicked.connect(slot)
        row.addWidget(button)
    return row
