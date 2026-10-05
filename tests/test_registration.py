# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Tests for galileo.registration — the startup usage-tracking ping.

Not tied to an SRS requirement (ported from AstroFiler as an undocumented,
hardcoded "per project decision" feature, same as there); exercises the
ini opt-out, the handshake payload, and that failures never raise.
"""

from __future__ import annotations

import socket

import pytest

from galileo import registration
from galileo.library.config import set_config_path


@pytest.fixture(autouse=True)
def _reset_config_path():
    yield
    set_config_path(None)


def test_ping_once_sends_the_handshake_over_a_tcp_connection():
    received: list[bytes] = []

    def handler(conn: socket.socket) -> None:
        received.append(conn.recv(1024))
        conn.close()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        host, port = server.getsockname()

        import threading
        t = threading.Thread(target=lambda: handler(server.accept()[0]), daemon=True)
        t.start()

        registration.ping_once(host, port, timeout_seconds=2.0)
        t.join(timeout=2.0)

    assert received == [registration.REGISTRATION_HANDSHAKE.encode("utf-8")]


def test_ping_once_raises_on_connection_failure():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        _, unused_port = probe.getsockname()

    with pytest.raises(OSError):
        registration.ping_once("127.0.0.1", unused_port, timeout_seconds=0.5)


def test_ini_allows_registration_by_default(tmp_path):
    set_config_path(tmp_path / "library.ini")
    assert registration._ini_allows_registration() is True


def test_ini_disables_registration_when_set_false(tmp_path):
    ini = tmp_path / "library.ini"
    ini.write_text("[DEFAULT]\nRegistration = False\n", encoding="utf-8")
    set_config_path(ini)
    assert registration._ini_allows_registration() is False


def test_start_startup_ping_never_raises_even_on_failure(monkeypatch, tmp_path):
    set_config_path(tmp_path / "library.ini")

    def boom(*args, **kwargs):
        raise OSError("no such host")

    monkeypatch.setattr(registration, "ping_once", boom)

    messages: list[str] = []
    thread_holder = []

    import threading
    original_thread = threading.Thread

    def capturing_thread(*args, **kwargs):
        t = original_thread(*args, **kwargs)
        thread_holder.append(t)
        return t

    monkeypatch.setattr(registration.threading, "Thread", capturing_thread)

    registration.start_startup_ping(status_callback=messages.append)
    thread_holder[0].join(timeout=2.0)

    assert messages == ["Pinging registration server..."]


def test_start_startup_ping_respects_ini_opt_out(monkeypatch, tmp_path):
    ini = tmp_path / "library.ini"
    ini.write_text("[DEFAULT]\nRegistration = False\n", encoding="utf-8")
    set_config_path(ini)

    called = []
    monkeypatch.setattr(registration, "ping_once", lambda *a, **k: called.append(True))

    import threading
    thread_holder = []
    original_thread = threading.Thread

    def capturing_thread(*args, **kwargs):
        t = original_thread(*args, **kwargs)
        thread_holder.append(t)
        return t

    monkeypatch.setattr(registration.threading, "Thread", capturing_thread)

    registration.start_startup_ping()
    thread_holder[0].join(timeout=2.0)

    assert called == []
