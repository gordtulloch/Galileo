# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Resumable, chunked, checksummed binary transfer (LINK-070).

Objects are identified by their SHA-256 and stored content-addressed, so the receiver recognises one
it already holds (``has``) and a repeated upload is a no-op. An upload arrives as consecutive chunks:
each carries its own SHA-256, must start exactly where the verified data ends (otherwise the reply
says where to resume), and the whole object is hashed before it is reported complete. Transfers run
below interactive work: they are refused with a ``Retry-After`` while the node is ``busy`` (a session
is running) or while the transfer concurrency cap is in use.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_CHUNK = 1024 * 1024
MAX_CHUNK = 8 * DEFAULT_CHUNK
_HASH = re.compile(r"^[0-9a-f]{64}$")


class TransferError(Exception):
    """A transfer the service refuses; ``status`` is the HTTP status the listener answers with."""

    def __init__(self, message: str, status: int = 400, **detail: object) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


class TransferBusy(TransferError):
    def __init__(self, retry_after: int = 2) -> None:
        super().__init__("busy", 503, retry_after=retry_after)


def valid_hash(value: str) -> bool:
    return bool(_HASH.match(value))


def sha256_file(path: Path, chunk: int = DEFAULT_CHUNK) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


class TransferService:
    def __init__(
        self, root: Path, *, busy: Callable[[], bool] | None = None, max_concurrent: int = 2,
        max_object_bytes: int = 1 << 40,
    ) -> None:
        self._objects = root / "objects"
        self._partial = root / "partial"
        self._objects.mkdir(parents=True, exist_ok=True)
        self._partial.mkdir(parents=True, exist_ok=True)
        self._busy = busy or (lambda: False)
        self._max_concurrent = max_concurrent
        self._max_object = max_object_bytes
        self._active = 0

    # -- queries -----------------------------------------------------------------------
    def object_path(self, sha: str) -> Path:
        if not valid_hash(sha):
            raise TransferError("not a SHA-256", 400)
        return self._objects / sha

    def has(self, sha: str) -> bool:
        return self.object_path(sha).is_file()

    def received(self, sha: str) -> int:
        """Bytes of an in-progress upload that are verified (0 when none)."""
        if not valid_hash(sha):
            raise TransferError("not a SHA-256", 400)
        p = self._partial / f"{sha}.part"
        return p.stat().st_size if p.is_file() else 0

    def status(self, sha: str) -> dict[str, object]:
        if self.has(sha):
            return {"have": True, "size": self.object_path(sha).stat().st_size, "received": 0}
        return {"have": False, "size": 0, "received": self.received(sha)}

    # -- lowest request class ----------------------------------------------------------
    def _enter(self) -> None:
        if self._busy() or self._active >= self._max_concurrent:
            raise TransferBusy()
        self._active += 1

    def _leave(self) -> None:
        self._active -= 1

    # -- upload ------------------------------------------------------------------------
    async def put_chunk(self, sha: str, size: int, offset: int, data: bytes, chunk_sha: str) -> dict[str, object]:
        """Append one verified chunk. Returns ``{"complete": bool, "received": n}``; a wrong ``offset``
        is a 409 carrying ``received`` so the sender resumes from there."""
        self.object_path(sha)
        if self.has(sha):
            return {"complete": True, "received": size}
        if size <= 0 or size > self._max_object:
            raise TransferError("bad object size", 400)
        if not data or len(data) > MAX_CHUNK:
            raise TransferError("bad chunk size", 413 if data else 400)
        if hashlib.sha256(data).hexdigest() != chunk_sha.lower():
            raise TransferError("chunk checksum mismatch", 422)
        self._enter()
        try:
            return await asyncio.to_thread(self._append, sha, size, offset, data)
        finally:
            self._leave()

    def _append(self, sha: str, size: int, offset: int, data: bytes) -> dict[str, object]:
        part = self._partial / f"{sha}.part"
        have = part.stat().st_size if part.is_file() else 0
        if offset != have:
            raise TransferError("wrong offset", 409, received=have)
        if have + len(data) > size:
            raise TransferError("chunk runs past the object size", 400)
        with part.open("ab") as f:
            f.write(data)
        now = have + len(data)
        if now < size:
            return {"complete": False, "received": now}
        if sha256_file(part) != sha:
            part.unlink(missing_ok=True)            # a bad object is thrown away whole; start again
            raise TransferError("object checksum mismatch", 422, received=0)
        part.replace(self._objects / sha)
        return {"complete": True, "received": size}

    def abort(self, sha: str) -> None:
        if valid_hash(sha):
            (self._partial / f"{sha}.part").unlink(missing_ok=True)

    # -- download ----------------------------------------------------------------------
    async def get_chunk(self, sha: str, offset: int, length: int) -> tuple[bytes, int]:
        """``(data, object_size)`` for a byte range of a held object."""
        path = self.object_path(sha)
        if not path.is_file():
            raise TransferError("no such object", 404)
        if offset < 0 or not 0 < length <= MAX_CHUNK:
            raise TransferError("bad range", 400)
        self._enter()
        try:
            return await asyncio.to_thread(self._read, path, offset, length)
        finally:
            self._leave()

    @staticmethod
    def _read(path: Path, offset: int, length: int) -> tuple[bytes, int]:
        with path.open("rb") as f:
            f.seek(offset)
            return f.read(length), path.stat().st_size


class TransferClient:
    """The sending/receiving side over an ``aiohttp`` session already pinned to the peer's
    certificate. ``base`` is ``https://host:port/connect/v1``; ``headers`` carry the bearer token."""

    def __init__(self, session: Any, base: str, headers: dict[str, str], chunk: int = DEFAULT_CHUNK) -> None:
        self._s, self._base, self._h = session, base.rstrip("/") + "/transfer", headers
        self._chunk = min(chunk, MAX_CHUNK)

    async def _status(self, sha: str) -> dict[str, Any]:
        async with self._s.get(f"{self._base}/{sha}", headers=self._h) as r:
            r.raise_for_status()
            return dict(await r.json())

    async def upload(self, path: Path, *, progress: Callable[[int, int], None] | None = None) -> str:
        """Send a file, resuming from whatever the receiver has already verified; returns its hash.
        An object the receiver already holds is not sent again."""
        sha = await asyncio.to_thread(sha256_file, path)
        size = (await asyncio.to_thread(path.stat)).st_size
        state = await self._status(sha)
        if state["have"]:
            return sha
        offset = int(state["received"])
        while offset < size:
            data = await asyncio.to_thread(_read_at, path, offset, self._chunk)
            headers = {**self._h, "X-Chunk-SHA256": hashlib.sha256(data).hexdigest()}
            async with self._s.put(f"{self._base}/{sha}", params={"size": size, "offset": offset},
                                   data=data, headers=headers) as r:
                body = await r.json()
                if r.status == 409:
                    offset = int(body["received"])      # the receiver is somewhere else: resume there
                    continue
                if r.status != 200:
                    raise TransferError(str(body.get("error", r.status)), r.status)
            offset += len(data)
            if progress:
                progress(offset, size)
        return sha

    async def download(self, sha: str, dest: Path, *, progress: Callable[[int, int], None] | None = None) -> None:
        """Fetch an object into ``dest``. A partial ``dest.part`` from an earlier attempt is continued;
        every chunk and the whole file are verified before ``dest`` appears."""
        part = dest.with_name(dest.name + ".part")
        offset = part.stat().st_size if part.is_file() else 0
        size = -1
        while size < 0 or offset < size:
            params = {"offset": offset, "length": self._chunk}
            async with self._s.get(f"{self._base}/{sha}/chunk", params=params, headers=self._h) as r:
                if r.status != 200:
                    raise TransferError(f"download failed ({r.status})", r.status)
                data = await r.read()
                if hashlib.sha256(data).hexdigest() != r.headers.get("X-Chunk-SHA256", ""):
                    raise TransferError("chunk checksum mismatch", 422)
                size = int(r.headers["X-Object-Size"])
            if not data and offset < size:
                raise TransferError("short read", 502)
            await asyncio.to_thread(_append_to, part, data)
            offset += len(data)
            if progress:
                progress(offset, size)
        if await asyncio.to_thread(sha256_file, part) != sha:
            part.unlink(missing_ok=True)
            raise TransferError("object checksum mismatch", 422)
        part.replace(dest)


def _read_at(path: Path, offset: int, length: int) -> bytes:
    with path.open("rb") as f:
        f.seek(offset)
        return f.read(length)


def _append_to(path: Path, data: bytes) -> None:
    with path.open("ab") as f:
        f.write(data)


__all__ = [
    "DEFAULT_CHUNK",
    "MAX_CHUNK",
    "TransferBusy",
    "TransferClient",
    "TransferError",
    "TransferService",
    "sha256_file",
    "valid_hash",
]
