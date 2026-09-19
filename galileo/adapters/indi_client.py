# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Native INDI protocol client (galileo.adapters.indi_client).

Speaks the INDI XML wire protocol (v1.7) directly over TCP, so INDI support
works on every platform Galileo targets — including Windows, where
``pyindi-client`` (a SWIG wrapper around the libindi C++ library) cannot be
built because libindi has no Windows port.

Threading model (SDD §2.3): one reader thread per server connection owns the
socket, parses the incoming XML stream, and maintains a thread-safe property
cache. Callers — including the Qt UI, which runs adapter calls in short-lived
``asyncio.run`` event loops — use the blocking, thread-safe API here (usually
wrapped in ``asyncio.to_thread`` by the adapters), so nothing depends on one
long-lived event loop. Connections are shared per ``(host, port)`` through
:func:`acquire_client` / :func:`release_client` because an INDI server streams
its entire property set to every new client, which makes reconnecting per
call slow.
"""

from __future__ import annotations

import base64
import logging
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
import zlib
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable
from xml.sax.saxutils import escape, quoteattr

from galileo.exceptions import DeviceConnectionError, DeviceTimeoutError

logger = logging.getLogger(__name__)

DEFAULT_PORT = 7624
PROTOCOL_VERSION = "1.7"

# Property states (INDI ``state`` attribute).
IDLE, OK, BUSY, ALERT = "Idle", "Ok", "Busy", "Alert"

# ``DRIVER_INTERFACE`` bit mask (indidevapi / basedevice.h).
INTERFACE_TELESCOPE = 1 << 0
INTERFACE_CCD = 1 << 1
INTERFACE_GUIDER = 1 << 2
INTERFACE_FOCUSER = 1 << 3
INTERFACE_FILTER = 1 << 4
INTERFACE_DOME = 1 << 5
INTERFACE_GPS = 1 << 6
INTERFACE_WEATHER = 1 << 7
INTERFACE_AO = 1 << 8
INTERFACE_DUSTCAP = 1 << 9
INTERFACE_LIGHTBOX = 1 << 10
INTERFACE_ROTATOR = 1 << 12
INTERFACE_AUX = 1 << 15
INTERFACE_OUTPUT = 1 << 16
INTERFACE_POWER = 1 << 18

_KIND_BY_TAG = {
    "Text": "text", "Number": "number", "Switch": "switch", "Light": "light", "BLOB": "blob",
}
_DEF_TAGS = {f"def{k}Vector": v for k, v in _KIND_BY_TAG.items()}
_SET_TAGS = {f"set{k}Vector": v for k, v in _KIND_BY_TAG.items()}
_TOP_LEVEL_TAGS = set(_DEF_TAGS) | set(_SET_TAGS) | {"delProperty", "message"}

_SEXAGESIMAL_SPLIT = re.compile(r"[:; ]+")


def parse_indi_number(text: str) -> float:
    """Parse an INDI number, which may be plain (``12.5``) or sexagesimal
    (``12:30:00``, ``-5:15``) — mounts commonly report coordinates in the
    latter form."""
    text = (text or "").strip()
    try:
        return float(text)
    except ValueError:
        pass
    parts = [p for p in _SEXAGESIMAL_SPLIT.split(text) if p]
    if not parts:
        raise ValueError(f"not an INDI number: {text!r}")
    negative = parts[0].startswith("-")
    total = 0.0
    for i, part in enumerate(parts):
        total += abs(float(part)) / (60.0 ** i)
    return -total if negative else total


@dataclass
class IndiElement:
    name: str
    label: str = ""
    # number -> float, text -> str, switch -> bool, light -> state str, blob -> bytes
    value: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    format: str = ""
    blob_format: str = ""


@dataclass
class IndiProperty:
    device: str
    name: str
    kind: str                   # text | number | switch | light | blob
    label: str = ""
    group: str = ""
    perm: str = "rw"
    rule: str = ""              # switches: OneOfMany | AtMostOne | AnyOfMany
    state: str = IDLE
    timeout: float = 0.0
    elements: dict[str, IndiElement] = field(default_factory=dict)
    seq: int = 0                # bumped on every server update (BLOB arrival detection)

    def value(self, element: str, default: Any = None) -> Any:
        el = self.elements.get(element)
        return default if el is None else el.value


class IndiClient:
    """One TCP connection to an INDI server, with a live property cache."""

    def __init__(self, host: str, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self._cond = threading.Condition()
        self._props: dict[tuple[str, str], IndiProperty] = {}
        self._last_def = 0.0
        self._alive = False
        self._error: str | None = None
        self.messages: deque[str] = deque(maxlen=50)
        self.refcount = 0

    # -- lifecycle ---------------------------------------------------------

    @property
    def alive(self) -> bool:
        return self._alive

    def open(self, timeout: float = 10.0) -> None:
        """Connect and ask the server to stream every device's properties."""
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
        except OSError as exc:
            raise DeviceConnectionError(
                f"Cannot reach INDI server at {self.host}:{self.port}: {exc}"
            ) from exc
        sock.settimeout(None)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._alive = True
        self._last_def = time.monotonic()
        self._reader = threading.Thread(
            target=self._read_loop, name=f"indi-{self.host}:{self.port}", daemon=True,
        )
        self._reader.start()
        self._send(f'<getProperties version="{PROTOCOL_VERSION}"/>')

    def close(self) -> None:
        self._alive = False
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        with self._cond:
            self._cond.notify_all()

    # -- wire I/O ----------------------------------------------------------

    def _send(self, xml: str) -> None:
        sock = self._sock
        if sock is None or not self._alive:
            raise DeviceConnectionError(
                f"INDI connection to {self.host}:{self.port} is closed"
                + (f" ({self._error})" if self._error else "")
            )
        try:
            with self._send_lock:
                sock.sendall(xml.encode("utf-8"))
        except OSError as exc:
            self._fail(str(exc))
            raise DeviceConnectionError(f"INDI send to {self.host}:{self.port} failed: {exc}") from exc

    def _fail(self, reason: str) -> None:
        self._error = reason
        self._alive = False
        with self._cond:
            self._cond.notify_all()

    def _read_loop(self) -> None:
        # The INDI stream is a sequence of sibling elements with no single
        # document root, so wrap it in a synthetic one for the XML parser and
        # drop each top-level element once handled to keep memory flat.
        parser = ET.XMLPullParser(events=("start", "end"))
        parser.feed(b"<indi_stream>")
        root: ET.Element | None = None
        try:
            while self._alive:
                sock = self._sock
                if sock is None:
                    break
                chunk = sock.recv(65536)
                if not chunk:
                    self._fail("connection closed by server")
                    break
                parser.feed(chunk)
                for event, elem in parser.read_events():
                    if event == "start":
                        if root is None:
                            root = elem
                    elif elem.tag in _TOP_LEVEL_TAGS:
                        try:
                            self._handle(elem)
                        except Exception:
                            logger.exception("Error handling INDI element <%s>", elem.tag)
                        if root is not None:
                            root.remove(elem)
        except (OSError, ET.ParseError) as exc:
            if self._alive:
                logger.error("INDI connection to %s:%d lost: %s", self.host, self.port, exc)
            self._fail(str(exc))

    # -- incoming message handling -----------------------------------------

    def _handle(self, elem: ET.Element) -> None:
        tag = elem.tag
        if tag == "message":
            text = elem.get("message", "")
            if text:
                line = f"[{elem.get('device') or 'server'}] {text}"
                self.messages.append(line)
                # Servers replay recent driver messages to every new client and
                # drivers chatter routinely, so only problems reach the log pane.
                level = (logging.ERROR if "[ERROR]" in text
                         else logging.WARNING if "[WARNING]" in text else logging.DEBUG)
                logger.log(level, "INDI message %s", line)
            return
        if tag == "delProperty":
            device, name = elem.get("device", ""), elem.get("name")
            with self._cond:
                if name:
                    self._props.pop((device, name), None)
                else:
                    for key in [k for k in self._props if k[0] == device]:
                        del self._props[key]
                self._cond.notify_all()
            return
        if tag in _DEF_TAGS:
            self._handle_def(elem, _DEF_TAGS[tag])
        else:
            self._handle_set(elem, _SET_TAGS[tag])

    @staticmethod
    def _element_children(elem: ET.Element, kind: str) -> list[ET.Element]:
        prefix = {"text": "Text", "number": "Number", "switch": "Switch",
                  "light": "Light", "blob": "BLOB"}[kind]
        return elem.findall(f"one{prefix}") + elem.findall(f"def{prefix}")

    @staticmethod
    def _parse_value(kind: str, child: ET.Element) -> Any:
        text = (child.text or "").strip()
        if kind == "number":
            try:
                return parse_indi_number(text)
            except ValueError:
                return None
        if kind == "switch":
            return text == "On"
        return text if kind != "blob" else None

    def _handle_def(self, elem: ET.Element, kind: str) -> None:
        device, name = elem.get("device", ""), elem.get("name", "")
        prop = IndiProperty(
            device=device, name=name, kind=kind,
            label=elem.get("label", name), group=elem.get("group", ""),
            perm=elem.get("perm", "rw"), rule=elem.get("rule", ""),
            state=elem.get("state", IDLE), timeout=_to_float(elem.get("timeout")) or 0.0,
        )
        for child in self._element_children(elem, kind):
            el = IndiElement(name=child.get("name", ""), label=child.get("label", child.get("name", "")))
            if kind == "number":
                el.min, el.max = _to_float(child.get("min")), _to_float(child.get("max"))
                el.step, el.format = _to_float(child.get("step")), child.get("format", "")
            if kind != "blob":
                el.value = self._parse_value(kind, child)
            prop.elements[el.name] = el
        with self._cond:
            self._props[(device, name)] = prop
            self._last_def = time.monotonic()
            self._cond.notify_all()

    def _handle_set(self, elem: ET.Element, kind: str) -> None:
        device, name = elem.get("device", ""), elem.get("name", "")
        with self._cond:
            prop = self._props.get((device, name))
            if prop is None:
                return
            if elem.get("state"):
                prop.state = elem.get("state", prop.state)
            if elem.get("timeout"):
                prop.timeout = _to_float(elem.get("timeout")) or prop.timeout
            for child in self._element_children(elem, kind):
                el = prop.elements.get(child.get("name", ""))
                if el is None:
                    el = prop.elements[child.get("name", "")] = IndiElement(name=child.get("name", ""))
                if kind == "blob":
                    el.value, el.blob_format = self._decode_blob(child)
                else:
                    el.value = self._parse_value(kind, child)
                if kind == "number":
                    for attr, key in (("min", "min"), ("max", "max"), ("step", "step")):
                        if child.get(attr) is not None:
                            setattr(el, key, _to_float(child.get(attr)))
            prop.seq += 1
            self._cond.notify_all()

    @staticmethod
    def _decode_blob(child: ET.Element) -> tuple[bytes, str]:
        fmt = child.get("format", "")
        data = base64.b64decode(child.text or "")
        if fmt.endswith(".z"):
            data, fmt = zlib.decompress(data), fmt[:-2]
        return data, fmt

    # -- cache queries -----------------------------------------------------

    def get_property(self, device: str, name: str) -> IndiProperty | None:
        with self._cond:
            return self._props.get((device, name))

    def find_property(self, device: str, predicate: Callable[[IndiProperty], bool]) -> IndiProperty | None:
        with self._cond:
            for (dev, _), prop in self._props.items():
                if dev == device and predicate(prop):
                    return prop
        return None

    def get_number(self, device: str, name: str, element: str) -> float | None:
        prop = self.get_property(device, name)
        value = prop.value(element) if prop else None
        return float(value) if value is not None else None

    def get_text(self, device: str, name: str, element: str) -> str | None:
        prop = self.get_property(device, name)
        return prop.value(element) if prop else None

    def get_switch(self, device: str, name: str, element: str) -> bool | None:
        prop = self.get_property(device, name)
        value = prop.value(element) if prop else None
        return bool(value) if value is not None else None

    def get_state(self, device: str, name: str) -> str | None:
        prop = self.get_property(device, name)
        return prop.state if prop else None

    def active_switch(self, device: str, name: str) -> str | None:
        """Name of the first ``On`` element of a switch vector."""
        prop = self.get_property(device, name)
        if prop:
            for el in prop.elements.values():
                if el.value:
                    return el.name
        return None

    def device_names(self) -> list[str]:
        with self._cond:
            return sorted({dev for dev, _ in self._props})

    def device_properties(self, device: str) -> list[IndiProperty]:
        """Every property one device currently defines, sorted by group then
        name — for discovery logging of what a driver actually offers."""
        with self._cond:
            props = [p for (dev, _), p in self._props.items() if dev == device]
        return sorted(props, key=lambda p: (p.group, p.name))

    def device_interface(self, device: str) -> int:
        text = self.get_text(device, "DRIVER_INFO", "DRIVER_INTERFACE")
        try:
            return int(text) if text else 0
        except ValueError:
            return 0

    def device_snapshot(self, device: str) -> dict[str, Any]:
        """Flat ``{"PROPERTY.ELEMENT": value}`` view of one device's
        properties (BLOB payloads reported by size), for the raw property
        inspector (EQP-060)."""
        out: dict[str, Any] = {}
        with self._cond:
            for (dev, name), prop in self._props.items():
                if dev != device:
                    continue
                for el in prop.elements.values():
                    out[f"{name}.{el.name}"] = len(el.value) if prop.kind == "blob" and el.value else el.value
        return out

    # -- waiting -----------------------------------------------------------

    def wait_for(self, predicate: Callable[[], bool], timeout: float, what: str = "condition") -> None:
        """Block until *predicate* (evaluated under the cache lock) holds."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while not predicate():
                if not self._alive:
                    raise DeviceConnectionError(
                        f"INDI connection to {self.host}:{self.port} dropped while waiting for {what}"
                        + (f" ({self._error})" if self._error else "")
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    hint = f" Last server message: {self.messages[-1]}" if self.messages else ""
                    raise DeviceTimeoutError(f"Timed out after {timeout:g}s waiting for {what}.{hint}")
                self._cond.wait(remaining)

    def wait_property(self, device: str, name: str, timeout: float = 10.0) -> IndiProperty:
        self.wait_for(lambda: (device, name) in self._props, timeout, f"{device}.{name} to be defined")
        return self._props[(device, name)]

    def wait_settled(self, quiet: float = 0.6, timeout: float = 8.0, restart: bool = False) -> None:
        """Wait for a burst of property definitions to finish: at least one
        property known, and none newly defined for *quiet* seconds. Never
        raises on timeout — a chatty server just gets whatever has arrived
        so far. Pass ``restart=True`` right after something that triggers a
        new burst (a device connecting makes its driver define most of its
        properties), so quiet time is measured from now rather than from the
        previous burst."""
        deadline = time.monotonic() + timeout
        with self._cond:
            if restart:
                self._last_def = time.monotonic()
            while self._alive:
                now = time.monotonic()
                if self._props and now - self._last_def >= quiet:
                    return
                if now >= deadline:
                    return
                self._cond.wait(min(quiet, deadline - now))

    def blob_seq(self, device: str, name: str) -> int:
        prop = self.get_property(device, name)
        return prop.seq if prop else 0

    def latest_blob(self, device: str, name: str) -> tuple[bytes, str] | None:
        prop = self.get_property(device, name)
        if prop:
            for el in prop.elements.values():
                if el.value:
                    return el.value, el.blob_format
        return None

    # -- outgoing commands -------------------------------------------------

    def send_number(self, device: str, name: str, values: dict[str, float]) -> None:
        body = "".join(
            f"<oneNumber name={quoteattr(k)}>{format(float(v), '.12g')}</oneNumber>" for k, v in values.items()
        )
        self._send(f"<newNumberVector device={quoteattr(device)} name={quoteattr(name)}>{body}</newNumberVector>")

    def send_switch(self, device: str, name: str, values: dict[str, bool]) -> None:
        body = "".join(
            f"<oneSwitch name={quoteattr(k)}>{'On' if v else 'Off'}</oneSwitch>" for k, v in values.items()
        )
        self._send(f"<newSwitchVector device={quoteattr(device)} name={quoteattr(name)}>{body}</newSwitchVector>")

    def send_text(self, device: str, name: str, values: dict[str, str]) -> None:
        body = "".join(f"<oneText name={quoteattr(k)}>{escape(str(v))}</oneText>" for k, v in values.items())
        self._send(f"<newTextVector device={quoteattr(device)} name={quoteattr(name)}>{body}</newTextVector>")

    def enable_blob(self, device: str, mode: str = "Also") -> None:
        """Ask the server to deliver BLOBs (images) for *device* to this client."""
        self._send(f"<enableBLOB device={quoteattr(device)}>{mode}</enableBLOB>")


def _to_float(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return parse_indi_number(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Shared per-server connections
# ---------------------------------------------------------------------------

_registry: dict[tuple[str, int], IndiClient] = {}
_registry_lock = threading.Lock()


def acquire_client(host: str, port: int = DEFAULT_PORT, settle: bool = True) -> IndiClient:
    """Return the shared, open client for ``host:port`` (blocking), creating
    it if needed, and take a reference on it. Pair with :func:`release_client`.
    ``.local`` hostnames are resolved through mDNS since Windows can't do so
    natively."""
    key = (host, port)
    with _registry_lock:
        client = _registry.get(key)
        if client is None or not client.alive:
            address = host
            if host.lower().endswith(".local"):
                from galileo.adapters.alpaca import resolve_mdns_host_sync
                address = resolve_mdns_host_sync(host)
            client = IndiClient(address, port)
            client.open()
            _registry[key] = client
            fresh = True
        else:
            fresh = False
        client.refcount += 1
    if fresh and settle:
        client.wait_settled()
    return client


def release_client(client: IndiClient) -> None:
    """Drop one reference; the connection closes when the last holder releases."""
    with _registry_lock:
        client.refcount -= 1
        if client.refcount > 0:
            return
        for key, held in list(_registry.items()):
            if held is client:
                del _registry[key]
    client.close()
