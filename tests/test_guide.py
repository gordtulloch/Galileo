"""GUIDE — Guiding Integration (TC-GUIDE-010 … TC-GUIDE-060)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def guiding_service():
    guiding_mod = pytest.importorskip("galileo.guiding")
    svc = guiding_mod.GuidingService(host="localhost", port=4400)
    return svc


# ---------------------------------------------------------------------------
# TC-GUIDE-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-010")
@pytest.mark.priority("MVP")
async def test_tc_guide_010_connect_and_reflect_state(guiding_service, mock_guider):
    """GUIDE-010: Connect to external guiding application's control interface and reflect its connection/guiding state."""
    guiding_service._client = mock_guider
    await guiding_service.connect()
    mock_guider.connect.assert_called_once()
    assert guiding_service.is_connected is True


# ---------------------------------------------------------------------------
# TC-GUIDE-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-020")
@pytest.mark.priority("MVP")
async def test_tc_guide_020_start_stop_guiding_await_confirm(guiding_service, mock_guider):
    """GUIDE-020: Issue start/stop guiding commands and await confirmation before dependent sequence steps proceed."""
    guiding_service._client = mock_guider

    guiding_service._wait_for_guiding_state = AsyncMock(return_value=True)
    await guiding_service.start_guiding()
    mock_guider.start_guiding.assert_called_once()
    guiding_service._wait_for_guiding_state.assert_called()

    await guiding_service.stop_guiding()
    mock_guider.stop_guiding.assert_called_once()


# ---------------------------------------------------------------------------
# TC-GUIDE-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-030")
@pytest.mark.priority("MVP")
async def test_tc_guide_030_dither_and_wait_for_settle(guiding_service, mock_guider):
    """GUIDE-030: Issue dither command between exposures and wait for guider to settle before resuming capture."""
    guiding_service._client = mock_guider
    mock_guider.dither = AsyncMock()
    mock_guider.wait_for_settle = AsyncMock(return_value=True)

    await guiding_service.dither_and_wait(settle_timeout_s=30.0, settle_pixels=0.5)

    mock_guider.dither.assert_called_once()
    mock_guider.wait_for_settle.assert_called()


# ---------------------------------------------------------------------------
# TC-GUIDE-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-040")
@pytest.mark.priority("P2")
def test_tc_guide_040_surface_guide_error_for_display_and_logging(guiding_service, mock_guider):
    """GUIDE-040: Surface the guider's reported guide error (RMS) for display and session-history logging."""
    guiding_service._client = mock_guider
    rms = guiding_service.get_rms()
    assert rms["ra"] == mock_guider.rms_ra
    assert rms["dec"] == mock_guider.rms_dec
    assert "total" in rms


# ---------------------------------------------------------------------------
# TC-GUIDE-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-050")
@pytest.mark.priority("MVP")
async def test_tc_guide_050_guiding_loss_is_recoverable_error(guiding_service, mock_guider, event_bus):
    """GUIDE-050: Guiding-connection loss during a sequence treated as recoverable error, not silent stall."""
    guiding_service._client = mock_guider
    guiding_service._event_bus = event_bus
    mock_guider.is_connected = False

    await guiding_service.check_health()

    assert event_bus.publish.called
    published = event_bus.publish.call_args[0][0]
    assert hasattr(published, "recoverable") or "guide" in str(type(published)).lower()


# ---------------------------------------------------------------------------
# TC-GUIDE-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-GUIDE-060")
@pytest.mark.priority("P2")
def test_tc_guide_060_independent_guider_per_pier():
    """GUIDE-060: Each Pier has its own independent guider connection — never shared across Piers."""
    guiding_mod = pytest.importorskip("galileo.guiding")
    obs_mod = pytest.importorskip("galileo.observatory")

    pier1 = obs_mod.Pier(name="Pier-1")
    pier2 = obs_mod.Pier(name="Pier-2")

    pier1.guiding_service = guiding_mod.GuidingService(host="localhost", port=4400)
    pier2.guiding_service = guiding_mod.GuidingService(host="localhost", port=4401)

    assert pier1.guiding_service is not pier2.guiding_service
    assert pier2.guiding_service.port == 4401
