"""Multi-Mount Observatory management (OBS-010 … OBS-080).

An Observatory groups one or more Piers.  Safety monitors and domes may be
scoped at either the Observatory (shared) or Pier (independent) level.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pier
# ---------------------------------------------------------------------------

class Pier:
    """Represents one mount plus its associated device set.

    Corresponds to the ``PROF`` Pier concept in the SDD.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.device_pool = None        # galileo.core.devices.DevicePool
        self.safety_monitor = None
        self.dome = None
        self.guiding_service = None
        self.sequence_runner = None
        self._state = "idle"

    def set_safety_monitor(self, monitor) -> None:
        self.safety_monitor = monitor

    def set_dome(self, dome) -> None:
        self.dome = dome

    async def abort_and_park(self) -> None:
        """Abort any running sequence and park the mount."""
        if self.sequence_runner is not None:
            try:
                await self.sequence_runner.abort()
            except Exception:
                logger.exception("Pier %r: error aborting sequence", self.name)

        if self.device_pool is not None:
            mount = self.device_pool.get("Mount")
            if mount is not None:
                try:
                    await mount.park()
                except Exception:
                    logger.exception("Pier %r: error parking mount", self.name)


# ---------------------------------------------------------------------------
# Observatory
# ---------------------------------------------------------------------------

class Observatory:
    """Groups multiple Piers; manages shared safety and dome resources."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.piers: list[Pier] = []
        self.safety_monitor = None
        self.dome = None
        self._event_bus = None
        self.state = "idle"

    def add_pier(self, pier: Pier) -> None:
        self.piers.append(pier)

    def set_safety_monitor(self, monitor, scope: str = "observatory") -> None:
        if scope == "observatory":
            self.safety_monitor = monitor

    def set_dome(self, dome, scope: str = "observatory") -> None:
        if scope == "observatory":
            self.dome = dome

    def get_dashboard(self) -> list[dict]:
        """Return a status summary for every Pier (OBS-060)."""
        return [
            {
                "pier_name": pier.name,
                "equipment_state": "connected" if pier.device_pool else "disconnected",
                "sequence_state": getattr(pier.sequence_runner, "state", "idle"),
            }
            for pier in self.piers
        ]

    async def handle_safety_unsafe(self, source: str = "", explanation: str = "") -> None:
        """Abort and park ALL Piers when an Observatory-scoped unsafe event fires."""
        logger.warning("Observatory %r safety unsafe: %s — %s", self.name, source, explanation)
        await asyncio.gather(
            *(pier.abort_and_park() for pier in self.piers),
            return_exceptions=True,
        )

    async def connect_all_piers(self) -> None:
        """Connect device sets of all Piers concurrently (OBS-080)."""
        await asyncio.gather(
            *(pier.device_pool.connect_all() for pier in self.piers if pier.device_pool),
            return_exceptions=True,
        )

    async def run_all_sequences(self) -> None:
        """Run independent sequences across all Piers concurrently (OBS-020)."""
        await asyncio.gather(
            *(pier.sequence_runner.run() for pier in self.piers if pier.sequence_runner),
            return_exceptions=True,
        )


# ---------------------------------------------------------------------------
# Persisted settings (master records)
# ---------------------------------------------------------------------------
#
# The Observatory/Pier classes above are live, in-process runtime objects
# (device pools, sequence runners) and are never serialized. The functions
# below persist just the settings a user configures once per Observatory/Pier
# — the "which Observatory/Pier am I working with" the UI's top-bar selectors
# save to and reload across restarts — as Peewee master records in the same
# project-wide database used by galileo.library/galileo.history (ADR-002).

def list_observatories() -> list["ObservatoryRecord"]:
    """Return every saved Observatory, alphabetically by name."""
    from galileo.library.models.observatory import ObservatoryRecord
    return list(ObservatoryRecord.select().order_by(ObservatoryRecord.name))


def create_observatory(
    name: str,
    latitude: float | None = None,
    longitude: float | None = None,
    timezone: str | None = None,
    physical_address: str | None = None,
    owner: str | None = None,
) -> "ObservatoryRecord":
    """Create and persist a new Observatory settings record."""
    from galileo.library.models.observatory import ObservatoryRecord
    return ObservatoryRecord.create(
        name=name,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        physical_address=physical_address,
        owner=owner,
    )


def list_piers(observatory: "ObservatoryRecord") -> list["PierRecord"]:
    """Return every saved Pier belonging to *observatory*, alphabetically by name."""
    from galileo.library.models.observatory import PierRecord
    return list(PierRecord.select().where(PierRecord.observatory == observatory).order_by(PierRecord.name))


def create_pier(observatory: "ObservatoryRecord", name: str) -> "PierRecord":
    """Create and persist a new Pier settings record under *observatory*."""
    from galileo.library.models.observatory import PierRecord
    return PierRecord.create(observatory=observatory, name=name)
