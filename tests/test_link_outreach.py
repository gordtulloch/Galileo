# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — the outreach event facility (TC-LINK-100 … TC-LINK-210)."""

import asyncio
import logging

import pytest

from galileo import settings_store
from galileo.connect_link import AuditLog
from galileo.connect_link.outreach import (
    NAMESPACE,
    Enrolment,
    OutreachError,
    OutreachFacility,
    OutreachOptions,
    SubnetGuard,
    parse_subnets,
    qr_svg,
    wifi_qr_payload,
)

GOOD = "192.168.50.20"


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


class Surface:
    def __init__(self, name="web", precondition=None, payload="https://scope.local/o#SECRET"):
        self.name, self._pre, self._payload = name, precondition, payload
        self.opened = self.closed = 0
        self.ctx = None
        self.saw_secret = []

    def precondition(self):
        if isinstance(self._pre, Exception):
            raise self._pre
        return self._pre

    def payload(self, secret):
        self.saw_secret.append(secret)
        return f"{self._payload}:{secret}"

    def on_open(self, ctx):
        self.opened += 1
        self.ctx = ctx

    def on_close(self):
        self.closed += 1


def _opts(**kw):
    base = {"ssid": "Obs-Guest", "subnets": ("192.168.50.0/24",), "default_duration_min": 60, "guest_cap": 3,
            "piers": ("p1", "p2"), "surfaces": ("web",)}
    base.update(kw)
    return OutreachOptions(**base)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def rig(settings_db, clock):
    surface = Surface()
    link = {"up": True}
    fac = OutreachFacility(AuditLog(clock), clock=clock, options=lambda: _opts(),
                           link_available=lambda: link["up"], pier_names=lambda refs: {r: f"Scope {r}" for r in refs},
                           passphrase=lambda: "hunter2")
    fac.register_surface(surface)
    fac.surface, fac.link = surface, link
    return fac


def _secret(fac):
    return fac._event.secret


# ---- LINK-100 / 210 ----------------------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-100")
@pytest.mark.priority("MVP")
def test_tc_link_100_an_event_is_off_by_default_opens_for_a_time_and_ends(rig, clock):
    """LINK-100: nothing is open or registered until the owner opens an event; it ends when its duration
    ends, when the owner ends it, or when Connect Link stops; ending voids every guest and the secret."""
    assert not rig.is_open and rig.surface.opened == 0 and rig.remaining() == 0
    assert rig.enrol("anything", GOOD) == Enrolment() and rig.status() == {"open": False}
    rig.open("owner", duration_min=30)
    assert rig.is_open and rig.surface.opened == 1 and rig.remaining() == 1800
    secret = _secret(rig)
    token = rig.enrol(secret, GOOD).token
    assert rig.handle(token, GOOD, "list_piers")
    clock.t += 1799
    rig.tick()
    assert rig.is_open
    clock.t += 2
    rig.tick()
    assert not rig.is_open and rig.surface.closed == 1
    assert rig.handle(token, GOOD, "list_piers") is None and rig.enrol(secret, GOOD) == Enrolment()
    rig.open("owner")
    rig.close("owner")
    assert not rig.is_open
    rig.open("owner")
    rig.link["up"] = False
    rig.tick()
    assert not rig.is_open                                                    # disabling Connect Link ends it


@pytest.mark.requirement("TC-LINK-100")
@pytest.mark.priority("MVP")
async def test_tc_link_100_ending_an_event_disconnects_every_guest(rig):
    """LINK-100: ending the event tells every connected guest it is over and leaves no timer running."""
    rig.open("owner")
    got = []
    tokens = [rig.enrol(_secret(rig), GOOD).token for _ in range(2)]
    for t in tokens:
        rig.add_sink(t, got.append)
    rig.start_timer()
    assert rig._ticker is not None and not rig._ticker.done()
    rig.close("owner")
    assert [m["type"] for m in got if m["type"] == "ended"] == ["ended", "ended"]
    await rig.stop_timer()
    assert rig._ticker is None
    assert [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()] == []


@pytest.mark.requirement("TC-LINK-210")
@pytest.mark.priority("MVP")
def test_tc_link_210_an_event_fails_closed(rig, settings_db):
    """LINK-210: no subnet, no Pier, no Connect Link, an unready surface, or a surface whose check crashes
    each stop the event from opening, with a reason; nothing is left half-open."""
    cases = [
        ({"subnets": ()}, "subnet"), ({"piers": ()}, "Pier"),
    ]
    for kw, word in cases:
        fac = OutreachFacility(AuditLog(), options=lambda kw=kw: _opts(**kw))
        with pytest.raises(OutreachError, match=word):
            fac.open("owner")
        assert not fac.is_open
    rig.link["up"] = False
    with pytest.raises(OutreachError, match="not running"):
        rig.open("owner")
    rig.link["up"] = True
    rig.surface._pre = "no HTTPS certificate"
    with pytest.raises(OutreachError, match="no HTTPS certificate"):
        rig.open("owner")
    rig.surface._pre = RuntimeError("boom")
    with pytest.raises(OutreachError, match="readiness check failed"):
        rig.open("owner")
    assert not rig.is_open and rig.surface.opened == 0
    rig.surface._pre = None
    rig.open("owner")
    with pytest.raises(OutreachError, match="already"):
        rig.open("owner")


@pytest.mark.requirement("TC-LINK-210")
@pytest.mark.priority("MVP")
def test_tc_link_210_a_fault_is_confined_to_one_guest_or_surface_and_lost_state_closes(rig, caplog):
    """LINK-210: a guest whose delivery fails does not affect others; a surface that fails to start stops
    only the opening; an event whose state is lost closes itself; the secret and tokens are never logged."""
    rig.open("owner")
    secret = _secret(rig)
    good, bad = rig.enrol(secret, GOOD).token, rig.enrol(secret, "192.168.50.21").token
    seen = []
    rig.add_sink(good, seen.append)

    def broken(_):
        raise OSError("socket gone")

    with caplog.at_level(logging.DEBUG):
        rig.add_sink(bad, broken)
        rig.frame_ready("p1", b"JPEG")
        rig.eject_all()
        rig.close("owner")
    assert {"type": "image", "pier": "p1", "jpeg": b"JPEG"} in seen
    assert secret not in caplog.text and good not in caplog.text and bad not in caplog.text
    rig.open("owner")
    rig._event.secret = ""                                                    # as if its memory were damaged
    rig.tick()
    assert not rig.is_open


@pytest.mark.requirement("TC-LINK-210")
@pytest.mark.priority("MVP")
def test_tc_link_210_nothing_about_an_event_is_written_down(rig, settings_db):
    """LINK-210: the secret and guest tokens never reach the database; a restart (a new facility) voids
    every guest."""
    from galileo.library.models.base import db
    rig.open("owner")
    secret = _secret(rig)
    token = rig.enrol(secret, GOOD).token
    rig.close("owner")
    everything = " ".join(
        str(c) for t in db.get_tables() if t != "sqlite_sequence"
        for row in db.execute_sql(f'SELECT * FROM "{t}"').fetchall()  # noqa: S608 - names come from the database
        for c in row)
    assert secret not in everything and token not in everything
    fresh = OutreachFacility(AuditLog(), options=lambda: _opts())
    assert fresh.handle(token, GOOD, "list_piers") is None and fresh.enrol(secret, GOOD) == Enrolment()


# ---- LINK-110 ----------------------------------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-110")
@pytest.mark.priority("MVP")
def test_tc_link_110_options_live_in_the_settings_store_validated_and_clamped(settings_db):
    """LINK-110: the event options are stored in the settings database, clamped to sensible bounds; a
    public subnet is rejected; the passphrase is not among them."""
    saved = OutreachOptions(ssid="  Obs-Guest  ", subnets=("192.168.50.7/24",), default_duration_min=100000,
                            guest_cap=0, preview_size=99999, preview_quality=1, piers=("p1",), surfaces=("web",)).save()
    assert (saved.ssid, saved.subnets, saved.default_duration_min, saved.guest_cap) == (
        "Obs-Guest", ("192.168.50.0/24",), 1440, 1)
    assert (saved.preview_size, saved.preview_quality) == (1024, 30)
    assert OutreachOptions.load() == saved
    assert "passphrase" not in settings_store.get_namespace(NAMESPACE)
    for bad in ("8.8.8.0/24", "0.0.0.0/0", "127.0.0.0/8", "nonsense", "10.0.0.0/4"):
        with pytest.raises(OutreachError):
            OutreachOptions(subnets=(bad,)).save()
    assert parse_subnets(["10.1.2.0/24", "172.16.0.0/16", "fd00::/64"])


# ---- LINK-120 / 130 ------------------------------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-120")
@pytest.mark.priority("MVP")
def test_tc_link_120_the_event_secret_is_strong_per_event_and_can_be_reissued(rig):
    """LINK-120: a new random secret of at least 128 bits per event; re-issuing refuses old-secret
    enrolments and leaves enrolled guests alone."""
    rig.open("owner")
    first = _secret(rig)
    assert len(first) * 6 >= 128
    token = rig.enrol(first, GOOD).token
    rig.reissue_secret()
    second = _secret(rig)
    assert second != first and rig.enrol(first, "192.168.50.22") == Enrolment()
    assert rig.enrol(second, "192.168.50.22").ok and rig.handle(token, GOOD, "list_piers")
    rig.close("owner")
    rig.open("owner")
    assert _secret(rig) not in (first, second)


@pytest.mark.requirement("TC-LINK-130")
@pytest.mark.priority("MVP")
def test_tc_link_130_enrolment_is_anonymous_only_with_the_secret_and_looks_like_a_closed_port(rig):
    """LINK-130: a guest token needs only the secret and a subnet address (no name or approval) and carries
    only outreach.view; every refusal is the same empty answer, except that a holder of the secret is told
    when the event is full."""
    rig.open("owner")
    secret = _secret(rig)
    ok = rig.enrol(secret, GOOD)
    assert ok.ok and len(ok.token) >= 24 and rig.permissions_of(ok.token) == frozenset({"outreach.view"})
    assert rig.permissions_of("nope") == frozenset()
    refusals = [rig.enrol("wrong", "192.168.50.30"), rig.enrol(secret, "10.9.9.9"), rig.enrol("", GOOD)]
    assert all(r == Enrolment() for r in refusals)                              # identical, reasonless
    rig.enrol(secret, "192.168.50.31")
    rig.enrol(secret, "192.168.50.32")
    full = rig.enrol(secret, "192.168.50.33")
    assert not full.ok and "full" in full.reason
    assert rig.enrol("wrong", "192.168.50.34") == Enrolment()                  # no reason without the secret
    assert len({rig.enrol(secret, f"192.168.50.{i}").token for i in range(40, 43)}) == 1       # all refused: ""


@pytest.mark.requirement("TC-LINK-130")
@pytest.mark.priority("MVP")
def test_tc_link_130_enrolment_attempts_are_rate_limited(rig, clock):
    """LINK-130: repeated enrolment attempts from one address are throttled, even with the right secret."""
    rig.open("owner")
    secret = _secret(rig)
    results = [rig.enrol("guess" + str(i), "192.168.50.99") for i in range(12)]
    assert all(r == Enrolment() for r in results)
    assert rig.enrol(secret, "192.168.50.99") == Enrolment()                    # throttled
    assert rig._event.refusals["rate"] >= 1 and rig._event.refusals["secret"] == 5
    clock.t += 30
    assert rig.enrol(secret, "192.168.50.99").ok


# ---- LINK-140 --------------------------------------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-140")
@pytest.mark.priority("MVP")
def test_tc_link_140_the_source_address_is_confined_to_the_subnet_every_time(rig):
    """LINK-140: the subnet is checked on enrolment and on every guest request; a guest seen from outside
    it is disconnected; forwarded-looking or malformed sources are refused."""
    g = SubnetGuard(["192.168.50.0/24"])
    assert g.allows("192.168.50.1") and g.allows("::ffff:192.168.50.9") and g.allows(" 192.168.50.5 ")
    for outside in ("192.168.51.1", "8.8.8.8", "127.0.0.1", "::1", "192.168.50.1, 1.2.3.4", "", "nonsense",
                    "192.168.50.256"):
        assert not g.allows(outside), outside
    with pytest.raises(OutreachError):
        SubnetGuard([])
    rig.open("owner")
    got = []
    token = rig.enrol(_secret(rig), GOOD).token
    rig.add_sink(token, got.append)
    assert rig.handle(token, GOOD, "list_piers")
    assert rig.handle(token, "203.0.113.5", "list_piers") is None             # now seen from the internet
    assert rig.handle(token, GOOD, "list_piers") is None                      # and gone
    assert got[-1] == {"type": "ended"} and rig._event.refusals["subnet"] == 1


# ---- LINK-150 ------------------------------------------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-150")
@pytest.mark.priority("MVP")
def test_tc_link_150_a_guest_may_do_exactly_three_things(rig):
    """LINK-150: list the offered Piers (display names only), receive the live image, switch Pier; anything
    else is refused and counted before it reaches any handler, and a plugin cannot widen the list."""
    rig.open("owner")
    token = rig.enrol(_secret(rig), GOOD).token
    assert rig.handle(token, GOOD, "list_piers") == [{"ref": "p1", "name": "Scope p1"},
                                                     {"ref": "p2", "name": "Scope p2"}]
    assert rig.handle(token, GOOD, "image") is None
    assert rig.handle(token, GOOD, "switch_pier", pier="p2") is None          # nothing yet for p2
    assert rig._event.guests[token].pier == "p2"
    assert rig.handle(token, GOOD, "switch_pier", pier="elsewhere") == {"error": "no such Pier"}
    for op in ("operate", "catalogue", "lease", "state", "preview", "__class__", "", "LIST_PIERS"):
        assert rig.handle(token, GOOD, op) == {"error": "not available to guests"}
    assert rig._event.refusals["not allowed"] == 8
    from galileo.connect_link.outreach import GUEST_OPERATIONS
    assert GUEST_OPERATIONS == ("list_piers", "image", "switch_pier")
    assert not hasattr(rig.surface.ctx, "tokens") and not hasattr(rig.surface.ctx, "allowlist")


# ---- LINK-160 / 170 --------------------------------------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-160")
@pytest.mark.priority("MVP")
async def test_tc_link_160_a_finished_frame_reaches_guests_viewing_that_pier_and_joiners_get_the_latest(settings_db, clock):
    """LINK-160: each completed frame is rendered in guest mode and pushed to guests viewing that Pier; a
    guest who joins or switches gets the latest image at once; a failed render is only logged."""
    rendered = []

    async def render(pier):
        rendered.append(pier)
        if pier == "p2":
            raise RuntimeError("no frame")
        return b"JPEG-" + pier.encode()

    fac = OutreachFacility(AuditLog(clock), clock=clock, options=lambda: _opts(surfaces=()), render=render)
    fac.open("owner")
    secret = fac._event.secret
    a, b = fac.enrol(secret, GOOD).token, fac.enrol(secret, "192.168.50.21").token
    seen_a, seen_b = [], []
    fac.add_sink(a, seen_a.append)
    fac.add_sink(b, seen_b.append)
    assert seen_a == [{"type": "unavailable", "pier": "p1"}]                  # nothing to show yet
    fac.handle(b, "192.168.50.21", "switch_pier", pier="p2")
    await fac.on_frame_complete("p1")
    await fac.on_frame_complete("p2")                                         # render fails: logged, not raised
    await fac.on_frame_complete("elsewhere")                                  # not offered: never rendered
    assert rendered == ["p1", "p2"]
    assert seen_a[-1] == {"type": "image", "pier": "p1", "jpeg": b"JPEG-p1"}
    assert all(m["pier"] != "p1" or m["type"] != "image" for m in seen_b)      # b watches p2
    late = fac.enrol(secret, "192.168.50.22").token
    got = []
    fac.add_sink(late, got.append)
    assert got == [{"type": "image", "pier": "p1", "jpeg": b"JPEG-p1"}]
    assert fac.handle(late, "192.168.50.22", "image") == b"JPEG-p1"
    fac.close("owner")
    await fac.on_frame_complete("p1")
    assert rendered == ["p1", "p2"]


@pytest.mark.requirement("TC-LINK-160")
@pytest.mark.priority("MVP")
async def test_tc_link_160_guest_images_come_from_the_preview_services_guest_mode(settings_db, clock):
    """LINK-160: the image sent to guests carries no metadata and is limited in size and quality — it is
    the preview service's guest mode, end to end."""
    import io

    import numpy as np
    from PIL import Image

    from galileo.preview import PreviewParams, PreviewService, assert_clean
    frame = np.random.default_rng(1).uniform(0, 4000, (900, 1200)).astype(np.float32)
    svc = PreviewService({"current": lambda ref: ("1", frame)})

    async def render(pier):
        return (await svc.render("current", PreviewParams(guest=True, max_size=4000, quality=95))).data

    fac = OutreachFacility(AuditLog(clock), clock=clock, options=lambda: _opts(surfaces=()), render=render)
    fac.open("owner")
    token = fac.enrol(fac._event.secret, GOOD).token
    sent = []
    fac.add_sink(token, sent.append)
    await fac.on_frame_complete("p1")
    jpeg = sent[-1]["jpeg"]
    assert_clean(jpeg)
    assert max(Image.open(io.BytesIO(jpeg)).size) <= 1024 and len(svc.cache) == 0


@pytest.mark.requirement("TC-LINK-170")
@pytest.mark.priority("MVP")
def test_tc_link_170_guests_are_capped_and_rate_limited(rig, clock):
    """LINK-170: concurrent guests are limited to the configured cap; each guest is rate-limited; leaving
    frees a place."""
    rig.open("owner")
    secret = _secret(rig)
    tokens = [rig.enrol(secret, f"192.168.50.{10 + i}").token for i in range(3)]
    assert all(tokens) and not rig.enrol(secret, "192.168.50.60").ok
    assert rig._event.peak == 3
    answers = [rig.handle(tokens[0], "192.168.50.10", "list_piers") for _ in range(40)]
    assert {"error": "slow down"} in answers and answers[0] != {"error": "slow down"}
    assert rig.handle(tokens[1], "192.168.50.11", "list_piers")                # another guest is unaffected
    rig.eject_all()
    assert rig.enrol(secret, "192.168.50.61").ok


# ---- LINK-180 ---------------------------------------------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-180")
@pytest.mark.priority("MVP")
def test_tc_link_180_the_event_is_audited_in_aggregate_without_personal_data(rig, clock):
    """LINK-180: one audit record per event — who opened it, when, Piers, surfaces, peak and total guests,
    refusals by kind, guests per Pier — and no guest token, address or secret."""
    rig.open("gord")
    secret = _secret(rig)
    t1 = rig.enrol(secret, GOOD).token
    rig.enrol(secret, "192.168.50.21")
    rig.enrol("wrong", "192.168.50.22")
    rig.enrol(secret, "10.1.1.1")
    rig.handle(t1, GOOD, "switch_pier", pier="p2")
    rig.eject_all()
    rig.enrol(secret, "192.168.50.23")
    clock.t += 600
    rig.close("gord")
    (event,) = [e for e in rig._audit.query() if e.route == "event.close"]
    f = event.fields
    assert (event.actor, event.plugin, event.outcome) == ("gord", "outreach", "ended")
    assert f["opened_by"] == "gord" and f["ended_at"] - f["opened_at"] == 600
    assert f["piers"] == ["Scope p1", "Scope p2"] and f["surfaces"] == ["web"]
    assert (f["peak_visitors"], f["total_visitors"]) == (2, 3) and f["refusals"] == {"secret": 1, "subnet": 1}
    assert f["per_pier"] == {"Scope p1": 3, "Scope p2": 1}
    blob = str(event.__dict__)
    for private in (secret, t1, GOOD, "192.168.50", "10.1.1.1"):
        assert private not in blob


# ---- LINK-190 / 200 ------------------------------------------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-190")
@pytest.mark.priority("MVP")
def test_tc_link_190_owner_controls_and_the_event_display(rig, clock):
    """LINK-190: the owner extends the event, sees time left, guests and Piers, ejects everyone, and gets the
    Wi-Fi QR payload (passphrase only if set) and one enrolment payload per enabled surface — with real QR
    codes."""
    rig.open("owner", duration_min=10)
    rig.extend(5)
    assert rig.remaining() == 900
    token = rig.enrol(_secret(rig), GOOD).token
    status = rig.status()
    assert status["guests"] == 1 and status["piers"] == {"p1": "Scope p1", "p2": "Scope p2"}
    shown = rig.event_display()
    assert shown["wifi"] == "WIFI:T:WPA;S:Obs-Guest;P:hunter2;;"
    assert shown["surfaces"] == [{"surface": "web", "payload": f"https://scope.local/o#SECRET:{_secret(rig)}"}]
    assert rig.eject_all() == 1 and rig.handle(token, GOOD, "list_piers") is None
    assert wifi_qr_payload("Open Net") == "WIFI:T:nopass;S:Open Net;;"
    assert wifi_qr_payload("A;B:C", "p,w") == "WIFI:T:WPA;S:A\\;B\\:C;P:p\\,w;;"
    assert wifi_qr_payload("") == ""
    svg = qr_svg(shown["wifi"])
    assert svg.startswith(("<?xml", "<svg"))
    rig.close("owner")
    with pytest.raises(OutreachError):
        rig.event_display()
    with pytest.raises(OutreachError):
        rig.extend(5)


@pytest.mark.requirement("TC-LINK-200")
@pytest.mark.priority("MVP")
def test_tc_link_200_surfaces_run_only_while_an_event_is_open_and_the_surface_is_enabled(settings_db, clock):
    """LINK-200: a surface is started only when the event opens and it is enabled, is stopped when the event
    ends, sees the secret only through its payload builder, and cannot read or issue tokens."""
    web, app = Surface("web"), Surface("mobile")
    fac = OutreachFacility(AuditLog(clock), clock=clock, options=lambda: _opts(surfaces=("web",)))
    fac.register_surface(web)
    fac.register_surface(app)
    assert web.opened == app.opened == 0
    fac.open("owner")
    assert (web.opened, app.opened) == (1, 0)                                  # mobile is not enabled
    assert [s["surface"] for s in fac.event_display()["surfaces"]] == ["web"]
    secret = fac._event.secret
    assert web.saw_secret == [secret]
    ctx = web.ctx
    assert ctx.enrol(secret, GOOD).ok and not ctx.enrol("bad", "192.168.50.5").ok
    assert {n for n in dir(ctx) if not n.startswith("_")} == {"enrol", "handle", "add_sink", "remove_sink"}
    fac.close("owner")
    assert (web.closed, app.closed) == (1, 0)
    fac.unregister_surface("web")
    fac2 = OutreachFacility(AuditLog(clock), clock=clock, options=lambda: _opts(surfaces=("web",)))
    fac2.open("owner")                                                         # an unregistered surface is skipped
    assert fac2.is_open


@pytest.mark.requirement("TC-LINK-200")
@pytest.mark.priority("MVP")
def test_tc_link_200_a_surface_that_cannot_start_stops_the_event_and_the_others_are_closed(settings_db, clock):
    """LINK-200 / LINK-210: a surface that fails to start prevents the event, and surfaces that had already
    started are stopped again."""
    ok, broken = Surface("web"), Surface("mobile")

    def explode(ctx):
        raise RuntimeError("cannot bind")

    broken.on_open = explode
    fac = OutreachFacility(AuditLog(clock), clock=clock, options=lambda: _opts(surfaces=("web", "mobile")))
    fac.register_surface(ok)
    fac.register_surface(broken)
    with pytest.raises(OutreachError, match="mobile could not start"):
        fac.open("owner")
    assert not fac.is_open and ok.opened == 1 and ok.closed == 1

