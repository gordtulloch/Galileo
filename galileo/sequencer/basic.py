# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Basic sequencer — ordered target list execution (SEQ-010 … SEQ-090).

The ``BasicSequencer`` runs an ordered list of ``SequenceDef`` targets,
capturing frames for each step.  All device I/O goes through injected
controller objects so the sequencer core has no direct hardware dependency.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

from galileo.sequencer.file_namer import FileNamer  # re-exported from this module

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class SequencerState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class CaptureStep:
    """One capture step within a sequence target."""
    filter: str
    exposure: float          # seconds
    count: int
    binning: int = 1
    frame_type: str = "Light"
    dither: bool = False


@dataclass
class SequenceTarget:
    name: str
    ra_deg: float
    dec_deg: float
    steps: list[CaptureStep] = field(default_factory=list)


class SequenceDef:
    """Defines an ordered imaging sequence (SEQ-010, SEQ-060)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.targets: list[SequenceTarget] = []

    def add_target(self, name: str, ra_deg: float, dec_deg: float,
                   steps: list[CaptureStep]) -> None:
        self.targets.append(SequenceTarget(name=name, ra_deg=ra_deg, dec_deg=dec_deg, steps=steps))

    def save(self, path: Path | str) -> None:
        """Persist this sequence to a .gseq JSON file (SEQ-060)."""
        data = {
            "name": self.name,
            "version": 1,
            "targets": [
                {
                    "name": t.name,
                    "ra_deg": t.ra_deg,
                    "dec_deg": t.dec_deg,
                    "steps": [asdict(s) for s in t.steps],
                }
                for t in self.targets
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> SequenceDef:
        """Load a sequence from a .gseq file."""
        data = json.loads(Path(path).read_text("utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, d: dict) -> SequenceDef:
        seq = cls(name=d.get("name", ""))
        for td in d.get("targets", []):
            steps = [CaptureStep(**sd) for sd in td.get("steps", [])]
            seq.add_target(
                name=td.get("name", ""),
                ra_deg=float(td.get("ra_deg", 0)),
                dec_deg=float(td.get("dec_deg", 0)),
                steps=steps,
            )
        return seq


# ---------------------------------------------------------------------------
# Sequencer
# ---------------------------------------------------------------------------

class BasicSequencer:
    """Executes a ``SequenceDef`` from start to finish (SEQ-030 … SEQ-090)."""

    def __init__(
        self,
        camera=None,
        mount=None,
        filter_wheel=None,
        guider=None,
        plate_solver=None,
        output_dir: Path | str = ".",
        file_namer=None,
        event_bus=None,
        retry_policy: dict | None = None,
    ) -> None:
        self._camera = camera
        self._mount = mount
        self._filter_wheel = filter_wheel
        self._guider = guider
        self._plate_solver = plate_solver
        self._output_dir = Path(output_dir)
        self._file_namer = file_namer or FileNamer()
        self._event_bus = event_bus
        self._retry_policy = retry_policy or {"max_retries": 3, "delay_s": 5.0}
        self._repository = None
        self._state_path: Path | None = None

        self.state = SequencerState.IDLE
        self.frames_captured = 0
        self.errors: list[str] = []
        self.last_saved_path: Path | None = None
        self.capture_status: str = "idle"
        self._current_progress: dict = {}
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # not paused initially

    # --- Public control API -----------------------------------------------

    async def run(self, seq: SequenceDef) -> None:
        """Execute *seq* from start to finish (SEQ-030)."""
        self.state = SequencerState.RUNNING
        self.frames_captured = 0
        self.errors = []

        total_frames = sum(s.count for t in seq.targets for s in t.steps)
        frame_num = 0

        for target in seq.targets:
            for step in target.steps:
                for i in range(step.count):
                    await self._pause_event.wait()
                    if self.state == SequencerState.STOPPED:
                        return

                    frame_num += 1
                    self._current_progress = {
                        "current_target": target.name,
                        "frame_current": frame_num,
                        "frame_total": total_frames,
                    }
                    self.capture_status = "exposing"

                    try:
                        await self._capture_frame(target, step, frame_num)
                    except Exception as exc:
                        msg = f"Frame {frame_num} error: {exc}"
                        logger.warning(msg)
                        self.errors.append(msg)
                        # Non-fatal: continue to next frame (SEQ-080)
                        continue

        self.state = SequencerState.COMPLETED
        self.capture_status = "complete"

    async def pause(self) -> None:
        self.state = SequencerState.PAUSED
        self._pause_event.clear()

    async def resume(self) -> None:
        self.state = SequencerState.RUNNING
        self._pause_event.set()

    async def stop(self) -> None:
        self.state = SequencerState.STOPPED
        self._pause_event.set()

    async def abort(self) -> None:
        await self.stop()

    # --- Progress / state -------------------------------------------------

    def get_progress(self) -> dict:
        return dict(self._current_progress)

    # --- Persistence (NFR-REL-040) -----------------------------------------

    def persist_completed_frame(self, frame_number: int, path: Path) -> None:
        if self._state_path is None:
            return
        state = self._load_state()
        state.setdefault("completed_frames", []).append({"n": frame_number, "path": str(path)})
        state["completed_frame_count"] = len(state["completed_frames"])
        self._state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    @staticmethod
    def load_persisted_state(state_path: Path | str) -> dict:
        p = Path(state_path)
        if not p.exists():
            return {"completed_frame_count": 0}
        return json.loads(p.read_text("utf-8"))

    def _load_state(self) -> dict:
        if self._state_path and self._state_path.exists():
            return json.loads(self._state_path.read_text("utf-8"))
        return {}

    # --- Private capture logic -------------------------------------------

    async def _capture_frame(
        self,
        target: SequenceTarget,
        step: CaptureStep,
        frame_number: int,
    ) -> Path:
        """Capture one frame, retrying only on connection-level errors."""
        max_retries = self._retry_policy.get("max_retries", 3)
        delay_s = self._retry_policy.get("delay_s", 5.0)

        for attempt in range(max_retries):
            try:
                await self._camera.start_exposure(
                    duration=step.exposure,
                    frame_type=step.frame_type,
                    binning=step.binning,
                )
                data = await self._camera.get_image_array()
                break
            except (ConnectionResetError, ConnectionError):
                # Retry transient connection errors (NFR-REL-010)
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay_s)
                else:
                    raise
        else:
            raise RuntimeError("All retries exhausted")

        date_str = datetime.date.today().isoformat()
        out_path = self._file_namer.make_path(
            self._output_dir,
            target=target.name,
            filter=step.filter,
            date=date_str,
            frame_number=frame_number,
            frame_type=step.frame_type,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._save_fits(data, out_path, target, step)

        self.frames_captured += 1
        self.last_saved_path = out_path

        # Auto-register in library (LIB-150)
        if self._repository is not None:
            try:
                self._repository.register_frame(out_path)
            except Exception:
                logger.exception("Failed to register frame in library")

        return out_path

    def _save_fits(self, data, path: Path, target: SequenceTarget, step: CaptureStep) -> None:
        """Write *data* to a FITS file with sequence metadata headers."""
        try:
            import numpy as np
            from astropy.io import fits
            if data is None:
                data = np.zeros((10, 10), dtype=np.float32)
            hdr = fits.Header()
            hdr["OBJECT"] = target.name
            hdr["EXPTIME"] = step.exposure
            hdr["FILTER"] = step.filter
            hdr["XBINNING"] = step.binning
            hdr["YBINNING"] = step.binning
            hdr["IMAGETYP"] = step.frame_type
            hdr["DATE-OBS"] = datetime.datetime.utcnow().isoformat()
            fits.PrimaryHDU(data, header=hdr).writeto(path, overwrite=True)
        except Exception:
            logger.exception("Failed to write FITS file %s", path)
