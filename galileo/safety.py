"""Safety monitoring and watchdog service (SAFE-010 … SAFE-100)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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
        if self._require_user_confirm:
            return False
        return True

    # --- Advisory data sources (SAFE-050, SAFE-090, SAFE-100) -----------

    async def get_forecast_advisory(self) -> dict | None:
        if self._forecast_client is None:
            return None
        return await self._forecast_client.get_forecast()

    async def get_aurora_advisory(self) -> float:
        if self._kp_client is None:
            return 0.0
        return await self._kp_client.get_kp_index()

    async def get_smoke_advisory(self) -> float:
        if self._smoke_client is None:
            return 0.0
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
                timestamp=datetime.datetime.utcnow().isoformat(),
            ))


# ---------------------------------------------------------------------------
# Watchdog (SAFE-060)
# ---------------------------------------------------------------------------

class WatchdogService:
    """Heartbeat-timeout watchdog that parks mount and dome autonomously (SAFE-060)."""

    def __init__(self, mount=None, dome=None, timeout_s: float = 300.0) -> None:
        self._mount = mount
        self._dome = dome
        self.timeout_s = timeout_s
        self._last_heartbeat = asyncio.get_event_loop().time()
        self._task: asyncio.Task | None = None
        self._running = False

    def heartbeat(self) -> None:
        """Call periodically to prevent the watchdog from firing."""
        self._last_heartbeat = asyncio.get_event_loop().time()

    def start(self) -> None:
        self._running = True
        self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while self._running:
            await asyncio.sleep(min(self.timeout_s / 10, 5.0))
            elapsed = asyncio.get_event_loop().time() - self._last_heartbeat
            if elapsed >= self.timeout_s:
                logger.warning("Watchdog timeout — parking mount and closing dome")
                await self._emergency_park()
                return

    async def _emergency_park(self) -> None:
        if self._mount:
            try:
                await self._mount.park()
            except Exception:
                logger.exception("Watchdog: failed to park mount")
        if self._dome:
            try:
                await self._dome.close_shutter()
            except Exception:
                logger.exception("Watchdog: failed to close dome shutter")


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
            "forecast_days": 1,
        })
        url = f"https://api.open-meteo.com/v1/forecast?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception:
            return {}
