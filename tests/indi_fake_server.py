# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""A small in-process INDI server for testing ``galileo.adapters.indi``.

Speaks the real INDI XML wire protocol over a loopback TCP socket, so the
adapter tests exercise the actual client (framing, parsing, property cache,
BLOB delivery) rather than mocks. It hosts four simulated devices — a CCD, a
telescope, a filter wheel and a focuser — each defining the standard INDI
properties its category's adapter uses, and echoing client ``new*Vector``
commands back as ``set*Vector`` updates the way a driver would.
"""

from __future__ import annotations

import base64
import io
import socket
import threading
import time
import xml.etree.ElementTree as ET
import zlib
from xml.sax.saxutils import quoteattr

import numpy as np

IMAGE = np.arange(12, dtype=np.uint16).reshape(3, 4) * 1000


def fits_bytes() -> bytes:
    from astropy.io import fits
    buf = io.BytesIO()
    fits.PrimaryHDU(IMAGE).writeto(buf)
    return buf.getvalue()


def _attrs(**kw: str) -> str:
    return " ".join(f"{k}={quoteattr(str(v))}" for k, v in kw.items())


def text_vec(dev: str, name: str, items: dict[str, str], perm: str = "ro") -> str:
    body = "".join(f'<defText name="{k}" label="{k}">{v}</defText>' for k, v in items.items())
    return f'<defTextVector {_attrs(device=dev, name=name, label=name, group="Main", state="Idle", perm=perm)}>{body}</defTextVector>'


def num_vec(dev: str, name: str, items: dict[str, tuple], perm: str = "rw") -> str:
    """items: element -> (value, min, max)."""
    body = "".join(
        f'<defNumber name="{k}" label="{k}" format="%g" min="{lo}" max="{hi}" step="1">{v}</defNumber>'
        for k, (v, lo, hi) in items.items()
    )
    return f'<defNumberVector {_attrs(device=dev, name=name, label=name, group="Main", state="Idle", perm=perm)}>{body}</defNumberVector>'


def sw_vec(dev: str, name: str, items: dict[str, bool], rule: str = "OneOfMany") -> str:
    body = "".join(f'<defSwitch name="{k}" label="{k}">{"On" if v else "Off"}</defSwitch>' for k, v in items.items())
    return f'<defSwitchVector {_attrs(device=dev, name=name, label=name, group="Main", state="Idle", perm="rw", rule=rule)}>{body}</defSwitchVector>'


def blob_vec(dev: str, name: str) -> str:
    return (f'<defBLOBVector {_attrs(device=dev, name=name, label=name, group="Image", state="Idle", perm="ro")}>'
            f'<defBLOB name="{name}" label="Image"/></defBLOBVector>')


def _devices() -> dict[str, dict]:
    ccd, mnt, fw, foc = "CCD Simulator", "Telescope Simulator", "Filter Simulator", "Focuser Simulator"
    rot = "Rotator Simulator"

    def base(dev: str, iface: int) -> list[str]:
        return [
            text_vec(dev, "DRIVER_INFO", {"DRIVER_NAME": dev, "DRIVER_EXEC": f"indi_{dev.split()[0].lower()}",
                                          "DRIVER_VERSION": "1.0", "DRIVER_INTERFACE": str(iface)}),
            sw_vec(dev, "CONNECTION", {"CONNECT": False, "DISCONNECT": True}),
        ]

    return {
        ccd: {"static": base(ccd, 6), "on_connect": [
            num_vec(ccd, "CCD_EXPOSURE", {"CCD_EXPOSURE_VALUE": (0, 0, 3600)}),
            num_vec(ccd, "CCD_INFO", {"CCD_MAX_X": (4144, 0, 1e5), "CCD_MAX_Y": (2822, 0, 1e5),
                                      "CCD_PIXEL_SIZE": (4.63, 0, 100)}, perm="ro"),
            num_vec(ccd, "CCD_TEMPERATURE", {"CCD_TEMPERATURE_VALUE": (12.5, -50, 50)}),
            num_vec(ccd, "CCD_BINNING", {"HOR_BIN": (1, 1, 4), "VER_BIN": (1, 1, 4)}),
            num_vec(ccd, "CCD_GAIN", {"GAIN": (100, 0, 500)}),
            sw_vec(ccd, "CCD_FRAME_TYPE", {"FRAME_LIGHT": True, "FRAME_BIAS": False,
                                           "FRAME_DARK": False, "FRAME_FLAT": False}),
            sw_vec(ccd, "CCD_COOLER", {"COOLER_ON": False, "COOLER_OFF": True}),
            sw_vec(ccd, "UPLOAD_MODE", {"UPLOAD_CLIENT": False, "UPLOAD_LOCAL": True, "UPLOAD_BOTH": False}),
            sw_vec(ccd, "CCD_ABORT_EXPOSURE", {"ABORT": False}, rule="AtMostOne"),
            blob_vec(ccd, "CCD1"),
        ]},
        mnt: {"static": base(mnt, 1), "on_connect": [
            # Sexagesimal on the wire, as real mount drivers report it.
            num_vec(mnt, "EQUATORIAL_EOD_COORD", {"RA": ("6:30:00", 0, 24), "DEC": ("-10:30:00", -90, 90)}),
            num_vec(mnt, "GEOGRAPHIC_COORD", {"LAT": (51.0, -90, 90), "LONG": (350.0, 0, 360), "ELEV": (120, -200, 9000)}),
            num_vec(mnt, "TIME_LST", {"LST": (5.5, 0, 24)}, perm="ro"),
            sw_vec(mnt, "ON_COORD_SET", {"SLEW": True, "TRACK": False, "SYNC": False}),
            sw_vec(mnt, "TELESCOPE_TRACK_STATE", {"TRACK_ON": False, "TRACK_OFF": True}),
            sw_vec(mnt, "TELESCOPE_PARK", {"PARK": True, "UNPARK": False}, rule="OneOfMany"),
            sw_vec(mnt, "TELESCOPE_PIER_SIDE", {"PIER_EAST": False, "PIER_WEST": True}),
            sw_vec(mnt, "TELESCOPE_ABORT_MOTION", {"ABORT": False}, rule="AtMostOne"),
            sw_vec(mnt, "TELESCOPE_MOTION_NS", {"MOTION_NORTH": False, "MOTION_SOUTH": False}, rule="AtMostOne"),
            sw_vec(mnt, "TELESCOPE_SLEW_RATE", {"SLEW_GUIDE": True, "SLEW_CENTERING": False,
                                                "SLEW_FIND": False, "SLEW_MAX": False}),
        ]},
        fw: {"static": base(fw, 16), "on_connect": [
            num_vec(fw, "FILTER_SLOT", {"FILTER_SLOT_VALUE": (1, 1, 3)}),
            text_vec(fw, "FILTER_NAME", {"FILTER_SLOT_NAME_1": "L", "FILTER_SLOT_NAME_2": "R", "FILTER_SLOT_NAME_3": "Ha"},
                     perm="rw"),
        ]},
        # Property names as exposed by the real INDI Rotator Simulator driver.
        rot: {"static": base(rot, 4096), "on_connect": [
            num_vec(rot, "ABS_ROTATOR_ANGLE", {"ANGLE": (10.0, 0, 360)}),
            num_vec(rot, "SYNC_ROTATOR_ANGLE", {"ANGLE": (0, 0, 360)}),
            sw_vec(rot, "ROTATOR_REVERSE", {"INDI_ENABLED": False, "INDI_DISABLED": True}),
            sw_vec(rot, "ROTATOR_ABORT_MOTION", {"ABORT": False}, rule="AtMostOne"),
        ]},
        foc: {"static": base(foc, 8), "on_connect": [
            num_vec(foc, "ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": (5000, 0, 60000)}),
            num_vec(foc, "REL_FOCUS_POSITION", {"FOCUS_RELATIVE_POSITION": (0, 0, 2000)}),
            sw_vec(foc, "FOCUS_MOTION", {"FOCUS_INWARD": True, "FOCUS_OUTWARD": False}),
            num_vec(foc, "FOCUS_TEMPERATURE", {"TEMPERATURE": (8.25, -50, 50)}, perm="ro"),
        ]},
    }


class FakeIndiServer:
    """Listens on ``127.0.0.1:<port>``; ``received`` logs every client command
    as ``(tag, device, property, {element: text})`` for assertions."""

    # Properties whose changes show as Busy before Ok, like a real move.
    _SLOW = {"EQUATORIAL_EOD_COORD", "FILTER_SLOT", "ABS_FOCUS_POSITION", "ABS_ROTATOR_ANGLE"}

    def __init__(self, preconnected: tuple[str, ...] = ()) -> None:
        self.devices = _devices()
        self.connected: set[str] = set(preconnected)
        self.received: list[tuple[str, str, str, dict[str, str]]] = []
        self.blob_enabled: set[str] = set()
        self.exposure_delay = 0.15
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(5)
        self.port = self._listener.getsockname()[1]
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def close(self) -> None:
        self._running = False
        self._listener.close()
        for sock in list(self._clients):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    # -- plumbing ----------------------------------------------------------

    def _accept_loop(self) -> None:
        while self._running:
            try:
                sock, _ = self._listener.accept()
            except OSError:
                return
            self._clients.append(sock)
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _send(self, sock: socket.socket, xml: str) -> None:
        with self._lock:
            try:
                sock.sendall(xml.encode())
            except OSError:
                pass

    def _serve(self, sock: socket.socket) -> None:
        parser = ET.XMLPullParser(events=("start", "end"))
        parser.feed(b"<client>")
        root = None
        while self._running:
            try:
                chunk = sock.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            parser.feed(chunk)
            for event, elem in parser.read_events():
                if event == "start":
                    root = root if root is not None else elem
                elif elem.tag in ("getProperties", "enableBLOB", "newSwitchVector", "newNumberVector", "newTextVector"):
                    self._on_command(sock, elem)
                    root.remove(elem)

    def _defs(self, dev: str) -> list[str]:
        info = self.devices[dev]
        return info["static"] + (info["on_connect"] if dev in self.connected else [])

    def _set_connection(self, sock: socket.socket, dev: str) -> None:
        on = dev in self.connected
        self._send(sock, f'<setSwitchVector device={quoteattr(dev)} name="CONNECTION" state="Ok">'
                         f'<oneSwitch name="CONNECT">{"On" if on else "Off"}</oneSwitch>'
                         f'<oneSwitch name="DISCONNECT">{"Off" if on else "On"}</oneSwitch></setSwitchVector>')

    # -- command handling --------------------------------------------------

    def _on_command(self, sock: socket.socket, elem: ET.Element) -> None:
        tag, dev, name = elem.tag, elem.get("device", ""), elem.get("name", "")
        values = {c.get("name", ""): (c.text or "").strip() for c in elem}
        self.received.append((tag, dev, name, values))

        if tag == "getProperties":
            for d in self.devices:
                for xml in self._defs(d):
                    self._send(sock, xml)
                if d in self.connected:
                    self._set_connection(sock, d)
        elif tag == "enableBLOB":
            self.blob_enabled.add(dev)
        elif name == "CONNECTION":
            was = dev in self.connected
            if values.get("CONNECT") == "On":
                self.connected.add(dev)
            else:
                self.connected.discard(dev)
            self._set_connection(sock, dev)
            if dev in self.connected and not was:
                for xml in self.devices[dev]["on_connect"]:
                    self._send(sock, xml)
        elif name == "CCD_EXPOSURE":
            threading.Thread(target=self._expose, args=(sock, dev, values), daemon=True).start()
        else:
            self._echo(sock, tag, dev, name, values)

    def _echo(self, sock: socket.socket, tag: str, dev: str, name: str, values: dict[str, str]) -> None:
        kind = tag.replace("new", "").replace("Vector", "")
        one = f"one{kind}"

        def send(state: str) -> None:
            body = "".join(f'<{one} name={quoteattr(k)}>{v}</{one}>' for k, v in values.items())
            self._send(sock, f'<set{kind}Vector device={quoteattr(dev)} name={quoteattr(name)} state="{state}">{body}</set{kind}Vector>')

        if name in self._SLOW:
            send("Busy")
            threading.Timer(0.2, send, args=("Ok",)).start()
        else:
            send("Ok")

    def _expose(self, sock: socket.socket, dev: str, values: dict[str, str]) -> None:
        exp = f'<setNumberVector device={quoteattr(dev)} name="CCD_EXPOSURE" state="%s"><oneNumber name="CCD_EXPOSURE_VALUE">%s</oneNumber></setNumberVector>'
        self._send(sock, exp % ("Busy", values.get("CCD_EXPOSURE_VALUE", "0")))
        time.sleep(self.exposure_delay)
        if dev not in self.blob_enabled:
            self._send(sock, exp % ("Alert", "0"))
            return
        self._send(sock, exp % ("Ok", "0"))
        payload = base64.b64encode(zlib.compress(fits_bytes())).decode()
        self._send(sock, f'<setBLOBVector device={quoteattr(dev)} name="CCD1" state="Ok">'
                         f'<oneBLOB name="CCD1" size="{len(payload)}" format=".fits.z">\n{payload}\n</oneBLOB></setBLOBVector>')
