# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Session history — per-frame metrics storage (HIST-010 … HIST-040)."""

from __future__ import annotations

import csv
import json
import logging
import threading
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FrameRecord:
    timestamp: str
    hfr: float
    star_count: int
    guide_rms_ra: float = 0.0
    guide_rms_dec: float = 0.0


@dataclass
class SessionRecord:
    name: str
    frames: list[FrameRecord]

    @property
    def frame_count(self) -> int:
        return len(self.frames)


class SessionHistory:
    """Records per-frame quality metrics and persists them across restarts (HIST-030)."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            from galileo.platform import get_data_dir
            db_path = get_data_dir() / "session_history.json"
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, SessionRecord] = {}
        self._current_session: SessionRecord | None = None
        # The sequencer records from its worker thread while the History screen reads on the UI thread.
        self._lock = threading.RLock()
        self._load_from_disk()

    # --- Session lifecycle -----------------------------------------------

    def start_session(self, name: str) -> None:
        with self._lock:
            self._current_session = SessionRecord(name=name, frames=[])
            self._sessions[name] = self._current_session

    def end_session(self) -> None:
        with self._lock:
            self._flush()
            self._current_session = None

    # --- Frame recording (HIST-010) -------------------------------------

    def record_frame(
        self,
        timestamp: str,
        hfr: float,
        star_count: int,
        guide_rms_ra: float = 0.0,
        guide_rms_dec: float = 0.0,
    ) -> None:
        record = FrameRecord(
            timestamp=timestamp,
            hfr=hfr,
            star_count=star_count,
            guide_rms_ra=guide_rms_ra,
            guide_rms_dec=guide_rms_dec,
        )
        with self._lock:
            if self._current_session is not None:
                self._current_session.frames.append(record)

    # --- Queries (HIST-020) -----------------------------------------------

    def get_current_session_frames(self) -> list[dict]:
        if self._current_session is None:
            return []
        return [asdict(f) for f in self._current_session.frames]

    def get_session_report(self) -> dict:
        if self._current_session is None:
            return {}
        return self.get_report_for_session(self._current_session.name)

    def get_report_for_session(self, name: str) -> dict:
        """Frames plus averages for any recorded session (HIST-020); ``{}`` if unknown."""
        with self._lock:
            session = self._sessions.get(name)
            frames = list(session.frames) if session is not None else None
        if frames is None:
            return {}
        if not frames:
            return {"frames": [], "avg_hfr": 0.0, "avg_star_count": 0.0}
        return {
            "frames": [asdict(f) for f in frames],
            "avg_hfr": sum(f.hfr for f in frames) / len(frames),
            "avg_star_count": sum(f.star_count for f in frames) / len(frames),
        }

    def list_sessions(self) -> list[dict]:
        with self._lock:
            return [{"name": name, "frame_count": s.frame_count} for name, s in self._sessions.items()]

    def get_frames_for_session(self, name: str) -> list[dict]:
        with self._lock:
            session = self._sessions.get(name)
            return [] if session is None else [asdict(f) for f in session.frames]

    def delete_session(self, name: str) -> None:
        with self._lock:
            if self._current_session is not None and self._current_session.name == name:
                self._current_session = None
            if self._sessions.pop(name, None) is not None:
                self._flush()

    # --- Export (HIST-040) -----------------------------------------------

    def export_csv(self, session_name: str, dest: Path | str) -> None:
        frames = self.get_frames_for_session(session_name)
        if not frames:
            return
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(frames[0].keys()))
            writer.writeheader()
            writer.writerows(frames)

    # --- Persistence -------------------------------------------------------

    def _flush(self) -> None:
        data = {
            name: {"name": s.name, "frames": [asdict(f) for f in s.frames]}
            for name, s in self._sessions.items()
        }
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_from_disk(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text("utf-8"))
            for name, d in raw.items():
                frames = [FrameRecord(**f) for f in d.get("frames", [])]
                self._sessions[name] = SessionRecord(name=name, frames=frames)
        except Exception:
            logger.exception("Failed to load session history from %s", self._path)


_shared: SessionHistory | None = None
_shared_lock = threading.Lock()


def get_history() -> SessionHistory:
    """The application-wide history store, shared by the session executor (which records) and the
    History screen (which reviews)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = SessionHistory()
        return _shared
