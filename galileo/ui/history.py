# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Planning > History (HIST-020, HIST-040): review the per-frame quality metrics the session
executor records (HFR, star count, guide RMS) as a chart and a table, during or after a run,
and export them to CSV.

The executor writes to ``galileo.history.get_history()`` from its worker thread; this page only
reads, on the UI thread, when it is shown or refreshed (and on a slow timer while visible so a
running session's frames appear without pressing Refresh).
"""

from __future__ import annotations

import itertools
import logging
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from galileo.history import SessionHistory, get_history

logger = logging.getLogger(__name__)

_REFRESH_MS = 5000
_COLUMNS = ("Time", "HFR", "Stars", "Guide RA", "Guide Dec")

# (key in a frame record, legend text, colour) — HFR and guide error share the left axis (pixels or
# arcseconds are both small numbers); star count is scaled onto its own right-hand axis.
_HFR_COLOUR = QColor("#4fc3f7")
_STAR_COLOUR = QColor("#ffb74d")


def summarise(frames: list[dict]) -> str:
    """One line describing a session's frames, for the label above the chart."""
    if not frames:
        return "No frames recorded."
    hfr = [f["hfr"] for f in frames]
    stars = [f["star_count"] for f in frames]
    guided = [f for f in frames if f["guide_rms_ra"] or f["guide_rms_dec"]]
    text = (f"{len(frames)} frame(s) — HFR mean {sum(hfr) / len(hfr):.2f} "
            f"(best {min(hfr):.2f}, worst {max(hfr):.2f}); stars mean {sum(stars) / len(stars):.0f}")
    if guided:
        total = [(f["guide_rms_ra"] ** 2 + f["guide_rms_dec"] ** 2) ** 0.5 for f in guided]
        text += f"; guide RMS mean {sum(total) / len(total):.2f}"
    return text


class _MetricsChart(QWidget):
    """HFR (left axis) and star count (right axis) against frame number."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(200)
        self._hfr: list[float] = []
        self._stars: list[float] = []

    def set_frames(self, frames: list[dict]) -> None:
        self._hfr = [float(f["hfr"]) for f in frames]
        self._stars = [float(f["star_count"]) for f in frames]
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1a1a1a"))
        foreground = QColor("#cccccc")
        font = QFont(painter.font())
        font.setPointSizeF(8.0)
        painter.setFont(font)
        painter.setPen(foreground)
        plot = QRectF(44, 18, self.width() - 96, self.height() - 40)
        if not self._hfr or plot.width() < 20 or plot.height() < 20:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No frames recorded")
            painter.end()
            return
        self._draw_series(painter, plot, self._hfr, _HFR_COLOUR, left=True)
        self._draw_series(painter, plot, self._stars, _STAR_COLOUR, left=False)
        painter.setPen(_HFR_COLOUR)
        painter.drawText(QPointF(plot.left(), 12), "HFR")
        painter.setPen(_STAR_COLOUR)
        painter.drawText(QPointF(plot.left() + 40, 12), "Stars")
        painter.setPen(foreground)
        painter.drawText(QRectF(plot.left(), plot.bottom() + 4, plot.width(), 16),
                         Qt.AlignmentFlag.AlignCenter, f"Frame (1 – {len(self._hfr)})")
        painter.end()

    @staticmethod
    def _draw_series(painter: QPainter, plot: QRectF, values: list[float], colour: QColor, left: bool) -> None:
        low, high = min(values), max(values)
        if high - low < 1e-9:
            low, high = low - 1.0, high + 1.0
        pad = (high - low) * 0.1
        low, high = low - pad, high + pad
        count = len(values)

        def point(i: int, v: float) -> QPointF:
            x = plot.left() + (plot.width() * i / (count - 1) if count > 1 else plot.width() / 2)
            return QPointF(x, plot.bottom() - (v - low) / (high - low) * plot.height())

        painter.setPen(colour)
        for tick in (low, (low + high) / 2, high):
            y = point(0, tick).y()
            label = f"{tick:.1f}" if high < 100 else f"{tick:.0f}"
            if left:
                painter.drawText(QRectF(0, y - 8, plot.left() - 4, 16),
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
            else:
                painter.drawText(QRectF(plot.right() + 4, y - 8, 48, 16),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        pen = QPen(colour)
        pen.setWidthF(1.6)
        painter.setPen(pen)
        points = [point(i, v) for i, v in enumerate(values)]
        for a, b in itertools.pairwise(points):
            painter.drawLine(a, b)
        for p in points:
            painter.drawEllipse(p, 2.5, 2.5)


class HistoryPageWidget(QWidget):
    """The History screen — one recorded session at a time, as chart, summary and table."""

    def __init__(self, window=None, history: SessionHistory | None = None) -> None:
        super().__init__()
        self._history = history
        self._frames: list[dict] = []

        layout = QVBoxLayout(self)
        form = QFormLayout()
        row = QHBoxLayout()
        self._session_combo = QComboBox()
        self._session_combo.setMinimumWidth(320)
        self._session_combo.currentIndexChanged.connect(self._show_selected)
        row.addWidget(self._session_combo, 1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.reload)
        self._export_btn = QPushButton("Export CSV…")
        self._export_btn.clicked.connect(self._export)
        self._delete_btn = QPushButton("Delete Session")
        self._delete_btn.clicked.connect(self._delete)
        for button in (self._refresh_btn, self._export_btn, self._delete_btn):
            row.addWidget(button)
        form.addRow("Session", row)
        layout.addLayout(form)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._chart = _MetricsChart()
        layout.addWidget(self._chart, 2)
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_COLUMNS))
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 3)

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self.reload()

    @property
    def history(self) -> SessionHistory:
        return self._history if self._history is not None else get_history()

    # --- Loading ----------------------------------------------------------

    def reload(self) -> None:
        """Re-read the session list (keeping the selection) and redraw the selected session."""
        names = [s["name"] for s in self.history.list_sessions() if s["frame_count"]]
        names.reverse()                                   # most recent first
        current = self._session_combo.currentData()
        self._session_combo.blockSignals(True)
        self._session_combo.clear()
        for name in names:
            count = len(self.history.get_frames_for_session(name))
            self._session_combo.addItem(f"{name}  ({count} frame{'s' if count != 1 else ''})", name)
        index = self._session_combo.findData(current) if current is not None else -1
        self._session_combo.setCurrentIndex(index if index >= 0 else (0 if names else -1))
        self._session_combo.blockSignals(False)
        self._show_selected()

    def _show_selected(self, *_args) -> None:
        name = self._session_combo.currentData()
        self._frames = self.history.get_frames_for_session(name) if name else []
        self._summary.setText(summarise(self._frames) if name else "No sessions have been recorded yet. "
                              "Frames are logged as a session takes light exposures.")
        self._chart.set_frames(self._frames)
        self._table.setRowCount(len(self._frames))
        for row, frame in enumerate(self._frames):
            cells = (frame["timestamp"], f"{frame['hfr']:.2f}", str(frame["star_count"]),
                     f"{frame['guide_rms_ra']:.2f}", f"{frame['guide_rms_dec']:.2f}")
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, column, item)
        has = bool(self._frames)
        self._export_btn.setEnabled(has)
        self._delete_btn.setEnabled(name is not None)

    def _tick(self) -> None:
        """Pick up frames a running session has added since the last look."""
        name = self._session_combo.currentData()
        total = len(self.history.list_sessions())
        if total != self._session_combo.count() or (
                name and len(self.history.get_frames_for_session(name)) != len(self._frames)):
            self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload()
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    # --- Actions ----------------------------------------------------------

    def _export(self) -> None:
        name = self._session_combo.currentData()
        if not name:
            return
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "session"
        path, _ = QFileDialog.getSaveFileName(self, "Export session history", f"{safe}.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            self.history.export_csv(name, Path(path))
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def _delete(self) -> None:
        name = self._session_combo.currentData()
        if not name:
            return
        answer = QMessageBox.question(self, "Delete session history",
                                      f"Delete the recorded history for {name!r}? The images are not affected.")
        if answer == QMessageBox.StandardButton.Yes:
            self.history.delete_session(name)
            self.reload()
