# SPDX-License-Identifier: GPL-3.0-or-later AND GPL-2.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
# Portions derived from KStars/Ekos (kstars/ekos/align/polaralign.cpp),
# SPDX-FileCopyrightText: 2021 Hy Murveit, GPL-2.0-or-later. Modified: translated to Python and reworked.

"""Plate-solve polar alignment (PLT-080).

Where the mount's RA axis points is found from three plate solves taken at different RA
positions. The mount body is fixed to the Earth, so in the Earth-fixed horizon frame a camera
attached to the mount swings on an exact circle about the RA axis whatever the mount is doing
(tracking included). Each solve is therefore converted to altitude/azimuth *at the time its frame
was taken*, and the axis is the normal of the plane through the three points. That needs no
knowledge of how far the mount really turned, so it does not trust the mount's own RA readout.

The error is the angular distance from that axis to the celestial pole, split into the two
things the mount's adjusters change: altitude, and azimuth (reported both as the distance the
axis moves across the sky and as the rotation of the mount). Solved altitudes are raised by
atmospheric refraction, as the mount must point higher to see a star, but the target stays the
geometric pole: aiming the axis at the refracted pole would help at one altitude and hurt at
every other.

Once measured, the mount stays where it is and the screen keeps solving. The user's turns of the
altitude and azimuth knobs are modelled as what they are, a rotation about the east-west
horizontal axis and then about the vertical (the smallest such pair that carries the third
measuring position onto the newly solved one, after allowing for the mount's tracking since),
and the axis is rotated by the same pair, so the error updates live and is exact wherever the
camera points. The model assumes the mount is level, as does any polar-alignment routine of this
kind.

The knob model for the live update (:func:`knob_adjustment`, :func:`axis_after_adjustment` and the two
rotation helpers) is derived from ``PolarAlign::processRefreshCoords`` and ``findSmallestThetaY`` in
KStars/Ekos (Hy Murveit, GPL-2.0-or-later), translated to Python and modified. The axis fit, error
split, refraction, frame-offset display and the workflow are Galileo's own.

:class:`PolarAlignWorkflow` is domain-core like :class:`~galileo.platesolve.SolveWorkflow`, which
it extends: it drives a camera, mount and solver through their ports and reports through a
callback on the thread it runs on.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from galileo.platesolve import (
    PlateSolver,
    SolveSettings,
    SolveWorkflow,
    j2000_to_mount_frame,
    mount_frame_to_j2000,
)
from galileo.platesolve_solvers import angular_offset_arcsec

logger = logging.getLogger(__name__)

MEASURE_POINTS = 3                    # solves taken while rotating, before adjusting begins
MIN_SEPARATION_DEG = 0.25             # solves closer together than this cannot fix the axis
SIDEREAL_DEG_PER_S = 360.98564736629 / 86400.0
_MAX_FAILED_ADJUST_SOLVES = 3         # consecutive failures that end the adjust phase
_TRAVEL_WARN_FRACTION = 0.9           # warn if the mount turned less than this share of what was asked
_POLE_NEIGHBOURHOOD_DEG = 2.0         # within this of a pole a meridian flip is no concern
_ZENITH_PASSES = 3                    # solve-sync-reslew rounds spent getting the mount onto the zenith
_ARRIVAL_TOLERANCE_DEG = 1.0          # how close to its target the mount must report being before a frame is taken


class PolarAlignError(Exception):
    """The measurements cannot give an axis (points too close together, too few of them)."""


def _wrap180(angle_deg: float) -> float:
    return (angle_deg + 180.0) % 360.0 - 180.0


def altaz_vector(alt_deg: float, az_deg: float) -> np.ndarray:
    """Unit vector in the horizon frame: x north, y east, z up (azimuth from north through east)."""
    alt, az = math.radians(alt_deg), math.radians(az_deg)
    return np.array([math.cos(alt) * math.cos(az), math.cos(alt) * math.sin(az), math.sin(alt)])


def vector_altaz(vector: np.ndarray) -> tuple[float, float]:
    """``(alt°, az°)`` of a horizon-frame vector; azimuth in [0, 360)."""
    return (math.degrees(math.atan2(vector[2], math.hypot(vector[0], vector[1]))),
            math.degrees(math.atan2(vector[1], vector[0])) % 360.0)


def refracted_altitude(alt_deg: float) -> float:
    """Where a star at true altitude *alt_deg* appears, at standard temperature and pressure
    (Sæmundsson). Refraction raises stars, so a mount must point this high to see one."""
    if alt_deg < -1.0:
        return alt_deg
    return alt_deg + (1.02 / math.tan(math.radians(alt_deg + 10.3 / (alt_deg + 5.11)))) / 60.0


def horizon_vector(ra_deg: float, dec_deg: float, when: dt.datetime, latitude: float, longitude: float,
                   refract: bool = True) -> np.ndarray:
    """Where coordinates of date are in the Earth-fixed horizon frame at *when* (raised by
    refraction if asked)."""
    from galileo.planning.star_atlas import equatorial_to_horizontal, julian_date, local_sidereal_deg
    lst = local_sidereal_deg(julian_date(when), longitude)
    alt, az = equatorial_to_horizontal(ra_deg, dec_deg, lst, latitude)
    return altaz_vector(refracted_altitude(float(alt)) if refract else float(alt), float(az))


def pole_vector(latitude_deg: float) -> np.ndarray:
    """The celestial pole of the hemisphere (the one above the horizon), as a horizon-frame vector."""
    lat = math.radians(latitude_deg)
    return np.array([math.cos(lat), 0.0, math.sin(lat)]) if latitude_deg >= 0 \
        else np.array([-math.cos(lat), 0.0, -math.sin(lat)])


def format_angle(arcsec: float) -> str:
    """An angle as people read it off a polar-alignment screen: ``45″``, ``3′12″`` or ``1°02′05″``."""
    total = round(abs(arcsec))
    degrees, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if degrees:
        return f"{degrees}°{minutes:02d}′{seconds:02d}″"
    if minutes:
        return f"{minutes}′{seconds:02d}″"
    return f"{seconds}″"


@dataclass(frozen=True)
class PolarError:
    """How far the mount's RA axis is from the celestial pole."""
    axis: tuple[float, float, float]      # unit vector of the axis, horizon frame (x north, y east, z up)
    total_arcsec: float                   # angular distance from the pole
    altitude_arcsec: float                # axis altitude minus pole altitude; positive = axis too high
    azimuth_arcsec: float                 # how far east of the pole the axis points, along the sky (negative = west)
    azimuth_rotation_arcsec: float        # the same as the angle the mount is turned through in azimuth

    def altitude_advice(self) -> str:
        if round(abs(self.altitude_arcsec)) == 0:
            return "Altitude is spot on."
        verb = "Lower" if self.altitude_arcsec > 0 else "Raise"
        return f"{verb} the polar axis by {format_angle(self.altitude_arcsec)}."

    def azimuth_advice(self) -> str:
        if round(abs(self.azimuth_arcsec)) == 0:
            return "Azimuth is spot on."
        side = "west" if self.azimuth_arcsec > 0 else "east"
        return (f"Move the polar axis {side} by {format_angle(self.azimuth_arcsec)} "
                f"(turn the mount {format_angle(self.azimuth_rotation_arcsec)} in azimuth).")


def fit_rotation_axis(vectors: list[np.ndarray], latitude_deg: float) -> np.ndarray:
    """The axis a set of horizon-frame positions swings round: the normal of the plane through them
    (least-squares for more than three), as a unit vector on the pole's side.

    Raises :class:`PolarAlignError` if there are fewer than three, or they are too close together
    or too nearly in line to define a circle."""
    if len(vectors) < MEASURE_POINTS:
        raise PolarAlignError(f"Need at least {MEASURE_POINTS} solved positions, have {len(vectors)}.")
    points = np.array(vectors)
    widest = max(math.degrees(math.acos(float(np.clip(points[i] @ points[j], -1.0, 1.0))))
                 for i in range(len(points)) for j in range(i))
    if widest < MIN_SEPARATION_DEG:
        raise PolarAlignError(
            f"The solved positions are only {widest:.2f}° apart — too close to find the axis. "
            "Rotate further, or point nearer the equator.")
    _, singular, vt = np.linalg.svd(points - points.mean(axis=0))
    if singular[1] < 0.005 * singular[0]:
        raise PolarAlignError("The solved positions are in a straight line, so they do not define a circle.")
    normal = vt[2]
    return normal if normal @ pole_vector(latitude_deg) >= 0 else -normal


def polar_error(axis: np.ndarray, latitude_deg: float) -> PolarError:
    """The error of *axis* (unit vector, horizon frame) against the pole."""
    northern = latitude_deg >= 0
    pole = pole_vector(latitude_deg)
    total = math.degrees(math.atan2(float(np.linalg.norm(np.cross(axis, pole))), float(axis @ pole)))
    alt, az = vector_altaz(axis)
    pole_alt = abs(latitude_deg)
    # Azimuth rises eastward only when facing north; facing the south pole it rises westward.
    east = _wrap180(az - (0.0 if northern else 180.0)) * (1.0 if northern else -1.0)
    return PolarError(
        axis=(float(axis[0]), float(axis[1]), float(axis[2])), total_arcsec=total * 3600.0,
        altitude_arcsec=(alt - pole_alt) * 3600.0,
        azimuth_arcsec=east * math.cos(math.radians(pole_alt)) * 3600.0,    # a degree of azimuth is shorter up high
        azimuth_rotation_arcsec=east * 3600.0)


def target_offset_arcmin(result, axis: np.ndarray, when: dt.datetime, latitude: float, longitude: float,
                         ) -> tuple[float, float] | None:
    """Where the celestial pole lies relative to where the mount's axis points, as seen in the frame *result* solved:
    ``(dx, dy)`` in arcminutes, x to the right and y downwards (the way the frame is shown).

    The axis is a fixed point in the camera's view (the camera turns about it), and the pole moves towards it as
    the altitude and azimuth adjusters are turned, so the user is asked to bring the pole (drawn as an X) into the
    axis point (drawn as a circle). Both are put through the same horizon frame, so they coincide exactly when the
    reported error is nil. ``None`` if the solver gave no CD matrix, or either point is too far from the frame
    centre for a flat projection."""
    cd = getattr(result, "cd", None)
    if cd is None or result.ra_deg is None or result.dec_deg is None:
        return None
    from galileo.planning.star_atlas import horizontal_to_equatorial, julian_date, local_sidereal_deg
    lst = local_sidereal_deg(julian_date(when), longitude)
    ra0, dec0 = math.radians(result.ra_deg), math.radians(result.dec_deg)

    def pixels(vector: np.ndarray) -> np.ndarray | None:
        alt, az = vector_altaz(vector)
        ra, dec = horizontal_to_equatorial(alt, az, lst, latitude)
        ra, dec = mount_frame_to_j2000(ra, dec, None)
        ra, dec = math.radians(ra), math.radians(dec)
        d = math.sin(dec) * math.sin(dec0) + math.cos(dec) * math.cos(dec0) * math.cos(ra - ra0)
        if d <= 0.05:
            return None
        xi = math.degrees(math.cos(dec) * math.sin(ra - ra0) / d)           # standard coordinates, east
        eta = math.degrees((math.sin(dec) * math.cos(dec0) - math.cos(dec) * math.sin(dec0) * math.cos(ra - ra0)) / d)
        return np.linalg.solve(np.array([[cd[0], cd[1]], [cd[2], cd[3]]]), np.array([xi, eta]))

    circle, cross = pixels(axis), pixels(pole_vector(latitude))
    if circle is None or cross is None:
        return None
    scale_arcmin = math.hypot(cd[0], cd[2]) * 60.0
    dx, dy = (cross - circle) * scale_arcmin
    return float(dx), float(dy)


def _rotate_about(vector: np.ndarray, axis: np.ndarray, degrees: float) -> np.ndarray:
    a = math.radians(degrees)
    return (vector * math.cos(a) + np.cross(axis, vector) * math.sin(a)
            + axis * float(axis @ vector) * (1 - math.cos(a)))


def _rotate_y(vector: np.ndarray, degrees: float) -> np.ndarray:
    """About the east-west horizontal axis: what the altitude knob turns the mount through."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return np.array([c * vector[0] + s * vector[2], vector[1], -s * vector[0] + c * vector[2]])


def _rotate_z(vector: np.ndarray, degrees: float) -> np.ndarray:
    """About the vertical: what the azimuth knob turns the mount through."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return np.array([c * vector[0] - s * vector[1], s * vector[0] + c * vector[1], vector[2]])


def knob_adjustment(start: np.ndarray, goal: np.ndarray) -> tuple[float, float] | None:
    """The smallest turns of the altitude knob then the azimuth knob, ``(about y°, about z°)``, that carry
    *start* to *goal*; ``None`` if no such pair does. The altitude turn leaves the point's y alone and
    the azimuth turn leaves its z alone, which fixes the intermediate point up to a sign."""
    radicand = 1.0 - start[1] ** 2 - goal[2] ** 2
    if radicand < -1e-9:
        return None
    root = math.sqrt(max(0.0, radicand))
    best: tuple[float, float] | None = None
    for x in (root, -root):
        theta_y = _wrap180(math.degrees(math.atan2(x, goal[2]) - math.atan2(start[0], start[2])))
        turned = _rotate_y(start, theta_y)
        theta_z = _wrap180(math.degrees(math.atan2(goal[1], goal[0]) - math.atan2(turned[1], turned[0])))
        if best is None or abs(theta_y) + abs(theta_z) < abs(best[0]) + abs(best[1]):
            best = (theta_y, theta_z)
    return best


def tracking_angle(seconds: float, latitude_deg: float) -> float:
    """How far a camera on a tracking mount turns about the pole-side RA axis in *seconds*, in degrees
    (about an axis pointing at the pole, as :func:`fit_rotation_axis` returns it). The sign flips with
    the hemisphere, and is the opposite of what a right-handed frame would give because the horizon
    frame (x north, y east, z up) is left-handed."""
    return SIDEREAL_DEG_PER_S * seconds * (1.0 if latitude_deg >= 0 else -1.0)


def axis_after_adjustment(axis: np.ndarray, anchor: np.ndarray, new: np.ndarray, seconds: float,
                          latitude_deg: float) -> np.ndarray | None:
    """The RA axis once the user has turned the mount's knobs, given *anchor* (the last measuring
    position), *new* (where the field is now, taken *seconds* later) and the *axis* as measured.
    ``None`` if the knobs cannot explain the move."""
    untouched = _rotate_about(anchor, axis, tracking_angle(seconds, latitude_deg))     # tracking alone moves it
    turns = knob_adjustment(untouched, new)
    if turns is None:
        return None
    return _rotate_z(_rotate_y(axis, turns[0]), turns[1])


@dataclass
class PolarAlignSettings(SolveSettings):
    """One polar-alignment run's settings. ``exposure_s``, ``settle_s`` and ``scale_hint_arcsec_px``
    are those of :class:`~galileo.platesolve.SolveSettings`."""
    work_dec_deg: float = 70.0        # declination (magnitude) to measure at, after the zenith start:
                                      # solves right at the pole are unreliable
    step_deg: float = 30.0            # how far the mount turns in RA between the measuring solves
    direction: str = "east"           # "east" or "west": which way the RA axis turns
    refraction: bool = True           # raise solved altitudes by atmospheric refraction
    arrival_timeout_s: float = 120.0  # how long to wait for the mount to reach each position before giving up


@dataclass
class PolarAlignProgress:
    """What the workflow tells its caller as it goes."""
    phase: str                        # "measuring" | "adjusting"
    message: str
    step: int = 0                     # measuring: the solve being taken, 1-based
    steps: int = MEASURE_POINTS
    error: PolarError | None = None   # known once measuring is done, refreshed on every adjusting solve
    # Adjusting: where the pole (X) lies relative to the axis point (circle) in the latest frame, in
    # arcminutes (x right, y down); ``None`` when the solver gave no WCS to place them with.
    target_offset: tuple[float, float] | None = None


class PolarAlignWorkflow(SolveWorkflow):
    """Measure the polar-alignment error and then keep it up to date while the user adjusts (PLT-080)."""

    def __init__(
        self,
        solver: PlateSolver,
        camera=None,
        mount=None,
        *,
        latitude: float,
        longitude: float,
        on_progress: Callable[[PolarAlignProgress], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(solver, camera=camera, mount=mount, **kwargs)
        self.latitude, self.longitude = latitude, longitude
        self._on_progress = on_progress or (lambda progress: None)
        self.error: PolarError | None = None      # the latest

    async def align(self, settings: PolarAlignSettings) -> None:
        """Measure, then adjust until :meth:`stop` is called (or solving keeps failing)."""
        await self._run(self._align(settings))

    def _report(self, phase: str, message: str, step: int = 0, error: PolarError | None = None,
                target_offset: tuple[float, float] | None = None) -> None:
        self._log(message)
        self._on_progress(PolarAlignProgress(phase, message, step=step, error=error, target_offset=target_offset))

    def _crosses_meridian(self, start_ra: float, dec: float, offsets: list[float]) -> bool:
        """Whether turning to *offsets* degrees from *start_ra* takes a GEM across the meridian (where it
        would flip, which ruins the measurement). Near a pole there is no meridian to speak of."""
        if abs(dec) > 90.0 - _POLE_NEIGHBOURHOOD_DEG:
            return False
        from galileo.planning.star_atlas import julian_date, local_sidereal_deg
        lst = local_sidereal_deg(julian_date(dt.datetime.now(dt.UTC)), self.longitude)
        hour_angles = [_wrap180(lst - (start_ra + offset)) for offset in offsets]
        return min(hour_angles) <= 0.0 <= max(hour_angles)

    async def _slew_and_arrive(self, ra: float, dec: float, system: str | None, settings: PolarAlignSettings,
                               ) -> tuple[float, float, str | None] | None:
        """Slew to the mount-frame position (*ra*, *dec*) and wait until the mount reports being there, then settle.
        Returns where it ended up, or ``None`` (after saying so) if it never got there. A mount's "slewing" flag can
        still read false just after the command, so the slew finishing is not taken as arriving: a frame taken then
        is of the wrong place."""
        await self._slew(mount_frame_to_j2000(ra, dec, system), system)
        deadline = asyncio.get_running_loop().time() + settings.arrival_timeout_s
        while True:
            position = await self._mount_position()
            if position is not None:
                separation = math.hypot(_wrap180(position[0] - ra) * math.cos(math.radians(dec)), position[1] - dec)
                if separation <= _ARRIVAL_TOLERANCE_DEG:
                    break
            if asyncio.get_running_loop().time() >= deadline:
                self._report("measuring", "The mount did not reach the position it was sent to, so no frame was taken "
                                          "there. Check that it is unparked, tracking, and clear of its limits.")
                return None
            await asyncio.sleep(1.0)
        await asyncio.sleep(settings.settle_s)
        return position

    def _zenith_j2000(self) -> tuple[float, float]:
        """The zenith now (RA = local sidereal time, Dec = latitude, of date) as J2000 coordinates."""
        from galileo.planning.star_atlas import julian_date, local_sidereal_deg
        lst = local_sidereal_deg(julian_date(dt.datetime.now(dt.UTC)), self.longitude)
        return mount_frame_to_j2000(lst, self.latitude, None)

    async def _go_to_zenith(self, settings: PolarAlignSettings, system: str | None) -> int | None:
        """Slew to the zenith and solve to check the mount really is there. If it is not (it has never been synced,
        so its idea of its position is wrong) sync it to the solution and slew again, up to ``_ZENITH_PASSES``
        times. Returns how many frames were taken, or ``None`` after saying why the run cannot start."""
        attempt = 0
        for pass_number in range(1, _ZENITH_PASSES + 1):
            zenith = self._zenith_j2000()
            self._report("measuring", "Moving the mount to the zenith to start…" if pass_number == 1
                         else "Moving the mount to the zenith again…")
            mount_zenith = j2000_to_mount_frame(*zenith, system)
            if await self._slew_and_arrive(mount_zenith[0], mount_zenith[1], system, settings) is None:
                return None
            self._report("measuring", "Taking a frame at the zenith to check the mount is there…")
            solved = None
            for hint in (zenith, None):              # then blind, in case the mount's position is far out
                frame = await self._capture(settings, attempt)
                attempt += 1
                if frame is None:
                    return None
                result = await self._solve(frame, hint, settings)
                if result.success and result.ra_deg is not None and result.dec_deg is not None:
                    solved = (result.ra_deg, result.dec_deg)
                    break
            if solved is None:
                self._report("measuring", "The frame at the zenith did not solve, so the mount's position cannot be "
                                          "checked. Check focus and exposure, and that the sky is clear overhead.")
                return None
            d_ra, d_dec = angular_offset_arcsec(*solved, *zenith)
            off_deg = math.hypot(d_ra, d_dec) / 3600.0
            if off_deg <= _ARRIVAL_TOLERANCE_DEG:
                self._log(f"The mount is at the zenith ({off_deg * 60.0:.1f}′ off).")
                return attempt
            self._report("measuring", f"The mount is {off_deg:.1f}° from the zenith, not where it reports being. "
                                      "Syncing it to the solution" +
                         (" and moving to the zenith again…" if pass_number < _ZENITH_PASSES else "."))
            await self._sync(solved, system)
        self._log("The mount is still not at the zenith after syncing; carrying on from where it is.")
        return attempt

    async def _align(self, settings: PolarAlignSettings) -> None:
        if self.mount is None:
            self._log("Polar alignment needs a connected mount to rotate.")
            return
        position = await self._mount_position()
        if position is None:
            self._log("The mount's position is unknown, so it cannot be rotated.")
            return
        system = position[2]
        direction = 1.0 if settings.direction == "east" else -1.0
        offsets = [direction * settings.step_deg * i for i in range(MEASURE_POINTS)]

        # The scope can be anywhere to begin with, and its idea of where it points may be wrong (never synced).
        # It is first sent to the zenith, a known position clear of the pole and of any cable or limit trouble,
        # and a solve there confirms it; if it is somewhere else the mount is synced to the solution and sent
        # again. Then it goes to the measuring position. Solves at the pole are unreliable (the field's RA
        # converges) and an RA turn about the axis barely moves the camera, so the three measuring positions
        # are taken well away from it, at a declination of the working band.
        attempt = await self._go_to_zenith(settings, system)
        if attempt is None:
            return
        from galileo.planning.star_atlas import julian_date, local_sidereal_deg
        lst = local_sidereal_deg(julian_date(dt.datetime.now(dt.UTC)), self.longitude)

        # RA means nothing at the zenith as a starting point, so choose one that leaves the whole swing on one
        # side of the meridian: east of it (negative hour angle) when turning west, and the reverse turning east.
        target_dec = math.copysign(settings.work_dec_deg, self.latitude or 1.0)
        reach = max(90.0, (MEASURE_POINTS - 1) * settings.step_deg + 15.0)
        start_ra = (lst - direction * reach) % 360.0
        self._report("measuring", f"Moving to Dec {target_dec:+.0f}° before measuring…")
        moved = await self._slew_and_arrive(start_ra, target_dec, system, settings)
        if moved is None:
            return
        start_ra, dec, system = moved

        if self._crosses_meridian(*j2000_to_mount_frame(*mount_frame_to_j2000(start_ra, dec, system), None), offsets):
            self._report("measuring", f"Turning {abs(offsets[-1]):g}° {settings.direction} would take the mount "
                                      "across the meridian, where it would flip. Turn the other way, or start further "
                                      "from the meridian.")
            return
        vectors: list[np.ndarray] = []
        stamps: list[dt.datetime] = []
        hint = mount_frame_to_j2000(start_ra, dec, system)

        for i in range(MEASURE_POINTS):
            if i:
                self._report("measuring", f"Rotating the mount {settings.step_deg:g}° {settings.direction}…", i)
                moved = await self._slew_and_arrive((start_ra + offsets[i]) % 360.0, dec, system, settings)
                if moved is None:
                    return
                hint = mount_frame_to_j2000(moved[0], moved[1], system)
                turned = _wrap180(moved[0] - start_ra)
                if abs(turned) < _TRAVEL_WARN_FRACTION * abs(offsets[i]):
                    self._log(f"The mount turned {turned:+.1f}° of the {offsets[i]:+.1f}° asked for; carrying on.")
            self._report("measuring", f"Solving position {i + 1} of {MEASURE_POINTS}…", i + 1)
            solved = await self._capture_solve(settings, hint, attempt)
            attempt += 1
            if solved is None:
                self._report("measuring", f"Position {i + 1} did not solve, so the axis cannot be measured.", i + 1)
                return
            vectors.append(solved[0])
            stamps.append(solved[1])

        try:
            axis = fit_rotation_axis(vectors, self.latitude)
        except PolarAlignError as exc:
            self._report("measuring", str(exc), MEASURE_POINTS)
            return
        self.error = polar_error(axis, self.latitude)
        self._report("adjusting", f"Polar axis is {format_angle(self.error.total_arcsec)} from the pole. "
                                  "Turn the altitude and azimuth adjusters to bring the X into the circle.",
                     MEASURE_POINTS, self.error,
                     target_offset_arcmin(solved[2], axis, stamps[-1], self.latitude, self.longitude))

        anchor, anchor_time = vectors[-1], stamps[-1]
        failures = 0
        while True:
            fresh = await self._capture_solve(settings, hint, attempt)
            attempt += 1
            if fresh is None:
                failures += 1
                if failures >= _MAX_FAILED_ADJUST_SOLVES:
                    self._report("adjusting", "Solving keeps failing, so live adjustment has stopped.", MEASURE_POINTS)
                    return
                continue
            failures = 0
            adjusted = axis_after_adjustment(axis, anchor, fresh[0], (fresh[1] - anchor_time).total_seconds(),
                                             self.latitude)
            if adjusted is None:
                self._log("The mount has moved in a way the altitude and azimuth knobs cannot explain; waiting.")
                continue
            self.error = polar_error(adjusted, self.latitude)
            self._report("adjusting", f"Polar axis is {format_angle(self.error.total_arcsec)} from the pole.",
                         MEASURE_POINTS, self.error,
                         target_offset_arcmin(fresh[2], adjusted, fresh[1], self.latitude, self.longitude))

    async def _capture_solve(self, settings: PolarAlignSettings, hint, attempt: int) -> tuple[np.ndarray, dt.datetime, object] | None:
        """One frame, solved: where it points in the horizon frame, when (mid-exposure) and the solver's result,
        or ``None`` if either step failed."""
        frame = await self._capture(settings, attempt)
        if frame is None:
            return None
        stamp = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=settings.exposure_s / 2.0)
        result = await self._solve(frame, hint, settings)
        if not result.success or result.ra_deg is None or result.dec_deg is None:
            return None
        ra, dec = j2000_to_mount_frame(result.ra_deg, result.dec_deg, None)       # coordinates of date
        return horizon_vector(ra, dec, stamp, self.latitude, self.longitude, settings.refraction), stamp, result
