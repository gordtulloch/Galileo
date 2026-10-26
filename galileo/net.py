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
