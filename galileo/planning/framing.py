"""Framing assistant — FOV calculation and mosaic planning (FRAME-010 … FRAME-060)."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FOV:
    """Field of view rectangle in degrees."""
    width_deg: float
    height_deg: float
    rotation_deg: float = 0.0


@dataclass
class MosaicPanel:
    """One panel in a mosaic grid."""
    panel_index: int
    ra_deg: float
    dec_deg: float
    overlap_pct: float

    @property
    def ra(self) -> float:  # alias for backwards compat with tests
        return self.ra_deg

    @property
    def dec(self) -> float:
        return self.dec_deg

    def as_sequence_target(self) -> dict:
        return {
            "name": f"Panel-{self.panel_index}",
            "ra_deg": self.ra_deg,
            "dec_deg": self.dec_deg,
        }


@dataclass
class Mosaic:
    """Grid of overlapping framing panels (FRAME-040)."""
    cols: int
    rows: int
    overlap_pct: float
    panels: list[MosaicPanel] = field(default_factory=list)

    @property
    def total_panels(self) -> int:
        return len(self.panels)


class FramingAssistant:
    """Computes FOV and builds mosaic layouts for a given optical train."""

    def __init__(
        self,
        focal_length_mm: float,
        sensor_width_px: int,
        sensor_height_px: int,
        pixel_size_um: float,
    ) -> None:
        self._focal_length_mm = focal_length_mm
        self._sensor_width_px = sensor_width_px
        self._sensor_height_px = sensor_height_px
        self._pixel_size_um = pixel_size_um

        self._target_ra: float | None = None
        self._target_dec: float | None = None
        self._target_name: str = ""
        self._rotation_angle: float = 0.0
        self.show_constellations: bool = False
        self.show_grid: bool = False

    @classmethod
    def from_profile(cls, profile_data: dict) -> "FramingAssistant":
        """Build a FramingAssistant from a profile dict or EquipmentProfile."""
        try:
            from galileo.equipment.profiles import EquipmentProfile
            if isinstance(profile_data, EquipmentProfile):
                train = profile_data.piers[0].optical_trains[0]
            else:
                train_data = profile_data["piers"][0]["optical_trains"][0]
                from galileo.equipment.profiles import _profile_from_dict, OpticalTrain
                train = OpticalTrain(
                    name=train_data.get("name", ""),
                    focal_length_mm=float(train_data.get("focal_length_mm", 1000)),
                    aperture_mm=float(train_data.get("aperture_mm", 100)),
                    camera=train_data.get("camera", {}),
                )
        except (KeyError, IndexError):
            return cls(focal_length_mm=1000, sensor_width_px=4656, sensor_height_px=3520, pixel_size_um=5.86)

        cam = getattr(train, "camera", {}) or {}
        return cls(
            focal_length_mm=train.focal_length_mm,
            sensor_width_px=cam.get("sensor_width_px", 4656),
            sensor_height_px=cam.get("sensor_height_px", 3520),
            pixel_size_um=cam.get("pixel_size_um", 5.86),
        )

    def compute_fov(self) -> FOV:
        """Return the FOV rectangle derived from the optical train parameters."""
        # FOV (deg) = (sensor_px * pixel_um / focal_mm) * 206.265 / 3600
        scale = (self._pixel_size_um / self._focal_length_mm) * 206.265 / 3600.0
        return FOV(
            width_deg=self._sensor_width_px * scale,
            height_deg=self._sensor_height_px * scale,
            rotation_deg=self._rotation_angle,
        )

    def set_rotation_angle(self, angle: float) -> None:
        self._rotation_angle = angle

    @property
    def rotation_angle(self) -> float:
        return self._rotation_angle

    def set_target(self, ra: float, dec: float, name: str = "") -> None:
        self._target_ra = ra
        self._target_dec = dec
        self._target_name = name

    def as_sequence_target(self) -> dict:
        return {
            "name": self._target_name,
            "ra_deg": self._target_ra,
            "dec_deg": self._target_dec,
        }

    def create_mosaic(
        self,
        center_ra: float,
        center_dec: float,
        cols: int,
        rows: int,
        overlap_pct: float,
    ) -> Mosaic:
        """Build a mosaic grid centred on (*center_ra*, *center_dec*)."""
        fov = self.compute_fov()
        step_ra = fov.width_deg * (1.0 - overlap_pct / 100.0)
        step_dec = fov.height_deg * (1.0 - overlap_pct / 100.0)

        panels = []
        idx = 0
        for row in range(rows):
            for col in range(cols):
                ra = center_ra + (col - (cols - 1) / 2.0) * step_ra
                dec = center_dec + (row - (rows - 1) / 2.0) * step_dec
                panels.append(MosaicPanel(
                    panel_index=idx,
                    ra_deg=ra,
                    dec_deg=dec,
                    overlap_pct=overlap_pct,
                ))
                idx += 1

        return Mosaic(cols=cols, rows=rows, overlap_pct=overlap_pct, panels=panels)

    def set_overlay(self, constellations: bool, coordinate_grid: bool) -> None:
        self.show_constellations = constellations
        self.show_grid = coordinate_grid

    async def get_background(self, ra: float, dec: float, mode: str = "online") -> bytes:
        if mode == "online":
            return await self._fetch_online_image(ra, dec)
        return self._render_offline(ra, dec)

    async def _fetch_online_image(self, ra: float, dec: float) -> bytes:
        return b""

    def _render_offline(self, ra: float, dec: float) -> bytes:
        return b""

    def get_background_offline(self, ra: float, dec: float) -> bytes:
        return self._render_offline(ra, dec)
