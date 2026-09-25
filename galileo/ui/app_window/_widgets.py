# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Standalone widget classes used by the various pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import _HAS_QT, QWidget, QLabel, QPlainTextEdit, Signal

if TYPE_CHECKING:
    from PySide6.QtWidgets import QButtonGroup


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
