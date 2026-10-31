# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Sessions screen (SES-100 … SES-230): per-Pier, block-based session authoring.

A session region is a thin Qt view (``SessionsPageWidget``, below) over a plain-Python
model (``SessionsScreen``/``SessionRegion``/the block classes) — the model has no Qt
dependency at all, so it can be built, tested, and reasoned about independently of the
drag-and-drop chrome around it.

Scope note: this module covers session *authoring and lifecycle* — creating, ordering,
templating, and scheduling a session's blocks. Translating each block type into real
device I/O at run time is ``galileo.session_exec``'s job, separate,
already-tracked work (see ``TODO.md``'s "Domain logic with no UI" entries for Autofocus,
Plate solving, Calibration, Meridian flip, Safety, Dome, Notifications); only
``NotificationBlock`` has a real ``execute()`` here, since it's the one block whose
execution behavior this domain's own requirements (``SES-150``) actually specify.
"""

from __future__ import annotations

from galileo.ui.qt_helpers import layout_widget, take_widget
import hashlib
import json
import logging
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from galileo.ui.session_runner import get_session_controller
from galileo.ui.session_blocks import (
    AutofocusBlock,
    BlockOrderError,
    CoolCameraBlock,
    DarkCaptureBlock,
    DitherBlock,
    DomeCloseBlock,
    DomeOpenBlock,
    DomeSyncBlock,
    FilterChangeBlock,
    FlatCaptureBlock,
    ForFilterBlock,
    ForObjectBlock,
    GuideStartBlock,
    GuideStopBlock,
    ImageBlock,
    LoopBlock,
    MeridianFlipBlock,
    NotificationBlock,
    ParkMountBlock,
    PlateSolveBlock,
    RegionLockedError,
    SessionBlock,
    TargetBlock,
    UnparkMountBlock,
    WarmCameraBlock,
)

logger = logging.getLogger(__name__)

_SESSION_SUFFIX = ".gses"


def _safe_filename(text: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_ " else "_" for c in text).strip()
    return cleaned or "session"


# ---------------------------------------------------------------------------
# Action blocks (SES-130, SES-140)
# ---------------------------------------------------------------------------


# The v1 action-block catalog (SES-130 MVP tier + SES-140 P2 tier), keyed by class
# name for template (de)serialization — see _block_to_dict/_block_from_dict below.
_BLOCK_CLASSES: dict[str, type] = {
    cls.__name__: cls
    for cls in (
        TargetBlock, ImageBlock, FilterChangeBlock, CoolCameraBlock, WarmCameraBlock,
        AutofocusBlock, PlateSolveBlock, GuideStartBlock, GuideStopBlock, DitherBlock,
        FlatCaptureBlock, ParkMountBlock, UnparkMountBlock, MeridianFlipBlock,
        DomeOpenBlock, DomeCloseBlock, DomeSyncBlock, NotificationBlock,
        ForFilterBlock, ForObjectBlock, DarkCaptureBlock,
    )
}

# Block types that require a preceding Target block in the same region (SES-170).
# Deliberately small: PlateSolveBlock is the SRS/PSD's own literal example. Extend this
# as real ordering rules are specified, rather than guessing at a fuller policy.
_REQUIRES_TARGET: tuple[type, ...] = (PlateSolveBlock,)


def _block_to_dict(block: SessionBlock) -> dict:
    d = asdict(block)
    d["_type"] = type(block).__name__
    return d


def _block_from_dict(d: dict) -> SessionBlock:
    d = dict(d)
    cls = _BLOCK_CLASSES[d.pop("_type")]
    # Drop fields a saved template has that the block no longer defines (e.g. an
    # older Flat Capture's target_adu), so old templates still load.
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Session template (SES-180, SES-190)
# ---------------------------------------------------------------------------

class SessionTemplate:
    """A saved, reusable session procedure (SES-180) — its Target block, if any, is
    a generic placeholder rather than a specific target. Persisted as a named row
    in the shared database (``galileo.library.models.session_template``), not a
    file — see ``SessionRegion.save_as_template``."""

    def __init__(self, blocks: list[SessionBlock]) -> None:
        self.blocks = blocks

    @classmethod
    def load(cls, name: str) -> SessionTemplate:
        from galileo.library.models.session_template import SessionTemplateRecord
        record = SessionTemplateRecord.get_or_none(SessionTemplateRecord.name == name)
        if record is None:
            raise KeyError(f"No session template named {name!r}.")
        return cls(blocks=[_block_from_dict(bd) for bd in json.loads(record.blocks_json)])

    @classmethod
    def list_names(cls) -> list[str]:
        """Every saved template's name, for the Load from Template picker."""
        from galileo.library.models.session_template import SessionTemplateRecord
        return [r.name for r in SessionTemplateRecord.select().order_by(SessionTemplateRecord.name)]


# ---------------------------------------------------------------------------
# Session region (SES-100 … SES-230)
# ---------------------------------------------------------------------------

class SessionRegion:
    """One session: an ordered, per-Pier list of action blocks, with its own
    Save/Save as Template/Load from Template/Schedule/Delete controls (SES-110)."""

    def __init__(self, name: str, scheduler: Any = None) -> None:
        self.name = name
        self.blocks: list[SessionBlock] = []
        self.is_scheduled = False
        self._scheduler = scheduler
        self._job: Any = None
        self._screen: SessionsScreen | None = None
        self._pier_name: str | None = None
        # The camera (a Camera DeviceConfigRecord slot id) this session images with. A session
        # belongs to one camera: every action of its run uses it, whatever the top bar is on.
        self.camera_slot: str = "primary"

    # --- Editing state (SES-210) ------------------------------------------

    @property
    def is_editable(self) -> bool:
        return not self.is_scheduled

    @property
    def boundary_style(self) -> str:
        return "red" if self.is_scheduled else "default"

    # --- Block authoring (SES-120, SES-170) --------------------------------

    def insert_block(self, block: SessionBlock, before: SessionBlock | None = None,
                      after: SessionBlock | None = None) -> None:
        if not self.is_editable:
            raise RegionLockedError(f"Session {self.name!r} is scheduled and read-only.")
        index = len(self.blocks)
        if before is not None:
            index = self.blocks.index(before)
        elif after is not None:
            index = self.blocks.index(after) + 1
        if isinstance(block, _REQUIRES_TARGET) and not any(
            isinstance(b, TargetBlock) for b in self.blocks[:index]
        ):
            raise BlockOrderError(f"{type(block).__name__} requires a preceding Target block.")
        # A block dropped under a loop (or under one of its body blocks) joins
        # that body; the user drags it left to unindent.
        prev = self.blocks[index - 1] if index > 0 else None
        if prev is not None:
            block.indent = prev.indent + (1 if isinstance(prev, LoopBlock) else 0)
        else:
            block.indent = 0
        self.blocks.insert(index, block)
        self._normalize_indents()

    def _max_indent(self, index: int) -> int:
        """Deepest indent the block at *index* may have: one level inside a loop
        directly above it, otherwise no deeper than the block above."""
        if index <= 0:
            return 0
        prev = self.blocks[index - 1]
        return prev.indent + (1 if isinstance(prev, LoopBlock) else 0)

    def _normalize_indents(self) -> None:
        for i, b in enumerate(self.blocks):
            b.indent = max(0, min(b.indent, self._max_indent(i)))

    def body_of(self, block: SessionBlock) -> list[SessionBlock]:
        """The blocks nested beneath *block* (empty unless it's a loop)."""
        start = self.blocks.index(block) + 1
        body = []
        for b in self.blocks[start:]:
            if b.indent <= block.indent:
                break
            body.append(b)
        return body

    def reorder_block(self, block: SessionBlock, index: int) -> None:
        """Move *block* (and, if it's a loop, its whole body) to *index*."""
        if not self.is_editable:
            raise RegionLockedError(f"Session {self.name!r} is scheduled and read-only.")
        group = [block, *self.body_of(block)]
        for b in group:
            self.blocks.remove(b)
        index = min(index, len(self.blocks))
        self.blocks[index:index] = group
        self._normalize_indents()

    def set_indent(self, block: SessionBlock, indent: int) -> None:
        """Indent/unindent *block* (clamped to what's valid at its position). A
        loop's body shifts with it so the nesting under it is preserved."""
        if not self.is_editable:
            raise RegionLockedError(f"Session {self.name!r} is scheduled and read-only.")
        index = self.blocks.index(block)
        new = max(0, min(indent, self._max_indent(index)))
        delta = new - block.indent
        for b in (block, *self.body_of(block)):
            b.indent += delta
        self._normalize_indents()

    def remove_block(self, block: SessionBlock) -> None:
        """Delete *block* from this region (e.g. dragged outside the session
        panel to remove it) — a scheduled/locked region refuses, same as
        every other authoring mutation. A removed loop's body stays, moved
        out one level."""
        if not self.is_editable:
            raise RegionLockedError(f"Session {self.name!r} is scheduled and read-only.")
        self.blocks.remove(block)
        self._normalize_indents()

    # --- Persistence (SES-060, SES-180, SES-190) ---------------------------

    def _store_path(self) -> Path:
        from galileo.platform import get_data_dir
        pier_dir = get_data_dir() / "sessions" / _safe_filename(self._pier_name or "unassigned")
        return pier_dir / f"{_safe_filename(self.name)}{_SESSION_SUFFIX}"

    def save(self) -> None:
        """Persist this region for reuse (SES-060) — not run until Schedule is used."""
        path = self._store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"name": self.name, "camera_slot": self.camera_slot,
                "blocks": [_block_to_dict(b) for b in self.blocks]}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def save_as_template(self, name: str) -> None:
        """Save this region's blocks as a reusable template (SES-180), under *name*
        in the shared database (overwriting any existing template of that name):
        its Target block, if it's the first block, is stored as a generic
        placeholder."""
        from galileo.library.models.session_template import SessionTemplateRecord
        blocks_out = []
        for i, block in enumerate(self.blocks):
            if i == 0 and isinstance(block, TargetBlock):
                block = replace(block, is_placeholder_target=True)
            blocks_out.append(_block_to_dict(block))
        blocks_json = json.dumps(blocks_out)
        SessionTemplateRecord.delete().where(SessionTemplateRecord.name == name).execute()
        SessionTemplateRecord.create(name=name, blocks_json=blocks_json)

    def can_load_from_template(self) -> bool:
        """Load from Template needs an existing concrete Slew To (Target) block to
        substitute the template's placeholder for (SES-190)."""
        return any(
            isinstance(b, TargetBlock) and not b.is_placeholder_target for b in self.blocks
        )

    def load_from_template(self, name: str) -> None:
        if not self.can_load_from_template():
            raise BlockOrderError("Load from Template needs a Slew To block with a target chosen. Add one first.")
        template = SessionTemplate.load(name)
        remaining = (
            template.blocks[1:]
            if template.blocks and isinstance(template.blocks[0], TargetBlock)
            else list(template.blocks)
        )
        self.blocks = self.blocks + remaining
        self._normalize_indents()

    # --- Scheduling (SES-200, SES-210) --------------------------------------

    def _make_job(self):
        from galileo.scheduler import SchedulerJob
        from galileo.session_exec import build_tree, estimate_frames
        target = next((b for b in self.blocks if isinstance(b, TargetBlock)), None)
        job = SchedulerJob(
            name=self.name,
            sequence=self,
            pier_name=self._pier_name or "",
            target_ra=target.ra_deg if target else 0.0,
            target_dec=target.dec_deg if target else 0.0,
        )
        job.total_required = estimate_frames(build_tree(self.blocks))
        return job

    def schedule(self) -> None:
        """Submit this session to the Scheduler (SES-200) — the only control with a
        side effect; authoring alone never runs or queues a session."""
        if self._scheduler is not None:
            self._job = self._make_job()
            self._scheduler.add_job(self._job)
        self.is_scheduled = True

    def deschedule(self) -> None:
        if self._scheduler is not None and self._job is not None:
            self._scheduler.remove_job(self._job)
        self._job = None
        self.is_scheduled = False

    def run_now(self) -> list[Any]:
        """Run control (SCHED-150): schedule this session (if not already) and
        position its job to start immediately on the Schedule timeline, rather
        than leaving it unpositioned for the autoscheduler. Returns any other
        timeline entries on this Pier whose window now overlaps it, for the
        caller to report — conflicts are surfaced, not auto-resolved."""
        import datetime
        if not self.is_scheduled:
            self.schedule()
        self._job.scheduled_start_utc = datetime.datetime.now(datetime.UTC).isoformat()
        if self._scheduler is None:
            return []
        self._scheduler.save()
        return self._scheduler.overlapping_jobs(self._job)

    # --- Deletion (SES-220) --------------------------------------------------

    def delete(self) -> None:
        if self._screen is not None:
            self._screen._remove_region(self)


# ---------------------------------------------------------------------------
# Sessions screen (SES-100, SES-160)
# ---------------------------------------------------------------------------

class SessionsScreen:
    """Owns every session region, grouped per Pier — only the active Pier's own
    regions are shown (SES-100)."""

    def __init__(self, profile: Any = None) -> None:
        self.profile = profile
        self._sessions: dict[str | None, list[SessionRegion]] = {}
        self._active_pier: str | None = None

    def add_session(self, region: SessionRegion, pier_name: str | None) -> SessionRegion:
        region._screen = self
        region._pier_name = pier_name
        self._sessions.setdefault(pier_name, []).append(region)
        return region

    def _remove_region(self, region: SessionRegion) -> None:
        regions = self._sessions.get(region._pier_name, [])
        if region in regions:
            regions.remove(region)

    def set_active_pier(self, name: str | None) -> None:
        self._active_pier = name

    @property
    def visible_sessions(self) -> list[SessionRegion]:
        return list(self._sessions.get(self._active_pier, []))

    def create_session_for_target(self, name: str, ra_deg: float, dec_deg: float) -> SessionRegion:
        """Auto-create a session pre-populated with a Target block (SES-160) — used
        when a target is selected on the Targets/Sky Atlas screen."""
        region = SessionRegion(name=f"{name} Session")
        region.insert_block(TargetBlock(name=name, ra_deg=ra_deg, dec_deg=dec_deg))
        return self.add_session(region, pier_name=self._active_pier)

    def add_session_from_context_menu(self) -> SessionRegion:
        """An equivalent empty session for manual authoring (SES-160)."""
        return self.add_session(SessionRegion(name="New Session"), pier_name=self._active_pier)

    def add_session_from_template(self, template_name: str) -> SessionRegion:
        """A new session pre-filled with every block of a saved template (SES-180),
        including its placeholder Target, for the user to replace with a real one."""
        template = SessionTemplate.load(template_name)
        region = SessionRegion(name=f"{template_name} Session")
        region.blocks = list(template.blocks)
        region._normalize_indents()
        return self.add_session(region, pier_name=self._active_pier)


# ---------------------------------------------------------------------------
# Qt view (SES-100 … SES-230) — a thin layer over the model above
# ---------------------------------------------------------------------------
#
# No existing screen in this codebase uses Qt drag-and-drop, so there's no in-repo
# pattern to extend here. Deliberately kept to QListWidget's built-in drag/drop
# machinery (Qt.ItemDataRole.UserRole item data + a custom dropEvent) rather than a QGraphicsView
# canvas, as SDD 4.6a suggests — a small fraction of the code, and nothing the tests
# require calls for one.

_PALETTE_BLOCK_TYPES: tuple[type[SessionBlock], ...] = (
    TargetBlock, ImageBlock, FilterChangeBlock, CoolCameraBlock, WarmCameraBlock,
    AutofocusBlock, PlateSolveBlock, GuideStartBlock, GuideStopBlock,
    FlatCaptureBlock, ParkMountBlock, UnparkMountBlock,
    DomeOpenBlock, DomeCloseBlock, DomeSyncBlock, ForFilterBlock, ForObjectBlock,
    DarkCaptureBlock,
)
# DitherBlock and MeridianFlipBlock are deliberately not offered in the palette (dither
# and meridian flips are handled elsewhere) but stay in _BLOCK_CLASSES so sessions and
# templates saved with them still load.
_INDENT_PX = 28  # horizontal width of one indent level in a region's block list
_BLOCK_ROLE = Qt.ItemDataRole.UserRole

# A fixed hue (0-359) per block *type*, evenly spaced around the wheel, so every
# kind of block keeps the same colour identity across the app and across theme
# switches (Store a set of colours with each block type). An unlisted type
# (e.g. a plugin-registered block, SES-340) falls back to a hash-derived hue in
# _block_color below, so new types still get a stable colour for free.
_BLOCK_HUES: dict[str, int] = {
    cls.__name__: i * (360 // len(_BLOCK_CLASSES))
    for i, cls in enumerate(_BLOCK_CLASSES.values())
}


def _block_color(kind_name: str, window: Any = None) -> QColor:
    """This block type's colour: a fixed hue identity (_BLOCK_HUES, or a
    hash-derived fallback for an unknown/plugin type) blended lightly into the
    *current* theme's own surface tone, rather than an independently bright,
    saturated colour — so every block reads as a subtle variation on whichever
    theme is active instead of a glaring tile."""
    hue = _BLOCK_HUES.get(kind_name)
    if hue is None:
        digest = hashlib.md5(kind_name.encode("utf-8"), usedforsecurity=False).hexdigest()
        hue = int(digest[:8], 16) % 360
    theme_mgr = getattr(window, "_theme", None)
    if theme_mgr is None:
        from galileo.ui.theme import ThemeManager
        theme_mgr = ThemeManager()
    r, g, b = theme_mgr.block_tint_rgb(hue)
    return QColor(r, g, b)


def _block_item_widget(label_text: str, kind_name: str, window: Any = None,
                       running: bool = False) -> QLabel:
    """A colour-coded, theme-bordered, padded tile for one block — used as the
    item widget for both the palette and a region's block list so a block's
    colour is consistent wherever it appears. *running* marks the block the
    session is executing right now (SES-350) with a heavy accent border."""
    color = _block_color(kind_name, window)
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    text_color = "#000000" if luminance > 140 else "#ffffff"
    theme_mgr = getattr(window, "_theme", None)
    border_color = theme_mgr.palette()["border"] if theme_mgr is not None else "#555555"
    border = "3px solid #2e9e3f" if running else f"1px solid {border_color}"
    widget = QLabel(f"▶ {label_text}" if running else label_text)
    block_cls = _BLOCK_CLASSES.get(kind_name)
    if block_cls is not None:
        widget.setProperty("helpKey", block_cls.label)  # a tile reads "Image: 10×60s…"; its help is the block type's
    widget.setStyleSheet(
        f"QLabel {{"
        f" background-color: {color.name()};"
        f" color: {text_color};"
        f" border: {border};"
        f" border-radius: 4px;"
        f" padding: 6px 10px;"
        f" }}"
    )
    return widget


def _build_palette(window: Any = None, parent=None) -> QListWidget:
    palette = QListWidget(parent)
    palette.setObjectName("SessionPalette")
    palette.setDragEnabled(True)
    palette.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
    palette.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    palette.setMaximumWidth(180)
    palette.setToolTip("Drag a block into a session below to add it.")
    for cls in _PALETTE_BLOCK_TYPES:
        item = QListWidgetItem(cls.label)
        item.setData(_BLOCK_ROLE, cls)
        palette.addItem(item)
        widget = _block_item_widget(cls.label, cls.__name__, window)
        item.setSizeHint(widget.sizeHint())
        if issubclass(cls, _REQUIRES_TARGET):
            widget.setToolTip(f"{cls.label} requires a preceding Target block in the session (SES-170).")
        palette.setItemWidget(item, widget)
    return palette


class BlockListWidget(QListWidget):
    """One session region's ordered block list: accepts a drop from the palette
    (inserts a new block) or from itself (reorders), calling back into the
    region model — this widget never mutates ``region.blocks`` directly.

    Sized to fit every block with no scrollbar of its own — a ``QListWidget``'s
    default ``sizeHint`` is a fixed constant regardless of content, which would
    otherwise clip a region to a few visible rows and force scrolling *inside*
    each session box. Instead this box grows to hold all its blocks, and the
    page-level ``QScrollArea`` (``SessionsPageWidget._regions_area``) is what
    scrolls once several session boxes together no longer fit on screen."""

    def __init__(self, region: SessionRegion, palette: QListWidget, on_changed,
                 window: Any = None, parent=None) -> None:
        super().__init__(parent)
        self._region = region
        self._palette = palette
        self._on_changed = on_changed
        self._window = window
        self._running_block: SessionBlock | None = None
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_right_click)
        self.refresh()

    def refresh(self) -> None:
        self.clear()
        for block in self._region.blocks:
            item = QListWidgetItem(block.display_text)
            item.setData(_BLOCK_ROLE, block)
            self.addItem(item)
            self._set_item_widget(item, block)
        self._fit_height_to_contents()

    def set_running_block(self, block: SessionBlock | None) -> None:
        """Mark *block* as the one executing now (SES-350); ``None`` clears the marker."""
        if block is self._running_block:
            return
        self._running_block = block
        for row in range(self.count()):
            item = self.item(row)
            candidate = item.data(_BLOCK_ROLE)
            self._set_item_widget(item, candidate)

    def _set_item_widget(self, item: QListWidgetItem, block: SessionBlock) -> None:
        """Tile for *block*, inset by its indent level so a loop's body reads as nested."""
        tile = _block_item_widget(block.display_text, type(block).__name__, self._window,
                                  running=block is self._running_block)
        if block.indent:
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(block.indent * _INDENT_PX, 0, 0, 0)
            row.setSpacing(0)
            row.addWidget(tile)
            widget: QWidget = holder
        else:
            widget = tile
        item.setSizeHint(widget.sizeHint())
        self.setItemWidget(item, widget)

    def _on_right_click(self, pos) -> None:
        """Right-click a dragged-in block to open its own parameter dialog
        directly (e.g. an Image block's exposure/count/gain/offset and
        Framing/mosaic control) — no intermediate menu, since editing
        parameters is the only thing a right-click here does. A block with no
        fields at all (Dither, Park Mount, …), or a block in a scheduled
        (locked) session, does nothing."""
        item = self.itemAt(pos)
        if item is None:
            return
        block = item.data(_BLOCK_ROLE)
        if not self._region.is_editable:
            return
        from galileo.ui.session_block_dialogs import has_parameters, open_block_parameter_dialog
        if not has_parameters(type(block)):
            return
        if open_block_parameter_dialog(self, block, self._region, self._window):
            item.setText(block.display_text)
            self._set_item_widget(item, block)

    def _fit_height_to_contents(self) -> None:
        height = 2 * self.frameWidth()
        for row in range(self.count()):
            height += self.sizeHintForRow(row)
        height = max(height, 32)
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)

    def _is_outside_every_session_panel(self, global_pos) -> bool:
        """Whether *global_pos* (screen coordinates) falls outside every drop
        target that counts as "the session panel" — the palette and every
        region's own block list, including other sessions' — used to tell a
        genuine drag-to-delete from a drop that just wasn't accepted (e.g. an
        unsupported cross-region move, which today still does nothing rather
        than deleting the block)."""
        window = self.window()
        targets = [self._palette, *window.findChildren(BlockListWidget)]
        return not any(
            w.isVisible() and w.rect().contains(w.mapFromGlobal(global_pos))
            for w in targets
        )

    def startDrag(self, supportedActions) -> None:
        """Dragging a block out of every session panel (the palette and every
        region's block list) deletes it — the palette is drag-only and never
        accepts a drop, so today's default Qt behavior for a drag nothing
        accepts is to silently leave the source list untouched; this makes
        that same gesture double as "remove this block" instead."""
        item = self.currentItem()
        if item is None:
            return
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QCursor, QDrag
        # Where the drag began, so dropEvent can read horizontal travel as an
        # indent (right) / unindent (left) request.
        self._drag_start_x = self.viewport().mapFromGlobal(QCursor.pos()).x()
        drag = QDrag(self)
        mime_data = self.model().mimeData(self.selectedIndexes()) or QMimeData()
        drag.setMimeData(mime_data)
        drag.setPixmap(self.viewport().grab(self.visualItemRect(item)))
        result = drag.exec(supportedActions, Qt.DropAction.MoveAction)
        if result != Qt.DropAction.IgnoreAction:
            return
        if not self._is_outside_every_session_panel(QCursor.pos()):
            return
        block = item.data(_BLOCK_ROLE)
        if block not in self._region.blocks:
            return
        try:
            self._region.remove_block(block)
        except RegionLockedError as exc:
            QMessageBox.warning(self, "Can't remove block", str(exc))
            return
        self.refresh()
        self._on_changed(None)

    def _accepts_drag(self, event) -> bool:
        return event.source() is self or event.source() is self._palette

    def dragEnterEvent(self, event) -> None:
        # Qt's stock handling refuses a drop whose pointer is still over the
        # dragged block's own row — exactly where an indent/unindent drag (a
        # sideways move on the same row) ends — so dropEvent never ran and
        # dragging left to leave a loop did nothing.
        if self._accepts_drag(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._accepts_drag(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        source = event.source()
        hovered = self.indexAt(event.pos())
        if hovered.row() < 0:
            drop_row = self.count()
        else:
            # Which row the drop lands *before* depends on which half of the
            # hovered row the pointer is in — treating every hover as "insert
            # before this row" (regardless of position within it) made it
            # impossible to drop *after* the last block: with the list's
            # height fit tightly to its content, there's no empty space below
            # the last row to drop into, so e.g. placing a Plate Solve block
            # after an existing (and required) Target block would always be
            # misread as inserting it *before* that Target, failing SES-170's
            # ordering check even though a Target block was already present.
            row_rect = self.visualRect(hovered)
            drop_row = hovered.row() + 1 if event.pos().y() >= row_rect.center().y() else hovered.row()
        before = self._region.blocks[drop_row] if drop_row < len(self._region.blocks) else None
        try:
            if source is self._palette:
                item = self._palette.currentItem()
                if item is None:
                    return
                block_cls = item.data(_BLOCK_ROLE)
                self._region.insert_block(block_cls(), before=before)
            elif source is self:
                item = self.currentItem()
                if item is None:
                    return
                moved = item.data(_BLOCK_ROLE)
                old_index = self._region.blocks.index(moved)
                # Dropping onto its own row or the gap right after it is a pure
                # indent change; otherwise it's a move (the extra step down the
                # list is because the block's own slot disappears first).
                group_len = 1 + len(self._region.body_of(moved))
                if not old_index <= drop_row <= old_index + group_len:
                    if drop_row > old_index:
                        drop_row -= group_len
                    self._region.reorder_block(moved, index=drop_row)
                dx = event.pos().x() - getattr(self, "_drag_start_x", event.pos().x())
                if abs(dx) >= _INDENT_PX // 2:
                    self._region.set_indent(moved, moved.indent + round(dx / _INDENT_PX))
            else:
                return
        except (BlockOrderError, RegionLockedError) as exc:
            QMessageBox.warning(self, "Can't add block", str(exc))
            self._on_changed(str(exc))
            return
        event.acceptProposedAction()
        self._on_changed(None)


class _RegionWidget(QFrame):
    """One session region's card: name, its five controls (SES-110), and its
    block list."""

    def __init__(self, region: SessionRegion, palette: QListWidget, on_reload,
                 window: Any = None, parent=None) -> None:
        super().__init__(parent)
        self._region = region
        self._on_reload = on_reload
        self.setObjectName("SessionRegion")
        self.setFrameShape(QFrame.Shape.Box)
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        name_label = QLabel(region.name)
        name_label.setObjectName("PageSubtitle")
        header.addWidget(name_label, 1)

        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self._save)
        self._template_btn = QPushButton("Save as Template…")
        self._template_btn.clicked.connect(self._save_as_template)
        self._load_btn = QPushButton("Load from Template…")
        self._load_btn.clicked.connect(self._load_from_template)
        self._schedule_btn = QPushButton("Schedule")
        self._schedule_btn.clicked.connect(self._toggle_schedule)
        self._run_btn = QPushButton("Run")
        self._run_btn.setToolTip("Execute this session's blocks now (SES-030); also places it on the "
                                 "Schedule timeline starting now (SCHED-150).")
        self._run_btn.clicked.connect(self._run_now)
        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setToolTip("Hold before the next block or frame (SES-040).")
        self._pause_btn.clicked.connect(self._toggle_pause)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setToolTip("Stop the running session and abort the current exposure or slew (SES-040).")
        self._stop_btn.clicked.connect(self._stop_run)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._delete)
        for btn in (self._save_btn, self._template_btn, self._load_btn, self._schedule_btn,
                    self._run_btn, self._pause_btn, self._stop_btn, self._delete_btn):
            header.addWidget(btn)
        layout.addLayout(header)

        # The camera this session belongs to: every block of its run images with it.
        camera_row = QHBoxLayout()
        camera_row.addWidget(QLabel("Camera:"))
        self._camera_combo = QComboBox()
        self._camera_combo.setMinimumWidth(240)
        self._camera_combo.setToolTip("The camera this session images with. Every action of the session "
                                      "uses it, whichever camera is chosen elsewhere.")
        self._window = window
        self._fill_camera_combo()
        self._camera_combo.activated.connect(self._on_camera_chosen)
        camera_row.addWidget(self._camera_combo)
        camera_row.addStretch(1)
        layout.addLayout(camera_row)

        # Live progress while the session runs (SES-050): state, current block, frame N of M.
        self._progress_label = QLabel("")
        self._progress_label.setObjectName("StatusHint")
        self._progress_label.setWordWrap(True)
        self._progress_label.setVisible(False)
        layout.addWidget(self._progress_label)

        self._blocks_list = BlockListWidget(region, palette, self._on_block_change, window)
        layout.addWidget(self._blocks_list)
        self._controller = get_session_controller(window)
        self._apply_boundary_style()
        self.refresh_run_state()

    def _fill_camera_combo(self) -> None:
        """List the Pier's configured cameras, with the session's own selected. A slot that is
        no longer configured stays listed so the session never silently changes camera."""
        from galileo.ui.app_window._common import _camera_slot_label
        slots: list[str] = []
        pier = getattr(self._window, "_current_pier", None)
        if pier is not None:
            try:
                from galileo.observatory import list_device_config_slots
                slots = list(list_device_config_slots(pier, "camera"))
            except Exception:
                slots = []
        if self._region.camera_slot not in slots:
            slots.append(self._region.camera_slot)
        self._camera_combo.clear()
        for slot in slots:
            self._camera_combo.addItem(_camera_slot_label(slot), slot)
        self._camera_combo.setCurrentIndex(slots.index(self._region.camera_slot))

    def _on_camera_chosen(self, index: int) -> None:
        slot = self._camera_combo.itemData(index)
        if slot and self._region.is_editable:
            self._region.camera_slot = slot

    def _on_block_change(self, error: str | None) -> None:
        self._blocks_list.refresh()
        if error:
            self._on_reload(error)

    def _apply_boundary_style(self) -> None:
        scheduled = self._region.is_scheduled
        self.setStyleSheet(
            "QFrame#SessionRegion { border: 2px solid #cc3333; }" if scheduled
            else "QFrame#SessionRegion { border: 1px solid #555; }"
        )
        self._schedule_btn.setText("Deschedule" if scheduled else "Schedule")
        self._camera_combo.setEnabled(not scheduled)
        self._template_btn.setEnabled(not scheduled)
        self._load_btn.setEnabled(not scheduled and self._region.can_load_from_template())

    def refresh_run_state(self) -> None:
        """Reflect this session's run (if any) in its controls, progress line, and the
        highlighted block (SES-040, SES-050, SES-350)."""
        from galileo.session_exec import RunState
        run = self._controller.run_for(self._region)
        running = run is not None
        # While running, nothing that edits or withdraws the session is available.
        for btn in (self._save_btn, self._template_btn, self._load_btn, self._schedule_btn,
                    self._delete_btn, self._run_btn):
            btn.setEnabled(not running)
        self._camera_combo.setEnabled(not running and self._region.is_editable)
        if not running:
            self._apply_boundary_style()
        self._pause_btn.setVisible(running)
        self._stop_btn.setVisible(running)
        self._progress_label.setVisible(running)
        if run is None:
            self._blocks_list.set_running_block(None)
            return
        progress = run.progress
        paused = progress.state == RunState.PAUSED
        self._pause_btn.setText("Resume" if paused else "Pause")
        self._blocks_list.set_running_block(progress.block)
        bits = ["Paused" if paused else "Running"]
        if progress.block_total:
            bits.append(f"block {progress.block_index} of {progress.block_total}")
        if progress.frames_total:
            bits.append(f"frame {progress.frames_done} of {progress.frames_total}")
        text = " · ".join(bits)
        if progress.message:
            text += f" — {progress.message}"
        self._progress_label.setText(text)

    def _save(self) -> None:
        self._region.save()

    def _save_as_template(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save as Template", "Template name:",
            QLineEdit.EchoMode.Normal, self._region.name)
        name = name.strip()
        if ok and name:
            self._region.save_as_template(name)

    def _load_from_template(self) -> None:
        names = SessionTemplate.list_names()
        if not names:
            QMessageBox.information(self, "Load from Template", "No saved templates yet.")
            return
        name, ok = QInputDialog.getItem(
            self, "Load from Template", "Template:", names, editable=False)
        if not ok:
            return
        try:
            self._region.load_from_template(name)
        except BlockOrderError as exc:
            QMessageBox.warning(self, "Load from Template", str(exc))
            return
        self._blocks_list.refresh()

    def _toggle_schedule(self) -> None:
        if self._region.is_scheduled:
            self._region.deschedule()
        else:
            self._region.schedule()
        self._apply_boundary_style()

    def _run_now(self) -> None:
        """Execute this session immediately (SES-030). It is not put on the Schedule; if a
        scheduled session is running on the Pier it is stopped to make way."""
        problems, conflicts = self._controller.start_region(self._region)
        if problems:
            QMessageBox.warning(self, "Can't run session", "\n".join(f"• {p}" for p in problems))
            return
        self._apply_boundary_style()
        self.refresh_run_state()
        if conflicts:
            names = ", ".join(c.name for c in conflicts)
            # Parent the dialog to the main window, not this card: the run's progress signals
            # rebuild the session cards (a finished session is reaped), deleting this widget while
            # the modal dialog is still open on it — a native crash.
            QMessageBox.warning(
                self.window(), "Run", f"{self._region.name!r} is running now, but overlaps: {names}. "
                             "Resolve the conflict on the Schedule screen.")

    def _toggle_pause(self) -> None:
        if self._controller.run_for(self._region) is None:
            return
        if self._pause_btn.text() == "Resume":
            self._controller.resume(self._region)
        else:
            self._controller.pause(self._region)

    def _stop_run(self) -> None:
        self._controller.stop(self._region)
        self._progress_label.setText("Stopping…")

    def _delete(self) -> None:
        self._region.delete()
        self._on_reload(None)


class SessionsPageWidget(QWidget):
    """Planning > Sessions (SES-100 … SES-230). Constructed once by
    ``AppWindow._build_sessions_page`` and kept in sync with the active Pier via
    ``reload()``, following the same ``self._device_pages[...] = {"reload": ...}``
    convention every other per-Pier page uses."""

    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("SessionsPage")
        self._window = window
        self.sessions_screen = SessionsScreen()
        self._local_schedulers: dict[str, Any] = {}  # fallback when window lacks _scheduler_for_pier
        self._controller = get_session_controller(window)
        self._controller.changed.connect(self._on_run_changed)
        if hasattr(window, "_scheduler_for_pier"):
            self._controller.start_ticking()      # fire scheduled sessions as their start time arrives
            self.destroyed.connect(self._controller.stop_ticking)
        self._build()
        self.reload()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        title = QLabel("Sessions")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        self._status = QLabel("")
        self._status.setObjectName("StatusHint")
        outer.addWidget(self._status)

        body = QHBoxLayout()
        outer.addLayout(body, 1)

        add_col = QVBoxLayout()
        self._regions_area = QScrollArea()
        self._regions_area.setWidgetResizable(True)
        regions_container = QWidget()
        self._regions_layout = QVBoxLayout(regions_container)
        self._regions_layout.addStretch(1)
        self._regions_area.setWidget(regions_container)
        add_col.addWidget(self._regions_area, 1)

        add_btn = QPushButton("Add Session")
        add_btn.setObjectName("AccentButton")
        add_btn.clicked.connect(self._add_session_from_menu)
        add_tpl_btn = QPushButton("Add Session from Template")
        add_tpl_btn.clicked.connect(self._add_session_from_template)
        buttons = QHBoxLayout()
        buttons.addWidget(add_btn)
        buttons.addWidget(add_tpl_btn)
        add_col.addLayout(buttons)
        body.addLayout(add_col, 1)

        self._palette = _build_palette(self._window, self)
        body.addWidget(self._palette)

    def _scheduler_for(self, pier_name: str | None):
        """The Pier's shared ``ObservatoryScheduler`` (owned by ``AppWindow`` so
        Planning > Schedule sees the same jobs), or a local fallback instance when
        used standalone (e.g. outside a real ``AppWindow``, in a smoke test)."""
        get_scheduler = getattr(self._window, "_scheduler_for_pier", None)
        if get_scheduler is not None:
            return get_scheduler(pier_name)
        from galileo.scheduler import ObservatoryScheduler
        key = pier_name or ""
        if key not in self._local_schedulers:
            self._local_schedulers[key] = ObservatoryScheduler()
        return self._local_schedulers[key]

    def _default_camera_slot(self) -> str:
        """A new session starts on the camera the top bar is on; it can be changed on the card."""
        return getattr(self._window, "_active_camera_slot", None) or "primary"

    def _active_pier_name(self) -> str | None:
        pier = getattr(self._window, "_current_pier", None)
        return getattr(pier, "name", None)

    def create_session_for_target(self, name: str, ra_deg: float, dec_deg: float) -> None:
        """Called when a target is selected elsewhere in the app (SES-160)."""
        region = self.sessions_screen.create_session_for_target(name, ra_deg, dec_deg)
        region.camera_slot = self._default_camera_slot()
        region._scheduler = self._scheduler_for(region._pier_name)
        self._rebuild_regions()

    def _add_session_from_menu(self) -> None:
        region = self.sessions_screen.add_session_from_context_menu()
        region.camera_slot = self._default_camera_slot()
        region._scheduler = self._scheduler_for(region._pier_name)
        self._rebuild_regions()

    def _add_session_from_template(self) -> None:
        names = SessionTemplate.list_names()
        if not names:
            QMessageBox.information(self, "Add Session from Template", "No saved templates yet.")
            return
        name, ok = QInputDialog.getItem(
            self, "Add Session from Template", "Template:", names, editable=False)
        if not ok or not name:
            return
        try:
            region = self.sessions_screen.add_session_from_template(name)
        except KeyError as exc:
            QMessageBox.warning(self, "Add Session from Template", str(exc))
            return
        region.camera_slot = self._default_camera_slot()
        region._scheduler = self._scheduler_for(region._pier_name)
        self._rebuild_regions()

    def reload(self) -> None:
        """Show the active Pier's own sessions (SES-100) — reaping any that finished
        (their scheduled job completed) before rebuilding, so a completed session
        disappears here too, not only from Planning > Schedule."""
        pier_name = self._active_pier_name()
        self._scheduler_for(pier_name).reap_completed_jobs()
        self.sessions_screen.set_active_pier(pier_name)
        self._rebuild_regions()

    def _on_run_changed(self, _pier_key=None) -> None:
        """A run started, progressed, or finished: update the cards in place, and rebuild once
        no run is left (a completed session is reaped and its card must go — SES-210)."""
        if not self._controller.is_running():
            self.reload()
            return
        for i in range(self._regions_layout.count()):
            widget = layout_widget(self._regions_layout, i)
            if isinstance(widget, _RegionWidget):
                widget.refresh_run_state()

    def _rebuild_regions(self, status: str | None = None) -> None:
        while self._regions_layout.count() > 1:
            w = take_widget(self._regions_layout)
            if w is not None:
                w.deleteLater()
        for region in self.sessions_screen.visible_sessions:
            widget = _RegionWidget(region, self._palette, self._rebuild_regions, self._window)
            self._regions_layout.insertWidget(self._regions_layout.count() - 1, widget)
        pier_name = self._active_pier_name()
        if status:
            self._status.setText(status)
        elif pier_name is None:
            self._status.setText("Create a Pier to author sessions.")
        else:
            self._status.setText(f"{len(self.sessions_screen.visible_sessions)} session(s) for {pier_name}.")
