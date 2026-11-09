# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Switch channels shown on the Imaging screen (EQP-SW-150).

On Equipment > Switches each switchable channel (a power port, a dew heater, a regulated output) has a
**Show on imaging** tick. Ticked channels are offered on the Imaging screen, on the desktop and — through the
Control Surface (``imaging.controls``, ``switch.set``) — in the web and mobile apps, so a dew heater can be
switched or set to a percentage without leaving the frame being taken.

The choice is configuration, so it lives in the shared database (``app_settings``, namespace
``imaging_switches``, scoped to the Pier, one list of channel ids). This module has no screen and no adapter
import: it only filters a :class:`~galileo.core.switches.SwitchPanel` and describes a channel as plain data.
"""

from __future__ import annotations

from typing import Any

from galileo.core.switches import KIND_DEW, KIND_TOGGLE, KIND_VARIABLE, DUTY_MAX, SwitchChannel, SwitchPanel

NAMESPACE = "imaging_switches"
KEY = "shown"

# What can be put on the Imaging screen: the channels that switch on and off (a dew heater adds a duty).
SHOWABLE_KINDS = (KIND_TOGGLE, KIND_DEW, KIND_VARIABLE)


def can_show(channel: SwitchChannel) -> bool:
    """Whether *channel* can be offered on the Imaging screen (it must be a switchable on/off output)."""
    return channel.switchable and channel.kind in SHOWABLE_KINDS


def shown_ids(pier: str) -> list[str]:
    """The ids of the channels ticked **Show on imaging** for *pier*, in the order they were ticked."""
    from galileo.settings_store import get_setting
    raw = get_setting(NAMESPACE, KEY, [], scope=str(pier))
    return [str(i) for i in raw] if isinstance(raw, list) else []


def set_shown(pier: str, channel_id: str, shown: bool) -> None:
    """Tick or untick **Show on imaging** for one channel of *pier*."""
    from galileo.settings_store import set_setting
    ids = [i for i in shown_ids(pier) if i != channel_id]
    if shown:
        ids.append(channel_id)
    set_setting(NAMESPACE, KEY, ids, scope=str(pier))


def shown_channels(panel: SwitchPanel | None, pier: str) -> list[SwitchChannel]:
    """The channels of *panel* ticked for the Imaging screen, in the panel's own order. A ticked channel the
    device no longer offers (a different box, an optional property absent) is skipped, not an error."""
    if panel is None:
        return []
    wanted = set(shown_ids(pier))
    return [c for c in panel.channels() if c.id in wanted and can_show(c)]


def describe(channel: SwitchChannel, shown: bool | None = None) -> dict[str, Any]:
    """*channel* as plain data for a remote client: what to draw (a toggle, plus a percentage for a dew
    heater, plus a voltage for a regulated output) and its present state."""
    out: dict[str, Any] = {
        "id": channel.id, "label": channel.label, "kind": channel.kind, "on": channel.on,
        "switchable": channel.switchable, "writable": channel.writable, "available": channel.available,
        "state": channel.state,
    }
    if channel.kind == KIND_DEW:
        out.update(duty=channel.duty, duty_min=0.0, duty_max=DUTY_MAX, unit="%")
    elif channel.kind == KIND_VARIABLE:
        out.update(volts=channel.volts, volts_min=channel.min, volts_max=channel.max, unit="V")
    if channel.current_a is not None:
        out["current_a"] = channel.current_a
    if shown is not None:
        out["show_on_imaging"] = shown
    return out


__all__ = ["KEY", "NAMESPACE", "SHOWABLE_KINDS", "can_show", "describe", "set_shown", "shown_channels", "shown_ids"]
