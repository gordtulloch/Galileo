"""PHD2 event-server adapter (GUIDE-010 … GUIDE-090).

Speaks PHD2's "Event Server" protocol: newline-delimited JSON over TCP (port
4400 for the first PHD2 instance, 4401 for the second, …). PHD2 pushes
unsolicited *events* (``{"Event": "GuideStep", …}``) and answers *requests*
(``{"method": …, "id": n}``) with ``{"jsonrpc": "2.0", "result": …, "id": n}``
or an ``"error"`` object.

The transport is a plain socket plus one reader thread — the same shape as
``galileo.adapters.indi_client`` — so it works from the Qt UI thread, from the
sequencer's asyncio loop (via the ``async`` methods, which hop to a worker
thread) and from tests, without a Qt or event-loop dependency. Incoming events
go to a single ``on_event`` callback that runs on the reader thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
from collections.abc import Callable
from concurrent.futures import Future

from galileo.guiding import GuiderError

logger = logging.getLogger(__name__)

DEFAULT_PORT = 4400
_CONNECT_TIMEOUT_S = 3.0
_CALL_TIMEOUT_S = 10.0


class Phd2Error(GuiderError):
    """PHD2 rejected a request, or the connection failed."""


class Phd2Adapter:
    """One connection to one PHD2 instance (the ``GuiderAdapter`` port,
    SDD §4.14). Also usable as ``GuidingService._client``."""

    def __init__(self, host: str = "localhost", port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.on_event: Callable[[dict], None] | None = None
        self.on_disconnect: Callable[[], None] | None = None
        self._sock: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self._pending: dict[int, Future] = {}
        self._pending_lock = threading.Lock()
        self._next_id = 0
        self._settle_done = threading.Event()
        self._settle_result: dict | None = None

    # --- Connection -------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._sock is not None

    def open(self) -> None:
        """Blocking connect; raises ``Phd2Error`` if PHD2 isn't listening."""
        if self._sock is not None:
            return
        from galileo.adapters.alpaca import (
            resolve_mdns_host_sync,  # .local names on Windows
        )

        try:
            sock = socket.create_connection(
                (resolve_mdns_host_sync(self.host), self.port), timeout=_CONNECT_TIMEOUT_S
            )
        except OSError as exc:
            raise Phd2Error(f"Could not connect to PHD2 at {self.host}:{self.port}: {exc}") from exc
        sock.settimeout(None)
        self._sock = sock
        self._reader = threading.Thread(
            target=self._read_loop, args=(sock,), name=f"phd2-{self.host}:{self.port}", daemon=True
        )
        self._reader.start()
        logger.info("Connected to PHD2 at %s:%d", self.host, self.port)

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        self._fail_pending(Phd2Error("disconnected"))

    async def connect(self) -> None:
        await asyncio.to_thread(self.open)

    async def disconnect(self) -> None:
        await asyncio.to_thread(self.close)

    # --- Requests ---------------------------------------------------------

    def request(self, method: str, params=None) -> Future:
        """Send *method* and return a ``Future`` for its ``result``. Never
        blocks on the reply, so it is safe to call from the UI thread."""
        future: Future = Future()
        sock = self._sock
        if sock is None:
            future.set_exception(Phd2Error("not connected to PHD2"))
            return future
        with self._pending_lock:
            self._next_id += 1
            request_id = self._next_id
            self._pending[request_id] = future
        message: dict = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = params
        try:
            with self._send_lock:
                sock.sendall((json.dumps(message) + "\r\n").encode())
        except OSError as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            future.set_exception(Phd2Error(f"send failed: {exc}"))
        return future

    def call(self, method: str, params=None, timeout: float = _CALL_TIMEOUT_S):
        """Blocking ``request``; returns the ``result`` or raises ``Phd2Error``."""
        try:
            return self.request(method, params).result(timeout)
        except TimeoutError as exc:
            raise Phd2Error(f"PHD2 did not answer {method!r} within {timeout:g}s") from exc

    # --- GuiderAdapter port (async; what GuidingService/the sequencer call) --

    async def start_guiding(self, settle_pixels: float = 0.5, settle_time_s: float = 10,
                            settle_timeout_s: float = 60, recalibrate: bool = False) -> None:
        self._settle_done.clear()
        await asyncio.to_thread(
            self.call, "guide",
            [{"pixels": settle_pixels, "time": settle_time_s, "timeout": settle_timeout_s}, recalibrate],
        )

    async def stop_guiding(self) -> None:
        await asyncio.to_thread(self.call, "stop_capture")

    async def dither(self, amount_px: float = 3.0, ra_only: bool = False,
                     settle_pixels: float = 0.5, settle_time_s: float = 10,
                     settle_timeout_s: float = 60) -> None:
        self._settle_done.clear()
        await asyncio.to_thread(
            self.call, "dither",
            [amount_px, ra_only, {"pixels": settle_pixels, "time": settle_time_s, "timeout": settle_timeout_s}],
        )

    async def wait_for_settle(self, timeout_s: float = 60.0) -> bool:
        """Wait for PHD2's ``SettleDone`` after a ``guide``/``dither``. Raises
        ``Phd2Error`` if PHD2 reports the settle failed."""
        done = await asyncio.to_thread(self._settle_done.wait, timeout_s)
        result = self._settle_result or {}
        if done and result.get("Status", 0) != 0:
            raise Phd2Error(f"PHD2 settle failed: {result.get('Error', 'unknown error')}")
        return done

    # --- Reader thread ----------------------------------------------------

    def _read_loop(self, sock: socket.socket) -> None:
        buffer = b""
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if line:
                        self._dispatch(line)
        except OSError:
            pass
        finally:
            was_open = self._sock is sock
            if was_open:
                self._sock = None
            sock.close()
            self._fail_pending(Phd2Error("PHD2 connection closed"))
            if was_open:
                logger.warning("PHD2 connection to %s:%d closed", self.host, self.port)
                if self.on_disconnect is not None:
                    try:
                        self.on_disconnect()
                    except Exception:
                        logger.exception("PHD2 on_disconnect handler failed")

    def _dispatch(self, line: bytes) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            logger.debug("Ignoring non-JSON PHD2 line: %r", line[:200])
            return
        if not isinstance(message, dict):
            return
        if "Event" in message:
            if message["Event"] == "SettleDone":
                self._settle_result = message
                self._settle_done.set()
            if self.on_event is not None:
                try:
                    self.on_event(message)
                except Exception:
                    logger.exception("PHD2 event handler failed for %r", message.get("Event"))
            return
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return
        with self._pending_lock:
            future = self._pending.pop(request_id, None)
        if future is None:
            return
        if "error" in message:
            error = message["error"]
            future.set_exception(Phd2Error(error.get("message", str(error)) if isinstance(error, dict) else str(error)))
        else:
            future.set_result(message.get("result"))

    def _fail_pending(self, error: Exception) -> None:
        with self._pending_lock:
            pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(error)
