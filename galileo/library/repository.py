"""FITS repository scanning, cataloging, and management (LIB-010 … LIB-160).

Adapted from AstroFiler's core scanning and hashing logic.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entry dataclass (lightweight, in-memory representation)
# ---------------------------------------------------------------------------

@dataclass
class RepositoryEntry:
    """One catalogued FITS file."""
    path: Path
    object_name: str = ""
    filter_name: str = ""
    frame_type: str = ""
    date_obs: str = ""
    content_hash: str = ""
    fwhm: float | None = None
    hfr: float | None = None
    snr: float | None = None


@dataclass
class SessionContainer:
    """A group of frames forming one imaging session."""
    session_id: str
    step_name: str = ""
    frame_count: int = 0
    entries: list[RepositoryEntry] = field(default_factory=list)


@dataclass
class OrganizeProposal:
    entry: RepositoryEntry
    new_path: Path


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class Repository:
    """Scans a directory tree of FITS files and maintains an in-memory catalog."""

    def __init__(self, root: "Path | str") -> None:
        self._root = Path(root)
        self._entries: list[RepositoryEntry] = []
        self._sessions: list[SessionContainer] = []
        self._active_session_id: str | None = None

    # --- Scanning (LIB-010) -----------------------------------------------

    def scan(self) -> None:
        """Recursively scan *root* and ingest all FITS files."""
        self._entries.clear()
        for fits_path in self._root.rglob("*.fits"):
            entry = _ingest_fits(fits_path)
            if entry:
                self._entries.append(entry)

    # --- Entry access -------------------------------------------------------

    def all_entries(self) -> list[RepositoryEntry]:
        return list(self._entries)

    def entry_count(self) -> int:
        return len(self._entries)

    def register_frame(self, path: "Path | str") -> None:
        """Register a single frame without a full scan (LIB-150)."""
        entry = _ingest_fits(Path(path))
        if entry:
            self._entries.append(entry)

    # --- Deduplication (LIB-020) -------------------------------------------

    def find_duplicates(self) -> list[list[RepositoryEntry]]:
        """Return groups of entries with identical SHA-256 hashes."""
        from collections import defaultdict
        by_hash: dict[str, list[RepositoryEntry]] = defaultdict(list)
        for entry in self._entries:
            if not entry.content_hash:
                entry.content_hash = _sha256(entry.path)
            by_hash[entry.content_hash].append(entry)
        return [group for group in by_hash.values() if len(group) > 1]

    # --- Organisation (LIB-030) --------------------------------------------

    def organize(self, pattern: str, dry_run: bool = True) -> list[OrganizeProposal]:
        """Propose renamed paths derived from each entry's FITS metadata."""
        proposals = []
        seq: dict[str, int] = {}
        for entry in self._entries:
            key = f"{entry.object_name}_{entry.date_obs}_{entry.filter_name}"
            seq[key] = seq.get(key, 0) + 1
            new_name = pattern.format(
                object=entry.object_name or "Unknown",
                date=entry.date_obs[:10] if entry.date_obs else "0000-00-00",
                filter=entry.filter_name or "None",
                seq=seq[key],
            )
            proposals.append(OrganizeProposal(entry=entry, new_path=self._root / new_name))
        return proposals

    # --- Session detection (LIB-040) --------------------------------------

    def detect_sessions(self) -> list[SessionContainer]:
        """Group frames heuristically by object/date/instrument/binning/temperature."""
        from collections import defaultdict
        groups: dict[str, list[RepositoryEntry]] = defaultdict(list)
        for entry in self._entries:
            key = f"{entry.object_name}_{entry.date_obs[:10] if entry.date_obs else ''}"
            groups[key].append(entry)
        self._sessions = [
            SessionContainer(
                session_id=str(uuid.uuid4()),
                step_name=key,
                frame_count=len(entries),
                entries=entries,
            )
            for key, entries in groups.items()
        ]
        return self._sessions

    # --- Sequence sessions (LIB-160) --------------------------------------

    def begin_sequence_session(self, step_name: str) -> str:
        session_id = str(uuid.uuid4())
        self._sessions.append(SessionContainer(session_id=session_id, step_name=step_name))
        self._active_session_id = session_id
        return session_id

    def add_frame_to_session(self, session_id: str, path: "Path | str") -> None:
        for s in self._sessions:
            if s.session_id == session_id:
                entry = _ingest_fits(Path(path)) or RepositoryEntry(path=Path(path))
                s.entries.append(entry)
                s.frame_count += 1
                return

    def end_sequence_session(self, session_id: str) -> None:
        self._active_session_id = None

    def get_sequence_sessions(self) -> list[SessionContainer]:
        return [s for s in self._sessions if s.step_name]

    # --- Quality metrics (LIB-070) -----------------------------------------

    def compute_quality_metrics(self) -> None:
        """Compute FWHM/HFR/SNR for every entry using SEP."""
        for entry in self._entries:
            try:
                entry.fwhm, entry.hfr, entry.snr = _compute_metrics(entry.path)
            except Exception:
                pass

    # --- Statistics (LIB-080) -----------------------------------------------

    def get_statistics(self) -> dict:
        from collections import Counter
        by_object = Counter(e.object_name for e in self._entries)
        by_filter = Counter(e.filter_name for e in self._entries)
        return {
            "total_frames": len(self._entries),
            "by_object": dict(by_object),
            "by_filter": dict(by_filter),
        }

    # --- Integrity verification (LIB-140) ----------------------------------

    def verify_integrity(self) -> list[RepositoryEntry]:
        """Return entries whose on-disk content no longer matches the stored hash."""
        corrupt = []
        for entry in self._entries:
            if not entry.content_hash:
                continue
            current = _sha256(entry.path)
            if current != entry.content_hash:
                corrupt.append(entry)
        return corrupt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ingest_fits(path: Path) -> RepositoryEntry | None:
    """Read FITS headers and return a ``RepositoryEntry``; returns None on error."""
    try:
        from astropy.io import fits
        with fits.open(str(path), memmap=False) as hdul:
            hdr = hdul[0].header
            return RepositoryEntry(
                path=path,
                object_name=str(hdr.get("OBJECT", "")),
                filter_name=str(hdr.get("FILTER", "")),
                frame_type=str(hdr.get("IMAGETYP", "Light Frame")),
                date_obs=str(hdr.get("DATE-OBS", "")),
                content_hash=_sha256(path),
            )
    except Exception:
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        h.update(path.read_bytes())
    except Exception:
        pass
    return h.hexdigest()


def _compute_metrics(path: Path) -> tuple[float, float, float]:
    """Return (fwhm, hfr, snr) for the frame at *path*."""
    try:
        import numpy as np
        import sep
        from astropy.io import fits
        with fits.open(str(path), memmap=False) as hdul:
            data = hdul[0].data.astype(np.float64)
        bkg = sep.Background(data)
        sub = data - bkg
        objs = sep.extract(sub, 1.5, err=bkg.globalrms)
        if len(objs) == 0:
            return 0.0, 0.0, 0.0
        fwhm = float(np.median(2.355 * (objs["a"] + objs["b"]) / 2))
        hfr = float(np.median(objs["a"] + objs["b"]) / 2)
        snr = float(np.median(objs["flux"]) / (bkg.globalrms + 1e-9))
        return fwhm, hfr, snr
    except Exception:
        return 0.0, 0.0, 0.0
