# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Tracking rate selection when a slew finishes (EQP-MNT-050).

A mount that has just arrived somewhere should start tracking, and at the rate the thing it is
pointed at actually moves: the stars drift at the sidereal rate, but the Moon falls behind it by
about half a degree an hour and the Sun by about a degree a day, so tracking either at the
sidereal rate lets it walk out of frame. This module decides the rate from the target and turns
tracking on once the slew has settled.

Domain core: it drives a mount through its port and has no Qt or filesystem dependency. Callers
on the Qt UI thread must run :func:`resume_tracking` on a worker thread, since waiting for a slew
to finish can take minutes.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

SIDEREAL = "Sidereal"
LUNAR = "Lunar"
SOLAR = "Solar"

# The two bodies that need their own rate. Everything else — stars, deep-sky objects, and the
# planets, whose drift from sidereal is far smaller than a night's guiding error — tracks sidereal.
_RATE_BY_NAME = {"moon": LUNAR, "sun": SOLAR}

SLEW_TIMEOUT_S = 180.0
_POLL_S = 0.5
# A mount does not always report itself slewing the instant the command lands, so for this long a
# "not slewing" answer is not taken as "already arrived".
_START_GRACE_S = 3.0


def target_name(target) -> str:
    """The name of *target*, which may be a ``CurrentObject``, a Star Atlas dict, or a plain
    string. Empty when there is nothing to go on."""
    if target is None:
        return ""
    if isinstance(target, str):
        return target
    name = getattr(target, "name", None)
    if name is None and isinstance(target, dict):
        name = target.get("name")
    return str(name or "")


def tracking_rate_for(target) -> str:
    """The rate to track *target* at: ``"Lunar"`` for the Moon, ``"Solar"`` for the Sun, and
    ``"Sidereal"`` for everything else, including no target at all."""
    return _RATE_BY_NAME.get(target_name(target).strip().lower(), SIDEREAL)


async def wait_for_slew(mount, timeout_s: float = SLEW_TIMEOUT_S) -> bool:
    """Wait until *mount* reports it has stopped slewing. Returns whether it settled within
    *timeout_s* — a mount that never reports its slewing state settles immediately, which is the
    best that can be done with it."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    started = loop.time()
    seen_slewing = False
    while loop.time() < deadline:
        try:
            status = await mount.get_status() or {}
        except Exception:
            logger.debug("Could not read the mount while waiting for its slew to finish", exc_info=True)
            return False
        slewing = status.get("slewing")
        if slewing:
            seen_slewing = True
        elif seen_slewing or slewing is None or loop.time() - started > _START_GRACE_S:
            return True
        await asyncio.sleep(_POLL_S)
    logger.warning("The mount was still slewing after %.0fs; not waiting any longer.", timeout_s)
    return False


async def set_tracking_rate(mount, target=None) -> str:
    """Put *mount* on the rate that suits *target* and turn tracking on. Returns the rate set.

    The rate is selected before tracking is enabled, so the mount never tracks at the wrong one,
    even briefly. A mount that cannot select a rate still gets tracking turned on: sidereal is
    what such a mount does anyway, and refusing to track at all would be worse."""
    rate = tracking_rate_for(target)
    select = getattr(mount, "set_tracking_rate_mode", None)
    if select is not None:
        try:
            await select(rate)
        except Exception:
            logger.warning("Could not select the %s tracking rate; tracking at whatever the mount has.",
                           rate, exc_info=True)
    await mount.set_tracking(True)
    return rate


async def resume_tracking(mount, target=None, timeout_s: float = SLEW_TIMEOUT_S) -> str | None:
    """Wait for *mount*'s slew to finish, then track *target* at its proper rate (EQP-MNT-050).

    Returns the rate set, or ``None`` if the mount never settled — in which case tracking is left
    alone, since something is still moving and issuing more commands would only confuse it."""
    if mount is None:
        return None
    if not await wait_for_slew(mount, timeout_s):
        return None
    rate = await set_tracking_rate(mount, target)
    logger.info("Slew finished; tracking at the %s rate%s.", rate,
                f" for {target_name(target)}" if target_name(target) else "")
    return rate
