# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The plate-solver backends (ASTAP, local astrometry.net, nova.astrometry.net, tetra3) behind one PlateSolver."""

from __future__ import annotations

import logging
import asyncio
import json
import math
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from galileo.net import http_request, urlopen_http
from galileo.bus import Event, SolveCompleteEvent, SolveStartedEvent, get_bus

logger = logging.getLogger(__name__)


_OFFLINE_BACKENDS = {"astap", "astrometry_local", "tetra3"}


_NOVA_URL = "https://nova.astrometry.net"


# tetra3 (github.com/esa/tetra3) is a Python library, not a program: it is imported in-process
# and loads a star-pattern database once, which is then reused by every later solve.
_TETRA3_TIMEOUT_S = 120.0


_tetra3_instances: dict[str, object] = {}


_NOVA_TIMEOUT_S = 300.0


_NOVA_POLL_S = 3.0


# Where the installers put ASTAP when it isn't on PATH (the Windows installer never adds it).
_KNOWN_LOCATIONS = {
    "astap": [
        r"C:\Program Files\astap\astap.exe",
        r"C:\Program Files (x86)\astap\astap.exe",
        "/opt/astap/astap",
        "/usr/local/bin/astap",
        "/Applications/ASTAP.app/Contents/MacOS/astap",
    ],
}


# ASTAP's process exit codes (from its command-line documentation), used when it left no ERROR line behind.
_ASTAP_UNREADABLE = 16      # ASTAP could not read the image file it was given


_ASTAP_EXIT_REASONS = {
    1: "No solution found",
    2: "Not enough stars detected",
    16: "Error reading the image file",
    32: "No star database found",
    33: "Error reading the star database",
}


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

    Supports ASTAP (``backend="astap"``), a local astrometry.net installation
    (``backend="astrometry_local"``, its ``solve-field``), the nova.astrometry.net
    web service (``backend="astrometry_web"``, which needs an API key and internet access) and
    ESA's tetra3 (``backend="tetra3"``), a fast offline "lost in space" solver run in-process;
    for it ``executable`` is the path of a tetra3 database (blank for the one it ships with).

    Every solve publishes ``SolveStartedEvent`` and ``SolveCompleteEvent`` on the
    event bus, so a screen showing solves (the Solve screen) sees those started by
    any workflow — a session's centering, variable-star analysis — not only its own.
    """

    def __init__(
        self,
        backend: str = "astap",
        executable: str = "",
        params: SolverParams | None = None,
        event_bus=None,
        pier_key=None,
        api_key: str = "",
    ) -> None:
        self.backend = backend
        self.executable = executable or self._find_executable(backend)
        self.api_key = api_key
        self.web_url = _NOVA_URL
        self.params = params or SolverParams()
        self._bus = event_bus
        # Carried on every published event so a listener subscribed process-wide
        # (the Solve screen) can tell which Pier this solve belongs to — two
        # Piers can each have their own solve running at once.
        self.pier_key = pier_key

    def is_available(self) -> bool:
        """True when the configured backend has what it needs to run: an executable that exists
        (ASTAP, ``solve-field``) or, for nova.astrometry.net, an API key."""
        if self.backend == "astrometry_web":
            return bool(self.api_key)
        if self.backend == "tetra3":
            return tetra3_installed()
        return bool(self.executable)

    def missing_message(self) -> str:
        """What to tell the user when :meth:`is_available` is False."""
        if self.backend == "astrometry_web":
            return "Solving through nova.astrometry.net needs an API key (Options > Solve)."
        if self.backend == "tetra3":
            return ("Solving with tetra3 needs the tetra3 Python package, installed from "
                    "github.com/esa/tetra3 (pip install git+https://github.com/esa/tetra3.git).")
        if self.backend == "astrometry_local":
            return ("Solving needs astrometry.net's solve-field and its index files. Install them, "
                    "or set the path in Options > Solve.")
        return ("Solving needs the ASTAP solver and a star database (both free from hnsky.org/astap.htm). "
                "Install them, then try again.")

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
        for location in _KNOWN_LOCATIONS.get(backend, []):
            if Path(location).exists():
                return location
        return ""

    def _publish(self, event: Event) -> None:
        (self._bus or get_bus()).publish(event)

    # --- Public API -------------------------------------------------------

    async def solve(
        self, fits_path: Path | str, hint: tuple[float, float] | None = None,
    ) -> SolveResult:
        """Invoke the configured solver on *fits_path* and return a ``SolveResult``.

        *hint* is where the telescope is believed to point, ``(ra_deg, dec_deg)`` in J2000.
        The solver then searches only within ``params.search_radius_deg`` of it, which is
        both faster and — on a sparse field — far less likely to return a false match than
        a blind search of the whole sky."""
        path = Path(fits_path)
        self._publish(SolveStartedEvent(
            source="platesolve", fits_path=str(path), backend=self.backend, pier_key=self.pier_key,
        ))
        try:
            result = await self._run_solver(path, hint)
        except asyncio.CancelledError:
            self._publish(SolveCompleteEvent(
                source="platesolve", fits_path=str(path),
                result=SolveResult(success=False, failure_reason="Cancelled"), pier_key=self.pier_key,
            ))
            raise
        self._publish(SolveCompleteEvent(
            source="platesolve", fits_path=str(path), result=result, pier_key=self.pier_key,
        ))
        return result

    async def solve_and_sync(self, fits_path: Path | str, mount) -> SolveResult:
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
    ) -> bool:
        """Iteratively solve, sync and slew until within *tolerance_arcsec* of the target (PLT-040).

        *target_ra*/*target_dec* are in degrees, in the frame the solver reports (J2000) -- which is also
        the frame the mount is synced and slewed in here, so a mount working in JNow should be driven
        through :class:`SolveWorkflow` instead. Each pass syncs the mount to the solution *before*
        slewing, so the slew corrects the pointing error rather than repeating it. Returns True once
        the solution is within tolerance, False if a solve fails or the iterations run out."""
        for _ in range(max_iterations):
            await camera.start_exposure(duration=5.0, frame_type="Light")
            data = await camera.get_image_array()

            with tempfile.TemporaryDirectory(prefix="galileo_center_") as tmpdir:
                tmp = Path(tmpdir) / "galileo_center.fits"
                await asyncio.to_thread(_write_temp_fits, data, tmp)
                result = await self.solve(tmp, hint=(target_ra, target_dec))
            if not result.success or result.ra_deg is None or result.dec_deg is None:
                return False

            d_ra, d_dec = angular_offset_arcsec(result.ra_deg, result.dec_deg, target_ra, target_dec)
            if math.hypot(d_ra, d_dec) <= tolerance_arcsec:
                return True

            await mount.sync_to_coordinates(ra=result.ra_deg, dec=result.dec_deg)
            await mount.slew_to_coordinates(ra=target_ra, dec=target_dec)
            await asyncio.sleep(2)
        return False

    # --- Private runner ---------------------------------------------------

    async def _run_solver(self, fits_path: Path, hint: tuple[float, float] | None = None) -> SolveResult:
        """Dispatch to the appropriate backend solver."""
        if self.backend == "astap":
            return await self._run_astap(fits_path, hint)
        if self.backend == "astrometry_local":
            return await self._run_astrometry(fits_path, hint)
        if self.backend == "astrometry_web":
            return await self._run_nova(fits_path, hint)
        if self.backend == "tetra3":
            return await self._run_tetra3(fits_path)
        return SolveResult(success=False, failure_reason=f"Unknown backend: {self.backend}")

    async def _run_astap(self, fits_path: Path, hint: tuple[float, float] | None = None) -> SolveResult:
        if not self.executable or not await asyncio.to_thread(Path(self.executable).exists):
            return SolveResult(success=False, failure_reason="ASTAP executable not found")

        base = fits_path.with_suffix("")
        # A previous solve of this same frame must not be mistaken for this one's answer.
        def _clear_previous_solve() -> None:
            for suffix in (".ini", ".wcs"):
                base.with_suffix(suffix).unlink(missing_ok=True)

        await asyncio.to_thread(_clear_previous_solve)

        cmd = [self.executable, "-f", str(fits_path), "-update", "-o", str(base)]
        if self.params.fov_hint_deg > 0:
            cmd += ["-fov", f"{self.params.fov_hint_deg:g}"]
        if self.params.downsample > 1:
            cmd += ["-z", str(self.params.downsample)]
        if hint is not None:
            ra_deg, dec_deg = hint
            # ASTAP takes RA in hours and Dec as the south-pole distance.
            cmd += ["-ra", f"{ra_deg / 15.0:.6f}", "-spd", f"{dec_deg + 90.0:.6f}",
                    "-r", f"{self.params.search_radius_deg:g}"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            return SolveResult(success=False, failure_reason=str(exc))
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return SolveResult(success=False, failure_reason="Solver timed out")
        except asyncio.CancelledError:
            proc.kill()      # a stopped solve must not leave ASTAP running in the background
            raise
        except Exception as exc:
            return SolveResult(success=False, failure_reason=str(exc))

        # ASTAP reports both outcomes in its .ini file. On failure it exits non-zero with
        # nothing on stderr, so the reason is only there (or in its exit code).
        ini = _read_astap_ini(base.with_suffix(".ini"))
        if ini.get("PLTSOLVD") == "T":
            return _result_from_astap_ini(ini)
        reason = (
            ini.get("ERROR")
            or _ASTAP_EXIT_REASONS.get(proc.returncode or 0)
            or stderr.decode(errors="replace").strip()[:200]
            or f"ASTAP exited with code {proc.returncode}"
        )
        if proc.returncode == _ASTAP_UNREADABLE:
            # The solver never got as far as looking for stars, so what it was handed is the whole
            # story — without this the user has nothing to go on but "error reading the image file".
            reason = f"{reason} — it was given {_describe_fits(fits_path)}"
        logger.info("ASTAP failed (%s): %s", reason, " ".join(cmd))
        return SolveResult(success=False, failure_reason=reason)

    async def _run_astrometry(self, fits_path: Path, hint: tuple[float, float] | None = None) -> SolveResult:
        """Solve with a local astrometry.net ``solve-field``. It writes a WCS file on success; its
        many other outputs go to a scratch folder that is removed afterwards."""
        if not self.executable or not await asyncio.to_thread(Path(self.executable).exists):
            return SolveResult(success=False, failure_reason="solve-field not found")
        with tempfile.TemporaryDirectory(prefix="galileo_astrometry_") as outdir:
            cmd = [self.executable, "--overwrite", "--no-plots", "--new-fits", "none",
                   "--crpix-center", "--cpulimit", "120", "--dir", outdir, "--out", "solved"]
            fov = self.params.fov_hint_deg
            if fov > 0:
                cmd += ["--scale-units", "degwidth", "--scale-low", f"{fov * 0.8:g}", "--scale-high", f"{fov * 1.25:g}"]
            if self.params.downsample > 1:
                cmd += ["--downsample", str(self.params.downsample)]
            if hint is not None:
                cmd += ["--ra", f"{hint[0]:.6f}", "--dec", f"{hint[1]:.6f}", "--radius", f"{self.params.search_radius_deg:g}"]
            cmd.append(str(fits_path))
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            except Exception as exc:
                return SolveResult(success=False, failure_reason=str(exc))
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return SolveResult(success=False, failure_reason="Solver timed out")
            except asyncio.CancelledError:
                proc.kill()
                raise
            except Exception as exc:
                return SolveResult(success=False, failure_reason=str(exc))
            wcs = Path(outdir) / "solved.wcs"
            if wcs.exists():
                return await asyncio.to_thread(_result_from_wcs, wcs)
            reason = (stderr.decode(errors="replace").strip()[-200:]
                      or ("No solution found" if proc.returncode == 0 else f"solve-field exited with code {proc.returncode}"))
            logger.info("solve-field failed (%s): %s", reason, " ".join(cmd))
            return SolveResult(success=False, failure_reason=reason)

    async def _run_tetra3(self, fits_path: Path) -> SolveResult:
        """Solve with tetra3. It matches patterns of the brightest stars against its own database, so
        the position hint is not used — it is the field-of-view hint that narrows the search. The
        library cannot be interrupted, so a stopped solve is abandoned rather than killed."""
        if not tetra3_installed():
            return SolveResult(success=False, failure_reason="The tetra3 package is not installed")
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._tetra3_solve, fits_path), timeout=_TETRA3_TIMEOUT_S + 30)
        except TimeoutError:
            return SolveResult(success=False, failure_reason="Solver timed out")
        except Exception as exc:
            logger.info("tetra3 failed: %s", exc, exc_info=True)
            return SolveResult(success=False, failure_reason=f"tetra3: {exc}")

    def _tetra3_solve(self, fits_path: Path) -> SolveResult:
        import numpy as np
        import tetra3
        from astropy.io import fits

        patch_numpy_for_tetra3()

        database = self.executable
        solver = _tetra3_instances.get(database)
        if solver is None:
            solver = tetra3.Tetra3(load_database=database or "default_database")
            _tetra3_instances[database] = solver
        with fits.open(fits_path, memmap=False) as hdul:
            hdu = _image_hdu(hdul)
            if hdu is None:
                return SolveResult(success=False, failure_reason="The file holds no image")
            image = np.asarray(hdu.data, dtype=np.float32)
        if image.ndim > 2:
            image = image.mean(axis=int(np.argmin(image.shape)))
        height, width = image.shape
        centroids = tetra3.get_centroids_from_image(image)
        if len(centroids) < 4:
            return SolveResult(success=False, failure_reason="Not enough stars detected")
        # The field-of-view hint is the image's height (ASTAP's convention); tetra3 wants its width.
        fov = self.params.fov_hint_deg * width / height
        solution = solver.solve_from_centroids(
            centroids, size=(height, width),
            fov_estimate=fov if fov > 0 else None, fov_max_error=fov * 0.3 if fov > 0 else None,
            solve_timeout=_TETRA3_TIMEOUT_S * 1000.0)
        if not solution or solution.get("RA") is None:
            return SolveResult(success=False, failure_reason="No solution found")
        return SolveResult(
            success=True, ra_deg=float(solution["RA"]), dec_deg=float(solution["Dec"]),
            rotation_deg=float(solution["Roll"]) if solution.get("Roll") is not None else None,
            scale_arcsec_px=float(solution["FOV"]) * 3600.0 / width)

    async def _run_nova(self, fits_path: Path, hint: tuple[float, float] | None = None) -> SolveResult:
        """Solve through the nova.astrometry.net web API (upload, then poll the job)."""
        if not self.api_key:
            return SolveResult(success=False, failure_reason="No nova.astrometry.net API key is configured")
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._nova_solve, fits_path, hint), timeout=_NOVA_TIMEOUT_S + 30)
        except TimeoutError:
            return SolveResult(success=False, failure_reason="nova.astrometry.net timed out")
        except Exception as exc:
            return SolveResult(success=False, failure_reason=f"nova.astrometry.net: {exc}")

    def _nova_solve(self, fits_path: Path, hint: tuple[float, float] | None) -> SolveResult:
        session = self._nova_request("login", {"apikey": self.api_key}).get("session")
        if not session:
            return SolveResult(success=False, failure_reason="nova.astrometry.net rejected the API key")
        options: dict = {"session": session, "publicly_visible": "n", "allow_commercial_use": "n",
                         "allow_modifications": "n"}
        fov = self.params.fov_hint_deg
        if fov > 0:
            options.update(scale_units="degwidth", scale_type="ul", scale_lower=fov * 0.8, scale_upper=fov * 1.25)
        if self.params.downsample > 1:
            options["downsample_factor"] = self.params.downsample
        if hint is not None:
            options.update(center_ra=hint[0], center_dec=hint[1], radius=self.params.search_radius_deg)
        upload = self._nova_request("upload", options, file=fits_path)
        if upload.get("status") != "success":
            return SolveResult(success=False, failure_reason=f"Upload failed: {upload.get('errormessage', upload)}")
        sub_id = upload["subid"]
        deadline = time.monotonic() + _NOVA_TIMEOUT_S
        job_id = None
        while time.monotonic() < deadline:
            if job_id is None:
                jobs = [j for j in self._nova_request(f"submissions/{sub_id}").get("jobs", []) if j]
                job_id = jobs[0] if jobs else None
            if job_id is not None:
                status = self._nova_request(f"jobs/{job_id}").get("status")
                if status == "success":
                    cal = self._nova_request(f"jobs/{job_id}/calibration")
                    return SolveResult(success=True, ra_deg=float(cal["ra"]), dec_deg=float(cal["dec"]),
                                       rotation_deg=float(cal.get("orientation", 0.0)),
                                       scale_arcsec_px=float(cal["pixscale"]))
                if status == "failure":
                    return SolveResult(success=False, failure_reason="No solution found")
            time.sleep(_NOVA_POLL_S)
        return SolveResult(success=False, failure_reason="nova.astrometry.net timed out")

    def _nova_request(self, path: str, fields: dict | None = None, file: Path | None = None) -> dict:
        """One call to the nova.astrometry.net JSON API (blocking; runs on a worker thread)."""
        import urllib.parse
        import urllib.request
        url = f"{self.web_url.rstrip('/')}/api/{path}"
        if fields is None and file is None:
            with urlopen_http(url, timeout=30) as response:
                return json.loads(response.read())
        body_json = json.dumps(fields or {})
        if file is None:
            data = urllib.parse.urlencode({"request-json": body_json}).encode()
            request = http_request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        else:
            boundary = "galileo" + str(time.time_ns())
            head = (f'--{boundary}\r\nContent-Disposition: form-data; name="request-json"\r\n'
                    f'Content-Type: text/plain\r\n\r\n{body_json}\r\n'
                    f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file.name}"\r\n'
                    f'Content-Type: application/octet-stream\r\n\r\n').encode()
            data = head + file.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
            request = http_request(
                url, data=data, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urlopen_http(request, timeout=60) as response:
            return json.loads(response.read())


def patch_numpy_for_tetra3() -> None:
    """tetra3 still calls ``np.math.factorial``, which NumPy 2 removed; put it back."""
    import numpy as np
    if not hasattr(np, "math"):
        np.math = math


def tetra3_installed() -> bool:
    """True when the ``tetra3`` package can be imported (it is optional and not on PyPI)."""
    import importlib.util
    import sys
    if "tetra3" in sys.modules:
        return True
    try:
        return importlib.util.find_spec("tetra3") is not None
    except (ImportError, ValueError):
        return False


def _result_from_wcs(path: Path) -> SolveResult:
    """Build a ``SolveResult`` from a WCS FITS file written by astrometry.net (referenced to the image centre)."""
    try:
        from astropy.io import fits
        header = fits.getheader(path)
        ra, dec = float(header["CRVAL1"]), float(header["CRVAL2"])
        if "CD1_1" in header:
            cd11, cd12, cd21, cd22 = (float(header[k]) for k in ("CD1_1", "CD1_2", "CD2_1", "CD2_2"))
        else:
            cd11, cd12, cd21, cd22 = float(header["CDELT1"]), 0.0, 0.0, float(header["CDELT2"])
        return SolveResult(success=True, ra_deg=ra, dec_deg=dec,
                           rotation_deg=math.degrees(math.atan2(cd12, cd22)),
                           scale_arcsec_px=math.hypot(cd11, cd21) * 3600.0)
    except Exception as exc:
        return SolveResult(success=False, failure_reason=f"Could not read astrometry.net's solution: {exc}")


def _read_astap_ini(path: Path) -> dict[str, str]:
    """ASTAP's ``<name>.ini`` result file: one ``KEY=value`` per line."""
    values: dict[str, str] = {}
    try:
        for line in path.read_text(errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep:
                values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def _result_from_astap_ini(ini: dict[str, str]) -> SolveResult:
    """Build a ``SolveResult`` from a successful ASTAP ``.ini``: the WCS of the frame,
    which ASTAP references to the image centre (CRVAL1/2, J2000)."""
    try:
        ra, dec = float(ini["CRVAL1"]), float(ini["CRVAL2"])
        if all(k in ini for k in ("CD1_1", "CD1_2", "CD2_1", "CD2_2")):
            cd11, cd12, cd21, cd22 = (float(ini[k]) for k in ("CD1_1", "CD1_2", "CD2_1", "CD2_2"))
            scale = math.hypot(cd11, cd21) * 3600.0         # the x-axis pixel size, whatever the rotation
            rotation = math.degrees(math.atan2(cd12, cd22))  # 0 = north up (east left); flips keep this convention
        else:
            scale = abs(float(ini["CDELT1"])) * 3600.0
            rotation = float(ini.get("CROTA2", 0.0))
        return SolveResult(success=True, ra_deg=ra, dec_deg=dec, rotation_deg=rotation, scale_arcsec_px=scale)
    except (KeyError, ValueError) as exc:
        return SolveResult(success=False, failure_reason=f"Could not read ASTAP's solution: {exc}")


def _write_temp_fits(data, path: Path) -> None:
    try:
        import numpy as np
        from astropy.io import fits
        if data is None:
            data = np.zeros((100, 100), dtype=np.float32)
        fits.PrimaryHDU(data).writeto(path, overwrite=True)
    except Exception:
        logger.warning("Could not write temporary FITS file %s", path, exc_info=True)


def angular_offset_arcsec(ra_deg: float, dec_deg: float, ref_ra_deg: float, ref_dec_deg: float) -> tuple[float, float]:
    """``(dRA, dDec)`` in arcseconds of a position relative to a reference: east and north
    positive. dRA is the on-sky distance (RA difference × cos Dec), not the raw RA difference."""
    d_ra = (ra_deg - ref_ra_deg + 180.0) % 360.0 - 180.0
    mean_dec = math.radians((dec_deg + ref_dec_deg) / 2.0)
    return d_ra * math.cos(mean_dec) * 3600.0, (dec_deg - ref_dec_deg) * 3600.0


def _image_hdu(hdul):
    """The first HDU in *hdul* holding a 2-D-or-larger image. A tile-compressed FITS keeps its
    image in a later HDU, so the primary one is not always the picture."""
    for hdu in hdul:
        data = getattr(hdu, "data", None)
        if data is not None and getattr(data, "ndim", 0) >= 2:
            return hdu
    return None


def _describe_fits(path: Path) -> str:
    """What a FITS file actually holds, for a message about a solver refusing it."""
    try:
        size_mb = path.stat().st_size / 1e6
    except OSError:
        return f"{path.name}, which is missing"
    try:
        from astropy.io import fits
        with fits.open(path, memmap=False) as hdul:
            hdu = _image_hdu(hdul)
            if hdu is None:
                return f"{path.name} ({size_mb:.1f} MB), which holds no image"
            shape = "x".join(str(n) for n in reversed(hdu.data.shape))
            return f"{path.name}: {shape}, BITPIX {hdu.header.get('BITPIX')}, {size_mb:.1f} MB"
    except Exception as exc:
        return f"{path.name} ({size_mb:.1f} MB), which could not be read here either: {exc}"
