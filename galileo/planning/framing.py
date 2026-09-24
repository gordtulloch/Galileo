# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Framing assistant — FOV calculation and mosaic planning (FRAME-010 … FRAME-090).

Invoked contextually only (FRAME-070) — never as a primary-navigation section —
via :func:`open_from_imaging_tab` (IMG-180) or :func:`open_from_session_image_block`
(SES-130). Each call builds an independent ``FramingAssistant`` with its own
target/mosaic state; the only thing the two entry points share is the pane-overlap
setting (``MosaicSettings``, FRAME-040), which is scoped to Options > Imaging, not
per entry point.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_HIPS2FITS_URL = "https://alasky.cds.unistra.fr/hips-image-services/hips2fits"

# The CDS HiPS survey queried for cutouts — DSS2's color composite (its red
# and blue plates combined), preferred over a single-band plate wherever it's
# available.
_DSS_HIPS_SURVEY = "CDS/P/DSS2/color"

# Unlike STScI's old dss_search CGI (which returned a FITS cutout at a fixed
# pixel scale, so a large arcmin request meant a large file that eventually
# failed to parse), hips2fits takes the OUTPUT pixel size and the sky field of
# view as independent parameters — the pixel scale just gets coarser for a
# wider fov, it doesn't fail. Its only real limit is 50 million output pixels
# (irrelevant at this module's preview sizes), so this cap is just a sanity
# ceiling against a degenerate request (e.g. a very-wide-angle lens's FOV,
# padded 3x by survey_cutout_extent_deg), not a service limitation to work
# around.
_MAX_HIPS_FOV_DEG = 60.0


def _fetch_hips_cutout_sync(
    ra_deg: float, dec_deg: float, width_arcmin: float, height_arcmin: float, size_px: int = 480,
) -> bytes:
    """Blocking HiPS cutout fetch (FRAME-020) via the CDS hips2fits service,
    requesting a pre-rendered JPEG directly from the ``CDS/P/DSS2/color``
    composite (no local FITS decoding/normalization needed, since the color
    survey is already an 8-bit-per-channel rendering) — the same technique and
    API as ``galileo.planning.sky_atlas``'s ``_fetch_hips_thumbnail_sync``,
    generalized to a non-square, larger preview size. Returns ``b""`` on any
    failure (no internet, an unreadable response, …) rather than raising — a
    missing survey image is never fatal to the Framing Assistant."""
    import io

    try:
        import requests
        from PIL import Image

        width_deg = width_arcmin / 60.0
        height_deg = height_arcmin / 60.0
        if width_arcmin >= height_arcmin:
            width_px = size_px
            height_px = max(1, round(size_px * height_arcmin / width_arcmin)) if width_arcmin else size_px
        else:
            height_px = size_px
            width_px = max(1, round(size_px * width_arcmin / height_arcmin))
        fov_deg = max(width_deg, height_deg)

        resp = requests.get(
            _HIPS2FITS_URL,
            params={
                "hips": _DSS_HIPS_SURVEY,
                "width": width_px,
                "height": height_px,
                "fov": fov_deg,
                "projection": "TAN",
                "coordsys": "icrs",
                "ra": ra_deg,
                "dec": dec_deg,
                "format": "jpg",
            },
            timeout=15,
        )
        resp.raise_for_status()
        # Round-trip through PIL to confirm the response is actually a decodable
        # image (a service error can still come back with a 200 status).
        image = Image.open(io.BytesIO(resp.content)).convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="JPEG")
        return buf.getvalue()
    except Exception:
        logger.debug(
            "Could not fetch HiPS cutout for RA=%s Dec=%s", ra_deg, dec_deg, exc_info=True
        )
        return b""


def _survey_cache_path(ra_deg: float, dec_deg: float, width_deg: float, height_deg: float):
    from galileo.platform import get_cache_dir
    name = f"framing_{ra_deg:.4f}_{dec_deg:.4f}_{width_deg:.3f}x{height_deg:.3f}.jpg"
    return get_cache_dir() / name


def _cache_survey_image(ra_deg: float, dec_deg: float, width_deg: float, height_deg: float, data: bytes) -> None:
    try:
        _survey_cache_path(ra_deg, dec_deg, width_deg, height_deg).write_bytes(data)
    except Exception:
        logger.debug("Could not cache survey image", exc_info=True)


def _cached_survey_image(ra_deg: float, dec_deg: float, width_deg: float, height_deg: float) -> bytes:
    path = _survey_cache_path(ra_deg, dec_deg, width_deg, height_deg)
    try:
        return path.read_bytes() if path.exists() else b""
    except Exception:
        return b""


class RotatorUnavailableError(Exception):
    """Rotation was requested but the active optical train has no rotator (FRAME-030)."""


@dataclass
class FOV:
    """Field of view rectangle in degrees."""
    width_deg: float
    height_deg: float
    rotation_deg: float = 0.0


@dataclass
class MosaicPanel:
    """One panel in a mosaic grid."""
    pane_index: int
    ra_deg: float
    dec_deg: float
    overlap_pct: float

    @property
    def ra(self) -> float:  # alias for backwards compat with tests
        return self.ra_deg

    @property
    def dec(self) -> float:
        return self.dec_deg


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


@dataclass
class MosaicCaptureStep:
    """One step of a pane-major mosaic capture pass (FRAME-090)."""
    pane_index: int
    pass_index: int
    requires_reslew: bool = True
    requires_guider_dither: bool = False


def mosaic_capture_order(mosaic: Mosaic, exposures_per_pane: int) -> list[MosaicCaptureStep]:
    """Pane-major capture order (FRAME-090): one exposure at every pane in
    turn, repeating the pass for additional exposures per pane, rather than
    exhausting one pane before the next. The re-slew between passes is what
    dithers a pane's frames against each other — no separate guider-dither
    command is needed between them.

    Module-level (not a ``FramingAssistant`` method) because executing a
    mosaic needs only the already-built ``Mosaic`` and no optical-train
    state — the shared helper ``galileo.ui.imaging.ImagingService`` and
    ``galileo.sequencer.basic`` both call to actually run one."""
    return [
        MosaicCaptureStep(pane_index=panel.pane_index, pass_index=pass_index)
        for pass_index in range(exposures_per_pane)
        for panel in mosaic.panels
    ]


@dataclass
class FovSpec:
    """One camera's field of view, for Compare Cameras (FRAME-080)."""
    width_deg: float
    height_deg: float
    pier_name: str = ""
    camera_name: str = ""


@dataclass
class CameraComparison:
    """Result of comparing every Pier's camera FOV (FRAME-080)."""
    fovs: list[FovSpec]
    survey_scale_deg: float


class MosaicSettings:
    """The shared, Imaging-settings-scoped pane-overlap value (FRAME-040) — one
    process-wide instance, not configured separately per Framing Assistant entry
    point. Backed by ``IMG-170``'s Options > Imaging screen once that setting is
    wired up there; until then this is the in-memory default."""

    _instance: "MosaicSettings | None" = None

    def __init__(self) -> None:
        self.pane_overlap_pct: float = 10.0

    @classmethod
    def instance(cls) -> "MosaicSettings":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_pane_overlap_pct(self, value: float) -> None:
        self.pane_overlap_pct = value


class FramingAssistant:
    """Computes FOV, builds mosaic layouts, and holds one entry point's
    target/mosaic state for a given optical train."""

    def __init__(
        self,
        focal_length_mm: float,
        sensor_width_px: int,
        sensor_height_px: int,
        pixel_size_um: float,
        rotator_available: bool = False,
    ) -> None:
        self._focal_length_mm = focal_length_mm
        self._sensor_width_px = sensor_width_px
        self._sensor_height_px = sensor_height_px
        self._pixel_size_um = pixel_size_um
        self.rotator_available = rotator_available

        self._target_ra: float | None = None
        self._target_dec: float | None = None
        self._target_name: str = ""
        self._mosaic: Mosaic | None = None
        self._rotation_angle: float = 0.0
        self.show_constellations: bool = False
        self.show_grid: bool = False
        self.opening_context: Any = None

    @classmethod
    def _default(cls) -> "FramingAssistant":
        """Fallback optical-train parameters when no profile data is available —
        the reference camera/OTA from the PSD (Section 6.8)."""
        return cls(focal_length_mm=1000, sensor_width_px=4656, sensor_height_px=3520,
                    pixel_size_um=5.86, rotator_available=False)

    @classmethod
    def from_profile(cls, profile_data: Any) -> "FramingAssistant":
        """Build a FramingAssistant from a profile dict or EquipmentProfile."""
        try:
            from galileo.equipment.profiles import EquipmentProfile
            if isinstance(profile_data, EquipmentProfile):
                train = profile_data.piers[0].optical_trains[0]
                cam = getattr(train, "camera", {}) or {}
                rotator = getattr(train, "rotator", None)
                focal_length_mm = float(train.focal_length_mm)
            else:
                train_data = profile_data["piers"][0]["optical_trains"][0]
                cam = train_data.get("camera", {}) or {}
                rotator = train_data.get("rotator")
                focal_length_mm = float(train_data.get("focal_length_mm", 1000))
        except (KeyError, IndexError, TypeError):
            return cls._default()

        return cls(
            focal_length_mm=focal_length_mm,
            sensor_width_px=cam.get("sensor_width_px", 4656),
            sensor_height_px=cam.get("sensor_height_px", 3520),
            pixel_size_um=cam.get("pixel_size_um", 5.86),
            rotator_available=bool(rotator),
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
        """Rotate the framing rectangle (FRAME-030) — unavailable, not silently
        ignored, when the active optical train has no rotator."""
        if not self.rotator_available:
            raise RotatorUnavailableError("The active optical train has no rotator equipped.")
        self._rotation_angle = angle

    @property
    def rotation_angle(self) -> float:
        return self._rotation_angle

    def set_target(self, ra: float, dec: float, name: str = "") -> None:
        self._target_ra = ra
        self._target_dec = dec
        self._target_name = name

    @property
    def target_name(self) -> str:
        return self._target_name

    def set_mosaic(self, mosaic: Mosaic | None) -> None:
        self._mosaic = mosaic

    @property
    def mosaic(self) -> Mosaic | None:
        return self._mosaic

    def attach_to_context(self) -> dict:
        """Attach the defined framing target to whichever context opened this
        assistant, as that context's own capture target (FRAME-050) — a mosaic
        attaches as one unit, never decomposed into separate per-panel targets."""
        if self._mosaic is not None:
            return {
                "name": self._target_name,
                "ra_deg": self._target_ra,
                "dec_deg": self._target_dec,
                "mosaic": self._mosaic,
                "is_mosaic": True,
            }
        return {
            "name": self._target_name,
            "ra_deg": self._target_ra,
            "dec_deg": self._target_dec,
            "is_mosaic": False,
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
                    pane_index=idx,
                    ra_deg=ra,
                    dec_deg=dec,
                    overlap_pct=overlap_pct,
                ))
                idx += 1

        return Mosaic(cols=cols, rows=rows, overlap_pct=overlap_pct, panels=panels)

    def mosaic_footprint_deg(self, cols: int, rows: int, overlap_pct: float) -> tuple[float, float]:
        """The overall RA/Dec extent a *cols*×*rows* mosaic grid covers (FRAME-040)
        — the same panel spacing :meth:`create_mosaic` uses, without building the
        panels themselves. Used to size a survey-image fetch/preview around the
        whole grid rather than just one pane."""
        fov = self.compute_fov()
        step_ra = fov.width_deg * (1.0 - overlap_pct / 100.0)
        step_dec = fov.height_deg * (1.0 - overlap_pct / 100.0)
        width_deg = fov.width_deg + max(cols - 1, 0) * step_ra
        height_deg = fov.height_deg + max(rows - 1, 0) * step_dec
        return width_deg, height_deg

    def rotated_frame_bounding_box_deg(self, rotation_deg: float) -> tuple[float, float]:
        """The axis-aligned bounding box of the single-frame FOV tilted by
        *rotation_deg* (FRAME-030's no-rotator fallback): with no rotator to
        physically achieve that tilt, this is the (un-rotated) area a covering
        mosaic needs to span instead."""
        rad = math.radians(rotation_deg)
        fov = self.compute_fov()
        width_deg = abs(fov.width_deg * math.cos(rad)) + abs(fov.height_deg * math.sin(rad))
        height_deg = abs(fov.width_deg * math.sin(rad)) + abs(fov.height_deg * math.cos(rad))
        return width_deg, height_deg

    def mosaic_grid_to_cover_deg(self, width_deg: float, height_deg: float, overlap_pct: float) -> tuple[int, int]:
        """The smallest ``cols``×``rows`` mosaic grid (at this train's FOV and
        *overlap_pct*) whose footprint (:meth:`mosaic_footprint_deg`) fully
        contains a *width_deg* × *height_deg* area — used to size the covering
        mosaic for :meth:`rotated_frame_bounding_box_deg`, or any other target
        area larger than one frame."""
        fov = self.compute_fov()
        step_ra = fov.width_deg * (1.0 - overlap_pct / 100.0)
        step_dec = fov.height_deg * (1.0 - overlap_pct / 100.0)
        cols = 1 + max(0, math.ceil((width_deg - fov.width_deg) / step_ra)) if step_ra > 0 else 1
        rows = 1 + max(0, math.ceil((height_deg - fov.height_deg) / step_dec)) if step_dec > 0 else 1
        return max(1, cols), max(1, rows)

    def mosaic_capture_order(self, mosaic: Mosaic, exposures_per_pane: int) -> list[MosaicCaptureStep]:
        """Pane-major capture order (FRAME-090). Delegates to the module-level
        :func:`mosaic_capture_order`, the shared helper both ``galileo.ui.imaging``
        and ``galileo.sequencer.basic`` call to actually execute a mosaic — it
        needs no optical-train state, so it doesn't need a FramingAssistant."""
        return mosaic_capture_order(mosaic, exposures_per_pane)

    def compare_cameras(self, observatory: Any) -> CameraComparison:
        """Overlay every camera configured across every Pier in *observatory*
        (FRAME-080), auto-scaled to the largest field size among them."""
        fovs = list(observatory.all_camera_fovs())
        survey_scale_deg = max((max(f.width_deg, f.height_deg) for f in fovs), default=0.0)
        return CameraComparison(fovs=fovs, survey_scale_deg=survey_scale_deg)

    def set_overlay(self, constellations: bool, coordinate_grid: bool) -> None:
        self.show_constellations = constellations
        self.show_grid = coordinate_grid

    def survey_cutout_extent_deg(
        self, width_deg: float | None = None, height_deg: float | None = None,
    ) -> tuple[float, float]:
        """The sky extent (degrees) a survey-image fetch around *width_deg* ×
        *height_deg* (the current FOV, or a mosaic footprint) should request —
        padded so the FOV/mosaic rectangle reads as a frame against surrounding
        sky context rather than filling the whole preview, and clamped to a
        sanity ceiling (``_MAX_HIPS_FOV_DEG``) against a degenerate request —
        a field that's already close to or beyond that ceiling is requested at
        the ceiling rather than growing without bound.
        Defaults to the current single-frame FOV when not given."""
        if width_deg is None or height_deg is None:
            fov = self.compute_fov()
            width_deg, height_deg = fov.width_deg, fov.height_deg
        pad = 3.0
        max_deg = _MAX_HIPS_FOV_DEG
        return (
            min(max(width_deg * pad, 0.15), max_deg),
            min(max(height_deg * pad, 0.15), max_deg),
        )

    async def get_background(self, ra: float, dec: float, mode: str = "online") -> bytes:
        if mode == "online":
            return await self._fetch_online_image(ra, dec)
        return self._render_offline(ra, dec)

    async def _fetch_online_image(
        self, ra: float, dec: float, width_deg: float | None = None, height_deg: float | None = None,
    ) -> bytes:
        """Fetch a DSS sky-survey cutout around (*ra*, *dec*) (FRAME-020) via the
        CDS hips2fits service, sized to *width_deg* × *height_deg* (or the current
        FOV, when not given) padded via :meth:`survey_cutout_extent_deg`. Cached to
        disk on success so a later offline lookup of the same field can still show
        something."""
        ext_w_deg, ext_h_deg = self.survey_cutout_extent_deg(width_deg, height_deg)
        data = await asyncio.to_thread(
            _fetch_hips_cutout_sync, ra, dec, ext_w_deg * 60.0, ext_h_deg * 60.0,
        )
        if data:
            _cache_survey_image(ra, dec, ext_w_deg, ext_h_deg, data)
        return data

    def _render_offline(
        self, ra: float, dec: float, width_deg: float | None = None, height_deg: float | None = None,
    ) -> bytes:
        """The cached copy of a previous online fetch for this field, if any
        (FRAME-020's offline/cached mode) — ``b""`` when nothing was ever cached."""
        ext_w_deg, ext_h_deg = self.survey_cutout_extent_deg(width_deg, height_deg)
        return _cached_survey_image(ra, dec, ext_w_deg, ext_h_deg)

    def get_background_offline(self, ra: float, dec: float) -> bytes:
        return self._render_offline(ra, dec)

    def fetch_survey_image_sync(
        self, ra: float, dec: float, width_deg: float | None = None, height_deg: float | None = None,
    ) -> bytes:
        """Synchronous convenience for Qt callers that can't await (the Imaging
        tab's Framing… dialog, FRAME-020): try the online source, falling back to
        any cached copy on failure — never raises."""
        try:
            data = asyncio.run(self._fetch_online_image(ra, dec, width_deg, height_deg))
            if data:
                return data
        except Exception:
            logger.debug("Online survey image fetch failed", exc_info=True)
        return self._render_offline(ra, dec, width_deg, height_deg)

    def close(self) -> Any:
        """Close this assistant and return to whichever context opened it (FRAME-070)."""
        return self.opening_context


# ---------------------------------------------------------------------------
# Entry points (FRAME-070) — the only two ways to obtain a FramingAssistant.
# There is deliberately no bare top-level constructor call/route registered
# anywhere in the UI shell (no ``PRIMARY_NAV_ENTRY``): the Framing Assistant is
# presented only when opened from the Imaging tab or a Session Image block.
# ---------------------------------------------------------------------------

def open_from_imaging_tab(context: Any, profile: Any = None) -> FramingAssistant:
    """Open a FramingAssistant for the Imaging tab's own Framing… control
    (IMG-180), against *context* (the ``ImagingService``) and, when known, the
    active Pier's *profile* data — falling back to reference defaults when not."""
    asst = FramingAssistant.from_profile(profile) if profile is not None else FramingAssistant._default()
    asst.opening_context = context
    return asst


def open_from_session_image_block(context: Any, profile: Any = None) -> FramingAssistant:
    """Open a FramingAssistant for a Session Image block's own Framing… control
    (SES-130), against *context* (the block) — independent state from any
    Imaging-tab assistant, per FRAME-070."""
    asst = FramingAssistant.from_profile(profile) if profile is not None else FramingAssistant._default()
    asst.opening_context = context
    return asst
