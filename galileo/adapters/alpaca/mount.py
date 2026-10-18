# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Alpaca adapter(s): mount."""

from __future__ import annotations

import datetime
import logging
from typing import Any, ClassVar

from galileo.adapters.alpaca._base import AlpacaAdapter
from galileo.core.devices import DeviceCategory
from galileo.core.slew_guard import get_slew_guard
from galileo.exceptions import MountParkedError

logger = logging.getLogger(__name__)


class AlpacaMountAdapter(AlpacaAdapter):
    # ASCOM's SideOfPier/EquatorialSystem/TrackingRate properties are integer
    # enums on the wire — normalized to strings here so the UI (and any other
    # caller) doesn't need to know ASCOM's enum ordinals.
    _SIDE_OF_PIER: ClassVar = {-1: "Unknown", 0: "East", 1: "West"}
    _EQUATORIAL_SYSTEM: ClassVar = {0: "Other", 1: "JNOW", 2: "J2000", 3: "J2050", 4: "B1950"}
    TRACKING_RATE_NAMES: ClassVar = ["Sidereal", "Lunar", "Solar", "King"]

    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.MOUNT, host, port, **kwargs)
        self.ra = 0.0
        self.dec = 0.0
        self.altitude = 0.0
        self.azimuth = 0.0
        self.pier_side = "East"
        self.is_tracking = False
        self.is_slewing = False
        self._static_status: dict[str, Any] | None = None
        self.site_lat: float | None = None
        self.site_lon: float | None = None
        self.site_elevation: float | None = None

    async def connect(self) -> None:
        await super().connect()
        await self._sync_site_and_time()

    async def _sync_site_and_time(self) -> None:
        """Push current UTC time and (if configured) site coordinates to the
        mount immediately after connection so goto, meridian-flip limits, and
        sidereal time are all computed from accurate values."""
        utc_now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")
        pairs: list[tuple[str, str, object]] = [
            ("utcdate", "UTCDate", utc_now),
            ("sitelatitude", "SiteLatitude", self.site_lat),
            ("sitelongitude", "SiteLongitude", self.site_lon),
            ("siteelevation", "SiteElevation", self.site_elevation),
        ]
        for attribute, key, value in pairs:
            if value is None:
                continue
            try:
                await self._put(attribute, **{key: value})
            except Exception:
                logger.warning("Could not set %s on Alpaca mount %s", attribute, self.base_url, exc_info=True)
        self._static_status = None  # site values may have changed; re-read on next get_status()

    async def _refuse_if_parked(self, command: str) -> None:
        """Movement commands must not reach a parked mount. Asks the mount
        (``AtPark``) rather than trusting a cached value, so a park done
        outside Galileo is honoured too. If the mount can't say, the command
        goes ahead and the device decides — ASCOM drivers reject movement
        while parked themselves."""
        try:
            parked = bool(await self._get("atpark"))
        except Exception:
            logger.warning("Could not read AtPark from %s before %s; sending it anyway", self.base_url, command)
            return
        if parked:
            logger.warning("Not sending %s to %s: the mount is parked", command, self.base_url)
            raise MountParkedError(f"The mount is parked, so {command} was not sent — unpark it first.")

    async def slew_to_coordinates(self, ra: float, dec: float) -> None:
        await self._refuse_if_parked("slew_to_coordinates")
        (getattr(self, "slew_guard", None) or get_slew_guard()).check_radec(ra, dec)
        await self._put("slewtocoordinatesasync", RightAscension=ra / 15.0, Declination=dec)
        self.ra, self.dec = ra, dec

    async def slew_to_altaz(self, alt: float, az: float) -> None:
        await self._refuse_if_parked("slew_to_altaz")
        (getattr(self, "slew_guard", None) or get_slew_guard()).check_altaz(alt, az)
        await self._put("slewtoaltazasync", Azimuth=az, Altitude=alt)
        self.altitude, self.azimuth = alt, az

    async def abort_slew(self) -> None:
        await self._put("abortslew")

    async def park(self) -> None:
        await self._put("park")

    async def unpark(self) -> None:
        await self._put("unpark")

    async def find_home(self) -> None:
        await self._refuse_if_parked("find_home")
        await self._put("findhome")

    async def move_axis(self, axis: int, rate: float) -> None:
        """Continuous jog via ``ITelescopeV3.MoveAxis`` — Axis 0 is Primary
        (RA/Az), Axis 1 is Secondary (Dec/Alt). A nonzero ``rate`` (deg/s)
        starts motion on that axis; ``rate=0`` stops it. Used by the Mount
        page's N/S/E/W jog buttons rather than a one-shot relative slew,
        since MoveAxis is the standard way to drive a mount while a button
        is held rather than computing a target coordinate. Stopping an axis
        (``rate=0``) is always allowed."""
        if rate:
            await self._refuse_if_parked("move_axis")
        await self._put("moveaxis", Axis=axis, Rate=rate)

    async def set_tracking(self, enabled: bool) -> None:
        if enabled:
            await self._refuse_if_parked("set_tracking")
        await self._put("tracking", Tracking=enabled)
        self.is_tracking = enabled

    async def set_tracking_rate(self, ra_rate_arcsec_s: float, dec_rate_arcsec_s: float) -> None:
        self._properties.update({"RA_RATE": ra_rate_arcsec_s, "DEC_RATE": dec_rate_arcsec_s})

    async def set_tracking_rate_mode(self, mode: str) -> None:
        """Select one of ASCOM's four standard ``TrackingRate`` enum values
        (Sidereal/Lunar/Solar/King) by name — distinct from
        ``set_tracking_rate``'s arbitrary custom RA/Dec rates (EQP-MNT-040's
        non-sidereal tracking), this is the Mount page's "Set tracking rate"
        control mirroring what a real ASCOM driver exposes as a dropdown."""
        try:
            idx = self.TRACKING_RATE_NAMES.index(mode)
        except ValueError:
            idx = 0
        await self._put("trackingrate", TrackingRate=idx)

    async def sync_to_coordinates(self, ra: float, dec: float) -> None:
        await self._refuse_if_parked("sync_to_coordinates")
        await self._put("synctocoordinates", RightAscension=ra / 15.0, Declination=dec)
        self.ra, self.dec = ra, dec

    async def _read_static_status(self) -> dict[str, Any]:
        """Properties that don't change while connected. A failed read is
        logged once and stays ``None`` (cached too, so an unimplemented
        optional property like SiteElevation isn't retried every poll)."""
        static: dict[str, Any] = {}
        reads: list[tuple[str, str, Any]] = [
            ("name", "name", str),
            ("description", "description", str),
            ("driver_info", "driverinfo", str),
            ("driver_version", "driverversion", str),
            ("site_latitude", "sitelatitude", float),
            ("site_longitude", "sitelongitude", float),
            ("site_elevation", "siteelevation", float),
        ]
        for key, attribute, caster in reads:
            try:
                value = await self._get(attribute)
                static[key] = caster(value) if value is not None else None
            except Exception:
                logger.exception("Could not read %s from %s", attribute, self.base_url)
                static[key] = None
        try:
            raw_equatorial_system = await self._get("equatorialsystem")
            static["equatorial_system"] = (
                self._EQUATORIAL_SYSTEM.get(int(raw_equatorial_system)) if raw_equatorial_system is not None else None
            )
        except Exception:
            logger.exception("Could not read EquatorialSystem from %s", self.base_url)
            static["equatorial_system"] = None
        return static

    async def get_status(self) -> dict:
        """Live-query this mount's status from the standard ASCOM
        ``ITelescopeV3`` properties — the Mount page's live status display
        (Name/Description/Driver info/version, Site latitude/longitude/
        elevation, Sidereal time, Right Ascension/Declination, Altitude/
        Azimuth, Side of Pier, Tracking, Epoch). Every property is read
        defensively since not every driver implements every optional one
        (e.g. SiteElevation) — a failed read leaves that field ``None``
        rather than aborting the whole refresh.

        The UI polls this every couple of seconds and each property is its
        own HTTP request, so the ones that never change while connected
        (identity, site, equatorial system) are read once and reused."""
        if self._static_status is None:
            self._static_status = await self._read_static_status()
        status: dict[str, Any] = dict(self._static_status)
        reads: list[tuple[str, str, Any]] = [
            ("sidereal_time", "siderealtime", float),
            ("right_ascension", "rightascension", float),
            ("declination", "declination", float),
            ("altitude", "altitude", float),
            ("azimuth", "azimuth", float),
            ("tracking", "tracking", bool),
            ("slewing", "slewing", bool),
            ("at_park", "atpark", bool),
        ]
        for key, attribute, caster in reads:
            try:
                value = await self._get(attribute)
                status[key] = caster(value) if value is not None else None
            except Exception:
                logger.exception("Could not read %s from %s", attribute, self.base_url)
                status[key] = None
        try:
            raw_side_of_pier = await self._get("sideofpier")
            status["side_of_pier"] = self._SIDE_OF_PIER.get(int(raw_side_of_pier)) if raw_side_of_pier is not None else None
        except Exception:
            logger.exception("Could not read SideOfPier from %s", self.base_url)
            status["side_of_pier"] = None
        try:
            raw_rate = await self._get("trackingrate")
            idx = int(raw_rate) if raw_rate is not None else -1
            status["tracking_rate"] = self.TRACKING_RATE_NAMES[idx] if 0 <= idx < len(self.TRACKING_RATE_NAMES) else None
        except Exception:
            logger.debug("Could not read TrackingRate from %s", self.base_url, exc_info=True)
            status["tracking_rate"] = None

        if status.get("right_ascension") is not None:
            self.ra = status["right_ascension"] * 15.0
        if status.get("declination") is not None:
            self.dec = status["declination"]
        if status.get("altitude") is not None:
            self.altitude = status["altitude"]
        if status.get("azimuth") is not None:
            self.azimuth = status["azimuth"]
        if status.get("side_of_pier") is not None:
            self.pier_side = status["side_of_pier"]
        if status.get("tracking") is not None:
            self.is_tracking = status["tracking"]
        if status.get("slewing") is not None:
            self.is_slewing = status["slewing"]
        return status
