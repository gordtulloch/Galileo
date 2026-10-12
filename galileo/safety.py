# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Safety monitoring and watchdog service (SAFE-010 … SAFE-100)."""

from __future__ import annotations

import asyncio
import logging
import operator
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class SafetyState(Enum):
    SAFE = "safe"
    WARNING = "warning"
    ABORTED = "aborted"
    IDLE = "idle"


@dataclass
class SafetyPolicy:
    """Per-Observatory safety response policy (SAFE-030)."""
    abort_on_unsafe: bool = True
    warn_on_borderline: bool = True


class SafetyMonitorService:
    """Polls a safety monitor device and acts on unsafe conditions (SAFE-010 … SAFE-100)."""

    def __init__(self, monitor=None, event_bus=None, policy: SafetyPolicy | None = None) -> None:
        self._monitor = monitor
        self._event_bus = event_bus
        self.policy = policy or SafetyPolicy()
        self._state_value = SafetyState.IDLE  # backing store
        self._require_user_confirm = False
        self._sequences: list = []
        self._mounts: list = []
        self._forecast_client = None
        self._kp_client = None
        self._smoke_client = None
        self.last_abort_trigger: str = ""

    @property
    def state(self) -> SafetyState:
        return self._state_value

    @state.setter
    def state(self, value: SafetyState) -> None:
        self._state_value = value

    # Alias so tests can set safety_service._state directly
    @property
    def _state(self) -> SafetyState:
        return self._state_value

    @_state.setter
    def _state(self, value: SafetyState) -> None:
        self._state_value = value

    # --- Configuration ---------------------------------------------------

    def register_sequence(self, seq) -> None:
        self._sequences.append(seq)

    def register_mount(self, mount) -> None:
        self._mounts.append(mount)

    def set_forecast_client(self, client) -> None:
        self._forecast_client = client

    def set_kp_client(self, client) -> None:
        self._kp_client = client

    def set_smoke_client(self, client) -> None:
        self._smoke_client = client

    # --- Polling (SAFE-010, SAFE-070, SAFE-080) --------------------------

    async def poll_and_react(self) -> None:
        """Poll the monitor; abort sequences and park mounts if unsafe."""
        await self._monitor.poll()

        if not self._monitor.is_safe:
            self.state = SafetyState.ABORTED
            self.last_abort_trigger = f"SafetyMonitor:{getattr(self._monitor, 'name', '')}"

            if self.policy.abort_on_unsafe:
                await asyncio.gather(
                    *(seq.abort() for seq in self._sequences),
                    return_exceptions=True,
                )
                await asyncio.gather(
                    *(mount.park() for mount in self._mounts),
                    return_exceptions=True,
                )

            if self._event_bus:
                from galileo.bus import SafetyUnsafeEvent
                self._event_bus.publish(SafetyUnsafeEvent(
                    source=getattr(self._monitor, "name", ""),
                    explanation=getattr(self._monitor, "explanation", ""),
                ))

    # --- Resume guard (SAFE-040) -----------------------------------------

    async def can_resume(self) -> bool:
        if self.state != SafetyState.ABORTED:
            return True
        if not self._monitor.is_safe:
            return False
        return not self._require_user_confirm

    # --- Advisory data sources (SAFE-050, SAFE-090, SAFE-100) -----------

    async def get_forecast_advisory(self, latitude: float = 0.0, longitude: float = 0.0) -> dict | None:
        if self._forecast_client is None:
            return None
        return await self._forecast_client.get_forecast(latitude, longitude)

    async def get_aurora_advisory(self) -> float | None:
        """Current Kp index, or ``None`` when no client is configured —
        distinct from an actual reading of 0 (a quiet night), so a caller
        such as What's Up Tonight (WUT-100) can tell "no data" apart from
        "no aurora activity" rather than treating the two the same."""
        if self._kp_client is None:
            return None
        return await self._kp_client.get_kp_index()

    async def get_smoke_advisory(self) -> float | None:
        """Current smoke/transparency AQI estimate, or ``None`` when no
        client is configured — same "no data" vs. "measured clear"
        distinction as :meth:`get_aurora_advisory` (WUT-100)."""
        if self._smoke_client is None:
            return None
        return await self._smoke_client.get_smoke_aqi()


# ---------------------------------------------------------------------------
# Weather logging (SAFE-020)
# ---------------------------------------------------------------------------

class WeatherLoggingService:
    """Logs weather readings alongside session history (SAFE-020)."""

    def __init__(self, station=None, event_bus=None) -> None:
        self._station = station
        self._event_bus = event_bus

    async def poll_and_log(self) -> None:
        await self._station.poll()
        if self._event_bus:
            from galileo.bus import WeatherReadingEvent
            import datetime
            self._event_bus.publish(WeatherReadingEvent(
                source=getattr(self._station, "name", ""),
                timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
            ))


# ---------------------------------------------------------------------------
# Per-reading weather safety rules (EQP-WX-020)
# ---------------------------------------------------------------------------
#
# A Weather Station device (e.g. indi-argentweather's ADS-WS1, or
# indi-hydreon's RG-11 rain sensor) is a different device category from a
# Safety Monitor (SAFE-070/SAFE-080) — it has no SAFE/NOT-SAFE state of its
# own in Galileo's device model, only readings. This lets the user annotate
# which of those readings matter for safety and what crossing into "unsafe"
# looks like for each (e.g. Rain >= 1, Wind Speed >= 20 km/h), for display on
# the Equipment > Weather screen. Deliberately advisory-only, the same trust
# tier as the SAFE-050 internet forecast: it never publishes an unsafe-state
# event and never drives an automated abort by itself — only a connected
# Safety Monitor device is authoritative for SAFE-010 (see galileo.safety
# module docstring / SDD 4.16's trust-tier note).

#: Comparison operators a WeatherSafetyRule's *operator* may be.
UNSAFE_OPERATORS: tuple[str, ...] = (">=", ">", "<=", "<", "==", "!=")

_OPERATOR_FUNCS = {
    ">=": operator.ge, ">": operator.gt, "<=": operator.le,
    "<": operator.lt, "==": operator.eq, "!=": operator.ne,
}

#: Known Weather Station reading keys (WeatherController.get_readings()) ->
#: (display label, unit), covering both reference drivers named in EQP-WX-020
#: (indi-argentweather's ADS-WS1, indi-hydreon's RG-11) plus Alpaca
#: ObservingConditions. Not exhaustive — a rule may name any reading key the
#: connected backend actually reports, even one not listed here.
WEATHER_PARAMETER_INFO: dict[str, tuple[str, str]] = {
    "temperature": ("Outdoor Temperature", "°C"),
    "humidity": ("Outdoor Humidity", "%"),
    "dew_point": ("Dew Point", "°C"),
    "pressure": ("Barometric Pressure", "mbar"),
    "wind_speed": ("Wind Speed", "km/h"),
    "wind_gust": ("Wind 1-min Avg", "km/h"),
    "rain_rate": ("Rain Today", "mm"),
    "rain": ("Rain (now)", "bool"),
    "cloud_cover": ("Cloud Cover", "%"),
}


@dataclass
class WeatherSafetyRule:
    """One user-configured rule for a single Weather Station reading
    (EQP-WX-020): whether *parameter* counts toward the Weather screen's
    safety verdict, and what reading crosses it into "unsafe" — e.g.
    ``WeatherSafetyRule("rain_rate", operator=">", threshold=0.0)`` ("Rain is
    YES") or ``WeatherSafetyRule("wind_speed", operator=">=", threshold=20.0)``
    ("Wind >= 20 km/h")."""

    parameter: str
    label: str = ""
    unit: str = ""
    safety_related: bool = False
    operator: str = ">="
    threshold: float = 0.0

    def __post_init__(self) -> None:
        if self.operator not in UNSAFE_OPERATORS:
            raise ValueError(f"Unknown weather safety operator {self.operator!r}")
        if not self.label or not self.unit:
            default_label, default_unit = WEATHER_PARAMETER_INFO.get(self.parameter, (self.parameter, ""))
            self.label = self.label or default_label
            self.unit = self.unit or default_unit

    def describe(self) -> str:
        """Human-readable form of this rule's unsafe condition, e.g. ``"Wind Speed >= 20 km/h"``."""
        unit_suffix = f" {self.unit}" if self.unit and self.unit != "bool" else ""
        return f"{self.label} {self.operator} {self.threshold:g}{unit_suffix}"


def default_weather_safety_rules() -> list[WeatherSafetyRule]:
    """Starter rules shown on an unconfigured Pier's Weather screen — one row
    per :data:`WEATHER_PARAMETER_INFO` entry, with only the two measures
    EQP-WX-020 itself gives as examples (Rain, Wind Speed) pre-enabled, at
    conservative astronomy-friendly thresholds. The user is free to enable,
    disable, or retune any row from there; this only seeds first use."""
    defaults: dict[str, tuple[bool, str, float]] = {
        "rain": (True, ">", 0.0),
        "wind_speed": (True, ">=", 20.0),
        "wind_gust": (False, ">=", 30.0),
        "humidity": (False, ">=", 90.0),
        "cloud_cover": (False, ">=", 80.0),
    }
    rules = []
    for parameter in WEATHER_PARAMETER_INFO:
        safety_related, op, threshold = defaults.get(parameter, (False, ">=", 0.0))
        rules.append(WeatherSafetyRule(
            parameter=parameter, safety_related=safety_related, operator=op, threshold=threshold,
        ))
    return rules


@dataclass
class WeatherSafetyStatus:
    """Result of evaluating a Weather Station's current readings against its
    configured :class:`WeatherSafetyRule`\\ s (EQP-WX-020)."""

    is_safe: bool = True
    violations: list[str] = field(default_factory=list)


def evaluate_weather_safety(readings: dict, rules: list[WeatherSafetyRule]) -> WeatherSafetyStatus:
    """Evaluate *rules* (a Pier's saved weather safety rules) against
    *readings* (``WeatherController.get_readings()``) and return the overall
    verdict plus which rules tripped. Advisory/display-only (EQP-WX-020) —
    the caller must not treat this as an automated-abort trigger; see this
    module's note above. A rule not marked ``safety_related``, or whose
    reading is currently unavailable (``None``), is skipped rather than
    counted as either safe or unsafe."""
    violations = []
    for rule in rules:
        if not rule.safety_related:
            continue
        value = readings.get(rule.parameter)
        if value is None:
            continue
        try:
            unsafe = _OPERATOR_FUNCS[rule.operator](value, rule.threshold)
        except TypeError:
            continue
        if unsafe:
            violations.append(rule.describe())
    return WeatherSafetyStatus(is_safe=not violations, violations=violations)


class LiveSafetyMonitor:
    """A Pier's live safety verdict for the scheduler (SCHED-060), backed by a callable
    returning ``(any device connected, safe, reasons)`` — the Equipment > Safety page's
    ``evaluate``. Re-evaluated on every access, so it follows devices connecting and
    disconnecting without being re-registered. With no safety device connected it reports
    safe (there is nothing to gate on); an evaluation failure is treated as unsafe."""

    def __init__(self, evaluate) -> None:
        self._evaluate = evaluate

    def _status(self) -> tuple[bool, bool, list[str]]:
        try:
            connected, safe, reasons = self._evaluate()
        except Exception:
            logger.exception("Safety evaluation failed; treating conditions as unsafe")
            return True, False, ["the safety evaluation failed"]
        return bool(connected), bool(safe), list(reasons)

    @property
    def is_safe(self) -> bool:
        connected, safe, _ = self._status()
        return safe or not connected

    @property
    def reason(self) -> str:
        connected, safe, reasons = self._status()
        if safe or not connected:
            return ""
        return "; ".join(reasons) or "the safety monitor reports unsafe conditions"


# ---------------------------------------------------------------------------
# Watchdog (SAFE-060)
# ---------------------------------------------------------------------------

class WatchdogService:
    """Heartbeat-timeout watchdog that parks the mount and closes the dome (SAFE-060).

    It runs on its **own daemon thread**, not on the application's event loop, so it still
    fires when the Qt/asyncio loop is hung or blocked — which is the whole point: a
    watchdog scheduled on the loop it is watching would hang with it. The application calls
    :meth:`heartbeat` from its event loop; if no heartbeat arrives for *timeout_s* seconds
    the watchdog trips once: it parks the mount, then closes the dome shutter (each on a
    private event loop in the watchdog thread), publishes a ``SafetyUnsafeEvent`` on the
    bus and invokes the *on_trip* callbacks (notifications, UI). It does not protect
    against the whole process being killed; where an INDI server is in use the server-side
    ``indi_watchdog`` driver covers that (SDD 4.16).

    *mount* / *dome* may be devices or zero-argument callables returning the device that is
    connected **now** (``None`` if none), so devices connected after start-up are covered.
    """

    #: Longest a single park/close call may take before the watchdog moves on (seconds).
    ACTION_TIMEOUT_S = 120.0

    def __init__(self, mount=None, dome=None, timeout_s: float = 300.0, event_bus=None,
                 on_trip=None) -> None:
        self._mount = mount
        self._dome = dome
        self.timeout_s = timeout_s
        self._event_bus = event_bus
        self._on_trip: list = [on_trip] if on_trip else []
        self._lock = threading.Lock()
        self._last_heartbeat = time.monotonic()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._tripped = False
        self.trip_detail: str = ""

    # --- control ---------------------------------------------------------

    def add_trip_handler(self, handler) -> None:
        """*handler(detail: str)* is called, on the watchdog thread, after a trip."""
        self._on_trip.append(handler)

    def heartbeat(self) -> None:
        """Call periodically (from any thread) to prevent the watchdog from firing."""
        with self._lock:
            self._last_heartbeat = time.monotonic()

    def start(self) -> None:
        """Arm the watchdog (a fresh heartbeat is recorded). No-op when already running."""
        if self.running:
            return
        self._stop_event.clear()
        self._tripped = False
        self.trip_detail = ""
        self.heartbeat()
        self._thread = threading.Thread(target=self._run, name="galileo-watchdog", daemon=True)
        self._thread.start()

    def stop_sync(self, join_timeout: float = 5.0) -> None:
        """Disarm and wait (briefly) for the thread to exit. Safe to call when not running."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(join_timeout)
        self._thread = None

    async def stop(self) -> None:
        await asyncio.to_thread(self.stop_sync)

    # --- status ----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def status(self) -> str:
        """``"tripped"``, ``"armed"`` (running) or ``"stopped"``."""
        if self._tripped:
            return "tripped"
        return "armed" if self.running else "stopped"

    @property
    def seconds_since_heartbeat(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_heartbeat

    # --- thread body -----------------------------------------------------

    def _run(self) -> None:
        interval = max(0.005, min(self.timeout_s / 20, 5.0))
        while not self._stop_event.wait(interval):
            if self.seconds_since_heartbeat >= self.timeout_s:
                self._trip()
                return

    def _trip(self) -> None:
        detail = (f"No application heartbeat for {self.seconds_since_heartbeat:.0f} s "
                  f"(limit {self.timeout_s:g} s): parking the mount and closing the dome.")
        logger.warning("Watchdog timeout — %s", detail)
        self._tripped = True
        self.trip_detail = detail
        self._emergency_park()
        if self._event_bus:
            try:
                from galileo.bus import SafetyUnsafeEvent
                self._event_bus.publish(SafetyUnsafeEvent(source="Watchdog", explanation=detail))
            except Exception:
                logger.exception("Watchdog: failed to publish the unsafe event")
        for handler in list(self._on_trip):
            try:
                handler(detail)
            except Exception:
                logger.exception("Watchdog: trip handler raised")

    @staticmethod
    def _resolve(device):
        return device() if callable(device) and not hasattr(device, "park") and not hasattr(device, "close_shutter") else device

    def _emergency_park(self) -> None:
        mount = self._safe_resolve(self._mount)
        dome = self._safe_resolve(self._dome)
        if mount is not None:
            self._run_action("park the mount", mount.park)
        if dome is not None:
            self._run_action("close the dome shutter", dome.close_shutter)

    def _safe_resolve(self, device):
        try:
            return self._resolve(device)
        except Exception:
            logger.exception("Watchdog: could not resolve a device")
            return None

    def _run_action(self, what: str, call) -> None:
        async def _go():
            result = call()
            if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
                await asyncio.wait_for(result, self.ACTION_TIMEOUT_S)
        try:
            asyncio.run(_go())
        except Exception:
            logger.exception("Watchdog: failed to %s", what)


# ---------------------------------------------------------------------------
# Open-Meteo client (EXT-130)
# ---------------------------------------------------------------------------

class OpenMeteoClient:
    """Queries the Open-Meteo API for geocoding and weather forecasts (EXT-130)."""

    requires_user_consent: bool = True

    async def geocode(self, place_name: str) -> dict:
        from galileo.planning.sky_atlas import geocode_location
        return await geocode_location(place_name)

    async def get_forecast(self, latitude: float = 0.0, longitude: float = 0.0) -> dict:
        import json
        import urllib.request
        import urllib.parse
        params = urllib.parse.urlencode({
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "precipitation,cloudcover,windspeed_10m",
            "forecast_days": 2,       # tonight spans today's evening into tomorrow's morning
            "timezone": "auto",       # hourly times in the site's local time, so night hours can be picked out
        })
        url = f"https://api.open-meteo.com/v1/forecast?{params}"
        def _fetch() -> dict:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return json.loads(resp.read())
        try:
            # Off the event loop: this runs inside the safety poll, which must stay responsive
            # even when the forecast service is slow.
            return await asyncio.to_thread(_fetch)
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Aurora (SAFE-090) and smoke (SAFE-100) advisory clients
# ---------------------------------------------------------------------------
# Ported from the author's MCP project (mcpAurora/mcpSmoke, themselves derived from indi-allsky),
# using only the standard library so they add no dependencies (no numpy/shapely/lxml).

_KP_INDEX_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
_HMS_KML_URL = ("https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/KML/"
                "{now:%Y}/{now:%m}/hms_smoke{now:%Y}{now:%m}{now:%d}.kml")

# HMS smoke density → AQI-equivalent, so the existing smoke-AQI ranking scale (good <= 50,
# fully degraded at 200) applies. HMS gives only three density bands, not a measured AQI.
_HMS_FOLDER_AQI = (("Smoke (Heavy)", 200.0), ("Smoke (Medium)", 125.0), ("Smoke (Light)", 75.0))
_HMS_CLEAR_AQI = 25.0


def _http_get(url: str) -> bytes:
    import urllib.request
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read()


class NoaaKpClient:
    """Latest planetary Kp index from NOAA SWPC (SAFE-090). Global, so no location needed."""

    async def get_kp_index(self) -> float | None:
        import json
        try:
            rows = json.loads(await asyncio.to_thread(_http_get, _KP_INDEX_URL))
            # First row is the column header; the last row is the most recent 3-hour value.
            return float(rows[-1][1])
        except Exception:
            logger.debug("NOAA Kp index unavailable", exc_info=True)
            return None


def _segments_intersect_box(poly: list[tuple[float, float]], box: tuple[float, float, float, float]) -> bool:
    """Whether a polygon (lon, lat vertices) overlaps an axis-aligned (min_lon, min_lat,
    max_lon, max_lat) box: any vertex inside the box, any box corner inside the polygon,
    or any polygon edge crossing a box edge."""
    min_x, min_y, max_x, max_y = box
    if len(poly) < 3:
        return False
    if any(min_x <= x <= max_x and min_y <= y <= max_y for x, y in poly):
        return True

    def inside(px: float, py: float) -> bool:
        hit = False
        for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
            if (y1 > py) != (y2 > py) and px < (x2 - x1) * (py - y1) / (y2 - y1) + x1:
                hit = not hit
        return hit

    corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
    if any(inside(x, y) for x, y in corners):
        return True

    def ccw(a, b, c) -> bool:
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    def cross(a, b, c, d) -> bool:
        return ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d)

    for p1, p2 in zip(poly, poly[1:] + poly[:1], strict=True):
        for c1, c2 in zip(corners, corners[1:] + corners[:1], strict=True):
            if cross(p1, p2, c1, c2):
                return True
    return False


class NoaaSmokeClient:
    """Wildfire-smoke estimate for a location from NOAA's Hazard Mapping System (SAFE-100).

    HMS covers North America only (northern + western hemisphere); elsewhere this returns
    ``None`` ("no data"). Smoke within ~0.5° (~35 miles) of the site counts."""

    def __init__(self, latitude: float, longitude: float) -> None:
        self.latitude = latitude
        self.longitude = longitude

    async def get_smoke_aqi(self) -> float | None:
        if not (self.latitude > 0 and self.longitude < 0):
            return None
        import datetime
        try:
            url = _HMS_KML_URL.format(now=datetime.datetime.now(datetime.UTC))
            return await asyncio.to_thread(self._rate, await asyncio.to_thread(_http_get, url))
        except Exception:
            logger.debug("NOAA HMS smoke data unavailable", exc_info=True)
            return None

    def _rate(self, kml: bytes) -> float | None:
        import xml.etree.ElementTree as ET
        KML = "http://www.opengis.net/kml/2.2"
        root = ET.fromstring(kml)
        box = (self.longitude - 0.5, self.latitude - 0.5, self.longitude + 0.5, self.latitude + 0.5)
        found_folder = False
        for folder_name, aqi in _HMS_FOLDER_AQI:  # heaviest first: first match wins
            folder = next((f for f in root.iter(f"{{{KML}}}Folder")
                           if folder_name in "".join(f.itertext())), None)
            if folder is None:
                continue
            found_folder = True
            for coords in folder.iter(f"{{{KML}}}coordinates"):
                poly = []
                for line in (coords.text or "").split():
                    lon, lat = line.split(",")[:2]
                    poly.append((float(lon), float(lat)))
                if _segments_intersect_box(poly, box):
                    return aqi
        return _HMS_CLEAR_AQI if found_folder else None
