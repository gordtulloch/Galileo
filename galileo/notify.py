# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Notification service — in-app and outbound channels (NOTIF-010 … NOTIF-030)."""

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


class NotificationService:
    """Routes events to in-app subscribers and external channels (NOTIF-010 … NOTIF-030)."""

    def __init__(self) -> None:
        self.channels: list = []
        self._subscribers: list[Callable] = []
        # Per-channel per-event enable/disable map
        self._channel_disabled: dict[tuple, bool] = {}

    def add_channel(self, channel) -> None:
        self.channels.append(channel)

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
