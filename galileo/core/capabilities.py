"""Device capabilities and connection state data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConnectionState(Enum):
    """Reported state of a device connection."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    DISCONNECTING = "disconnecting"


@dataclass
class DeviceCapabilities:
    """Advertised capabilities for a device.

    Fields are set by ``DeviceCapabilities.from_backend(backend)`` by
    inspecting the backend's ``capabilities`` attribute.  Absent capability
    fields default to ``False`` / ``None`` so that UI code can safely test
    any field without knowing the device category.
    """

    # Camera
    has_cooler: bool = False
    can_set_gain: bool = False
    can_set_offset: bool = False
    can_bin: bool = False
    max_bin_x: int = 1
    max_bin_y: int = 1
    has_shutter: bool = False
    sensor_width: int = 0
    sensor_height: int = 0
    pixel_size_x: float = 0.0
    pixel_size_y: float = 0.0

    # Mount
    can_track_non_sidereal: bool = False
    can_park: bool = False
    can_slew: bool = False
    can_sync: bool = False

    # Focuser
    can_set_position: bool = False
    has_temperature: bool = False

    # Rotator
    can_rotate: bool = False

    # Flat panel
    has_cover: bool = False
    has_brightness_control: bool = False

    # Platform-specific unavailable flag
    platform_unavailable: bool = False

    # Generic extension point for per-category extra capabilities
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_backend(cls, backend: object) -> "DeviceCapabilities":
        """Build a ``DeviceCapabilities`` from a device backend's attribute."""
        raw = getattr(backend, "capabilities", None)
        if raw is None:
            return cls()
        kwargs = {}
        for f in cls.__dataclass_fields__:
            if hasattr(raw, f):
                kwargs[f] = getattr(raw, f)
        return cls(**kwargs)
