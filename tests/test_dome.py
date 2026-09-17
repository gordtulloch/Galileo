"""DOME — Dome Control (TC-DOME-010 … TC-DOME-030)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


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
def test_tc_dome_030_disable_slaving_for_third_party_hardware(dome_service):
    """DOME-030: Allow dome slaving to be disabled for domes controlled by independent third-party slaving hardware."""
    dome_service.set_slaving(enabled=True)
    assert dome_service.slaving_enabled is True

    dome_service.set_slaving(enabled=False)
    assert dome_service.slaving_enabled is False
    # When disabled, sync_to_mount must be a no-op
    dome_service._dome.slew_to_azimuth.reset_mock()

    import asyncio
    asyncio.get_event_loop().run_until_complete(dome_service.sync_to_mount())
    dome_service._dome.slew_to_azimuth.assert_not_called()
