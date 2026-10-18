# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""DOME — Dome Control (TC-DOME-010 … TC-DOME-030)."""

import pytest


@pytest.fixture
def dome_service(mock_dome, mock_indi_mount):
    dome_mod = pytest.importorskip("galileo.dome")
    return dome_mod.DomeService(dome=mock_dome, mount=mock_indi_mount)


# ---------------------------------------------------------------------------
# TC-DOME-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-DOME-010")
@pytest.mark.priority("P2")
async def test_tc_dome_010_slave_azimuth_to_mount(dome_service, mock_dome, mock_indi_mount):
    """DOME-010: Support slaving dome azimuth to the mount's current pointing direction while tracking."""
    dome_service.set_slaving(enabled=True)
    assert dome_service.slaving_enabled is True

    mock_indi_mount.azimuth = 135.0
    await dome_service.sync_to_mount()
    mock_dome.slew_to_azimuth.assert_called_with(pytest.approx(135.0, abs=2.0))


# ---------------------------------------------------------------------------
# TC-DOME-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-DOME-020")
@pytest.mark.priority("P2")
async def test_tc_dome_020_sync_shutter_park_with_sequence_events(dome_service, mock_dome, event_bus):
    """DOME-020: Synchronize dome shutter and park actions with sequence start/end and meridian-flip events."""
    dome_service._event_bus = event_bus

    await dome_service.on_sequence_start()
    mock_dome.open_shutter.assert_called_once()

    await dome_service.on_sequence_end()
    mock_dome.close_shutter.assert_called_once()
    mock_dome.park.assert_called_once()

    await dome_service.on_meridian_flip()
    # Park during flip not required; but shutter must remain open
    assert mock_dome.close_shutter.call_count == 1  # still only once (from sequence end)


# ---------------------------------------------------------------------------
# TC-DOME-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-DOME-030")
@pytest.mark.priority("P2")
async def test_tc_dome_030_disable_slaving_for_third_party_hardware(dome_service):
    """DOME-030: Allow dome slaving to be disabled for domes controlled by independent third-party slaving hardware."""
    dome_service.set_slaving(enabled=True)
    assert dome_service.slaving_enabled is True

    dome_service.set_slaving(enabled=False)
    assert dome_service.slaving_enabled is False
    # When disabled, sync_to_mount must be a no-op
    dome_service._dome.slew_to_azimuth.reset_mock()

    await dome_service.sync_to_mount()
    dome_service._dome.slew_to_azimuth.assert_not_called()


# ---------------------------------------------------------------------------
# Wiring: slaving tracks a moving mount, sessions use the service
# ---------------------------------------------------------------------------

def _tracking_mount(azimuth, **extra):
    from unittest.mock import AsyncMock, MagicMock
    mount = MagicMock(name="Mount")
    mount.get_status = AsyncMock(return_value={"azimuth": azimuth, "tracking": True, "slewing": False,
                                               "at_park": False, **extra})
    return mount


@pytest.mark.requirement("TC-DOME-010")
@pytest.mark.priority("P2")
async def test_tc_dome_010_track_mount_follows_only_beyond_tolerance(mock_dome):
    """DOME-010: slaving follows the tracking mount, re-slewing only when it has moved past the tolerance."""
    from galileo.dome import DomeService
    mount = _tracking_mount(100.0)
    service = DomeService(dome=mock_dome, mount=mount)
    assert await service.track_mount() is False  # slaving off: DOME-030 no-op
    service.set_slaving(True)
    assert await service.track_mount() is True
    mock_dome.slew_to_azimuth.assert_called_with(100.0)
    mount.get_status.return_value = {"azimuth": 101.0, "tracking": True}
    assert await service.track_mount() is False  # within tolerance
    mount.get_status.return_value = {"azimuth": 120.0, "tracking": True}
    assert await service.track_mount() is True
    mount.get_status.return_value = {"azimuth": 200.0, "tracking": True, "at_park": True}
    assert await service.track_mount() is False  # parked mount is not followed


@pytest.mark.requirement("TC-DOME-010")
@pytest.mark.priority("P2")
async def test_tc_dome_010_forced_sync_works_with_slaving_off(mock_dome):
    """DOME-010/030: the explicit Dome Sync (force) slews even while continuous slaving is off."""
    from galileo.dome import DomeService
    service = DomeService(dome=mock_dome, mount=_tracking_mount(42.0))
    await service.sync_to_mount()
    mock_dome.slew_to_azimuth.assert_not_called()
    await service.sync_to_mount(force=True)
    mock_dome.slew_to_azimuth.assert_called_once_with(42.0)


@pytest.mark.requirement("TC-DOME-020")
@pytest.mark.priority("P2")
async def test_tc_dome_020_session_uses_dome_service_and_session_sync(mock_dome):
    """DOME-020: a session's Dome blocks go through the DomeService, and shutter open/close+park
    follow the session start/end only when the operator enabled it."""
    from galileo.dome import DomeService
    from galileo.session_exec import SessionContext, SessionExecutor
    from galileo.ui.sessions import DomeCloseBlock, DomeOpenBlock, DomeSyncBlock

    service = DomeService(dome=mock_dome, mount=_tracking_mount(77.0))
    ctx = SessionContext(dome=mock_dome, mount=service.mount, dome_service=service)
    await SessionExecutor(ctx, name="t").run([DomeOpenBlock(), DomeSyncBlock(), DomeCloseBlock()])
    assert mock_dome.open_shutter.await_count == 1  # block only; session sync disabled
    mock_dome.slew_to_azimuth.assert_called_with(77.0)
    mock_dome.park.assert_not_called()

    service.set_sequence_sync(True)
    await SessionExecutor(ctx, name="t").run([])
    assert mock_dome.open_shutter.await_count == 2
    mock_dome.park.assert_awaited_once()
