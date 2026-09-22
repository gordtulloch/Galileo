# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The current object of each Pier (IMG-140).

Picking an object in the Star Atlas makes it the *current object* of the selected
Pier. The rest of the application reads it from here rather than from the atlas:
captured frames are named after it, and plate solving slews to its coordinates.
It is kept per Pier — each Pier runs its own mount — and only for the running
session. Domain-core: plain Python, no Qt; changes are announced on the event bus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from galileo.bus import CurrentObjectChangedEvent, EventBus, get_bus


@dataclass(frozen=True)
class CurrentObject:
    """A named sky position; ``ra_deg``/``dec_deg`` are J2000, as the Star Atlas holds them."""

    name: str
    ra_deg: float
    dec_deg: float
    kind: str = ""
    designation: str = ""

    @classmethod
    def from_atlas(cls, obj: dict[str, Any]) -> "CurrentObject":
        """Build one from a Star Atlas object dict (``StarAtlasView.select``'s payload)."""
        return cls(
            name=str(obj["name"]), ra_deg=float(obj["ra_deg"]), dec_deg=float(obj["dec_deg"]),
            kind=str(obj.get("type") or obj.get("kind") or ""), designation=str(obj.get("designation") or ""),
        )

    @property
    def file_stem(self) -> str:
        """The name in a form safe to put in a file name (``"M 31"`` -> ``"M_31"``)."""
        return safe_file_stem(self.name)


def safe_file_stem(name: "str | None") -> str:
    """*name* with anything unsafe in a file name replaced by ``_``; empty if nothing usable is left."""
    return re.sub(r"[^\w.+-]+", "_", (name or "").strip()).strip("_.")


def pier_key(pier: Any) -> "Any | None":
    """What identifies *pier* in the store: its database id when it has one (Pier names repeat
    across Observatories), else its name. ``None`` for no Pier."""
    if pier is None:
        return None
    pier_id = getattr(pier, "id", None)
    return pier_id if pier_id is not None else getattr(pier, "name", None)


class CurrentObjects:
    """The current object of each Pier, keyed by ``pier_key``."""

    def __init__(self, bus: "EventBus | None" = None) -> None:
        self._bus = bus
        self._objects: dict[Any, CurrentObject] = {}

    def get(self, pier: Any) -> "CurrentObject | None":
        key = pier_key(pier)
        return self._objects.get(key) if key is not None else None

    def set(self, pier: Any, obj: "CurrentObject | None") -> None:
        """Make *obj* the Pier's current object (``None`` clears it), announcing a change."""
        key = pier_key(pier)
        if key is None or self._objects.get(key) == obj:
            return
        if obj is None:
            del self._objects[key]
        else:
            self._objects[key] = obj
        (self._bus or get_bus()).publish(CurrentObjectChangedEvent(source="current_object", pier=key, object=obj))

    def clear(self, pier: Any) -> None:
        self.set(pier, None)


_default_store: "CurrentObjects | None" = None


def get_current_objects() -> CurrentObjects:
    """The process-wide store."""
    global _default_store
    if _default_store is None:
        _default_store = CurrentObjects()
    return _default_store
