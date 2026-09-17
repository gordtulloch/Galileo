"""Plate-solving service — ASTAP and astrometry.net integration (PLT-010 … PLT-060)."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_OFFLINE_BACKENDS = {"astap", "astrometry_local"}


@dataclass
class SolveResult:
    """Result from one plate-solve attempt."""
    success: bool
    ra_deg: float | None = None
    dec_deg: float | None = None
    rotation_deg: float | None = None
    scale_arcsec_px: float | None = None
    failure_reason: str = ""


@dataclass
class SolverParams:
    """Configurable solver parameters (PLT-060)."""
    fov_hint_deg: float = 0.0
    search_radius_deg: float = 30.0
    downsample: int = 2


class PlateSolver:
    """Drives an external plate-solving engine (PLT-010 … PLT-060).

    Currently supports ASTAP (``backend="astap"``) and a local
    astrometry.net installation (``backend="astrometry_local"``).
    """

    def __init__(
        self,
        backend: str = "astap",
        executable: str = "",
        params: SolverParams | None = None,
    ) -> None:
        self.backend = backend
        self.executable = executable or self._find_executable(backend)
        self.params = params or SolverParams()

    @staticmethod
    def is_offline_capable(backend: str) -> bool:
        """Return True when *backend* does not require internet access (PLT-020)."""
        return backend in _OFFLINE_BACKENDS

    @staticmethod
    def _find_executable(backend: str) -> str:
        import shutil
        names = {"astap": ["astap", "astap.exe"], "astrometry_local": ["solve-field"]}
        for name in names.get(backend, []):
            found = shutil.which(name)
            if found:
                return found
        return ""

    # --- Public API -------------------------------------------------------

    async def solve(self, fits_path: "Path | str") -> SolveResult:
        """Invoke the configured solver on *fits_path* and return a ``SolveResult``."""
        return await self._run_solver(Path(fits_path))

    async def solve_and_sync(self, fits_path: "Path | str", mount) -> SolveResult:
        """Solve *fits_path* and sync the mount's reported position (PLT-030)."""
        result = await self.solve(fits_path)
        if result.success and mount is not None:
            await mount.sync_to_coordinates(ra=result.ra_deg, dec=result.dec_deg)
        return result

    async def solve_and_center(
        self,
        target_ra: float,
        target_dec: float,
        mount,
        camera,
        tolerance_arcsec: float = 30.0,
        max_iterations: int = 5,
    ) -> None:
        """Iteratively slew and re-solve until within *tolerance_arcsec* (PLT-040)."""
        import numpy as np
        tol_deg = tolerance_arcsec / 3600.0

        for _ in range(max_iterations):
            # Capture a frame
            await camera.start_exposure(duration=5.0, frame_type="Light")
            data = await camera.get_image_array()

            # Write temp FITS
            tmp = Path("/tmp/galileo_center.fits")
            _write_temp_fits(data, tmp)

            result = await self.solve(tmp)
            if not result.success:
                break

            dist = math.sqrt(
                (result.ra_deg - target_ra) ** 2 + (result.dec_deg - target_dec) ** 2
            )
            if dist <= tol_deg:
                return

            await mount.slew_to_coordinates(ra=target_ra, dec=target_dec)
            await asyncio.sleep(2)

    # --- Private runner ---------------------------------------------------

    async def _run_solver(self, fits_path: Path) -> SolveResult:
        """Dispatch to the appropriate backend solver."""
        if self.backend == "astap":
            return await self._run_astap(fits_path)
        if self.backend == "astrometry_local":
            return await self._run_astrometry(fits_path)
        return SolveResult(success=False, failure_reason=f"Unknown backend: {self.backend}")

    async def _run_astap(self, fits_path: Path) -> SolveResult:
        if not self.executable or not Path(self.executable).exists():
            return SolveResult(success=False, failure_reason="ASTAP executable not found")

        cmd = [
            self.executable,
            "-f", str(fits_path),
            "-update",
            "-o", str(fits_path.with_suffix("")),
        ]
        if self.params.fov_hint_deg > 0:
            cmd += ["-fov", str(self.params.fov_hint_deg)]
        if self.params.downsample > 1:
            cmd += ["-down", str(self.params.downsample)]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode == 0:
                return _parse_astap_solution(fits_path.with_suffix(".wcs"))
            return SolveResult(
                success=False,
                failure_reason=stderr.decode(errors="replace")[:200],
            )
        except asyncio.TimeoutError:
            return SolveResult(success=False, failure_reason="Solver timed out")
        except Exception as exc:
            return SolveResult(success=False, failure_reason=str(exc))

    async def _run_astrometry(self, fits_path: Path) -> SolveResult:
        if not self.executable:
            return SolveResult(success=False, failure_reason="solve-field not found")
        return SolveResult(success=False, failure_reason="astrometry.net backend not yet fully implemented")


def _parse_astap_solution(wcs_path: Path) -> SolveResult:
    """Parse the ASTAP .wcs output file for RA/Dec/rotation/scale."""
    try:
        from astropy.io import fits
        with fits.open(wcs_path) as hdul:
            hdr = hdul[0].header
            ra = float(hdr.get("CRVAL1", 0))
            dec = float(hdr.get("CRVAL2", 0))
            cd1_1 = float(hdr.get("CD1_1", 0))
            cd1_2 = float(hdr.get("CD1_2", 0))
            scale = abs(cd1_1) * 3600.0
            rotation = math.degrees(math.atan2(cd1_2, cd1_1))
            return SolveResult(
                success=True,
                ra_deg=ra,
                dec_deg=dec,
                rotation_deg=rotation,
                scale_arcsec_px=scale,
            )
    except Exception as exc:
        return SolveResult(success=False, failure_reason=str(exc))


def _write_temp_fits(data, path: Path) -> None:
    try:
        import numpy as np
        from astropy.io import fits
        if data is None:
            data = np.zeros((100, 100), dtype=np.float32)
        fits.PrimaryHDU(data).writeto(path, overwrite=True)
    except Exception:
        pass


import math  # noqa: E402 — used in solve_and_center above
