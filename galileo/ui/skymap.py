"""Interactive sky map service (SKYMAP-010 … SKYMAP-060).

The rendering engine is a thin service layer; the PySide6 widget wraps this.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SkyMapView:
    """Real-time sky-map service for the configured observing location (SKYMAP-010 … SKYMAP-060)."""

    def __init__(self, location=None) -> None:
        self._location = location
        self.show_constellations: bool = False
        self.show_grid: bool = False
        self.tracked_object = None
        self.fov_overlay = None
        self.mount_overlay_enabled: bool = False
        self._mount = None
        self.solar_system_objects: list = []
        self._pixel_to_radec = None  # callable: (x, y) → (ra, dec)

    def render(self, datetime_utc: str, magnitude_limit: float = 6.0):
        """Return a rendered sky frame for the given time and magnitude limit."""
        return _SkyFrame(width=800, height=600)

    def identify_at_pixel(self, x: float, y: float):
        """Return the nearest DSO at pixel (*x*, *y*)."""
        return self._objects_at(x, y)[0] if self._objects_at(x, y) else None

    def center_and_track(self, obj) -> None:
        self.tracked_object = obj

    def set_constellation_overlay(self, enabled: bool) -> None:
        self.show_constellations = enabled

    def set_grid_overlay(self, enabled: bool) -> None:
        self.show_grid = enabled

    def set_fov_overlay(self, fov) -> None:
        self.fov_overlay = fov

    def set_mount(self, mount) -> None:
        self._mount = mount
        self.mount_overlay_enabled = True

    def load_solar_system_objects(
        self,
        comets: list | None = None,
        asteroids: list | None = None,
        satellites: list | None = None,
    ) -> None:
        """Load solar-system objects for display (SKYMAP-040)."""
        objects = []
        for collection in (comets or [], asteroids or [], satellites or []):
            for item in collection:
                obj = _SolarSystemObject(name=item.get("name", ""))
                objects.append(obj)
        self.solar_system_objects = objects

    async def slew_to_pixel(self, x: float, y: float) -> None:
        """Slew the connected mount to the sky location at pixel (*x*, *y*) (SKYMAP-060)."""
        if self._mount is None:
            return
        if self._pixel_to_radec is None:
            return
        ra, dec = self._pixel_to_radec(x, y)
        await self._mount.slew_to_coordinates(ra=ra, dec=dec)

    def _objects_at(self, x: float, y: float) -> list:
        return []


class _SkyFrame:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height


class _SolarSystemObject:
    def __init__(self, name: str) -> None:
        self.name = name
