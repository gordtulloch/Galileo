# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""In-app help UI (HELP-010 .. HELP-060): hover text, per-control help, the help window.

Content lives in ``galileo/help/content/*.md`` and is parsed by :mod:`galileo.help`.
This module only *finds* the right entry for a widget, so a page needs no
help-specific code beyond being tagged with its screen id
(:func:`tag_help_screen`): every label, button and input is matched to a help
section by its text -- the form-row label, the button caption, a table column
header -- or by an explicit ``helpKey`` property when the text is ambiguous.

* Every control with a help entry has that entry's first paragraph as its tooltip.
* **F1** opens the help window on the focused control (else the current screen).
* **Shift+F1**, or the sidebar's ? button, enters *point-and-click* mode: the next
  control clicked opens its help instead of acting.

``python -m galileo.ui.help --audit`` lists every control, on every screen, that
has no help entry yet.
"""

from __future__ import annotations

import logging

from galileo import community
from galileo import help as help_content

try:
    from PySide6.QtCore import QEvent, QObject, Qt, QTimer
    from PySide6.QtGui import QColor, QCursor, QKeySequence, QPalette, QShortcut
    from PySide6.QtWidgets import (
        QAbstractButton, QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QFormLayout,
        QGridLayout, QBoxLayout, QGroupBox, QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton, QRadioButton, QSplitter,
        QTabBar, QTableWidget, QTextBrowser, QToolButton, QTreeWidget, QTreeWidgetItem,
        QVBoxLayout, QWidget,
    )
    _HAS_QT = True
except ImportError:  # pragma: no cover - Qt is optional for headless use of the core
    _HAS_QT = False
    QObject = QWidget = object  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)

# The default link colours (blue / purple when visited) are unreadable on the dark themes.
_LINK_COLOR = "#d0d0d0"

_TIP_PROPERTY = "helpTipFor"   # the widget text its tooltip was last matched against
_TIP_INTERVAL_MS = 500

SCREEN_PROPERTY = "helpScreen"
KEY_PROPERTY = "helpKey"


def tag_help_screen(widget, screen_id: str):
    """Mark *widget* as the root of screen *screen_id*; returns *widget*.

    Every control inside it resolves its help against that screen (then its
    parents, then ``common``). A nested tag wins over an outer one.
    """
    widget.setProperty(SCREEN_PROPERTY, screen_id)
    add_title_buttons(widget)
    return widget


_controller: HelpController | None = None


class _CornerPinner(QObject):
    """Keeps a button pinned to the top-right corner of its parent as the parent resizes."""

    def __init__(self, button) -> None:
        super().__init__(button)
        self._button = button
        button.parentWidget().installEventFilter(self)
        self._place()

    def _place(self) -> None:
        parent = self._button.parentWidget()
        self._button.move(parent.width() - self._button.width() - 6, 4)
        self._button.raise_()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._place()
        return False


def _make_help_button() -> QToolButton:
    button = QToolButton()
    button.setText("?")
    button.setObjectName("HelpButton")
    button.setProperty("helpKey", "help")
    button.setAutoRaise(True)
    button.setFixedSize(24, 24)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet("QToolButton { font-weight: bold; border: 1px solid palette(mid); border-radius: 12px; }")
    button.setToolTip("Help for this screen (F1). Shift+F1 then click a control for help on just that control.")
    button.clicked.connect(lambda _=False, b=button: _controller.help_for_screen_of(b) if _controller else None)
    return button


def add_title_buttons(page) -> None:
    """Put a ? button after the screen's ``PageTitle`` heading on *page* (not on a nested tagged page).

    A screen with no PageTitle (the Library's) gets the button pinned to its top-right corner instead.
    """
    if not _HAS_QT:
        return
    if page.property("helpButtonAdded"):
        return
    has_title = any(
        t.objectName() == "PageTitle" and screen_id_for(t) == page.property(SCREEN_PROPERTY)
        for t in page.findChildren(QLabel)
    )
    if not has_title:
        children = page.findChildren(QWidget)
        container = any(c.property(SCREEN_PROPERTY) for c in children)  # its sub-screens carry their own ?
        if children and not container:  # an empty placeholder (a lazy page) is decorated once it is filled
            corner = _make_help_button()
            corner.setParent(page)
            _CornerPinner(corner)
            corner.show()
            page.setProperty("helpButtonAdded", True)
        return
    for title in page.findChildren(QLabel):
        if title.objectName() != "PageTitle":
            continue
        if page.property("helpButtonAdded"):
            return  # one ? per screen; a second PageTitle (e.g. "Filters") is a sub-heading
        if screen_id_for(title) != page.property(SCREEN_PROPERTY):
            continue  # belongs to a nested screen, which tags (and decorates) itself
        parent = title.parentWidget()
        found = _locate(parent.layout(), title) if parent is not None and parent.layout() is not None else None
        if found is None or not isinstance(found[0], QBoxLayout):
            continue
        layout, idx = found
        button = _make_help_button()
        page.setProperty("helpButtonAdded", True)
        if isinstance(layout, QHBoxLayout):
            layout.insertWidget(idx + 1, button)
        else:  # title sits alone on its own row of a vertical layout: give it a row of its own with the button
            row = QHBoxLayout()
            layout.removeWidget(title)
            row.addWidget(title)
            row.addWidget(button)
            row.addStretch(1)
            layout.insertLayout(idx, row)


def screen_id_for(widget) -> str | None:
    w = widget
    while w is not None:
        sid = w.property(SCREEN_PROPERTY)
        if sid:
            return str(sid)
        w = w.parentWidget()
    return None


def _clean(text: str) -> str:
    return text.replace("&", "").strip()


def _layout_contains(layout: QLayout, w) -> bool:
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        if item.widget() is w:
            return True
        sub = item.layout()
        if sub is not None and _layout_contains(sub, w):
            return True
    return False


def _form_role(layout: QLayout, w):
    """(role, label text) if *w* is a label or field of a QFormLayout reachable from *layout*."""
    if isinstance(layout, QFormLayout):
        for row in range(layout.rowCount()):
            label_item = layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
            label_widget = label_item.widget() if label_item is not None else None
            label_text = _clean(label_widget.text()) if isinstance(label_widget, QLabel) else ""
            if label_widget is w:
                return "label", label_text
            for role in (QFormLayout.ItemRole.FieldRole, QFormLayout.ItemRole.SpanningRole):
                item = layout.itemAt(row, role)
                if item is None:
                    continue
                if item.widget() is w or (item.layout() is not None and _layout_contains(item.layout(), w)):
                    return "field", label_text
    for i in range(layout.count()):
        sub = layout.itemAt(i).layout() if layout.itemAt(i) is not None else None
        if sub is not None:
            found = _form_role(sub, w)
            if found:
                return found
    return None


def _enclosing_form_role(widget):
    """Walk up from *widget* looking for the form row it belongs to."""
    w = widget
    while w is not None and not w.property(SCREEN_PROPERTY):
        parent = w.parentWidget()
        if parent is not None and parent.layout() is not None:
            found = _form_role(parent.layout(), w)
            if found:
                return found
        w = parent
    return None


def _locate(layout: QLayout, w):
    """(layout, index) of the layout that directly holds *w*, searching sub-layouts."""
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        if item.widget() is w:
            return layout, i
        sub = item.layout()
        if sub is not None:
            found = _locate(sub, w)
            if found:
                return found
    return None


def _is_caption(label) -> bool:
    text = _clean(label.text()) if isinstance(label, QLabel) else ""
    return bool(text) and len(text) <= 40 and any(c.isalpha() for c in text)  # a sentence is not a caption


def _neighbour_caption(widget) -> str:
    """Text of the caption label sitting before *widget* in a grid row or box layout.

    Covers pages that lay out ``QLabel("Step size:")`` + spin box by hand
    instead of with a QFormLayout.
    """
    w = widget
    while w is not None and not w.property(SCREEN_PROPERTY):
        parent = w.parentWidget()
        if parent is not None and parent.layout() is not None:
            found = _locate(parent.layout(), w)
            if found:
                layout, idx = found
                if isinstance(layout, QGridLayout):
                    row, col, _rs, _cs = layout.getItemPosition(idx)
                    best, best_col = None, -1
                    for j in range(layout.count()):
                        r, c, _a, _b = layout.getItemPosition(j)
                        lw = layout.itemAt(j).widget()
                        if r == row and best_col < c < col and _is_caption(lw):
                            best, best_col = lw, c
                    if best is not None:
                        return _clean(best.text())
                    for j in range(layout.count()):  # none beside it: a caption directly above, in the same column
                        r, c, _a, _b = layout.getItemPosition(j)
                        lw = layout.itemAt(j).widget()
                        if r == row - 1 and c == col and _is_caption(lw):
                            return _clean(lw.text())
                elif not isinstance(layout, QFormLayout):
                    for j in range(idx - 1, -1, -1):
                        lw = layout.itemAt(j).widget()
                        if lw is not None and _is_caption(lw):
                            return _clean(lw.text())
        w = parent
    return ""


def _group_title(widget) -> str:
    w = widget.parentWidget()
    while w is not None and not w.property(SCREEN_PROPERTY):
        if isinstance(w, QGroupBox) and w.title():
            return _clean(w.title())
        w = w.parentWidget()
    return ""


def _table_header_text(widget) -> str:
    """The column header over a widget that sits in a QTableWidget cell."""
    w = widget
    while w is not None and not w.property(SCREEN_PROPERTY):
        table = w.parentWidget().parentWidget() if w.parentWidget() is not None else None
        if isinstance(table, QTableWidget) and w.parentWidget() is table.viewport():
            for row in range(table.rowCount()):  # by identity, not geometry: a hidden page has no layout yet
                for col in range(table.columnCount()):
                    if table.cellWidget(row, col) is w:
                        item = table.horizontalHeaderItem(col)
                        return _clean(item.text()) if item is not None else ""
            return ""
        w = w.parentWidget()
    return ""


def candidate_keys(widget) -> list[str]:
    """Help-section keys for *widget*, best first (see module docstring).

    Each key is also tried qualified by its enclosing group box's title
    (``manual-focus-position`` before ``position``), so one screen can document
    two same-named controls separately.
    """
    base: list[str] = []

    def add(text: str) -> None:
        k = help_content.slug(text)
        if k and k not in base:
            base.append(k)

    explicit = widget.property(KEY_PROPERTY)
    if explicit:
        add(str(explicit))
    form = _enclosing_form_role(widget)
    caption = form[1] if form else ""
    if not caption and not isinstance(widget, (QLabel, QPushButton, QToolButton, QGroupBox)):
        caption = _neighbour_caption(widget)
    if isinstance(widget, (QCheckBox, QRadioButton)):
        add(_table_header_text(widget))
        add(caption)
        add(widget.text())
    elif isinstance(widget, (QPushButton, QToolButton)):
        add(widget.text())
        if widget.text().strip() == "+":
            add("add another device")
        add(caption)
    elif isinstance(widget, QLabel):
        add(widget.text())  # a caption names itself; a value label ("—") slugs to nothing useful
        if form and form[0] == "field":
            add(caption)
    elif isinstance(widget, QGroupBox):
        add(widget.title())
    else:
        add(_table_header_text(widget))  # a table cell's column header beats a stray label above the table
        add(caption)
        if isinstance(widget, QAbstractButton):
            add(widget.text())
    add(widget.accessibleName() or "")
    add(widget.objectName())
    if widget.objectName() == "PageTitle":
        base.append(help_content.OVERVIEW)

    group = help_content.slug(_group_title(widget))
    if not group:
        return base
    return [f"{group}-{k}" for k in base if k != group] + base


def lookup(widget):
    """``(HelpDoc, Section)`` documenting *widget*, or None."""
    sid = screen_id_for(widget)
    if sid is None:
        return None
    for key in candidate_keys(widget):
        hit = help_content.resolve(sid, key)
        if hit is not None:
            return hit
    return None


def tooltip_html(section) -> str:
    from html import escape
    return f"<p style='margin:0'>{escape(section.summary)}</p><p style='margin:4px 0 0 0'><i>F1 for details</i></p>"


# --------------------------------------------------------------------------- audit

_DOCUMENTED_TYPES = (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit) if _HAS_QT else ()


def audit(root) -> list[str]:
    """Descriptions of controls under *root* that have no help entry.

    Only interactive controls and form labels are checked; the sidebar and
    scroll-bar/spin-box internals are not part of a screen's own controls.
    """
    missing: list[str] = []
    seen: set[str] = set()
    for w in root.findChildren(QWidget):
        if w.objectName().startswith(("qt-", "qt_")):
            continue  # Qt's own internals (table corner button, scroll-bar buttons)
        if isinstance(w, QLineEdit) and isinstance(w.parentWidget(), (QAbstractSpinBox, QComboBox)):
            continue  # the inner editor of a spin box / editable combo
        is_form_label = isinstance(w, QLabel) and (_enclosing_form_role(w) or ("",))[0] == "label"
        if not (isinstance(w, _DOCUMENTED_TYPES) or is_form_label):
            continue
        if isinstance(w, QToolButton) and w.parentWidget() is not None and w.parentWidget().objectName().endswith("Sidebar"):
            continue
        if isinstance(w.parentWidget(), QTabBar):
            continue  # a tab's scroll arrows and close button
        if lookup(w) is None:
            keys = candidate_keys(w)
            desc = f"{screen_id_for(w)}: {type(w).__name__} " + (repr(keys[0]) if keys else f"<unnamed {w.objectName()!r}>")
            if desc not in seen:
                seen.add(desc)
                missing.append(desc)
    return missing


# --------------------------------------------------------------------------- window

class HelpWindow(QWidget):
    """Non-modal help viewer: topic tree + search on the left, rendered Markdown on the right."""

    def __init__(self, manual_url: str = "", on_pick=None, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Galileo Help")
        self.resize(980, 680)
        self._manual_url = manual_url

        layout = QVBoxLayout(self)
        split = QSplitter()
        layout.addWidget(split, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search help…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._rebuild_tree)
        left_layout.addWidget(self._search)
        if on_pick is not None:
            pick = QPushButton("Point at a control…")
            pick.setToolTip("Click this, then click any control in Galileo to see its help (Shift+F1).")
            pick.clicked.connect(on_pick)
            left_layout.addWidget(pick)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemClicked.connect(self._on_item)
        left_layout.addWidget(self._tree, 1)
        split.addWidget(left)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.document().setDefaultStyleSheet(f"a {{ color: {_LINK_COLOR}; }}")
        split.addWidget(self._browser)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 720])

        if manual_url:
            link = QLabel(f'<a href="{manual_url}">Online manual (user guides on the wiki)</a>'
                          f' &nbsp;·&nbsp; <a href="{community.DISCUSSIONS_URL}">Not answered here? Ask the community</a>')
            link.setOpenExternalLinks(True)
            palette = link.palette()
            palette.setColor(QPalette.ColorRole.Link, QColor(_LINK_COLOR))
            palette.setColor(QPalette.ColorRole.LinkVisited, QColor(_LINK_COLOR))
            link.setPalette(palette)
            layout.addWidget(link)

        self._current: str | None = None
        self._rebuild_tree()

    # -- tree
    def _rebuild_tree(self, query: str = "") -> None:
        self._tree.clear()
        query = query.strip()
        if query:
            for doc, sec in help_content.search(query):
                item = QTreeWidgetItem([f"{doc.title} › {sec.title}"])
                item.setData(0, Qt.ItemDataRole.UserRole, (doc.screen_id, sec.key))
                self._tree.addTopLevelItem(item)
            return
        for sid in help_content.screen_ids():
            doc = help_content.load(sid)
            if doc is None or sid == help_content.COMMON:
                continue
            top = QTreeWidgetItem([doc.title])
            top.setData(0, Qt.ItemDataRole.UserRole, (sid, None))
            for sec in doc.topics():
                if sec.key != help_content.OVERVIEW:
                    child = QTreeWidgetItem([sec.title])
                    child.setData(0, Qt.ItemDataRole.UserRole, (sid, sec.key))
                    top.addChild(child)
            self._tree.addTopLevelItem(top)

    def _on_item(self, item, _col=0) -> None:
        sid, key = item.data(0, Qt.ItemDataRole.UserRole)
        self.show_topic(sid, key)

    # -- content
    def show_topic(self, screen_id: str, key: str | None = None) -> None:
        """Show *screen_id*'s help, scrolled to section *key*; falls back to parent screens / common."""
        doc = help_content.load(screen_id)
        section = None
        if key is not None:
            hit = help_content.resolve(screen_id, key)
            if hit is not None:
                doc, section = hit
        if doc is None:
            # Nothing written for this screen: fall back to its closest documented parent.
            parts = screen_id.split(".")
            while doc is None and parts:
                parts.pop()
                doc = help_content.load(".".join(parts)) if parts else None
        if doc is None:
            self._current = None
            self._browser.setMarkdown(
                "# No help for this screen yet\n\nSee the online manual (link below) for the user guides."
            )
        else:
            if self._current != doc.screen_id:
                self._browser.setMarkdown(doc.markdown)
                self._current = doc.screen_id
            self._scroll_to(section.title if section is not None and section.key != help_content.OVERVIEW else None)
        # Over a modal dialog (Flats Assistant, a block's settings…) the help must itself be modal,
        # or the dialog blocks all input to it and it could not even be scrolled.
        over_modal = QApplication.activeModalWidget() not in (None, self)
        wanted = Qt.WindowModality.ApplicationModal if over_modal else Qt.WindowModality.NonModal
        if self.windowModality() != wanted:
            self.hide()
            self.setWindowModality(wanted)
        self.show()
        self.raise_()
        self.activateWindow()

    def _scroll_to(self, heading: str | None) -> None:
        bar = self._browser.verticalScrollBar()
        if heading is None:
            cursor = self._browser.textCursor()
            cursor.clearSelection()
            self._browser.setTextCursor(cursor)
            bar.setValue(0)
            return
        cursor = self._browser.document().find(heading)
        if cursor.isNull():
            return
        self._browser.setTextCursor(cursor)  # selecting the heading highlights it
        bar.setValue(0)
        bar.setValue(self._browser.cursorRect(cursor).top())


# --------------------------------------------------------------------------- controller

class HelpController(QObject):
    """Wires tooltips, F1, Shift+F1 and point-and-click help for one main window.

    Tooltips are *assigned* to widgets (``setToolTip``) by a timer rather than served from an
    application-wide event filter: a Python filter on QApplication is called for every event of
    every object, including ones mid-destruction, and crashed PySide when a layout was deleted.
    The pick-a-control filter below is installed only while picking.
    """

    def __init__(self, main_window, manual_url: str = "") -> None:
        super().__init__(main_window)
        global _controller
        _controller = self
        self._main = main_window
        self._manual_url = manual_url
        self._window: HelpWindow | None = None
        self._picking = False
        self._tip_timer = QTimer(self)
        self._tip_timer.timeout.connect(self.apply_tooltips)
        self._tip_timer.start(_TIP_INTERVAL_MS)
        for seq, slot in (("F1", self.help_for_focus), ("Shift+F1", self.start_pick)):
            sc = QShortcut(QKeySequence(seq), main_window)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(slot)

    # -- tooltips
    def apply_tooltips(self, root=None) -> int:
        """Give every documented widget under *root* its help text as its tooltip.

        With no *root*, every visible top-level window (the main window, an open dialog) is
        scanned, so controls created later — an extra device panel, a dialog — are covered too.
        A widget already done is skipped unless its own text has changed since (a button that
        reads "Start" and later "Stop" is matched again). Returns the number of widgets set.
        """
        roots = [root] if root is not None else [w for w in QApplication.topLevelWidgets() if w.isVisible()]
        done = 0
        for top in roots:
            for w in [top, *top.findChildren(QWidget)]:
                if root is None and not w.isVisible():
                    continue
                text = w.text() if isinstance(w, (QAbstractButton, QLabel)) else ""
                if w.property(_TIP_PROPERTY) == text:
                    continue
                w.setProperty(_TIP_PROPERTY, text)
                hit = lookup(w)
                if hit is not None:
                    w.setToolTip(tooltip_html(hit[1]))
                    done += 1
        return done

    # -- window
    def window(self) -> HelpWindow:
        if self._window is None:
            self._window = HelpWindow(self._manual_url, on_pick=self.start_pick)
        return self._window

    def current_screen_id(self) -> str | None:
        """The most specific tagged page currently on screen."""
        best = None
        for w in self._main.findChildren(QWidget):
            sid = w.property(SCREEN_PROPERTY)
            if sid and w.isVisible() and (best is None or len(str(sid)) > len(best)):
                best = str(sid)
        return best

    # -- entry points
    def help_for_screen(self) -> None:
        self.window().show_topic(self.current_screen_id() or help_content.COMMON)

    def help_for_widget(self, widget) -> None:
        hit = lookup(widget)
        sid = screen_id_for(widget) or self.current_screen_id() or help_content.COMMON
        if hit is not None:
            self.window().show_topic(hit[0].screen_id, hit[1].key)
        else:
            self.window().show_topic(sid)

    def help_for_screen_of(self, widget) -> None:
        """Help for the screen *widget* is on (the ? button beside a screen's title)."""
        self.window().show_topic(screen_id_for(widget) or self.current_screen_id() or help_content.COMMON)

    def help_for_focus(self) -> None:
        w = QApplication.focusWidget()
        if w is not None and screen_id_for(w) is not None:
            self.help_for_widget(w)
        elif w is None or w.window() is not self._window:
            self.help_for_screen()

    def start_pick(self) -> None:
        if self._picking:
            return
        self._picking = True
        QApplication.instance().installEventFilter(self)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WhatsThisCursor))
        self._main.statusBar().showMessage("Click any control for help on it (Esc to cancel).")

    def _end_pick(self) -> None:
        if self._picking:
            self._picking = False
            QApplication.instance().removeEventFilter(self)
            QApplication.restoreOverrideCursor()
            self._main.statusBar().clearMessage()

    # -- events
    def eventFilter(self, obj, ev):  # Qt signature
        et = ev.type()
        if self._picking and et == QEvent.Type.MouseButtonPress:
            target = QApplication.widgetAt(ev.globalPosition().toPoint())
            self._end_pick()
            if target is not None and screen_id_for(target) is not None:
                self.help_for_widget(target)
                return True
        elif self._picking and et == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
            self._end_pick()
            return True
        return False


def audit_window(win, only: str = "") -> tuple[list[str], int]:
    """Every undocumented control, on every screen, of a built ``AppWindow``.

    Returns ``(problems, screens_checked)``. A screen with no help file of its own or any parent's
    is a problem; so is any control on it that matches no section.
    """
    from galileo.ui.library.pages import _LazyPage
    for lazy in win._window.findChildren(_LazyPage):
        lazy.fill()  # the Library builds its screens on first show
    pages = [w for w in win._window.findChildren(QWidget) if w.property(SCREEN_PROPERTY)]
    problems: list[str] = []
    for page in sorted(pages, key=lambda p: str(p.property(SCREEN_PROPERTY))):
        sid = str(page.property(SCREEN_PROPERTY))
        if only and sid != only:
            continue
        if not any(help_content.load(s) is not None for s in help_content._chain(sid)[:-1]):
            problems.append(f"{sid}: NO HELP FILE (nor any parent screen's)")
        problems.extend(line for line in audit(page) if line.startswith(f"{sid}:"))
    return problems, len(pages)


def _audit_cli(only: str = "") -> int:  # pragma: no cover - developer tool
    import os
    import tempfile
    from pathlib import Path

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])
    from galileo.library.database import db, init_db
    init_db(Path(tempfile.mkdtemp()) / "help_audit.db")
    from galileo.ui.app_window import AppWindow

    problems, screens = audit_window(AppWindow(), only)
    db.close()
    for line in problems:
        print(line)
    print(f"{len(problems)} undocumented item(s) across {screens} tagged screen(s).")
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    args = sys.argv[1:]
    sys.exit(_audit_cli(args[args.index("--audit") + 1] if "--audit" in args and args[-1] != "--audit" else "")
             if "--audit" in args else 0)
