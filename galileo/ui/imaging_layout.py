# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Imaging-tab panel layout model (UI-020, IMG-080).

Plain Python, no Qt: the ordered list of the Imaging tab's movable panels and which
of them are hidden. The Qt view (``galileo.ui.app_window._imaging_page``) applies it
to the page's widgets; ``ImagingLayoutStore`` persists it per user through
``galileo.ui.theme.LayoutManager`` (the shared database), so it
is restored at start-up. Saved data is treated as untrusted: unknown panels are
dropped and panels added since it was saved are appended in their default place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: Movable panels in default order: (id, label). "settings" holds the capture
#: controls and is not listed because it must always stay reachable.
PANELS: tuple[tuple[str, str], ...] = (
    ("view", "View settings"),
    ("nudge", "Mount Nudge"),
    ("stretch", "Stretch slider"),
    ("histogram", "Histogram"),
    ("progress", "Progress"),
    ("log", "Log"),
)
DEFAULT_ORDER: tuple[str, ...] = tuple(pid for pid, _ in PANELS)
PANEL_LABELS: dict[str, str] = dict(PANELS)
LAYOUT_KEY = "imaging.panels"


@dataclass
class ImagingLayout:
    """Order and visibility of the Imaging tab's panels."""

    order: list[str] = field(default_factory=lambda: list(DEFAULT_ORDER))
    hidden: set[str] = field(default_factory=set)

    def is_visible(self, panel_id: str) -> bool:
        return panel_id not in self.hidden

    def set_visible(self, panel_id: str, visible: bool) -> None:
        if panel_id not in PANEL_LABELS:
            raise KeyError(panel_id)
        (self.hidden.discard if visible else self.hidden.add)(panel_id)

    def move(self, panel_id: str, offset: int) -> bool:
        """Move a panel by ``offset`` places (clamped); True if its position changed."""
        old = self.order.index(panel_id)
        new = max(0, min(len(self.order) - 1, old + offset))
        if new == old:
            return False
        self.order.insert(new, self.order.pop(old))
        return True

    def reset(self) -> None:
        self.order = list(DEFAULT_ORDER)
        self.hidden = set()

    def is_default(self) -> bool:
        return self.order == list(DEFAULT_ORDER) and not self.hidden

    def to_dict(self) -> dict:
        return {"order": list(self.order), "hidden": [p for p in self.order if p in self.hidden]}

    @classmethod
    def from_dict(cls, data: object) -> ImagingLayout:
        layout = cls()
        if not isinstance(data, dict):
            return layout
        raw_order = data.get("order")
        order: list[str] = []
        if isinstance(raw_order, list):
            for pid in raw_order:
                if isinstance(pid, str) and pid in PANEL_LABELS and pid not in order:
                    order.append(pid)
        order += [pid for pid in DEFAULT_ORDER if pid not in order]
        layout.order = order
        raw_hidden = data.get("hidden")
        if isinstance(raw_hidden, list):
            layout.hidden = {p for p in raw_hidden if isinstance(p, str) and p in PANEL_LABELS}
        return layout


class ImagingLayoutStore:
    """Loads and saves the user's ``ImagingLayout`` (per-user config dir by default)."""

    def __init__(self, legacy_path: Path | str | None = None) -> None:
        from galileo.ui.theme import LayoutManager
        self._manager = LayoutManager(legacy_path=legacy_path)

    def load(self) -> ImagingLayout:
        return ImagingLayout.from_dict(self._manager.load_layout(LAYOUT_KEY))

    def save(self, layout: ImagingLayout) -> None:
        self._manager.save_layout(LAYOUT_KEY, layout.to_dict())
