# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""NOTIF — Notifications (TC-NOTIF-010 … TC-NOTIF-040).

External delivery is narrowed to email and/or text message (SMS) as the two
concrete channels, delivered using the contact details configured on the
Observatory the triggering Pier/session belongs to (OBS-090), not a separate
per-notification contact configuration.
"""

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
async def test_tc_notif_020_external_delivery_via_email_and_sms(notif_service):
    """NOTIF-020: Support external delivery via email and/or text message (SMS), configurable by the user, delivering the same event set as NOTIF-010."""
    notify_mod = pytest.importorskip("galileo.notify")
    email = notify_mod.EmailChannel(address="operator@example.com")
    email.send = AsyncMock()
    sms = notify_mod.SmsChannel(phone_number="+15551234567")
    sms.send = AsyncMock()

    notif_service.add_channel(email)
    notif_service.add_channel(sms)
    await notif_service.emit(notify_mod.NotificationEvent.SEQUENCE_COMPLETE, detail="Done")

    email.send.assert_called_once()
    sms.send.assert_called_once()
    sent_payload = email.send.call_args[0][0]
    assert "SEQUENCE_COMPLETE" in str(sent_payload).upper() or "complete" in str(sent_payload).lower()


# ---------------------------------------------------------------------------
# TC-NOTIF-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-NOTIF-030")
@pytest.mark.priority("P3")
async def test_tc_notif_030_per_event_per_channel_enable_disable(notif_service):
    """NOTIF-030: Allow notification events to be individually enabled/disabled per channel."""
    notify_mod = pytest.importorskip("galileo.notify")

    email = notify_mod.EmailChannel(address="operator@example.com")
    email.send = AsyncMock()
    notif_service.add_channel(email)

    # Disable SEQUENCE_ERROR on this channel
    notif_service.set_channel_event_enabled(email, notify_mod.NotificationEvent.SEQUENCE_ERROR, enabled=False)

    await notif_service.emit(notify_mod.NotificationEvent.SEQUENCE_ERROR, detail="test error")
    email.send.assert_not_called()

    await notif_service.emit(notify_mod.NotificationEvent.SEQUENCE_COMPLETE, detail="done")
    email.send.assert_called_once()


# ---------------------------------------------------------------------------
# TC-NOTIF-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-NOTIF-040")
@pytest.mark.priority("P3")
async def test_tc_notif_040_reads_contact_details_from_owning_observatory(notif_service):
    """NOTIF-040: Read external-delivery contact details (email address, phone/SMS number, and which channel(s) to use) from the Observatory record (OBS-090) that owns the Pier/session raising the event, rather than maintaining a separate per-notification contact configuration."""
    pytest.importorskip("galileo.notify")
    obs_mod = pytest.importorskip("galileo.observatory")

    observatory = obs_mod.Observatory(name="Backyard")
    observatory.set_contact_details(
        email="operator@example.com", phone_number="+15551234567", channels=["email", "sms"],
    )
    pier = obs_mod.Pier(name="Pier-1")
    observatory.add_pier(pier)

    notif_service.set_owning_observatory(observatory)

    sent = notif_service.resolve_delivery_contacts(pier=pier)
    assert sent.email == "operator@example.com"
    assert sent.phone_number == "+15551234567"
    assert sent.channels == ["email", "sms"]
