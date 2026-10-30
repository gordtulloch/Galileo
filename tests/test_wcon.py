# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""WCON — WebConnect plugin (TC-WCON-010 … TC-WCON-1330).

Covers the ``WCON`` domain of ``docs/plugins/webconnect/SRS.md`` (not a core domain).
One ``test_tc_wcon_<nnn>_*`` function per row of ``docs/plugins/webconnect/RTM.md``.

**Status: the plugin is not built yet.** Until the ``webconnect`` package exists:

* the document-chain tests (``test_wcon_doc_chain_*``) run and check that SRS, SDD,
  RTM and this file agree;
* every requirement test skips through ``pytest.importorskip``.

Once a module exists, a requirement whose test has no body yet **fails** (``_pending``)
instead of skipping, so a half-written suite can never show green.

Interfaces assumed (taken from ``docs/plugins/webconnect/SDD.md``; adjust here, in one
place, if the implementation differs):

* ``webconnect.web.create_app(settings, link, clock=...) -> flask.Flask`` — the operating
  application. ``settings``: ``allowed_hosts``, ``session_idle_s``, ``session_abs_s``,
  optional ``outreach_subnets``. ``webconnect.web.PUBLIC_ROUTES`` lists the only
  unauthenticated routes.
* ``link`` is the web half's ``LinkClientPort``: ``call(route, body, on_behalf_of,
  headers) -> (status, json)``, ``open_stream(topic, on_behalf_of, last_id)`` yielding
  ``(id, event, data)``, ``handshake()``. Routes used here: ``signin``, ``ops``, ``fits``.
* Pages carry ``<meta name="csrf-token" content="…">``; ``POST /signin`` needs the
  device cookie and a same-origin ``Origin`` but no CSRF token (there is no session yet).
* ``webconnect.outreach_app.create_app(settings, facility, clock=...)`` — the guest
  application; ``facility`` is the ``OutreachFacilityPort``.
* ``webconnect.config.WebConnectConfig.from_dict(dict)`` and
  ``webconnect.outreach.qr_payload(host, port, event, secret)``.
"""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs" / "plugins" / "webconnect"
OUTREACH_SETTINGS = {
    "subnets": ["192.168.50.0/24"],
    "hostname": "sky.test",
    "cert": "cert.pem",
    "key": "key.pem",
}


def _pending(tc, module):
    """Skip while the module is missing; fail once it exists but the test is unwritten."""
    pytest.importorskip(module)
    pytest.fail(f"{tc}: {module} exists but this requirement has no test body yet")


# ---------------------------------------------------------------------------
# Fakes for the ports the web half talks to
# ---------------------------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeLink:
    """Stands in for Connect Link as the web half sees it, modelling just enough of the
    Master half's pipeline (role check) for the web layer's behaviour to be observable."""

    def __init__(self):
        self.calls = []          # (route, body, on_behalf_of, headers)
        self.devices = {}        # device token -> (peer, role)
        self.roles = {}          # peer -> role
        self.handlers = {}       # route -> fn(body, who, headers) -> (status, json)
        self.stream_events = []  # (id, event, data)

    def call(self, route, body=None, on_behalf_of=None, headers=None):
        headers = dict(headers or {})
        self.calls.append((route, body, on_behalf_of, headers))
        handler = self.handlers.get(route) or getattr(self, "_default_" + route, None)
        if handler:
            return handler(body, on_behalf_of, headers)
        return 200, {}

    def open_stream(self, topic, on_behalf_of=None, last_id=None):
        floor = int(last_id) if last_id not in (None, "") else 0
        return iter([e for e in self.stream_events if e[0] > floor])

    def handshake(self):
        return {"galileo": "0.9.2", "plugin_api": "v1", "areas": ["devices", "imaging"]}

    def _default_signin(self, body, who, headers):
        dev = self.devices.get((body or {}).get("device"))
        if not dev:
            return 401, {"error": "refused", "reason": "unknown device"}
        return 200, {"peer": dev[0], "role": dev[1]}

    def _default_ops(self, body, who, headers):
        if self.roles.get(who) == "viewer":
            return 403, {"error": "refused", "reason": "a Viewer cannot operate"}
        return 200, {"ok": True}

    def _default_fits(self, body, who, headers):
        if self.roles.get(who) == "viewer":
            return 403, {"error": "refused", "reason": "a Viewer cannot download FITS"}
        return 200, {"size": 1024}


class FakeFacility:
    """Stands in for the Connect Link outreach facility (L9) as the guest app sees it."""

    def __init__(self):
        self.event, self.secret = "ev1", "s3cret"
        self.enrol_calls = []    # (event, secret, asserted_source)
        self.piers = [{"id": "p1", "name": "North"}]
        self.images = {"p1": (1, "2026-10-29T22:00:00Z", b"\xff\xd8\xff\xe0fakejpeg")}

    def enrol(self, event, secret, asserted_source):
        self.enrol_calls.append((event, secret, asserted_source))
        return "gtok" if (event, secret) == (self.event, self.secret) else None

    def offered_piers(self, token):
        return self.piers if token == "gtok" else None

    def latest_image(self, pier):
        return self.images.get(pier)

    def guest_stream(self, token, pier):
        if token != "gtok" or pier not in self.images:
            return None
        seq, taken, _ = self.images[pier]
        return iter([("image", {"pier": pier, "seq": seq, "captured_at": taken})])


# ---------------------------------------------------------------------------
# A browser driver over Flask's test client
# ---------------------------------------------------------------------------

class Browser:
    def __init__(self, app, host="wc.test", addr="192.168.1.20"):
        self.c, self.host, self.addr, self.csrf = app.test_client(), host, addr, None
        self.base = f"https://{host}"

    def req(self, method, path, headers=None, json=None, csrf=True, origin=True):
        h = dict(headers or {})
        if method not in ("GET", "HEAD", "OPTIONS"):
            if origin is True:
                h.setdefault("Origin", self.base)
            elif origin:
                h.setdefault("Origin", origin)
            if csrf is True and self.csrf:
                h.setdefault("X-CSRF-Token", self.csrf)
            elif isinstance(csrf, str):
                h.setdefault("X-CSRF-Token", csrf)
        return self.c.open(
            path, method=method, headers=h, json=json,
            base_url=self.base, environ_overrides={"REMOTE_ADDR": self.addr},
        )

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, **kw):
        return self.req("POST", path, **kw)


def anon_browser(app, host="wc.test", addr="192.168.1.20"):
    return Browser(app, host, addr)


def op_browser_factory(app, link, role="operator", peer="peer-1"):
    """A browser that has been approved on the Master and signed in."""
    link.devices["dev-" + peer] = (peer, role)
    link.roles[peer] = role
    b = Browser(app)
    b.c.set_cookie("__Host-wc_device", "dev-" + peer, domain=b.host)
    assert b.post("/signin", csrf=False).status_code in (200, 204, 302)
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', b.get("/").get_data(as_text=True))
    assert m, "pages must carry a CSRF token in a <meta name=\"csrf-token\"> element"
    b.csrf = m.group(1)
    return b


def guest_browser(oapp, facility):
    """A visitor who has scanned the QR code and enrolled."""
    b = Browser(oapp, host="sky.test", addr="192.168.50.20")
    r = b.post("/outreach/enrol", json={"event": facility.event, "secret": facility.secret})
    assert r.status_code in (200, 204)
    return b


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def link():
    return FakeLink()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def facility():
    return FakeFacility()


@pytest.fixture
def app(link, clock):
    pytest.importorskip("flask")
    web = pytest.importorskip("webconnect.web")
    return web.create_app(
        {"allowed_hosts": ["wc.test"], "session_idle_s": 600, "session_abs_s": 3600},
        link, clock=clock,
    )


def outreach_app_factory(facility, clock):
    pytest.importorskip("flask")
    oapp = pytest.importorskip("webconnect.outreach_app")
    return oapp.create_app(OUTREACH_SETTINGS, facility, clock=clock)


# ---------------------------------------------------------------------------
# Document chain: these run today and keep SRS, SDD, RTM and this file in step
# ---------------------------------------------------------------------------

def _read(name):
    return (DOCS / name).read_text(encoding="utf-8")


def _srs_rows():
    return {int(n): p for n, p in re.findall(r"^\| WCON-(\d+) \| .* \| (MVP|P2|P3) \|$", _read("SRS.md"), flags=re.MULTILINE)}


def _rtm_ids():
    return [int(n) for n in re.findall(r"^\| `WCON-(\d+)` \|", _read("RTM.md"), flags=re.MULTILINE)]


def test_wcon_doc_chain_srs_and_rtm_list_the_same_requirements():
    srs, rtm = set(_srs_rows()), _rtm_ids()
    assert len(rtm) == len(set(rtm)), "duplicate RTM row"
    assert srs == set(rtm), f"only in SRS: {sorted(srs - set(rtm))}; only in RTM: {sorted(set(rtm) - srs)}"


def test_wcon_doc_chain_srs_summary_counts_match_its_tables():
    rows = _srs_rows()
    table = _read("SRS.md").split("## 5. Requirement Summary Counts", 1)[1].split("## 6.", 1)[0]
    total = re.search(r"\| \*\*Total\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \|", table)
    assert total, "summary total row not found"
    got = tuple(int(x) for x in total.groups())
    want = (len(rows), *(sum(1 for p in rows.values() if p == k) for k in ("MVP", "P2", "P3")))
    assert got == want, f"SRS summary says {got}, tables list {want}"
    subtotal = [tuple(int(x) for x in m) for m in re.findall(r"^\| [^|*]+ \(\d+[–-]\d+\) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$", table, flags=re.MULTILINE)]
    assert tuple(sum(col) for col in zip(*subtotal, strict=True)) == want, "sub-area rows do not add up to the total"


def test_wcon_doc_chain_every_requirement_maps_to_an_sdd_component():
    ids = set(_srs_rows())
    sdd = _read("SDD.md").split("## 7. Requirement-to-Component Map", 1)[1].split("## 8.", 1)[0]
    covered, referenced = set(), set()
    for line in sdd.splitlines():
        if not line.startswith("|") or line.startswith("|---") or "Requirements" in line.split("|")[1]:
            continue
        cell = line.split("|")[1]
        for a, b in re.findall(r"`(?:WCON-)?(\d+)`(?:\s*[–-]\s*`(\d+)`)?", cell):
            lo, hi = int(a), int(b or a)
            referenced.update({lo, hi})
            covered.update(i for i in ids if lo <= i <= hi)
    assert referenced <= ids, f"SDD map names unknown requirements: {sorted(referenced - ids)}"
    assert ids <= covered, f"requirements missing from SDD section 7: {sorted(ids - covered)}"


def test_wcon_doc_chain_rtm_components_exist_in_the_sdd():
    sdd = _read("SDD.md")
    sections = set(re.findall(r"^### (3\.\d+) ", sdd, flags=re.MULTILINE))
    used = set(re.findall(r"SDD (3\.\d+) ", _read("RTM.md")))
    assert used <= sections, f"RTM cites SDD sections that do not exist: {sorted(used - sections)}"


def test_wcon_doc_chain_every_rtm_test_case_has_exactly_one_test_here():
    src = Path(__file__).read_text(encoding="utf-8")
    marked = re.findall(r'@pytest\.mark\.requirement\("TC-WCON-(\d+)"\)', src)
    assert len(marked) == len(set(marked)), "a TC-WCON id is used by more than one test"
    assert {int(m) for m in marked} == set(_rtm_ids()), "tests and RTM rows differ"
    for tc in re.findall(r"`(TC-WCON-\d+)`", _read("RTM.md")):
        assert f'"{tc}"' in src, f"{tc} has no test"


def test_wcon_doc_chain_test_priorities_match_the_srs():
    src = Path(__file__).read_text(encoding="utf-8")
    pairs = re.findall(r'@pytest\.mark\.requirement\("TC-WCON-(\d+)"\)\n@pytest\.mark\.priority\("(\w+)"\)', src)
    srs = _srs_rows()
    assert {int(n) for n, _ in pairs} == set(srs)
    wrong = [(n, p, srs[int(n)]) for n, p in pairs if srs[int(n)] != p]
    assert not wrong, f"priority differs from SRS: {wrong}"


# ---------------------------------------------------------------------------
# Requirement tests
# ---------------------------------------------------------------------------


@pytest.mark.requirement("TC-WCON-010")
@pytest.mark.priority("MVP")
def test_tc_wcon_010_be_delivered_as_a_first_party():
    """WCON-010: The system shall be delivered as a first-party plugin with the manifest identity WCON, distributed as a ZIP from the Galileo Plugins repository and installed through PLUG-090/PLUG-110; it shall not be bundled in the Galileo …"""
    _pending("TC-WCON-010", "webconnect.plugin")


@pytest.mark.requirement("TC-WCON-020")
@pytest.mark.priority("MVP")
def test_tc_wcon_020_be_enabled_only_on_a_master():
    """WCON-020: The system shall be enabled only on a Master node."""
    _pending("TC-WCON-020", "webconnect.plugin")


@pytest.mark.requirement("TC-WCON-030")
@pytest.mark.priority("MVP")
def test_tc_wcon_030_while_enabled_the_system_shall_run():
    """WCON-030: While enabled, the system shall run the operating web application as a Flask application under a production WSGI server (never Flask's development server) in a separate operating-system process that the plugin starts, supervises …"""
    _pending("TC-WCON-030", "webconnect.supervisor")


@pytest.mark.requirement("TC-WCON-040")
@pytest.mark.priority("MVP")
def test_tc_wcon_040_while_disabled_the_system_shall_be():
    """WCON-040: While disabled, the system shall be fully inert (PLUG-060): every web process stopped, every listener closed, every browser session ended, no background activity."""
    _pending("TC-WCON-040", "webconnect.plugin")


@pytest.mark.requirement("TC-WCON-050")
@pytest.mark.priority("MVP")
def test_tc_wcon_050_add_a_top_level_webconnect_section():
    """WCON-050: The system shall add a top-level WebConnect section (PLUG-130) showing the address to open, signed-in browsers (name, browser and platform, role, Piers they hold a lease on, sign-in time), pending pairing requests, recent alerts …"""
    _pending("TC-WCON-050", "webconnect.config")


@pytest.mark.requirement("TC-WCON-060")
@pytest.mark.priority("MVP")
def test_tc_wcon_060_bind_the_operating_web_application_to():
    """WCON-060: The system shall bind the operating web application to a configurable address and port, defaulting to the Master's LAN interface and not to all interfaces; binding more widely shall require an explicit setting."""
    cfg_mod = pytest.importorskip("webconnect.config")
    cfg = cfg_mod.WebConnectConfig.from_dict({})
    all_interfaces = ("0.0.0.0", "::", "")  # noqa: S104
    assert cfg.bind_address not in all_interfaces, "must default to the LAN interface, not all interfaces"
    assert 1 <= cfg.port <= 65535


@pytest.mark.requirement("TC-WCON-070")
@pytest.mark.priority("MVP")
def test_tc_wcon_070_serve_the_operating_web_application_over():
    """WCON-070: The system shall serve the operating web application over HTTPS only."""
    _pending("TC-WCON-070", "webconnect.supervisor")


@pytest.mark.requirement("TC-WCON-080")
@pytest.mark.priority("MVP")
def test_tc_wcon_080_never_run_network_or_rendering_work():
    """WCON-080: The system shall never run network or rendering work on the Qt UI thread, and shall keep serving cost bounded so a Raspberry Pi 5-class Master running a session is not disturbed: previews rendered on demand and cached, state …"""
    _pending("TC-WCON-080", "webconnect.plugin")


@pytest.mark.requirement("TC-WCON-090")
@pytest.mark.priority("MVP")
def test_tc_wcon_090_the_web_processes_shall_reach_galileo():
    """WCON-090: The web processes shall reach Galileo only through Connect Link, authenticated with their own paired credential , and shall use only the documented wire API (PSD PC7)."""
    pytest.importorskip("webconnect.web")
    code = (
        "import sys, webconnect.web; "
        "bad = [m for m in sys.modules if m == 'galileo' or m.startswith('galileo.')]; "
        "sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)  # noqa: S603
    assert r.returncode == 0, r.stderr or "the web half imported a galileo module"


@pytest.mark.requirement("TC-WCON-100")
@pytest.mark.priority("MVP")
def test_tc_wcon_100_register_a_browser_only_through_connect():
    """WCON-100: The system shall register a browser only through Connect Link's pairing flow (needs CL, L2): the browser submits a pairing request identifying itself (a name the user types, browser and platform), the request and a short …"""
    _pending("TC-WCON-100", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-110")
@pytest.mark.priority("MVP")
def test_tc_wcon_110_assign_every_approved_browser_one_of():
    """WCON-110: The system shall assign every approved browser one of two roles, Viewer (state, events and images only) or Operator (Viewer plus operations)."""
    _pending("TC-WCON-110", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-120")
@pytest.mark.priority("MVP")
def test_tc_wcon_120_enforce_the_role_on_the_master(app, link):
    """WCON-120: The system shall enforce the role on the Master for every request: a Viewer's operation request is refused with a reason and audited."""
    b = op_browser_factory(app, link, role="viewer", peer="peer-v")
    r = b.post("/api/v1/pier/p1/ops/mount.slew", json={"ra": 1, "dec": 2})
    assert r.status_code == 403
    assert r.get_json()["error"] == "refused"
    who = link.calls[-1][2]
    assert who == "peer-v", "the request must be presented on behalf of the browser, not the service"


@pytest.mark.requirement("TC-WCON-130")
@pytest.mark.priority("MVP")
def test_tc_wcon_130_never_grant_an_approved_browser_the(app, link):
    """WCON-130: The system shall never grant an approved browser the config."""
    forbidden = ("config", "settings", "options", "equipment", "profile", "plugins")
    for rule in app.url_map.iter_rules():
        assert not any(f in rule.rule.lower() for f in forbidden), f"configuration-like route registered: {rule.rule}"
    b = op_browser_factory(app, link)
    link.handlers["ops"] = lambda body, who, h: (404, {"error": "unavailable", "reason": "not in catalogue"})
    r = b.post("/api/v1/pier/p1/ops/config.write", json={})
    assert r.status_code == 404 and r.get_json()["error"] == "unavailable"


@pytest.mark.requirement("TC-WCON-140")
@pytest.mark.priority("MVP")
def test_tc_wcon_140_apply_the_control_lease_per_pier():
    """WCON-140: The system shall apply the control lease per Pier with the semantics of MCON-140: an Operator holds a Pier's lease to issue a Pier-affecting operation; the lease is shared with the desktop and with MobileConnect clients; it is …"""
    _pending("TC-WCON-140", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-150")
@pytest.mark.priority("MVP")
def test_tc_wcon_150_when_an_operation_is_refused_because():
    """WCON-150: When an operation is refused because another party holds the lease, the refusal shall identify the holder and offer the confirmation of WCON-180 to take it, as MCON-150."""
    _pending("TC-WCON-150", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-160")
@pytest.mark.priority("MVP")
def test_tc_wcon_160_the_emergency_operations_wcon_710_shall():
    """WCON-160: The Emergency operations (WCON-710) shall not require the lease and shall be permitted to any approved Operator."""
    _pending("TC-WCON-160", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-170")
@pytest.mark.priority("MVP")
def test_tc_wcon_170_immediately_ending_its_sessions_and_open():
    """WCON-170: The system shall let the user on the Master revoke any approved browser — immediately ending its sessions and open streams and invalidating its device credential — and optionally set a per-browser expiry."""
    _pending("TC-WCON-170", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-180")
@pytest.mark.priority("MVP")
def test_tc_wcon_180_require_confirmation_for_the_destructive_or(app, link):
    """WCON-180: The system shall require confirmation for the destructive or hard-to-reverse operations defined by the Control Surface permission class (at least those listed in MCON-180), enforced by a two-step request whose confirmation token …"""
    b = op_browser_factory(app, link)

    def handler(body, who, headers):
        if headers.get("X-Confirm-Token") == "t1":
            return 200, {"ok": True}
        return 409, {"error": "confirmation_required", "token": "t1"}

    link.handlers["ops"] = handler
    first = b.post("/api/v1/pier/p1/ops/mount.park", json={})
    assert first.status_code == 409 and first.get_json()["token"] == "t1"
    second = b.post("/api/v1/pier/p1/ops/mount.park", json={}, headers={"X-Confirm-Token": "t1"})
    assert second.status_code == 200
    assert link.calls[-1][3].get("X-Confirm-Token") == "t1", "the token must reach the Master unchanged"


@pytest.mark.requirement("TC-WCON-190")
@pytest.mark.priority("MVP")
def test_tc_wcon_190_browser_identity_role_pier_operation_and():
    """WCON-190: The system shall record every request by every browser — browser identity, role, Pier, operation and arguments (secrets elided), time, outcome — in the Connect Link audit log, shown on the plugin page, filterable and retained for …"""
    _pending("TC-WCON-190", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-200")
@pytest.mark.priority("MVP")
def test_tc_wcon_200_present_to_a_browser_the_piers():
    """WCON-200: The system shall present to a browser the Piers of the Master and, through it, those of every paired spoke node in one list, over one address, one sign-in, one lease model and one audit log."""
    _pending("TC-WCON-200", "webconnect.relay")


@pytest.mark.requirement("TC-WCON-210")
@pytest.mark.priority("MVP")
def test_tc_wcon_210_for_a_spoke_s_pier_the():
    """WCON-210: For a spoke's Pier, the system shall relay operations, state, events and previews over Connect Link , forwarding the identity of the approved browser so the spoke can audit it."""
    _pending("TC-WCON-210", "webconnect.relay")


@pytest.mark.requirement("TC-WCON-220")
@pytest.mark.priority("MVP")
def test_tc_wcon_220_reach_a_spoke_only_if_the():
    """WCON-220: The system shall reach a spoke only if the spoke's user has granted the Master the opt-in right to operate it (control and view scopes, never config.), revocable on the spoke at any time."""
    _pending("TC-WCON-220", "webconnect.relay")


@pytest.mark.requirement("TC-WCON-230")
@pytest.mark.priority("MVP")
def test_tc_wcon_230_the_control_lease_for_a_spoke():
    """WCON-230: The control lease for a spoke's Pier shall be held on that spoke, so its desktop, a MobileConnect client and this plugin contend through one lease."""
    _pending("TC-WCON-230", "webconnect.relay")


@pytest.mark.requirement("TC-WCON-240")
@pytest.mark.priority("MVP")
def test_tc_wcon_240_when_the_master_cannot_reach_a():
    """WCON-240: When the Master cannot reach a spoke, the system shall show that spoke's Piers as unreachable (with the time last heard from), refuse operations to them with that reason, and resume without re-pairing when it returns."""
    _pending("TC-WCON-240", "webconnect.relay")


@pytest.mark.requirement("TC-WCON-250")
@pytest.mark.priority("MVP")
def test_tc_wcon_250_be_exposed_as_one_interface_relayport():
    """WCON-250: The relay shall be exposed as one interface (RelayPort) that MobileConnect and WebConnect consume without knowledge of each other, so that either plugin works with the other absent and neither forks the relay."""
    _pending("TC-WCON-250", "webconnect.relay")


@pytest.mark.requirement("TC-WCON-300")
@pytest.mark.priority("MVP")
def test_tc_wcon_300_on_opening_the_event_stream_the():
    """WCON-300: On opening the event stream the system shall send the browser a complete snapshot of the state of every Pier it may see, then only changes, so that a newly signed-in browser shows live state for every Pier within a few seconds."""
    _pending("TC-WCON-300", "webconnect.web.events")


@pytest.mark.requirement("TC-WCON-310")
@pytest.mark.priority("MVP")
def test_tc_wcon_310_deliver_state_events_and_alerts_to(app, link):
    """WCON-310: The system shall deliver state, events and alerts to the browser by Server-Sent Events (PSD D1), derived from galileo.bus events and the Control Surface's observable state ."""
    b = op_browser_factory(app, link)
    link.stream_events = [(1, "snapshot", {"piers": {}}), (2, "delta", {"k": "v"})]
    r = b.get("/events")
    assert r.status_code == 200
    assert r.mimetype == "text/event-stream"
    text = r.get_data(as_text=True)
    assert text.index("event: snapshot") < text.index("event: delta"), "snapshot must come first"
    assert "id: 1" in text and "id: 2" in text


@pytest.mark.requirement("TC-WCON-320")
@pytest.mark.priority("MVP")
def test_tc_wcon_320_the_state_delivered_shall_include_for():
    """WCON-320: The state delivered shall include, for each Pier, what MCON-320 lists, including the same activity record as the Dashboard timelines (OBS-150, galileo.dashboard_timeline)."""
    _pending("TC-WCON-320", "webconnect.web.events")


@pytest.mark.requirement("TC-WCON-330")
@pytest.mark.priority("MVP")
def test_tc_wcon_330_long_running_operations_slew_solve_autofocus():
    """WCON-330: Long-running operations (slew, solve, autofocus run, session, calibration set, flip) shall be reported as started / progress / finished events carrying a correlation id , which the page ties to the request that began them and …"""
    _pending("TC-WCON-330", "webconnect.web.events")


@pytest.mark.requirement("TC-WCON-340")
@pytest.mark.priority("MVP")
def test_tc_wcon_340_forward_the_node_s_alerts_to():
    """WCON-340: The system shall forward the node's alerts to the page while it is open, keep a recent-alerts list available on request, and make an alert conspicuous (visual, and audible if the user enables it)."""
    _pending("TC-WCON-340", "webconnect.web.events")


@pytest.mark.requirement("TC-WCON-350")
@pytest.mark.priority("MVP")
def test_tc_wcon_350_on_reconnection_after_a_drop_the(app, link):
    """WCON-350: On reconnection after a drop the system shall resume the event stream from the browser's last event id where the events are still held, and otherwise send a fresh snapshot, so the page never shows stale state as current."""
    b = op_browser_factory(app, link)
    link.stream_events = [(1, "snapshot", {}), (2, "delta", {"a": 1}), (3, "delta", {"a": 2})]
    text = b.get("/events", headers={"Last-Event-ID": "2"}).get_data(as_text=True)
    assert "id: 3" in text
    assert "id: 1" not in text and "id: 2" not in text, "events already seen must not be replayed"


@pytest.mark.requirement("TC-WCON-360")
@pytest.mark.priority("P2")
def test_tc_wcon_360_deliver_the_state_of_a_pier():
    """WCON-360: The system shall deliver the state of a Pier to a browser only if that Pier is among those the plugin's options expose (WCON-910) and the browser's role permits viewing."""
    _pending("TC-WCON-360", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-400")
@pytest.mark.priority("MVP")
def test_tc_wcon_400_publish_the_operations_to_the_page():
    """WCON-400: The system shall publish the operations to the page as a catalogue from the Control Surface and drive the page from it."""
    _pending("TC-WCON-400", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-410")
@pytest.mark.priority("MVP")
def test_tc_wcon_410_as_mcon_410_list_observatories_and():
    """WCON-410: Observatory and Pier — as MCON-410: list Observatories and Piers, choose the working Pier, view the Dashboard timelines of every Pier."""
    _pending("TC-WCON-410", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-420")
@pytest.mark.priority("MVP")
def test_tc_wcon_420_as_mcon_420_connect_and_disconnect():
    """WCON-420: Devices — as MCON-420: connect and disconnect devices and operate the mount, camera, filter wheel, rotator, dome, flat panel and switches; view weather and safety-monitor state; focuser movement only under Focus (WCON-470)."""
    _pending("TC-WCON-420", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-421")
@pytest.mark.priority("MVP")
def test_tc_wcon_421_after_a_mount_connects_through_an():
    """WCON-421: After a mount connects through an operation of this plugin, the same date/time and site latitude/longitude synchronisation shall occur as when connecting at the desktop."""
    _pending("TC-WCON-421", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-430")
@pytest.mark.priority("MVP")
def test_tc_wcon_430_as_mcon_430_live_exposure_loop():
    """WCON-430: Imaging — as MCON-430: live exposure loop, single and series captures, current-frame preview with stretch, histogram, statistics and star metrics, live stack, reject frames."""
    _pending("TC-WCON-430", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-440")
@pytest.mark.priority("MVP")
def test_tc_wcon_440_as_mcon_440_sky_view_with():
    """WCON-440: Sky and framing — as MCON-440: sky view with the mount's position, target search and selection, go-to, Framing Assistant, current-object details, Planning and visibility lists, Telescopius and AAVSO targets."""
    _pending("TC-WCON-440", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-450")
@pytest.mark.priority("MVP")
def test_tc_wcon_450_as_mcon_450():
    """WCON-450: Plate solving and alignment — as MCON-450."""
    _pending("TC-WCON-450", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-460")
@pytest.mark.priority("MVP")
def test_tc_wcon_460_as_mcon_460_including_the_error():
    """WCON-460: Guiding — as MCON-460, including the error trace and guide-star cut-out."""
    _pending("TC-WCON-460", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-470")
@pytest.mark.priority("MVP")
def test_tc_wcon_470_as_mcon_470_manual_focus_relative():
    """WCON-470: Focus — as MCON-470: manual focus (relative, absolute, halt, position and temperature) and autofocus (start, cancel, V-curve, result, temperature-compensation state) presented as one place; manual focus invoked through the focus …"""
    _pending("TC-WCON-470", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-480")
@pytest.mark.priority("MVP")
def test_tc_wcon_480_as_mcon_480_a_trigger_is():
    """WCON-480: Meridian flip — as MCON-480; a trigger is a confirmed operation (WCON-180)."""
    _pending("TC-WCON-480", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-490")
@pytest.mark.priority("MVP")
def test_tc_wcon_490_sessions_run_as_mcon_490_list():
    """WCON-490: Sessions, run — as MCON-490: list, load, run, pause, resume, skip and stop, with progress block by block."""
    _pending("TC-WCON-490", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-500")
@pytest.mark.priority("P2")
def test_tc_wcon_500_sessions_authoring_as_mcon_500_add():
    """WCON-500: Sessions, authoring — as MCON-500: add, remove, reorder and nest instruction, condition and trigger blocks, set parameters and save, using the Sessions model of the desktop, with plugin-registered blocks (SES-340) in the palette; …"""
    _pending("TC-WCON-500", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-510")
@pytest.mark.priority("P2")
def test_tc_wcon_510_as_mcon_510():
    """WCON-510: Scheduler — as MCON-510."""
    _pending("TC-WCON-510", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-520")
@pytest.mark.priority("P2")
def test_tc_wcon_520_as_mcon_520():
    """WCON-520: Calibration — as MCON-520."""
    _pending("TC-WCON-520", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-530")
@pytest.mark.priority("MVP")
def test_tc_wcon_530_as_mcon_530_every_safety_input():
    """WCON-530: Safety — as MCON-530: every safety input, overall state and stop reason; an Operator may acknowledge only, and resuming remains the decision of the core safety service."""
    _pending("TC-WCON-530", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-540")
@pytest.mark.priority("P2")
def test_tc_wcon_540_as_mcon_540_recent_sessions_and():
    """WCON-540: Library and history — as MCON-540: recent sessions and frames, quality metrics, history and charts; explicit FITS download under WCON-620."""
    _pending("TC-WCON-540", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-550")
@pytest.mark.priority("P2")
def test_tc_wcon_550_as_mcon_550_recent_alerts_visible():
    """WCON-550: Notifications — as MCON-550: recent alerts visible; channels and rules are configuration and not exposed."""
    _pending("TC-WCON-550", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-560")
@pytest.mark.priority("P3")
def test_tc_wcon_560_as_mcon_560_a_plugin_s():
    """WCON-560: Plugin surfaces — as MCON-560: a plugin's registered remote surface is listed and operated from the catalogue, rendered by a generic form view."""
    _pending("TC-WCON-560", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-570")
@pytest.mark.priority("MVP")
def test_tc_wcon_570_per_run_parameters_as_mcon_570():
    """WCON-570: Per-run parameters — as MCON-570: per-run parameters are accepted; any request on any route that would alter a stored definition listed as configuration is refused."""
    _pending("TC-WCON-570", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-580")
@pytest.mark.priority("MVP")
def test_tc_wcon_580_validate_every_operation_s_arguments_on(app, link):
    """WCON-580: The system shall validate every operation's arguments on the Master against the Control Surface's declared types and ranges and return a typed error (refused, invalid, unavailable, busy, unreachable) rather than an exception."""
    b = op_browser_factory(app, link)
    link.handlers["ops"] = lambda body, who, h: (422, {"error": "invalid", "reason": "exposure out of range", "detail": "args.exposure"})
    r = b.post("/api/v1/pier/p1/ops/camera.expose", json={"exposure": -1})
    assert r.status_code == 422 and r.get_json()["error"] == "invalid"

    def boom(body, who, h):
        raise ConnectionError("master gone")

    link.handlers["ops"] = boom
    r = b.post("/api/v1/pier/p1/ops/camera.expose", json={"exposure": 1})
    assert r.status_code in (502, 503, 504)
    assert r.get_json()["error"] == "unreachable", "an expected failure must be typed, never an HTTP 500"


@pytest.mark.requirement("TC-WCON-590")
@pytest.mark.priority("MVP")
def test_tc_wcon_590_parity_an_automated_check_shall_confirm():
    """WCON-590: Parity."""
    _pending("TC-WCON-590", "webconnect.wire")


@pytest.mark.requirement("TC-WCON-600")
@pytest.mark.priority("MVP")
def test_tc_wcon_600_deliver_images_as_server_rendered_previews():
    """WCON-600: The system shall deliver images as server-rendered previews : stretched and scaled to a size the page requests, JPEG-encoded, for the current exposure, any Library frame and any guide or focus cut-out."""
    _pending("TC-WCON-600", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-610")
@pytest.mark.priority("P2")
def test_tc_wcon_610_offer_a_preview_as_tiles_of():
    """WCON-610: The system shall offer a preview as tiles of a pyramid for pan and zoom, with a bounded server-side cache so repeated requests do not re-render."""
    _pending("TC-WCON-610", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-620")
@pytest.mark.priority("P3")
def test_tc_wcon_620_allow_an_operator_to_download_a(app, link):
    """WCON-620: The system shall allow an Operator to download a full FITS frame as an explicit action, with its size reported beforehand."""
    b = op_browser_factory(app, link, role="viewer", peer="peer-v")
    r = b.get("/api/v1/frame/1/fits")
    assert r.status_code == 403
    assert r.headers.get("Content-Disposition") is None


@pytest.mark.requirement("TC-WCON-630")
@pytest.mark.priority("P2")
def test_tc_wcon_630_expose_preview_quality_and_maximum_size():
    """WCON-630: The system shall expose preview quality and maximum size as options (WCON-910), let the page request a lower quality, and give session work priority over preview rendering."""
    _pending("TC-WCON-630", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-640")
@pytest.mark.priority("P2")
def test_tc_wcon_640_let_the_user_hold_the_tiles():
    """WCON-640: The page shall let the user hold the tiles of two frames at once for blink and side-by-side comparison, as MCON-670."""
    _pending("TC-WCON-640", "webconnect.web.ui")


@pytest.mark.requirement("TC-WCON-650")
@pytest.mark.priority("MVP")
def test_tc_wcon_650_render_the_sky_view_locally_in():
    """WCON-650: The page shall render the sky view locally in the browser from sky data streamed by the Master (needs SK; MCON-640, MCON-660): the browser shall ship no catalog and compute no ephemeris."""
    _pending("TC-WCON-650", "webconnect.web.api")


@pytest.mark.requirement("TC-WCON-700")
@pytest.mark.priority("MVP")
def test_tc_wcon_700_every_operation_shall_pass_through_the():
    """WCON-700: Every operation shall pass through the same core services and safety interlocks as the desktop UI."""
    _pending("TC-WCON-700", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-710")
@pytest.mark.priority("MVP")
def test_tc_wcon_710_stop_everything_park_close_dome_callable():
    """WCON-710: The system shall provide Emergency operations — Stop everything, Park, Close dome — callable by any approved Operator without the lease, present on every page, confirmed in the page by a deliberate gesture, succeeding in a single …"""
    _pending("TC-WCON-710", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-720")
@pytest.mark.priority("MVP")
def test_tc_wcon_720_imaging_shall_continue_unchanged_when_the():
    """WCON-720: Imaging shall continue, unchanged, when the browser tab is closed, the browser sleeps or the connection is lost; the node shall neither require a browser to remain connected nor stop a session when one disconnects."""
    _pending("TC-WCON-720", "webconnect.web.hold")


@pytest.mark.requirement("TC-WCON-730")
@pytest.mark.priority("MVP")
def test_tc_wcon_730_a_manual_slew_or_jog_and():
    """WCON-730: A manual slew or jog and a focuser move started from the browser shall run only while a keep-alive arrives from a pressed control ."""
    _pending("TC-WCON-730", "webconnect.web.hold")


@pytest.mark.requirement("TC-WCON-740")
@pytest.mark.priority("MVP")
def test_tc_wcon_740_an_operation_shall_carry_a_client(app, link):
    """WCON-740: An operation shall carry a client-generated idempotency key, and a retried request with the same key shall return the original result rather than repeat the operation, as MCON-740."""
    b = op_browser_factory(app, link)
    b.post("/api/v1/pier/p1/ops/camera.expose", json={"exposure": 1}, headers={"Idempotency-Key": "k-123"})
    assert link.calls[-1][3].get("Idempotency-Key") == "k-123"


@pytest.mark.requirement("TC-WCON-750")
@pytest.mark.priority("MVP")
def test_tc_wcon_750_where_a_command_is_refused_because(app, link):
    """WCON-750: Where a command is refused because the lease is held elsewhere, the Pier is unsafe, the device is busy or unconnected, or the target is unreachable, the system shall say so with a reason the page can display, never silently …"""
    b = op_browser_factory(app, link)
    link.handlers["ops"] = lambda body, who, h: (409, {"error": "refused", "reason": "lease_held", "detail": {"holder": "desktop", "can_take": True}})
    r = b.post("/api/v1/pier/p1/ops/mount.slew", json={"ra": 1, "dec": 2})
    j = r.get_json()
    assert r.status_code == 409 and j["reason"] == "lease_held"
    assert j["detail"]["holder"] == "desktop", "the refusal must name the holder (WCON-150)"


@pytest.mark.requirement("TC-WCON-760")
@pytest.mark.priority("MVP")
def test_tc_wcon_760_a_lease_shall_not_outlive_its():
    """WCON-760: A lease shall not outlive its holder: on sign-out, session expiry, event-stream close or idle timeout it is released and the desktop and other clients are told."""
    _pending("TC-WCON-760", "webconnect.delegate")


@pytest.mark.requirement("TC-WCON-770")
@pytest.mark.priority("P2")
def test_tc_wcon_770_a_flood_of_requests_from_one():
    """WCON-770: A flood of requests from one browser or source shall be rate-limited without affecting other clients, imaging or the Emergency operations."""
    _pending("TC-WCON-770", "webconnect.web.security")


@pytest.mark.requirement("TC-WCON-780")
@pytest.mark.priority("MVP")
def test_tc_wcon_780_while_the_event_stream_is_down():
    """WCON-780: While the event stream is down, the page shall mark all state as stale and disable Pier-affecting operations other than the Emergency operations, which shall remain attemptable, until the stream is restored."""
    _pending("TC-WCON-780", "webconnect.web.events")


@pytest.mark.requirement("TC-WCON-800")
@pytest.mark.priority("MVP")
def test_tc_wcon_800_be_built_from_server_rendered_templates(app, link):
    """WCON-800: The web application shall be built from server-rendered templates with light JavaScript (PSD D2)."""
    b = op_browser_factory(app, link)
    for page in (b.get("/").get_data(as_text=True), anon_browser(app).get("/pair").get_data(as_text=True)):
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", page, re.IGNORECASE), "inline script"
        assert not re.search(r"\son[a-z]+\s*=", page, re.IGNORECASE), "inline event handler"
        assert not re.search(r"\sstyle\s*=", page, re.IGNORECASE), "inline style"
        assert not re.search(r"""(?:src|href)\s*=\s*["']https?://""", page, re.IGNORECASE), "third-party resource"


@pytest.mark.requirement("TC-WCON-810")
@pytest.mark.priority("MVP")
def test_tc_wcon_810_be_responsive_and_tablet_first_the():
    """WCON-810: The interface shall be responsive and tablet-first: the large layout shows the sky view, image and session list side by side; narrower layouts reduce secondary panels progressively down to a phone; it shall be usable by touch and …"""
    _pending("TC-WCON-810", "webconnect.web.ui")


@pytest.mark.requirement("TC-WCON-820")
@pytest.mark.priority("MVP")
def test_tc_wcon_820_provide_a_screen_or_section_for():
    """WCON-820: The interface shall provide a screen or section for each operational area of Section 3.5, driven by the catalogue; an area the node does not offer shall be hidden or shown unavailable, never broken."""
    _pending("TC-WCON-820", "webconnect.web.ui")


@pytest.mark.requirement("TC-WCON-830")
@pytest.mark.priority("MVP")
def test_tc_wcon_830_guide_a_new_browser_through_pairing():
    """WCON-830: The interface shall guide a new browser through pairing (Section 3.2): request, display of the confirmation code, waiting for approval on the Master with a clear refused/expired outcome, and then sign-in."""
    _pending("TC-WCON-830", "webconnect.web.session")


@pytest.mark.requirement("TC-WCON-840")
@pytest.mark.priority("MVP")
def test_tc_wcon_840_show_at_all_times_the_browser():
    """WCON-840: The interface shall show at all times the browser's role, the lease state of the selected Pier and who holds it, the connection state, and the age of the state shown."""
    _pending("TC-WCON-840", "webconnect.web.ui")


@pytest.mark.requirement("TC-WCON-850")
@pytest.mark.priority("MVP")
def test_tc_wcon_850_hide_operations_a_viewer_cannot_perform():
    """WCON-850: The interface shall hide operations a Viewer cannot perform, shall present the confirmation of WCON-180 for confirmed operations, and shall show the Emergency operations (WCON-710) on every page."""
    _pending("TC-WCON-850", "webconnect.web.ui")


@pytest.mark.requirement("TC-WCON-860")
@pytest.mark.priority("MVP")
def test_tc_wcon_860_provide_a_night_vision_red_theme():
    """WCON-860: The interface shall provide a night-vision (red) theme that emits no non-red light — including form controls, scrollbars, dialogs, the loading state and the favicon — and shall remember the choice as a browser-side UI preference."""
    _pending("TC-WCON-860", "webconnect.web.ui")


@pytest.mark.requirement("TC-WCON-870")
@pytest.mark.priority("P2")
def test_tc_wcon_870_be_operable_by_keyboard_and_expose():
    """WCON-870: The interface shall be operable by keyboard and expose roles, names and live regions to assistive technology for its non-imaging controls, targeting WCAG 2.1 level AA."""
    _pending("TC-WCON-870", "webconnect.web.ui")


@pytest.mark.requirement("TC-WCON-880")
@pytest.mark.priority("MVP")
def test_tc_wcon_880_be_tested_against_the_browser_support():
    """WCON-880: The interface shall be tested against the browser support matrix of PSD PC8 (current Chrome and Edge, Firefox, Safari on iOS, iPadOS and macOS, Chrome on Android)."""
    _pending("TC-WCON-880", "webconnect.web.ui")


@pytest.mark.requirement("TC-WCON-890")
@pytest.mark.priority("P2")
def test_tc_wcon_890_provide_help_for_each_screen_and():
    """WCON-890: The interface shall provide help for each screen, and an About view showing the Galileo, plugin and protocol versions and the browser's own pairing details."""
    _pending("TC-WCON-890", "webconnect.web.ui")


@pytest.mark.requirement("TC-WCON-900")
@pytest.mark.priority("MVP")
def test_tc_wcon_900_add_a_webconnect_page_under_options():
    """WCON-900: The system shall add a WebConnect page under Options (PLUG-170) in which a Master user manages approved browsers (list, role, revoke, expiry) and pending approvals."""
    _pending("TC-WCON-900", "webconnect.config")


@pytest.mark.requirement("TC-WCON-910")
@pytest.mark.priority("MVP")
def test_tc_wcon_910_provide_and_persist_in_galileo_s(tmp_path, monkeypatch):
    """WCON-910: The system shall provide, and persist in Galileo's database under the plugin's namespace (PLUG-150), these options: bind address and port, whether to start with Galileo, TLS certificate source, which Piers are exposed, session …"""
    cfg_mod = pytest.importorskip("webconnect.config")
    cfg = cfg_mod.WebConnectConfig.from_dict(
        {"port": 10**6, "session_idle_s": -5, "session_abs_s": 0, "lease_idle_s": -1, "audit_retention_days": 10**9, "preview_quality": 500}
    )
    assert 1 <= cfg.port <= 65535
    assert cfg.session_idle_s > 0 and cfg.session_abs_s >= cfg.session_idle_s
    assert cfg.lease_idle_s > 0
    assert 1 <= cfg.preview_quality <= 100
    assert cfg.audit_retention_days < 10**9
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    cfg_mod.WebConnectConfig.from_dict({})
    assert set(tmp_path.iterdir()) == before, "configuration must never be written to a plugin-private file"


@pytest.mark.requirement("TC-WCON-920")
@pytest.mark.priority("MVP")
def test_tc_wcon_920_describe_its_browser_facing_api_in():
    """WCON-920: The system shall describe its browser-facing API in a published, language-neutral form (OpenAPI for requests, a schema for the event stream), versioned /webconnect/v1/..., generated from the types the server validates against so …"""
    _pending("TC-WCON-920", "webconnect.wire")


@pytest.mark.requirement("TC-WCON-930")
@pytest.mark.priority("MVP")
def test_tc_wcon_930_perform_the_connect_link_version_handshake():
    """WCON-930: The system shall perform the Connect Link version handshake (L8) when its web process starts and on reconnection, refuse to operate against an incompatible Galileo with a message naming the versions, and report operation areas …"""
    _pending("TC-WCON-930", "webconnect.wire")


@pytest.mark.requirement("TC-WCON-940")
@pytest.mark.priority("MVP")
def test_tc_wcon_940_ship_help_markdown_for_every_control():
    """WCON-940: The system shall ship help Markdown for every control on its plugin page and Options page (HELP-060), registered through the plugin help mechanism, and shall pass the help audit."""
    _pending("TC-WCON-940", "webconnect.config")


@pytest.mark.requirement("TC-WCON-1000")
@pytest.mark.priority("MVP")
def test_tc_wcon_1000_every_state_changing_request_any_method(app, link):
    """WCON-1000: Every state-changing request (any method other than GET, HEAD, OPTIONS) shall be rejected unless it carries a valid CSRF token bound to the session and comes from the application's own origin."""
    b = op_browser_factory(app, link)
    url = "/api/v1/pier/p1/ops/camera.expose"
    n = len(link.calls)
    assert b.post(url, json={}, csrf=False).status_code == 403, "missing token"
    assert b.post(url, json={}, csrf="forged").status_code == 403, "forged token"
    assert b.post(url, json={}, origin="https://evil.test").status_code == 403, "foreign origin"
    assert b.post(url, json={}, origin=False).status_code == 403, "no origin"
    assert len(link.calls) == n, "a rejected request must never reach the Master"
    assert b.post(url, json={}).status_code == 200


@pytest.mark.requirement("TC-WCON-1010")
@pytest.mark.priority("MVP")
def test_tc_wcon_1010_session_and_device_cookies_shall_be(app, link):
    """WCON-1010: Session and device cookies shall be HttpOnly, Secure and SameSite=Strict, host-bound (__Host- prefix), and a session identifier shall be regenerated at sign-in, on role change and at sign-out."""
    b = anon_browser(app)
    link.devices["dev-tok"] = ("peer-1", "operator")
    link.roles["peer-1"] = "operator"

    def session_cookie(browser):
        browser.c.set_cookie("__Host-wc_device", "dev-tok", domain=browser.host)
        r = browser.post("/signin", csrf=False)
        cookies = [c for c in r.headers.getlist("Set-Cookie") if c.startswith("__Host-wc_session=")]
        assert len(cookies) == 1, "a session cookie, host-bound, must be set at sign-in"
        flags = cookies[0].lower()
        assert "httponly" in flags and "secure" in flags and "samesite=strict" in flags and "path=/" in flags
        assert "domain=" not in flags, "__Host- cookies carry no Domain attribute"
        return cookies[0].split(";")[0]

    first = session_cookie(b)
    second = session_cookie(anon_browser(app))
    assert first != second, "the session identifier must be regenerated at every sign-in"


@pytest.mark.requirement("TC-WCON-1020")
@pytest.mark.priority("MVP")
def test_tc_wcon_1020_every_response_shall_carry_a_strict(app, link):
    """WCON-1020: Every response shall carry a strict Content-Security-Policy that permits no inline script, no inline event handler and no third-party origin, and also X-Content-Type-Options: nosniff, Referrer-Policy: no-referrer and a …"""
    b = op_browser_factory(app, link)
    for path in ("/", "/api/v1/piers"):
        r = b.get(path)
        csp = r.headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        for bad in ("unsafe-inline", "unsafe-eval", "http:", "https:"):
            assert bad not in csp, f"CSP contains {bad!r}: {csp}"
        assert "*" not in csp, "no wildcard sources"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "no-store" in b.get("/api/v1/piers").headers["Cache-Control"]


@pytest.mark.requirement("TC-WCON-1030")
@pytest.mark.priority("MVP")
def test_tc_wcon_1030_sign_in_pairing_requests_and_any(app):
    """WCON-1030: Sign-in, pairing requests and any other unauthenticated entry point shall be rate-limited per source, with an increasing delay on repeated failure."""
    b = anon_browser(app)
    codes = [b.post("/signin", csrf=False).status_code for _ in range(40)]
    assert 429 in codes, "repeated failed sign-ins from one source must be rate-limited"
    other = anon_browser(app, addr="192.168.1.99")
    assert other.get("/pair").status_code == 200, "another source must be unaffected"


@pytest.mark.requirement("TC-WCON-1040")
@pytest.mark.priority("MVP")
def test_tc_wcon_1040_a_session_shall_expire_after_configurable(app, link, clock):
    """WCON-1040: A session shall expire after configurable idle and absolute timeouts, after which the page shall require a new sign-in."""
    b = op_browser_factory(app, link)
    assert b.get("/api/v1/piers").status_code == 200
    clock.advance(601)  # idle timeout is 600 s in the fixture
    assert b.get("/api/v1/piers").status_code in (401, 302), "idle session must expire"
    assert b.post("/signin", csrf=False).status_code in (200, 204, 302), "one-click sign-in with the device credential"
    for _ in range(8):
        clock.advance(500)  # keeps it alive past the 3600 s absolute limit
        b.get("/api/v1/piers")
    assert b.get("/api/v1/piers").status_code in (401, 302), "absolute timeout must expire an active session"
    assert b.get("/sw.js").status_code == 404, "no service worker"
    assert "serviceWorker" not in anon_browser(app).get("/pair").get_data(as_text=True)


@pytest.mark.requirement("TC-WCON-1050")
@pytest.mark.priority("MVP")
def test_tc_wcon_1050_every_route_shall_require_an_authenticated(app):
    """WCON-1050: Every route shall require an authenticated session, a role check and (for state-changing routes) a CSRF check, except those named in a single explicit public-route list."""
    web = pytest.importorskip("webconnect.web")
    b = anon_browser(app)
    public = set(web.PUBLIC_ROUTES)
    assert public <= {"/pair", "/pair/request", "/pair/wait", "/signin", "/static/<path:filename>", "/healthz"}
    for rule in app.url_map.iter_rules():
        if rule.rule in public:
            continue
        path = re.sub(r"<[^>]+>", "1", rule.rule)
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            r = b.req(method, path)
            assert r.status_code in (302, 401, 403), f"{method} {rule.rule} answered {r.status_code} without a session"


@pytest.mark.requirement("TC-WCON-1060")
@pytest.mark.priority("MVP")
def test_tc_wcon_1060_the_application_shall_reject_a_request(app):
    """WCON-1060: The application shall reject a request whose Host or Origin is not one of the addresses it is configured to serve, as a defence against DNS rebinding and cross-origin use."""
    b = anon_browser(app, host="evil.test")
    assert b.get("/pair").status_code in (400, 403, 421), "unknown Host must be refused (DNS rebinding)"
    assert anon_browser(app).get("/pair").status_code == 200


@pytest.mark.requirement("TC-WCON-1070")
@pytest.mark.priority("P2")
def test_tc_wcon_1070_undergo_a_documented_security_review_csrf():
    """WCON-1070: The web application shall undergo a documented security review (CSRF, session handling, header policy, route enumeration, dependency audit) before each release that changes it, with its findings resolved or recorded."""
    _pending("TC-WCON-1070", "webconnect.web.security")


@pytest.mark.requirement("TC-WCON-1200")
@pytest.mark.priority("MVP")
def test_tc_wcon_1200_the_owner_shall_choose_on_connect():
    """WCON-1200: The owner shall choose, on Connect Link's Outreach page, whether an event is offered to apps, to browsers or to both."""
    _pending("TC-WCON-1200", "webconnect.outreach")


@pytest.mark.requirement("TC-WCON-1210")
@pytest.mark.priority("MVP")
def test_tc_wcon_1210_serve_browser_outreach_from_a_separate():
    """WCON-1210: The system shall serve browser outreach from a separate, minimal Flask application with its own process and listener, bound to the outreach network's address and port and started only while a browser-enabled event is open and …"""
    pytest.importorskip("webconnect.outreach_app")
    code = "import sys, webconnect.outreach_app; sys.exit(1 if any(m == 'webconnect.web' or m.startswith('webconnect.web.') for m in sys.modules) else 0)"
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)  # noqa: S603
    assert r.returncode == 0, "the outreach application must contain no code from the operating application"


@pytest.mark.requirement("TC-WCON-1220")
@pytest.mark.priority("MVP")
def test_tc_wcon_1220_the_operating_web_application_shall_not(link, clock):
    """WCON-1220: The operating web application shall not be reachable on the outreach listener, and shall itself refuse any request whose source address lies in a configured outreach subnet."""
    pytest.importorskip("flask")
    web = pytest.importorskip("webconnect.web")
    guarded = web.create_app(
        {"allowed_hosts": ["wc.test"], "session_idle_s": 600, "session_abs_s": 3600, "outreach_subnets": ["192.168.50.0/24"]},
        link, clock=clock,
    )
    assert anon_browser(guarded, addr="192.168.50.20").get("/pair").status_code in (403, 404), "outreach subnet must be refused"
    assert anon_browser(guarded, addr="192.168.1.20").get("/pair").status_code == 200


@pytest.mark.requirement("TC-WCON-1230")
@pytest.mark.priority("MVP")
def test_tc_wcon_1230_the_event_display_shall_include_a():
    """WCON-1230: The event display shall include a web QR code encoding an HTTPS address of the outreach page with the event identifier and secret in the URL fragment (https://<host>:<port>/outreach#e=<event>&s=<secret>), and the address as short …"""
    outreach = pytest.importorskip("webconnect.outreach")
    url = outreach.qr_payload("sky.test", 8443, "ev1", "s3cret")
    parts = urlsplit(url)
    assert parts.scheme == "https" and parts.netloc == "sky.test:8443" and parts.path == "/outreach"
    assert parts.query == "", "the secret must not be in the query"
    assert "s3cret" not in parts.path
    frag = parse_qs(parts.fragment)
    assert frag["e"] == ["ev1"] and frag["s"] == ["s3cret"], "event and secret travel in the fragment"


@pytest.mark.requirement("TC-WCON-1240")
@pytest.mark.priority("MVP")
def test_tc_wcon_1240_read_the_fragment_exchange_the_secret(facility, clock):
    """WCON-1240: The outreach page shall read the fragment, exchange the secret for a guest token by a single enrolment request, remove the fragment from the address bar and history, and hold the token only in a HttpOnly, Secure, SameSite=Strict, …"""
    pytest.importorskip("flask")
    oapp = outreach_app_factory(facility, clock)
    b = anon_browser(oapp, host="sky.test", addr="192.168.50.20")
    bad = b.post("/outreach/enrol", json={"event": "ev1", "secret": "wrong"})
    assert bad.status_code in (401, 403) and not bad.headers.getlist("Set-Cookie")
    noorigin = b.post("/outreach/enrol", json={"event": "ev1", "secret": "s3cret"}, origin=False)
    assert noorigin.status_code in (400, 403)
    ok = b.post("/outreach/enrol", json={"event": "ev1", "secret": "s3cret"})
    assert ok.status_code in (200, 204)
    cookie = [c for c in ok.headers.getlist("Set-Cookie") if c.startswith("__Host-wc_guest=")]
    assert len(cookie) == 1
    low = cookie[0].lower()
    assert "httponly" in low and "secure" in low and "samesite=strict" in low and "domain=" not in low
    # the page script reads the fragment, scrubs it, and stores nothing durable
    pkg = Path(pytest.importorskip("webconnect.outreach_app").__file__).parent
    js = "\n".join(p.read_text(encoding="utf-8") for p in pkg.rglob("*.js"))
    assert js, "the outreach page must ship its own script"
    assert "location.hash" in js and "history.replaceState" in js
    assert "localStorage" not in js and "sessionStorage" not in js


@pytest.mark.requirement("TC-WCON-1250")
@pytest.mark.priority("MVP")
def test_tc_wcon_1250_a_guest_token_outreach_view_and(facility, clock):
    """WCON-1250: A guest token (outreach.view and nothing else) shall permit exactly: listing the Piers offered (display names only), receiving the live image of an offered Pier, and switching between offered Piers."""
    pytest.importorskip("flask")
    oapp = outreach_app_factory(facility, clock)
    rules = {re.sub(r"<[^>]+>", "<>", r.rule) for r in oapp.url_map.iter_rules()}
    assert rules == {"/outreach", "/outreach/static/<>", "/outreach/enrol", "/outreach/piers", "/outreach/stream", "/outreach/img/<>/<>"}
    b = guest_browser(oapp, facility)
    for path in ("/", "/events", "/signin", "/api/v1/piers", "/api/v1/pier/p1/ops/x", "/outreach/config", "/outreach/frames/1"):
        assert b.get(path).status_code == 404, path
    assert b.get("/outreach/piers").status_code == 200
    names = [p["name"] for p in b.get("/outreach/piers").get_json()]
    assert names == ["North"], "display names only"


@pytest.mark.requirement("TC-WCON-1260")
@pytest.mark.priority("MVP")
def test_tc_wcon_1260_push_to_each_visitor_the_live(facility, clock):
    """WCON-1260: The system shall push to each visitor the live image of the chosen Pier as each frame completes, by Server-Sent Events, with the image's age; a visitor who joins or switches Pier shall receive the latest image at once; a Pier …"""
    pytest.importorskip("flask")
    oapp = outreach_app_factory(facility, clock)
    b = guest_browser(oapp, facility)
    r = b.get("/outreach/stream?pier=p1")
    assert r.mimetype == "text/event-stream"
    text = r.get_data(as_text=True)
    assert "event: image" in text, "the latest image is sent at once"
    assert "/outreach/img/p1/1" in text
    assert b"\xff\xd8" not in r.get_data(), "images are fetched by URL, not inlined in the stream"
    img = b.get("/outreach/img/p1/1")
    assert img.status_code == 200 and img.mimetype == "image/jpeg"
    assert "no-store" in img.headers["Cache-Control"]
    assert b.get("/outreach/stream?pier=not-offered").status_code == 404


@pytest.mark.requirement("TC-WCON-1270")
@pytest.mark.priority("MVP")
def test_tc_wcon_1270_images_sent_to_visitors_shall_be():
    """WCON-1270: Images sent to visitors shall be the facility's guest previews: limited to the guest size and quality, and carrying no FITS header, EXIF, GPS or other embedded metadata."""
    _pending("TC-WCON-1270", "webconnect.outreach")


@pytest.mark.requirement("TC-WCON-1280")
@pytest.mark.priority("MVP")
def test_tc_wcon_1280_be_hardened_for_the_public_a(facility, clock):
    """WCON-1280: The outreach application shall be hardened for the public: a strict Content-Security-Policy with no inline script and no third-party resource of any kind (the outreach network may have no internet), Referrer-Policy: no-referrer, …"""
    pytest.importorskip("flask")
    oapp = outreach_app_factory(facility, clock)
    b = guest_browser(oapp, facility)
    r = b.get("/outreach")
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp
    for bad in ("unsafe-inline", "unsafe-eval", "http:", "https:"):
        assert bad not in csp
    assert r.headers["Referrer-Policy"] == "no-referrer"
    page = r.get_data(as_text=True)
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", page, re.IGNORECASE)
    assert not re.search(r"""(?:src|href)\s*=\s*["']https?://""", page, re.IGNORECASE), "no third-party resource"
    assert "serviceWorker" not in page
    assert "no-store" in b.get("/outreach/img/p1/1").headers["Cache-Control"]


@pytest.mark.requirement("TC-WCON-1290")
@pytest.mark.priority("MVP")
def test_tc_wcon_1290_the_outreach_listener_shall_serve_https(facility, clock):
    """WCON-1290: The outreach listener shall serve HTTPS only, using a certificate the owner supplies for a stable name on the outreach network."""
    pytest.importorskip("flask")
    oapp_mod = pytest.importorskip("webconnect.outreach_app")
    with pytest.raises((ValueError, RuntimeError)):
        oapp_mod.create_app({"subnets": ["192.168.50.0/24"], "hostname": "sky.test"}, facility, clock=clock)
    with pytest.raises((ValueError, RuntimeError)):
        oapp_mod.create_app(dict(OUTREACH_SETTINGS, plain_http=True), facility, clock=clock)


@pytest.mark.requirement("TC-WCON-1300")
@pytest.mark.priority("MVP")
def test_tc_wcon_1300_be_designed_for_a_phone_held():
    """WCON-1300: The outreach page shall be designed for a phone held by a visitor: usable on any current browser, dark and dim by default, with a red-light toggle, and nothing to install."""
    _pending("TC-WCON-1300", "webconnect.outreach_app")


@pytest.mark.requirement("TC-WCON-1310")
@pytest.mark.priority("MVP")
def test_tc_wcon_1310_confine_outreach_enrolment_and_guest_requests(facility, clock):
    """WCON-1310: The system shall confine outreach enrolment and guest requests to source addresses inside the outreach subnet(s), checking the source on the outreach listener as well as in the facility, and shall refuse everything else without …"""
    pytest.importorskip("flask")
    oapp = outreach_app_factory(facility, clock)
    outside = anon_browser(oapp, host="sky.test", addr="10.9.9.9")
    assert outside.post("/outreach/enrol", json={"event": "ev1", "secret": "s3cret"}).status_code in (403, 404)
    assert outside.get("/outreach").status_code in (403, 404)
    assert facility.enrol_calls == [], "a source outside the outreach subnet must never reach the facility"
    inside = anon_browser(oapp, host="sky.test", addr="192.168.50.20")
    assert inside.post("/outreach/enrol", json={"event": "ev1", "secret": "s3cret"}).status_code in (200, 204)
    assert facility.enrol_calls[-1][2] == "192.168.50.20", "the visitor's address must be asserted to the facility"


@pytest.mark.requirement("TC-WCON-1320")
@pytest.mark.priority("MVP")
def test_tc_wcon_1320_provide_and_persist_in_galileo_s():
    """WCON-1320: The system shall provide, and persist in Galileo's database (PLUG-150), these browser-outreach options: the outreach listener address and port, the outreach hostname, the certificate source (its private key held as a secret, …"""
    cfg_mod = pytest.importorskip("webconnect.config")
    cfg = cfg_mod.WebConnectConfig.from_dict({"outreach_port": 0, "outreach_hostname": "sky.test", "outreach_key": "-----BEGIN PRIVATE KEY-----abc"})
    assert 1 <= cfg.outreach_port <= 65535
    assert "BEGIN PRIVATE KEY" not in repr(cfg) and "BEGIN PRIVATE KEY" not in str(cfg), "the key is a secret and must never be logged"


@pytest.mark.requirement("TC-WCON-1330")
@pytest.mark.priority("P2")
def test_tc_wcon_1330_contribute_to_the_facility_s_aggregate():
    """WCON-1330: The system shall contribute to the facility's aggregate audit the number of browser guests per Pier, and shall retain no personal data about visitors: a guest is a random token and a source address held only for the event's …"""
    _pending("TC-WCON-1330", "webconnect.outreach")

