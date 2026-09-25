# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Image stacking with star registration (adapted from VSTarget analysis/stack.py)."""

from __future__ import annotations

import logging
from pathlib import Path

from galileo.core.compute import run_cpu

logger = logging.getLogger(__name__)


async def stack_frames(frames: list[Path], output_path: Path | str) -> Path:
    """Mean-stack *frames* after star registration (VST-AN-030).

    Runs in core's CPU worker pool: astroalign holds the GIL for seconds per frame, so a thread
    would freeze the UI (NFR-PERF-020). Only paths cross into the worker, not frames."""
    return await run_cpu(_stack_sync, list(frames), Path(output_path))


def _stack_sync(frames: list[Path], output_path: Path) -> Path:
    import numpy as np
    from astropy.io import fits

    if not frames:
        raise ValueError("No frames to stack")

    # Load all frames
    data_list = []
    ref_hdr = None
    for p in frames:
        with fits.open(str(p)) as hdul:
            data = hdul[0].data.astype(np.float32)
            if ref_hdr is None:
                ref_hdr = hdul[0].header.copy()
            data_list.append(data)

    if len(data_list) == 1:
        stacked = data_list[0]
    else:
        # Attempt astroalign registration
        try:
            import astroalign as aa  # type: ignore[import]
            aligned = [data_list[0]]
            for img in data_list[1:]:
                try:
                    registered, _ = aa.register(img, data_list[0])
                    aligned.append(registered)
                except Exception:
                    aligned.append(img)
            stacked = np.mean(aligned, axis=0).astype(np.float32)
        except ImportError:
            stacked = np.mean(data_list, axis=0).astype(np.float32)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(stacked, header=ref_hdr).writeto(str(output_path), overwrite=True)
    return output_path
