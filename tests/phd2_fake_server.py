"""A tiny stand-in for PHD2's event server (newline-delimited JSON over TCP).

Answers requests from a ``responses`` table (a value, or a callable taking the
request's params), records every request it receives, and lets a test push
unsolicited events to whoever is connected — enough to drive the real
``Phd2Adapter`` socket path without PHD2.
"""

from __future__ import annotations

import json
import socket
import threading
import time


class FakePhd2Server:
    def __init__(self) -> None:
        self.responses: dict = {
            "get_app_state": "Stopped",
            "get_connected": True,
            "get_exposure": 2000,
            "get_exposure_durations": [500, 1000, 2000, 3000],
            "get_pixel_scale": 2.0,
            "get_camera_frame_size": [640, 480],
            "get_dec_guide_mode": "Auto",
            "get_calibrated": False,
        }
        self.received: list[tuple[str, object]] = []
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen()
        self.port = self._listener.getsockname()[1]
        self._closed = False
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def push(self, event: dict) -> None:
        line = (json.dumps(event) + "\r\n").encode()
        with self._lock:
            for client in list(self._clients):
                try:
                    client.sendall(line)
                except OSError:
                    pass

    def drop_clients(self) -> None:
        """Hang up on every client, as if PHD2 had quit."""
        with self._lock:
            clients, self._clients = self._clients, []
        for client in clients:
            client.close()

    def wait_for_request(self, method: str, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(m == method for m, _ in self.received):
                return True
            time.sleep(0.01)
        return False

    def close(self) -> None:
        self._closed = True
        self._listener.close()
        self.drop_clients()

    def _accept_loop(self) -> None:
        while not self._closed:
            try:
                client, _ = self._listener.accept()
            except OSError:
                return
            with self._lock:
                self._clients.append(client)
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()
            self.push({"Event": "Version", "PHDVersion": "2.6.13", "PHDSubver": "", "MsgVersion": 1})

    def _serve(self, client: socket.socket) -> None:
        buffer = b""
        try:
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip():
                        self._answer(client, json.loads(line))
        except OSError:
            return

    def _answer(self, client: socket.socket, request: dict) -> None:
        method, params = request["method"], request.get("params")
        self.received.append((method, params))
        if method in self.responses:
            value = self.responses[method]
            reply = {"jsonrpc": "2.0", "result": value(params) if callable(value) else value, "id": request["id"]}
        else:
            reply = {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"unknown method {method}"}, "id": request["id"]}
        try:
            client.sendall((json.dumps(reply) + "\r\n").encode())
        except OSError:
            pass
