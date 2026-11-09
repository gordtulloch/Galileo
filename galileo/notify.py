# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Notification service — in-app and outbound channels (NOTIF-010 … NOTIF-040)."""

from __future__ import annotations

import asyncio
import logging
import re
from enum import StrEnum
from collections.abc import Callable
from galileo.net import http_request, urlopen_http

logger = logging.getLogger(__name__)


class NotificationEvent(StrEnum):
    SEQUENCE_COMPLETE = "sequence_complete"
    SEQUENCE_ERROR = "sequence_error"
    SAFETY_ABORT = "safety_abort"
    AUTOFOCUS_COMPLETE = "autofocus_complete"
    MERIDIAN_FLIP = "meridian_flip"
    SESSION_MESSAGE = "session_message"      # a session's Notification block (SES-150)


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
        import urllib.parse
        import urllib.request
        import json
        # urlopen also speaks file:// and ftp://; a webhook is an HTTP POST, so refuse anything else
        if urllib.parse.urlparse(self.url).scheme not in ("http", "https"):
            logger.error("WebhookChannel: refusing non-HTTP(S) webhook URL %r", self.url)
            return
        payload = json.dumps({
            "event": notification.event_type.value,
            "detail": notification.detail,
        }).encode()
        try:
            req = http_request(
                self.url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            await asyncio.to_thread(urlopen_http, req, 10)
        except Exception:
            logger.exception("WebhookChannel: failed to POST to %s", self.url)


class EmailChannel:
    """Outbound email notification channel (NOTIF-020), the narrower
    "email and/or SMS" channel set documented in SDD Section 4.19 —
    ``WebhookChannel`` above stays for EXT-070's separate, broader
    "webhook/email/push integrations" requirement."""

    def __init__(
        self,
        address: str,
        smtp_host: str = "localhost",
        smtp_port: int = 25,
        *,
        username: str | None = None,
        password: str | None = None,
        security: str = "none",
        sender: str | None = None,
    ) -> None:
        """*security* is ``"none"`` (plain SMTP), ``"starttls"`` or ``"ssl"`` (implicit TLS);
        *username*/*password* enable SMTP authentication; *sender* is the From address
        (defaults to *address*)."""
        self.address = address
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username or None
        self.password = password or None
        self.security = security
        self.sender = sender or None

    async def deliver(self, notification: _Notification) -> None:
        """Email *notification* to :attr:`address` via :attr:`smtp_host`; raises on failure
        (used by the Options > Notifications test button, which reports the error)."""
        import smtplib
        from email.message import EmailMessage

        message = EmailMessage()
        message["Subject"] = f"Galileo: {notification.event_type.value}"
        message["From"] = self.sender or self.address
        message["To"] = self.address
        message.set_content(f"{notification.event_type.value}: {notification.detail}")

        def _send_sync() -> None:
            if self.security == "ssl":
                smtp = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=10)
            else:
                smtp = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
            with smtp:
                if self.security == "starttls":
                    smtp.starttls()
                if self.username:
                    smtp.login(self.username, self.password or "")
                smtp.send_message(message)

        await asyncio.to_thread(_send_sync)

    async def send(self, notification: _Notification) -> None:
        """Like :meth:`deliver`, but a failure is logged rather than raised."""
        try:
            await self.deliver(notification)
        except Exception:
            logger.exception("EmailChannel: failed to send to %s", self.address)


class SmsChannel:
    """Outbound SMS notification channel (NOTIF-020), via a carrier
    email-to-SMS gateway (SDD Section 4.19's first suggested adapter option —
    needs no separate SMS API account/credentials). *gateway_address* is the
    phone's full email-to-SMS address (e.g. ``"5551234567@vtext.com"``); left
    unset, :meth:`send` logs that no gateway is configured rather than
    emailing a guessed, likely-wrong address."""

    def __init__(
        self, phone_number: str, gateway_address: str | None = None, email_channel_kwargs: dict | None = None,
    ) -> None:
        """*email_channel_kwargs* are the SMTP settings (host, port, credentials, …) of the
        :class:`EmailChannel` the gateway message is sent through."""
        self.phone_number = phone_number
        self.gateway_address = gateway_address
        self.email_channel_kwargs = dict(email_channel_kwargs or {})

    async def deliver(self, notification: _Notification) -> None:
        """As :meth:`send`, but SMTP failures raise (and a missing gateway raises ``ValueError``)."""
        if not self.gateway_address:
            raise ValueError("no email-to-SMS gateway configured")
        await EmailChannel(address=self.gateway_address, **self.email_channel_kwargs).deliver(notification)

    async def send(self, notification: _Notification) -> None:
        if not self.gateway_address:
            logger.warning(
                "SmsChannel: no email-to-SMS gateway configured for %s; message not sent.", self.phone_number,
            )
            return
        await EmailChannel(address=self.gateway_address, **self.email_channel_kwargs).send(notification)


_NTFY_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Title / priority / emoji tag per event for ntfy (priority 1-5; 5 makes the phone alert loudly).
_NTFY_STYLE: dict[NotificationEvent, tuple[str, int, str]] = {
    NotificationEvent.SEQUENCE_COMPLETE: ("Galileo: session complete", 3, "white_check_mark"),
    NotificationEvent.SEQUENCE_ERROR: ("Galileo: session error", 4, "x"),
    NotificationEvent.SAFETY_ABORT: ("Galileo: safety abort", 5, "rotating_light"),
    NotificationEvent.AUTOFOCUS_COMPLETE: ("Galileo: autofocus complete", 3, "mag"),
    NotificationEvent.MERIDIAN_FLIP: ("Galileo: meridian flip", 3, "arrows_counterclockwise"),
    NotificationEvent.SESSION_MESSAGE: ("Galileo: message", 3, "telescope"),
}


def valid_ntfy_topic(topic: str) -> bool:
    """True if *topic* is a legal ntfy topic name (1-64 letters, digits, ``_`` or ``-``)."""
    return bool(_NTFY_TOPIC_RE.match(topic or ""))


def normalise_ntfy_server(server: str) -> str:
    """*server* as an ``http(s)://host`` base URL without a trailing slash (a bare host gets
    ``https://``); the default public server when blank."""
    server = (server or "").strip().rstrip("/")
    if not server:
        return "https://ntfy.sh"
    return server if "://" in server else f"https://{server}"


class NtfyChannel:
    """Push notification to the phone's ntfy app (https://ntfy.sh): one HTTPS POST from this
    computer, no account, no relay of our own. Anyone who knows the *topic* can read the
    alerts, so it should be a long random string (the settings page can generate one).

    *backup*, if given, is another channel (the e-mail channel) used only when the push fails,
    except for events in *backup_disabled_events*."""

    def __init__(
        self, topic: str, server: str = "https://ntfy.sh", token: str | None = None,
        backup=None, backup_disabled_events: frozenset | set | tuple = (),
    ) -> None:
        self.topic = topic
        self.server = normalise_ntfy_server(server)
        self.token = token or None
        self.backup = backup
        self.backup_disabled_events = frozenset(backup_disabled_events)

    async def deliver(self, notification: _Notification) -> None:
        """POST the alert to the topic; raises on an invalid topic or any HTTP/network failure."""
        if not valid_ntfy_topic(self.topic):
            raise ValueError("invalid ntfy topic (use 1-64 letters, digits, - or _)")
        title, priority, tag = _NTFY_STYLE.get(
            notification.event_type, ("Galileo", 3, "telescope"))
        headers = {"Title": title, "Priority": str(priority), "Tags": tag}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = (notification.detail or title).encode("utf-8")
        req = http_request(f"{self.server}/{self.topic}", data=body, headers=headers, method="POST")

        def _post() -> None:
            with urlopen_http(req, 10):
                pass

        await asyncio.to_thread(_post)

    async def send(self, notification: _Notification) -> None:
        """As :meth:`deliver`, but a failure is logged and handed to the backup channel."""
        try:
            await self.deliver(notification)
            return
        except Exception:
            logger.exception("NtfyChannel: failed to push to %s", self.server)
        if self.backup is None or notification.event_type in self.backup_disabled_events:
            return
        logger.warning("NtfyChannel: sending the alert through the backup channel instead")
        await self.backup.send(notification)


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
