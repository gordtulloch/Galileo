# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment profiles — Pier / optical-train management (PROF-010 … PROF-090).

Profiles are persisted in the shared database (``galileo.settings_store``).
Each profile contains one or more Piers; each Pier has one or more
optical trains.  Plate scale is auto-derived from the train parameters.
"""

from __future__ import annotations

import json
import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_PROFILE_SUFFIX = ".gpf"


class DeviceUnreachableWarning(UserWarning):
    """Issued when a profile references a device that cannot be reached."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CameraConfig:
    name: str
    backend: str
    host: str
    pixel_size_um: float = 5.86
    sensor_width_px: int = 4656
    sensor_height_px: int = 3520


@dataclass
class OpticalTrain:
    """One imaging chain: scope → [accessories] → camera."""
    name: str
    focal_length_mm: float
    aperture_mm: float
    camera: dict = field(default_factory=dict)
    filter_wheel: dict = field(default_factory=dict)
    focuser: dict = field(default_factory=dict)
    rotator: dict = field(default_factory=dict)

    @property
    def effective_focal_length_mm(self) -> float:
        return self.focal_length_mm

    @property
    def plate_scale_arcsec_px(self) -> float:
        """arcsec/pixel derived from camera pixel size and focal length."""
        px_um = self.camera.get("pixel_size_um", 0.0)
        if self.focal_length_mm and px_um:
            return (px_um / self.focal_length_mm) * 206.265
        return 0.0


@dataclass
class PierConfig:
    """One mount + one or more optical trains."""
    name: str
    optical_trains: list[OpticalTrain] = field(default_factory=list)


@dataclass
class EquipmentProfile:
    name: str
    version: int = 1
    piers: list[PierConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> EquipmentProfile:
        return _profile_from_dict(d)


# ---------------------------------------------------------------------------
# Profile manager
# ---------------------------------------------------------------------------

class ProfileManager:
    """Loads, saves, and manages equipment profiles in the shared database.

    Profiles are ``app_settings`` rows (namespace ``equipment_profiles``, one key per profile
    name); the last-used name is ``equipment.last_used``. With no database available they live in
    memory for the session only. *storage_dir* names a folder of legacy ``*.gpf`` profile files
    (default: ``<data dir>/profiles``) that are imported once and renamed ``*.gpf.migrated``.
    ``.gpf`` files remain the portable interchange format for :meth:`export` / :meth:`import_profile`.
    """

    NAMESPACE = "equipment_profiles"
    META_NAMESPACE = "equipment"

    def __init__(self, storage_dir: Path | str | None = None) -> None:
        if storage_dir is None:
            from galileo.platform import get_data_dir
            self._legacy_dir = get_data_dir() / "profiles"
        else:
            self._legacy_dir = Path(storage_dir)
        self._in_memory: dict[str, EquipmentProfile] = {}
        self._last_used: str | None = None
        self._import_legacy()

    def _import_legacy(self) -> None:
        """One-time upgrade of ``*.gpf`` files (and ``.last_used``) into the database."""
        from galileo import settings_store
        try:
            if not self._legacy_dir.is_dir() or not settings_store.available():
                return
            for path in sorted(self._legacy_dir.glob(f"*{_PROFILE_SUFFIX}")):
                try:
                    data = json.loads(path.read_text("utf-8"))
                    name = _profile_from_dict(data).name or path.stem
                    if settings_store.get_setting(self.NAMESPACE, name) is None:
                        settings_store.set_setting(self.NAMESPACE, name, _profile_to_dict(_profile_from_dict(data)))
                    settings_store.mark_migrated(path)
                except Exception:
                    logger.warning("Could not import the legacy profile %s", path, exc_info=True)
            last = self._legacy_dir / ".last_used"
            if last.exists():
                if settings_store.get_setting(self.META_NAMESPACE, "last_used") is None:
                    settings_store.set_setting(self.META_NAMESPACE, "last_used", last.read_text("utf-8").strip())
                settings_store.mark_migrated(last)
        except Exception:
            logger.exception("Could not import the legacy equipment profiles")

    # --- CRUD -----------------------------------------------------------------

    def save(self, profile_data: dict | EquipmentProfile) -> None:
        """Persist *profile_data* to the database and update the in-memory cache."""
        from galileo import settings_store
        if isinstance(profile_data, EquipmentProfile):
            profile = profile_data
        else:
            profile = _profile_from_dict(profile_data)
        self._in_memory[profile.name] = profile
        settings_store.set_setting(self.NAMESPACE, profile.name, _profile_to_dict(profile))

    def exists(self, name: str) -> bool:
        from galileo import settings_store
        return name in self._in_memory or settings_store.get_setting(self.NAMESPACE, name) is not None

    def get(self, name: str) -> EquipmentProfile:
        if name not in self._in_memory:
            from galileo import settings_store
            data = settings_store.get_setting(self.NAMESPACE, name)
            if not isinstance(data, dict):
                from galileo.exceptions import ProfileNotFoundError
                raise ProfileNotFoundError(name)
            self._in_memory[name] = _profile_from_dict(data)
        return self._in_memory[name]

    def list_names(self) -> list[str]:
        from galileo import settings_store
        stored = set(settings_store.get_namespace(self.NAMESPACE))
        return sorted(stored | set(self._in_memory.keys()))

    def rename(self, old_name: str, new_name: str) -> None:
        profile = self.get(old_name)
        self.delete(old_name)
        profile.name = new_name
        self.save(profile)

    def delete(self, name: str) -> None:
        from galileo import settings_store
        self._in_memory.pop(name, None)
        settings_store.delete_setting(self.NAMESPACE, name)

    def export(self, name: str, dest: Path | str) -> None:
        """Export a profile to a portable .gpf file."""
        profile = self.get(name)
        Path(dest).write_text(json.dumps(_profile_to_dict(profile), indent=2), encoding="utf-8")

    def import_profile(self, src: Path | str) -> None:
        """Import a profile from a .gpf file."""
        data = json.loads(Path(src).read_text("utf-8"))
        self.save(data)

    # --- Persistence helpers --------------------------------------------------

    def set_last_used(self, name: str) -> None:
        from galileo import settings_store
        self._last_used = name
        settings_store.set_setting(self.META_NAMESPACE, "last_used", name)

    def get_last_used_name(self) -> str | None:
        from galileo import settings_store
        name = settings_store.get_setting(self.META_NAMESPACE, "last_used", self._last_used)
        return (name or "").strip() or None

    # --- Connect / load -------------------------------------------------------

    async def load(
        self,
        name: str,
        connect_fn: Callable[[dict], Awaitable[None]] | None = None,
    ) -> EquipmentProfile:
        """Load profile *name*, calling *connect_fn* for each device config."""
        profile = self.get(name)
        if connect_fn is not None:
            for pier in profile.piers:
                for train in pier.optical_trains:
                    for cfg in _device_configs(train):
                        try:
                            await connect_fn(cfg)
                        except (ConnectionError, OSError) as exc:
                            warnings.warn(
                                f"Device {cfg.get('name', '?')} unreachable: {exc}",
                                DeviceUnreachableWarning,
                                stacklevel=2,
                            )
        return profile

    def serialize_profile(self, name: str) -> dict:
        """Return serializable dict for the named profile (NFR-SEC-010)."""
        return _profile_to_dict(self.get(name))


class FirstRunWizard:
    """Guided first-run equipment-setup flow (NFR-USE-010)."""

    steps = ["welcome", "create_profile", "add_pier", "connect_camera", "connect_mount", "finish"]

    async def run(self, profile_manager: ProfileManager) -> EquipmentProfile | None:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _device_configs(train: OpticalTrain) -> list[dict]:
    configs = []
    for key in ("camera", "filter_wheel", "focuser", "rotator"):
        cfg = getattr(train, key)
        if cfg:
            configs.append(cfg)
    return configs


def _profile_to_dict(profile: EquipmentProfile) -> dict:
    d: dict = {"name": profile.name, "version": profile.version, "piers": []}
    for pier in profile.piers:
        pd: dict = {"name": pier.name, "optical_trains": []}
        for train in pier.optical_trains:
            td = {
                "name": train.name,
                "focal_length_mm": train.focal_length_mm,
                "aperture_mm": train.aperture_mm,
                "camera": train.camera,
                "filter_wheel": train.filter_wheel,
                "focuser": train.focuser,
                "rotator": train.rotator,
            }
            pd["optical_trains"].append(td)
        d["piers"].append(pd)
    return d


def _profile_from_dict(d: dict) -> EquipmentProfile:
    piers = []
    for pd in d.get("piers", []):
        trains = []
        for td in pd.get("optical_trains", []):
            trains.append(OpticalTrain(
                name=td.get("name", ""),
                focal_length_mm=float(td.get("focal_length_mm", 0)),
                aperture_mm=float(td.get("aperture_mm", 0)),
                camera=td.get("camera", {}),
                filter_wheel=td.get("filter_wheel", {}),
                focuser=td.get("focuser", {}),
                rotator=td.get("rotator", {}),
            ))
        piers.append(PierConfig(name=pd.get("name", ""), optical_trains=trains))
    return EquipmentProfile(
        name=d.get("name", ""),
        version=d.get("version", 1),
        piers=piers,
    )
