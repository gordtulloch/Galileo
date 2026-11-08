# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Saved external-notification settings (Options > Notifications; NOTIF-020, NOTIF-030, NOTIF-050).

Everything except the SMTP password lives in the shared database (``app_settings``, namespace ``notifications``); the
password goes to the OS credential store through ``keyring`` (NFR-SEC-030), never to the database.
"""

from __future__ import annotations

import logging
from typing import Any

from galileo.notify import (
    EmailChannel, NotificationEvent, NotificationService, NtfyChannel, SmsChannel, valid_ntfy_topic,
)

logger = logging.getLogger(__name__)

SECURITY_CHOICES = ("none", "starttls", "ssl")

DEFAULTS: dict[str, Any] = {
    "email_enabled": True,
    "sms_enabled": True,
    "email_address": "",          # where e-mail alerts go (the Observatory's contact details win, NOTIF-040)
    "phone_number": "",
    "smtp_host": "localhost",
    "smtp_port": 25,
    "smtp_security": "none",
    "smtp_username": "",
    "from_address": "",
    # Carrier e-mail-to-SMS gateway: a domain ("vtext.com", sent to <phone>@vtext.com) or a full
    # address template/value containing "@" used as-is.
    "sms_gateway": "",
    # ntfy push (https://ntfy.sh): the primary alert route; e-mail is its backup (sent only if the push fails).
    "ntfy_enabled": True,
    "ntfy_server": "https://ntfy.sh",
    "ntfy_topic": "",             # empty = ntfy not set up
    "email_backup_for_ntfy": True,
    # Event values switched off for external delivery, per channel (NOTIF-030).
    "email_disabled_events": [],
    "sms_disabled_events": [],
    "ntfy_disabled_events": [],
}

_KEYRING_SERVICE = "galileo-notify"
_KEYRING_SMTP_USER = "smtp"
_KEYRING_NTFY_TOKEN = "ntfy-token"  # noqa: S105 - keychain entry name, not a secret


NAMESPACE = "notifications"
LEGACY_FILE = "notifications.json"   # one-time import, then renamed *.migrated


def load_notify_settings() -> dict[str, Any]:
    """The saved settings, with a default for anything missing, unreadable or invalid."""
    settings = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    from galileo.settings_store import load_with_legacy
    raw = load_with_legacy(NAMESPACE, LEGACY_FILE)
    valid_events = {e.value for e in NotificationEvent}
    for key, default in DEFAULTS.items():
        value = raw.get(key)
        if isinstance(default, bool):
            if isinstance(value, bool):
                settings[key] = value
        elif isinstance(default, int):
            if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535:
                settings[key] = value
        elif isinstance(default, list):
            if isinstance(value, list):
                settings[key] = [v for v in value if v in valid_events]
        elif isinstance(value, str):
            settings[key] = value.strip()
    if settings["smtp_security"] not in SECURITY_CHOICES:
        settings["smtp_security"] = DEFAULTS["smtp_security"]
    return settings


def save_notify_settings(settings: dict[str, Any]) -> None:
    from galileo.settings_store import set_namespace
    set_namespace(NAMESPACE, {key: settings.get(key, default) for key, default in DEFAULTS.items()})


def get_smtp_password() -> str:
    """The SMTP password from the OS credential store ("" if unset or the store is unavailable)."""
    try:
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_SMTP_USER) or ""
    except Exception:
        logger.warning("Could not read the SMTP password from the OS keychain", exc_info=True)
        return ""


def set_smtp_password(password: str) -> None:
    """Store the SMTP password in the OS credential store (an empty string clears it)."""
    try:
        import keyring
        if password:
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_SMTP_USER, password)
        else:
            try:
                keyring.delete_password(_KEYRING_SERVICE, _KEYRING_SMTP_USER)
            except Exception:
                logger.debug("Could not delete the SMTP password from the OS keychain", exc_info=True)
    except Exception:
        logger.warning("Could not save the SMTP password to the OS keychain", exc_info=True)


def get_ntfy_token() -> str:
    """The optional ntfy access token from the OS credential store ("" if unset or unavailable)."""
    try:
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_NTFY_TOKEN) or ""
    except Exception:
        logger.warning("Could not read the ntfy token from the OS keychain", exc_info=True)
        return ""


def set_ntfy_token(token: str) -> None:
    """Store the ntfy access token in the OS credential store (an empty string clears it)."""
    try:
        import keyring
        if token:
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_NTFY_TOKEN, token)
        else:
            try:
                keyring.delete_password(_KEYRING_SERVICE, _KEYRING_NTFY_TOKEN)
            except Exception:
                logger.debug("Could not delete the ntfy token from the OS keychain", exc_info=True)
    except Exception:
        logger.warning("Could not save the ntfy token to the OS keychain", exc_info=True)


def generate_ntfy_topic() -> str:
    """A new unguessable topic name (anyone who knows the topic can read the alerts)."""
    import secrets
    return "galileo-" + secrets.token_urlsafe(16)


def sms_gateway_address(phone_number: str, gateway: str) -> str | None:
    """The e-mail-to-SMS address for *phone_number*: ``<digits>@<gateway>`` for a bare domain,
    or *gateway* itself when it already contains the phone part (``"{number}@txt.example"`` or
    a full address)."""
    gateway = (gateway or "").strip()
    if not gateway:
        return None
    digits = "".join(ch for ch in (phone_number or "") if ch.isdigit())
    if "{number}" in gateway:
        return gateway.replace("{number}", digits) if digits else None
    if "@" in gateway:
        return gateway
    return f"{digits}@{gateway}" if digits else None


def smtp_kwargs(settings: dict[str, Any], password: str | None = None) -> dict[str, Any]:
    """Keyword arguments for :class:`~galileo.notify.EmailChannel` from *settings*."""
    username = settings.get("smtp_username") or None
    pw = password if password is not None else (get_smtp_password() if username else "")
    return {
        "smtp_host": settings.get("smtp_host") or "localhost",
        "smtp_port": int(settings.get("smtp_port") or 25),
        "username": username, "password": pw or None,
        "security": settings.get("smtp_security", "none"),
        "sender": settings.get("from_address") or username or None,
    }


def build_channels(
    settings: dict[str, Any], contacts: Any = None, password: str | None = None,
    ntfy_token: str | None = None,
) -> list[tuple[str, Any]]:
    """The ``(kind, channel)`` pairs to deliver through, kind being ``"ntfy"``, ``"email"`` or ``"sms"``.

    ntfy is Master-wide (a topic, not a recipient), so the Observatory's channel choice does not
    narrow it. While ntfy is set up and ``email_backup_for_ntfy`` is on, the e-mail channel is not
    a separate pair: it is the ntfy channel's backup, used only when the push fails.

    The recipient e-mail / phone come from the owning Observatory's contact details when it has
    them (NOTIF-040) and from *settings* otherwise; the Observatory's channel choice (OBS-090)
    narrows the set further. SMS needs a gateway (see :func:`sms_gateway_address`)."""
    wanted = set(getattr(contacts, "channels", None) or ["email", "sms"])
    email = getattr(contacts, "email", None) or settings.get("email_address") or ""
    phone = getattr(contacts, "phone_number", None) or settings.get("phone_number") or ""
    kwargs = smtp_kwargs(settings, password)
    channels: list[tuple[str, Any]] = []
    email_channel = (
        EmailChannel(email, **kwargs) if settings.get("email_enabled") and "email" in wanted and email else None)
    topic = settings.get("ntfy_topic") or ""
    if settings.get("ntfy_enabled") and valid_ntfy_topic(topic):
        token = ntfy_token if ntfy_token is not None else get_ntfy_token()
        backup = email_channel if settings.get("email_backup_for_ntfy") else None
        channels.append(("ntfy", NtfyChannel(
            topic, settings.get("ntfy_server", ""), token or None, backup,
            settings.get("email_disabled_events", []) if backup else ())))
        if backup is not None:
            email_channel = None
    if email_channel is not None:
        channels.append(("email", email_channel))
    if settings.get("sms_enabled") and "sms" in wanted and phone:
        channels.append(("sms", SmsChannel(
            phone, sms_gateway_address(phone, settings.get("sms_gateway", "")), kwargs)))
    return channels


def configure_service(service: NotificationService, settings: dict[str, Any], contacts: Any = None) -> None:
    """Add the configured external channels to *service*, with the per-event switches applied."""
    for kind, channel in build_channels(settings, contacts):
        service.add_channel(channel)
        for value in settings.get(f"{kind}_disabled_events", []):
            try:
                service.set_channel_event_enabled(channel, NotificationEvent(value), False)
            except ValueError:
                continue
