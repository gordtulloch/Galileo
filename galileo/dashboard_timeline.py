# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""What each Pier has been doing, as a compact multi-lane timeline (OBS-150).

Plain Python with no Qt: the Dashboard samples every Pier about once a second into a
:class:`PierActivity` and hands it to :meth:`PierTimeline.record`, which turns changes of
state into :class:`Segment` runs on seven lanes (session, mount, flip, guide, align, focus,
capture) and keeps the recent guide-error samples. The Dashboard paints the result; nothing
here is persisted — the timeline is a live view of the current run of the application.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field

# Lane ids, top to bottom.
SESSION, MOUNT, FLIP, GUIDE, ALIGN, FOCUS, CAPTURE = (
    "session", "mount", "flip", "guide", "align", "focus", "capture")
LANES: tuple[str, ...] = (SESSION, MOUNT, FLIP, GUIDE, ALIGN, FOCUS, CAPTURE)
LANE_LABELS = {SESSION: "Session", MOUNT: "Mount", FLIP: "Flip", GUIDE: "Guide",
               ALIGN: "Align", FOCUS: "Focus", CAPTURE: "Capture"}

# Segment states. ``OK`` is the normal "doing its job" state of every lane.
OK, WARN, BAD, LIGHT, CAL = "ok", "warn", "bad", "light", "cal"

RETENTION_S = 12 * 3600          # how much history is kept per Pier
MIN_SPAN_S = 15 * 60             # the time axis is never shorter than this
GUIDE_SAMPLE_MIN_GAP_S = 1.0     # guide samples are thinned to about one a second
MAX_GUIDE_SAMPLES = 20_000


@dataclass
class Segment:
    """One run of a lane in one state; ``end`` is ``None`` while it is still going on."""
    start: float
    end: float | None
    state: str
    label: str = ""


@dataclass
class PierActivity:
    """A Pier's instantaneous state, as the Dashboard samples it. ``None`` for a lane means idle."""
    session: str | None = None       # "running" | "paused" | "error"
    session_label: str = ""
    mount: str | None = None         # "tracking" | "slewing" | "idle" | "parked"; None = not connected
    flipping: bool = False
    guide: str | None = None         # "guiding" | "settling" | "lost"
    aligning: bool = False
    focusing: bool = False
    capture: str | None = None       # LIGHT or CAL while exposing
    frames_done: int = 0             # frames finished by the running block (to cut capture into boxes)
    guide_error: tuple[float, float] | None = None    # latest (ra, dec) guide error, arcsec
    guide_sample_id: int | None = None                # lets repeated reads of one sample be ignored


_STATE_FOR_SESSION = {"running": OK, "paused": WARN, "error": BAD}
_STATE_FOR_MOUNT = {"tracking": OK, "slewing": WARN, "idle": None, "parked": None}
_STATE_FOR_GUIDE = {"guiding": OK, "settling": WARN, "lost": BAD}


class PierTimeline:
    """The recorded history of one Pier."""

    def __init__(self, name: str = "", retention_s: float = RETENTION_S) -> None:
        self.name = name
        self.retention_s = retention_s
        self._lock = threading.Lock()
        self._lanes: dict[str, list[Segment]] = {lane: [] for lane in LANES}
        self._guide: deque[tuple[float, float, float]] = deque(maxlen=MAX_GUIDE_SAMPLES)
        self._last_frames: int | None = None
        self._last_sample_id: int | None = None
        self.latest: PierActivity = PierActivity()
        self._first: float | None = None

    # --- Recording ------------------------------------------------------------

    def set_state(self, lane: str, state: str | None, now: float, label: str = "") -> None:
        """Make *state* the lane's current state (``None`` = idle). Does nothing while the state
        is unchanged, so calling it every sample is cheap."""
        with self._lock:
            self._set_state(lane, state, now, label)

    def _set_state(self, lane: str, state: str | None, now: float, label: str = "") -> None:
        segments = self._lanes[lane]
        current = segments[-1] if segments and segments[-1].end is None else None
        if current is not None:
            if current.state == state:
                if label and not current.label:
                    current.label = label
                return
            current.end = now
        if state is not None:
            segments.append(Segment(now, None, state, label))
            if self._first is None:
                self._first = now

    def record(self, activity: PierActivity, now: float) -> None:
        """Fold one sample of the Pier's state into the timeline."""
        with self._lock:
            self.latest = activity
            self._set_state(SESSION, _STATE_FOR_SESSION.get(activity.session or ""), now, activity.session_label)
            self._set_state(MOUNT, _STATE_FOR_MOUNT.get(activity.mount or ""), now)
            self._set_state(FLIP, OK if activity.flipping else None, now)
            self._set_state(GUIDE, _STATE_FOR_GUIDE.get(activity.guide or ""), now)
            self._set_state(ALIGN, OK if activity.aligning else None, now)
            self._set_state(FOCUS, OK if activity.focusing else None, now)
            self._set_state(CAPTURE, activity.capture, now)
            # Cut the capture lane into one box per finished frame.
            if activity.capture:
                if self._last_frames is not None and activity.frames_done != self._last_frames:
                    self._split(CAPTURE, now)
                self._last_frames = activity.frames_done
            else:
                self._last_frames = None
            error = activity.guide_error
            if (error is not None and activity.guide_sample_id != self._last_sample_id
                    and (not self._guide or now - self._guide[-1][0] >= GUIDE_SAMPLE_MIN_GAP_S)):
                self._guide.append((now, error[0], error[1]))
                self._last_sample_id = activity.guide_sample_id
            self._trim(now)

    def _split(self, lane: str, now: float) -> None:
        segments = self._lanes[lane]
        if segments and segments[-1].end is None:
            last = segments[-1]
            last.end = now
            segments.append(Segment(now, None, last.state, last.label))

    def _trim(self, now: float) -> None:
        cutoff = now - self.retention_s
        for segments in self._lanes.values():
            while segments and segments[0].end is not None and segments[0].end < cutoff:
                segments.pop(0)
        while self._guide and self._guide[0][0] < cutoff:
            self._guide.popleft()

    # --- Reading (safe from the UI thread while recording continues elsewhere) -----

    def segments(self, lane: str) -> list[Segment]:
        with self._lock:
            return [Segment(s.start, s.end, s.state, s.label) for s in self._lanes[lane]]

    def guide_samples(self) -> list[tuple[float, float, float]]:
        """``(time, ra, dec)`` guide errors, oldest first."""
        with self._lock:
            return list(self._guide)

    def window(self, now: float) -> tuple[float, float]:
        """The ``(start, end)`` of the time axis: back to the first recorded event, but never
        shorter than :data:`MIN_SPAN_S` nor longer than the retention."""
        with self._lock:
            first = self._first
        span = MIN_SPAN_S if first is None else max(MIN_SPAN_S, min(self.retention_s, now - first))
        return now - span, now

    def clear(self) -> None:
        with self._lock:
            for segments in self._lanes.values():
                segments.clear()
            self._guide.clear()
            self._first = None
            self._last_frames = None
            self._last_sample_id = None


@dataclass
class TimelineRecorder:
    """The :class:`PierTimeline` of every Pier of the Observatory, by Pier key."""
    timelines: dict = field(default_factory=dict)

    def timeline(self, key, name: str = "") -> PierTimeline:
        tl = self.timelines.get(key)
        if tl is None:
            tl = self.timelines[key] = PierTimeline(name)
        if name:
            tl.name = name
        return tl

    def forget_except(self, keys) -> None:
        """Drop the timelines of Piers that no longer exist."""
        keep = set(keys)
        for key in [k for k in self.timelines if k not in keep]:
            del self.timelines[key]


def activity_from_progress(progress, mount=None, guider=None, *, manual_focus: bool = False,
                           manual_align: bool = False, session_name: str = "") -> PierActivity:
    """Build a :class:`PierActivity` from the pieces the Dashboard can read without blocking:
    the session's ``SessionProgress`` (or ``None`` when nothing runs), the Pier's mount adapter and
    its ``GuidingService``. Every argument is read defensively — a device mid-reconnect or a
    stub without an attribute reads as idle rather than breaking the Dashboard.

    *manual_focus* / *manual_align* say an autofocus / plate solve started outside a session
    (from the Focus or Solve screen) is in progress on this Pier."""
    a = PierActivity()
    block_name = ""
    if progress is not None:
        state = str(getattr(getattr(progress, "state", ""), "value", getattr(progress, "state", "")))
        a.session = "running" if state in ("idle", "") else state
        if a.session not in _STATE_FOR_SESSION:
            a.session = None                         # completed / stopped: nothing is running now
        a.session_label = session_name
        block_name = type(getattr(progress, "block", None)).__name__
        a.frames_done = int(getattr(progress, "frames_done", 0) or 0)
    running = a.session == "running"
    a.capture = (LIGHT if block_name == "ImageBlock" else CAL
                 if block_name in ("DarkCaptureBlock", "FlatCaptureBlock") else None) if running else None
    a.flipping = running and block_name == "MeridianFlipBlock"
    a.aligning = manual_align or (running and block_name == "PlateSolveBlock")
    a.focusing = manual_focus or (running and block_name == "AutofocusBlock")

    if mount is not None:
        try:
            if getattr(mount, "is_slewing", False):
                a.mount = "slewing"
            elif getattr(mount, "is_tracking", False):
                a.mount = "tracking"
            elif getattr(mount, "is_parked", False) or getattr(mount, "at_park", False):
                a.mount = "parked"
            else:
                a.mount = "idle"
        except Exception:
            a.mount = None

    if guider is not None:
        try:
            if getattr(guider, "is_connected", False):
                snap = guider.model.snapshot()
                if snap.app_state == "LostLock":
                    a.guide = "lost"
                elif snap.settling or snap.app_state in ("Calibrating", "Selected"):
                    a.guide = "settling"
                elif snap.phase == "run":
                    a.guide = "guiding"
                if a.guide == "guiding" and snap.samples:
                    last = snap.samples[-1]
                    scale = snap.pixel_scale or 1.0
                    a.guide_error = (last.ra * scale, last.dec * scale)
                    a.guide_sample_id = last.frame
        except Exception:
            a.guide = None
    return a
