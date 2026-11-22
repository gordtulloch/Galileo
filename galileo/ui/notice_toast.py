# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The floating event-notice panels over the top-right corner of the main window (NOTE-010, NOTE-020).

Each :class:`galileo.notices.NoticeEvent` appears as a small panel that closes itself after
:data:`TIMEOUT_MS` or when its X is clicked. Panels stack downwards, newest at the bottom, and at most
:data:`MAX_VISIBLE` are shown at once (the oldest is dismissed first). They float over whatever screen is
showing, so no screen needs a log view of its own.

The bus calls handlers on whatever thread published the event, so the handler only emits a Qt signal; the panel
is built on the GUI thread.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from galileo.notices import NoticeEvent

logger = logging.getLogger(__name__)

TIMEOUT_MS = 10_000
MAX_VISIBLE = 5
PANEL_WIDTH = 340
MARGIN = 12
GAP = 6

# Accent stripe per severity. The night-vision theme (UI-011) may show only red, so it passes its own.
_ACCENTS = {"info": "#4fc3f7", "success": "#66bb6a", "warning": "#ffb74d", "error": "#ef5350"}


class NoticePanel(QFrame):
    """One notice: a title, an optional message, a close button and a 10 s timer."""

    closed = Signal(object)

    def __init__(self, parent: QWidget, title: str, message: str, severity: str, colours: dict[str, str],
                 accent: str, timeout_ms: int = TIMEOUT_MS) -> None:
        super().__init__(parent)
        self.setObjectName("NoticePanel")
        self.setProperty("severity", severity)
        self.setFixedWidth(PANEL_WIDTH)
        self.setStyleSheet(
            f"QFrame#NoticePanel {{ background: {colours['surface']}; border: 1px solid {colours['border']};"
            f" border-left: 5px solid {accent}; border-radius: 6px; }}"
            f"QFrame#NoticePanel QLabel {{ background: transparent; border: none; color: {colours['text']}; }}"
            f"QFrame#NoticePanel QLabel#NoticeTitle {{ color: {colours['text_bright']}; font-weight: bold; }}"
            f"QFrame#NoticePanel QLabel#NoticeMessage {{ color: {colours['text_dim']}; }}"
            f"QFrame#NoticePanel QPushButton {{ background: transparent; border: none; color: {colours['text_dim']};"
            f" font-size: 15px; padding: 0 4px; }}"
            f"QFrame#NoticePanel QPushButton:hover {{ color: {colours['text_bright']}; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 4, 6)
        row.setSpacing(6)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("NoticeTitle")
        text.addWidget(self.title_label)
        self.message_label = QLabel(message)
        self.message_label.setObjectName("NoticeMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(bool(message))
        text.addWidget(self.message_label)
        row.addLayout(text, 1)
        self.close_button = QPushButton("×")
        self.close_button.setToolTip("Dismiss")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFlat(True)
        self.close_button.setFixedSize(22, 22)
        self.close_button.clicked.connect(self.dismiss)
        row.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._timer.start(timeout_ms)
        self.adjustSize()

    def dismiss(self) -> None:
        self._timer.stop()
        if self.isVisible() or self.parent() is not None:
            self.hide()
            self.closed.emit(self)
            self.deleteLater()


class NoticeToasts(QObject):
    """Shows bus notices as stacked panels over the top-right of *window*."""

    _incoming = Signal(object)

    def __init__(self, window: QWidget, colours: Callable[[], dict[str, str]],
                 night_vision: Callable[[], bool] = lambda: False, timeout_ms: int = TIMEOUT_MS) -> None:
        super().__init__(window)
        self._window = window
        self._colours = colours
        self._night = night_vision
        self._timeout_ms = timeout_ms
        self._panels: list[NoticePanel] = []
        self._top_offset = MARGIN
        self._incoming.connect(self._show)
        window.installEventFilter(self)
        from galileo.bus import get_bus
        self._bus = get_bus()
        self._bus.subscribe(NoticeEvent, self._on_event)
        window.destroyed.connect(lambda *_: self.close())

    def close(self) -> None:
        try:
            self._bus.unsubscribe(NoticeEvent, self._on_event)
        except Exception:
            logger.debug("Could not unsubscribe the notice panels", exc_info=True)

    # -- input -----------------------------------------------------------------------------------
    def _on_event(self, event: NoticeEvent) -> None:        # any thread
        p = event.payload
        self._incoming.emit((str(p.get("title") or ""), str(p.get("message") or ""), str(p.get("severity") or "info")))

    def notify(self, title: str, message: str = "", severity: str = "info") -> None:
        """Show a panel directly (GUI thread)."""
        self._show((title, message, severity))

    # -- panels ----------------------------------------------------------------------------------
    @property
    def panels(self) -> list[NoticePanel]:
        return list(self._panels)

    def _show(self, item: tuple[str, str, str]) -> None:
        title, message, severity = item
        if not title and not message:
            return
        colours = dict(self._colours())
        accent = colours["text_bright"] if self._night() else _ACCENTS.get(severity, _ACCENTS["info"])
        panel = NoticePanel(self._window, title or message, message if title else "", severity, colours, accent,
                            self._timeout_ms)
        panel.closed.connect(self._on_closed)
        self._panels.append(panel)
        while len(self._panels) > MAX_VISIBLE:
            self._panels[0].dismiss()
        panel.show()
        self._layout()

    def _on_closed(self, panel: NoticePanel) -> None:
        if panel in self._panels:
            self._panels.remove(panel)
        self._layout()

    def set_top_offset(self, pixels: int) -> None:
        """Keep the panels clear of a toolbar the window shows along its top edge."""
        self._top_offset = max(0, pixels)
        self._layout()

    def _layout(self) -> None:
        x_right = self._window.width() - MARGIN
        y = self._top_offset
        for panel in self._panels:
            panel.adjustSize()
            panel.move(max(0, x_right - panel.width()), y)
            panel.raise_()
            y += panel.height() + GAP

    def eventFilter(self, obj, event) -> bool:
        if obj is self._window and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._layout()
        return False


def install_notice_toasts(window: QWidget, colours: Callable[[], dict[str, str]],
                          night_vision: Callable[[], bool] = lambda: False) -> NoticeToasts:
    return NoticeToasts(window, colours, night_vision)


__all__ = ["MAX_VISIBLE", "TIMEOUT_MS", "NoticePanel", "NoticeToasts", "install_notice_toasts"]
