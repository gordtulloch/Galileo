# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Prior integration time lookup for a catalog object (WUT-050).

What's Up Tonight shows prior Library integration time per ranked entry as an
informational annotation only — this is the read-only catalog query behind
that, not a new capability of the Library itself. Its return value is meant
to be passed as ``rank_for_train``'s/``rank_tonight``'s ``library_lookup``
(``galileo.planning.recommend``), which is documented to never feed it into
the ranking score.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def prior_integration_hours(object_name: str) -> float | None:
    """Total light-frame exposure time (hours) already catalogued for
    *object_name* (matched against ``fitsFile.fitsFileObject``, exactly),
    excluding soft-deleted frames. Returns ``None`` when nothing is
    catalogued for it — distinct from ``0.0``, which would mean frames
    exist but their recorded exposure times summed to zero. Returns
    ``None`` on any database error too (e.g. no catalog initialized yet)
    rather than raising, matching this function's advisory, display-only
    purpose (WUT-050) — a failed lookup should never block the ranked list."""
    try:
        import peewee
        from galileo.library.models import fitsFile

        query = fitsFile.select().where(
            (fitsFile.fitsFileObject == object_name)
            & (peewee.fn.UPPER(fitsFile.fitsFileType) == "LIGHT FRAME")
            & ((fitsFile.fitsFileSoftDelete.is_null(True)) | (fitsFile.fitsFileSoftDelete == False))  # noqa: E712
        )
        total_seconds = 0.0
        found = False
        for f in query:
            found = True
            try:
                total_seconds += float(f.fitsFileExpTime or 0)
            except (TypeError, ValueError):
                continue
        return (total_seconds / 3600.0) if found else None
    except Exception:
        logger.debug("Could not compute prior integration time for %r", object_name, exc_info=True)
        return None
