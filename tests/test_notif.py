# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""NOTIF — Notifications (TC-NOTIF-010 … TC-NOTIF-040).

External delivery is narrowed to email and/or text message (SMS) as the two
concrete channels, delivered using the contact details configured on the
Observatory the triggering Pier/session belongs to (OBS-090), not a separate
per-notification contact configuration.
"""

import pytest
from unittest.mock import AsyncMock


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


# ---------------------------------------------------------------------------
# TC-NOTIF-050
# ---------------------------------------------------------------------------

@pytest.fixture
def notify_cfg(tmp_path, monkeypatch, settings_db):
    """Config folder in tmp, and an in-memory stand-in for the OS credential store."""
    import galileo.notify_settings as ns
    store: dict = {}
    monkeypatch.setattr(ns, "get_smtp_password", lambda: store.get("pw", ""))
    monkeypatch.setattr(ns, "set_smtp_password", lambda pw: store.__setitem__("pw", pw))
    return tmp_path, store


@pytest.mark.requirement("TC-NOTIF-050")
@pytest.mark.priority("P3")
def test_tc_notif_050_settings_persist_and_password_not_in_file(notify_cfg):
    """NOTIF-050: Notification delivery settings persist; the SMTP password is kept in the credential store, not the file."""
    import galileo.notify_settings as ns
    _tmp_path, _store = notify_cfg
    settings = ns.load_notify_settings()
    assert settings["smtp_host"] == "localhost"
    settings.update(email_address="me@example.com", smtp_host="smtp.example.com", smtp_port=587,
                    smtp_security="starttls", smtp_username="me", sms_disabled_events=["meridian_flip", "bogus"])
    ns.save_notify_settings(settings)
    ns.set_smtp_password("s3cret")

    from galileo.settings_store import get_namespace
    text = repr(get_namespace("notifications"))
    assert "s3cret" not in text
    loaded = ns.load_notify_settings()
    assert loaded["smtp_host"] == "smtp.example.com"
    assert loaded["smtp_security"] == "starttls"
    assert loaded["sms_disabled_events"] == ["meridian_flip"]   # unknown event dropped
    assert ns.get_smtp_password() == "s3cret"


@pytest.mark.requirement("TC-NOTIF-050")
@pytest.mark.priority("P3")
async def test_tc_notif_050_configure_service_applies_channels_and_event_switches(notify_cfg):
    """NOTIF-050: The configured channels are built (Observatory contacts win) and per-event switches applied."""
    import galileo.notify as notify_mod
    import galileo.notify_settings as ns
    from galileo.observatory import ContactDetails
    settings = ns.load_notify_settings()
    settings.update(email_address="fallback@example.com", phone_number="5551234567", sms_gateway="vtext.com",
                    smtp_username="me", email_disabled_events=["autofocus_complete"])
    ns.set_smtp_password("pw")

    service = notify_mod.NotificationService()
    ns.configure_service(service, settings, ContactDetails(email="op@example.com", channels=["email", "sms"]))
    email, sms = service.channels
    assert email.address == "op@example.com" and email.username == "me" and email.password == "pw"
    assert sms.gateway_address == "5551234567@vtext.com"

    sent = []

    async def fake_deliver(self, n):
        sent.append((self.address, n.event_type))

    notify_mod.EmailChannel.deliver = fake_deliver   # restored below
    try:
        await service.emit(notify_mod.NotificationEvent.AUTOFOCUS_COMPLETE)
        await service.emit(notify_mod.NotificationEvent.SEQUENCE_ERROR)
    finally:
        del notify_mod.EmailChannel.deliver
    # e-mail skipped the disabled event; the SMS (via its gateway e-mail) got both
    assert ("op@example.com", notify_mod.NotificationEvent.AUTOFOCUS_COMPLETE) not in sent
    assert ("op@example.com", notify_mod.NotificationEvent.SEQUENCE_ERROR) in sent
    assert len([s for s in sent if s[0] == "5551234567@vtext.com"]) == 2


@pytest.mark.requirement("TC-NOTIF-050")
@pytest.mark.priority("P3")
def test_tc_notif_050_test_send_reports_errors_and_missing_recipient(notify_cfg):
    """NOTIF-050: The test-send reports a missing recipient and SMTP failures instead of raising."""
    import galileo.notify_settings as ns
    from galileo.ui.app_window._notifications_page import run_test_send
    settings = ns.load_notify_settings()
    assert "e-mail address" in run_test_send("email", settings, "")
    settings.update(email_address="me@example.com", smtp_host="127.0.0.1", smtp_port=1)  # nothing listens
    assert run_test_send("email", settings, "") != ""
    settings.update(phone_number="5551234567", sms_gateway="")
    assert "gateway" in run_test_send("sms", settings, "")


@pytest.mark.requirement("TC-NOTIF-050")
@pytest.mark.priority("P3")
def test_tc_notif_050_session_runner_uses_saved_settings(notify_cfg):
    """NOTIF-050: The session runner's notification service is built from the saved settings."""
    import galileo.notify_settings as ns
    from galileo.ui.session_runner import _build_notify_service
    settings = ns.load_notify_settings()
    settings.update(email_address="me@example.com", sms_enabled=False)
    ns.save_notify_settings(settings)

    class _Win:
        _current_observatory = None

    service = _build_notify_service(_Win())
    assert [type(c).__name__ for c in service.channels] == ["EmailChannel"]
    assert service.channels[0].address == "me@example.com"
