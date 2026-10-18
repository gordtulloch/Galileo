# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""INDI adapter(s) for mount devices."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, ClassVar

from galileo.adapters import indi_client as ic
from galileo.adapters.indi._base import IndiAdapter
from galileo.core.capabilities import DeviceCapabilities
from galileo.core.devices import DeviceCategory
from galileo.core.slew_guard import get_slew_guard
from galileo.exceptions import MountParkedError

logger = logging.getLogger(__name__)


class IndiMountAdapter(IndiAdapter):
    """INDI telescope adapter (``INDI::Telescope`` standard properties).
    Coordinates are the mount's ``EQUATORIAL_EOD_COORD`` (JNow), matching
    what the Alpaca adapter hands to ASCOM."""

    # Galileo's names -> INDI TELESCOPE_TRACK_MODE elements.
    _TRACK_MODES: ClassVar = {"Sidereal": "TRACK_SIDEREAL", "Lunar": "TRACK_LUNAR",
                    "Solar": "TRACK_SOLAR", "King": "TRACK_KING"}
    # Speeds for jogging, slowest first: (max deg/s, INDI TELESCOPE_SLEW_RATE element).
    _SLEW_RATES = ((0.02, "SLEW_GUIDE"), (0.2, "SLEW_CENTERING"), (2.0, "SLEW_FIND"), (math.inf, "SLEW_MAX"))

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.MOUNT, host, port, **kwargs)
        self.ra = 0.0
        self.dec = 0.0
        self.altitude = 0.0
        self.azimuth = 0.0
        self.pier_side = "East"
        self.is_tracking = False
        self.is_slewing = False
        self.site_lat: float | None = None
        self.site_lon: float | None = None
        self.site_elevation: float | None = None

    def get_capabilities(self) -> DeviceCapabilities:
        if self._client is None:
            return DeviceCapabilities(can_park=True, can_slew=True, can_sync=True)
        return DeviceCapabilities(
            can_park=self._has("TELESCOPE_PARK"),
            can_slew=self._has("EQUATORIAL_EOD_COORD") or self._has("HORIZONTAL_COORD"),
            can_sync=self._has("ON_COORD_SET"),
            can_track_non_sidereal=self._has("TELESCOPE_TRACK_RATE"),
        )

    def _on_connected(self) -> None:
        self._sync_site_and_time()

    def _sync_site_and_time(self) -> None:
        """Push current UTC time and (if configured) site coordinates to the
        mount right after connection so goto, meridian-flip limits, and
        sidereal time are computed from accurate values."""
        if self._client is None:
            return
        # Shares push_context's send-and-wait path (and its de-duplication with
        # the UI's own post-connect push): LX200 OnStep logs "Error setting UTC
        # Offset" / "site longitude" when the same sets arrive back to back.
        # Runs on a worker thread (asyncio.to_thread), so it has no loop of its own.
        asyncio.run(self.push_context(self.site_lat, self.site_lon, self.site_elevation))

    def _refuse_if_parked(self, command: str) -> None:
        """Movement commands must not reach a parked mount. Checked against the
        driver's live ``TELESCOPE_PARK`` state, so a park done outside Galileo
        is honoured too."""
        if self._sw("TELESCOPE_PARK", "PARK"):
            logger.warning("Not sending %s to INDI mount %r: it is parked", command, self.device_name)
            raise MountParkedError(f"The mount is parked, so {command} was not sent — unpark it first.")

    async def slew_to_coordinates(self, ra: float, dec: float) -> None:
        self._refuse_if_parked("slew_to_coordinates")
        (getattr(self, "slew_guard", None) or get_slew_guard()).check_radec(ra, dec)
        self._log_interaction("slew_to_coordinates", ra=ra, dec=dec)
        self._select("ON_COORD_SET", "TRACK")
        self._set_num("EQUATORIAL_EOD_COORD", {"RA": ra / 15.0, "DEC": dec})
        self.ra, self.dec = ra, dec

    async def slew_to_altaz(self, alt: float, az: float) -> None:
        self._refuse_if_parked("slew_to_altaz")
        (getattr(self, "slew_guard", None) or get_slew_guard()).check_altaz(alt, az)
        self._log_interaction("slew_to_altaz", alt=alt, az=az)
        self._set_num("HORIZONTAL_COORD", {"ALT": alt, "AZ": az})
        self.altitude, self.azimuth = alt, az

    async def abort_slew(self) -> None:
        self._log_interaction("abort_slew")
        self._set_sw("TELESCOPE_ABORT_MOTION", {"ABORT": True})

    async def park(self) -> None:
        self._log_interaction("park")
        self._set_sw("TELESCOPE_PARK", {"PARK": True, "UNPARK": False})

    async def unpark(self) -> None:
        self._log_interaction("unpark")
        self._set_sw("TELESCOPE_PARK", {"PARK": False, "UNPARK": True})

    async def find_home(self) -> None:
        self._refuse_if_parked("find_home")
        self._log_interaction("find_home")
        self._select("TELESCOPE_HOME", "FIND")

    async def move_axis(self, axis: int, rate: float) -> None:
        """Continuous jog, same contract as the Alpaca adapter's ``MoveAxis``:
        axis 0 is RA (positive = east), axis 1 is Dec (positive = north),
        ``rate`` in deg/s, ``0`` stops that axis. INDI drives jogging with
        direction switches plus a discrete slew-rate selector, so the
        requested speed is snapped to the nearest slower standard rate.
        Stopping an axis (``rate=0``) is always allowed."""
        if rate:
            self._refuse_if_parked("move_axis")
        self._log_interaction("move_axis", axis=axis, rate=rate)
        if axis == 0:
            prop, positive, negative = "TELESCOPE_MOTION_WE", "MOTION_EAST", "MOTION_WEST"
        else:
            prop, positive, negative = "TELESCOPE_MOTION_NS", "MOTION_NORTH", "MOTION_SOUTH"
        if rate and self._has("TELESCOPE_SLEW_RATE"):
            speed = next(el for limit, el in self._SLEW_RATES if abs(rate) <= limit)
            if speed in self._require("TELESCOPE_SLEW_RATE").elements:
                self._select("TELESCOPE_SLEW_RATE", speed)
        self._set_sw(prop, {positive: rate > 0, negative: rate < 0})

    async def set_tracking(self, enabled: bool) -> None:
        if enabled:
            self._refuse_if_parked("set_tracking")
        self._log_interaction("set_tracking", enabled=enabled)
        self._set_sw("TELESCOPE_TRACK_STATE", {"TRACK_ON": enabled, "TRACK_OFF": not enabled})
        self.is_tracking = enabled

    async def set_tracking_rate(self, ra_rate_arcsec_s: float, dec_rate_arcsec_s: float) -> None:
        self._log_interaction("set_tracking_rate", ra_rate_arcsec_s=ra_rate_arcsec_s, dec_rate_arcsec_s=dec_rate_arcsec_s)
        self._select("TELESCOPE_TRACK_MODE", "TRACK_CUSTOM")
        self._set_num("TELESCOPE_TRACK_RATE", {"TRACK_RATE_RA": ra_rate_arcsec_s, "TRACK_RATE_DE": dec_rate_arcsec_s})
        self._properties.update({"RA_RATE": ra_rate_arcsec_s, "DEC_RATE": dec_rate_arcsec_s})

    async def set_tracking_rate_mode(self, mode: str) -> None:
        self._log_interaction("set_tracking_rate_mode", mode=mode)
        self._select("TELESCOPE_TRACK_MODE", self._TRACK_MODES.get(mode, "TRACK_SIDEREAL"))

    async def sync_to_coordinates(self, ra: float, dec: float) -> None:
        self._refuse_if_parked("sync_to_coordinates")
        self._log_interaction("sync_to_coordinates", ra=ra, dec=dec)
        self._select("ON_COORD_SET", "SYNC")
        self._set_num("EQUATORIAL_EOD_COORD", {"RA": ra / 15.0, "DEC": dec})
        self.ra, self.dec = ra, dec

    async def get_status(self) -> dict:
        """Live status from the standard ``INDI::Telescope`` properties. A
        property the driver doesn't define reports ``None`` (the UI treats
        that as "not available")."""
        longitude = self._num("GEOGRAPHIC_COORD", "LONG")
        if longitude is not None and longitude > 180.0:
            longitude -= 360.0  # INDI reports 0..360° east; ASCOM/UI use -180..180
        side = "PIER_WEST" if self._sw("TELESCOPE_PIER_SIDE", "PIER_WEST") else (
            "PIER_EAST" if self._sw("TELESCOPE_PIER_SIDE", "PIER_EAST") else None)
        status: dict[str, Any] = {
            **self._driver_info(),
            "site_latitude": self._num("GEOGRAPHIC_COORD", "LAT"),
            "site_longitude": longitude,
            "site_elevation": self._num("GEOGRAPHIC_COORD", "ELEV"),
            "sidereal_time": self._num("TIME_LST", "LST"),
            "equatorial_system": "JNOW" if self._has("EQUATORIAL_EOD_COORD") else None,
            "right_ascension": self._num("EQUATORIAL_EOD_COORD", "RA"),
            "declination": self._num("EQUATORIAL_EOD_COORD", "DEC"),
            "altitude": self._num("HORIZONTAL_COORD", "ALT"),
            "azimuth": self._num("HORIZONTAL_COORD", "AZ"),
            "side_of_pier": {"PIER_WEST": "West", "PIER_EAST": "East"}.get(side) if side else None,
            "tracking": self._sw("TELESCOPE_TRACK_STATE", "TRACK_ON"),
            "slewing": (self._state("EQUATORIAL_EOD_COORD") == ic.BUSY) if self._has("EQUATORIAL_EOD_COORD") else None,
            "at_park": self._sw("TELESCOPE_PARK", "PARK"),
            "tracking_rate": next((n for n, el in self._TRACK_MODES.items() if self._sw("TELESCOPE_TRACK_MODE", el)),
                                  "Custom" if self._sw("TELESCOPE_TRACK_MODE", "TRACK_CUSTOM") else None),
        }
        if status["right_ascension"] is not None:
            self.ra = status["right_ascension"] * 15.0
        if status["declination"] is not None:
            self.dec = status["declination"]
        if status["altitude"] is not None:
            self.altitude = status["altitude"]
        if status["azimuth"] is not None:
            self.azimuth = status["azimuth"]
        if status["side_of_pier"] is not None:
            self.pier_side = status["side_of_pier"]
        if status["tracking"] is not None:
            self.is_tracking = status["tracking"]
        if status["slewing"] is not None:
            self.is_slewing = status["slewing"]
        return status
