"""NOTIF — Notifications (TC-NOTIF-010 … TC-NOTIF-030)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def notif_service():
    notify_mod = pytest.importorskip("galileo.notify")
    svc = notify_mod.NotificationService()
    return svc


# ---------------------------------------------------------------------------
# TC-NOTIF-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-NOTIF-010")
@pytest.mark.priority("P2")
async def test_tc_notif_010_in_app_notifications_for_key_events(notif_service, event_bus):
    """NOTIF-010: Raise in-app notification for sequence completion, sequence error/abort, and safety abort."""
    notify_mod = pytest.importorskip("galileo.notify")
    received = []
    notif_service.subscribe(lambda event: received.append(event))

    await notif_service.emit(notify_mod.NotificationEvent.SEQUENCE_COMPLETE, detail="M42 Ha done")
    await notif_service.emit(notify_mod.NotificationEvent.SEQUENCE_ERROR, detail="CCD timeout")
    await notif_service.emit(notify_mod.NotificationEvent.SAFETY_ABORT, detail="Rain detected")

    assert len(received) == 3
    event_types = [e.event_type for e in received]
    assert notify_mod.NotificationEvent.SEQUENCE_COMPLETE in event_types
    assert notify_mod.NotificationEvent.SAFETY_ABORT in event_types


# ---------------------------------------------------------------------------
# TC-NOTIF-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-NOTIF-020")
@pytest.mark.priority("P3")
async def test_tc_notif_020_external_notification_channel(notif_service):
    """NOTIF-020: Support at least one external notification channel (webhook/push); deliver same event set."""
    notify_mod = pytest.importorskip("galileo.notify")
    webhook = notify_mod.WebhookChannel(url="https://example.com/hook")
    webhook.send = AsyncMock()

    notif_service.add_channel(webhook)
    await notif_service.emit(notify_mod.NotificationEvent.SEQUENCE_COMPLETE, detail="Done")

    webhook.send.assert_called_once()
    sent_payload = webhook.send.call_args[0][0]
    assert "SEQUENCE_COMPLETE" in str(sent_payload).upper() or "complete" in str(sent_payload).lower()


# ---------------------------------------------------------------------------
# TC-NOTIF-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-NOTIF-030")
@pytest.mark.priority("P3")
async def test_tc_notif_030_per_event_per_channel_enable_disable(notif_service):
    """NOTIF-030: Allow notification events to be individually enabled/disabled per channel."""
    notify_mod = pytest.importorskip("galileo.notify")

    webhook = notify_mod.WebhookChannel(url="https://example.com/hook")
    webhook.send = AsyncMock()
    notif_service.add_channel(webhook)

    # Disable SEQUENCE_ERROR on this channel
    notif_service.set_channel_event_enabled(webhook, notify_mod.NotificationEvent.SEQUENCE_ERROR, enabled=False)

    await notif_service.emit(notify_mod.NotificationEvent.SEQUENCE_ERROR, detail="test error")
    webhook.send.assert_not_called()

    await notif_service.emit(notify_mod.NotificationEvent.SEQUENCE_COMPLETE, detail="done")
    webhook.send.assert_called_once()
