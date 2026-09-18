"""Imaging tab service — preview, statistics, manual capture (IMG-010 … IMG-100)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ImagingService:
    """Domain-layer service for the imaging tab; no PySide6 dependency."""

    def __init__(self, camera=None, output_dir: "Path | str" = ".") -> None:
        self._camera = camera
        self._output_dir = Path(output_dir)
        self.current_frame = None
        self.current_preview = None
        self.last_saved_array = None
        self.last_saved_path: Path | None = None
        self.zoom_factor: float = 1.0
        self.pan_offset: tuple[int, int] = (0, 0)
        self.star_overlay_enabled: bool = False
        self.capture_status: str = "idle"
        self._panel_layout: dict = {}
        self._capture_status: str = "idle"

    # --- Capture ---------------------------------------------------------

    async def capture_and_preview(
        self,
        duration: float,
        filter_name: str = "",
        frame_type: str = "Light",
        save_dir: "Path | str | None" = None,
    ) -> None:
        """Expose, download, stretch, and cache the current frame (IMG-010 … IMG-030)."""
        import numpy as np

        self._capture_status = "exposing"
        self.capture_status = "exposing"

        await self._camera.start_exposure(duration=duration, frame_type=frame_type)
        data = await self._camera.get_image_array()

        self.current_frame = data
        self.last_saved_array = data

        if data is not None:
            self.current_preview = _auto_stretch(data)

        self._capture_status = "preview_ready"
        self.capture_status = "preview_ready"

        if save_dir is not None:
            import datetime
            out_dir = Path(save_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / f"frame_{datetime.datetime.utcnow().strftime('%H%M%S')}.fits"
            _save_fits(data, p)
            self.last_saved_path = p

    async def capture_single(self, duration: float, filter_name: str = "", frame_type: str = "Light"):
        """Manual single-exposure capture independent of any sequence (IMG-070)."""
        await self._camera.start_exposure(duration=duration, frame_type=frame_type)
        data = await self._camera.get_image_array()
        self.current_frame = data
        return data

    # --- Statistics (IMG-040) --------------------------------------------

    def get_frame_stats(self) -> dict:
        if self.current_frame is None:
            return {}
        return _compute_stats(self.current_frame)

    # --- Histogram (IMG-030) ---------------------------------------------

    def get_histogram(self) -> dict:
        if self.current_frame is None:
            return {"bins": [], "counts": []}
        return _compute_histogram(self.current_frame)

    # --- View controls (IMG-060) -----------------------------------------

    def set_zoom(self, factor: float) -> None:
        self.zoom_factor = factor

    def set_pan_offset(self, dx: int, dy: int) -> None:
        self.pan_offset = (dx, dy)

    def reset_view(self) -> None:
        self.zoom_factor = 1.0
        self.pan_offset = (0, 0)

    # --- Star overlay (IMG-050) -------------------------------------------

    def set_star_overlay(self, enabled: bool) -> None:
        self.star_overlay_enabled = enabled

    # --- Panel layout (IMG-080) ------------------------------------------

    def set_panel_layout(self, layout: dict) -> None:
        self._panel_layout = dict(layout)

    def get_panel_layout(self) -> dict:
        return dict(self._panel_layout)

    # --- Save current frame (IMG-100) ------------------------------------

    def save_current_frame(self, path: "Path | str") -> None:
        _save_fits(self.current_frame, Path(path))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auto_stretch(data):
    """Return an 8-bit auto-stretched preview array."""
    try:
        import numpy as np
        if data is None:
            return None
        d = data.astype(np.float32)
        lo, hi = float(np.percentile(d, 0.5)), float(np.percentile(d, 99.5))
        stretched = np.clip((d - lo) / (hi - lo + 1e-9), 0, 1)
        return (stretched * 255).astype(np.uint8)
    except Exception:
        return None


def _compute_stats(data) -> dict:
    try:
        import numpy as np
        from galileo.autofocus import _compute_hfr
        d = data.astype(np.float32)
        return {
            "mean": float(np.mean(d)),
            "median": float(np.median(d)),
            "min": float(np.min(d)),
            "max": float(np.max(d)),
            "star_count": 0,
            "hfr": _compute_hfr(d),
        }
    except Exception:
        return {"mean": 0, "median": 0, "min": 0, "max": 0, "star_count": 0, "hfr": 0}


def _compute_histogram(data) -> dict:
    try:
        import numpy as np
        counts, bins = np.histogram(data.flatten(), bins=256)
        return {"bins": bins[:-1].tolist(), "counts": counts.tolist()}
    except Exception:
        return {"bins": [], "counts": []}


def _save_fits(data, path: Path) -> None:
    try:
        import numpy as np
        from astropy.io import fits
        if data is None:
            data = np.zeros((10, 10), dtype=np.float32)
        path.parent.mkdir(parents=True, exist_ok=True)
        fits.PrimaryHDU(data).writeto(str(path), overwrite=True)
    except Exception:
        logger.exception("Failed to save FITS frame to %s", path)
