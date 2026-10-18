# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Star-pattern databases for the tetra3 plate solver, built for each Pier's field of view (PLT-090).

tetra3's bundled database only covers fields of 10-30 degrees, far wider than a typical telescope and
camera. This module works out the field of view each Pier's optical tubes give (focal length, camera
pixel size and sensor width), plans one database per distinct range, downloads the star catalogue
tetra3 builds it from (Hipparcos for fields of 3 degrees and wider, Tycho below that) and builds it in a
separate process. A separate process is what lets the build be cancelled -- it can run for hours for a
narrow field -- and keeps its memory and CPU use away from the UI.

Domain-core: no Qt. The Options > Solve page drives :class:`DatabaseBuilder` and stores the results.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing
import queue
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_ARCSEC_PER_RAD_UM_MM = 206.265      # image scale in arcsec/px = this x pixel size (um) / focal length (mm)

_CATALOG_BASE = "https://cdsarc.cds.unistra.fr/ftp/cats/I/239/"

# name -> (file, approximate download size in MB, dimmest star magnitude to keep)
CATALOGS: dict[str, tuple[str, int, float]] = {
    "hip_main": ("hip_main.dat", 51, 7.0),
    "tyc_main": ("tyc_main.dat", 354, 10.0),
}

# Below this width (degrees) Hipparcos is too sparse to match patterns reliably; tetra3 recommends Tycho.
_TYCHO_BELOW_DEG = 3.0


@dataclass(frozen=True)
class DatabasePlan:
    """One database to build, and the Piers that will use it."""
    min_fov: float                 # degrees, along the image width (tetra3's convention)
    max_fov: float
    catalog: str                   # a key of CATALOGS
    path: Path
    pier_ids: tuple[int, ...]
    pier_labels: tuple[str, ...]

    @property
    def fov_text(self) -> str:
        if self.min_fov == self.max_fov:
            return f"{self.max_fov:g}°"
        return f"{self.min_fov:g}°–{self.max_fov:g}°"


def tetra3_dir() -> Path:
    """Where downloaded catalogues and built databases live (created on demand)."""
    from galileo.platform import get_data_dir
    folder = get_data_dir() / "tetra3"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def catalog_for(min_fov: float) -> str:
    return "tyc_main" if min_fov < _TYCHO_BELOW_DEG else "hip_main"


def database_path(catalog: str, min_fov: float, max_fov: float) -> Path:
    return tetra3_dir() / f"{catalog}_{min_fov:.2f}-{max_fov:.2f}deg.npz"


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def pier_fovs_deg(pier) -> list[float]:
    """Image-width fields of view, in degrees, of *pier*'s optical tubes with their cameras.

    A tube uses the cameras associated with it on the Optics page, or the Pier's primary camera if it
    has none. A tube or camera missing a focal length, pixel size or sensor width contributes nothing."""
    from galileo.library.models.device_config import PRIMARY_SLOT
    from galileo.observatory import get_device_config, list_optical_tubes
    fovs: list[float] = []
    for tube in list_optical_tubes(pier):
        if not tube.focal_length_mm:
            continue
        slots = [key.split(":", 1)[1] for key in tube.associated if key.startswith("camera:")] or [PRIMARY_SLOT]
        for slot in slots:
            camera = get_device_config(pier, "camera", slot=slot)
            if camera is None or not camera.pixel_size_um or not camera.sensor_width_px:
                continue
            scale = _ARCSEC_PER_RAD_UM_MM * camera.pixel_size_um / tube.focal_length_mm
            fovs.append(round(scale * camera.sensor_width_px / 3600.0, 2))
    return fovs


def all_piers() -> list:
    """Every Pier of every Observatory."""
    from galileo.observatory import list_observatories, list_piers
    return [pier for observatory in list_observatories() for pier in list_piers(observatory)]


def pier_label(pier) -> str:
    return f"{pier.observatory.name} / {pier.name}"


def plan_databases(piers: Iterable) -> tuple[list[DatabasePlan], list[str]]:
    """Plan the databases *piers* need. Returns ``(plans, skipped)`` where *skipped* names each Pier whose
    optics don't determine a field of view, and why. Piers whose range works out the same share a database."""
    groups: dict[tuple[float, float], list] = {}
    skipped: list[str] = []
    for pier in piers:
        fovs = pier_fovs_deg(pier)
        if not fovs:
            skipped.append(f"{pier_label(pier)} (needs an optical tube with a focal length and a camera with "
                           "its pixel size and sensor width)")
            continue
        groups.setdefault((min(fovs), max(fovs)), []).append(pier)
    plans = []
    for (low, high), members in sorted(groups.items()):
        catalog = catalog_for(low)
        plans.append(DatabasePlan(
            min_fov=low, max_fov=high, catalog=catalog, path=database_path(catalog, low, high),
            pier_ids=tuple(p.id for p in members), pier_labels=tuple(pier_label(p) for p in members)))
    return plans, skipped


def download_size_mb(plans: Iterable[DatabasePlan]) -> int:
    """Catalogue data still to download for *plans* (catalogues already on disk cost nothing)."""
    needed = {p.catalog for p in plans if not (tetra3_dir() / CATALOGS[p.catalog][0]).exists()}
    return sum(CATALOGS[name][1] for name in needed)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def _download_catalog(catalog: str, folder: Path, emit: Callable[..., None]) -> Path:
    """Fetch *catalog* into *folder* unless it is already there. Written to a ``.part`` file and renamed, so an
    interrupted download is never mistaken for a catalogue."""
    from galileo.net import urlopen_http
    name, size_mb, _ = CATALOGS[catalog]
    target = folder / name
    if target.exists():
        return target
    part = target.with_suffix(".part")
    emit("log", f"Downloading the {catalog} star catalogue (about {size_mb} MB)…")
    done, reported = 0, time.monotonic()
    with urlopen_http(_CATALOG_BASE + name, timeout=60) as response, open(part, "wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if time.monotonic() - reported > 2.0:
                reported = time.monotonic()
                emit("log", f"Downloading {catalog}: {done / 1e6:.0f} of about {size_mb} MB")
    part.replace(target)
    return target


@contextlib.contextmanager
def _catalog_dir(folder: Path) -> Iterator[None]:
    """tetra3 looks for its catalogue next to its own source file, which is read-only in an installed
    app; point it at *folder* for the duration of a build."""
    module = sys.modules.get("tetra3.tetra3")
    if module is None:
        yield
        return
    original = module.__file__
    module.__file__ = str(folder / "tetra3.py")
    try:
        yield
    finally:
        module.__file__ = original


def partial_path(plan: DatabasePlan) -> Path:
    """Where *plan*'s database is written until it is complete."""
    return plan.path.with_name(plan.path.stem + ".partial.npz")


def build_databases(plans: list[DatabasePlan], emit: Callable[..., None], folder: Path | None = None) -> None:
    """Build every plan, reporting through ``emit(kind, *args)``: ``"log"`` text, ``"built"`` plan index and
    path, ``"failed"`` plan index and reason. A plan whose database already exists is not rebuilt. Runs in the
    build process (:class:`DatabaseBuilder`) but is plain Python so it can be exercised in-process."""
    from galileo.platesolve_solvers import patch_numpy_for_tetra3
    folder = folder or tetra3_dir()
    patch_numpy_for_tetra3()
    import tetra3
    for index, plan in enumerate(plans):
        try:
            if plan.path.exists():
                emit("log", f"{plan.path.name} already exists.")
            else:
                _download_catalog(plan.catalog, folder, emit)
                emit("log", f"Building the {plan.fov_text} database from {plan.catalog}. A narrow field can take hours.")
                # Built under another name and renamed, so a cancelled build never leaves a half-written file.
                with _catalog_dir(folder):
                    tetra3.Tetra3(load_database=None).generate_database(
                        max_fov=plan.max_fov, min_fov=plan.min_fov, save_as=str(partial_path(plan)),
                        star_catalog=plan.catalog, star_max_magnitude=CATALOGS[plan.catalog][2])
                partial_path(plan).replace(plan.path)
            emit("built", index, str(plan.path))
        except Exception as exc:
            logger.exception("Could not build the tetra3 database %s", plan.path.name)
            partial_path(plan).unlink(missing_ok=True)
            emit("failed", index, f"{type(exc).__name__}: {exc}")


class _QueueLogHandler(logging.Handler):
    def __init__(self, emit: Callable[..., None]) -> None:
        super().__init__(level=logging.INFO)
        self._emit_message = emit

    def emit(self, record: logging.LogRecord) -> None:
        self._emit_message("log", record.getMessage())


def _build_process(plans: list[DatabasePlan], messages) -> None:
    """Entry point of the build process."""
    def emit(kind: str, *args) -> None:
        messages.put((kind, *args))

    tetra_logger = logging.getLogger("tetra3.Tetra3")
    tetra_logger.addHandler(_QueueLogHandler(emit))
    tetra_logger.propagate = False
    try:
        build_databases(plans, emit)
    finally:
        emit("finished")


class DatabaseBuilder:
    """Builds :class:`DatabasePlan` databases in a separate process, which :meth:`cancel` can stop.

    Call :meth:`poll` regularly (from a timer); it never blocks and returns the messages since the last
    call as tuples: ``("log", text)``, ``("built", index, path)``, ``("failed", index, reason)`` and,
    last, ``("finished",)`` -- also sent if the process dies or is cancelled."""

    def __init__(self, plans: list[DatabasePlan]) -> None:
        self.plans = plans
        context = multiprocessing.get_context("spawn")
        self._messages = context.Queue()
        self._process = context.Process(target=_build_process, args=(plans, self._messages), daemon=True)
        self._finished = False
        self._cancelled = False

    def start(self) -> None:
        self._process.start()

    @property
    def running(self) -> bool:
        return not self._finished

    def cancel(self) -> None:
        """Stop the build. The database being built is discarded; ones already finished are kept."""
        self._cancelled = True
        if self._process.is_alive():
            self._process.terminate()

    def _drain(self, wait: float = 0.0) -> list[tuple]:
        out: list[tuple] = []
        while True:
            try:
                out.append(self._messages.get(timeout=wait) if wait else self._messages.get_nowait())
            except queue.Empty:
                return out

    def poll(self) -> list[tuple]:
        out = self._drain()
        if not self._finished and not any(m[0] == "finished" for m in out)                 and not self._process.is_alive() and self._process.exitcode is not None:
            out += self._drain(wait=0.3)          # anything still in transit from a process that has just exited
            if not any(m[0] == "finished" for m in out):
                # It ended without saying so: cancelled, crashed or out of memory.
                if not self._cancelled:
                    out.append(("failed", -1, f"The build process stopped unexpectedly (exit code {self._process.exitcode})."))
                for plan in self.plans:
                    partial_path(plan).unlink(missing_ok=True)
                out.append(("finished",))
        if any(m[0] == "finished" for m in out):
            self._finished = True
        return out
