# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Star Atlas pointer handling: hit-testing, pan/zoom, selection, context menu and the cursor read-out."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any
import numpy as np
from PySide6.QtCore import Qt
from galileo.planning import star_atlas as sa


def format_ra(deg: float) -> str:
    total = (deg % 360.0) / 15.0 * 3600.0
    return f"{int(total // 3600):02d}h {int(total % 3600 // 60):02d}m {total % 60:04.1f}s"


def format_dec(deg: float) -> str:
    sign = "-" if deg < 0 else "+"
    total = abs(deg) * 3600.0
    return f"{sign}{int(total // 3600):02d}° {int(total % 3600 // 60):02d}′ {total % 60:02.0f}″"

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as _MixinBase  # type checkers see a widget (it is mixed into one)
else:
    _MixinBase = object




class StarAtlasInputMixin(_MixinBase):
    """Star Atlas pointer handling: hit-testing, pan/zoom, selection, context menu and the cursor read-out."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def _cursor_text(self) -> str:
        if self._cursor is None:
            return ""
        alt, az = self.view.unproject(*self._cursor)
        ra, dec = sa.horizontal_to_equatorial(float(alt), float(az), self._lst, self.latitude)
        return f"Alt {float(alt):.1f}°  Az {float(az):.1f}°   RA {format_ra(ra)}  Dec {format_dec(dec)}  (of date)"

    def _sky_point_at(self, sx: float, sy: float) -> dict[str, Any] | None:
        """J2000 ra_deg/dec_deg + alt/az for screen position (sx, sy), or None on error."""
        try:
            vp = self._viewport()
            alt_arr, az_arr = vp.unproject(sx, sy)
            alt = float(alt_arr)
            az = float(az_arr)
            ra_date, dec_date = sa.horizontal_to_equatorial(alt, az, self._lst, self.latitude)
            ra, dec = sa.precess_to_j2000(float(ra_date), float(dec_date), self._jd)
            return {"kind": "sky_point", "ra_deg": float(ra), "dec_deg": float(dec), "alt": alt, "az": az}
        except Exception:
            return None

    def object_at(self, x: float, y: float) -> dict[str, Any] | None:
        """Nearest visible object within a few pixels of screen position (x, y)."""
        sets = self._sets(self._viewport())
        best, best_d = None, float(self.HIT_RADIUS_PX)
        makers = {"bodies": self._body_object, "minor": self._minor_object,
                  "stars": self._star_object, "dsos": self._dso_object}
        for key in ("bodies", "minor", "stars", "dsos"):      # bodies win ties, then comets etc., stars, DSOs
            idx, xs, ys = sets[key]
            if len(idx) == 0:
                continue
            d = np.hypot(xs - x, ys - y)
            j = int(np.argmin(d))
            if d[j] < best_d:
                best, best_d = makers[key](int(idx[j])), float(d[j])
        return best

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position()
            self._dragging = False

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        self._cursor = (pos.x(), pos.y())
        if self._press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = pos - self._press_pos
            if not self._dragging and delta.manhattanLength() > 4:
                self._dragging = True
                self.tracked = None
            if self._dragging:
                deg_per_px = self.view.fov_deg / max(1, self.height())
                # Dragging the sky right brings what was to the left (lower azimuth) to the centre.
                self.view.az0 = (self.view.az0 - delta.x() * deg_per_px / max(0.25, math.cos(math.radians(self.view.alt0)))) % 360.0
                self.view.alt0 = float(np.clip(self.view.alt0 + delta.y() * deg_per_px, -10.0, 90.0))
                self._press_pos = pos
                self.viewChanged.emit()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            if not self._dragging:
                self.select(self.object_at(event.position().x(), event.position().y()))
            self._press_pos = None
            self._dragging = False

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            obj = self.object_at(event.position().x(), event.position().y())
            if obj is not None:
                self.select(obj)
                self.center_on(obj, track=True)

    def contextMenuEvent(self, event) -> None:
        obj = self.object_at(event.pos().x(), event.pos().y())
        if obj is not None:
            self.select(obj)
        sky_point = self._sky_point_at(event.pos().x(), event.pos().y())
        self.contextMenuRequested.emit(obj, event.globalPos(), sky_point)

    def leaveEvent(self, _event) -> None:
        self._cursor = None
        self.update()

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.set_fov(self.view.fov_deg * (0.85 ** steps))
