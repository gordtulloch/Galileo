# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Chunked, resumable, checksummed binary transfer (LINK-070).

An upload is a series of in-order chunks, each verified against its own SHA-256, appended to a
partial file; the whole object is verified against the announced SHA-256 before it is reported
complete and only then enters the object store. The upload id is derived from (peer, object hash),
so a peer that reconnects — or a node that restarted — resumes at the first chunk not yet on disk
without any extra state file. An object already held (same hash) is recognised at ``begin``.
Downloads serve verified chunks of a held object. Work yields to interactive requests and to a
running session through ``busy_probe`` and a small concurrency cap.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CHUNK = 1 << 20
MAX_CHUNK = 8 << 20
_HEX = re.compile(r"^[0-9a-f]{64}$")


class TransferError(Exception):
    """A transfer step that cannot be done; ``status`` is the HTTP status the listener answers."""

    def __init__(self, message: str, status: int = 400, next_chunk: int | None = None) -> None:
        super().__init__(message)
        self.status, self.next_chunk = status, next_chunk


@dataclass(frozen=True)
class UploadState:
    transfer_id: str
    state: str                  # "open" | "have" (already held) | "complete"
    next_chunk: int
    chunk_size: int
    sha256: str


@dataclass(frozen=True)
class ObjectInfo:
    sha256: str
    size: int
    path: Path


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()


class TransferStore:
    def __init__(
        self, root: Path | None = None, *, busy_probe: Callable[[], bool] | None = None,
        max_concurrent: int = 2, max_object_bytes: int = 64 << 30,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if root is None:
            from galileo.platform import get_cache_dir
            root = get_cache_dir() / "connect_link"
        self._parts, self._objects = root / "partial", root / "objects"
        self._busy = busy_probe or (lambda: False)
        self._sem = asyncio.Semaphore(max_concurrent)
        self._max = max_object_bytes
        self._clock = clock
        self._announced: dict[str, tuple[str, str, int, int]] = {}     # id -> (peer, sha, size, chunk)
        self._names: dict[str, str] = {}
        self._published: dict[str, Path] = {}                          # sha -> file a plugin offers
        self._on_complete: list[Callable[[str, str, str, Path], None]] = []

    # -- objects -----------------------------------------------------------------------
    def on_complete(self, listener: Callable[[str, str, str, Path], None]) -> None:
        """Call *listener(peer_id, name, sha256, path)* when an upload has been verified."""
        self._on_complete.append(listener)

    def have(self, sha256: str) -> ObjectInfo | None:
        if not _HEX.match(sha256):
            return None
        path = self._objects / sha256
        if path.is_file():
            return ObjectInfo(sha256, path.stat().st_size, path)
        offered = self._published.get(sha256)
        if offered is not None and offered.is_file():
            return ObjectInfo(sha256, offered.stat().st_size, offered)
        return None

    def publish_file(self, path: Path) -> str:
        """Offer a file already on disk for download; returns the hash the peer asks for."""
        sha = _file_sha(path)
        self._published[sha] = path
        return sha

    def unpublish(self, sha256: str) -> None:
        self._published.pop(sha256, None)

    # -- upload ------------------------------------------------------------------------
    @staticmethod
    def _id(peer_id: str, sha256: str) -> str:
        return _sha(f"{peer_id}:{sha256}".encode())[:32]

    def begin(self, peer_id: str, name: str, size: int, sha256: str, chunk_size: int = DEFAULT_CHUNK) -> UploadState:
        if not _HEX.match(sha256 or ""):
            raise TransferError("sha256 must be 64 lowercase hex characters")
        if not 0 < chunk_size <= MAX_CHUNK:
            raise TransferError(f"chunk_size must be 1..{MAX_CHUNK}")
        if not 0 <= size <= self._max:
            raise TransferError("object too large", 413)
        tid = self._id(peer_id, sha256)
        if self.have(sha256) is not None:
            return UploadState(tid, "have", -1, chunk_size, sha256)
        self._announced[tid] = (peer_id, sha256, size, chunk_size)
        self._parts.mkdir(parents=True, exist_ok=True)
        part = self._parts / tid
        if part.exists():                                     # resume: keep only whole verified chunks
            whole = (min(part.stat().st_size, size) // chunk_size) * chunk_size
            with part.open("r+b") as f:
                f.truncate(whole)
        else:
            part.touch()
        self._names[tid] = name
        return UploadState(tid, "open", part.stat().st_size // chunk_size, chunk_size, sha256)

    def _open(self, peer_id: str, tid: str) -> tuple[str, int, int, Path]:
        info = self._announced.get(tid)
        if info is None or info[0] != peer_id:
            raise TransferError("unknown transfer", 404)
        return info[1], info[2], info[3], self._parts / tid

    async def _yield_to_interactive(self) -> None:
        for _ in range(50):                                   # at most ~10 s of deference per chunk
            if not self._busy():
                return
            await asyncio.sleep(0.2)

    async def put_chunk(self, peer_id: str, tid: str, index: int, data: bytes, chunk_sha256: str) -> int:
        """Append chunk *index*; returns the next chunk expected. A repeat of a chunk already
        stored is accepted without change, so a retry after a lost reply is harmless."""
        _, size, chunk, part = self._open(peer_id, tid)
        async with self._sem:
            await self._yield_to_interactive()
            have = part.stat().st_size // chunk
            if index < have:
                return have
            if index != have:
                raise TransferError("chunk out of order", 409, next_chunk=have)
            expected = min(chunk, size - have * chunk)
            if len(data) != expected or expected <= 0:
                raise TransferError(f"chunk {index} must be {expected} bytes")
            if _sha(data) != chunk_sha256.lower():
                raise TransferError("chunk checksum mismatch", 422, next_chunk=have)
            await asyncio.to_thread(self._append, part, data)
            return have + 1

    @staticmethod
    def _append(part: Path, data: bytes) -> None:
        with part.open("ab") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

    async def complete(self, peer_id: str, tid: str) -> UploadState:
        """Verify the whole object, then move it into the store and tell listeners."""
        sha, size, chunk, part = self._open(peer_id, tid)
        async with self._sem:
            await self._yield_to_interactive()
            got = part.stat().st_size
            if got != size:
                raise TransferError("object incomplete", 409, next_chunk=got // chunk)
            actual = await asyncio.to_thread(_file_sha, part)
            if actual != sha:
                await asyncio.to_thread(part.unlink)           # unrecoverable: start again
                self._announced.pop(tid, None)
                raise TransferError("object checksum mismatch", 422, next_chunk=0)
            self._objects.mkdir(parents=True, exist_ok=True)
            dest = self._objects / sha
            await asyncio.to_thread(shutil.move, str(part), str(dest))
        name = self._names.pop(tid, "")
        self._announced.pop(tid, None)
        for fn in list(self._on_complete):
            try:
                fn(peer_id, name, sha, dest)
            except Exception:                                  # a plugin's handler never fails the transfer
                logger.exception("transfer-complete listener failed")
        return UploadState(tid, "complete", size // chunk, chunk, sha)

    def abandon_older_than(self, seconds: float) -> int:
        """Remove partial uploads untouched for *seconds*; returns how many."""
        n, cutoff = 0, self._clock() - seconds
        if self._parts.is_dir():
            for p in self._parts.iterdir():
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
                    self._announced.pop(p.name, None)
                    n += 1
        return n

    # -- download ----------------------------------------------------------------------
    def info(self, sha256: str) -> ObjectInfo:
        obj = self.have(sha256)
        if obj is None:
            raise TransferError("unknown object", 404)
        return obj

    async def read_chunk(self, sha256: str, index: int, chunk_size: int = DEFAULT_CHUNK) -> tuple[bytes, str]:
        obj = self.info(sha256)
        if not 0 < chunk_size <= MAX_CHUNK or index < 0 or index * chunk_size >= max(obj.size, 1):
            raise TransferError("chunk out of range", 416)
        async with self._sem:
            await self._yield_to_interactive()
            data = await asyncio.to_thread(self._read, obj.path, index * chunk_size, chunk_size)
        return data, _sha(data)

    @staticmethod
    def _read(path: Path, offset: int, n: int) -> bytes:
        with path.open("rb") as f:
            f.seek(offset)
            return f.read(n)
