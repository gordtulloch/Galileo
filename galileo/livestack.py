# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Live stacking of frames as they are captured (IMG-160).

Each new frame is registered onto the first one of the run and added to a running mean, so the
displayed image gains signal-to-noise as the sequence goes on instead of each exposure replacing
the last. Domain core: plain numpy, no Qt and no file access. Registration is the expensive step,
so :meth:`LiveStacker.add_async` runs it in the CPU worker pool (galileo.core.compute).

Registration prefers ``astroalign`` (a declared dependency), which solves a full affine transform
and so copes with field rotation. Where it is not installed, or cannot find a transform for a
particular frame, the stacker falls back to whole-pixel translation measured by phase correlation
— enough for the guiding drift that dominates a short run, but not for rotation. Which one was
used is recorded in :attr:`LiveStacker.method` rather than left for the user to guess.
"""

from __future__ import annotations

import logging

import numpy as np

from galileo.core.compute import run_cpu

logger = logging.getLogger(__name__)

# Live stacking engages only for a run longer than this: below it there is nothing to stack.
LIVE_STACK_MIN_FRAMES = 3

ASTROALIGN = "astroalign"
TRANSLATION = "translation"


def _luminance(frame: np.ndarray) -> np.ndarray:
    """A 2-D view of *frame* for measuring a shift from — colour planes averaged."""
    return frame.astype(np.float64) if frame.ndim == 2 else frame.astype(np.float64).mean(axis=2)


def translation_offset(frame: np.ndarray, reference: np.ndarray) -> tuple[int, int]:
    """``(dy, dx)``: the whole-pixel shift to apply to *frame* to line it up with *reference*.

    Phase correlation, which finds the offset of two images from the phase of their cross-power
    spectrum. It is immune to a uniform brightness difference between the frames (each is
    mean-subtracted) and costs two FFTs per frame."""
    a, b = _luminance(reference), _luminance(frame)
    a, b = a - a.mean(), b - b.mean()
    cross = np.fft.rfft2(a) * np.conj(np.fft.rfft2(b))
    magnitude = np.abs(cross)
    magnitude[magnitude == 0] = 1.0                      # a flat frame correlates with nothing
    correlation = np.fft.irfft2(cross / magnitude, s=a.shape)
    peak_y, peak_x = np.unravel_index(int(np.argmax(correlation)), correlation.shape)
    height, width = a.shape
    # The peak wraps around: an index past the halfway point is a negative shift.
    dy = peak_y - height if peak_y > height // 2 else peak_y
    dx = peak_x - width if peak_x > width // 2 else peak_x
    return int(dy), int(dx)


def shift_frame(frame: np.ndarray, dy: int, dx: int) -> tuple[np.ndarray, np.ndarray]:
    """``(shifted, valid)``: *frame* moved by ``(dy, dx)`` with no wrap-around, and a mask of the
    pixels that came from it. The pixels shifted in from outside are left at zero and marked
    invalid, so they can be kept out of the mean rather than darkening the stack's edges."""
    shifted = np.zeros_like(frame, dtype=np.float32)
    valid = np.zeros(frame.shape[:2], dtype=bool)
    height, width = frame.shape[:2]
    # Where the frame lands, and the part of it that is still on the canvas.
    dst_y, src_y = (slice(dy, height), slice(0, height - dy)) if dy >= 0 else (slice(0, height + dy), slice(-dy, height))
    dst_x, src_x = (slice(dx, width), slice(0, width - dx)) if dx >= 0 else (slice(0, width + dx), slice(-dx, width))
    shifted[dst_y, dst_x] = frame[src_y, src_x]
    valid[dst_y, dst_x] = True
    return shifted, valid


def astroalign_available() -> bool:
    """Whether ``astroalign`` can be imported — it is a declared dependency, but an environment
    can be missing it, and that changes what a fallback to translation means."""
    try:
        import astroalign  # noqa: F401
    except ImportError:
        return False
    return True


def _astroalign_register(frame: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """``(registered, valid)`` from astroalign, or ``None`` if it isn't installed or found no
    transform (too few stars, or too little overlap with the reference)."""
    try:
        import astroalign
    except ImportError:
        return None
    try:
        registered, footprint = astroalign.register(
            frame.astype(np.float32), reference.astype(np.float32), fill_value=0.0)
    except Exception:
        logger.debug("astroalign could not register a frame; falling back to translation", exc_info=True)
        return None
    # astroalign's footprint marks the pixels that are *not* from the source frame.
    return np.asarray(registered, dtype=np.float32), ~np.asarray(footprint, dtype=bool)


def register(frame: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
    """``(registered, valid, method)``: *frame* aligned onto *reference*, the mask of pixels that
    really came from it, and which method did it."""
    aligned = _astroalign_register(frame, reference)
    if aligned is not None:
        return aligned[0], aligned[1], ASTROALIGN
    dy, dx = translation_offset(frame, reference)
    shifted, valid = shift_frame(frame, dy, dx)
    return shifted, valid, TRANSLATION


class LiveStacker:
    """A running mean of registered frames (IMG-160).

    The first frame added is the reference every later one is aligned to; the stack is the mean of
    what has been added, taken per pixel over the frames that actually cover it, so the edges a
    drifting run leaves only partly covered stay at the right brightness instead of fading.
    """

    def __init__(self) -> None:
        self.reference: np.ndarray | None = None
        self.frames: int = 0                 # frames in the stack, the reference included
        self.rejected: int = 0               # frames that could not be added (wrong shape)
        self.total_exposure_s: float = 0.0   # integration time the stack represents
        self.method: str = ""                # how the last frame was registered
        self._sum: np.ndarray | None = None
        self._counts: np.ndarray | None = None

    def reset(self) -> None:
        """Forget the stack, so the next frame starts a new one."""
        self.__init__()

    def add(self, frame: np.ndarray | None, exposure_s: float = 0.0) -> bool:
        """Register *frame* onto the reference and add it to the stack. Returns whether it went in.

        A frame whose shape doesn't match the reference — the camera's binning or region of
        interest changed mid-run — is rejected rather than stacked into nonsense."""
        handled = self._take_without_registering(frame, exposure_s)
        if handled is not None:
            return handled
        self._accumulate(*register(np.asarray(frame), self.reference), exposure_s)
        return True

    async def add_async(self, frame: np.ndarray | None, exposure_s: float = 0.0) -> bool:
        """:meth:`add`, with the registration run in the CPU worker pool. astroalign holds the GIL
        for seconds on a full frame, which would freeze the UI from any thread (NFR-PERF-020)."""
        handled = self._take_without_registering(frame, exposure_s)
        if handled is not None:
            return handled
        registered = await run_cpu(register, np.asarray(frame), self.reference)
        self._accumulate(*registered, exposure_s)
        return True

    def _take_without_registering(self, frame: np.ndarray | None, exposure_s: float) -> bool | None:
        """Deal with a frame that needs no registration: ``True`` if it became the reference,
        ``False`` if it was refused, ``None`` if it still has to be registered and accumulated."""
        if frame is None:
            return False
        if self.reference is None:
            self.reference = np.asarray(frame, dtype=np.float32)
            self._sum = self.reference.copy()
            self._counts = np.ones(frame.shape[:2], dtype=np.int32)
            self.frames, self.total_exposure_s, self.method = 1, float(exposure_s), ""
            return True
        if frame.shape != self.reference.shape:
            self.rejected += 1
            logger.warning("Live stack: a %s frame does not match the stack's %s frames; not stacked.",
                           frame.shape, self.reference.shape)
            return False
        return None

    def _accumulate(self, registered: np.ndarray, valid: np.ndarray, method: str, exposure_s: float) -> None:
        """Add a registered frame to the running sum."""
        self.method = method
        assert self._sum is not None and self._counts is not None
        self._sum += registered * (valid[..., None] if self._sum.ndim == 3 else valid)
        self._counts += valid
        self.frames += 1
        self.total_exposure_s += float(exposure_s)

    @property
    def result(self) -> np.ndarray | None:
        """The stack: the per-pixel mean of the frames covering each pixel, or ``None`` if empty."""
        if self._sum is None or self._counts is None:
            return None
        counts = np.maximum(self._counts, 1)
        return (self._sum / (counts[..., None] if self._sum.ndim == 3 else counts)).astype(np.float32)

    @property
    def summary(self) -> str:
        """One line on what the stack holds, for the page to show."""
        if not self.frames:
            return ""
        how = ""
        if self.method == TRANSLATION:
            how = (" — aligned by shifting only, as astroalign could not register these frames"
                   if astroalign_available() else
                   " — aligned by shifting only; install astroalign to correct rotation too")
        text = f"Stacked {self.frames} frames, {self.total_exposure_s:g}s total{how}"
        if self.rejected:
            text += f"; {self.rejected} not stacked"
        return text
