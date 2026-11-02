# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Where a frame's pixels live: *Local* or *On Master* (LIB-200, LIB-210, LIB-220).

A frame is marked *On Master* only after the node holding it has reported the whole file's content hash
and that hash equals the catalog's. Once it is, a plugin may delete the local copy; the catalog row, the
thumbnail and the quality metrics stay, and the row's identity (its content hash) never changes. Any
operation that needs the pixels first calls :func:`ensure_local`, which fetches the file back over
Connect Link (``data.pull``), checks its hash and makes the frame *Local* again.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from galileo.library.models.fits_file import fitsFile

logger = logging.getLogger(__name__)

LOCAL = "local"
ON_MASTER = "on_master"

# ``fetch(sha256, destination)`` brings an object to *destination* (Connect Link's TransferClient.download).
Fetch = Callable[[str, Path], Awaitable[None]]


class LocationError(Exception):
    """A change of location the library refuses."""


def _frame(frame_id: str) -> fitsFile:
    try:
        return fitsFile.get(fitsFile.fitsFileId == frame_id)
    except fitsFile.DoesNotExist:
        raise LocationError(f"no such frame: {frame_id}") from None


def _sha256(path: Path) -> str:
    from galileo.library.core.services import get_file_hash_calculator
    return str(get_file_hash_calculator().calculate_sha256(str(path)))


def location_of(frame_id: str) -> tuple[str, str | None]:
    """``(location, holding node)`` — the node is only set for an *On Master* frame."""
    f = _frame(frame_id)
    return (f.fitsFileLocation or LOCAL), f.fitsFileHolderNode


def mark_on_master(frame_id: str, holder_node: str, verified_hash: str) -> None:
    """Record that *holder_node* holds the whole frame. ``verified_hash`` is the hash the holder computed
    over what it received; it must equal the catalog's hash, so nothing unverified is ever marked."""
    f = _frame(frame_id)
    if not f.fitsFileHash:
        raise LocationError("the frame has no content hash, so it cannot be verified")
    if verified_hash.lower() != f.fitsFileHash.lower():
        raise LocationError("the holder's hash does not match the catalog; the frame is not marked On Master")
    if not holder_node:
        raise LocationError("say which node holds the frame")
    fitsFile.update(fitsFileLocation=ON_MASTER, fitsFileHolderNode=holder_node).where(
        fitsFile.fitsFileId == frame_id).execute()


def delete_local_copy(frame_id: str) -> bool:
    """Delete the local file of a frame already verified *On Master*; the catalog row stays. Returns
    whether a file was removed. Refused for a frame that is not On Master."""
    f = _frame(frame_id)
    if (f.fitsFileLocation or LOCAL) != ON_MASTER:
        raise LocationError("only a frame verified On Master may lose its local copy")
    path = f.fitsFileName
    if path and os.path.exists(path):
        os.remove(path)
        return True
    return False


async def retrieve(frame_id: str, fetch: Fetch) -> Path:
    """Fetch an *On Master* frame back, verify its hash and make it *Local* again (LIB-210). The file is
    written beside its final path and moved into place only once it checks out."""
    f = _frame(frame_id)
    if (f.fitsFileLocation or LOCAL) != ON_MASTER:
        raise LocationError("the frame is already on this node")
    if not f.fitsFileName or not f.fitsFileHash:
        raise LocationError("the catalog does not say where the file belongs or what it should hash to")
    dest = Path(f.fitsFileName)
    part = dest.with_name(dest.name + ".retrieving")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        await fetch(f.fitsFileHash, part)
        got = await asyncio.to_thread(_sha256, part)
        if got.lower() != f.fitsFileHash.lower():
            raise LocationError("the retrieved file does not match its hash; it was discarded")
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    fitsFile.update(fitsFileLocation=LOCAL, fitsFileHolderNode=None).where(fitsFile.fitsFileId == frame_id).execute()
    return dest


# -- the hook any operation needing pixels calls first (LIB-210) ----------------------------------
_retriever: Fetch | None = None


def set_retriever(fetch: Fetch | None) -> None:
    """Install (or remove, with ``None``) the function that fetches a frame from its holder. A plugin
    that moves frames to a Master installs it when it starts and removes it when it stops."""
    global _retriever
    _retriever = fetch


async def ensure_local(frame_id: str) -> Path:
    """The frame's local path, retrieving it first if it is On Master. Raises ``LocationError`` if it
    is On Master and nothing can fetch it (no plugin, or the Master is not reachable)."""
    f = _frame(frame_id)
    if (f.fitsFileLocation or LOCAL) == LOCAL:
        return Path(f.fitsFileName or "")
    if _retriever is None:
        raise LocationError("this frame is stored on the Master and nothing is available to retrieve it")
    try:
        return await retrieve(frame_id, _retriever)
    except LocationError:
        raise
    except Exception as exc:
        logger.exception("Could not retrieve frame %s", frame_id)
        raise LocationError(f"the frame could not be retrieved: {exc}") from exc


def ensure_local_sync(frame_id: str) -> Path:
    """:func:`ensure_local` for code that is not async. Call from a worker thread, never the UI thread
    (retrieval is a network transfer)."""
    return asyncio.run(ensure_local(frame_id))


__all__ = ["LOCAL", "ON_MASTER", "Fetch", "LocationError", "delete_local_copy", "ensure_local",
           "ensure_local_sync", "location_of", "mark_on_master", "retrieve", "set_retriever"]
