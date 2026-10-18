# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Alpaca adapter(s): UDP discovery of Alpaca devices on the LAN."""

from __future__ import annotations

import asyncio
import json
import logging
import socket

logger = logging.getLogger(__name__)


_ALPACA_DISCOVERY_PORT = 32227


_ALPACA_DISCOVERY_MSG = b"alpacadiscovery1"


class AlpacaDiscovery:
    """Discovers Alpaca devices on the LAN via UDP broadcast (ARCH-050)."""

    async def discover(self, timeout_s: float = 2.0) -> list[dict]:
        return await self._raw_discover(timeout_s)

    async def _raw_discover(self, timeout_s: float = 2.0) -> list[dict]:
        loop = asyncio.get_event_loop()

        def _broadcast() -> list[dict]:
            found: list[dict] = []
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    sock.settimeout(timeout_s)
                    sock.sendto(_ALPACA_DISCOVERY_MSG, ("<broadcast>", _ALPACA_DISCOVERY_PORT))
                    while True:
                        try:
                            data, addr = sock.recvfrom(1024)
                            resp = json.loads(data.decode())
                            resp["_host"] = addr[0]
                            found.append(resp)
                        except TimeoutError:
                            break
            except Exception as exc:
                logger.debug("Alpaca discovery error: %s", exc)
            return found

        return await loop.run_in_executor(None, _broadcast)
