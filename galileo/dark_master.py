# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Finding and applying a Library dark master to a preview (the "Subtract dark" checkbox).

Shared by the Imaging, Focus and Solve screens so all three match a master the same way: it was made
with the same telescope and camera as the frame, at the same binning and an exposure within 1% of the
frame's. Used for previews only — nothing here changes a frame that is measured, solved or saved.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

EXPOSURE_TOLERANCE = 0.01      # a master matches within 1% of the frame's exposure

_cache_lock = threading.Lock()
_cache: tuple | None = None    # (path, mtime, array) of the last master loaded, so a Loop doesn't re-read it


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def find_dark_master_path(telescope, instrument, exposure_s: float, binning_x=1, binning_y=1) -> str | None:
    """Path of the newest dark master in the Library made with *telescope* and *instrument* at this
    binning and an exposure within 1% of *exposure_s*, or ``None``."""
    from galileo.library.models.masters import Masters

    wanted = (_number(binning_x) or 1.0, _number(binning_y) or 1.0)
    for master in Masters.get_masters_for_equipment(telescope, instrument):   # newest first
        if master.master_type != "dark" or not Path(master.master_path).is_file():
            continue
        exposure = _number(master.exposure_time)
        if exposure is None or abs(exposure - exposure_s) > EXPOSURE_TOLERANCE * max(exposure_s, 1e-6):
            continue
        # A master with no binning recorded is taken as unbinned.
        if (_number(master.binning_x) or 1.0, _number(master.binning_y) or 1.0) != wanted:
            continue
        return master.master_path
    return None


def load_master_data(path: str):
    """The 2-D float32 image of a master FITS file (the last one loaded is kept)."""
    global _cache
    import numpy as np
    mtime = os.path.getmtime(path)
    with _cache_lock:
        if _cache is not None and _cache[0] == path and _cache[1] == mtime:
            return _cache[2]
    from galileo.library.core.light_calibration import _read_master_array
    data = np.asarray(_read_master_array(path)[0], dtype=np.float32)
    with _cache_lock:
        _cache = (path, mtime, data)
    return data


def dark_for_frame(telescope, instrument, exposure_s, binning_x, binning_y, shape) -> tuple:
    """``(dark array or None, note)`` for a frame of *shape* taken with this rig and exposure. The note
    says which master was used, or why none was; it is ``""`` only for no exposure to match.
    Safe to call from a worker thread."""
    if not exposure_s:
        return None, "Subtract dark: the frame's exposure is unknown."
    try:
        path = find_dark_master_path(telescope, instrument, float(exposure_s), binning_x, binning_y)
        if path is None:
            return None, "Subtract dark: no dark master for this camera, optics and exposure."
        data = load_master_data(path)
    except Exception:
        logger.exception("Could not load a dark master")
        return None, "Subtract dark: the dark master could not be read."
    if tuple(shape[:2]) != data.shape:
        return None, (f"Subtract dark: the master is {data.shape[1]}x{data.shape[0]} but the frame is "
                      f"{shape[1]}x{shape[0]} — not subtracted.")
    # Logged each time a dark is applied so the log shows exactly which master a frame was shown with.
    logger.info("Subtracting dark master %s (%s / %s, %.4g s, bin %sx%s) from the frame.", Path(path).name,
                telescope, instrument, float(exposure_s), binning_x, binning_y)
    return data, f"Dark subtracted ({Path(path).name})."


def subtract(frame, dark):
    """*frame* minus *dark* as float32 (so unsigned data can't wrap), or *frame* if there is no dark
    or the shapes differ. Only 2-D mosaics/mono frames are matched against a master."""
    import numpy as np
    if dark is None or getattr(frame, "shape", None) != dark.shape:
        return frame
    return np.asarray(frame, dtype=np.float32) - dark
