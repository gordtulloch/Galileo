# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Start-up progress reporting for the splash screen.

``app.main`` installs a :class:`StartupProgress` around the splash; the slow start-up phases
(database, plugin discovery, building each screen) call :func:`report` with a short description. With no
reporter installed — tests, ``--selftest``, a window built after start-up — :func:`report` does nothing.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_reporter: StartupProgress | None = None

# Height of the strip added beneath the splash logo for the operation list, bar and percentage.
PROGRESS_AREA_HEIGHT = 150


def set_reporter(reporter: StartupProgress | None) -> None:
    global _reporter
    _reporter = reporter


def report(message: str) -> None:
    """Record that the start-up operation *message* is now running (completes the previous one)."""
    if _reporter is not None:
        _reporter.step(message)


def begin_detail(message: str) -> None:
    """Show *message* (e.g. a device connection attempt) as the running line, without counting a step."""
    if _reporter is not None:
        _reporter.begin_detail(message)


def end_detail(message: str, ok: bool) -> None:
    """Record the outcome of the detail started by :func:`begin_detail` as a ticked (``ok``) or failed line."""
    if _reporter is not None:
        _reporter.end_detail(message, ok)


def add_steps(count: int) -> None:
    """Grow the expected number of operations once a phase knows how many it has."""
    if _reporter is not None:
        _reporter.add_steps(count)


class StartupProgress:
    """Drives a splash screen's status line and progress bar.

    The bar shows completed operations out of the expected total; the status line names the one running.
    """

    def __init__(self, splash, app, total: int) -> None:
        self._splash = splash
        self._app = app
        self._total = max(1, total)
        self._done = 0
        self._message = ""
        self._completed: list[tuple[str, bool]] = []
        self._detail = ""

    def add_steps(self, count: int) -> None:
        self._total += max(0, count)
        self._paint()

    def step(self, message: str) -> None:
        if self._message:
            self._done = min(self._done + 1, self._total)
            self._completed.append((self._message, True))
        self._message = message
        self._detail = ""
        logger.info("Start-up: %s", message)
        self._paint()

    def begin_detail(self, message: str) -> None:
        self._detail = message
        logger.info("Start-up: %s", message)
        self._paint()

    def end_detail(self, message: str, ok: bool) -> None:
        self._detail = ""
        self._completed.append((message, ok))
        logger.info("Start-up: %s", message)
        self._paint()

    def finish(self) -> None:
        self._done = self._total
        self._message = "Ready"
        self._paint()

    @property
    def fraction(self) -> float:
        return self._done / self._total

    @property
    def message(self) -> str:
        return self._message

    def _paint(self) -> None:
        setter = getattr(self._splash, "set_progress", None)
        if setter is not None:
            setter(self.fraction, self._detail or self._message, self._completed[-3:])
        self._app.processEvents()


def make_splash_class():
    """Build the QSplashScreen subclass that draws the operation list and progress bar."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtWidgets import QSplashScreen

    class ProgressSplash(QSplashScreen):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._fraction = 0.0
            self._current = ""
            self._recent: list[tuple[str, bool]] = []
            self._logo_height = 0

        def set_progress(self, fraction: float, current: str, recent: list[tuple[str, bool]]) -> None:
            self._fraction = fraction
            self._current = current
            self._recent = list(recent)
            self.repaint()

        def set_logo_height(self, height: int) -> None:
            self._logo_height = height

        def drawContents(self, painter: QPainter) -> None:
            width, height = self.width(), self.height()
            # Version + copyright notice, bottom-aligned within the logo area (above the progress strip).
            logo_h = self._logo_height or height
            painter.setPen(QColor("white"))
            painter.drawText(0, 0, width, logo_h,
                             int(Qt.AlignBottom | Qt.AlignHCenter), self.message())

            margin = int(width * 0.12)
            bar_h = 10
            bar_y = height - 40
            font = painter.font()
            font.setPointSize(11)
            painter.setFont(font)
            line_h = painter.fontMetrics().height()

            # Recently finished operations (dimmed, ticked), then the running one, stacked above the bar.
            lines = [(f"{'✓' if ok else '✗'} {m}",
                      QColor(255, 255, 255, 130) if ok else QColor(255, 120, 120))
                     for m, ok in self._recent]
            if self._current:
                lines.append((f"{self._current}…", QColor("white")))
            y = bar_y - 8 - line_h * len(lines)
            for text, colour in lines:
                painter.setPen(colour)
                painter.drawText(margin, y, width - 2 * margin, line_h,
                                 int(Qt.AlignLeft | Qt.AlignVCenter), text)
                y += line_h

            track = QRectF(margin, bar_y, width - 2 * margin, bar_h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 60))
            painter.drawRoundedRect(track, bar_h / 2, bar_h / 2)
            fill = QRectF(track)
            fill.setWidth(track.width() * max(0.0, min(1.0, self._fraction)))
            painter.setBrush(QColor("#4da3ff"))
            painter.drawRoundedRect(fill, bar_h / 2, bar_h / 2)
            painter.setPen(QColor("white"))
            painter.drawText(margin, bar_y + bar_h + 2, width - 2 * margin, line_h,
                             int(Qt.AlignRight | Qt.AlignVCenter), f"{int(self._fraction * 100)}%")

    return ProgressSplash
