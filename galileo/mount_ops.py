# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""What the Mount page does to a mount and how it describes one, with no screen (EQP-MNT-010, EQP-MNT-020).

The Mount page used to hold all of this inside its widget-building function, so nothing could use a mount without
that page. This module is the part that does not draw anything:

* :class:`MountOps` runs each mount command against the adapter it is given and returns an :class:`Outcome` saying
  what happened, instead of showing a message. The caller decides how to tell the person (a status-bar message
  today); an engine or a remote client can use the same outcomes.
* :func:`describe_status` turns an adapter's status dictionary into the text the status display shows.
* :func:`target_ra_dec` / :func:`target_alt_az` turn the manual-coordinate fields into numbers.
* :func:`scan_mounts` lists the mounts a server offers.

``MountOps`` is given a callable that returns the adapter *now*, so the same code serves a mount the page
connected itself or one the device service holds. Behaviour, log lines and the failure texts are those of the
page they came from.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from galileo.coordinate_format import format_dms, format_hms
from galileo.device_ops import FAILED, forget, LIMIT, NOT_CONNECTED, OBSTRUCTED, OK, PARKED, UNSUPPORTED, Outcome, scan_devices
from galileo.exceptions import MountLimitError, MountParkedError, SlewObstructedError
from galileo.mount_limits import pier_side_text

logger = logging.getLogger(__name__)


class MountOps:
    def __init__(self, get_adapter: Callable[[], Any]) -> None:
        self._get = get_adapter

    def _call(self, name: str, call: Callable[[Any], Awaitable[Any]], failed: str, *, parked: bool = True,
              obstructed: bool = False, limit: bool = False, ok_log: str = "", ok_log_args: tuple = ()) -> Outcome:
        adapter = self._get()
        if adapter is None:
            return Outcome(False, NOT_CONNECTED)
        try:
            asyncio.run(call(adapter))
        except MountParkedError:
            if parked:
                return Outcome(False, PARKED)
            logger.exception("Mount %s failed", name)
        except SlewObstructedError:
            if obstructed:
                return Outcome(False, OBSTRUCTED)
            logger.exception("Mount %s failed", name)
        except MountLimitError as exc:
            if limit:
                return Outcome(False, LIMIT, str(exc))
            logger.exception("Mount %s failed", name)
        except Exception:
            logger.exception("Mount %s failed", name)
        else:
            if ok_log:
                logger.info(ok_log, *ok_log_args)
            return OK
        return Outcome(False, FAILED, failed)

    # -- slewing ---------------------------------------------------------------------------------------
    def slew_to_coordinates(self, ra_hours: float, dec_deg: float) -> Outcome:
        return self._call("slew-to-coordinates", lambda a: a.slew_to_coordinates(ra_hours * 15.0, dec_deg),
                          "Slew failed — see log.", obstructed=True, limit=True,
                          ok_log="Mount: slew requested to RA %.4fh Dec %.4f°", ok_log_args=(ra_hours, dec_deg))

    def slew_to_altaz(self, alt_deg: float, az_deg: float) -> Outcome:
        return self._call("slew-to-altaz", lambda a: a.slew_to_altaz(alt_deg, az_deg),
                          "Slew failed — see log.", obstructed=True, limit=True,
                          ok_log="Mount: slew requested to Alt %.4f° Az %.4f°", ok_log_args=(alt_deg, az_deg))

    def abort_slew(self) -> Outcome:
        outcome = self._call("stop", lambda a: a.abort_slew(), "", parked=False)
        if outcome.kind != NOT_CONNECTED:
            logger.info("Mount: Stop requested")
        return outcome

    # -- home, park, tracking ----------------------------------------------------------------------------
    def find_home(self) -> Outcome:
        return self._call("find_home", lambda a: a.find_home(), "Find Home failed — see log.",
                          ok_log="Mount: Find Home requested")

    def park(self) -> Outcome:
        return self._call("park", lambda a: a.park(), "Park failed — see log.", parked=False,
                          ok_log="Mount: Park requested")

    def unpark(self) -> Outcome:
        return self._call("unpark", lambda a: a.unpark(), "Unpark failed — see log.", parked=False,
                          ok_log="Mount: Unpark requested")

    def set_park_position(self) -> Outcome:
        return self._call("set park position", lambda a: a.set_park_position(), "Set Park Position failed — see log.",
                          ok_log="Mount: park position set to current position")

    def set_home_position(self) -> Outcome:
        adapter = self._get()
        if adapter is not None and not hasattr(adapter, "set_home_position"):
            return Outcome(False, UNSUPPORTED, "This driver can't set a home position.")
        return self._call("set home position", lambda a: a.set_home_position(), "Set Home Position failed — see log.",
                          ok_log="Mount: home position set to current position")

    def set_tracking(self, enabled: bool) -> Outcome:
        return self._call("set_tracking", lambda a: a.set_tracking(enabled), "Tracking change failed — see log.",
                          ok_log="Mount: tracking %s requested", ok_log_args=("on" if enabled else "off",))

    def set_tracking_rate(self, mode: str) -> Outcome:
        return self._call("set_tracking_rate_mode", lambda a: a.set_tracking_rate_mode(mode),
                          "Set tracking rate failed — see log.", parked=False,
                          ok_log="Mount: tracking rate set to %s", ok_log_args=(mode,))

    def set_axis_reversed(self, axis: int, reversed_: bool) -> Outcome:
        return self._call(f"axis {axis} reversal", lambda a: a.set_axis_reversed(axis, reversed_),
                          "The mount driver would not change its motion direction — see log.", parked=False)

    # -- reading -----------------------------------------------------------------------------------------
    def status(self) -> dict | None:
        """The adapter's status, or ``None`` when no mount is connected or it cannot be read."""
        adapter = self._get()
        if adapter is None:
            return None
        try:
            return asyncio.run(adapter.get_status())
        except Exception:
            logger.exception("Could not refresh mount status")
            return None

    def disconnect(self) -> bool:
        adapter = self._get()
        if adapter is None:
            return False
        try:
            asyncio.run(adapter.disconnect())
        except Exception:
            logger.exception("Could not disconnect Mount")
        forget(adapter)
        return True


# -- the status display ------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MountView:
    """Everything the status display and the buttons that depend on the status show."""

    name: str = "—"
    description: str = "—"
    driver_info: str = "—"
    driver_version: str = "—"
    site_latitude: str = "—"
    site_longitude: str = "—"
    site_elevation: str = "—"
    epoch: str = "—"
    sidereal_time: str = "—"
    right_ascension: str = "—"
    declination: str = "—"
    altitude: str = "—"
    azimuth: str = "—"
    side_of_pier: str = "—"
    tracking: str = "—"
    meridian_in: str = "—"
    pier_side: str = "Pier Side: —"
    park_status: str = "Park status: —"
    tracking_status: str = "Tracking: —"
    tracking_flag: bool | None = None        # whether the mount is tracking; None when it does not say
    at_park: bool | None = None
    park_enabled: bool = True                # the Park button
    unpark_enabled: bool = True              # the Unpark button


def describe_status(status: dict) -> MountView:
    tracking = status.get("tracking")
    lst, ra = status.get("sidereal_time"), status.get("right_ascension")
    elevation = status.get("site_elevation")
    at_park = status.get("at_park")
    rate = status.get("tracking_rate")
    if tracking is None:
        tracking_status = "Tracking: —"
    elif tracking:
        tracking_status = f"Tracking: On ({rate} rate)" if rate else "Tracking: On"
    else:
        tracking_status = "Tracking: Off" + (f" ({rate} rate selected)" if rate else "")
    return MountView(
        name=status.get("name") or "—", description=status.get("description") or "—",
        driver_info=status.get("driver_info") or "—", driver_version=status.get("driver_version") or "—",
        site_latitude=format_dms(status.get("site_latitude")), site_longitude=format_dms(status.get("site_longitude")),
        site_elevation="—" if elevation is None else f"{elevation:.1f} m",
        epoch=status.get("equatorial_system") or "—", sidereal_time=format_hms(lst),
        right_ascension=format_hms(ra), declination=format_dms(status.get("declination")),
        altitude=format_dms(status.get("altitude")), azimuth=format_dms(status.get("azimuth")),
        side_of_pier=status.get("side_of_pier") or "—",
        tracking="—" if tracking is None else ("Tracking" if tracking else "Stopped"),
        meridian_in=format_hms((ra - lst) % 24.0) if ra is not None and lst is not None else "—",
        pier_side="Pier Side: " + pier_side_text(status.get("side_of_pier")),
        park_status="Park status: —" if at_park is None else ("Park status: Parked" if at_park else "Park status: Unparked"),
        tracking_status=tracking_status, tracking_flag=bool(tracking) if tracking is not None else None,
        at_park=at_park, park_enabled=not at_park, unpark_enabled=at_park is not False)


# -- manual coordinates ------------------------------------------------------------------------------------------
def _signed(degrees: int, minutes: float, seconds: float) -> float:
    magnitude = abs(degrees) + minutes / 60.0 + seconds / 3600.0
    return -magnitude if degrees < 0 else magnitude


def target_ra_dec(ra: tuple[int, int, float], dec: tuple[int, int, float]) -> tuple[float, float]:
    """``(RA hours, Dec degrees)`` from the (h, m, s) and (d, m, s) fields."""
    return ra[0] + ra[1] / 60.0 + ra[2] / 3600.0, _signed(*dec)


def target_alt_az(alt: tuple[int, int, float], az: tuple[int, int, float]) -> tuple[float, float]:
    """``(Alt degrees, Az degrees)`` from the (d, m, s) fields."""
    return _signed(*alt), az[0] + az[1] / 60.0 + az[2] / 3600.0


# -- connecting --------------------------------------------------------------------------------------------------
def apply_site(adapter: Any, observatory: Any) -> None:
    """Give the adapter the Observatory's location before it connects."""
    if observatory is not None:
        adapter.site_lat = getattr(observatory, "latitude", None)
        adapter.site_lon = getattr(observatory, "longitude", None)
        adapter.site_elevation = getattr(observatory, "elevation_m", None)


def connect_mount(make_adapter: Callable[..., Any], driver: str, server: str, port: int, device_name: str,
                  observatory: Any = None, pier: Any = None) -> Any | None:
    """Build the mount's adapter with *make_adapter* (``(category, driver, server, port, device_name)``, so the page's
    own factory or the device service's serves alike), give it the Observatory's location and connect it.
    Returns the connected adapter, or ``None`` after logging why it could not. With the device service on (and a *pier*
    to hold it under) the service builds and holds it instead of *make_adapter*."""
    from galileo import desktop_devices
    from galileo.core.devices import DeviceCategory
    try:
        if pier is not None and desktop_devices.enabled():
            adapter = desktop_devices.connect(pier, DeviceCategory.MOUNT, "primary", driver, server, port, device_name,
                                              lambda a: apply_site(a, observatory))
            if adapter is None:
                raise RuntimeError("the device service could not connect it")
            return adapter
        adapter = make_adapter(DeviceCategory.MOUNT, driver, server, port, device_name)
        apply_site(adapter, observatory)
        asyncio.run(adapter.connect())
    except Exception:
        logger.exception("Could not connect to Mount %r at %s:%d", device_name, server, port)
        return None
    return adapter


def scan_mounts(driver: str, server: str, port: int) -> list[str]:
    """The mounts the server at *server*:*port* offers through *driver* (``"INDI"`` or Alpaca); empty on failure."""
    from galileo.core.devices import DeviceCategory
    return scan_devices(DeviceCategory.MOUNT, driver, server, port) or []


__all__ = [
    "FAILED", "LIMIT", "NOT_CONNECTED", "OBSTRUCTED", "OK", "PARKED", "UNSUPPORTED", "MountOps", "MountView", "Outcome",
    "apply_site", "connect_mount", "describe_status", "scan_mounts", "target_alt_az", "target_ra_dec",
]
