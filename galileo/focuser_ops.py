# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""What the Focuser page does to a focuser and how it describes one, with no screen (EQP-FOC-040).

* :class:`FocuserOps` runs the focuser commands against the adapter it is given and returns an
  :class:`~galileo.device_ops.Outcome` instead of showing a message.
* :func:`describe_status` turns an adapter's status dictionary into the text the panel shows.
* :func:`log_transitions` logs a move or settle starting and stopping, not every poll.
* :func:`set_travel_limit` / :func:`clear_travel_limits` change a :class:`~galileo.focuser_settings.FocuserSettings`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from galileo.device_ops import DeviceOps, Outcome
from galileo.focuser_settings import FocuserSettings, travel_problem

logger = logging.getLogger(__name__)


class FocuserOps(DeviceOps):
    def move_to(self, position: int) -> Outcome:
        return self._call("move focuser", lambda a: a.move_to(position), "Move failed — see log.", f" to {position}")

    def set_temp_comp(self, enabled: bool) -> Outcome:
        return self._call("set temperature compensation", lambda a: a.set_temp_comp(enabled))

    def position(self) -> int | None:
        adapter = self._get()
        return None if adapter is None else int(adapter.position)

    def apply_travel(self, settings: FocuserSettings) -> None:
        """Give the connected adapter the settings' travel limits."""
        adapter = self._get()
        if adapter is not None:
            adapter.travel_min = settings.travel_min
            adapter.travel_max = settings.travel_max


@dataclass(frozen=True)
class FocuserView:
    is_moving: str = "—"
    is_settling: str = "—"
    max_increment: str = "—"
    max_step: str = "—"
    position: str = "—"
    position_value: int | None = None          # for the target field, which follows the focuser
    temp_comp: bool | None = None              # None when the focuser does not say
    temperature: str = "—"


def _yes_no(value: Any) -> str:
    return "—" if value is None else ("Yes" if value else "No")


def _text(value: Any) -> str:
    return "—" if value is None else str(value)


def describe_status(status: dict) -> FocuserView:
    position, temperature, temp_comp = status.get("position"), status.get("temperature"), status.get("temp_comp")
    return FocuserView(
        is_moving=_yes_no(status.get("is_moving")), is_settling=_yes_no(status.get("is_settling")),
        max_increment=_text(status.get("max_increment")), max_step=_text(status.get("max_step")),
        position=_text(position), position_value=None if position is None else int(position),
        temp_comp=None if temp_comp is None else bool(temp_comp),
        temperature="—" if temperature is None else f"{temperature:.1f} °C")


def log_transitions(title: str, status: dict, last: tuple[Any, Any], target: int) -> tuple[Any, Any]:
    """Log is_moving/is_settling *changes* at INFO, not every 2-second poll, which would flood the log while a
    move runs. *last* is the ``(is_moving, is_settling)`` of the previous poll; returns the new pair."""
    position = status.get("position")
    was_moving, was_settling = last
    is_moving, is_settling = status.get("is_moving"), status.get("is_settling")
    if is_moving and not was_moving:
        logger.info("Focuser %s: started moving (target position %s)", title, target)
    elif was_moving and not is_moving:
        logger.info("Focuser %s: stopped moving at position %s", title, position)
    if is_settling and not was_settling:
        logger.info("Focuser %s: settling at position %s", title, position)
    elif was_settling and not is_settling:
        logger.info("Focuser %s: finished settling at position %s", title, position)
    return is_moving, is_settling


def set_travel_limit(settings: FocuserSettings, which: str, position: int) -> str:
    """Make *position* the ``"min"`` or ``"max"`` travel limit. Returns the problem text and changes nothing when
    the result would not be a sensible range, else an empty string."""
    low, high = (position, settings.travel_max) if which == "min" else (settings.travel_min, position)
    problem = travel_problem(low, high)
    if problem:
        return problem
    settings.travel_min, settings.travel_max = low, high
    return ""


def clear_travel_limits(settings: FocuserSettings) -> None:
    settings.travel_min = settings.travel_max = None


__all__ = ["FocuserOps", "FocuserView", "clear_travel_limits", "describe_status", "log_transitions",
           "set_travel_limit"]
