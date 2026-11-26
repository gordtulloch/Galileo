# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SAFE — Safety & Weather Monitoring (TC-SAFE-010 … TC-SAFE-100)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def safety_service(mock_safety_monitor, event_bus):
    safe_mod = pytest.importorskip("galileo.safety")
    return safe_mod.SafetyMonitorService()


def _reports_park(mount, parks: bool = True):
    """Make a mock mount report its park state: unparked until ``park`` is called (never, if not *parks*)."""
    state = {"at_park": False}

    async def park():
        state["at_park"] = parks

    async def get_status():
        return dict(state)

    mount.park = AsyncMock(side_effect=park)
    mount.get_status = get_status
    return mount


# ---------------------------------------------------------------------------
# A fake site for the protective stop
# ---------------------------------------------------------------------------

class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _SiteMount:
    def __init__(self, order, name, parks=True):
        self.order, self.name, self.parks, self.at_park = order, name, parks, False

    async def get_status(self):
        return {"at_park": self.at_park}

    async def park(self):
        self.order.append(f"park {self.name}")
        self.at_park = self.parks


class _Dome:
    def __init__(self, order):
        self.order, self.shutter_state = order, "Open"

    async def get_status(self):
        return {"shutter_state": self.shutter_state}

    async def close_shutter(self):
        self.order.append("close roof")
        self.shutter_state = "Closed"

    async def park(self):
        pass


class _SafetyDevice:
    is_connected = True

    def __init__(self):
        self.is_safe, self.explanation, self.fail = True, "", False

    async def poll(self):
        if self.fail:
            raise OSError("no answer")


class _Guider:
    def __init__(self, order):
        self.order = order

    async def stop_guiding(self):
        self.order.append("stop guiding")


def _world(monkeypatch, *, parks=(True, True), settings=None, store=None):
    """A two-Pier Observatory under one roof, watched by a supervisor with a fake clock."""
    from types import SimpleNamespace

    from galileo import roof as roof_mod
    from galileo import safety_supervisor as ss
    monkeypatch.setattr(roof_mod, "PARK_TIMEOUT_S", 0.1)
    monkeypatch.setattr(roof_mod, "PARK_POLL_S", 0.01)
    order: list[str] = []
    mounts = [("A", _SiteMount(order, "A", parks[0])), ("B", _SiteMount(order, "B", parks[1]))]
    dome, device, clock, messages, events = _Dome(order), _SafetyDevice(), _Clock(), [], []
    site = ss.Site(sources=[ss.Source(key="m", name="Rain sensor", kind="safety_monitor", adapter=device)],
                   mounts=mounts, guiders=[("A", _Guider(order))], roofs=[ss.Roof("the roof", dome, mounts)])
    options = settings or ss.SafetySettings()
    supervisor = ss.SafetySupervisor(
        lambda: site, settings=lambda: options, notify=messages.append, clock=clock,
        store=store or ss.MemoryStore(), bus=SimpleNamespace(publish=events.append))
    supervisor.activities.register("capture", lambda: order.append("stop activity"))
    return SimpleNamespace(supervisor=supervisor, order=order, mounts=mounts, dome=dome, device=device, clock=clock,
                           messages=messages, events=events, site=site, options=options, ss=ss)


# ---------------------------------------------------------------------------
# TC-SAFE-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-010")
@pytest.mark.priority("MVP")
async def test_tc_safe_010_unsafe_runs_the_protective_stop_with_nothing_running(monkeypatch):
    """SAFE-010: becoming unsafe stops activity, parks every Pier and closes the roof, with no session or person."""
    world = _world(monkeypatch)
    await world.supervisor.tick()
    assert world.order == [] and world.supervisor.is_safe()
    world.device.is_safe, world.device.explanation = False, "Rain detected"
    await world.supervisor.tick()
    assert world.supervisor.state == world.ss.State.SECURED
    assert world.dome.shutter_state == "Closed" and all(m.at_park for _n, m in world.mounts)
    assert not world.supervisor.is_safe()


# ---------------------------------------------------------------------------
# TC-SAFE-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-020")
@pytest.mark.priority("P3")
async def test_tc_safe_020_log_weather_readings_with_session_history(mock_weather_station, event_bus):
    """SAFE-020: Log weather-device readings alongside session history for quality correlation."""
    safe_mod = pytest.importorskip("galileo.safety")
    wx_service = safe_mod.WeatherLoggingService(station=mock_weather_station, event_bus=event_bus)

    await wx_service.poll_and_log()
    mock_weather_station.poll.assert_called_once()
    assert event_bus.publish.called

    published = event_bus.publish.call_args[0][0]
    assert hasattr(published, "timestamp") or "weather" in str(type(published)).lower()


# ---------------------------------------------------------------------------
# TC-SAFE-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-030")
@pytest.mark.priority("P2")
async def test_tc_safe_030_warn_rules_and_switching_the_stop_or_roof_close_off(monkeypatch):
    """SAFE-030: a Warn rule only warns; the stop, and separately the roof close, can be switched off."""
    from galileo.safety import WeatherSafetyRule
    from galileo.safety_supervisor import Level, SafetySettings, Source
    world = _world(monkeypatch)
    wind = WeatherSafetyRule("wind_speed", safety_related=True, operator=">=", threshold=20.0, action="warn")
    world.site.sources[:] = [Source("w", "Station", "weather", adapter=object(), rules=[wind])]
    world.supervisor._evaluator._read = lambda source: {"wind_speed": 30.0}
    await world.supervisor.tick()
    assert world.supervisor.verdict.level == Level.WARNING and world.supervisor.is_safe() and world.order == []

    world = _world(monkeypatch, settings=SafetySettings(close_roof=False))
    world.device.is_safe = False
    await world.supervisor.tick()
    assert "park A" in world.order and "close roof" not in world.order

    world = _world(monkeypatch, settings=SafetySettings(enabled=False))
    world.device.is_safe = False
    await world.supervisor.tick()
    assert world.order == [] and not world.supervisor.is_safe()      # still nothing may be started


# ---------------------------------------------------------------------------
# TC-SAFE-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-040")
@pytest.mark.priority("MVP")
async def test_tc_safe_040_nothing_restarts_until_safe_long_enough_and_acknowledged(monkeypatch):
    """SAFE-040: acknowledging is refused while unsafe or not yet stably safe; nothing restarts by itself unless the
    Observatory opted in."""
    from galileo.safety_supervisor import SafetySettings, State
    world = _world(monkeypatch)
    restarted: list[bool] = []
    world.supervisor.on_restart = lambda: restarted.append(True)
    world.device.is_safe = False
    await world.supervisor.tick()
    with pytest.raises(ValueError, match="still unsafe"):
        world.supervisor.acknowledge("me")
    world.device.is_safe = True
    await world.supervisor.tick()
    with pytest.raises(ValueError, match="long enough"):
        world.supervisor.acknowledge("me")
    world.clock.now += 901
    await world.supervisor.tick()
    assert world.supervisor.state == State.AWAITING_ACK and not world.supervisor.is_safe() and not restarted
    world.supervisor.acknowledge("me")
    assert world.supervisor.is_safe() and not restarted

    world = _world(monkeypatch, settings=SafetySettings(auto_restart=True))
    world.supervisor.on_restart = lambda: restarted.append(True)
    world.device.is_safe = False
    await world.supervisor.tick()
    world.device.is_safe = True
    await world.supervisor.tick()
    world.clock.now += 901
    await world.supervisor.tick()
    assert restarted == [True] and world.supervisor.is_safe()


# ---------------------------------------------------------------------------
# TC-SAFE-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-050")
@pytest.mark.priority("P2")
async def test_tc_safe_050_weather_forecast_advisory_only(safety_service):
    """SAFE-050: Internet weather forecast displayed as planning aid only; must never trigger automated abort."""
    forecast_client = MagicMock()
    forecast_client.get_forecast = AsyncMock(return_value={"precipitation_mm": 5.0, "cloud_cover_pct": 90})

    safety_service.set_forecast_client(forecast_client)
    forecast = await safety_service.get_forecast_advisory()

    assert forecast is not None
    # Forecast must not have caused an abort decision
    assert not hasattr(safety_service, "poll_and_react")      # advisory only: nothing here can stop equipment


# ---------------------------------------------------------------------------
# TC-SAFE-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-060")
@pytest.mark.priority("MVP")
async def test_tc_safe_060_watchdog_parks_on_heartbeat_timeout(mock_indi_mount, mock_dome):
    """SAFE-060: Independent heartbeat-timeout watchdog parks mount and dome if heartbeats stop."""
    safe_mod = pytest.importorskip("galileo.safety")
    _reports_park(mock_indi_mount)
    watchdog = safe_mod.WatchdogService(
        mount=mock_indi_mount,
        dome=mock_dome,
        timeout_s=0.1,
    )

    watchdog.start()
    await asyncio.sleep(0.2)  # allow timeout to expire without sending heartbeats
    await watchdog.stop()

    mock_indi_mount.park.assert_called()
    mock_dome.close_shutter.assert_called()


@pytest.mark.requirement("TC-SAFE-060")
@pytest.mark.priority("MVP")
async def test_tc_safe_060_heartbeats_keep_watchdog_quiet_and_trip_is_reported(mock_indi_mount, mock_dome, event_bus):
    """SAFE-060: Heartbeats prevent a trip; a trip parks mount then dome, publishes an unsafe event and calls handlers."""
    safe_mod = pytest.importorskip("galileo.safety")
    tripped = []
    _reports_park(mock_indi_mount)
    # Devices are resolved at trip time, so ones connected after start-up are covered.
    watchdog = safe_mod.WatchdogService(
        mount=lambda: mock_indi_mount, dome=lambda: mock_dome, timeout_s=0.3,
        event_bus=event_bus, on_trip=tripped.append,
    )
    watchdog.start()
    assert watchdog.status == "armed"
    for _ in range(8):
        await asyncio.sleep(0.1)
        watchdog.heartbeat()
    assert watchdog.status == "armed"
    mock_indi_mount.park.assert_not_called()

    await asyncio.sleep(0.8)  # heartbeats stop
    assert watchdog.status == "tripped"
    mock_indi_mount.park.assert_called_once()
    mock_dome.close_shutter.assert_called_once()
    assert len(tripped) == 1 and "heartbeat" in tripped[0]
    event_bus.publish.assert_called_once()
    assert event_bus.publish.call_args.args[0].source == "Watchdog"
    await watchdog.stop()


@pytest.mark.requirement("TC-SAFE-060")
@pytest.mark.priority("MVP")
async def test_tc_safe_060_watchdog_fires_when_event_loop_is_blocked(mock_indi_mount):
    """SAFE-060: The watchdog runs off the event loop, so a hung loop still trips it."""
    import time
    safe_mod = pytest.importorskip("galileo.safety")
    _reports_park(mock_indi_mount)
    watchdog = safe_mod.WatchdogService(mount=mock_indi_mount, timeout_s=0.2)
    watchdog.start()
    time.sleep(0.6)  # noqa: ASYNC251 - deliberately block this (the event-loop) thread, as a hang would
    watchdog.stop_sync()
    mock_indi_mount.park.assert_called_once()


@pytest.mark.requirement("TC-SAFE-060")
@pytest.mark.priority("MVP")
def test_tc_safe_060_clean_stop_never_parks(mock_indi_mount, mock_dome):
    """SAFE-060: Stopping the watchdog on exit disarms it without parking anything."""
    import time
    safe_mod = pytest.importorskip("galileo.safety")
    watchdog = safe_mod.WatchdogService(mount=mock_indi_mount, dome=mock_dome, timeout_s=0.2)
    watchdog.start()
    watchdog.stop_sync()
    time.sleep(0.4)
    assert watchdog.status == "stopped"
    mock_indi_mount.park.assert_not_called()
    mock_dome.close_shutter.assert_not_called()


@pytest.mark.requirement("TC-SAFE-060")
@pytest.mark.priority("MVP")
def test_tc_safe_060_settings_defaults_and_clamping(settings_db, config_folder):
    """SAFE-060: The heartbeat timeout is configurable, defaulting to 300 s and clamped to a sane range."""
    from galileo import watchdog_settings as ws
    assert ws.load_watchdog_settings() == {"enabled": True, "timeout_s": 300.0}
    (config_folder / "watchdog.json").write_text('{"enabled": false, "timeout_s": 1}')   # legacy file, imported once
    assert ws.load_watchdog_settings() == {"enabled": False, "timeout_s": ws.MIN_TIMEOUT_S}
    assert (config_folder / "watchdog.json.migrated").exists()
    from galileo.settings_store import set_namespace
    set_namespace("watchdog", {"enabled": "maybe", "timeout_s": "soon"}, replace=True)
    assert ws.load_watchdog_settings() == {"enabled": True, "timeout_s": 300.0}


# ---------------------------------------------------------------------------
# TC-SAFE-070
# ---------------------------------------------------------------------------

async def _verdict(monitor):
    """The supervisor's judgement of one Safety Monitor device."""
    from galileo.safety_supervisor import Evaluator, Source
    source = Source("m", "Safety monitor", "safety_monitor", adapter=monitor)
    return await Evaluator().evaluate([source], 60, 0.0)


@pytest.mark.requirement("TC-SAFE-070")
@pytest.mark.priority("P2")
async def test_tc_safe_070_tier1_hardware_monitor_trusted(mock_safety_monitor):
    """SAFE-070: Tier-1 hardware safety monitor connected via INDI/Alpaca; state fully trusted for abort."""
    mock_safety_monitor.tier = 1
    mock_safety_monitor.is_safe = False
    mock_safety_monitor.is_connected = True
    mock_safety_monitor.poll = AsyncMock()
    assert (await _verdict(mock_safety_monitor)).act


# ---------------------------------------------------------------------------
# TC-SAFE-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-080")
@pytest.mark.priority("MVP")
async def test_tc_safe_080_tier2_software_monitor_equally_trusted():
    """SAFE-080: Tier-2 software safety monitor (e.g. ML all-sky classifier) treated equally to Tier-1 for abort."""
    ml_monitor = MagicMock(name="MLAllSkySafetyMonitor")
    ml_monitor.tier = 2
    ml_monitor.is_connected = True
    ml_monitor.is_safe = False
    ml_monitor.explanation = "Clouds detected by classifier"
    ml_monitor.poll = AsyncMock()
    verdict = await _verdict(ml_monitor)
    assert verdict.act and "Clouds detected by classifier" in verdict.reasons[0]


@pytest.mark.requirement("TC-SAFE-080")
@pytest.mark.priority("MVP")
async def test_tc_safe_080_in_process_plugin_backend_equally_trusted():
    """SAFE-080: A Tier-2 monitor may be an in-process device backend a plugin registers through PLUG-010 implementing the identical port interface, rather than only an external INDI/Alpaca driver — trusted equally for automated abort decisions regardless of which."""
    devices = pytest.importorskip("galileo.core.devices")
    plugins = pytest.importorskip("galileo.plugins")

    class InProcessCloudClassifier(devices.DeviceBackend):
        backend = "in_process_cloud_classifier"
        device_type = "SafetyMonitor"
        tier = 2

        async def connect(self): pass
        async def disconnect(self): pass
        @property
        def is_connected(self): return True
        def get_capabilities(self): return devices.DeviceCapabilities()
        def get_properties(self): return {"is_safe": False, "explanation": "Clouds detected by classifier"}

    plugin_manager = plugins.PluginManager()
    ctx = plugin_manager.create_context()
    ctx.register_device_backend(devices.DeviceCategory.SAFETY_MONITOR, InProcessCloudClassifier)

    registered = devices.DeviceBackend.registered_backends.get(devices.DeviceCategory.SAFETY_MONITOR, [])
    assert InProcessCloudClassifier in registered, \
        "a plugin-registered in-process backend must use the same registration path as any other device category"

    in_process_monitor = InProcessCloudClassifier()
    in_process_monitor.is_safe = False
    in_process_monitor.poll = AsyncMock()
    # In-process backend's unsafe state must drive the stop, same as an external driver's.
    assert (await _verdict(in_process_monitor)).act


# ---------------------------------------------------------------------------
# TC-SAFE-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-090")
@pytest.mark.priority("P3")
async def test_tc_safe_090_aurora_advisory_display(safety_service):
    """SAFE-090: Optionally display aurora activity estimate (Kp index) as an advisory-only planning aid."""
    kp_client = MagicMock()
    kp_client.get_kp_index = AsyncMock(return_value=3.5)

    safety_service.set_kp_client(kp_client)
    kp = await safety_service.get_aurora_advisory()
    assert isinstance(kp, (int, float))
    # Advisory must not have triggered abort
    assert not hasattr(safety_service, "poll_and_react")      # advisory only: nothing here can stop equipment


@pytest.mark.requirement("TC-SAFE-090")
@pytest.mark.priority("P3")
async def test_tc_safe_090_aurora_advisory_is_none_not_zero_when_unconfigured(safety_service):
    """SAFE-090: with no Kp client configured, the advisory is None ("no data"), not 0.0
    ("measured calm") — a consumer such as What's Up Tonight (WUT-100) needs to tell the
    two apart to degrade its confidence indicator correctly rather than assuming a quiet
    night whenever no client happens to be configured."""
    assert await safety_service.get_aurora_advisory() is None


# ---------------------------------------------------------------------------
# TC-SAFE-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-100")
@pytest.mark.priority("P3")
async def test_tc_safe_100_smoke_transparency_advisory(safety_service):
    """SAFE-100: Optionally display smoke/transparency estimate as advisory-only planning aid; never drives abort."""
    smoke_client = MagicMock()
    smoke_client.get_smoke_aqi = AsyncMock(return_value=42)

    safety_service.set_smoke_client(smoke_client)
    aqi = await safety_service.get_smoke_advisory()
    assert isinstance(aqi, (int, float))
    assert not hasattr(safety_service, "poll_and_react")      # advisory only: nothing here can stop equipment


@pytest.mark.requirement("TC-SAFE-100")
@pytest.mark.priority("P3")
async def test_tc_safe_100_smoke_advisory_is_none_not_zero_when_unconfigured(safety_service):
    """SAFE-100: with no smoke client configured, the advisory is None ("no data"), not
    0.0 ("measured clear") — same "no data" vs. "measured clear" distinction as aurora
    (SAFE-090), needed by What's Up Tonight (WUT-100) to degrade confidence correctly."""
    assert await safety_service.get_smoke_advisory() is None


# ---------------------------------------------------------------------------
# NOAA aurora / smoke clients (SAFE-090 / SAFE-100)
# ---------------------------------------------------------------------------

_HMS_KML = b"""<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Folder><name>Smoke (Light)</name><Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>
-115,50,0 -113,50,0 -113,52,0 -115,52,0 -115,50,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Folder>
<Folder><name>Smoke (Heavy)</name><Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>
-100,40,0 -99,40,0 -99,41,0 -100,41,0 -100,40,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Folder>
</Document></kml>"""


@pytest.mark.requirement("TC-SAFE-090")
@pytest.mark.priority("P3")
async def test_tc_safe_090_noaa_kp_client_reads_latest_row(monkeypatch):
    """SAFE-090: the NOAA client reports the most recent Kp row, and None (not 0) on failure."""
    import json
    safe_mod = pytest.importorskip("galileo.safety")
    rows = [["time_tag", "Kp"], ["2026-10-07 00:00:00", "2.33"], ["2026-10-07 03:00:00", "5.00"]]
    monkeypatch.setattr(safe_mod, "_http_get", lambda url: json.dumps(rows).encode())
    assert await safe_mod.NoaaKpClient().get_kp_index() == 5.0

    def boom(url):
        raise OSError("offline")
    monkeypatch.setattr(safe_mod, "_http_get", boom)
    assert await safe_mod.NoaaKpClient().get_kp_index() is None


@pytest.mark.requirement("TC-SAFE-100")
@pytest.mark.priority("P3")
async def test_tc_safe_100_noaa_smoke_client_rates_location(monkeypatch):
    """SAFE-100: HMS smoke polygons near the site map to an AQI-equivalent; elsewhere is clear;
    outside North America (or offline) is None."""
    safe_mod = pytest.importorskip("galileo.safety")
    monkeypatch.setattr(safe_mod, "_http_get", lambda url: _HMS_KML)
    assert await safe_mod.NoaaSmokeClient(51.0, -114.0).get_smoke_aqi() == 75.0    # inside light smoke
    assert await safe_mod.NoaaSmokeClient(51.0, -113.2).get_smoke_aqi() == 75.0    # box overlaps edge only
    assert await safe_mod.NoaaSmokeClient(45.0, -90.0).get_smoke_aqi() == 25.0     # clear
    assert await safe_mod.NoaaSmokeClient(-33.0, 151.0).get_smoke_aqi() is None    # outside HMS coverage

    def boom(url):
        raise OSError("offline")
    monkeypatch.setattr(safe_mod, "_http_get", boom)
    assert await safe_mod.NoaaSmokeClient(51.0, -114.0).get_smoke_aqi() is None


@pytest.mark.requirement("TC-SAFE-100")
@pytest.mark.priority("P2")
def test_tc_safe_100_kml_with_entity_declaration_is_rejected():
    """SAFE-100: the NOAA KML is parsed with defusedxml, so a DTD/entity-expansion payload is refused, not expanded."""
    from defusedxml import DefusedXmlException
    safe_mod = pytest.importorskip("galileo.safety")
    bomb = b'<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY a "aaaa">]><kml xmlns="http://www.opengis.net/kml/2.2">&a;</kml>'
    with pytest.raises(DefusedXmlException):
        safe_mod.NoaaSmokeClient(-33.0, 151.0)._rate(bomb)


# ---------------------------------------------------------------------------
# TC-SAFE-110
# ---------------------------------------------------------------------------

@pytest.fixture
def quick_park(monkeypatch):
    from galileo import roof
    monkeypatch.setattr(roof, "PARK_TIMEOUT_S", 0.2)
    monkeypatch.setattr(roof, "PARK_POLL_S", 0.01)


def _roof(order):
    dome = MagicMock(name="Roof")
    dome.close_shutter = AsyncMock(side_effect=lambda: order.append("close"))
    dome.open_shutter = AsyncMock()
    dome.park = AsyncMock()
    return dome


def _mount(order, name, parks=True):
    mount = _reports_park(MagicMock(name=name), parks)
    inner = mount.park.side_effect

    async def park():
        order.append(f"park {name}")
        await inner()

    mount.park = AsyncMock(side_effect=park)
    return mount


@pytest.mark.requirement("TC-SAFE-110")
@pytest.mark.priority("MVP")
async def test_tc_safe_110_dome_close_block_parks_every_mount_under_the_roof_first(quick_park):
    """SAFE-110: before an automatic roof close every mount under it is parked and confirmed parked."""
    from galileo.session_exec import RunState, SessionContext, SessionExecutor
    from galileo.ui.sessions import DomeCloseBlock
    order: list[str] = []
    mine, other = _mount(order, "A"), _mount(order, "B")
    ctx = SessionContext(pier_name="A", mount=mine, dome=_roof(order), roof_mounts=lambda: [("A", mine), ("B", other)])
    result = await SessionExecutor(ctx).run([DomeCloseBlock()])
    assert result.state == RunState.COMPLETED
    assert sorted(order[:2]) == ["park A", "park B"] and order[2] == "close"


@pytest.mark.requirement("TC-SAFE-110")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("other", ["will not park", "not connected", "reports no park state"])
async def test_tc_safe_110_roof_stays_open_when_a_mount_is_not_confirmed_parked(quick_park, other):
    """SAFE-110: a mount that cannot be confirmed parked leaves the roof open, alerts, and the session is not
    reported as completed (a completed one would be removed)."""
    from galileo.session_exec import RunState, SessionContext, SessionExecutor
    from galileo.ui.sessions import DomeCloseBlock
    order: list[str] = []
    mine = _mount(order, "A")
    blind = MagicMock(name="B")
    blind.park = AsyncMock()
    blind.get_status = AsyncMock(return_value={})
    second = {"will not park": _mount(order, "B", parks=False), "not connected": None,
              "reports no park state": blind}[other]
    notify = MagicMock()
    notify.emit = AsyncMock()
    ctx = SessionContext(pier_name="A", mount=mine, dome=_roof(order), notify_service=notify,
                         roof_mounts=lambda: [("A", mine), ("Pier B", second)])
    result = await SessionExecutor(ctx).run([DomeCloseBlock()])
    assert "close" not in order
    assert result.state == RunState.ERROR
    assert any("roof was NOT closed" in e and "Pier B" in e for e in result.errors)
    assert any("Pier B" in str(call.args) for call in notify.emit.await_args_list)


@pytest.mark.requirement("TC-SAFE-110")
@pytest.mark.priority("MVP")
async def test_tc_safe_110_session_end_close_parks_first_and_respects_other_piers(quick_park):
    """SAFE-110 / OBS-100: the open/close-with-sessions close parks first, and is not made while another Pier
    is imaging under the same roof."""
    from galileo.dome import DomeService
    from galileo.observatory import ResourceArbiter
    from galileo.session_exec import SessionContext, SessionExecutor
    order: list[str] = []
    mount, dome = _mount(order, "A"), _roof(order)
    service = DomeService(dome=dome, mount=mount)
    service.set_sequence_sync(True)
    arbiter = ResourceArbiter(bus=MagicMock())
    ctx = SessionContext(pier_name="A", mount=mount, dome=dome, dome_service=service, arbiter=arbiter)
    await SessionExecutor(ctx).run([])
    assert order == ["park A", "close"]

    order.clear()
    arbiter.begin_activity("Pier B", "dome")
    await SessionExecutor(ctx).run([])
    assert order == []     # neither parked nor closed: Pier B still needs the roof


@pytest.mark.requirement("TC-SAFE-110")
@pytest.mark.priority("MVP")
def test_tc_safe_110_watchdog_leaves_the_roof_open_if_a_mount_will_not_park(quick_park, mock_dome):
    """SAFE-110 / SAFE-060: the watchdog parks every mount under the roof and closes only if all confirm."""
    import time

    from galileo.safety import WatchdogService
    order: list[str] = []
    good, stuck = _mount(order, "A"), _mount(order, "B", parks=False)
    watchdog = WatchdogService(dome=mock_dome, timeout_s=0.1, roof_mounts=lambda: [("A", good), ("Pier B", stuck)])
    watchdog.start()
    time.sleep(1.0)
    watchdog.stop_sync()
    good.park.assert_awaited_once()
    stuck.park.assert_awaited_once()
    mock_dome.close_shutter.assert_not_called()
    assert watchdog.roof_left_open and "Pier B" in watchdog.trip_detail



@pytest.mark.requirement("TC-SAFE-110")
@pytest.mark.priority("MVP")
async def test_tc_safe_110_unlisted_mounts_still_park_ours_but_keep_the_roof_open(quick_park, mock_dome):
    """SAFE-110: if the mounts under the roof cannot be listed, the reachable mount is still parked and the roof
    stays open, for a session and for the watchdog."""
    import time

    from galileo.safety import WatchdogService
    from galileo.session_exec import SessionContext, SessionExecutor
    from galileo.ui.sessions import DomeCloseBlock

    def broken():
        raise RuntimeError("no database")

    order: list[str] = []
    mine = _mount(order, "A")
    ctx = SessionContext(pier_name="A", mount=mine, dome=_roof(order), roof_mounts=broken)
    await SessionExecutor(ctx).run([DomeCloseBlock()])
    assert order == ["park A"]

    other = _mount(order, "W")
    watchdog = WatchdogService(mount=other, dome=mock_dome, timeout_s=0.1, roof_mounts=broken)
    watchdog.start()
    time.sleep(0.8)  # noqa: ASYNC251 - the watchdog runs on its own thread
    watchdog.stop_sync()
    other.park.assert_awaited_once()
    mock_dome.close_shutter.assert_not_called()

# ---------------------------------------------------------------------------
# TC-SAFE-120
# ---------------------------------------------------------------------------

def _desktop_window(verdict, mount):
    from types import SimpleNamespace
    return SimpleNamespace(
        _device_pages={"mount": {"adapter": mount}}, _current_pier=None, _current_observatory=None, _window=None,
        _safety_evaluation=lambda: (True, verdict["safe"], [] if verdict["safe"] else ["Rain detected"]))


@pytest.mark.requirement("TC-SAFE-120")
@pytest.mark.priority("MVP")
async def test_tc_safe_120_desktop_built_session_follows_the_safety_verdict():
    """SAFE-120: a session the desktop builds is given the Safety page's verdict: while unsafe only shutdown
    blocks run, and the session is not reported as completed."""
    from galileo.session_exec import RunState, SessionExecutor
    from galileo.ui.session_runner import build_session_context, refresh_safety_verdict
    from galileo.ui.sessions import ParkMountBlock, UnparkMountBlock
    verdict = {"safe": True}
    mount = _reports_park(MagicMock(name="Mount"))
    window = _desktop_window(verdict, mount)
    ctx = build_session_context(window)
    assert ctx.is_safe() is True and ctx.roof_mounts() == [("this Pier", mount)]

    verdict["safe"] = False                # the weather turns after the session was built
    refresh_safety_verdict(window)         # what the controller's safety timer does
    mount.unpark = AsyncMock()
    result = await SessionExecutor(ctx).run([UnparkMountBlock(), ParkMountBlock()])
    mount.unpark.assert_not_awaited()
    mount.park.assert_awaited_once()
    assert result.state == RunState.ERROR


@pytest.mark.requirement("TC-SAFE-120")
@pytest.mark.priority("MVP")
async def test_tc_safe_120_a_run_paused_for_the_weather_is_not_made_to_skip():
    """SAFE-120: a held (paused) run waits and is judged again on resume, so nothing is skipped."""
    from galileo.session_exec import RunState, SessionContext, SessionExecutor
    from galileo.ui.sessions import UnparkMountBlock
    safe = {"now": True}
    mount = MagicMock()
    mount.unpark = AsyncMock()
    executor = SessionExecutor(SessionContext(mount=mount, is_safe=lambda: safe["now"]))

    class _Hold:      # pauses the run and turns the weather bad, as the safety timer does between blocks
        display_text = "Hold"

        async def execute(self, context):
            executor.pause()
            safe["now"] = False

    task = asyncio.create_task(executor.run([_Hold(), UnparkMountBlock()]))
    await asyncio.sleep(0.3)
    mount.unpark.assert_not_awaited()
    safe["now"] = True
    executor.resume()
    result = await asyncio.wait_for(task, 5)
    assert result.state == RunState.COMPLETED
    mount.unpark.assert_awaited_once()


# ---------------------------------------------------------------------------
# TC-SAFE-130 / 140
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-130")
@pytest.mark.priority("MVP")
async def test_tc_safe_130_verdict_from_saved_devices_and_rules(monkeypatch, settings_db):
    """SAFE-130: any unsafe device, breached Stop rule or unreadable saved device is unsafe; no device saved is
    unmonitored, not unsafe. Rules and their action come back from the database."""
    from galileo.observatory import create_observatory, get_weather_safety_rules, save_weather_safety_rule
    from galileo.safety import WeatherSafetyRule
    from galileo.safety_supervisor import Evaluator, Level, Source
    observatory = create_observatory("Shed")
    save_weather_safety_rule(observatory, WeatherSafetyRule("wind_speed", safety_related=True, operator=">=",
                                                            threshold=20.0, action="warn"))
    save_weather_safety_rule(observatory, WeatherSafetyRule("rain_rate", safety_related=True, operator=">",
                                                            threshold=0.0))
    rules = get_weather_safety_rules(observatory)
    assert sorted(r.action for r in rules) == ["stop", "warn"]

    assert (await Evaluator().evaluate([], 60, 0.0)).level == Level.UNMONITORED
    station = Source("w", "Station", "weather", adapter=object(), rules=rules)
    verdict = await Evaluator(lambda s: {"rain_rate": 1.0, "wind_speed": 0.0}).evaluate([station], 60, 0.0)
    assert verdict.level == Level.UNSAFE and verdict.act
    missing = await Evaluator().evaluate([Source("w", "Station", "weather")], 60, 0.0)
    assert missing.level == Level.UNSAFE and not missing.act


@pytest.mark.requirement("TC-SAFE-140")
@pytest.mark.priority("MVP")
async def test_tc_safe_140_lost_device_is_acted_on_only_after_the_grace_period(monkeypatch):
    """SAFE-140: a device never read blocks but moves nothing; one that drops out is acted on after the grace."""
    from galileo.safety_supervisor import State
    world = _world(monkeypatch)
    world.device.fail = True                      # never read since start-up
    await world.supervisor.tick()
    world.clock.now += 3600
    await world.supervisor.tick()
    assert world.order == [] and not world.supervisor.is_safe()

    world.device.fail = False
    await world.supervisor.tick()
    world.device.fail = True                      # now it drops out
    await world.supervisor.tick()
    world.clock.now += 30
    await world.supervisor.tick()
    assert world.order == []
    world.clock.now += 31
    await world.supervisor.tick()
    assert world.supervisor.state == State.SECURED and "close roof" in world.order


# ---------------------------------------------------------------------------
# TC-SAFE-150 / 160
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-150")
@pytest.mark.priority("MVP")
async def test_tc_safe_150_order_of_the_stop_and_once_per_episode(monkeypatch):
    """SAFE-150: activities, then guiding, then park, then close; once per episode; one failure stops nothing else."""
    world = _world(monkeypatch)

    def broken():
        raise RuntimeError("stuck")

    world.supervisor.activities.register("broken", broken)
    world.device.is_safe = False
    await world.supervisor.tick()
    order = world.order
    assert order.index("stop activity") < order.index("stop guiding") < order.index("park A") < order.index("close roof")
    assert any("broken" in p for p in world.supervisor.problems) and world.dome.shutter_state == "Closed"
    assert len(world.events) == 2                 # one unsafe event per Pier
    before = list(order)
    await world.supervisor.tick()
    assert order == before                        # a person's later commands are not undone


@pytest.mark.requirement("TC-SAFE-160")
@pytest.mark.priority("MVP")
async def test_tc_safe_160_retries_the_park_and_alerts_until_the_roof_closes(monkeypatch):
    """SAFE-160: a mount that will not confirm leaves the roof open; the park is retried, alerts repeat, and the roof
    closes as soon as every mount confirms."""
    from galileo.safety_supervisor import State
    world = _world(monkeypatch, parks=(True, False))
    world.device.is_safe = False
    await world.supervisor.tick()
    assert world.supervisor.state == State.NOT_SECURED and "close roof" not in world.order
    assert any("NOT complete" in m for m in world.messages)
    world.clock.now += 601
    await world.supervisor.tick()
    assert any(m.startswith("Still not secured") for m in world.messages)
    world.mounts[1][1].parks = True
    world.clock.now += 61
    await world.supervisor.tick()
    assert world.supervisor.state == State.SECURED and world.dome.shutter_state == "Closed"


# ---------------------------------------------------------------------------
# TC-SAFE-170 / 180
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-170")
@pytest.mark.priority("MVP")
async def test_tc_safe_170_unacknowledged_stop_survives_a_restart(monkeypatch, settings_db):
    """SAFE-170: the stop is recorded, still in force after a restart, and shown until acknowledged."""
    from galileo.safety_supervisor import DatabaseStore, State
    world = _world(monkeypatch, store=DatabaseStore())
    world.device.is_safe = False
    await world.supervisor.tick()

    again = _world(monkeypatch, store=DatabaseStore())
    assert again.supervisor.state == State.SECURED and not again.supervisor.is_safe()
    assert "stop" in again.supervisor.gate_reason()
    await again.supervisor.tick()                 # safe now: still waits to be stable, then for a person
    again.clock.now += 901
    await again.supervisor.tick()
    again.supervisor.acknowledge("me")
    assert again.supervisor.history()[-1]["acknowledged_by"] == "me"
    assert _world(monkeypatch, store=DatabaseStore()).supervisor.state == State.READY


@pytest.mark.requirement("TC-SAFE-180")
@pytest.mark.priority("MVP")
async def test_tc_safe_180_desktop_wiring_parks_and_closes(monkeypatch, settings_db):
    """SAFE-180: through the desktop's own wiring, a weather rule tripping stops a screen's activity, parks the mount
    and closes the dome, and the gate the scheduler and Run read goes down."""
    import asyncio
    from types import SimpleNamespace

    from galileo import roof as roof_mod
    from galileo.safety_supervisor import MemoryStore, Source, State
    from PySide6.QtWidgets import QApplication

    from galileo.ui.safety_host import SafetyHost, register_stopper
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(roof_mod, "PARK_POLL_S", 0.01)
    order: list[str] = []
    mount, dome, device = _SiteMount(order, "A"), _Dome(order), _SafetyDevice()
    source = Source("m", "Rain sensor", "safety_monitor", adapter=device)
    window = SimpleNamespace(
        _device_pages={"mount": {"adapter": mount}, "dome": {"adapter": dome},
                       "weather": {"sources": lambda: [source]}},
        _current_pier=None, _current_observatory=None, _window=None, _camera_backends={})
    register_stopper(window, "capture", lambda: order.append("stop capture"))
    host = SafetyHost(window, store=MemoryStore())
    host.start(run_thread=False)
    await host.supervisor.tick()
    assert host.evaluation() == (True, True, [])

    device.is_safe = False
    task = asyncio.create_task(host.supervisor.tick())
    while not task.done():
        qapp.processEvents()                      # the stop's UI half is queued to this thread
        await asyncio.sleep(0.01)
    await task
    host.stop()
    assert host.supervisor.state == State.SECURED
    assert order == ["stop capture", "park A", "close roof"]
    assert not host.is_safe() and host.holding()
    assert "SAFETY STOP" in host.banner_text()



@pytest.mark.requirement("TC-SAFE-130")
@pytest.mark.priority("MVP")
async def test_tc_safe_130_no_registered_device_switches_the_safety_system_off(settings_db):
    """SAFE-130: with no safety device registered nothing is blocked and a left-over stop is cleared; a saved tab
    with no device name is not a registered device."""
    from galileo.observatory import create_observatory, registered_safety_slots, save_safety_device_config
    from galileo.safety_supervisor import MemoryStore, SafetySupervisor, Site, State

    observatory = create_observatory("Shed")
    save_safety_device_config(observatory, "weather", driver="INDI", server="x", port=7624, device_name=None)
    assert registered_safety_slots(observatory, "weather") == []

    store = MemoryStore()
    store.open("", "Weather Station is not connected or cannot be read")
    supervisor = SafetySupervisor(Site, store=store)
    assert supervisor.state == State.SECURED and supervisor.acknowledge_blocker()
    await supervisor.tick()
    assert supervisor.state == State.READY and supervisor.is_safe()
    assert store.unacknowledged("") is None
