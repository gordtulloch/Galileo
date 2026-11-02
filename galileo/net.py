# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Shared HTTP helper: ``urllib`` opens only ever speak http(s).

``urllib.request.urlopen`` also honours ``file:`` and custom schemes, which is never wanted for the
configurable URLs this app opens (Alpaca hosts, webhooks, a plate-solver web service, catalog
downloads). Every ``urllib`` fallback goes through :func:`urlopen_http` so that is enforced in one place.
"""
from __future__ import annotations

import urllib.request
from typing import Any
from urllib.parse import urlparse

_ALLOWED_SCHEMES = ("http", "https")


def check_http_url(url: str) -> str:
    """Return *url* unchanged if it is http(s); raise ``ValueError`` otherwise."""
    if urlparse(url).scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Refusing non-HTTP URL: {url!r}")
    return url


def http_request(url: str, **kwargs: Any) -> urllib.request.Request:
    """``urllib.request.Request`` for an http(s) *url* only."""
    return urllib.request.Request(check_http_url(url), **kwargs)  # noqa: S310 - scheme checked above


def urlopen_http(req: str | urllib.request.Request, timeout: float | None = None, data: bytes | None = None):
    """``urllib.request.urlopen`` restricted to http(s) URLs (usable as a context manager)."""
    check_http_url(req if isinstance(req, str) else req.full_url)
    return urllib.request.urlopen(req, data, timeout)  # noqa: S310 - scheme checked above


# --- Loopback guard (PROF-130, GUIDE-100) ------------------------------------------------------

def _host_of(address: str) -> str:
    """The host part of ``host``, ``host:port``, ``[v6]:port`` or a URL."""
    text = address.strip()
    if "://" in text:
        text = urlparse(text).netloc
    text = text.rsplit("@", 1)[-1]
    if text.startswith("["):
        return text[1:].split("]", 1)[0]
    if text.count(":") == 1:                       # host:port (a bare IPv6 literal has several colons)
        text = text.split(":", 1)[0]
    return text.strip().rstrip(".")


def is_loopback(address: str) -> bool:
    """Whether *address* names this machine itself — ``localhost``, ``127.0.0.0/8``, ``::1`` or
    ``0.0.0.0`` (also with a port, in brackets, or as a URL). A stored device address that is loopback
    means a different machine on every node, so it is refused wherever a user enters one. Only literals
    and the name ``localhost`` are judged; no name is resolved."""
    import ipaddress
    host = _host_of(address).lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback or (ip.is_unspecified and ip.version == 4)


LOOPBACK_MESSAGE = ("This is the address of this machine itself. Enter the machine's real host name or LAN "
                    "address instead, so the same setting works on every node.")


def loopback_message(address: str) -> str:
    """The refusal text for a loopback *address*, or an empty string when it is acceptable."""
    return LOOPBACK_MESSAGE if is_loopback(address) else ""
