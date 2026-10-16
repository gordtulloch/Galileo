# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Multi-Mount Observatory management (OBS-010 … OBS-080).

An Observatory groups one or more Piers.  Safety monitors and domes may be
scoped at either the Observatory (shared) or Pier (independent) level.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from galileo.bus import Event, get_bus

if TYPE_CHECKING:
    # ORM records, imported lazily inside the functions that use them (the domain
    # core must not load the persistence layer at import time); names here are for annotations.
    from galileo.library.models.device_config import DeviceConfigRecord
    from galileo.library.models.observatory import ObservatoryRecord, PierRecord
    from galileo.library.models.optical_tube import OpticalTubeRecord
    from galileo.library.models.weather_safety_rule import SafetyDeviceConfigRecord
    from galileo.autofocus import AutofocusParams, FilterOffset
    from galileo.mount_limits import MountLimits
    from galileo.platesolve import SolverParams
    from galileo.safety import WeatherSafetyRule

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Contact details (OBS-090)
# ---------------------------------------------------------------------------

@dataclass
class ContactDetails:
    """The operator's own external-notification contact details (OBS-090),
    read by :mod:`galileo.notify` (NOTIF-040) — one per Observatory, since
    being notified is scoped to the person running it, not to an individual
    Pier within it."""

    email: str | None = None
    phone_number: str | None = None
    channels: list[str] | None = None


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
        self.dome = None
        self.guiding_service = None
        self.sequence_runner = None
        self.scheduler = None          # galileo.scheduler.ObservatoryScheduler (the Pier's job queue)
        self._state = "idle"

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
# Cross-Pier shared-resource arbitration (OBS-100 … OBS-130)
# ---------------------------------------------------------------------------

#: Priorities: a safety action may override any imaging activity; everything else is equal.
PRIORITY_NORMAL = 50
PRIORITY_EMERGENCY = 100

#: Resource names the arbiter knows about.
RESOURCE_DOME = "dome"

#: Actions that disturb other Piers' work on a shared resource. Anything not listed (e.g.
#: opening the roof) never conflicts, so it is always granted.
DISRUPTIVE_ACTIONS: dict[str, frozenset[str]] = {
    RESOURCE_DOME: frozenset({"close", "slew"}),
}


class ResourceClaimDeniedEvent(Event):
    """A Pier's request for a shared resource lost to another Pier's active work (OBS-120)."""


class ResourceClaimGrantedEvent(Event):
    """A Pier's request for a shared resource was granted (OBS-120)."""


class ResourceReleasedEvent(Event):
    """A Pier finished the work it had registered against a shared resource (OBS-120)."""


@dataclass(frozen=True)
class ArbitrationDecision:
    """Outcome of :meth:`ResourceArbiter.request`."""

    granted: bool
    reason: str = ""
    blocked_by: tuple[str, ...] = ()


class ResourceArbiter:
    """Decides which Pier may act on an Observatory-scoped shared resource (OBS-100).

    Piers register the work they are doing against a resource (:meth:`begin_activity`, e.g.
    "imaging" under a shared roof) and release it when done. A request for a *disruptive*
    action (closing the roof, slewing the dome) is **denied** while another Pier holds
    equal-or-higher-priority activity on that resource; a non-disruptive one is always granted.
    A requester may ask to **queue** (``wait_s``): it is re-evaluated until the blockers release
    or the wait expires (OBS-110). Safety actions use :data:`PRIORITY_EMERGENCY` and override
    imaging (OBS-130). Resources scoped per-Pier are never arbitrated (OBS-050).
    Thread-safe; decisions are published on the event bus.
    """

    def __init__(self, bus=None, poll_s: float = 0.1) -> None:
        self._bus = bus
        self._poll_s = poll_s
        self._lock = threading.Lock()
        # resource -> {pier_name: (activity, priority)}
        self._activities: dict[str, dict[str, tuple[str, int]]] = {}
        self._scopes: dict[str, str] = {}

    def _publish(self, event: Event) -> None:
        try:
            (self._bus or get_bus()).publish(event)
        except Exception:
            logger.debug("Could not publish %r", event, exc_info=True)

    def set_scope(self, resource: str, scope: str) -> None:
        """``"observatory"`` (arbitrated, the default) or ``"pier"`` (independent, never arbitrated)."""
        with self._lock:
            self._scopes[resource] = scope

    def scope(self, resource: str) -> str:
        return self._scopes.get(resource, "observatory")

    def begin_activity(self, pier: str, resource: str, activity: str = "imaging",
                       priority: int = PRIORITY_NORMAL) -> None:
        """Record that *pier* is actively using *resource* until :meth:`end_activity`."""
        with self._lock:
            self._activities.setdefault(resource, {})[pier] = (activity, priority)

    def end_activity(self, pier: str, resource: str) -> None:
        with self._lock:
            held = self._activities.get(resource, {}).pop(pier, None)
        if held is not None:
            self._publish(ResourceReleasedEvent(source=pier, resource=resource, activity=held[0]))

    def activities(self, resource: str) -> dict[str, str]:
        """``{pier: activity}`` currently registered against *resource*."""
        with self._lock:
            return {p: a for p, (a, _prio) in self._activities.get(resource, {}).items()}

    def check(self, pier: str, resource: str, action: str,
              priority: int = PRIORITY_NORMAL) -> ArbitrationDecision:
        """Decide now, without waiting or publishing."""
        if self.scope(resource) != "observatory":
            return ArbitrationDecision(True, "resource is Pier-scoped")
        if action not in DISRUPTIVE_ACTIONS.get(resource, frozenset()):
            return ArbitrationDecision(True, "non-disruptive action")
        with self._lock:
            blockers = tuple(sorted(
                p for p, (_a, prio) in self._activities.get(resource, {}).items()
                if p != pier and prio >= priority))
        if blockers:
            return ArbitrationDecision(
                False, f"{resource} {action} denied: {', '.join(blockers)} is using the shared {resource}",
                blockers)
        return ArbitrationDecision(True, "no conflicting activity")

    async def request(self, pier: str, resource: str, action: str,
                      priority: int = PRIORITY_NORMAL, wait_s: float = 0.0) -> ArbitrationDecision:
        """Ask to perform *action* on *resource*; with ``wait_s`` > 0, queue until free or timeout."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, wait_s)
        while True:
            decision = self.check(pier, resource, action, priority)
            if decision.granted or loop.time() >= deadline:
                break
            await asyncio.sleep(self._poll_s)
        cls = ResourceClaimGrantedEvent if decision.granted else ResourceClaimDeniedEvent
        self._publish(cls(source=pier, resource=resource, action=action, reason=decision.reason,
                          blocked_by=list(decision.blocked_by)))
        return decision


# ---------------------------------------------------------------------------
# Observatory
# ---------------------------------------------------------------------------

def _scheduler_summary(scheduler) -> tuple[str, int, str | None]:
    """``(state, queued_jobs, running_job_name)`` for a Pier's job queue (OBS-060).

    State is ``running`` while a job executes, ``queued`` while jobs are waiting,
    else ``idle`` (also when the Pier has no scheduler at all)."""
    if scheduler is None:
        return "idle", 0, None
    jobs = list(getattr(scheduler, "jobs", []) or [])
    running = getattr(scheduler, "active_job", None) or next(
        (j for j in jobs if getattr(j, "run_state", "") == "running"), None)
    queued = sum(1 for j in jobs if getattr(j, "run_state", "pending") == "pending")
    if running is not None:
        return "running", queued, str(getattr(running, "name", running))
    return ("queued" if queued else "idle"), queued, None


class Observatory:
    """Groups multiple Piers; manages shared safety and dome resources."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.piers: list[Pier] = []
        self.safety_monitor = None      # Observatory-scoped, shared by every Pier (OBS-030)
        self.dome = None
        self._event_bus = None
        self.state = "idle"
        self.contact_details: ContactDetails | None = None
        self.arbiter = ResourceArbiter()

    def add_pier(self, pier: Pier) -> None:
        self.piers.append(pier)

    def set_contact_details(
        self,
        email: str | None = None,
        phone_number: str | None = None,
        channels: list[str] | None = None,
    ) -> None:
        """Set the operator's own external-notification contact details
        (OBS-090) — one per Observatory, read by :mod:`galileo.notify`
        (NOTIF-040) regardless of which Pier raised the event."""
        self.contact_details = ContactDetails(
            email=email, phone_number=phone_number, channels=channels,
        )

    def set_safety_monitor(self, monitor) -> None:
        """Safety devices belong to the Observatory, not to a Pier (OBS-030): one monitor is
        shared by every member Pier."""
        self.safety_monitor = monitor

    def set_dome(self, dome, scope: str = "observatory") -> None:
        self.arbiter.set_scope(RESOURCE_DOME, scope)
        if scope == "observatory":
            self.dome = dome

    def get_dashboard(self) -> list[dict]:
        """Return a status summary for every Pier (OBS-060): equipment, sequence and
        scheduler state, plus the scheduler's queue depth and running job."""
        rows = []
        for pier in self.piers:
            scheduler_state, queued, active = _scheduler_summary(getattr(pier, "scheduler", None))
            rows.append({
                "pier_name": pier.name,
                "equipment_state": "connected" if pier.device_pool else "disconnected",
                "sequence_state": getattr(pier.sequence_runner, "state", "idle"),
                "scheduler_state": scheduler_state,
                "queued_jobs": queued,
                "active_job": active,
            })
        return rows

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

def list_observatories() -> list[ObservatoryRecord]:
    """Return every saved Observatory, alphabetically by name."""
    from galileo.library.models.observatory import ObservatoryRecord
    return list(ObservatoryRecord.select().order_by(ObservatoryRecord.name))


def create_observatory(
    name: str,
    latitude: float | None = None,
    longitude: float | None = None,
    elevation_m: float | None = None,
    timezone: str | None = None,
    physical_address: str | None = None,
    owner: str | None = None,
    notification_type: str | None = None,
    email_address: str | None = None,
    cell_number: str | None = None,
) -> ObservatoryRecord:
    """Create and persist a new Observatory settings record."""
    from galileo.library.models.observatory import ObservatoryRecord
    return ObservatoryRecord.create(
        name=name,
        latitude=latitude,
        longitude=longitude,
        elevation_m=elevation_m,
        timezone=timezone,
        physical_address=physical_address,
        owner=owner,
        notification_type=notification_type,
        email_address=email_address,
        cell_number=cell_number,
    )


def list_piers(observatory: ObservatoryRecord) -> list[PierRecord]:
    """Return every saved Pier belonging to *observatory*, alphabetically by name."""
    from galileo.library.models.observatory import PierRecord
    return list(PierRecord.select().where(PierRecord.observatory == observatory).order_by(PierRecord.name))


def create_pier(observatory: ObservatoryRecord, name: str) -> PierRecord:
    """Create and persist a new Pier settings record under *observatory*."""
    from galileo.library.models.observatory import PierRecord
    return PierRecord.create(observatory=observatory, name=name)


#: The user-editable ObservatoryRecord columns (everything but the primary key).
OBSERVATORY_FIELDS = (
    "name", "latitude", "longitude", "elevation_m", "timezone", "physical_address",
    "owner", "notification_type", "email_address", "cell_number",
)


def update_observatory(observatory: ObservatoryRecord, **fields) -> ObservatoryRecord:
    """Persist edited *fields* on *observatory* (the same instance is updated in place,
    so anything holding it sees the change). Unknown field names raise ``ValueError``."""
    unknown = set(fields) - set(OBSERVATORY_FIELDS)
    if unknown:
        raise ValueError(f"Unknown Observatory field(s): {', '.join(sorted(unknown))}")
    for key, value in fields.items():
        setattr(observatory, key, value)
    observatory.save()
    return observatory


def rename_pier(pier: PierRecord, name: str) -> PierRecord:
    """Persist a new *name* for *pier*, updating the instance in place."""
    pier.name = name
    pier.save()
    return pier


def set_pier_connect_on_startup(pier: PierRecord, connect_on_startup: bool) -> None:
    """Persist *pier*'s "Connect on Startup" top-bar checkbox state."""
    pier.connect_on_startup = connect_on_startup
    pier.save()


def delete_observatory(observatory: ObservatoryRecord) -> None:
    """Permanently delete *observatory*'s settings record.

    Every Pier belonging to it — and, transitively, each Pier's device
    configs, optical tubes, and autofocus/solver settings — along with the
    Observatory's horizon points, cascade via the schema's own
    ``ON DELETE CASCADE`` (enforced since ``galileo.library.models.base``
    turns on SQLite's ``foreign_keys`` pragma), not application code here.
    """
    observatory.delete_instance()


def delete_pier(pier: PierRecord) -> None:
    """Permanently delete *pier*'s settings record.

    Its device configs, optical tubes, and autofocus/solver settings cascade
    via ``ON DELETE CASCADE``, same as :func:`delete_observatory`.
    """
    pier.delete_instance()


def list_horizon_points(observatory: ObservatoryRecord) -> list[tuple[float, float]]:
    """Return *observatory*'s horizon obstruction table as ``(azimuth°, altitude°)``
    pairs in azimuth order — empty if none has been uploaded."""
    from galileo.library.models.horizon import HorizonPointRecord
    rows = (HorizonPointRecord.select()
            .where(HorizonPointRecord.observatory == observatory)
            .order_by(HorizonPointRecord.azimuth_deg, HorizonPointRecord.id))
    return [(row.azimuth_deg, row.altitude_deg) for row in rows]


def save_horizon_points(observatory: ObservatoryRecord, points: list[tuple[float, float]]) -> None:
    """Replace *observatory*'s horizon obstruction table with *points* (Options >
    Star Atlas' upload). An empty list clears it."""
    from galileo.library.models.base import db
    from galileo.library.models.horizon import HorizonPointRecord
    with db.atomic():
        HorizonPointRecord.delete().where(HorizonPointRecord.observatory == observatory).execute()
        if points:
            HorizonPointRecord.insert_many(
                [{"observatory": observatory, "azimuth_deg": az, "altitude_deg": alt} for az, alt in points]
            ).execute()


def get_device_config(
    pier: PierRecord, category: str, slot: str = "primary"
) -> DeviceConfigRecord | None:
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
    pier: PierRecord,
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
    bayer_pattern: str | None = None,
    max_well_depth: int | None = None,
    panel_type: str | None = None,
    mount_limits: MountLimits | None = None,
) -> DeviceConfigRecord:
    """Create or update the saved device configuration for *category*/*slot*
    on *pier* (the Equipment page's per-device Save button). *bayer_pattern*
    (cameras only) is left as it was when omitted, and starts as ``RGGB``.
    *max_well_depth* (cameras only, electrons) feeds the Flat Assistant.
    *panel_type* (flat panel only) is left as it was when omitted, and starts
    as ``"Flat Panel"``. *mount_limits* (mount only) is left as it was when omitted."""
    from galileo.library.models.device_config import DeviceConfigRecord
    record = DeviceConfigRecord.get_or_none(
        (DeviceConfigRecord.pier == pier)
        & (DeviceConfigRecord.category == category)
        & (DeviceConfigRecord.slot == slot)
    )
    fields = {
        "driver": driver, "server": server, "port": port, "device_name": device_name,
        "pixel_size_um": pixel_size_um, "sensor_width_px": sensor_width_px,
        "sensor_height_px": sensor_height_px, "sensor_name": sensor_name,
    }
    if bayer_pattern is not None:
        fields["bayer_pattern"] = bayer_pattern
    if panel_type is not None:
        fields["panel_type"] = panel_type
    fields["max_well_depth"] = max_well_depth
    if mount_limits is not None:
        fields.update(dataclasses.asdict(mount_limits))
    if record is None:
        return DeviceConfigRecord.create(pier=pier, category=category, slot=slot, **fields)
    for key, value in fields.items():
        setattr(record, key, value)
    record.save()
    return record


def mount_limits_from_config(record: DeviceConfigRecord | None) -> MountLimits:
    """The Mount page's saved flip/limit settings from a mount's device config (defaults if none)."""
    from galileo.mount_limits import MountLimits
    if record is None:
        return MountLimits()
    return MountLimits(**{f.name: getattr(record, f.name) for f in dataclasses.fields(MountLimits)})


def delete_device_config(pier: PierRecord, category: str, slot: str = "primary") -> None:
    """Delete the saved device configuration for *category*/*slot* on *pier*,
    if any (used to prune a camera slot removed with the Camera page's "+"
    list, once the remaining slots no longer reach that far)."""
    from galileo.library.models.device_config import DeviceConfigRecord
    DeviceConfigRecord.delete().where(
        (DeviceConfigRecord.pier == pier)
        & (DeviceConfigRecord.category == category)
        & (DeviceConfigRecord.slot == slot)
    ).execute()


def get_autofocus_params(pier: PierRecord | None) -> AutofocusParams:
    """Return *pier*'s saved autofocus defaults (Options > Focus, FOC-070), or
    ``AutofocusParams()`` if none have been saved yet or no Pier is selected."""
    from galileo.autofocus import AutofocusParams
    if pier is None:
        return AutofocusParams()
    from galileo.library.models.autofocus_settings import AutofocusSettingsRecord
    record = AutofocusSettingsRecord.get_or_none(AutofocusSettingsRecord.pier == pier)
    if record is None:
        return AutofocusParams()
    return AutofocusParams(
        step_size=record.step_size, num_points=record.num_points,
        exposure_s=record.exposure_s, backlash_compensation=record.backlash_compensation,
    )


def save_autofocus_params(pier: PierRecord, params: AutofocusParams) -> None:
    """Create or update *pier*'s saved autofocus defaults (Options > Focus)."""
    from galileo.library.models.autofocus_settings import AutofocusSettingsRecord
    fields = {
        "step_size": params.step_size, "num_points": params.num_points,
        "exposure_s": params.exposure_s, "backlash_compensation": params.backlash_compensation,
    }
    record = AutofocusSettingsRecord.get_or_none(AutofocusSettingsRecord.pier == pier)
    if record is None:
        AutofocusSettingsRecord.create(pier=pier, **fields)
        return
    for key, value in fields.items():
        setattr(record, key, value)
    record.save()


def get_filter_offsets(pier: PierRecord | None) -> list[FilterOffset]:
    """Return *pier*'s saved per-filter offset state (Focus screen's Filter
    Offsets dialog, EQP-FW-020) — one entry per filter that has ever been
    measured or marked Primary on this Pier. Empty if none have been saved
    yet or no Pier is selected."""
    from galileo.autofocus import FilterOffset
    if pier is None:
        return []
    from galileo.library.models.filter_offset import FilterOffsetRecord
    return [
        FilterOffset(
            filter_name=record.filter_name, is_primary=record.is_primary,
            measurements=(record.measurement_1, record.measurement_2, record.measurement_3, record.measurement_4),
            offset_steps=record.offset_steps,
        )
        for record in FilterOffsetRecord.select().where(FilterOffsetRecord.pier == pier)
    ]


def get_primary_filter(pier: PierRecord | None) -> FilterOffset | None:
    """The one filter marked Primary on *pier*, or ``None`` if none is set."""
    return next((offset for offset in get_filter_offsets(pier) if offset.is_primary), None)


def save_filter_offset(pier: PierRecord, offset: FilterOffset) -> None:
    """Create or update *pier*'s saved offset state for ``offset.filter_name``.

    Marking a filter Primary (``offset.is_primary``) clears the flag from
    every other filter on this Pier first — FOC-060's offset calculation
    assumes exactly one Primary filter per Pier."""
    from galileo.library.models.filter_offset import FilterOffsetRecord
    if offset.is_primary:
        FilterOffsetRecord.update(is_primary=False).where(
            (FilterOffsetRecord.pier == pier) & (FilterOffsetRecord.filter_name != offset.filter_name)
        ).execute()
    m1, m2, m3, m4 = ([*list(offset.measurements), None, None, None, None])[:4]
    fields = {
        "is_primary": offset.is_primary, "measurement_1": m1, "measurement_2": m2,
        "measurement_3": m3, "measurement_4": m4, "offset_steps": offset.offset_steps,
    }
    record = FilterOffsetRecord.get_or_none(
        (FilterOffsetRecord.pier == pier) & (FilterOffsetRecord.filter_name == offset.filter_name)
    )
    if record is None:
        FilterOffsetRecord.create(pier=pier, filter_name=offset.filter_name, **fields)
        return
    for key, value in fields.items():
        setattr(record, key, value)
    record.save()


def get_filter_offset_steps(pier: PierRecord | None) -> dict[str, int]:
    """``{filter_name: offset_steps}`` for *pier*, skipping filters with no
    offset computed yet — ready to feed ``AutofocusService(filter_offsets=...)``
    for a filter-change focus compensation (FOC-060)."""
    return {
        offset.filter_name: offset.offset_steps
        for offset in get_filter_offsets(pier) if offset.offset_steps is not None
    }


# Safety devices (weather stations, safety monitors) and their rules belong to the Observatory,
# not to a Pier: one station watches the sky over every Pier under the roof (OBS-030).

def get_safety_device_config(
    observatory: ObservatoryRecord | None, category: str, slot: str = "primary"
) -> SafetyDeviceConfigRecord | None:
    """The saved safety device for *category*/*slot* on *observatory*, or ``None``."""
    if observatory is None:
        return None
    from galileo.library.models.weather_safety_rule import SafetyDeviceConfigRecord
    return SafetyDeviceConfigRecord.get_or_none(
        (SafetyDeviceConfigRecord.observatory == observatory)
        & (SafetyDeviceConfigRecord.category == category)
        & (SafetyDeviceConfigRecord.slot == slot)
    )


def save_safety_device_config(
    observatory: ObservatoryRecord, category: str, driver: str, server: str, port: int,
    device_name: str | None = None, slot: str = "primary",
) -> SafetyDeviceConfigRecord:
    """Create or update the safety device for *category*/*slot* on *observatory* (the Safety
    page's Save button)."""
    from galileo.library.models.weather_safety_rule import SafetyDeviceConfigRecord
    fields = {"driver": driver, "server": server, "port": port, "device_name": device_name}
    record = get_safety_device_config(observatory, category, slot)
    if record is None:
        return SafetyDeviceConfigRecord.create(observatory=observatory, category=category, slot=slot, **fields)
    for key, value in fields.items():
        setattr(record, key, value)
    record.save()
    return record


def delete_safety_device_config(observatory: ObservatoryRecord, category: str, slot: str = "primary") -> None:
    """Delete the saved safety device for *category*/*slot* on *observatory*, if any."""
    from galileo.library.models.weather_safety_rule import SafetyDeviceConfigRecord
    SafetyDeviceConfigRecord.delete().where(
        (SafetyDeviceConfigRecord.observatory == observatory)
        & (SafetyDeviceConfigRecord.category == category)
        & (SafetyDeviceConfigRecord.slot == slot)
    ).execute()


def list_safety_device_slots(observatory: ObservatoryRecord | None, category: str) -> list[str]:
    """Every slot saved for safety *category* on *observatory*, "primary" first then numbered."""
    if observatory is None:
        return []
    from galileo.library.models.weather_safety_rule import SafetyDeviceConfigRecord
    rows = SafetyDeviceConfigRecord.select(SafetyDeviceConfigRecord.slot).where(
        (SafetyDeviceConfigRecord.observatory == observatory) & (SafetyDeviceConfigRecord.category == category)
    )
    return sorted((row.slot for row in rows), key=_slot_sort_key)


def get_weather_safety_rules(observatory: ObservatoryRecord | None, slot: str = "primary") -> list[WeatherSafetyRule]:
    """Return *observatory*'s saved per-reading safety rules for the safety device in
    *slot* (Equipment > Safety screen, EQP-WX-020) -- one entry per reading the
    user has configured. Empty if none have been saved yet or no Observatory is
    selected."""
    from galileo.safety import WeatherSafetyRule
    if observatory is None:
        return []
    from galileo.library.models.weather_safety_rule import WeatherSafetyRuleRecord
    return [
        WeatherSafetyRule(
            parameter=record.parameter, label=record.label, unit=record.unit,
            safety_related=record.safety_related, operator=record.operator, threshold=record.threshold,
        )
        for record in WeatherSafetyRuleRecord.select().where(
            (WeatherSafetyRuleRecord.observatory == observatory) & (WeatherSafetyRuleRecord.slot == slot)
        )
    ]


def save_weather_safety_rule(observatory: ObservatoryRecord, rule: WeatherSafetyRule, slot: str = "primary") -> None:
    """Create or update *observatory*'s saved rule for ``rule.parameter`` (Equipment >
    Safety screen's Save button, EQP-WX-020)."""
    from galileo.library.models.weather_safety_rule import WeatherSafetyRuleRecord
    fields = {
        "label": rule.label, "unit": rule.unit, "safety_related": rule.safety_related,
        "operator": rule.operator, "threshold": rule.threshold,
    }
    record = WeatherSafetyRuleRecord.get_or_none(
        (WeatherSafetyRuleRecord.observatory == observatory) & (WeatherSafetyRuleRecord.slot == slot)
        & (WeatherSafetyRuleRecord.parameter == rule.parameter)
    )
    if record is None:
        WeatherSafetyRuleRecord.create(observatory=observatory, slot=slot, parameter=rule.parameter, **fields)
        return
    for key, value in fields.items():
        setattr(record, key, value)
    record.save()


def delete_weather_safety_rule(observatory: ObservatoryRecord, parameter: str, slot: str = "primary") -> None:
    """Delete *observatory*'s saved rule for *parameter* on the safety device in
    *slot*, if any."""
    from galileo.library.models.weather_safety_rule import WeatherSafetyRuleRecord
    WeatherSafetyRuleRecord.delete().where(
        (WeatherSafetyRuleRecord.observatory == observatory) & (WeatherSafetyRuleRecord.slot == slot)
        & (WeatherSafetyRuleRecord.parameter == parameter)
    ).execute()


def delete_weather_safety_rules(observatory: ObservatoryRecord, slot: str) -> None:
    """Delete every saved rule of the safety device in *slot* (its tab was removed)."""
    from galileo.library.models.weather_safety_rule import WeatherSafetyRuleRecord
    WeatherSafetyRuleRecord.delete().where(
        (WeatherSafetyRuleRecord.observatory == observatory) & (WeatherSafetyRuleRecord.slot == slot)
    ).execute()


def get_solver_settings(pier: PierRecord | None) -> tuple[str, SolverParams]:
    """Return *pier*'s saved ``(executable, SolverParams)`` (Options > Solve,
    PLT-060), or the Solve screen's long-standing defaults (auto-detected
    executable, no downsampling) if none have been saved yet or no Pier is
    selected."""
    from galileo.platesolve import SolverParams
    if pier is None:
        return "", SolverParams(downsample=0)
    from galileo.library.models.solver_settings import SolverSettingsRecord
    record = SolverSettingsRecord.get_or_none(SolverSettingsRecord.pier == pier)
    if record is None:
        return "", SolverParams(downsample=0)
    return record.executable or "", SolverParams(
        fov_hint_deg=record.fov_hint_deg, search_radius_deg=record.search_radius_deg,
        downsample=record.downsample,
    )


def save_solver_settings(pier: PierRecord, executable: str, params: SolverParams) -> None:
    """Create or update *pier*'s saved solver defaults (Options > Solve)."""
    from galileo.library.models.solver_settings import SolverSettingsRecord
    fields = {
        "executable": executable or None, "fov_hint_deg": params.fov_hint_deg,
        "search_radius_deg": params.search_radius_deg, "downsample": params.downsample,
    }
    record = SolverSettingsRecord.get_or_none(SolverSettingsRecord.pier == pier)
    if record is None:
        SolverSettingsRecord.create(pier=pier, **fields)
        return
    for key, value in fields.items():
        setattr(record, key, value)
    record.save()


def make_pier_solver(pier: PierRecord | None, pier_key=None, backend: str | None = None):
    """A ``PlateSolver`` built from *pier*'s saved Options > Solve settings (PLT-060): the chosen
    backend (or *backend* to override it for one run), its executable or API key, and the search
    parameters."""
    from galileo.platesolve import PlateSolver
    executable, params = get_solver_settings(pier)
    saved_backend, astrometry_executable, api_key = get_solver_backend(pier)
    backend = backend or saved_backend
    return PlateSolver(
        backend=backend, executable=astrometry_executable if backend == "astrometry_local" else executable,
        params=params, pier_key=pier_key, api_key=api_key)


def get_solver_backend(pier: PierRecord | None) -> tuple[str, str, str]:
    """Return *pier*'s saved ``(backend, astrometry_executable, nova_api_key)`` (Options > Solve,
    PLT-060); ``("astap", "", "")`` when nothing is saved."""
    if pier is None:
        return "astap", "", ""
    from galileo.library.models.solver_settings import SolverSettingsRecord
    record = SolverSettingsRecord.get_or_none(SolverSettingsRecord.pier == pier)
    if record is None:
        return "astap", "", ""
    return record.backend or "astap", record.astrometry_executable or "", record.nova_api_key or ""


def save_solver_backend(pier: PierRecord, backend: str, astrometry_executable: str = "", api_key: str = "") -> None:
    """Save *pier*'s solver backend choice, creating its solver settings row if need be."""
    from galileo.library.models.solver_settings import SolverSettingsRecord
    record = SolverSettingsRecord.get_or_none(SolverSettingsRecord.pier == pier)
    if record is None:
        record = SolverSettingsRecord(pier=pier)
    record.backend = backend
    record.astrometry_executable = astrometry_executable or None
    record.nova_api_key = api_key or None
    record.save()


def _slot_sort_key(slot: str) -> tuple:
    """Sort key putting "primary" first, then "<name>_<n>" by number, then the rest by name."""
    from galileo.library.models.device_config import PRIMARY_SLOT
    if slot == PRIMARY_SLOT:
        return (0, 0, "")
    prefix, _, suffix = slot.rpartition("_")
    if prefix and suffix.isdigit():
        return (1, int(suffix), prefix)
    return (2, 0, slot)


def list_device_config_slots(pier: PierRecord, category: str) -> list[str]:
    """Return every slot name saved for *category* on *pier* — used by the
    Camera page on load to know how many additional camera panels (beyond
    the always-present "primary") to rebuild.

    In slot order: "primary" first, then the numbered slots ("camera_2",
    "camera_3", …) by number, then anything else alphabetically. The database
    returns rows in whatever order it finds them — with the unique index on
    (pier, category, slot) that is alphabetical, which puts "camera_2" before
    "primary" — so callers that show these to the user, or take the first as a
    default, must not be left to that."""
    from galileo.library.models.device_config import DeviceConfigRecord
    rows = DeviceConfigRecord.select(DeviceConfigRecord.slot).where(
        (DeviceConfigRecord.pier == pier) & (DeviceConfigRecord.category == category)
    )
    return sorted((row.slot for row in rows), key=_slot_sort_key)


def list_device_configs(pier: PierRecord) -> list[DeviceConfigRecord]:
    """Return every saved device configuration on *pier*, across all
    categories and slots — the pool the Optics page's "Associated" picker
    offers to attach to an optical tube."""
    from galileo.library.models.device_config import DeviceConfigRecord
    return list(
        DeviceConfigRecord.select()
        .where(DeviceConfigRecord.pier == pier)
        .order_by(DeviceConfigRecord.category, DeviceConfigRecord.slot)
    )


def list_optical_tubes(pier: PierRecord) -> list[OpticalTubeRecord]:
    """Return *pier*'s saved optical tubes in display order."""
    from galileo.library.models.optical_tube import OpticalTubeRecord
    return list(
        OpticalTubeRecord.select()
        .where(OpticalTubeRecord.pier == pier)
        .order_by(OpticalTubeRecord.position)
    )


def save_optical_tubes(pier: PierRecord, tubes: list[dict]) -> None:
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
