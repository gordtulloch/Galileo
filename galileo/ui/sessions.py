# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Sessions screen (SES-100 … SES-230): per-Pier, block-based session authoring.

A session region is a thin Qt view (``SessionsPageWidget``, below) over a plain-Python
model (``SessionsScreen``/``SessionRegion``/the block classes) — the model has no Qt
dependency at all, so it can be built, tested, and reasoned about independently of the
drag-and-drop chrome around it.

Scope note: this module covers session *authoring and lifecycle* — creating, ordering,
templating, and scheduling a session's blocks. Translating each block type into real
device I/O against ``galileo.sequencer.basic``/``.advanced`` at run time is separate,
already-tracked work (see ``TODO.md``'s "Domain logic with no UI" entries for Autofocus,
Plate solving, Calibration, Meridian flip, Safety, Dome, Notifications); only
``NotificationBlock`` has a real ``execute()`` here, since it's the one block whose
execution behavior this domain's own requirements (``SES-150``) actually specify.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
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

logger = logging.getLogger(__name__)

_SESSION_SUFFIX = ".gses"


class BlockOrderError(Exception):
    """A block was inserted, or a template loaded, in violation of an ordering rule."""


class RegionLockedError(Exception):
    """A scheduled (locked) session region was edited."""


def _safe_filename(text: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_ " else "_" for c in text).strip()
    return cleaned or "session"


# ---------------------------------------------------------------------------
# Action blocks (SES-130, SES-140)
# ---------------------------------------------------------------------------

class SessionBlock:
    """Base for every action block. Subclasses are plain dataclasses; ``label`` is
    the palette's display text for that block type (a class attribute, not a field)."""
    label: ClassVar[str] = "Block"

    @property
    def display_text(self) -> str:
        """Text shown for one block *instance* in a region's block list — defaults
        to the type's palette ``label``, but a block can override this to surface
        its own identifying data (e.g. a Target block's chosen target name)."""
        return self.label


@dataclass
class TargetBlock(SessionBlock):
    label: ClassVar[str] = "Target"
    name: str = ""
    ra_deg: float = 0.0
    dec_deg: float = 0.0
    is_placeholder_target: bool = False

    @property
    def display_text(self) -> str:
        return f"{self.label}: {self.name}" if self.name else self.label


@dataclass
class ImageBlock(SessionBlock):
    """Mirrors the Imaging tab's own capture-parameter model (exposure, count, filter,
    binning, gain/offset, frame type), plus its own Framing… control (SES-130, FRAME-070)
    — kept separate from the Imaging tab's, per SDD 4.6a."""
    label: ClassVar[str] = "Image"
    exposure: float = 60.0
    count: int = 1
    filter: str = ""
    binning: int = 1
    gain: int | None = None
    offset: int | None = None
    frame_type: str = "Light"

    def __post_init__(self) -> None:
        # Not a dataclass field on purpose: a Mosaic isn't JSON-serializable, and
        # mosaic state doesn't need to round-trip through Save as Template (a template
        # captures a repeatable procedure, not a specific framing) — see module docstring.
        self._mosaic: Any = None

    @property
    def has_mosaic(self) -> bool:
        return self._mosaic is not None

    def set_mosaic(self, mosaic: Any) -> None:
        self._mosaic = mosaic

    def execution_model(self) -> str:
        """Which capture-order model this block's execution should follow (SES-230)."""
        return "mosaic_round_robin" if self.has_mosaic else "single_target"

    def open_framing_assistant(self, parent: Any = None) -> None:
        """Open the Framing Assistant against this block's own stored framing definition
        (SES-130, FRAME-070). The assistant dialog itself (IMG-180/FRAME-070) isn't built
        yet — this hook exists so the palette/region UI has something real to call once it
        is, rather than being wired up twice."""
        logger.info("Framing Assistant requested for an Image block (FRAME-070 not yet built).")


@dataclass
class FilterChangeBlock(SessionBlock):
    label: ClassVar[str] = "Filter Change"
    filter: str = ""


@dataclass
class CoolCameraBlock(SessionBlock):
    label: ClassVar[str] = "Cool Camera"
    setpoint_c: float = -10.0


@dataclass
class WarmCameraBlock(SessionBlock):
    label: ClassVar[str] = "Warm Camera"


@dataclass
class AutofocusBlock(SessionBlock):
    label: ClassVar[str] = "Autofocus"
    filter: str | None = None  # None = focus on the current filter


@dataclass
class PlateSolveBlock(SessionBlock):
    label: ClassVar[str] = "Plate Solve"


@dataclass
class GuideStartBlock(SessionBlock):
    label: ClassVar[str] = "Guide Start"
    calibrate: bool = False


@dataclass
class GuideStopBlock(SessionBlock):
    label: ClassVar[str] = "Guide Stop"


@dataclass
class DitherBlock(SessionBlock):
    label: ClassVar[str] = "Dither"


@dataclass
class FlatCaptureBlock(SessionBlock):
    label: ClassVar[str] = "Flat Capture"
    count: int = 1
    target_adu: float = 0.0


@dataclass
class ParkMountBlock(SessionBlock):
    label: ClassVar[str] = "Park Mount"


@dataclass
class UnparkMountBlock(SessionBlock):
    label: ClassVar[str] = "Unpark Mount"


@dataclass
class MeridianFlipBlock(SessionBlock):
    label: ClassVar[str] = "Meridian Flip"


@dataclass
class DomeOpenBlock(SessionBlock):
    label: ClassVar[str] = "Dome Open"


@dataclass
class DomeCloseBlock(SessionBlock):
    label: ClassVar[str] = "Dome Close"


@dataclass
class DomeSyncBlock(SessionBlock):
    label: ClassVar[str] = "Dome Sync"


@dataclass
class NotificationBlock(SessionBlock):
    label: ClassVar[str] = "Notification"
    message: str = ""

    async def execute(self, context: Any) -> None:
        """Send this block's message via the owning Observatory's configured contact
        channel(s) (SES-150, traces to NOTIF-010/OBS-090)."""
        await context.notify_service.emit(self.message)


# The v1 action-block catalog (SES-130 MVP tier + SES-140 P2 tier), keyed by class
# name for template (de)serialization — see _block_to_dict/_block_from_dict below.
_BLOCK_CLASSES: dict[str, type] = {
    cls.__name__: cls
    for cls in (
        TargetBlock, ImageBlock, FilterChangeBlock, CoolCameraBlock, WarmCameraBlock,
        AutofocusBlock, PlateSolveBlock, GuideStartBlock, GuideStopBlock, DitherBlock,
        FlatCaptureBlock, ParkMountBlock, UnparkMountBlock, MeridianFlipBlock,
        DomeOpenBlock, DomeCloseBlock, DomeSyncBlock, NotificationBlock,
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
    return cls(**d)


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
        self.blocks.insert(index, block)

    def reorder_block(self, block: SessionBlock, index: int) -> None:
        if not self.is_editable:
            raise RegionLockedError(f"Session {self.name!r} is scheduled and read-only.")
        self.blocks.remove(block)
        self.blocks.insert(index, block)

    # --- Persistence (SES-060, SES-180, SES-190) ---------------------------

    def _store_path(self) -> Path:
        from galileo.platform import get_data_dir
        pier_dir = get_data_dir() / "sessions" / _safe_filename(self._pier_name or "unassigned")
        return pier_dir / f"{_safe_filename(self.name)}{_SESSION_SUFFIX}"

    def save(self) -> None:
        """Persist this region for reuse (SES-060) — not run until Schedule is used."""
        path = self._store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"name": self.name, "blocks": [_block_to_dict(b) for b in self.blocks]}
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
        """Load from Template needs an existing concrete Target block to substitute
        the template's placeholder for (SES-190)."""
        return (
            bool(self.blocks)
            and isinstance(self.blocks[0], TargetBlock)
            and not self.blocks[0].is_placeholder_target
        )

    def load_from_template(self, name: str) -> None:
        if not self.can_load_from_template():
            raise BlockOrderError("Load from Template requires an existing concrete Target block.")
        template = SessionTemplate.load(name)
        remaining = (
            template.blocks[1:]
            if template.blocks and isinstance(template.blocks[0], TargetBlock)
            else list(template.blocks)
        )
        self.blocks = self.blocks + remaining

    # --- Scheduling (SES-200, SES-210) --------------------------------------

    def _make_job(self):
        from galileo.scheduler import SchedulerJob
        target = next((b for b in self.blocks if isinstance(b, TargetBlock)), None)
        return SchedulerJob(
            name=self.name,
            sequence=self,
            pier_name=self._pier_name or "",
            target_ra=target.ra_deg if target else 0.0,
            target_dec=target.dec_deg if target else 0.0,
        )

    def schedule(self) -> None:
        """Submit this session to the Scheduler (SES-200) — the only control with a
        side effect; authoring alone never runs or queues a session."""
        if self._scheduler is not None:
            self._job = self._make_job()
            self._scheduler.add_job(self._job)
        self.is_scheduled = True

    def deschedule(self) -> None:
        if self._scheduler is not None:
            self._scheduler.remove_job(self._job)
        self._job = None
        self.is_scheduled = False

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




# ---------------------------------------------------------------------------
# Qt view (SES-100 … SES-230) — a thin layer over the model above
# ---------------------------------------------------------------------------
#
# No existing screen in this codebase uses Qt drag-and-drop, so there's no in-repo
# pattern to extend here. Deliberately kept to QListWidget's built-in drag/drop
# machinery (Qt.UserRole item data + a custom dropEvent) rather than a QGraphicsView
# canvas, as SDD 4.6a suggests — a small fraction of the code, and nothing the tests
# require calls for one.

_PALETTE_BLOCK_TYPES: tuple[type[SessionBlock], ...] = (
    TargetBlock, ImageBlock, FilterChangeBlock, CoolCameraBlock, WarmCameraBlock,
    AutofocusBlock, PlateSolveBlock, GuideStartBlock, GuideStopBlock, DitherBlock,
    FlatCaptureBlock, ParkMountBlock, UnparkMountBlock, MeridianFlipBlock,
    DomeOpenBlock, DomeCloseBlock, DomeSyncBlock,
)
_BLOCK_ROLE = Qt.UserRole


def _block_color(kind_name: str) -> QColor:
    """A stable, visually distinct colour per block *type* (hashed from its class
    name), so every kind of block reads at a glance and new — including
    plugin-registered (SES-340) — block types get one for free without a
    hand-maintained colour table."""
    digest = hashlib.md5(kind_name.encode("utf-8")).hexdigest()
    hue = int(digest[:8], 16) % 360
    return QColor.fromHsv(hue, 150, 210)


def _block_item_widget(label_text: str, kind_name: str) -> QLabel:
    """A colour-coded, white-bordered, padded tile for one block — used as the
    item widget for both the palette and a region's block list so a block's
    colour is consistent wherever it appears."""
    color = _block_color(kind_name)
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    text_color = "#000000" if luminance > 140 else "#ffffff"
    widget = QLabel(label_text)
    widget.setStyleSheet(
        f"QLabel {{"
        f" background-color: {color.name()};"
        f" color: {text_color};"
        f" border: 2px solid white;"
        f" border-radius: 4px;"
        f" padding: 6px 10px;"
        f" }}"
    )
    return widget


def _build_palette(parent=None) -> QListWidget:
    palette = QListWidget(parent)
    palette.setObjectName("SessionPalette")
    palette.setDragEnabled(True)
    palette.setDragDropMode(QAbstractItemView.DragOnly)
    palette.setSelectionMode(QAbstractItemView.SingleSelection)
    palette.setMaximumWidth(180)
    palette.setToolTip("Drag a block into a session below to add it.")
    for cls in _PALETTE_BLOCK_TYPES:
        item = QListWidgetItem(cls.label)
        item.setData(_BLOCK_ROLE, cls)
        palette.addItem(item)
        widget = _block_item_widget(cls.label, cls.__name__)
        item.setSizeHint(widget.sizeHint())
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

    def __init__(self, region: SessionRegion, palette: QListWidget, on_changed, parent=None) -> None:
        super().__init__(parent)
        self._region = region
        self._palette = palette
        self._on_changed = on_changed
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh()

    def refresh(self) -> None:
        self.clear()
        for block in self._region.blocks:
            item = QListWidgetItem(block.display_text)
            item.setData(_BLOCK_ROLE, block)
            self.addItem(item)
            widget = _block_item_widget(block.display_text, type(block).__name__)
            item.setSizeHint(widget.sizeHint())
            self.setItemWidget(item, widget)
        self._fit_height_to_contents()

    def _fit_height_to_contents(self) -> None:
        height = 2 * self.frameWidth()
        for row in range(self.count()):
            height += self.sizeHintForRow(row)
        height = max(height, 32)
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)

    def dropEvent(self, event) -> None:
        source = event.source()
        drop_row = self.indexAt(event.pos()).row()
        if drop_row < 0:
            drop_row = self.count()
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
                self._region.reorder_block(item.data(_BLOCK_ROLE), index=drop_row)
            else:
                return
        except (BlockOrderError, RegionLockedError) as exc:
            self._on_changed(str(exc))
            return
        event.acceptProposedAction()
        self._on_changed(None)


class _RegionWidget(QFrame):
    """One session region's card: name, its five controls (SES-110), and its
    block list."""

    def __init__(self, region: SessionRegion, palette: QListWidget, on_reload, parent=None) -> None:
        super().__init__(parent)
        self._region = region
        self._on_reload = on_reload
        self.setObjectName("SessionRegion")
        self.setFrameShape(QFrame.Box)
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
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._delete)
        for btn in (self._save_btn, self._template_btn, self._load_btn,
                    self._schedule_btn, self._delete_btn):
            header.addWidget(btn)
        layout.addLayout(header)

        self._blocks_list = BlockListWidget(region, palette, self._on_block_change)
        layout.addWidget(self._blocks_list)
        self._apply_boundary_style()

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
        self._template_btn.setEnabled(not scheduled)
        self._load_btn.setEnabled(not scheduled and self._region.can_load_from_template())

    def _save(self) -> None:
        self._region.save()

    def _save_as_template(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save as Template", "Template name:",
            QLineEdit.Normal, self._region.name)
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
        self.screen = SessionsScreen()
        self._local_schedulers: "dict[str, Any]" = {}  # fallback when window lacks _scheduler_for_pier
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
        add_col.addWidget(add_btn)
        body.addLayout(add_col, 1)

        self._palette = _build_palette(self)
        body.addWidget(self._palette)

    def _scheduler_for(self, pier_name: "str | None"):
        """The Pier's shared ``ObservatoryScheduler`` (owned by ``AppWindow`` so
        Planning > Scheduler sees the same jobs), or a local fallback instance when
        used standalone (e.g. outside a real ``AppWindow``, in a smoke test)."""
        get_scheduler = getattr(self._window, "_scheduler_for_pier", None)
        if get_scheduler is not None:
            return get_scheduler(pier_name)
        from galileo.scheduler import ObservatoryScheduler
        key = pier_name or ""
        if key not in self._local_schedulers:
            self._local_schedulers[key] = ObservatoryScheduler()
        return self._local_schedulers[key]

    def _active_pier_name(self) -> str | None:
        pier = getattr(self._window, "_current_pier", None)
        return getattr(pier, "name", None)

    def create_session_for_target(self, name: str, ra_deg: float, dec_deg: float) -> None:
        """Called when a target is selected elsewhere in the app (SES-160)."""
        region = self.screen.create_session_for_target(name, ra_deg, dec_deg)
        region._scheduler = self._scheduler_for(region._pier_name)
        self._rebuild_regions()

    def _add_session_from_menu(self) -> None:
        region = self.screen.add_session_from_context_menu()
        region._scheduler = self._scheduler_for(region._pier_name)
        self._rebuild_regions()

    def reload(self) -> None:
        """Show the active Pier's own sessions (SES-100) — reaping any that finished
        (their scheduled job completed) before rebuilding, so a completed session
        disappears here too, not only from Planning > Scheduler."""
        pier_name = self._active_pier_name()
        self._scheduler_for(pier_name).reap_completed_jobs()
        self.screen.set_active_pier(pier_name)
        self._rebuild_regions()

    def _rebuild_regions(self, status: str | None = None) -> None:
        while self._regions_layout.count() > 1:
            item = self._regions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for region in self.screen.visible_sessions:
            widget = _RegionWidget(region, self._palette, self._rebuild_regions)
            self._regions_layout.insertWidget(self._regions_layout.count() - 1, widget)
        pier_name = self._active_pier_name()
        if status:
            self._status.setText(status)
        elif pier_name is None:
            self._status.setText("Create a Pier to author sessions.")
        else:
            self._status.setText(f"{len(self.screen.visible_sessions)} session(s) for {pier_name}.")
