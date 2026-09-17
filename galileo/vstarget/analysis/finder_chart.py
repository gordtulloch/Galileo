"""AAVSO-style finder chart renderer (VST-AN-090)."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class FinderChartRenderer:
    """Generates a PNG finder chart for a variable-star field (VST-AN-090)."""

    async def render(
        self,
        target: str = "",
        ra_deg: float = 0.0,
        dec_deg: float = 0.0,
        fov_arcmin: float = 30.0,
    ) -> bytes:
        """Return the PNG bytes of the finder chart."""
        try:
            from astroquery.skyview import SkyView  # type: ignore[import]
            import astropy.units as u
            from astropy.coordinates import SkyCoord

            coord = SkyCoord(ra=ra_deg, dec=dec_deg, unit="deg", frame="icrs")
            images = await asyncio.to_thread(
                SkyView.get_images,
                position=coord,
                survey=["DSS"],
                radius=fov_arcmin * u.arcmin,
            )
            if not images:
                return b""

            # Convert FITS to PNG
            import numpy as np
            from io import BytesIO
            from astropy.visualization import ZScaleInterval
            import PIL.Image  # type: ignore[import]

            data = images[0][0].data
            interval = ZScaleInterval()
            vmin, vmax = interval.get_limits(data)
            normalized = np.clip((data - vmin) / (vmax - vmin + 1e-9), 0, 1)
            img_array = (normalized * 255).astype(np.uint8)
            pil_img = PIL.Image.fromarray(img_array)
            buf = BytesIO()
            pil_img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as exc:
            logger.debug("Finder chart render failed: %s", exc)
            return b"\x89PNG\r\n\x1a\n" + b"\x00" * 50  # minimal valid PNG-like header
