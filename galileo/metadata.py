# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""FITS image metadata writer (META-010 … META-050).

Wraps ``astropy.io.fits`` to write properly formed headers with all
required keywords, optional plate-solve WCS, tile compression, and
user-defined custom keywords.
"""

from __future__ import annotations

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
}


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

    def write(self, data, metadata: dict, filename: str | None = None) -> Path:
        """Write *data* to a FITS file with headers derived from *metadata*.

        Returns the path of the written file.
        """
        from astropy.io import fits
        import numpy as np

        if data is None:
            data = np.zeros((10, 10), dtype=np.float32)

        hdr = fits.Header()
        # Map Galileo metadata keys to FITS keywords
        for meta_key, fits_kw in _KEYWORD_MAP.items():
            if meta_key in metadata:
                hdr[fits_kw] = metadata[meta_key]

        # Session-level custom keywords (META-050)
        for kw, val in self._session_keywords.items():
            hdr[kw] = val

        # Build output path
        if filename is None:
            import datetime
            ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            obj = metadata.get("object", "frame").replace(" ", "_")
            filename = f"{obj}_{ts}.fits"

        out_path = self.output_dir / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if self.compression:
            comp_hdu = fits.CompImageHDU(data, header=hdr, compression_type=self.compression)
            fits.HDUList([fits.PrimaryHDU(), comp_hdu]).writeto(out_path, overwrite=True)
        else:
            fits.PrimaryHDU(data, header=hdr).writeto(out_path, overwrite=True)

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
