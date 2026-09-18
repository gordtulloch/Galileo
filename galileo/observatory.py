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


def get_device_config(
    pier: "PierRecord", category: str, slot: str = "primary"
) -> "DeviceConfigRecord | None":
    """Return the saved device configuration for *category*/*slot* on *pier*,
    or ``None`` if it has never been saved for this Pier. *slot* distinguishes
    multiple devices sharing one category and connection — currently only
    Camera, where any number of additional non-guide cameras (e.g. a Seestar
    S30 Pro's wide-field camera) are saved as ``"camera_2"``, ``"camera_3"``,
    … alongside the always-present ``"primary"`` slot."""
    from galileo.library.models.device_config import DeviceConfigRecord
    return DeviceConfigRecord.get_or_none(
        (DeviceConfigRecord.pier == pier)
        & (DeviceConfigRecord.category == category)
        & (DeviceConfigRecord.slot == slot)
    )


def save_device_config(
    pier: "PierRecord",
    category: str,
    driver: str,
    server: str,
    port: int,
    device_name: str | None = None,
    slot: str = "primary",
    pixel_size_um: float | None = None,
    sensor_width_px: int | None = None,
    sensor_height_px: int | None = None,
    sensor_name: str | None = None,
) -> "DeviceConfigRecord":
    """Create or update the saved device configuration for *category*/*slot*
    on *pier* (the Equipment page's per-device Save button)."""
    from galileo.library.models.device_config import DeviceConfigRecord
    record = DeviceConfigRecord.get_or_none(
        (DeviceConfigRecord.pier == pier)
        & (DeviceConfigRecord.category == category)
        & (DeviceConfigRecord.slot == slot)
    )
    fields = dict(
        driver=driver, server=server, port=port, device_name=device_name,
        pixel_size_um=pixel_size_um, sensor_width_px=sensor_width_px,
        sensor_height_px=sensor_height_px, sensor_name=sensor_name,
    )
    if record is None:
        return DeviceConfigRecord.create(pier=pier, category=category, slot=slot, **fields)
    for key, value in fields.items():
        setattr(record, key, value)
    record.save()
    return record


def delete_device_config(pier: "PierRecord", category: str, slot: str = "primary") -> None:
    """Delete the saved device configuration for *category*/*slot* on *pier*,
    if any (used to prune a camera slot removed with the Camera page's "+"
    list, once the remaining slots no longer reach that far)."""
    from galileo.library.models.device_config import DeviceConfigRecord
    DeviceConfigRecord.delete().where(
        (DeviceConfigRecord.pier == pier)
        & (DeviceConfigRecord.category == category)
        & (DeviceConfigRecord.slot == slot)
    ).execute()


def list_device_config_slots(pier: "PierRecord", category: str) -> list[str]:
    """Return every slot name saved for *category* on *pier* — used by the
    Camera page on load to know how many additional camera panels (beyond
    the always-present "primary") to rebuild."""
    from galileo.library.models.device_config import DeviceConfigRecord
    rows = DeviceConfigRecord.select(DeviceConfigRecord.slot).where(
        (DeviceConfigRecord.pier == pier) & (DeviceConfigRecord.category == category)
    )
    return [row.slot for row in rows]


def list_device_configs(pier: "PierRecord") -> list["DeviceConfigRecord"]:
    """Return every saved device configuration on *pier*, across all
    categories and slots — the pool the Optics page's "Associated" picker
    offers to attach to an optical tube."""
    from galileo.library.models.device_config import DeviceConfigRecord
    return list(
        DeviceConfigRecord.select()
        .where(DeviceConfigRecord.pier == pier)
        .order_by(DeviceConfigRecord.category, DeviceConfigRecord.slot)
    )


def list_optical_tubes(pier: "PierRecord") -> list["OpticalTubeRecord"]:
    """Return *pier*'s saved optical tubes in display order."""
    from galileo.library.models.optical_tube import OpticalTubeRecord
    return list(
        OpticalTubeRecord.select()
        .where(OpticalTubeRecord.pier == pier)
        .order_by(OpticalTubeRecord.position)
    )


def save_optical_tubes(pier: "PierRecord", tubes: list[dict]) -> None:
    """Replace *pier*'s optical tubes with *tubes*, in order (the Optics
    page's Save button). Each dict may carry ``name``, ``focal_length_mm``,
    ``aperture_mm``, ``optical_system``, ``image_reversed``,
    ``image_inverted`` and ``associated`` (a list of ``"<category>:<slot>"``
    device keys); a tube's position is its index in the list."""
    from galileo.library.models.base import db
    from galileo.library.models.optical_tube import OpticalTubeRecord
    with db.atomic():
        OpticalTubeRecord.delete().where(OpticalTubeRecord.pier == pier).execute()
        for position, tube in enumerate(tubes):
            record = OpticalTubeRecord(
                pier=pier,
                position=position,
                name=tube.get("name", ""),
                focal_length_mm=tube.get("focal_length_mm", 0.0),
                aperture_mm=tube.get("aperture_mm", 0.0),
                optical_system=tube.get("optical_system", "Other"),
                image_reversed=bool(tube.get("image_reversed", False)),
                image_inverted=bool(tube.get("image_inverted", False)),
            )
            record.associated = tube.get("associated", [])
            record.save(force_insert=True)
