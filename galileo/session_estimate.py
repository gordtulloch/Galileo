# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Pre-run summary of a session (CSURF-185): how long it will take, how much it will write, and what it runs into.

Pure arithmetic over the block list, with no devices, Qt or database: the caller supplies what it knows about the
rig and the night (bytes per frame, free space, when the target sets, when dawn comes, when it crosses the meridian)
and anything it does not know is left out of the summary rather than guessed. The times per block are planning
figures, not measurements: they make a session of 3 hours come out as about 3 hours, not as a stopwatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from galileo.session_exec import _LOOP_BLOCKS, _loop_passes, build_tree

#: Seconds a block costs besides its exposures (slewing, settling, a focus run, ...).
BLOCK_OVERHEAD_S: dict[str, float] = {
    "TargetBlock": 60.0, "FilterChangeBlock": 10.0, "CoolCameraBlock": 600.0, "WarmCameraBlock": 600.0,
    "AutofocusBlock": 240.0, "PlateSolveBlock": 45.0, "GuideStartBlock": 30.0, "DitherBlock": 20.0,
    "ParkMountBlock": 60.0, "UnparkMountBlock": 20.0, "MeridianFlipBlock": 300.0,
    "DomeOpenBlock": 60.0, "DomeCloseBlock": 60.0, "DomeSyncBlock": 20.0,
}
GUIDE_CALIBRATION_S = 300.0
DOWNLOAD_S = 3.0                    # reading a frame off the camera and saving it
FITS_HEADER_BYTES = 5760            # two 2880-byte FITS blocks: the header, rounded up


@dataclass
class RunEstimate:
    duration_s: float = 0.0
    frames: int = 0
    exposure_s: float = 0.0                         # time actually spent exposing
    storage_bytes: int | None = None                # None when the frame size is unknown
    free_bytes: int | None = None
    start: datetime | None = None
    finish: datetime | None = None
    flip_at: datetime | None = None                 # when the target next crosses the meridian
    has_flip_block: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def iso(t: datetime | None) -> str | None:
            return t.isoformat() if t is not None else None
        return {"duration_s": round(self.duration_s), "frames": self.frames, "exposure_s": round(self.exposure_s),
                "storage_bytes": self.storage_bytes, "free_bytes": self.free_bytes,
                "start": iso(self.start), "finish": iso(self.finish), "flip_at": iso(self.flip_at),
                "has_flip_block": self.has_flip_block, "warnings": list(self.warnings)}


def frame_bytes(width_px: int, height_px: int, binning: int = 1, bytes_per_pixel: int = 2) -> int:
    """Size on disk of one FITS frame (16-bit by default)."""
    b = max(1, int(binning))
    return (width_px // b) * (height_px // b) * bytes_per_pixel + FITS_HEADER_BYTES


def _block_cost(block: Any, state: dict) -> tuple[float, float, int, int]:
    """(seconds, exposure seconds, frames, storage bytes) for one non-loop block; updates *state* (current filter)."""
    name = type(block).__name__
    per_frame = state.get("frame_bytes")
    seconds = BLOCK_OVERHEAD_S.get(name, 0.0)
    exposing, frames, storage = 0.0, 0, 0

    def add(count: int, exposure: float, binning: int = 1) -> None:
        nonlocal seconds, exposing, frames, storage
        frames += count
        exposing += exposure * count
        seconds += (exposure + DOWNLOAD_S) * count
        if state.get("width") and state.get("height"):
            storage += count * frame_bytes(state["width"], state["height"], binning)
        elif per_frame:
            storage += count * per_frame

    if name == "ImageBlock":
        panes = len(block.mosaic.panels) if getattr(block, "has_mosaic", False) else 1
        if block.filter and block.filter != state.get("filter"):
            seconds += BLOCK_OVERHEAD_S["FilterChangeBlock"]
            state["filter"] = block.filter
        add(max(1, int(block.count)) * panes, float(block.exposure), int(block.binning))
    elif name == "DarkCaptureBlock":
        for exposure in block.exposures:
            add(1, float(exposure))
    elif name == "FlatCaptureBlock":
        add(max(1, int(block.count)), float(block.exposure or 1.0))
    elif name == "FilterChangeBlock" and block.filter:
        state["filter"] = block.filter
    elif name == "GuideStartBlock" and getattr(block, "calibrate", False):
        seconds += GUIDE_CALIBRATION_S
    return seconds, exposing, frames, storage


def estimate_run(blocks: list, *, start: datetime, width_px: int | None = None, height_px: int | None = None,
                 bytes_per_frame: int | None = None, free_bytes: int | None = None,
                 dawn: datetime | None = None, sets_at: datetime | None = None,
                 flip_at: datetime | None = None) -> RunEstimate:
    """Estimate running *blocks* from *start*. Times are timezone-aware datetimes; each of *dawn* (when the sky
    gets too bright), *sets_at* (when the target drops below the horizon limit) and *flip_at* (when it reaches
    the meridian) may be ``None`` when the caller cannot tell."""
    state: dict = {"width": width_px, "height": height_px, "frame_bytes": bytes_per_frame, "filter": None}
    est = RunEstimate(start=start, free_bytes=free_bytes, flip_at=flip_at)
    elapsed = 0.0
    known_size = bool(width_px and height_px) or bool(bytes_per_frame)
    last_image_end = 0.0

    def walk(nodes: list, times: int) -> None:
        nonlocal elapsed, last_image_end
        for node in nodes:
            name = type(node.block).__name__
            if name in _LOOP_BLOCKS:
                for _ in range(times * _loop_passes(node.block)):
                    walk(node.children, 1)
                continue
            seconds, exposing, frames, storage = _block_cost(node.block, state)
            elapsed += seconds
            est.exposure_s += exposing
            est.frames += frames
            est.storage_bytes = (est.storage_bytes or 0) + storage
            if name == "MeridianFlipBlock":
                est.has_flip_block = True
            if frames:
                last_image_end = elapsed

    walk(build_tree(blocks), 1)
    est.duration_s = elapsed
    est.finish = start + timedelta(seconds=elapsed)
    if not known_size:
        est.storage_bytes = None

    imaging_ends = start + timedelta(seconds=last_image_end)
    if free_bytes is not None and est.storage_bytes is not None and est.storage_bytes > free_bytes:
        est.warnings.append("The session needs more storage than is free.")
    if dawn is not None and imaging_ends > dawn:
        est.warnings.append(f"The session runs past dawn ({dawn.astimezone():%H:%M}).")
    if sets_at is not None and imaging_ends > sets_at:
        est.warnings.append(f"The target drops below the horizon limit at {sets_at.astimezone():%H:%M}, "
                            "before the session ends.")
    if flip_at is not None and start < flip_at < imaging_ends and not est.has_flip_block:
        est.warnings.append(f"The target reaches the meridian at {flip_at.astimezone():%H:%M}, mid-session, "
                            "and the session has no Meridian Flip block.")
    return est


__all__ = ["RunEstimate", "estimate_run", "frame_bytes"]
