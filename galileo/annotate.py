# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Preview object annotation (IMG-200 … IMG-220): labels catalogued stars and deep-sky objects
on the Imaging tab's preview.

The layout — a circle at each object's position, a short leader line up to its label — is the
one `astronotation <https://gitlab.com/abonengo/astronotation>`_ (MIT licence) draws from
astrometry.net's own web-service annotation JSON. Galileo has no equivalent web service and needs
this to work fully offline, so positions instead come from a local plate solve (`galileo.platesolve`,
ASTAP/astrometry.net-local) and the bundled star/DSO catalogs already used elsewhere
(`galileo.planning.star_atlas`, `galileo.planning.sky_atlas`) — the rendering technique is reused,
not the data source.

Domain-core (no Qt/INDI/Alpaca): takes a preview array and a `SolveResult` and returns a new
array. Never touches `ImagingService.current_frame`/`current_preview` itself — the caller decides
what, if anything, to do with the result.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from galileo.platesolve import SolveResult

logger = logging.getLogger(__name__)

# The frame's own half-diagonal field of view is searched for catalog objects, widened by this
# margin so an object whose centre falls just outside the frame but whose disc still overlaps it
# is not missed.
_SEARCH_MARGIN = 1.15

MAX_STARS = 40
MAX_DSOS = 25
MIN_RADIUS_PX = 15.0
_OVERLAY_COLOR = (255, 255, 0, 255)   # yellow reads on both bright stars and dark background


@dataclass
class Annotation:
    """One labelled object placed on the preview, in preview-pixel coordinates."""
    name: str
    x: float
    y: float
    radius: float


def _gnomonic_pixel(ra_deg: float, dec_deg: float, solve: SolveResult, width: int, height: int):
    """Project a J2000 sky position to a preview pixel ``(x, y)``, via a tangent-plane
    (gnomonic) projection from *solve*'s centre, rotation and scale.

    This is a first-order approximation: `SolveResult` carries only a centre, a rotation angle
    and a scalar pixel scale (see `galileo.platesolve._result_from_astap_ini`) — no CD matrix or
    distortion terms — so this places a label near the right spot, not a scientific re-measurement
    of a position. Returns ``None`` for a position behind the tangent plane (>90° from centre).
    """
    ra0, dec0 = math.radians(solve.ra_deg), math.radians(solve.dec_deg)
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    d_ra = ra - ra0
    denom = math.sin(dec0) * math.sin(dec) + math.cos(dec0) * math.cos(dec) * math.cos(d_ra)
    if denom <= 0:
        return None
    xi = math.cos(dec) * math.sin(d_ra) / denom
    eta = (math.cos(dec0) * math.sin(dec) - math.sin(dec0) * math.cos(dec) * math.cos(d_ra)) / denom
    xi_as, eta_as = math.degrees(xi) * 3600.0, math.degrees(eta) * 3600.0
    scale = solve.scale_arcsec_px or 1.0
    rot = math.radians(solve.rotation_deg or 0.0)
    # East is left, by the same convention _result_from_astap_ini's rotation uses, so a positive
    # xi (east) moves left (negative x); pixel y grows downward while sky north is "up".
    dx = (-xi_as * math.cos(rot) - eta_as * math.sin(rot)) / scale
    dy = (-xi_as * math.sin(rot) + eta_as * math.cos(rot)) / scale
    return width / 2.0 + dx, height / 2.0 - dy


def _in_frame(pos, width: int, height: int) -> bool:
    if pos is None:
        return False
    x, y = pos
    return 0.0 <= x < width and 0.0 <= y < height


def _star_annotations(solve: SolveResult, width: int, height: int, radius_deg: float, catalog=None) -> list[Annotation]:
    try:
        import numpy as np

        from galileo.planning.star_atlas import load_star_catalog
        cat = catalog if catalog is not None else load_star_catalog()
    except Exception:
        logger.exception("Could not load the star catalog for annotation")
        return []
    if len(cat) == 0:
        return []
    d_ra = (cat.ra - solve.ra_deg + 180.0) % 360.0 - 180.0
    sep = np.hypot(d_ra * math.cos(math.radians(solve.dec_deg)), cat.dec - solve.dec_deg)
    out: list[Annotation] = []
    for i in np.argsort(sep):
        if sep[i] > radius_deg:
            break
        label = cat.label(i)
        if not label or label == "Star":
            continue      # an unnamed/undesignated star isn't worth cluttering the preview with
        pos = _gnomonic_pixel(float(cat.ra[i]), float(cat.dec[i]), solve, width, height)
        if not _in_frame(pos, width, height):
            continue
        out.append(Annotation(name=label, x=pos[0], y=pos[1], radius=MIN_RADIUS_PX))
        if len(out) >= MAX_STARS:
            break
    return out


def _dso_annotations(solve: SolveResult, width: int, height: int, radius_deg: float, catalog=None) -> list[Annotation]:
    try:
        from galileo.planning.sky_atlas import SkyAtlas
        objects = catalog if catalog is not None else SkyAtlas().search("")
    except Exception:
        logger.exception("Could not load the DSO catalog for annotation")
        return []
    scale = solve.scale_arcsec_px or 1.0
    scored: list[tuple[float, Annotation]] = []
    for obj in objects:
        d_ra = (obj.ra_deg - solve.ra_deg + 180.0) % 360.0 - 180.0
        sep = math.hypot(d_ra * math.cos(math.radians(solve.dec_deg)), obj.dec_deg - solve.dec_deg)
        if sep > radius_deg:
            continue
        pos = _gnomonic_pixel(obj.ra_deg, obj.dec_deg, solve, width, height)
        if not _in_frame(pos, width, height):
            continue
        radius_px = MIN_RADIUS_PX
        if obj.size_arcmin:
            radius_px = max(MIN_RADIUS_PX, (obj.size_arcmin * 60.0 / 2.0) / scale)
        scored.append((obj.magnitude, Annotation(name=obj.primary_name, x=pos[0], y=pos[1], radius=radius_px)))
    scored.sort(key=lambda pair: pair[0])   # brightest (lowest magnitude) first
    return [annotation for _, annotation in scored[:MAX_DSOS]]


def find_annotations(solve: SolveResult | None, width: int, height: int,
                      star_catalog=None, dso_catalog=None) -> list[Annotation]:
    """Every catalogued star/DSO from Galileo's bundled catalogs that falls within the frame
    *solve* describes, as preview-pixel positions — empty if *solve* has no usable solution."""
    if not (solve and solve.success and solve.ra_deg is not None and solve.dec_deg is not None
            and solve.scale_arcsec_px):
        return []
    radius_deg = (math.hypot(width, height) * solve.scale_arcsec_px / 3600.0 / 2.0) * _SEARCH_MARGIN
    return [
        *_star_annotations(solve, width, height, radius_deg, star_catalog),
        *_dso_annotations(solve, width, height, radius_deg, dso_catalog),
    ]


def _label_font():
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=14)
    except TypeError:      # Pillow < 10.1 has no `size` argument to the built-in bitmap font
        return ImageFont.load_default()


def render_annotations(preview, objects: list[Annotation]):
    """*preview* (an 8-bit gray or RGB array) with a circle, leader line and label drawn at each
    of *objects*, on a copy — *preview* itself is never modified. Returns an RGB ``uint8`` array,
    or *preview* unchanged if there is nothing to draw."""
    if preview is None or not objects:
        return preview
    import numpy as np
    from PIL import Image, ImageDraw

    array = np.asarray(preview)
    if array.ndim == 2:
        array = np.stack([array] * 3, axis=-1)
    img = Image.fromarray(array.astype(np.uint8), mode="RGB").convert("RGBA")
    draw = ImageDraw.Draw(img)
    font = _label_font()
    width, _height = img.size
    for obj in objects:
        x, y, r = obj.x, obj.y, max(obj.radius, MIN_RADIUS_PX)
        draw.ellipse((x - r, y - r, x + r, y + r), outline=_OVERLAY_COLOR, width=2)
        line_y = y - r - r * 0.5
        if (y - r) - line_y < 15:
            line_y = y - r - 15
        draw.line((x, y - r, x, line_y), fill=_OVERLAY_COLOR, width=2)
        text_y = max(0.0, line_y - 16)
        text_x = min(max(0.0, x - len(obj.name) * 3.5), max(0.0, width - len(obj.name) * 7))
        draw.text((text_x, text_y), obj.name, font=font, fill=_OVERLAY_COLOR)
    return np.array(img.convert("RGB"))


def _no_objects_note(solve: SolveResult | None) -> str:
    if not (solve and solve.success):
        reason = solve.failure_reason if solve is not None else "the frame has not been plate-solved"
        return f"Could not annotate: {reason}."
    return "Solved, but no catalogued objects were found in this field."


def annotate_preview(preview, solve: SolveResult | None):
    """Build the annotated view of *preview* for *solve*. Returns ``(overlay, note)`` — *overlay*
    is ``None`` (nothing to show) when *solve* did not succeed or no catalogued object falls
    within the frame; *note* is always set, for the Imaging page's status hint."""
    if preview is None:
        return None, ""
    height, width = preview.shape[0], preview.shape[1]
    objects = find_annotations(solve, width, height)
    if not objects:
        return None, _no_objects_note(solve)
    overlay = render_annotations(preview, objects)
    plural = "" if len(objects) == 1 else "s"
    return overlay, f"{len(objects)} object{plural} labelled."
