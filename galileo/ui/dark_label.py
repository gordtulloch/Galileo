# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The "Dark available" label beside "Subtract dark" on the Imaging and Solve screens."""

from __future__ import annotations

import logging
import os

from PySide6.QtWidgets import QLabel

from galileo import dark_master

logger = logging.getLogger(__name__)


def show_dark_availability(label: QLabel, telescope, instrument, exposure_s: float, binning_x=1, binning_y=1) -> bool:
    """Say on *label* whether the Library holds a dark master for this rig, exposure and binning, with
    the master (or what was looked for) as its tooltip. Returns whether there is one."""
    path = None
    try:
        if telescope and instrument:
            path = dark_master.find_dark_master_path(telescope, instrument, exposure_s, binning_x, binning_y)
    except Exception:
        logger.exception("Could not look for a dark master")
    label.setText("Dark available" if path else "No dark available")
    label.setStyleSheet("color: #31c24a;" if path else "")
    if path:
        tip = f"Dark master: {os.path.basename(path)}"
    elif telescope and instrument:
        tip = (f"No dark master found for {instrument} on {telescope} at {exposure_s:g} s, "
               f"bin {binning_x}x{binning_y}.")
    else:
        tip = "Set up the optical tube and camera (Equipment) so a dark master can be matched."
    label.setToolTip(tip)
    return path is not None
