# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Notification service — in-app and outbound channels (NOTIF-010 … NOTIF-040)."""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from collections.abc import Callable

logger = logging.getLogger(__name__)


class NotificationEvent(str, Enum):
    SEQUENCE_COMPLETE = "sequence_complete"
    SEQUENCE_ERROR = "sequence_error"
    SAFETY_ABORT = "safety_abort"
    AUTOFOCUS_COMPLETE = "autofocus_complete"
    MERIDIAN_FLIP = "meridian_flip"


class _Notification:
    def __init__(self, event_type: NotificationEvent, detail: str) -> None:
        self.event_type = event_type
        self.detail = detail

    def __repr__(self) -> str:
        return f"Notification({self.event_type.value!r}, {self.detail!r})"


class WebhookChannel:
    """Outbound webhook notification channel (NOTIF-020)."""

    def __init__(self, url: str) -> None:
        self.url = url

    async def send(self, notification: _Notification) -> None:
        """POST the notification payload to the configured URL."""
        import urllib.request
        import json
        payload = json.dumps({
            "event": notification.event_type.value,
            "detail": notification.detail,
        }).encode()
        try:
            req = urllib.request.Request(
                self.url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            await asyncio.to_thread(urllib.request.urlopen, req, None, 10)
        except Exception:
            logger.exception("WebhookChannel: failed to POST to %s", self.url)


class EmailChannel:
    """Outbound email notification channel (NOTIF-020), the narrower
    "email and/or SMS" channel set documented in SDD Section 4.19 —
    ``WebhookChannel`` above stays for EXT-070's separate, broader
    "webhook/email/push integrations" requirement."""

    def __init__(self, address: str, smtp_host: str = "localhost", smtp_port: int = 25) -> None:
        self.address = address
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port

    async def send(self, notification: _Notification) -> None:
        """Email *notification* to :attr:`address` via :attr:`smtp_host`."""
        import smtplib
        from email.message import EmailMessage

        message = EmailMessage()
        message["Subject"] = f"Galileo: {notification.event_type.value}"
        message["From"] = self.address
        message["To"] = self.address
        message.set_content(f"{notification.event_type.value}: {notification.detail}")

        def _send_sync() -> None:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as smtp:
                smtp.send_message(message)

        try:
            await asyncio.to_thread(_send_sync)
        except Exception:
            logger.exception("EmailChannel: failed to send to %s", self.address)


class SmsChannel:
    """Outbound SMS notification channel (NOTIF-020), via a carrier
    email-to-SMS gateway (SDD Section 4.19's first suggested adapter option —
    needs no separate SMS API account/credentials). *gateway_address* is the
    phone's full email-to-SMS address (e.g. ``"5551234567@vtext.com"``); left
    unset, :meth:`send` logs that no gateway is configured rather than
    emailing a guessed, likely-wrong address."""

    def __init__(self, phone_number: str, gateway_address: str | None = None) -> None:
        self.phone_number = phone_number
        self.gateway_address = gateway_address

    async def send(self, notification: _Notification) -> None:
        if not self.gateway_address:
            logger.warning(
                "SmsChannel: no email-to-SMS gateway configured for %s; message not sent.", self.phone_number,
            )
            return
        await EmailChannel(address=self.gateway_address).send(notification)


class NotificationService:
    """Routes events to in-app subscribers and external channels (NOTIF-010 … NOTIF-040)."""

    def __init__(self) -> None:
        self.channels: list = []
        self._subscribers: list[Callable] = []
        # Per-channel per-event enable/disable map
        self._channel_disabled: dict[tuple, bool] = {}
        self._observatory = None

    def add_channel(self, channel) -> None:
        self.channels.append(channel)

    def set_owning_observatory(self, observatory) -> None:
        """Bind this service to the ``galileo.observatory.Observatory``
        whose contact details (OBS-090) external delivery should read
        (NOTIF-040)."""
        self._observatory = observatory

    def resolve_delivery_contacts(self, pier=None):
        """Return the owning Observatory's :class:`~galileo.observatory.ContactDetails`
        (NOTIF-040) — external delivery always reads contact details from
        the Observatory that owns the raising Pier/session, never a separate
        per-notification configuration, and the same way regardless of which
        Pier that is (accepted for context/forward compatibility; a single
        Observatory has one operator to reach, per OBS-090). Returns an
        empty :class:`~galileo.observatory.ContactDetails` if no Observatory
        is bound yet or it has none set."""
        from galileo.observatory import ContactDetails

        if self._observatory is None or self._observatory.contact_details is None:
            return ContactDetails()
        return self._observatory.contact_details

    def subscribe(self, handler: Callable) -> None:
        self._subscribers.append(handler)

    def set_channel_event_enabled(
        self,
        channel,
        event_type: NotificationEvent,
        enabled: bool,
    ) -> None:
        key = (id(channel), event_type)
        self._channel_disabled[key] = not enabled

    async def emit(self, event_type: NotificationEvent, detail: str = "") -> None:
        """Emit *event_type* to all in-app subscribers and enabled channels."""
        notification = _Notification(event_type, detail)

        # In-app subscribers
        for handler in self._subscribers:
            try:
                handler(notification)
            except Exception:
                logger.exception("Notification subscriber raised")

        # External channels
        for channel in self.channels:
            key = (id(channel), event_type)
            if self._channel_disabled.get(key, False):
                continue
            try:
                await channel.send(notification)
            except Exception:
                logger.exception("Channel %r failed to send notification", channel)
