# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Focuser operating mode, retained position and travel guard-rails (EQP-FOC-040, EQP-FOC-050).

Pure data and functions — no device, Qt or database access — so the Focuser page, both transport
adapters and the tests all apply the same rules.

A *Pulse* focuser has no position readout: the driver only offers "run the motor for N ms"
(INDI ``FOCUS_TIMER``). Galileo gives it a virtual position axis of ``0..PULSE_RANGE_MAX`` and
dead-reckons along it, one completed pulse at a time. That position means nothing unless it is
remembered across restarts and the user has told Galileo where the focuser really is, hence the
saved position, the "Reset to middle" calibration and the user-set travel limits.
"""

from __future__ import annotations

from dataclasses import dataclass

MODE_ABSOLUTE = "Absolute"
MODE_PULSE = "Pulse"
MODES = (MODE_ABSOLUTE, MODE_PULSE)

PULSE_RANGE_MAX = 50_000                # virtual axis of a pulse focuser: 0..PULSE_RANGE_MAX
PULSE_MIDDLE = PULSE_RANGE_MAX // 2     # where the user is asked to leave the focuser, and the default
PULSE_MIN_MS = 32                       # shorter pulses are below what focuser motors reliably honour


@dataclass
class FocuserSettings:
    """One focuser's saved operating settings (a focuser's ``device_configs`` row)."""

    mode: str = MODE_ABSOLUTE
    position: int | None = None         # last known position; only meaningful in Pulse mode
    travel_min: int | None = None       # user-calibrated lowest safe position; None = unset
    travel_max: int | None = None       # user-calibrated highest safe position; None = unset

    @property
    def is_pulse(self) -> bool:
        return self.mode == MODE_PULSE

    def start_position(self) -> int:
        """Where a pulse focuser is assumed to be on connecting: the retained position, else the middle."""
        return PULSE_MIDDLE if self.position is None else clamp_position(self.position, 0, PULSE_RANGE_MAX)


def clamp_position(target: int, low: int | None, high: int | None) -> int:
    """*target* limited to ``low..high`` (either bound may be ``None`` for no limit)."""
    if low is not None and target < low:
        target = low
    if high is not None and target > high:
        target = high
    return target


def travel_problem(low: int | None, high: int | None) -> str | None:
    """Why ``low..high`` is not a usable travel range, or ``None`` if it is."""
    if low is not None and high is not None and low >= high:
        return f"The minimum travel ({low}) must be below the maximum travel ({high})."
    return None
