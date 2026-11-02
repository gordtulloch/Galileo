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


def is_loopback(address: str) -> bool:
    """True for an address that only ever means "this machine" (PROF-130, GUIDE-100): ``localhost``,
    ``127.0.0.0/8``, ``::1`` and ``0.0.0.0``. A host name is not resolved -- only literals are judged,
    so a value copied from another node cannot cause a lookup."""
    import ipaddress
    host = address.strip().lower()
    if "://" in host:
        host = urlparse(host).hostname or ""
    elif host.startswith("["):                       # [v6] or [v6]:port
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:                       # host:port (a bare IPv6 literal has several colons)
        host = host.split(":", 1)[0]
    if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


class LoopbackGuard:
    """Namespace for the check, as named in the design (SDD 4.32)."""

    is_loopback = staticmethod(is_loopback)
