# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The catalog thumbnail pack (SKY-080): every catalog object's survey thumbnail in one ZIP.

Fetching tens of thousands of cutouts one request at a time from the user's machine is slow
and hammers a free service, so the images are fetched once by ``scripts/build_thumbnail_pack.py``
(:func:`build_pack`), published on galileo-imaging.com, and each installation downloads that one
file (:func:`download_pack`) and unpacks it into the thumbnail cache (:func:`install_pack`) —
the same ``skythumb_*.jpg`` files :func:`galileo.planning.sky_atlas._cached_thumbnail` reads.

Pure Python (no Qt); the Options > Planning screen runs it on a worker thread.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

PACK_URL = "https://www.galileo-imaging.com/downloads/galileo-thumbnails.zip"
MANIFEST_NAME = "manifest.json"

# Exactly the names sky_atlas._thumbnail_cache_path() produces — anything else in a downloaded
# archive is ignored, so a bad/hostile ZIP can't write outside the cache directory.
_ENTRY_RE = re.compile(r"^skythumb_-?\d+\.\d{4}_-?\d+\.\d{4}_\d+\.\d{2}x\d+\.\d{2}(_\d+px)?\.jpg$")

# (done, total) — bytes while downloading, files while unpacking/building.
ProgressFn = Callable[[int, int], None]
StopFn = Callable[[], bool]


class PackError(Exception):
    """The pack could not be downloaded or is not a valid thumbnail pack."""


def is_pack_entry(name: str) -> bool:
    """Whether *name* is a thumbnail file name this pack may contain (flat, no directories)."""
    return bool(_ENTRY_RE.match(name))


def download_pack(
    dest: Path, url: str = PACK_URL, progress: ProgressFn | None = None, should_stop: StopFn | None = None,
) -> bool:
    """Stream *url* to *dest*. Returns ``False`` when stopped part-way (the partial file is removed);
    raises :class:`PackError` on any network/HTTP failure."""
    import requests
    try:
        with requests.get(url, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as out:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if should_stop is not None and should_stop():
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
                else:
                    return True
    except (requests.RequestException, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise PackError(f"Could not download {url}: {exc}") from exc
    dest.unlink(missing_ok=True)
    return False


def install_pack(
    zip_path: Path, dest_dir: Path | None = None, progress: ProgressFn | None = None,
    should_stop: StopFn | None = None,
) -> int:
    """Unpack the thumbnails in *zip_path* into the thumbnail cache (*dest_dir*, default the app cache
    directory), skipping any already there. Returns how many files were added. Raises
    :class:`PackError` when the file is not a ZIP."""
    if dest_dir is None:
        from galileo.platform import get_cache_dir
        dest_dir = get_cache_dir()
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PackError(f"{zip_path} is not a valid thumbnail pack: {exc}") from exc
    added = 0
    with archive:
        names = [n for n in archive.namelist() if is_pack_entry(n)]
        for i, name in enumerate(names, start=1):
            if should_stop is not None and should_stop():
                break
            target = dest_dir / name
            if not target.exists():
                target.write_bytes(archive.read(name))
                added += 1
            if progress is not None and (i % 200 == 0 or i == len(names)):
                progress(i, len(names))
    return added


def build_pack(
    out_path: Path,
    objects: Iterable,
    workers: int = 4,
    progress: ProgressFn | None = None,
    should_stop: StopFn | None = None,
) -> tuple[int, int, int]:
    """Fetch a thumbnail for every catalog object in *objects* (reusing the local thumbnail cache, so
    an interrupted run resumes) and write them all into the ZIP at *out_path*, with a ``manifest.json``.
    Images already in the cache are used as-is with no network request. Returns ``(included, failed,
    from_cache)``. The publisher's tool — see ``scripts/build_thumbnail_pack.py``."""
    from concurrent.futures import ThreadPoolExecutor

    from galileo.planning.sky_atlas import (
        _cache_thumbnail, _cached_thumbnail, _fetch_hips_thumbnail_sync, _thumbnail_cache_path,
        _thumbnail_field_arcmin,
    )

    objs = list(objects)

    cache_hits = 0

    def one(obj) -> tuple[str, bytes]:
        nonlocal cache_hits
        field = _thumbnail_field_arcmin(obj.size_arcmin)
        name = _thumbnail_cache_path(obj.ra_deg, obj.dec_deg, field, field).name
        data = _cached_thumbnail(obj.ra_deg, obj.dec_deg, field, field)
        if data:
            cache_hits += 1
        else:
            data = _fetch_hips_thumbnail_sync(obj.ra_deg, obj.dec_deg, field, field)
            if data:
                _cache_thumbnail(obj.ra_deg, obj.dec_deg, field, field, data)
        return name, data

    included = failed = 0
    seen: set[str] = set()
    tmp_path = out_path.with_suffix(out_path.suffix + ".part")
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as archive, ThreadPoolExecutor(max(workers, 1)) as pool:
        # imap-style bounded windows keep memory flat for tens of thousands of objects.
        window = max(workers, 1) * 8
        for start in range(0, len(objs), window):
            if should_stop is not None and should_stop():
                break
            for name, data in pool.map(one, objs[start:start + window]):
                if not data:
                    failed += 1
                elif name not in seen:      # two catalog entries can share a position/field
                    seen.add(name)
                    archive.writestr(name, data)
                    included += 1
            if progress is not None:
                progress(min(start + window, len(objs)), len(objs))
        archive.writestr(MANIFEST_NAME, json.dumps({
            "format": 1, "thumbnails": included, "failed": failed,
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
        }, indent=2))
    tmp_path.replace(out_path)
    return included, failed, cache_hits
