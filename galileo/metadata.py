# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""FITS image metadata writer (META-010 … META-050).

Wraps ``astropy.io.fits`` to write properly formed headers with all
required keywords, optional plate-solve WCS, tile compression, and
user-defined custom keywords.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Required FITS header keywords mapped from Galileo metadata keys.
_KEYWORD_MAP = {
    "object": "OBJECT",
    "exposure_s": "EXPTIME",
    "filter": "FILTER",
    "gain": "GAIN",
    "offset": "OFFSET",
    "binning_x": "XBINNING",
    "binning_y": "YBINNING",
    "ccd_temp_c": "CCD-TEMP",
    "date_obs_utc": "DATE-OBS",
    "telescope": "TELESCOP",
    "focal_length_mm": "FOCALLEN",
    "pixel_size_x_um": "XPIXSZ",
    "pixel_size_y_um": "YPIXSZ",
    "frame_type": "IMAGETYP",
    "instrument": "INSTRUME",
    "observer": "OBSERVER",
    "site": "SITENAME",
    "date_end_utc": "DATE-END",
    "aperture_mm": "APTDIA",
    "bayer_pattern": "BAYERPAT",
    "ra_deg": "RA",
    "dec_deg": "DEC",
    "objctra": "OBJCTRA",
    "objctdec": "OBJCTDEC",
    "site_lat_deg": "SITELAT",
    "site_long_deg": "SITELONG",
    "pier_side": "PIERSIDE",
    "focus_position": "FOCUSPOS",
    "set_temp_c": "SET-TEMP",
    "software": "SWCREATE",
    "total_exposure_s": "EXPTOTAL",
    "frames_combined": "NCOMBINE",
}


# The FITS bit depths astronomy software actually reads. A 64-bit image (BITPIX 64, or -64 for a
# double) is legal FITS and astropy loads it without complaint, but ASTAP and Tenmon refuse it as an
# unsupported sample format, so nothing Galileo writes may use one.
_PORTABLE_DTYPES = ("uint8", "int16", "uint16", "int32", "float32")


# The BITPIX values ``normalise_pixels``' *bitpix* override accepts, each mapped to the numpy
# dtype astropy writes it as (FITS's "unsigned via BZERO" convention covers the uint8/uint16 cases).
# "auto" is not a real BITPIX; it means "pick the smallest of these that fits", the pre-existing
# behaviour and still the default.
BITPIX_AUTO = "auto"
_BITPIX_DTYPES = {8: "uint8", 16: "uint16", 32: "int32", -32: "float32"}
BITPIX_CHOICES = (BITPIX_AUTO, *_BITPIX_DTYPES)     # display/settings order: Auto, 8, 16, 32, -32


def normalise_pixels(data, bitpix: "int | str | None" = None):
    """*data* in a pixel format other astronomy software can read.

    Cameras reached over Alpaca hand their image back as JSON numbers, which numpy turns into
    64-bit integers; written straight out that becomes a 64-bit FITS that ASTAP, Tenmon and others
    reject as an unsupported sample format. With *bitpix* left as ``None``/``"auto"`` (the default,
    and the Imaging setup screen's "Auto"), integer data that fits is written as unsigned 16-bit —
    what astronomy cameras actually produce — and everything else as 32-bit float, the standard
    format for processed data such as a stack. Anything already in a portable type is left exactly
    as it is.

    A specific *bitpix* (8, 16, 32 or -32 — see ``BITPIX_CHOICES``) instead converts every frame to
    that one format regardless of what it already is, clipping out-of-range values rather than
    wrapping them and rounding a float to the nearest integer; a value clipped is logged once per
    call, not once per pixel. This is the Imaging setup screen's "desired BITPIX" (`IMG-170`) —
    some downstream tools expect one consistent format rather than whatever best fit each frame.
    """
    import numpy as np
    array = np.asarray(data)

    if bitpix not in (None, BITPIX_AUTO):
        try:
            bitpix = int(bitpix)
        except (TypeError, ValueError):
            bitpix = None
    if bitpix not in (None, BITPIX_AUTO):
        dtype = np.dtype(_BITPIX_DTYPES[bitpix])
        if array.dtype == dtype:
            return array
        info = np.iinfo(dtype) if np.issubdtype(dtype, np.integer) else None
        source = array.astype(np.float64) if np.issubdtype(array.dtype, np.floating) else array
        if info is not None:
            clipped = np.clip(np.round(source), info.min, info.max) if source.size else source
            if source.size and (source.min() < info.min or source.max() > info.max):
                logger.warning("A frame's pixel values were clipped to fit BITPIX %s (%s…%s).",
                               bitpix, info.min, info.max)
            return clipped.astype(dtype)
        return source.astype(dtype)

    if array.dtype.name in _PORTABLE_DTYPES:
        return array
    if np.issubdtype(array.dtype, np.integer) and array.size:
        if array.min() >= 0 and array.max() <= 65535:
            return array.astype(np.uint16)
        if -2147483648 <= array.min() and array.max() <= 2147483647:
            return array.astype(np.int32)
    return array.astype(np.float32)


def build_header(metadata: dict):
    """A FITS header holding every keyword *metadata* supplies (see ``_KEYWORD_MAP``).

    Shared by the imaging tab's saved frames and the frames written for the plate solver, so both
    describe the instrument the same way."""
    from astropy.io import fits
    header = fits.Header()
    for meta_key, fits_kw in _KEYWORD_MAP.items():
        if metadata.get(meta_key) not in (None, ""):
            header[fits_kw] = metadata[meta_key]
    # EXPOSURE is the older spelling of EXPTIME; some tools read only one of them.
    if "EXPTIME" in header and "EXPOSURE" not in header:
        header["EXPOSURE"] = header["EXPTIME"]
    return header


def build_primary_hdu(data, metadata: dict, bitpix: "int | str | None" = None, extra_cards=None):
    """A ``PrimaryHDU`` holding *data* (see ``normalise_pixels``) with *metadata*'s header cards
    (``build_header``) — and, after those, any ``extra_cards`` (an iterable of ``(keyword, value)``
    or ``(keyword, value, comment)``, e.g. session keywords or ``DATE``) — appended *after* the
    block astropy writes for the pixel data itself, never merged in before it.

    This ordering is not cosmetic. ``fits.PrimaryHDU(data, header=some_header)`` still produces
    valid FITS — astropy, and every tool built on it, reads it back without complaint — but for
    8- or 16-bit unsigned data astropy appends the ``BSCALE``/``BZERO`` cards the unsigned-integer
    convention needs *after* whatever header was already there, landing them at the very end of the
    file, after every custom keyword, rather than directly after ``NAXIS2`` where a camera's own
    FITS writer puts them and where ASTAP's minimal parser expects to find them. A file written that
    way was refused outright by ASTAP ("Error reading the image file") although it was otherwise
    entirely standard FITS that astropy, Tenmon and everything else opened without issue — building
    the HDU from the data alone first, so astropy places ``BSCALE``/``BZERO`` immediately after
    ``NAXIS2`` on its own, and only then appending the rest of the header, is what fixed it.
    """
    from astropy.io import fits
    hdu = fits.PrimaryHDU(normalise_pixels(data, bitpix=bitpix))
    for card in build_header(metadata).cards:
        hdu.header.append(card)
    for card in (extra_cards or ()):
        hdu.header.append(card)
    return hdu


class FitsMetadataWriter:
    """Writes FITS files with standardised header metadata (META-010 … META-050)."""

    def __init__(
        self,
        output_dir: "Path | str" = ".",
        compression: str | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.compression = compression  # e.g. "RICE_1", "GZIP_1", None
        self._session_keywords: dict[str, Any] = {}

    def set_session_keywords(self, keywords: dict[str, Any]) -> None:
        """Define custom static FITS keywords applied to every frame (META-050)."""
        self._session_keywords.update(keywords)

    def write(self, data, metadata: dict, filename: str | None = None, bitpix: "int | str | None" = None) -> Path:
        """Write *data* to a FITS file with headers derived from *metadata*.

        *bitpix* is the desired sample format (see ``normalise_pixels``); left as ``None`` it is
        chosen automatically, as before.

        Returns the path of the written file.
        """
        from astropy.io import fits
        import numpy as np

        if data is None:
            data = np.zeros((10, 10), dtype=np.float32)

        # Session-level custom keywords (META-050), then when this file was written, as distinct
        # from when the exposure began (DATE-OBS) — appended after the metadata cards, in the same
        # trailing-after-the-data-block order build_primary_hdu keeps for those.
        extra_cards = [(kw, val) for kw, val in self._session_keywords.items()]
        extra_cards.append(("DATE", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")))

        # Build output path
        if filename is None:
            ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            obj = metadata.get("object", "frame").replace(" ", "_")
            filename = f"{obj}_{ts}.fits"

        out_path = self.output_dir / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if self.compression:
            # Built from the pixels alone first, same reasoning as build_primary_hdu: this is what
            # keeps CFITSIO's own BSCALE/BZERO/tile-compression cards ahead of our custom ones.
            comp_hdu = fits.CompImageHDU(normalise_pixels(data, bitpix=bitpix), compression_type=self.compression)
            for card in build_header(metadata).cards:
                comp_hdu.header.append(card)
            for card in extra_cards:
                comp_hdu.header.append(card)
            fits.HDUList([fits.PrimaryHDU(), comp_hdu]).writeto(out_path, overwrite=True)
        else:
            build_primary_hdu(data, metadata, bitpix=bitpix, extra_cards=extra_cards).writeto(out_path, overwrite=True)

        return out_path


def write_solve_result(
    fits_path: "Path | str",
    ra_deg: float,
    dec_deg: float,
    rotation_deg: float,
    scale_arcsec_px: float,
) -> None:
    """Write plate-solve results as WCS keywords to an existing FITS file (META-020)."""
    from astropy.io import fits
    import math

    with fits.open(str(fits_path), mode="update") as hdul:
        hdr = hdul[0].header
        hdr["CTYPE1"] = "RA---TAN"
        hdr["CTYPE2"] = "DEC--TAN"
        hdr["CRVAL1"] = ra_deg
        hdr["CRVAL2"] = dec_deg
        cd_scale = scale_arcsec_px / 3600.0
        angle_rad = math.radians(rotation_deg)
        hdr["CD1_1"] = -cd_scale * math.cos(angle_rad)
        hdr["CD1_2"] = cd_scale * math.sin(angle_rad)
        hdr["CD2_1"] = cd_scale * math.sin(angle_rad)
        hdr["CD2_2"] = cd_scale * math.cos(angle_rad)
        hdul.flush()


def read_fits(fits_path: "Path | str") -> tuple:
    """Read a FITS file (compressed or not) and return (data, header)."""
    from astropy.io import fits

    with fits.open(str(fits_path)) as hdul:
        # If it's a CompImageHDU, read from extension 1
        for hdu in hdul:
            if hasattr(hdu, "data") and hdu.data is not None:
                return hdu.data, hdu.header
    return None, fits.Header()
