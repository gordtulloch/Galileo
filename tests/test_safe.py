"""SAFE — Safety & Weather Monitoring (TC-SAFE-010 … TC-SAFE-100)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def safety_service(mock_safety_monitor, event_bus):
    safe_mod = pytest.importorskip("galileo.safety")
    return safe_mod.SafetyMonitorService(monitor=mock_safety_monitor, event_bus=event_bus)


# ---------------------------------------------------------------------------
# TC-SAFE-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-010")
@pytest.mark.priority("P2")
async def test_tc_safe_010_abort_sequence_and_park_on_unsafe(safety_service, mock_safety_monitor, event_bus):
    """SAFE-010: Abort/pause running sequence and park equipment when safety monitor reports unsafe."""
    mock_sequence = MagicMock()
    mock_sequence.abort = AsyncMock()
    mock_mount = MagicMock()
    mock_mount.park = AsyncMock()

    safety_service.register_sequence(mock_sequence)
    safety_service.register_mount(mock_mount)

    mock_safety_monitor.is_safe = False
    mock_safety_monitor.explanation = "Rain detected"
    await safety_service.poll_and_react()

    mock_sequence.abort.assert_called_once()
    mock_mount.park.assert_called_once()


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
def test_tc_safe_030_configure_abort_vs_warning_policy():
    """SAFE-030: Configure which unsafe conditions trigger automatic abort versus warning-only notification."""
    safe_mod = pytest.importorskip("galileo.safety")
    policy = safe_mod.SafetyPolicy(
        abort_on_unsafe=True,
        warn_on_borderline=True,
    )
    assert policy.abort_on_unsafe is True
    assert policy.warn_on_borderline is True

    policy2 = safe_mod.SafetyPolicy(abort_on_unsafe=False)
    assert policy2.abort_on_unsafe is False


# ---------------------------------------------------------------------------
# TC-SAFE-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-040")
@pytest.mark.priority("P2")
async def test_tc_safe_040_prevent_resume_until_confirmed_safe(safety_service, mock_safety_monitor):
    """SAFE-040: Prevent automatic sequence resumption after safety abort until conditions confirmed safe."""
    safe_mod = pytest.importorskip("galileo.safety")
    safety_service._state = safe_mod.SafetyState.ABORTED

    mock_safety_monitor.is_safe = False
    can_resume = await safety_service.can_resume()
    assert can_resume is False

    mock_safety_monitor.is_safe = True
    safety_service._require_user_confirm = False
    can_resume2 = await safety_service.can_resume()
    assert can_resume2 is True


# ---------------------------------------------------------------------------
# TC-SAFE-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-050")
@pytest.mark.priority("P2")
async def test_tc_safe_050_weather_forecast_advisory_only(safety_service):
    """SAFE-050: Internet weather forecast displayed as planning aid only; must never trigger automated abort."""
    safe_mod = pytest.importorskip("galileo.safety")
    forecast_client = MagicMock()
    forecast_client.get_forecast = AsyncMock(return_value={"precipitation_mm": 5.0, "cloud_cover_pct": 90})

    safety_service.set_forecast_client(forecast_client)
    forecast = await safety_service.get_forecast_advisory()

    assert forecast is not None
    # Forecast must not have caused an abort decision
    assert safety_service.state != safe_mod.SafetyState.ABORTED


# ---------------------------------------------------------------------------
# TC-SAFE-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-060")
@pytest.mark.priority("MVP")
async def test_tc_safe_060_watchdog_parks_on_heartbeat_timeout(mock_indi_mount, mock_dome):
    """SAFE-060: Independent heartbeat-timeout watchdog parks mount and dome if heartbeats stop."""
    safe_mod = pytest.importorskip("galileo.safety")
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


# ---------------------------------------------------------------------------
# TC-SAFE-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-070")
@pytest.mark.priority("P2")
async def test_tc_safe_070_tier1_hardware_monitor_trusted(safety_service, mock_safety_monitor):
    """SAFE-070: Tier-1 hardware safety monitor connected via INDI/Alpaca; state fully trusted for abort."""
    safe_mod = pytest.importorskip("galileo.safety")
    mock_safety_monitor.tier = 1
    mock_safety_monitor.is_safe = False

    await safety_service.poll_and_react()
    assert safety_service.last_abort_trigger == "SafetyMonitor:SimSafetyMonitor"


# ---------------------------------------------------------------------------
# TC-SAFE-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-080")
@pytest.mark.priority("MVP")
async def test_tc_safe_080_tier2_software_monitor_equally_trusted(event_bus):
    """SAFE-080: Tier-2 software safety monitor (e.g. ML all-sky classifier) treated equally to Tier-1 for abort."""
    safe_mod = pytest.importorskip("galileo.safety")

    ml_monitor = MagicMock(name="MLAllSkySafetyMonitor")
    ml_monitor.device_type = "SafetyMonitor"
    ml_monitor.name = "AllSkySafetyMonitor"
    ml_monitor.tier = 2
    ml_monitor.is_safe = False
    ml_monitor.explanation = "Clouds detected by classifier"
    ml_monitor.poll = AsyncMock()

    svc = safe_mod.SafetyMonitorService(monitor=ml_monitor, event_bus=event_bus)
    mock_mount = MagicMock(park=AsyncMock())
    svc.register_mount(mock_mount)

    await svc.poll_and_react()
    mock_mount.park.assert_called()


# ---------------------------------------------------------------------------
# TC-SAFE-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-090")
@pytest.mark.priority("P3")
async def test_tc_safe_090_aurora_advisory_display(safety_service):
    """SAFE-090: Optionally display aurora activity estimate (Kp index) as an advisory-only planning aid."""
    safe_mod = pytest.importorskip("galileo.safety")
    kp_client = MagicMock()
    kp_client.get_kp_index = AsyncMock(return_value=3.5)

    safety_service.set_kp_client(kp_client)
    kp = await safety_service.get_aurora_advisory()
    assert isinstance(kp, (int, float))
    # Advisory must not have triggered abort
    assert safety_service.state != safe_mod.SafetyState.ABORTED


# ---------------------------------------------------------------------------
# TC-SAFE-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SAFE-100")
@pytest.mark.priority("P3")
async def test_tc_safe_100_smoke_transparency_advisory(safety_service):
    """SAFE-100: Optionally display smoke/transparency estimate as advisory-only planning aid; never drives abort."""
    safe_mod = pytest.importorskip("galileo.safety")
    smoke_client = MagicMock()
    smoke_client.get_smoke_aqi = AsyncMock(return_value=42)

    safety_service.set_smoke_client(smoke_client)
    aqi = await safety_service.get_smoke_advisory()
    assert isinstance(aqi, (int, float))
    assert safety_service.state != safe_mod.SafetyState.ABORTED
