# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Plate-solving service — ASTAP and astrometry.net integration (PLT-010 … PLT-060)
and the capture-solve-correct workflow behind the Solve screen (PLT-070)."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import math
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from galileo.bus import Event, SolveCompleteEvent, SolveStartedEvent, get_bus

logger = logging.getLogger(__name__)

_OFFLINE_BACKENDS = {"astap", "astrometry_local"}

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

    Currently supports ASTAP (``backend="astap"``) and a local
    astrometry.net installation (``backend="astrometry_local"``).

    Every solve publishes ``SolveStartedEvent`` and ``SolveCompleteEvent`` on the
    event bus, so a screen showing solves (the Solve screen) sees those started by
    any workflow — the sequencer's centering, variable-star analysis — not only its own.
    """

    def __init__(
        self,
        backend: str = "astap",
        executable: str = "",
        params: SolverParams | None = None,
        event_bus=None,
    ) -> None:
        self.backend = backend
        self.executable = executable or self._find_executable(backend)
        self.params = params or SolverParams()
        self._bus = event_bus

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
        self._publish(SolveStartedEvent(source="platesolve", fits_path=str(path), backend=self.backend))
        try:
            result = await self._run_solver(path, hint)
        except asyncio.CancelledError:
            self._publish(SolveCompleteEvent(
                source="platesolve", fits_path=str(path),
                result=SolveResult(success=False, failure_reason="Cancelled"),
            ))
            raise
        self._publish(SolveCompleteEvent(source="platesolve", fits_path=str(path), result=result))
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
    ) -> None:
        """Iteratively slew and re-solve until within *tolerance_arcsec* (PLT-040)."""
        tol_deg = tolerance_arcsec / 3600.0

        for _ in range(max_iterations):
            # Capture a frame
            await camera.start_exposure(duration=5.0, frame_type="Light")
            data = await camera.get_image_array()

            # Write temp FITS
            tmp = Path(tempfile.gettempdir()) / "galileo_center.fits"
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

    async def _run_solver(self, fits_path: Path, hint: tuple[float, float] | None = None) -> SolveResult:
        """Dispatch to the appropriate backend solver."""
        if self.backend == "astap":
            return await self._run_astap(fits_path, hint)
        if self.backend == "astrometry_local":
            return await self._run_astrometry(fits_path)
        return SolveResult(success=False, failure_reason=f"Unknown backend: {self.backend}")

    async def _run_astap(self, fits_path: Path, hint: tuple[float, float] | None = None) -> SolveResult:
        if not self.executable or not Path(self.executable).exists():
            return SolveResult(success=False, failure_reason="ASTAP executable not found")

        base = fits_path.with_suffix("")
        # A previous solve of this same frame must not be mistaken for this one's answer.
        for suffix in (".ini", ".wcs"):
            base.with_suffix(suffix).unlink(missing_ok=True)

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

    async def _run_astrometry(self, fits_path: Path) -> SolveResult:
        if not self.executable:
            return SolveResult(success=False, failure_reason="solve-field not found")
        return SolveResult(success=False, failure_reason="astrometry.net backend not yet fully implemented")


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
        pass


# ---------------------------------------------------------------------------
# Coordinates (PLT-070)
# ---------------------------------------------------------------------------

def _equinox_jd(when: dt.datetime | None) -> float:
    from galileo.planning.star_atlas import julian_date
    return julian_date(when or dt.datetime.now(dt.UTC))


def j2000_to_mount_frame(
    ra_deg: float, dec_deg: float, system: str | None, when: dt.datetime | None = None,
) -> tuple[float, float]:
    """Express J2000 coordinates in the frame a mount takes: J2000 as-is for a mount that
    reports ``"J2000"``, otherwise coordinates of date (JNow), as every other mount uses."""
    if (system or "").upper() == "J2000":
        return ra_deg, dec_deg
    from galileo.planning.star_atlas import precess_from_j2000
    ra, dec = precess_from_j2000(ra_deg, dec_deg, _equinox_jd(when))
    return float(ra), float(dec)


def mount_frame_to_j2000(
    ra_deg: float, dec_deg: float, system: str | None, when: dt.datetime | None = None,
) -> tuple[float, float]:
    """Inverse of :func:`j2000_to_mount_frame`."""
    if (system or "").upper() == "J2000":
        return ra_deg, dec_deg
    from galileo.planning.star_atlas import precess_to_j2000
    ra, dec = precess_to_j2000(ra_deg, dec_deg, _equinox_jd(when))
    return float(ra), float(dec)


def angular_offset_arcsec(ra_deg: float, dec_deg: float, ref_ra_deg: float, ref_dec_deg: float) -> tuple[float, float]:
    """``(dRA, dDec)`` in arcseconds of a position relative to a reference: east and north
    positive. dRA is the on-sky distance (RA difference × cos Dec), not the raw RA difference."""
    d_ra = (ra_deg - ref_ra_deg + 180.0) % 360.0 - 180.0
    mean_dec = math.radians((dec_deg + ref_dec_deg) / 2.0)
    return d_ra * math.cos(mean_dec) * 3600.0, (dec_deg - ref_dec_deg) * 3600.0


def nearest_object_name(ra_deg: float, dec_deg: float, max_separation_deg: float = 1.0) -> str:
    """Name of the catalogued star nearest a J2000 position, or ``""`` if none is within
    *max_separation_deg* (or the catalogue is unavailable)."""
    try:
        import numpy as np

        from galileo.planning.star_atlas import load_star_catalog
        cat = load_star_catalog()
        d_ra = (cat.ra - ra_deg + 180.0) % 360.0 - 180.0
        sep = np.hypot(d_ra * math.cos(math.radians(dec_deg)), cat.dec - dec_deg)
        i = int(np.argmin(sep))
        return cat.label(i) if sep[i] <= max_separation_deg else ""
    except Exception:
        logger.exception("Could not look up the object near RA %.3f Dec %.3f", ra_deg, dec_deg)
        return ""


# ---------------------------------------------------------------------------
# Capture-solve-correct workflow (PLT-070)
# ---------------------------------------------------------------------------

class SolveAction(str, Enum):
    """What to do with the mount once a frame is solved."""
    SYNC = "sync"                      # tell the mount where it is really pointing
    SLEW_TO_TARGET = "slew"            # sync, then slew back to the target; repeat until close enough
    NOTHING = "nothing"


@dataclass
class SolveSettings:
    """One Capture & Solve run's settings."""
    exposure_s: float = 5.0
    action: SolveAction = SolveAction.NOTHING
    accuracy_arcsec: float = 30.0     # Slew to Target repeats until the solution is this close to the target
    settle_s: float = 1.5             # pause after a slew before the next frame
    max_iterations: int = 5
    scale_hint_arcsec_px: float | None = None   # from the optical train; narrows the solver's field-of-view search


class SolveWorkflow:
    """Capture a frame, solve it, and act on the result (PLT-030, PLT-040, PLT-070).

    Domain-core: it drives a camera, a mount and a ``PlateSolver`` through their ports and
    reports progress through the *log* callback (called on the thread the workflow runs
    on — the caller marshals it onto its own). ``stop()`` is safe to call from any thread.
    """

    _SLEW_TIMEOUT_S = 180.0
    _KEEP_FILES = 12

    def __init__(
        self,
        solver: PlateSolver,
        camera=None,
        mount=None,
        work_dir: Path | str | None = None,
        log: Callable[[str], None] | None = None,
        frame_metadata: dict | None = None,
    ) -> None:
        self.solver = solver
        self.camera = camera
        self.mount = mount
        # Header values for the frames this workflow captures, so the solver knows the image scale
        # and whether the sensor is one-shot-colour. Keyed as galileo.metadata expects.
        self.frame_metadata: dict = dict(frame_metadata or {})
        self._work_dir = Path(work_dir) if work_dir is not None else None
        self._log = log or (lambda message: None)
        # J2000 (ra_deg, dec_deg) the mount should end up at; taken from the mount when a run
        # starts if not already set.
        self.target: tuple[float, float] | None = None
        self.object_name = ""              # what the target is called; goes into the solve frames' file names
        self._target_preset = False        # the caller chose the target, so the mount isn't already "there"
        self.results: list[SolveResult] = []
        self.stopped = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None

    # --- Control ----------------------------------------------------------

    def set_target(self, ra_deg: float, dec_deg: float, name: str = "") -> None:
        """Aim the run at a chosen J2000 position (an object picked in the Star Atlas) rather than
        wherever the mount happens to be pointing when it starts. Slew to Target then slews there
        first, and corrects until the solution is within the accuracy of it."""
        self.target = (ra_deg, dec_deg)
        self.object_name = name
        self._target_preset = True

    def stop(self) -> None:
        """Cancel the run in progress. Thread-safe; a no-op when nothing is running."""
        loop, task = self._loop, self._task
        if loop is not None and task is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)

    def _work_path(self, stem: str) -> Path:
        if self._work_dir is None:
            from galileo.platform import get_cache_dir
            self._work_dir = get_cache_dir() / "solve"
        self._work_dir.mkdir(parents=True, exist_ok=True)
        return self._work_dir / f"{stem}.fits"

    def _frame_stem(self, suffix: str) -> str:
        """``solve_<object>_<timestamp>_<suffix>`` — the ``solve_`` prefix is what pruning looks for."""
        from galileo.current_object import safe_file_stem
        name = safe_file_stem(self.object_name)
        return f"solve_{name + '_' if name else ''}{dt.datetime.now():%Y%m%d_%H%M%S_%f}_{suffix}"

    def _prune_work_dir(self) -> None:
        """Frames are only kept so the screen can show them; drop all but the newest few."""
        if self._work_dir is None:
            return
        frames = sorted(self._work_dir.glob("solve_*.fits"), key=lambda p: p.stat().st_mtime)
        for old in frames[:-self._KEEP_FILES]:
            for suffix in (".fits", ".ini", ".wcs"):
                old.with_suffix(suffix).unlink(missing_ok=True)

    # --- Mount helpers ----------------------------------------------------

    async def _mount_position(self) -> tuple[float, float, str | None] | None:
        """The mount's pointing as ``(ra_deg, dec_deg, equatorial_system)``, or ``None``."""
        if self.mount is None:
            return None
        try:
            status = await self.mount.get_status() or {}
        except Exception as exc:
            self._log(f"Could not read the mount's position: {exc}")
            return None
        ra_h, dec = status.get("right_ascension"), status.get("declination")
        if ra_h is None or dec is None:
            return None
        return ra_h * 15.0, dec, status.get("equatorial_system")

    async def _wait_for_slew(self) -> None:
        deadline = time.monotonic() + self._SLEW_TIMEOUT_S
        await asyncio.sleep(0.5)
        while time.monotonic() < deadline:
            status = await self.mount.get_status() or {}
            if not status.get("slewing"):
                return
            await asyncio.sleep(0.5)
        self._log("The mount is still slewing after 3 minutes; carrying on.")

    async def _abort_hardware(self) -> None:
        for device, method in ((self.camera, "abort_exposure"), (self.mount, "abort_slew")):
            if device is None:
                continue
            try:
                await getattr(device, method)()
            except Exception:
                logger.debug("%s failed while stopping a solve", method, exc_info=True)

    # --- Runs -------------------------------------------------------------

    async def capture_and_solve(self, settings: SolveSettings) -> list[SolveResult]:
        """Capture, solve and (per ``settings.action``) sync or slew, repeating for Slew to
        Target until the solution is within ``settings.accuracy_arcsec`` of the target or
        ``settings.max_iterations`` frames have been taken. Returns the results in order."""
        return await self._run(self._capture_and_solve(settings))

    async def solve_file(self, fits_path: Path | str, slew: bool = True) -> list[SolveResult]:
        """Solve an existing FITS file — on a copy, since ASTAP writes the solution into the
        file it is given — and, if *slew*, slew the mount to the solved coordinates."""
        return await self._run(self._solve_file(Path(fits_path), slew))

    async def _run(self, coro) -> list[SolveResult]:
        self.results, self.stopped = [], False
        self._loop, self._task = asyncio.get_running_loop(), asyncio.current_task()
        try:
            await coro
        except asyncio.CancelledError:
            self.stopped = True
            await self._abort_hardware()
            self._log("Stopped.")
        except Exception as exc:
            logger.exception("Plate-solve workflow failed")
            self._log(f"Failed: {exc}")
        finally:
            self._task = None
        return self.results

    async def _capture_and_solve(self, settings: SolveSettings) -> None:
        action = settings.action
        position = await self._mount_position()
        if action is not SolveAction.NOTHING and self.mount is None:
            self._log("No mount is connected — solving only.")
            action = SolveAction.NOTHING
        hint = system = None
        if position is not None:
            ra, dec, system = position
            hint = mount_frame_to_j2000(ra, dec, system)
            if self.target is None:
                self.target = hint
                self._log(f"Setting target to RA:{_hms(hint[0])} DEC:{_dms(hint[1])}")
        if action is SolveAction.SLEW_TO_TARGET and self.target is None:
            self._log("The mount's position is unknown, so there is no target to slew back to — solving only.")
            action = SolveAction.NOTHING
        iterations = settings.max_iterations if action is SolveAction.SLEW_TO_TARGET else 1

        if action is SolveAction.SLEW_TO_TARGET and self._target_preset and self.target is not None and hint is not None:
            # Go to the chosen object first, so the first frame is taken there rather than wherever
            # the mount was; the loop below then corrects any remaining error.
            d_ra, d_dec = angular_offset_arcsec(*hint, *self.target)
            if math.hypot(d_ra, d_dec) > settings.accuracy_arcsec:
                name = f" ({self.object_name})" if self.object_name else ""
                self._log(f"Slewing to the target{name} before solving.")
                await self._slew(self.target, system)
                await asyncio.sleep(settings.settle_s)
                position = await self._mount_position()
                if position is not None:
                    hint = mount_frame_to_j2000(position[0], position[1], system)

        for attempt in range(iterations):
            frame = await self._capture(settings, attempt)
            if frame is None:
                return
            result = await self._solve(frame, hint, settings)
            if not result.success or result.ra_deg is None or result.dec_deg is None:
                return
            if action is SolveAction.NOTHING:
                return
            solved = (result.ra_deg, result.dec_deg)
            hint = solved                              # the next frame is known to be near here
            if action is SolveAction.SYNC:
                await self._sync(solved, system)
                return
            target = self.target
            if target is None:                         # ruled out above; keeps a later edit honest
                return
            d_ra, d_dec = angular_offset_arcsec(*solved, *target)
            error = math.hypot(d_ra, d_dec)
            if error <= settings.accuracy_arcsec:
                self._log(f"On target: {error:.1f}″ from it, within the {settings.accuracy_arcsec:g}″ accuracy.")
                return
            if attempt == iterations - 1:
                self._log(f"Still {error:.1f}″ from the target after {iterations} attempts; giving up.")
                return
            self._log(f"{error:.1f}″ from the target — syncing to the solution, then slewing back to the target.")
            await self._sync(solved, system)
            await self._slew(target, system)
            await asyncio.sleep(settings.settle_s)
            position = await self._mount_position()
            if position is not None:
                hint = mount_frame_to_j2000(position[0], position[1], system)

    async def _solve_file(self, source: Path, slew: bool) -> None:
        self._log(f"Loading {source.name}…")
        frame = self._work_path(self._frame_stem("loaded"))
        try:
            # Re-written rather than copied: the file may be tile-compressed, hold its image in a
            # later HDU, be three-plane colour or carry 64-bit pixels, none of which a solver reads.
            # Solving a copy is still the point — ASTAP writes its solution into the file it is given.
            await asyncio.to_thread(_normalise_fits, source, frame)
        except Exception as exc:
            self._log(f"Could not read {source.name}: {exc}")
            return
        result = await self._solve(frame, None, SolveSettings())
        if not (result.success and slew) or result.ra_deg is None or result.dec_deg is None:
            return
        if self.mount is None:
            self._log("No mount is connected — not slewing.")
            return
        position = await self._mount_position()
        await self._slew((result.ra_deg, result.dec_deg), position[2] if position else None)

    async def _capture(self, settings: SolveSettings, attempt: int) -> Path | None:
        if self.camera is None:
            self._log("No camera is connected.")
            return None
        self._log("Capturing image…")
        try:
            await self.camera.start_exposure(duration=settings.exposure_s, frame_type="Light")
            data = await self.camera.get_image_array()
            if data is None:
                raise RuntimeError("the camera returned no image")
            frame = self._work_path(self._frame_stem(str(attempt)))
            await asyncio.to_thread(_write_frame, data, frame, self.frame_metadata)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Capture for solving failed")
            self._log(f"Capture failed: {exc}")
            return None
        self._log("Image received.")
        self._prune_work_dir()
        return frame

    async def _solve(self, frame: Path, hint, settings: SolveSettings) -> SolveResult:
        params = self.solver.params
        scale_hint = settings.scale_hint_arcsec_px
        if scale_hint and params.fov_hint_deg <= 0:
            height = await asyncio.to_thread(_image_height_px, frame)
            fov = height * scale_hint / 3600.0 if height else 0.0
        else:
            fov = 0.0
        started = time.monotonic()
        saved = params.fov_hint_deg
        if fov > 0:
            params.fov_hint_deg = fov
        try:
            result = await self.solver.solve(frame, hint=hint)
        finally:
            params.fov_hint_deg = saved
        elapsed = time.monotonic() - started
        self.results.append(result)
        if result.success and result.ra_deg is not None and result.dec_deg is not None:
            self._log(f"Solver completed in {elapsed:.2f} seconds.")
            self._log(f"Solution: RA:{_hms(result.ra_deg)} DEC:{_dms(result.dec_deg)} (J2000)")
        else:
            self._log(f"Solver failed after {elapsed:.2f} seconds: {result.failure_reason}")
        return result

    async def _sync(self, coords: tuple[float, float], system: str | None) -> None:
        ra, dec = j2000_to_mount_frame(*coords, system)
        await self.mount.sync_to_coordinates(ra, dec)
        self._log("Mount synced to the solution.")

    async def _slew(self, coords: tuple[float, float], system: str | None) -> None:
        ra, dec = j2000_to_mount_frame(*coords, system)
        self._log(f"Slewing to RA:{_hms(coords[0])} DEC:{_dms(coords[1])}…")
        await self.mount.slew_to_coordinates(ra, dec)
        await self._wait_for_slew()
        await self._resume_tracking()

    async def _resume_tracking(self) -> None:
        """Track the target at its own rate now the mount has arrived (EQP-MNT-050). A failure
        here is logged and no more: the solve itself succeeded, and saying otherwise would be
        misleading."""
        from galileo.tracking import set_tracking_rate
        try:
            rate = await set_tracking_rate(self.mount, self.object_name)
        except Exception as exc:
            self._log(f"Could not start tracking after the slew: {exc}")
            return
        self._log(f"Tracking at the {rate} rate.")


def frame_for_solver(data):
    """A camera frame as a single-plane image in a pixel format every solver reads.

    Two conversions, both of which a solver will otherwise refuse the file over:

    * **One plane.** A colour frame arrives with three (Alpaca hands back ``(height, width, 3)``),
      and colour carries no astrometric information, so the planes are averaged into one. This also
      avoids writing a three-dimensional FITS, which solvers handle inconsistently at best.
    * **A type that fits.** Handled by :func:`galileo.metadata.normalise_pixels`, which every
      frame Galileo writes goes through: a 64-bit image is legal FITS but ASTAP reads it as a
      broken file.
    """
    import numpy as np
    from galileo.metadata import normalise_pixels
    array = np.asarray(data)
    if array.ndim > 2:
        # RGB or RGBA, at whichever end the source puts it: Alpaca hands back (height, width, 3),
        # while a FITS cube is plane-first. Anything else falls back to the shortest axis.
        if array.shape[-1] in (3, 4):
            colour_axis = array.ndim - 1
        elif array.shape[0] in (3, 4):
            colour_axis = 0
        else:
            colour_axis = min(range(array.ndim), key=lambda axis: array.shape[axis])
        array = array.mean(axis=colour_axis)
    return normalise_pixels(array)


def _write_frame(data, path: Path, metadata: dict | None = None) -> None:
    """Write a camera frame as FITS for the solver, in a form it can read (:func:`frame_for_solver`).

    *metadata* carries what the solver can use to work out the scale for itself — the pixel size
    (``XPIXSZ``/``YPIXSZ``), the focal length (``FOCALLEN``) and, for a one-shot-colour sensor, the
    mosaic layout (``BAYERPAT``). Without them a solver has to search a wide range of image scales,
    which is a common reason a perfectly good frame fails to solve.

    Built via :func:`galileo.metadata.build_primary_hdu`, which places the header cards *after* the
    block astropy writes for the pixel data (not merged in before it) — ASTAP refuses a file with
    the ``BSCALE``/``BZERO`` unsigned-integer cards pushed to the end behind custom keywords, which
    is what merging a header in at construction produces; see that function for the detail."""
    from galileo.metadata import build_primary_hdu
    build_primary_hdu(frame_for_solver(data), metadata or {}).writeto(path, overwrite=True)


def _image_hdu(hdul):
    """The first HDU in *hdul* holding a 2-D-or-larger image. A tile-compressed FITS keeps its
    image in a later HDU, so the primary one is not always the picture."""
    for hdu in hdul:
        data = getattr(hdu, "data", None)
        if data is not None and getattr(data, "ndim", 0) >= 2:
            return hdu
    return None


def _normalise_fits(source: Path, destination: Path) -> None:
    """Read the image out of *source* — whatever HDU, compression, plane count or bit depth it
    uses — and write it to *destination* in the form a solver can read.

    The source's own header is kept, minus the structural keywords that describe the old layout,
    so anything the solver can use (focal length, pixel size, a previous solution's WCS) survives.

    Built from the data alone first, then extended with what is kept of the source header — not by
    merging that header in at construction — for the same reason :func:`galileo.metadata.build_primary_hdu`
    is: astropy would otherwise place the new pixel data's ``BSCALE``/``BZERO`` cards after the kept
    header instead of directly after ``NAXIS2``, which ASTAP's parser refuses to read.
    """
    from astropy.io import fits
    with fits.open(source, memmap=False) as hdul:
        hdu = _image_hdu(hdul)
        if hdu is None:
            raise ValueError("it holds no image")
        data, header = hdu.data, hdu.header.copy()
    for keyword in ("SIMPLE", "XTENSION", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "NAXIS3",
                    "EXTEND", "PCOUNT", "GCOUNT", "BZERO", "BSCALE", "BLANK", "CHECKSUM", "DATASUM"):
        header.remove(keyword, ignore_missing=True, remove_all=True)
    new_hdu = fits.PrimaryHDU(frame_for_solver(data))
    for card in header.cards:
        new_hdu.header.append(card)
    new_hdu.writeto(destination, overwrite=True)


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


def _image_height_px(path: Path) -> int:
    try:
        from astropy.io import fits
        with fits.open(path) as hdul:
            return int(hdul[0].shape[-2])
    except Exception:
        return 0


def _hms(ra_deg: float) -> str:
    seconds = round((ra_deg % 360.0) / 15.0 * 3600.0)
    return f"{seconds // 3600 % 24:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _dms(dec_deg: float) -> str:
    seconds = round(abs(dec_deg) * 3600.0)
    return f"{'-' if dec_deg < 0 else '+'}{seconds // 3600:02d}° {seconds % 3600 // 60:02d}' {seconds % 60:02d}\""
