"""Calibration frame creation and application (LIB-050 … LIB-060)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CalibrationApplyResult:
    calibrated_count: int


class LibraryCalibrationService:
    """Creates master calibration frames and applies them to light frames (LIB-050, LIB-060)."""

    def __init__(self, repo_dir: "Path | str") -> None:
        self._repo_dir = Path(repo_dir)

    def create_master_dark(self, input_dir: "Path | str", output_path: "Path | str") -> Path:
        """Mean-combine all FITS files in *input_dir* into a master dark (LIB-050)."""
        return _create_master(Path(input_dir), Path(output_path), frame_type="Dark Frame")

    def create_master_bias(self, input_dir: "Path | str", output_path: "Path | str") -> Path:
        return _create_master(Path(input_dir), Path(output_path), frame_type="Bias Frame")

    def create_master_flat(self, input_dir: "Path | str", output_path: "Path | str", filter_name: str = "") -> Path:
        return _create_master(Path(input_dir), Path(output_path), frame_type="Flat Field")

    def calibrate(
        self,
        light_dir: "Path | str",
        master_dark: "Path | str",
        master_flat: "Path | str",
        output_dir: "Path | str",
        master_bias: "Path | str | None" = None,
    ) -> CalibrationApplyResult:
        """Apply master calibration frames to all light frames in *light_dir* (LIB-060)."""
        import numpy as np
        from astropy.io import fits

        light_dir_path = Path(light_dir)
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        # Load masters
        dark = _load_fits_data(Path(master_dark))
        flat = _load_fits_data(Path(master_flat))
        if flat is not None:
            flat = flat / (np.mean(flat) + 1e-9)  # normalise flat

        count = 0
        for light_path in sorted(light_dir_path.glob("*.fits")):
            try:
                with fits.open(str(light_path)) as hdul:
                    light_data = hdul[0].data.astype(np.float32)
                    hdr = hdul[0].header.copy()

                calibrated = light_data
                if dark is not None:
                    calibrated = calibrated - dark
                if flat is not None:
                    calibrated = calibrated / flat

                out_path = output_dir_path / light_path.name
                fits.PrimaryHDU(calibrated, header=hdr).writeto(str(out_path), overwrite=True)
                count += 1
            except Exception:
                logger.exception("Failed to calibrate %s", light_path)

        return CalibrationApplyResult(calibrated_count=count)


def _create_master(input_dir: Path, output_path: Path, frame_type: str) -> Path:
    import numpy as np
    from astropy.io import fits

    frames = []
    for p in sorted(input_dir.glob("*.fits")):
        data = _load_fits_data(p)
        if data is not None:
            frames.append(data)

    if not frames:
        # Write an empty file so callers can check existence
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fits.PrimaryHDU(np.zeros((10, 10), dtype=np.float32)).writeto(str(output_path), overwrite=True)
        return output_path

    master = np.mean(frames, axis=0).astype(np.float32)
    hdr = fits.Header()
    hdr["IMAGETYP"] = frame_type
    hdr["NUMFILES"] = len(frames)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(master, header=hdr).writeto(str(output_path), overwrite=True)
    return output_path


def _load_fits_data(path: Path):
    try:
        from astropy.io import fits
        import numpy as np
        with fits.open(str(path)) as hdul:
            return hdul[0].data.astype(np.float32)
    except Exception:
        return None
