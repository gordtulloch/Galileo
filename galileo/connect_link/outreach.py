# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The outreach event facility (LINK-100 to LINK-210).

An *event* lets visitors watch the live image from their own phones. It is off by default; the owner
opens it on the Master for a set time, and while it is open guests enrol anonymously with the event
secret from an address inside the outreach subnet and may do exactly three things: list the offered
Piers, receive the live image, and switch Pier. Nothing about an event is ever written to disk — the
secret and the guest tokens exist in memory only, so a restart voids every guest — and anything that
cannot be checked closes the door rather than opening it.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hmac
import ipaddress
import logging
import secrets as _secrets
import threading
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from galileo import settings_store
from galileo.connect_link.audit import AuditLog
from galileo.connect_link.permissions import PERMISSION_OUTREACH_VIEW
from galileo.core.ratelimit import RateLimiter

logger = logging.getLogger(__name__)

NAMESPACE = "connect_link.outreach"
PASSPHRASE_SECRET = "outreach.passphrase"  # noqa: S105 - the name of a keychain entry, not a password
GUEST_OPERATIONS = ("list_piers", "image", "switch_pier")          # LINK-150: exactly these three
SECRET_BITS = 160
MAX_DURATION_MIN = 24 * 60
MAX_GUESTS = 500


class OutreachError(Exception):
    """An event the facility will not open or a change it will not make; the reason is for the owner."""


# -- options (LINK-110) -------------------------------------------------------------------------
def parse_subnets(values: Iterable[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Private-range CIDRs only; a public (or malformed, or all-addresses) subnet is rejected."""
    nets = []
    for text in values:
        try:
            net = ipaddress.ip_network(str(text).strip(), strict=False)
        except ValueError:
            raise OutreachError(f"{text!r} is not a network address (use a form like 192.168.50.0/24)") from None
        if not (net.is_private and not net.is_loopback and not net.is_unspecified) or net.prefixlen < (8 if net.version == 4 else 16):
            raise OutreachError(f"{net} is not a private-range subnet; guests must be on the outreach Wi-Fi")
        nets.append(net)
    return nets


@dataclass(frozen=True)
class OutreachOptions:
    ssid: str = ""
    subnets: tuple[str, ...] = ()
    default_duration_min: int = 120
    guest_cap: int = 25
    preview_size: int = 800
    preview_quality: int = 70
    piers: tuple[str, ...] = ()                      # Pier references offered for outreach
    surfaces: tuple[str, ...] = ()                   # enabled surface names

    def clamped(self) -> OutreachOptions:
        parse_subnets(self.subnets)                  # a non-private subnet is rejected, not clamped
        return OutreachOptions(
            self.ssid.strip()[:32], tuple(str(n) for n in parse_subnets(self.subnets)),
            max(5, min(MAX_DURATION_MIN, int(self.default_duration_min))), max(1, min(MAX_GUESTS, int(self.guest_cap))),
            max(160, min(1024, int(self.preview_size))), max(30, min(80, int(self.preview_quality))),
            tuple(self.piers), tuple(self.surfaces))

    @classmethod
    def load(cls) -> OutreachOptions:
        raw = settings_store.get_namespace(NAMESPACE)
        d = cls()
        try:
            return cls(str(raw.get("ssid", d.ssid)), tuple(raw.get("subnets", d.subnets)),
                       int(raw.get("default_duration_min", d.default_duration_min)),
                       int(raw.get("guest_cap", d.guest_cap)), int(raw.get("preview_size", d.preview_size)),
                       int(raw.get("preview_quality", d.preview_quality)), tuple(raw.get("piers", d.piers)),
                       tuple(raw.get("surfaces", d.surfaces)))
        except (TypeError, ValueError):
            logger.warning("Outreach settings are unreadable; using the defaults")
            return d

    def save(self) -> OutreachOptions:
        ok = self.clamped()
        settings_store.set_namespace(NAMESPACE, {
            "ssid": ok.ssid, "subnets": list(ok.subnets), "default_duration_min": ok.default_duration_min,
            "guest_cap": ok.guest_cap, "preview_size": ok.preview_size, "preview_quality": ok.preview_quality,
            "piers": list(ok.piers), "surfaces": list(ok.surfaces)})
        return ok


# -- subnet confinement (LINK-140) ------------------------------------------------------------------
class SubnetGuard:
    def __init__(self, subnets: Iterable[str]) -> None:
        self._nets = parse_subnets(subnets)
        if not self._nets:
            raise OutreachError("no outreach subnet is set, so an event cannot open")

    def allows(self, address: str) -> bool:
        """Whether *address* is inside an outreach subnet. Anything unparsable, forwarded-looking or
        outside is refused."""
        try:
            ip = ipaddress.ip_address(address.strip().split("%", 1)[0])
        except ValueError:
            return False
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return any(ip.version == n.version and ip in n for n in self._nets)


# -- surfaces (LINK-200) --------------------------------------------------------------------------------
class SurfaceContext(Protocol):
    """What a surface is given while an event is open — and nothing more."""

    def enrol(self, secret: str, source: str) -> Enrolment: ...
    def handle(self, token: str, source: str, operation: str, **args: Any) -> Any: ...
    def add_sink(self, token: str, send: Callable[[dict[str, Any]], Any]) -> None: ...
    def remove_sink(self, token: str) -> None: ...


class OutreachSurface(Protocol):
    name: str

    def precondition(self) -> str | None:
        """None when the surface can run, else why not (for example, no HTTPS certificate)."""
    def payload(self, secret: str) -> str:
        """The text for this surface's enrolment QR code. The only place a surface sees the secret."""
    def on_open(self, ctx: SurfaceContext) -> None: ...
    def on_close(self) -> None: ...


@dataclass(frozen=True)
class Enrolment:
    token: str = ""
    reason: str = ""                  # set only for a caller who holds the secret when the event is full

    @property
    def ok(self) -> bool:
        return bool(self.token)


@dataclass
class _Guest:
    source: str
    pier: str = ""
    joined: float = 0.0
    sink: Callable[[dict[str, Any]], Any] | None = None


@dataclass
class _Event:
    opened_by: str
    opened_at: float
    ends_at: float
    secret: str
    guard: SubnetGuard
    options: OutreachOptions
    surfaces: list[OutreachSurface]
    piers: dict[str, str]                                          # reference -> display name
    guests: dict[str, _Guest] = field(default_factory=dict)
    refusals: Counter[str] = field(default_factory=Counter)
    peak: int = 0
    total: int = 0
    per_pier: Counter[str] = field(default_factory=Counter)
    limiter: RateLimiter | None = None
    guest_limiter: RateLimiter | None = None


class OutreachFacility:
    def __init__(
        self, audit: AuditLog, *, clock: Callable[[], float] = time.time,
        options: Callable[[], OutreachOptions] = OutreachOptions.load,
        link_available: Callable[[], bool] = lambda: True,
        pier_names: Callable[[Iterable[str]], dict[str, str]] | None = None,
        render: Callable[[str], Awaitable[bytes | None]] | None = None,
        passphrase: Callable[[], str] | None = None,
    ) -> None:
        self._audit, self._clock, self._options = audit, clock, options
        self._passphrase_source = passphrase or self._keychain_passphrase
        self._link_available = link_available
        self._pier_names = pier_names or (lambda refs: {r: r for r in refs})
        self._render = render                                       # guest-mode JPEG for a Pier, or None
        self._surfaces: dict[str, OutreachSurface] = {}
        self._event: _Event | None = None
        self._latest: dict[str, bytes] = {}
        self._lock = threading.RLock()
        self._ticker: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    # -- surfaces ------------------------------------------------------------------------
    def register_surface(self, surface: OutreachSurface) -> None:
        self._surfaces[surface.name] = surface

    def unregister_surface(self, name: str) -> None:
        self._surfaces.pop(name, None)

    # -- state ---------------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._event is not None

    def remaining(self) -> float:
        ev = self._event
        return max(0.0, ev.ends_at - self._clock()) if ev else 0.0

    def status(self) -> dict[str, Any]:
        ev = self._event
        if ev is None:
            return {"open": False}
        return {"open": True, "remaining_s": self.remaining(), "guests": len(ev.guests), "peak": ev.peak,
                "piers": dict(ev.piers), "surfaces": [s.name for s in ev.surfaces]}

    # -- open / close (LINK-100, LINK-210) ----------------------------------------------------
    def open(self, owner: str, duration_min: int | None = None) -> None:
        """Open an event, or raise :class:`OutreachError` saying why not. Fails closed."""
        with self._lock:
            if self._event is not None:
                raise OutreachError("an event is already open")
            if not self._link_available():
                raise OutreachError("Connect Link is not running")
            opts = self._options().clamped()
            guard = SubnetGuard(opts.subnets)                      # no subnet -> no event
            if not opts.piers:
                raise OutreachError("choose at least one Pier to offer")
            surfaces = [self._surfaces[n] for n in opts.surfaces if n in self._surfaces]
            for s in surfaces:
                # A check that fails to run is an unmet precondition, never a pass (LINK-210).
                reason = self._safely(s.name, s.precondition, default="its readiness check failed")
                if reason is not None:
                    raise OutreachError(f"{s.name} cannot run: {reason}")
            now = self._clock()
            minutes = opts.default_duration_min if duration_min is None else max(1, min(MAX_DURATION_MIN, int(duration_min)))
            self._event = _Event(
                owner, now, now + minutes * 60.0, _secrets.token_urlsafe(SECRET_BITS // 6 + 1), guard, opts, surfaces,
                self._pier_names(opts.piers), limiter=RateLimiter(self._clock, capacity=5, per_s=0.5),
                guest_limiter=RateLimiter(self._clock, capacity=20, per_s=2.0))
            opened: list[OutreachSurface] = []
            for s in surfaces:
                started = self._safely(s.name, functools.partial(self._start_surface, s), default=False)
                if not started:
                    self._event = None                           # a surface that cannot start stops the event
                    for done in opened:
                        self._safely(done.name, done.on_close)
                    raise OutreachError(f"{s.name} could not start")
                opened.append(s)

    def close(self, by: str = "owner", reason: str = "ended") -> None:
        """End the event: disconnect every guest, void every token and the secret, stop the surfaces, and
        write one aggregate audit record with no personal data (LINK-100, LINK-180)."""
        with self._lock:
            ev, self._event = self._event, None
            self._latest.clear()
            if ev is None:
                return
            sinks = [(t, g.sink) for t, g in ev.guests.items() if g.sink is not None]
            ev.guests.clear()
        for _, sink in sinks:
            self._safely("guest", functools.partial(sink, {"type": "ended"}))
        for s in ev.surfaces:
            self._safely(s.name, s.on_close)
        self._audit.write(by, "outreach", "event.close", reason, fields={
            "opened_by": ev.opened_by, "opened_at": ev.opened_at, "ended_at": self._clock(),
            "piers": sorted(ev.piers.values()), "surfaces": [s.name for s in ev.surfaces], "peak_visitors": ev.peak,
            "total_visitors": ev.total, "per_pier": dict(ev.per_pier), "refusals": dict(ev.refusals)})

    def extend(self, minutes: int) -> None:
        with self._lock:
            ev = self._require()
            ev.ends_at = min(ev.ends_at + max(1, int(minutes)) * 60.0, self._clock() + MAX_DURATION_MIN * 60.0)

    def reissue_secret(self) -> None:
        """New secret: enrolments with the old one are refused; guests already enrolled are unaffected."""
        with self._lock:
            self._require().secret = _secrets.token_urlsafe(SECRET_BITS // 6 + 1)

    def eject_all(self) -> int:
        with self._lock:
            ev = self._require()
            sinks = [g.sink for g in ev.guests.values() if g.sink is not None]
            n = len(ev.guests)
            ev.guests.clear()
        for sink in sinks:
            self._safely("guest", functools.partial(sink, {"type": "ended"}))
        return n

    def tick(self) -> None:
        """End the event when its time is up or its in-memory state is not trustworthy (LINK-210)."""
        ev = self._event
        if ev is None:
            return
        if self._clock() >= ev.ends_at:
            self.close("timer", "expired")
        elif not ev.secret or not ev.guard or not self._link_available():
            self.close("system", "state lost" if not ev.secret else "connect link stopped")

    async def run(self, interval: float = 1.0) -> None:
        """Watch the clock; cancel to stop. Only exists while someone is running events."""
        while True:
            await asyncio.sleep(interval)
            self.tick()

    def start_timer(self) -> None:
        if self._ticker is None or self._ticker.done():
            self._ticker = asyncio.create_task(self.run())

    async def stop_timer(self) -> None:
        ticker, self._ticker = self._ticker, None
        if ticker is not None:
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker
        for t in list(self._tasks):
            t.cancel()

    # -- enrolment (LINK-130, LINK-140) --------------------------------------------------------
    def enrol(self, secret: str, source: str) -> Enrolment:
        """Issue an anonymous guest token, or an :class:`Enrolment` with no token. Every refusal looks the
        same to the caller — as if nothing were listening — except the event being full, which a caller
        who holds the secret may be told."""
        with self._lock:
            ev = self._event
            if ev is None:
                return Enrolment()
            if not ev.guard.allows(source):                      # before anything else (LINK-140)
                ev.refusals["subnet"] += 1
                return Enrolment()
            assert ev.limiter is not None  # noqa: S101 - set when the event opens
            if not ev.limiter.allow(source):
                ev.refusals["rate"] += 1
                return Enrolment()
            if not hmac.compare_digest(secret.encode(), ev.secret.encode()):
                ev.refusals["secret"] += 1
                return Enrolment()
            if len(ev.guests) >= ev.options.guest_cap:
                ev.refusals["full"] += 1
                return Enrolment(reason="The event is full right now. Please try again in a few minutes.")
            token = _secrets.token_urlsafe(24)
            first = next(iter(ev.piers), "")
            ev.guests[token] = _Guest(source, first, self._clock())
            ev.total += 1
            ev.peak = max(ev.peak, len(ev.guests))
            ev.per_pier[ev.piers.get(first, first)] += 1
            return Enrolment(token)

    # -- the guest principal and its three operations (LINK-150) ----------------------------------
    def handle(self, token: str, source: str, operation: str, **args: Any) -> Any:
        """The only way a guest does anything. Anything but the three allowed operations, a token that is
        not live, or a source outside the subnet is refused and counted here — never reaching a plugin."""
        with self._lock:
            ev = self._event
            guest = ev.guests.get(token) if ev else None
            if ev is None or guest is None:
                return None
            if not ev.guard.allows(source) or not ev.guard.allows(guest.source):
                del ev.guests[token]                              # LINK-140: refuse and disconnect
                ev.refusals["subnet"] += 1
                self._drop_sink(guest)
                return None
            assert ev.guest_limiter is not None  # noqa: S101 - set when the event opens
            if not ev.guest_limiter.allow(token):
                ev.refusals["rate"] += 1
                return {"error": "slow down"}
            if operation not in GUEST_OPERATIONS:
                ev.refusals["not allowed"] += 1
                return {"error": "not available to guests"}
            if operation == "list_piers":
                return [{"ref": ref, "name": name} for ref, name in ev.piers.items()]
            if operation == "image":
                return self._latest.get(guest.pier)
            ref = str(args.get("pier", ""))
            if ref not in ev.piers:
                ev.refusals["unknown pier"] += 1
                return {"error": "no such Pier"}
            guest.pier = ref
            ev.per_pier[ev.piers[ref]] += 1
            self._push(guest, ref)
            return self._latest.get(ref)

    def permissions_of(self, token: str) -> frozenset[str]:
        """A guest holds exactly ``outreach.view``; a token that is not live holds nothing."""
        ev = self._event
        return frozenset({PERMISSION_OUTREACH_VIEW}) if ev and token in ev.guests else frozenset()

    # -- live image (LINK-160, LINK-170) ----------------------------------------------------------
    def add_sink(self, token: str, send: Callable[[dict[str, Any]], Any]) -> None:
        with self._lock:
            ev = self._event
            guest = ev.guests.get(token) if ev else None
            if guest is None:
                return
            guest.sink = send
            self._push(guest, guest.pier)                       # a guest that joins gets the latest at once

    def remove_sink(self, token: str) -> None:
        with self._lock:
            ev = self._event
            guest = ev.guests.get(token) if ev else None
            if guest is not None:
                guest.sink = None

    def _push(self, guest: _Guest, pier: str) -> None:
        image = self._latest.get(pier)
        if guest.sink is None:
            return
        message = {"type": "image", "pier": pier, "jpeg": image} if image else {"type": "unavailable", "pier": pier}
        sink = guest.sink
        self._safely("guest", lambda: sink(message))

    def frame_ready(self, pier: str, image: bytes) -> None:
        """A finished frame, already rendered in guest mode, goes to every guest viewing that Pier."""
        with self._lock:
            ev = self._event
            if ev is None or pier not in ev.piers:
                return
            self._latest[pier] = image
            targets = [g for g in ev.guests.values() if g.pier == pier]
        for g in targets:
            self._push(g, pier)

    async def on_frame_complete(self, pier: str) -> None:
        """Render the Pier's new frame through the preview service's guest mode and push it. Runs at the
        lowest priority — the renderer yields to a running session — and a failure here is only logged."""
        if self._render is None or self._event is None or pier not in self._event.piers:
            return
        try:
            image = await self._render(pier)
        except Exception:
            logger.exception("Could not render the outreach image for %s", pier)
            return
        if image:
            self.frame_ready(pier, image)

    # -- the owner's event display (LINK-190) ------------------------------------------------------
    def event_display(self) -> dict[str, Any]:
        """What the owner shows on screen: the Wi-Fi QR payload and one enrolment payload per surface."""
        with self._lock:
            ev = self._require()
            wifi = wifi_qr_payload(ev.options.ssid, self._passphrase_source())
            qrs = []
            for s in ev.surfaces:
                text = self._safely(s.name, functools.partial(s.payload, ev.secret), default="")
                if text:
                    qrs.append({"surface": s.name, "payload": text})
            return {"wifi": wifi, "surfaces": qrs, "remaining_s": self.remaining()}

    @staticmethod
    def _keychain_passphrase() -> str:
        """The Wi-Fi passphrase from the OS keychain; never from the database, never logged (LINK-110)."""
        from galileo.connect_link.secrets_store import KeyringSecretStore
        try:
            return KeyringSecretStore().get(PASSPHRASE_SECRET) or ""
        except Exception:
            return ""

    # -- internals ------------------------------------------------------------------------------
    def _require(self) -> _Event:
        if self._event is None:
            raise OutreachError("no event is open")
        return self._event

    def _start_surface(self, surface: OutreachSurface) -> bool:
        surface.on_open(_Context(self))
        return True

    @staticmethod
    def _drop_sink(guest: _Guest) -> None:
        sink, guest.sink = guest.sink, None
        if sink is not None:
            with contextlib.suppress(Exception):
                sink({"type": "ended"})

    @staticmethod
    def _safely(name: str, fn: Callable[[], Any], default: Any = None) -> Any:
        """Confine a fault to the one guest or surface it came from (LINK-210); ``default`` is returned
        when it faults."""
        try:
            return fn()
        except Exception:
            logger.exception("Outreach %s failed", name)
            return default


class _Context:
    """The facility as a surface sees it: enrol, relay guest requests, deliver. Nothing that reads tokens,
    issues them, or widens the allowlist."""

    def __init__(self, facility: OutreachFacility) -> None:
        self._f = facility

    def enrol(self, secret: str, source: str) -> Enrolment:
        return self._f.enrol(secret, source)

    def handle(self, token: str, source: str, operation: str, **args: Any) -> Any:
        return self._f.handle(token, source, operation, **args)

    def add_sink(self, token: str, send: Callable[[dict[str, Any]], Any]) -> None:
        self._f.add_sink(token, send)

    def remove_sink(self, token: str) -> None:
        self._f.remove_sink(token)


def wifi_qr_payload(ssid: str, passphrase: str = "") -> str:
    """The standard ``WIFI:`` payload phones read (the passphrase only if one is set)."""
    def esc(text: str) -> str:
        return "".join("\\" + c if c in '\\;,:"' else c for c in text)
    if not ssid:
        return ""
    if passphrase:
        return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(passphrase)};;"
    return f"WIFI:T:nopass;S:{esc(ssid)};;"


def qr_svg(payload: str, scale: int = 6) -> str:
    """The payload as an SVG QR code, for the owner's screen."""
    import io

    import segno
    buf = io.BytesIO()
    segno.make(payload, error="m").save(buf, kind="svg", scale=scale, border=2)
    return buf.getvalue().decode("utf-8")


__all__ = ["GUEST_OPERATIONS", "NAMESPACE", "PASSPHRASE_SECRET", "Enrolment", "OutreachError", "OutreachFacility",
           "OutreachOptions", "OutreachSurface", "SubnetGuard", "SurfaceContext", "parse_subnets", "qr_svg",
           "wifi_qr_payload"]
