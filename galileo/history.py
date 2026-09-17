"""Session history — per-frame metrics storage (HIST-010 … HIST-040)."""

from __future__ import annotations

import csv
import json
import logging
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

    def __init__(self, db_path: "Path | str | None" = None) -> None:
        if db_path is None:
            from galileo.platform import get_data_dir
            db_path = get_data_dir() / "session_history.json"
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, SessionRecord] = {}
        self._current_session: SessionRecord | None = None
        self._load_from_disk()

    # --- Session lifecycle -----------------------------------------------

    def start_session(self, name: str) -> None:
        self._current_session = SessionRecord(name=name, frames=[])
        self._sessions[name] = self._current_session

    def end_session(self) -> None:
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
        if self._current_session is None:
            return
        record = FrameRecord(
            timestamp=timestamp,
            hfr=hfr,
            star_count=star_count,
            guide_rms_ra=guide_rms_ra,
            guide_rms_dec=guide_rms_dec,
        )
        self._current_session.frames.append(record)

    # --- Queries (HIST-020) -----------------------------------------------

    def get_current_session_frames(self) -> list[dict]:
        if self._current_session is None:
            return []
        return [asdict(f) for f in self._current_session.frames]

    def get_session_report(self) -> dict:
        if self._current_session is None:
            return {}
        frames = self._current_session.frames
        if not frames:
            return {"frames": [], "avg_hfr": 0.0, "avg_star_count": 0.0}
        return {
            "frames": [asdict(f) for f in frames],
            "avg_hfr": sum(f.hfr for f in frames) / len(frames),
            "avg_star_count": sum(f.star_count for f in frames) / len(frames),
        }

    def list_sessions(self) -> list[dict]:
        return [{"name": name, "frame_count": s.frame_count} for name, s in self._sessions.items()]

    def get_frames_for_session(self, name: str) -> list[dict]:
        session = self._sessions.get(name)
        if session is None:
            return []
        return [asdict(f) for f in session.frames]

    # --- Export (HIST-040) -----------------------------------------------

    def export_csv(self, session_name: str, dest: "Path | str") -> None:
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
