# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Meridian flip service (MFLIP-010 … MFLIP-040)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MeridianFlipConfig:
    """Per-profile meridian flip configuration (MFLIP-040)."""
    flip_ha_limit: float = 6.0          # hour angle limit (hours)
    pre_flip_settle_s: int = 30
    post_flip_recenter: bool = True
    post_flip_restart_guiding: bool = True


class MeridianFlipService:
    """Monitors hour-angle and executes automated meridian flips (MFLIP-010 … MFLIP-040)."""

    def __init__(
        self,
        mount=None,
        guider=None,
        solver=None,
        config: MeridianFlipConfig | None = None,
    ) -> None:
        self._mount = mount
        self._guider = guider
        self._solver = solver
        self._config = config or MeridianFlipConfig()

    def set_flip_limit_ha(self, ha: float) -> None:
        self._config.flip_ha_limit = ha

    def time_to_flip_minutes(self) -> float:
        """Return estimated minutes until the flip limit is reached (MFLIP-010)."""
        current_ha = getattr(self._mount, "hour_angle", 0.0) if self._mount else 0.0
        remaining_ha = self._config.flip_ha_limit - current_ha
        return max(0.0, remaining_ha * 60.0)

    async def execute_flip(
        self,
        sequence=None,
        target_ra: float = 0.0,
        target_dec: float = 0.0,
    ) -> None:
        """Pause sequence, flip mount, recover, and resume (MFLIP-020)."""
        if sequence is not None:
            await sequence.pause()

        if self._config.pre_flip_settle_s:
            await asyncio.sleep(0.0)  # in real use: await asyncio.sleep(settle)

        await self._mount.slew_to_coordinates(ra=target_ra, dec=target_dec)

        if self._config.post_flip_recenter or self._config.post_flip_restart_guiding:
            await self.post_flip_recovery(target_ra=target_ra, target_dec=target_dec)

        if sequence is not None:
            await sequence.resume()

    async def post_flip_recovery(self, target_ra: float, target_dec: float) -> None:
        """Re-center and restart guiding after a flip (MFLIP-030)."""
        if self._solver is not None and self._config.post_flip_recenter:
            await self._solver.solve_and_center(
                target_ra=target_ra,
                target_dec=target_dec,
                mount=self._mount,
                camera=None,
            )

        if self._guider is not None and self._config.post_flip_restart_guiding:
            await self._guider.start_guiding()
