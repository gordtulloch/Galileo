# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Sky and framing on the engine (CSURF-130): the bundled catalogue and the Framing Assistant, for the Pier's own rig.

The catalogue is the Star Atlas's (``SkyAtlas``), searched offline; it loads on first use because reading it is the
slow part of starting. Rise, transit and set use the Pier's Observatory as the site. The field of view comes from the
Pier's first optical tube and its saved camera, the same figures the FITS header takes, so a Pier that has not saved
a camera with its sensor size and pixel size is refused rather than framed with made-up numbers.
"""

from __future__ import annotations

import logging
from typing import Any

from galileo.control_surface import Refused

logger = logging.getLogger(__name__)


def _brief(obj: Any) -> dict[str, Any]:
    return {"name": obj.primary_name, "designations": list(obj.designations), "ra_deg": obj.ra_deg,
            "dec_deg": obj.dec_deg, "type": str(obj.object_type), "magnitude": obj.magnitude,
            "size_arcmin": obj.size_arcmin}


class EngineSky:
    """``SkyAccess`` (``galileo.control_surface.sky``) over the Star Atlas and the Pier's saved rig."""

    def __init__(self, devices: Any, atlas: Any = None) -> None:
        self._devices, self._atlas = devices, atlas

    def _catalogue(self) -> Any:
        if self._atlas is None:
            from galileo.planning.sky_atlas import SkyAtlas
            self._atlas = SkyAtlas()
        return self._atlas

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], int]:
        found = self._catalogue().search(query)
        return [_brief(o) for o in found[:limit]], len(found)

    def detail(self, pier: str, name: str) -> dict[str, Any] | None:
        atlas = self._catalogue()
        try:
            obj = atlas.get_by_designation(name)
        except KeyError:
            wanted = name.strip().lower()
            matches = [o for o in atlas.search(name)
                       if wanted in (n.lower() for n in (o.primary_name, *o.designations))]
            if not matches:
                return None
            obj = matches[0]
        out = _brief(obj)
        out["description"] = obj.description
        location = self._location(pier)
        if location is None:
            out["rise_transit_set"] = None
            out["site"] = None
        else:
            out["site"] = location.name
            try:
                out["rise_transit_set"] = atlas.rise_transit_set(obj, location)
            except Exception:
                logger.exception("Could not work out when %s is up", obj.primary_name)
                out["rise_transit_set"] = None
        return out

    def framing(self, pier: str, *, ra_deg: float, dec_deg: float, rotation_deg: float, cols: int, rows: int,
                overlap_pct: float) -> dict[str, Any]:
        from galileo.planning.framing import FramingAssistant
        focal, width_px, height_px, pixel_um, rotator = self._rig(pier)
        assistant = FramingAssistant(focal, width_px, height_px, pixel_um, rotator_available=rotator)
        if rotator:
            assistant.set_rotation_angle(rotation_deg)
        fov = assistant.compute_fov()
        out: dict[str, Any] = {
            "ra_deg": ra_deg, "dec_deg": dec_deg, "rotation_deg": rotation_deg, "rotator": rotator,
            "focal_length_mm": focal, "pixel_size_um": pixel_um, "sensor_px": [width_px, height_px],
            "scale_arcsec_px": pixel_um / focal * 206.265,
            "fov_deg": [fov.width_deg, fov.height_deg]}
        if not rotator and rotation_deg:
            out["rotation_note"] = "this Pier has no rotator; the box is the area a covering mosaic would span"
            out["cover_deg"] = list(assistant.rotated_frame_bounding_box_deg(rotation_deg))
        mosaic = assistant.create_mosaic(ra_deg, dec_deg, cols, rows, overlap_pct, rotation_deg)
        out["mosaic"] = {"cols": cols, "rows": rows, "overlap_pct": overlap_pct,
                         "footprint_deg": list(assistant.mosaic_footprint_deg(cols, rows, overlap_pct, rotation_deg)),
                         "panels": [{"index": p.pane_index, "ra_deg": p.ra_deg % 360.0, "dec_deg": p.dec_deg}
                                    for p in mosaic.panels]}
        return out

    # -- the Pier's site and rig ---------------------------------------------------------------
    def _location(self, pier: str) -> Any:
        record = self._devices.pier_record(pier)
        try:
            observatory = record.observatory
            if observatory.latitude is None or observatory.longitude is None:
                return None
            from galileo.planning.visibility import ObservingLocation
            return ObservingLocation(name=observatory.name, latitude=observatory.latitude,
                                     longitude=observatory.longitude,
                                     elevation_m=getattr(observatory, "elevation_m", None) or 0.0)
        except Exception:
            logger.exception("Pier %s: could not read its Observatory", pier)
            return None

    def _rig(self, pier: str) -> tuple[float, int, int, float, bool]:
        record = self._devices.pier_record(pier)
        if record is None:
            raise Refused("there is no such Pier")
        from galileo.observatory import get_device_config, list_optical_tubes
        tubes = list_optical_tubes(record)
        focal = (tubes[0].focal_length_mm if tubes else 0) or 0
        if focal <= 0:
            raise Refused("this Pier has no optical tube with a focal length saved")
        camera = get_device_config(record, "camera")
        width, height = getattr(camera, "sensor_width_px", None), getattr(camera, "sensor_height_px", None)
        pixel = getattr(camera, "pixel_size_um", None)
        if not (width and height and pixel):
            raise Refused("this Pier's camera has no sensor size and pixel size saved")
        return float(focal), int(width), int(height), float(pixel), get_device_config(record, "rotator") is not None


__all__ = ["EngineSky"]
