# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The settings-changed event (REPL-050).

Published on the bus after a bulk apply of replicated rows, naming the tables, so open Options pages
and screens reload their values. Qt code subscribes through a queued connection (the bus calls
handlers on the publishing thread).
"""

from __future__ import annotations

from collections.abc import Iterable

from galileo.bus import Event, EventBus, get_bus


class SettingsChanged(Event):
    """Payload: ``tables`` — the tables whose rows were applied."""


def publish_settings_changed(tables: Iterable[str], bus: EventBus | None = None) -> None:
    (bus or get_bus()).publish(SettingsChanged("replication", tables=sorted(set(tables))))


__all__ = ["SettingsChanged", "publish_settings_changed"]
