# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Sessions screen's block model: every kind of session block (instruction, loop, trigger) and their ordering rules."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class BlockOrderError(Exception):
    """A block was inserted, or a template loaded, in violation of an ordering rule."""


class RegionLockedError(Exception):
    """A scheduled (locked) session region was edited."""


@dataclass
class SessionBlock:
    """Base for every action block. Subclasses are plain dataclasses; ``label`` is
    the palette's display text for that block type (a class attribute, not a field).

    ``indent`` is the block's nesting depth: a block indented one level deeper than
    the loop block (``LoopBlock``) above it is that loop's body. It is keyword-only so
    it never disturbs a subclass's own positional fields, and ``SessionRegion``
    keeps it consistent (no indent without a loop above to own it)."""
    label: ClassVar[str] = "Block"
    indent: int = field(default=0, kw_only=True)

    @property
    def display_text(self) -> str:
        """Text shown for one block *instance* in a region's block list — defaults
        to the type's palette ``label``, but a block can override this to surface
        its own identifying data (e.g. a Target block's chosen target name)."""
        return self.label


@dataclass
class TargetBlock(SessionBlock):
    label: ClassVar[str] = "Slew To"
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
    def display_text(self) -> str:
        bits = [f"{self.count}×{self.exposure:g}s"]
        if self.filter:
            bits.append(self.filter)
        bits.append(f"bin{self.binning}")
        if self.frame_type != "Light":
            bits.append(self.frame_type)
        if self.gain is not None:
            bits.append(f"gain {self.gain}")
        if self.offset is not None:
            bits.append(f"offset {self.offset}")
        if self.has_mosaic:
            m = self.mosaic
            bits.append(f"{m.cols}×{m.rows} mosaic")
        return f"{self.label}: {' '.join(bits)}"

    @property
    def has_mosaic(self) -> bool:
        return self._mosaic is not None

    @property
    def mosaic(self) -> Any:
        return self._mosaic

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

    @property
    def display_text(self) -> str:
        return f"{self.label}: {self.filter}" if self.filter else self.label


@dataclass
class CoolCameraBlock(SessionBlock):
    label: ClassVar[str] = "Cool Camera"
    setpoint_c: float = -10.0

    @property
    def display_text(self) -> str:
        return f"{self.label}: {self.setpoint_c:g}°C"


@dataclass
class WarmCameraBlock(SessionBlock):
    label: ClassVar[str] = "Warm Camera"


@dataclass
class AutofocusBlock(SessionBlock):
    label: ClassVar[str] = "Autofocus"
    filter: str | None = None  # None = focus on the current filter

    @property
    def display_text(self) -> str:
        return f"{self.label}: {self.filter}" if self.filter else self.label


@dataclass
class PlateSolveBlock(SessionBlock):
    label: ClassVar[str] = "Plate Solve"


@dataclass
class GuideStartBlock(SessionBlock):
    label: ClassVar[str] = "Guide Start"
    calibrate: bool = False

    @property
    def display_text(self) -> str:
        return f"{self.label} + Calibrate" if self.calibrate else self.label


@dataclass
class GuideStopBlock(SessionBlock):
    label: ClassVar[str] = "Guide Stop"


@dataclass
class DitherBlock(SessionBlock):
    label: ClassVar[str] = "Dither"


@dataclass
class FlatCaptureBlock(SessionBlock):
    """Same parameters as the Imaging page's Flats Assistant (CAL-060): flat method,
    exposure (0 = calculate), frame count, filter ("All" = every filter in turn),
    ADU method and exposure increment."""
    label: ClassVar[str] = "Flat Capture"
    method: str = "Sky Flats"
    exposure: float = 0.0
    count: int = 10
    filter: str = "All"
    adu_method: str = "Average"
    exposure_increment: float = 0.1

    @property
    def display_text(self) -> str:
        bits = [f"{self.count}×", self.filter or "All", self.method]
        bits.append(f"{self.exposure:g}s" if self.exposure else "auto exposure")
        return f"{self.label}: {' '.join(bits)}"


@dataclass
class DarkCaptureBlock(SessionBlock):
    """Same parameters as the Imaging page's Darks Assistant: one dark frame at each
    exposure length, optionally selecting a filter first."""
    label: ClassVar[str] = "Dark Capture"
    filter: str = ""
    exposures: list[float] = field(default_factory=lambda: [10.0, 20.0, 30.0, 60.0])
    # Close the Pier's dust cover / flip-flat panel (if it has one) for the darks.
    close_cover: bool = False

    @property
    def display_text(self) -> str:
        bits = [", ".join(f"{e:g}" for e in self.exposures) + " s"]
        if self.filter:
            bits.append(self.filter)
        if self.close_cover:
            bits.append("cover closed")
        return f"{self.label}: {' '.join(bits)}"


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


class LoopBlock(SessionBlock):
    """Marker base for blocks that repeat the blocks indented beneath them."""
    label: ClassVar[str] = "Loop"


@dataclass
class ForFilterBlock(LoopBlock):
    """FOR [filter] in <list>: repeat the indented blocks once per filter."""
    label: ClassVar[str] = "FOR Filter"
    filters: list[str] = field(default_factory=list)

    @property
    def display_text(self) -> str:
        return f"FOR Filter in [{', '.join(self.filters)}]" if self.filters else self.label


@dataclass
class ForObjectBlock(LoopBlock):
    """FOR [object] in <list>: repeat the indented blocks once per object."""
    label: ClassVar[str] = "FOR Object"
    # Each entry: {"name": str, "ra_deg": float, "dec_deg": float} — coordinates
    # are kept so the loop can slew to each object without a second lookup.
    objects: list[dict] = field(default_factory=list)

    @property
    def display_text(self) -> str:
        if not self.objects:
            return self.label
        text = ", ".join(o["name"] for o in self.objects)
        text = text if len(text) <= 40 else text[:37] + "…"
        return f"FOR Object in [{text}]"


@dataclass
class NotificationBlock(SessionBlock):
    label: ClassVar[str] = "Notification"
    message: str = ""

    @property
    def display_text(self) -> str:
        if not self.message:
            return self.label
        msg = self.message if len(self.message) <= 40 else self.message[:37] + "…"
        return f"{self.label}: {msg}"

    async def execute(self, context: Any) -> None:
        """Send this block's message via the owning Observatory's configured contact
        channel(s) (SES-150, traces to NOTIF-010/OBS-090)."""
        if context.notify_service is None:
            raise RuntimeError("no notification service is configured")
        from galileo.notify import NotificationEvent
        await context.notify_service.emit(NotificationEvent.SESSION_MESSAGE, self.message)
