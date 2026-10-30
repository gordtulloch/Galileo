# WebConnect Plugin — SDD (Software Design Description)

| | |
|---|---|
| **Project** | Galileo — WebConnect Plugin |
| **Document** | SDD (Software Design Description), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-29 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md) |
| **Downstream document** | RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SDD](../../SDD.md) |
| **Sibling designs** | [MobileConnect SDD](../mobileconnect/SDD.md) (the pipeline, state hub and outreach surface this design reuses), [NodeConnect](../nodeconnect/PSD.md) (Connect Link) |

---

## 1. Introduction

### 1.1 Purpose

This SDD describes how the `webconnect` package satisfies the requirements in [its SRS](SRS.md): how a browser request becomes a call on Galileo's domain services, how state and images flow back by Server-Sent Events, how the browser's security model is enforced, and how a separate, minimal listener serves outreach visitors.

### 1.2 Scope

The `webconnect` package: a plugin component inside Galileo and the Flask applications it supervises, their ADRs, data design and browser-facing API. Everything WebConnect does that **MobileConnect also does** — the request pipeline, confirmation, idempotency, lease broker, state aggregation, load governor, catalogue — is the same design; this document refers to [MobileConnect SDD](../mobileconnect/SDD.md) §3 for it rather than repeating it, and concentrates on what is particular to a browser and to a separate web process. Core architecture is inherited unchanged.

### 1.3 Design status and prerequisites

Like MobileConnect, WebConnect is a thin layer over facilities that do not exist yet (SRS §2.6). It is coded against the same **ports** ([MobileConnect SDD §3.0](../mobileconnect/SDD.md)) — `LinkPort`, `ControlSurfacePort`, `LeasePort`, `OperationEventsPort`, `PreviewPort`, `HoldPort`, `SkyStreamPort`, `PluginContext` — with stubs in the test suite. WebConnect adds three ports of its own (Section 3.0): `LinkClientPort` (the web process's side of Connect Link), `GatewayPort` (the shared pipeline) and `OutreachFacilityPort` (L9). `RelayPort` is *defined* here (Section 3.9) and consumed by MobileConnect.

### 1.4 References

[PSD](PSD.md), [SRS](SRS.md); [MobileConnect SDD](../mobileconnect/SDD.md); [Galileo Core SDD](../../SDD.md) §2.3 (concurrency), §4.20 (`galileo.plugins`), §6.3 (plugin API surface); [NodeConnect PSD](../nodeconnect/PSD.md) §6.2.

---

## 2. Design Considerations

### 2.1 Two Halves Joined by Connect Link (ADR-WCON-001)

**Decision:** the plugin is two cooperating halves. The **Master half** runs inside Galileo (`webconnect.plugin`, `.supervisor`, `.delegate`, `.relay`, `.outreach`, `.config`, `.ui`): it owns every decision — identity, role, lease, confirmation, validation, audit — by running the shared pipeline. The **web half** runs as separate operating-system processes (`webconnect.web`, `webconnect.outreach_app`): Flask applications that present pages, hold browser sessions, enforce browser-side security (CSRF, cookies, headers) and fan out Server-Sent Events. The two halves talk only over Connect Link.

**Rationale:** PSD PC3 and PC6 require that the web workload can never stall Galileo's UI or the session executor, and that a fault in a web server cannot take down imaging. A separate process gives both by construction and lets the web server use a different concurrency model (greenlets) from Galileo's Qt + asyncio. Keeping all *authority* in the Master half means a bug in a Flask view cannot grant a permission: the web half can only ask. The cost is a local hop per request (loopback-class latency over an encrypted link), which is small against LAN and device latency.

### 2.2 The Web Half Is a Backend-for-Frontend With Delegated Identity (ADR-WCON-002)

**Decision:** the browser never holds a Connect Link credential. The operating web application is a *backend-for-frontend*: it holds one **service credential** (its own Connect Link peer, scoped `view`/`control`, never `config.*`), authenticates the browser itself (Section 3.4), and presents every request to the Master half **on behalf of** the approved browser, naming the browser's peer identity. The Master half resolves that identity to a `Principal` (role, expiry, platform) and runs the pipeline against it; the audit log records the browser, not the service. A request naming a browser that is revoked, expired or unknown is refused.

**Rationale:** browsers cannot safely hold a long-lived bearer credential that can move a telescope in script-reachable storage, and Connect Link's certificate-pinning pairing does not apply to a browser. Delegation keeps the browser's secret in an `HttpOnly` cookie it cannot read, and puts the roles the user already manages on the Master (`WCON-110`) in force. **Cost and risk:** a compromised web process could impersonate any approved browser — mitigated by the service credential's narrow scope, the Master half's per-browser revocation, expiry and rate limits, `config.*` being unreachable regardless, and the web process running unprivileged. The alternative (one Connect Link peer per browser, token held server-side) is recorded in Section 8 P3; it needs no new facility but places many tokens in web-process memory. Requires Connect Link support for delegation (SRS DG, O2).

### 2.3 The Request Pipeline Is Shared, Not Copied (ADR-WCON-003)

**Decision:** the pipeline of [MobileConnect SDD ADR-MCON-002](../mobileconnect/SDD.md) — identify, authorise, validate, lease, confirm, idempotency, dispatch, audit — with its `ConfirmationIssuer`, `IdempotencyStore`, `LoadGovernor` and `Catalogue`, is consumed by WebConnect through `GatewayPort`. The implementation is to be a package shared by both plugins (proposed home: alongside the relay, Section 8 P1), so neither plugin depends on the other being installed and neither forks the safety logic. Until it exists WebConnect's tests run against a stub `GatewayPort`.

**Rationale:** the properties the SRS demands — role enforced on the Master, no config route, two-step confirmation, idempotency, the same interlocks as the desktop — are all "nothing bypasses X". One pipeline makes each a single test and guarantees the two front ends behave identically (PSD R2). Copying it into two plugins would let them drift in exactly the place where drift is a safety defect.

### 2.4 Server-Sent Events, With a Server That Makes Idle Streams Cheap (ADR-WCON-004)

**Decision:** live state is pushed to the page by Server-Sent Events (PSD D1) — `EventSource`, `Last-Event-ID` resumption, one stream per browser tab, the Master's stream multiplexed per browser *session* upstream. The WSGI server is provisionally **gevent's `pywsgi`**, run as a separate process with gevent's monkey-patching confined to it; the fallback is **Cheroot** (threaded). The choice is confirmed by a spike on a Raspberry Pi 5 (Section 8 P2) before MVP; any choice must run on Windows, macOS, Linux and Pi OS, support TLS natively, and sustain at least 50 idle SSE connections within the performance budget.

**Rationale:** Flask is WSGI, so each open SSE stream pins a worker; with threads that is a thread per viewer. Streams are mostly idle, which greenlets make nearly free, and gevent ships wheels for all target platforms. Waitress is rejected (no TLS, which PC4 requires); Gunicorn is rejected (not on Windows); an ASGI server with a WSGI adapter was considered and rejected as adding a layer for no gain here. Because the web process is separate from Galileo (ADR-WCON-001), gevent's patching cannot affect the Qt/asyncio process.

### 2.5 Server-Rendered Pages, Light JavaScript, Tablet-First (ADR-WCON-005)

**Decision:** pages are Jinja2 templates (autoescape on) with small, framework-free ES modules under `static/`, served by the web process. There is **no build step** for the operating screens. Session and schedule authoring (`WCON-500`, `510`), the only screen warranted a framework (PSD D2, R4), is a separate bundle built at release time into `static/authoring/` and shipped in the ZIP; it is loaded on that screen only and subject to the same CSP. The sky view is a `<canvas>` module fed by the sky-streaming service.

**Rationale:** a template-and-modules approach keeps the Pi-class cost low, makes the strict CSP (no inline script, no third-party origin) easy to hold, and avoids shipping a toolchain with the plugin. Confining the framework to authoring limits its blast radius and lets authoring slip behind the operating screens without blocking MVP.

### 2.6 Browser Outreach Is a Separate Process on a Separate Listener (ADR-WCON-006)

**Decision:** browser outreach is served by `webconnect.outreach_app`, a second, tiny Flask application with its own process, bound to the **outreach network address**, started when a browser-enabled event opens and stopped when it ends. It contains **no code from the operating application** — no template, route or session machinery — and has its own service credential with a single scope (`outreach.relay`) valid only for the facility's guest operations. The operating application additionally refuses any source in the outreach subnet (defence in depth, `WCON-1220`).

**Rationale:** outreach is the one door open to people the owner has not approved. Making it a different process, listener, credential and code base means there is no route to mistake, no shared middleware to mis-order and nothing to reach if it is compromised. A separate listener is also what lets it exist only for the duration of an event.

### 2.7 The Secret Travels in the URL Fragment (ADR-WCON-007)

**Decision:** the web QR code encodes `https://<host>:<port>/outreach#e=<event>&s=<secret>`. The outreach page's script reads `location.hash`, immediately removes it with `history.replaceState`, and exchanges it for a guest cookie by a `POST` to `/outreach/enrol`. The access log of the outreach listener is configured to omit cookies and query strings.

**Rationale:** a fragment is never sent to a server, so the secret appears in no access log, intermediary log or `Referer` header — the usual ways a QR-borne secret leaks (PSD R9). The secret is only useful on the outreach subnet during an event anyway; the fragment removes the remaining casual exposure.

### 2.8 Guest Images Are Fetched, Not Streamed Inline (ADR-WCON-008)

**Decision:** the outreach SSE stream carries small `image` events — Pier, sequence number, capture time, and a URL `/outreach/img/<pier>/<seq>` — and the page sets an `<img>` source to that URL. The image bytes are the facility's metadata-free guest previews, held per Pier in a bounded in-memory ring in the outreach process, and served `Cache-Control: no-store`.

**Rationale:** SSE is text-only; inlining a JPEG as Base64 costs a third more and bloats every event. A fetched image is cacheable by the browser's decoder, can be served from one shared in-memory copy to all visitors (so a crowd costs the Master one render per frame, not one per visitor), and keeps the event channel tiny.

---

## 3. Module / Component Design

### 3.0 Ports

`LinkPort`, `ControlSurfacePort`, `LeasePort`, `OperationEventsPort`, `PreviewPort`, `HoldPort`, `SkyStreamPort` and `PluginContext` are as in [MobileConnect SDD §3.0](../mobileconnect/SDD.md). WebConnect adds:

| Port | Provided by | Operations used |
|---|---|---|
| `GatewayPort` | shared pipeline package (Section 8 P1) | `handle(request, principal) → Response`; `confirm`, `idempotency` and `governor` are inside it; `principal_for(browser_peer)` |
| `LinkClientPort` | Connect Link client library, used by the **web half** | `call(route, body, on_behalf_of)`; `open_stream(topic, on_behalf_of, last_id)`; `handshake()`; present the service credential; verify the Master's pinned certificate |
| `OutreachFacilityPort` | Connect Link outreach facility (L9) | register surface `browser`; `enrol(event, secret, asserted_source)`; `guest_stream(token, pier)`; `offered_piers(token)`; `latest_image(pier)`; `event_state()`; caps and audit |
| `RelayPort` | **defined by this plugin (Section 3.9)** | `piers()`, `call(node, request, principal)`, `events(node)`, `preview(node, ref)`, `reachability(node)` |

### 3.1 `webconnect.plugin` — Plugin shell and lifecycle

- **`WebConnectPlugin`** (`PluginBase`): `panel_level = "top"`, `panel_label = "WebConnect"`; supplies its page and Options page. `activate` checks the node's role with `LinkPort` — on a spoke it registers nothing and shows that WebConnect belongs on the Master (`WCON-020`) — then builds the Master-half object graph, registers its delegated routes with Connect Link, and asks the `Supervisor` to start the operating web application.
- `on_enabled_changed(False)`: close any outreach event surface first, then stop the supervisor (which stops the web processes and closes their listeners), then end browser sessions' upstream streams, unregister routes, join workers. Approved browsers and options stay in the database, so re-enabling needs no re-pairing (`WCON-040`).
- **Isolation and threading:** all Master-half network handling is on the asyncio loop bridged by `qasync` (core SDD §2.3); blocking calls and rendering go to the executors the desktop uses; nothing runs on the Qt UI thread except widgets (`WCON-080`). A handler exception becomes a typed error and a log line, never an exception into the session executor.
- **Satisfies:** `WCON-010`, `020`, `040`, `080`.

### 3.2 `webconnect.supervisor` — Process supervision, TLS and hand-off

- **`Supervisor`** starts the operating web application (`python -I -m webconnect.web`) and, during a browser-enabled event, the outreach application (`python -I -m webconnect.outreach_app`), under the plugin's own interpreter. Each runs as an unprivileged child with no inherited handles other than its control pipe.
- **Configuration hand-off:** the child's settings (bind address, port, timeouts, certificate paths, offered options) and its **service credential** are written to its standard input as a one-shot message and never appear on the command line, in the environment or in a file; nothing about the web half is configured from files (`WCON-910`).
- **Liveness:** a heartbeat over the control pipe every few seconds; a missing heartbeat or an exit restarts the child with exponential back-off (cap 60 s), logs, and raises an alert to the plugin page after repeated failures (`WCON-030`). A crash of a child never propagates; Galileo does not wait on it. An optional loopback-only `/healthz` is provided for external monitors, off by default (`WCON-070`).
- **TLS material:** `CertificateStore` generates a self-signed certificate for the Master on first use (using the `cryptography` package), keeps the key in the core secret store, and records the certificate's fingerprint in the web process's Connect Link pairing; a user-supplied certificate and key replace it, with the key again held as a secret. The outreach certificate is separate and owner-supplied only; an event will not open without it (`WCON-070`, `1290`).
- **Binding:** the bind address defaults to the Master's LAN interface chosen via `galileo.platform`, not `0.0.0.0` (`WCON-060`); the outreach application binds only to the outreach address.
- **Stop:** `Supervisor.stop` sends a graceful shutdown on the pipe, waits briefly, then terminates the process tree, so disabling the plugin leaves no listener and no process (PSD Section 11).
- **Satisfies:** `WCON-030`, `040`, `060`, `070`, `080`, `1210` (lifecycle), `1290`.

### 3.3 `webconnect.delegate` — Delegated gateway and browser registry (Master half)

- **Routes.** The Master half registers `/webconnect/v1/...` with Connect Link (L5) for the service credential: `ops`, `lease`, `catalogue`, `piers`, `stream`, `preview`, `tiles`, `fits`, `sky`, `hold`, `alerts`, `pair/*`. Each carries the named browser; each is handed to `GatewayPort` with the browser's `Principal`. No route registered here changes a role or any configuration.
- **`BrowserRegistry`** wraps Connect Link's peer list with the plugin's metadata, kept in the peer's metadata record (so it is deleted with the peer): `role` (`viewer` by default), `expiry`, `browser`, `platform`, `user_agent_summary`, `first_seen`. Role promotion is a method callable only from the Master's UI controller, never from a route (`WCON-110`). `revoke(peer)` invalidates the device credential, ends the browser's upstream streams, releases its leases, cancels its holds and writes an audit record; expiry is a timer in the registry (`WCON-170`).
- **Pairing flow.** `pair/request` (the only unauthenticated Master-half route, callable only by the service credential) creates a pending request with a short confirmation code that the Master's UI shows beside the requester's name and browser; approval issues a device credential which is returned once, to the web half, for placement in the browser's cookie (Section 3.4). Pending requests expire after a few minutes (`WCON-100`).
- **Scopes.** A browser principal never has `config.*`; the catalogue registry rejects a *config*-class entry at startup; every refusal carries a reason and is audited (`WCON-120`, `130`, `570`, `580`, `700`, `750`).
- **Lease, confirmation, idempotency, emergency** are the pipeline's, unchanged ([MobileConnect SDD §3.4–3.5, §3.13](../mobileconnect/SDD.md)); the Gateway's `emergency` class is lease-free, Operator-only and runs in a single request (`WCON-140`, `150`, `160`, `180`, `710`, `740`, `760`).
- **Audit** is written by the pipeline through the Connect Link audit log with the plugin record type and the *browser* as actor; a spoke operation is also recorded on the owning node via the relay (`WCON-190`, `240`).
- **Satisfies:** `WCON-090`, `100`, `110`, `120`, `130`, `140`, `150`, `160`, `170`, `180`, `190`, `360`, `570`, `580`, `700`, `710`, `740`, `750`, `760`.

### 3.4 `webconnect.web.session` — Device credential, sessions and CSRF (web half)

- **Device credential.** On approval the web half sets `__Host-wc_device` — an opaque random token, `HttpOnly; Secure; SameSite=Strict; Path=/`, with the browser's expiry — and the Master half stores only its hash. The credential proves "this is the approved browser"; it grants nothing by itself.
- **Sign-in and session.** `POST /signin` presents the device credential; the web half asks the Master half to validate it, then creates a server-side session (`__Host-wc_session`, random 256-bit, regenerated at every sign-in, role change and sign-out) holding the browser's peer id, a CSRF secret, the upstream stream handle and the last-seen time. Sessions live in the web process's memory; a web-process restart simply requires the one-click sign-in again. Idle and absolute timeouts come from the options (`WCON-1040`, SRS O3). Sign-out closes the stream and tells the Master half to release the browser's leases (`WCON-760`).
- **CSRF.** A per-session secret yields a token embedded in each page (a `<meta>` element read by script, not inline script) and sent in an `X-CSRF-Token` header; comparison is constant-time. Every state-changing request is also checked against `Origin` and `Sec-Fetch-Site: same-origin` (`WCON-1000`).
- **Cookies** are host-bound and strict (`WCON-1010`).
- **Satisfies:** `WCON-100` (browser side), `170` (browser side), `830`, `1010`, `1040`.

### 3.5 `webconnect.web.security` — Headers, host checks, rate limits, route audit (web half)

- **`SecurityMiddleware`** (the outermost layer, so no view can omit it): rejects a `Host` or `Origin` not in the configured set (DNS-rebinding defence, `WCON-1060`); sets `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `Cache-Control: no-store` on state and images (`WCON-1020`). Templates contain no inline script, handler or style; a test greps the rendered pages (`WCON-800`).
- **`RateLimiter`**: in-memory token buckets per source and per session, with escalating delay on repeated sign-in or pairing failure (`WCON-1030`, `770`); it complements, and does not replace, the Master half's per-client governor.
- **Route registry.** Every route is added through `web.route(...)`, which records its authentication class (`session`, `public`, `service`) and role requirement; a startup check refuses to serve if a route lacks either, and a test enumerates the Flask URL map and fails on any route that is neither authenticated nor on the single explicit public list: the pairing page, sign-in, static assets for those, and the loopback health check (`WCON-1050`).
- **Outreach separation.** The operating app refuses any request whose source lies in a configured outreach subnet (`WCON-1220`).
- **Review.** `docs/security-review.md` in the product repository records each release's review against the checklist of `WCON-1070`.
- **Satisfies:** `WCON-770`, `800`, `1000`, `1020`, `1030`, `1050`, `1060`, `1070`, `1220`.

### 3.6 `webconnect.web.api` — Browser-facing API (web half)

A thin translation layer: each browser route validates the session, role and CSRF token, maps to a `LinkClientPort.call` for the Master half, and renders or relays the typed result. It contains **no per-area code**: areas in SRS §3.5 are satisfied by their Control Surface entries existing in core and being reachable through the catalogue ([MobileConnect SDD §3.7](../mobileconnect/SDD.md)). The browser-facing routes are listed in Section 5.2.

- **Operations** use `POST /api/v1/pier/{pier}/ops/{name}` with an `Idempotency-Key` header (generated by the page) and an optional `X-Confirm-Token`; a `confirmation_required` result carries the token the page presents in its dialog and returns on the second request (`WCON-180`, `740`).
- **Previews and tiles** are streamed through from the Master half (which obtained them from the owning node) with the governor's *previews* class; the web half keeps a small bounded LRU for repeated requests (`WCON-600`, `610`, `630`); the FITS route exists only for Operator sessions, reports the size first via `HEAD`, and streams to a download with `Content-Disposition: attachment` (`WCON-620`).
- **Sky data** routes proxy the sky-streaming service (`WCON-650`).
- **Errors** are the typed set `{error: refused|invalid|unavailable|busy|unreachable|confirmation_required, reason, detail}`; an expected condition is never an HTTP 500 (`WCON-580`, `750`).
- **Satisfies:** `WCON-080` (preview cache), `180` (two-step flow), `400`–`560`, `590` (route reachability), `600`, `610`, `620`, `630`, `650`, `740`, `750`.

### 3.7 `webconnect.web.events` — Server-Sent Events hub (web half)

- **Upstream:** one stream per signed-in *session* from the Master half (`LinkClientPort.open_stream`), carrying a snapshot and then deltas with sequence numbers, filtered on the Master by what that browser may see (exposed Piers, role) as in [MobileConnect SDD §3.8](../mobileconnect/SDD.md) (`WCON-300`, `320`, `330`, `360`).
- **Downstream:** each open tab is an `EventSource` on `/events`; the hub fans one upstream out to the session's tabs. Frames use the SSE `id:` field for the sequence number, so a reconnecting `EventSource` sends `Last-Event-ID` and the hub resumes from its bounded replay ring, or sends a fresh snapshot if the gap is too large (`WCON-350`). A comment heartbeat every 15 s keeps proxies from closing idle streams and lets the page detect a dead connection (`WCON-780`).
- **Back-pressure:** a bounded queue per tab with coalescing of state deltas for the same key; a tab that cannot keep up is closed with a `closing(slow)` event and reconnects with a snapshot; the upstream is never blocked by a slow tab. Reliable events (alerts, operation start/progress/finish) are never coalesced (`WCON-330`, `340`).
- **Stale state:** the page marks state stale when no frame or heartbeat has arrived within two heartbeat intervals, and disables Pier-affecting operations other than the Emergency operations until the stream recovers (`WCON-780`).
- **Closure:** closing the last tab of a session releases the session's leases after the idle grace period (`WCON-140`, `760`).
- **Satisfies:** `WCON-300`, `310`, `320`, `330`, `340`, `350`, `360`, `760`, `780`.

### 3.8 `webconnect.web.hold` — Held motion (web half)

- A manual slew, jog or focuser move starts with `POST /api/v1/hold/start` (an ordinary operation through the pipeline) and continues only while the page POSTs `/api/v1/hold/{id}/beat` every **250 ms** from a pressed control; the Master half forwards each beat to `HoldPort.beat`, and the core deadman stops the motion if none arrives within **600 ms** (`WCON-730`).
- **Page rules** (`static/hold.js`): a hold begins on `pointerdown` (or key down) and ends on `pointerup`, `pointercancel`, `keyup`, `blur`, `visibilitychange` (hidden), `pagehide` and `beforeunload`, each sending an explicit stop where the browser allows (`navigator.sendBeacon`); a hold never begins from a `click`.
- **Web-half watchdog:** the web process itself stops a hold if the browser's beats lapse for 600 ms or the session's event stream closes, in addition to the core deadman; the Master half stops it on lease loss, revocation or plugin disable.
- **Disconnects:** imaging continues untouched; the only thing a lost browser ever stops is a hold (`WCON-720`).
- **Satisfies:** `WCON-720`, `730`.

### 3.9 `webconnect.relay` — The Master relay (defines `RelayPort`)

This is the relay both plugins consume (MobileConnect SDD §3.9 is its client). It is specified here and is to be packaged for sharing (Section 8 P1) so that neither plugin imports the other.

- **`RelayPort`** merges the Master's Piers with each reachable spoke's, as `PierRef(node, pier)`, into one list (`WCON-200`); `call(node, request, principal)` forwards a request over Connect Link with the originating principal's identity so the spoke can audit it; `events(node)` feeds the spoke's state into the Master's hub; `preview(node, ref)` returns bytes rendered on the owner (`WCON-210`).
- **Grant model:** a spoke appears with `access = control | view | none` according to the opt-in grant it gave the Master when it paired; `view` shows its Piers view-only, `none` omits it, and the browser is told which (`WCON-220`). The grant is a pairing-time prompt on the spoke ("allow the Master to operate this node?"), limited to `control`/`view`, revocable on the spoke at any time.
- **Lease on the spoke:** the lease is acquired through the relay on the spoke itself; the Master keeps no copy of truth, so the spoke's desktop, MobileConnect and WebConnect contend through one lease (`WCON-230`).
- **Reachability:** `reachability()` reports `reachable` or `unreachable(since=…)`; unreachable Piers are shown as such, operations to them are refused with that reason, and the relay re-attaches without re-pairing when the spoke returns; the spoke's imaging is never affected (`WCON-240`). A spoke operation is audited on the Master and on the owning node.
- **Independence:** the interface exposes nothing specific to a front end (`WCON-250`); a contract test run against both plugins' stubs confirms it.
- **Satisfies:** `WCON-200`, `210`, `220`, `230`, `240`, `250`.

### 3.10 `webconnect.web.ui` — Templates, static modules and screens (web half)

- **Layout:** `templates/base.html` (CSP-safe, theme-aware, the Emergency bar and the role/lease/connection/age strip are in the base so they appear on every page — `WCON-710`, `840`, `850`); one template and one ES module per operational area of SRS §3.5, each rendering from the catalogue so an unavailable area is hidden or shown as unavailable (`WCON-820`); a generic form view renders a plugin-registered surface (`WCON-560`).
- **Responsive, tablet-first:** CSS grid layouts with three breakpoints (large: sky + image + session list side by side; medium; phone), touch targets sized for gloves, and keyboard shortcuts for desktop users (`WCON-810`).
- **Night theme:** a `--red-only` palette applied before first paint (a dedicated `<link>` selected server-side from a cookie so there is no white flash), `color-scheme` set for form controls and scrollbars, a red favicon, and no pure-white loading state; the choice is a browser-side UI preference (`WCON-860`).
- **Sky view:** `static/sky.js` renders a `<canvas>` from the data of `/api/v1/sky/*` (region, limiting magnitude, level of detail, delta frames, ephemeris), including the mount position, field of view and horizon; it carries no catalog and computes no ephemeris, and shows "reduced" or "unavailable" from the handshake without affecting other pages (`WCON-650`).
- **Image viewer:** server-rendered previews with stretch and histogram controls, tile-based pan/zoom, and two-frame blink and side-by-side (`WCON-430`, `640`).
- **Authoring:** a separate bundle under `static/authoring/` for session and schedule editing over the same Sessions model (`WCON-500`, `510`); `.gses` import via file chooser, export as a download.
- **Accessibility and browsers:** semantic landmarks, focus management in dialogs, `aria-live` regions for alerts and operation results, contrast-checked red theme; a feature-detection script shows a plain message in an unsupported browser instead of a broken page; automated tests run on the browser matrix (`WCON-870`, `880`).
- **Help and About:** per-screen help pages served from the plugin's help Markdown, and an About view (`WCON-890`).
- **Satisfies:** `WCON-400`–`560` (screens), `640`, `650`, `710`, `750`, `780`, `800`, `810`, `820`, `830`, `840`, `850`, `860`, `870`, `880`, `890`.

### 3.11 `webconnect.outreach` — The browser surface of core outreach (Master half)

The outreach **event** — `OutreachManager`, `QrBuilder`, `Enrolment`, `SubnetGuard`, guest tokens, the three-operation allowlist, `LiveImageFeed`, guest-preview rendering, caps and rate limits, aggregate audit — is hosted in core by Connect Link's outreach facility (L9) and shared with MobileConnect ([MobileConnect SDD §3.14](../mobileconnect/SDD.md)). WebConnect contributes only the **browser surface**:

| Component | Responsibility | Requirements |
|---|---|---|
| `BrowserOutreachSurface` | Registers with the facility as the surface named `browser`; declares whether the owner offered the event to browsers (when not, the outreach application is not started); supplies the **web QR payload** (`https://<host>:<port>/outreach#e=…&s=…`, ADR-WCON-007) and the short text address to the event display; starts and stops the outreach application through the `Supervisor` with the event; refuses to open without a subnet and a certificate | `1200`, `1210` (lifecycle), `1230`, `1290`, `1310` |
| `OutreachCredential` | Issues the outreach application a service credential scoped `outreach.relay`, valid only while the event is open and revoked at its end | `1250`, `1310` |
| `OutreachFeed` | Receives the facility's guest-sized, metadata-free live images and forwards them to the outreach application, which holds the latest per Pier | `1260`, `1270` |
| `OutreachConfig` | The browser-outreach options of `WCON-1320` | `1320` |

Failure modes stay fail-closed in the facility (no subnet, event does not open; secret store lost, event closes); the surface adds no listener of its own — the listener is the outreach application's. The facility must accept the visitor's address asserted by a registered surface, since the facility does not see the visitor's connection (Section 8 P5, SRS O8).

- **Satisfies:** `WCON-1200`, `1230`, `1270`, `1290`, `1310`, `1320`, `1330` (via the facility's aggregate audit).

### 3.12 `webconnect.outreach_app` — The guest web application

A separate Flask application, started only for a browser-enabled event (ADR-WCON-006). Its entire surface:

| Route | Purpose | Requirements |
|---|---|---|
| `GET /outreach` | The outreach page (one template, one script) | `1240`, `1300` |
| `GET /outreach/static/*` | Its own CSS/JS/icons — no third-party resource | `1280` |
| `POST /outreach/enrol` | Exchange `{event, secret}` for the guest cookie; checks `Origin`, rate-limits, asserts the visitor's source address to the facility | `1240`, `1280`, `1310` |
| `GET /outreach/piers` | Offered Piers (display names only) | `1250` |
| `GET /outreach/stream?pier=` | SSE: `image`, `unavailable`, `ended`; opening a stream for another Pier is the switch; the latest image is sent immediately | `1250`, `1260` |
| `GET /outreach/img/{pier}/{seq}` | The guest-preview bytes, `no-store` | `1260`, `1270` |

Everything else returns a bare 404 and increments a counter. The allowlist is the route table; a test asserts it has exactly these entries, and that a guest cookie is refused on any route outside it (`WCON-1250`).

- **Source confinement:** every request's source address is checked against the outreach subnet(s) before any handler, in addition to the facility's own check (`WCON-1310`); the listener is bound to the outreach address so it is unreachable elsewhere.
- **Guest session:** the cookie is `__Host-wc_guest`, `HttpOnly; Secure; SameSite=Strict`, expiring with the event; no other cookie is set; the page script reads the fragment, posts to enrol, calls `history.replaceState`, and discards the secret (`WCON-1240`).
- **Delivery:** one shared in-memory copy of each Pier's latest image and a short ring of recent sequence numbers; each visitor's SSE stream receives a small event and the page loads the image URL (ADR-WCON-008). A joining or switching visitor is sent the latest image's event at once, with its age (`WCON-1260`). The concurrent-guest cap is enforced by refusing new enrolments with a readable reason (`WCON-1280`); outreach traffic is lowest priority behind the session and every paired client.
- **Hardening:** CSP `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on images, no service worker; the access log omits cookies and query strings (`WCON-1280`). TLS uses the owner-supplied certificate and refuses to start without one (`WCON-1290`).
- **End of event:** the facility signals the end; the app sends `ended` to every stream, invalidates every cookie, and exits; plugin disable or a Master restart does the same (`WCON-1240`).
- **Phone-first page:** one dim, dark layout, a Pier switcher, the image with its age, and a red-light toggle; works without scripts beyond its single module; no tracking of any kind (`WCON-1300`).
- **Satisfies:** `WCON-1210`, `1240`, `1250`, `1260`, `1280`, `1290`, `1300`, `1310`.

### 3.13 `webconnect.config` and `webconnect.ui` — Options, plugin page, help

- **`WebConnectConfig`**: plain data with `from_dict` clamping every value (bind address and port, start-with-Galileo, certificate source, session idle/absolute timeouts, lease idle timeout, audit retention, preview quality/size and cache bytes, Pier exposure list), stored under namespace `plugin.WebConnect` via `PluginContext.settings()` (`PLUG-150`). Per-browser role and expiry live in the peer metadata (Section 3.3). Keys and private material (TLS keys, the outreach key) are stored as secrets and never logged or audited (`WCON-910`, `1320`).
- **`WebConnectPage`** (top-level section): the address to open, approved and signed-in browsers (name, browser, platform, role, leases held, last seen; promote, revoke), pending approvals with their confirmation codes, recent alerts, a filterable audit view, and a short Outreach panel (event open, browser guests, offered to browsers) linking to the event controls on Connect Link's Outreach page in core (`WCON-050`, `900`).
- **`WebConnectOptions`** (under Options, `PLUG-170`): the settings above; nothing applies until **Save**; changing the bind address, port or certificate restarts the web process.
- **Help:** `webconnect/help/plugin.WebConnectPlugin.md`, one section per control; the help audit runs in the test suite (`WCON-940`).
- **Satisfies:** `WCON-050`, `190` (view), `630`, `900`, `910`, `940`, `1320`.

### 3.14 `webconnect.wire` and the parity check

- **Browser-facing API:** the routes of Section 5.2 are defined with pydantic models; `wire/openapi.yaml` and `wire/events.schema.json` are generated from them and a test fails if the committed files differ from the generated ones (`WCON-920`). A breaking change is a new `/v2`.
- **Handshake:** at start-up and on reconnection the web half calls `LinkClientPort.handshake()`, compares Galileo, plugin-API and protocol versions, and shows a message naming the mismatch rather than operating (`WCON-930`); the result, with the available `areas`, drives the page (`WCON-400`).
- **Reference client:** because the web half uses only the documented Connect Link and `/webconnect/v1` wire API, its integration suite doubles as a conformance test of that API for third-party clients (`WCON-090`, `920`).
- **Parity check:** `tests/test_parity.py` loads the Control Surface catalogue (the stub catalogue in unit runs, the real one in integration), the operations MobileConnect exposes, and the routes/screens of the web UI, and fails if an operation is reachable in one and neither reachable nor listed with a reason in the other (`WCON-590`).
- **Satisfies:** `WCON-090`, `400`, `590`, `920`, `930`.

---

## 4. Data Design

| Data | Format | Storage | Lifetime |
|---|---|---|---|
| Plugin options (bind address/port, start-with-Galileo, certificate source, session timeouts, lease idle timeout, audit retention, preview limits and cache bytes, Pier exposure, outreach listener options) | JSON-valued keys | `app_settings`, namespace `plugin.WebConnect` (`PLUG-150`) | Persistent |
| TLS private keys (operating and outreach), service credentials | Secret | Core secret store | Persistent; never logged or audited |
| Approved browsers: peer record, device-credential hash, certificate pin for the web process | Connect Link peer records | Connect Link | Persistent; deleted on revoke |
| Per-browser `role`, `expiry`, `browser`, `platform`, `user_agent_summary` | Peer metadata | Connect Link peer record | Same as the peer |
| Audit records | Connect Link audit log (plugin record type) | Shared database via Connect Link | Per retention option |
| Browser sessions, CSRF secrets, SSE replay rings, rate-limit buckets, preview cache, hold registry | Python objects | **Web process memory** | Process |
| Confirmation tokens, idempotency results, lease timers | Python objects | Master process memory (pipeline) | Process |
| Outreach event secret (hash), guest tokens, latest guest images | Python objects | **Memory only** (the facility; the outreach process) | Event |
| Wire schemas | `openapi.yaml`, `events.schema.json` | Package files, generated | Release |
| Browser-side | Session/device/guest cookies; UI preferences (theme, layout) in `localStorage` | Browser | Per cookie/preference |

The plugin adds **no table and no migration**, reusing Connect Link's audit and peer stores as MobileConnect does (ADR-MCON-008); if they prove insufficient the fallback is a core-owned table, never a plugin-private file (PSD PC2). The plugin writes no configuration file; the web processes receive their settings over a pipe (Section 3.2).

---

## 5. Interface Design

### 5.1 Plugin boundary

Master half: depends only on `galileo.plugins` (`PluginBase`, `PluginContext`), the ports of Section 3.0, `galileo.bus` (read) and `galileo.dashboard_timeline`'s record type. Web half: depends on **no Galileo module at all** — only its Connect Link client library and the published wire schemas — and is started with `-I` (isolated mode) so it loads nothing from the working directory. No import of `galileo.adapters.*` or UI internals anywhere. External Python dependencies (listed in `THIRD_PARTY_NOTICES.md`): Flask, Jinja2, Werkzeug, gevent (or Cheroot), `cryptography`, `segno` (QR, Master half), `pydantic` (already core).

### 5.2 Browser-facing API (`/webconnect/v1`, operating application)

Every route needs a session cookie, a role check and, where state-changing, a CSRF token, unless marked public. Methods other than GET/HEAD need `X-CSRF-Token`.

| Method & path | Auth | Purpose | Requirements |
|---|---|---|---|
| `GET /` | session | The application shell | `800`, `820` |
| `GET /pair`, `POST /pair/request`, `GET /pair/wait` (SSE) | public, rate-limited | Pairing page; request; wait for approval | `100`, `830`, `1030` |
| `POST /signin`, `DELETE /session` | device cookie / session | Sign in; sign out | `1010`, `1040`, `760` |
| `GET /api/v1/capabilities`, `/catalogue`, `/piers` | session | Handshake extension, operations by area, Piers incl. spoke Piers with access/reachability | `400`, `200`, `220`, `240`, `930` |
| `POST /api/v1/pier/{pier}/ops/{name}` | session (Operator for non-read) | Invoke an operation (`Idempotency-Key`, optional `X-Confirm-Token`) | `410`–`580`, `740`, `180` |
| `POST /api/v1/pier/{pier}/lease`, `DELETE …/lease` | session (Operator) | Acquire / release; take with confirm token | `140`, `150` |
| `POST /api/v1/hold/start`, `POST /api/v1/hold/{id}/beat`, `POST /api/v1/hold/{id}/stop` | session (Operator) | Held motion | `730` |
| `GET /events` (SSE) | session | Snapshot, deltas, operation events, alerts; `Last-Event-ID` resumes | `300`–`360`, `780` |
| `GET /api/v1/alerts` | session | Recent alerts | `340`, `550` |
| `GET /api/v1/pier/{pier}/preview` | session | Preview with size/quality/stretch | `600`, `630` |
| `GET /api/v1/frame/{id}/tiles/{z}/{x}/{y}` | session | Pyramid tile | `610`, `640` |
| `GET /api/v1/frame/{id}/fits` (also `HEAD`) | session (Operator) | Full FITS, size first | `620` |
| `GET /api/v1/sky/catalog`, `/ephemeris`, `/site` | session | Sky streaming | `650` |
| `GET /static/*`, `GET /healthz` (loopback) | public | Assets; health check | `070`, `1050` |

There is no browser route for the audit log (it is on the Master's UI only) and none that changes a role or configuration. Errors are the typed set of Section 3.6.

### 5.3 Event stream messages (`/events`)

`snapshot`, `delta` (state key, value, seq, as-of), `op.started|progress|finished` (correlation id, request id), `alert`, `lease` (Pier, holder), `access` (spoke access change), `closing(reason)`, with the SSE `id:` field carrying the sequence number. The outreach stream carries `image` (Pier, seq, captured-at, URL), `unavailable(Pier)` and `ended`.

### 5.4 External interfaces added

Two network listeners, both owned by the web half: the **operating listener** (HTTPS, LAN address) while the plugin is enabled, and the **outreach listener** (HTTPS, outreach address) only during a browser-enabled event. The Master half adds no listener; the web half reaches it over Connect Link's encrypted, authenticated transport.

---

## 6. Concurrency, Failure and Security Notes

- **Isolation:** separate processes for the web workload (ADR-WCON-001); one greenlet per stream; a failing browser, web process or visitor cannot stop another, the session executor or the bus (`WCON-030`, `720`).
- **Back-pressure:** bounded per-tab queues with coalescing; a slow tab is closed and resynchronises by snapshot; the Master's bus is never blocked.
- **Disable and shutdown:** close any outreach event first, then the web processes (their listeners close with them), then upstream streams and holds (stop), then unregister routes; no lease is left held.
- **Threat summary:**

| Threat | Defence |
|---|---|
| Cross-site request forgery | CSRF token + `Origin`/`Sec-Fetch-Site` + `SameSite=Strict` cookies (`WCON-1000`, `1010`) |
| Script injection / XSS | Autoescaped templates, strict CSP with no inline script or third-party origin, a test over rendered pages (`WCON-1020`, `800`) |
| DNS rebinding / foreign origin | `Host`/`Origin` allowlist (`WCON-1060`) |
| Session theft or fixation | `HttpOnly` host-bound cookies, regeneration at sign-in/role change/sign-out, idle and absolute timeouts (`WCON-1010`, `1040`) |
| Forgotten route | Route registry that refuses to serve an unclassified route; enumeration test (`WCON-1050`) |
| Brute force on sign-in/pairing | Rate limits with escalating delay (`WCON-1030`) |
| Compromised web process | Narrow service credential, no `config.*` reachable, per-browser revocation and expiry on the Master, unprivileged child, `-I` isolated start (ADR-WCON-002) |
| Browser used by a bystander | Per-browser expiry and revocation (`WCON-170`); a per-device PIN is an open option (SRS O3) |
| Crowd of visitors loads the Master | Guest cap, shared image copy, lowest priority, small previews (`WCON-1280`, ADR-WCON-008) |
| Event secret leaks from a photographed QR | Fragment transport, no logging of the secret, subnet confinement, per-event and re-issuable (`WCON-1230`, `1310`) |
| Operating app reached from the public listener | Separate process, listener and credential; operating app refuses outreach-subnet sources (`WCON-1210`, `1220`) |

- **Not defended:** a visitor device that is simultaneously on a network reaching the observatory's equipment (the owner's isolated outreach network); a person with the physical, unlocked approved browser until it is revoked or expires; an internet-facing deployment, which is out of scope and unsupported (PSD R1).

---

## 7. Requirement-to-Component Map

| Requirements | Component (this SDD) |
|---|---|
| `WCON-010`, `020`, `040`, `080` | 3.1 `plugin` |
| `WCON-030`, `060`, `070` | 3.2 `supervisor` |
| `WCON-050`, `900`, `910`, `940`, `1320` | 3.13 `config`/`ui` |
| `WCON-090`, `100`, `110`, `120`, `130`, `140`, `150`, `160`, `170`, `180`, `190`, `360`, `570`, `580`, `700`, `710`, `740`, `750`, `760` | 3.3 `delegate` (with the shared pipeline) |
| `WCON-830`, `1010`, `1040` | 3.4 `web.session` |
| `WCON-770`, `800`, `1000`, `1020`, `1030`, `1050`, `1060`, `1070` | 3.5 `web.security` |
| `WCON-200`–`250` | 3.9 `relay` |
| `WCON-300`–`350`, `780` | 3.7 `web.events` |
| `WCON-400`–`560`, `600`–`630` | 3.6 `web.api` with 3.10 `web.ui` (screens) |
| `WCON-590`, `920`, `930` | 3.14 `wire`/parity |
| `WCON-640`, `650`, `810`, `820`, `840`, `850`, `860`, `870`, `880`, `890` | 3.10 `web.ui` |
| `WCON-720`, `730` | 3.8 `web.hold` |
| `WCON-1200`, `1230`, `1270`, `1330` | 3.11 `outreach` (facility OF in core) |
| `WCON-1210`, `1240`, `1250`, `1260`, `1280`, `1290`, `1300`, `1310` | 3.12 `outreach_app` (with 3.2 and 3.11) |
| `WCON-1220` | 3.5 `web.security` and 3.12 `outreach_app` |

---

## 8. Open Design Points

| # | Point |
|---|---|
| P1 | **Shared packages.** The request pipeline (ADR-WCON-003) and the relay (3.9) are shared by MobileConnect and WebConnect. Where they live — core, or a package distributed with both plugins — is undecided, as is who owns it. This SDD codes against `GatewayPort` and `RelayPort`; contract tests run against both plugins' stubs. (MobileConnect SDD P3.) |
| P2 | **Server choice and Pi budget (ADR-WCON-004).** gevent `pywsgi` is provisional. A spike on a Raspberry Pi 5 with 50 idle SSE streams, a running session and previews being rendered decides between gevent and Cheroot, and sets the concurrent-viewer limit and the figures for `WCON-080`. |
| P3 | **Delegation vs per-browser peers (ADR-WCON-002).** Delegation needs Connect Link to accept a service peer acting for a named client and to log the client as the actor. If Connect Link will not, the fallback is one Connect Link peer per approved browser with its token held in the web process's memory. The choice affects only `webconnect.delegate` and `LinkClientPort`. |
| P4 | **Held-motion transport.** Keep-alives are small HTTP `POST`s at 4 Hz over a kept-alive connection; if browser Wi-Fi jitter makes the 600 ms deadman trip spuriously, a dedicated WebSocket for holds is the alternative. Timings need measuring on a tablet and a phone over Wi-Fi (MobileConnect SDD P4). |
| P5 | **Asserted source address (SRS O8).** The facility needs to accept the visitor's source address asserted by a registered, credentialed surface; the outreach application checks it as well. To be agreed with the Connect Link outreach design. |
| P6 | **Pairing confirmation code (SRS O5)** is added here for browsers; whether MobileConnect adopts it too is open. |
| P7 | **Session expiry without accounts (SRS O3).** A per-device PIN is the natural strengthening if the one-click sign-in proves too weak; it would live in the device credential check in 3.3/3.4. |
| P8 | **Sky view and authoring front-end effort (SRS O10, PSD R4).** The two heaviest front-end pieces. The design lets both ship after the operating screens without blocking MVP; a server-rendered static sky image is the interim if the canvas view slips. |
| P9 | **Self-signed certificate friction.** Browsers warn on the first visit to a self-signed Master. The design documents installing the certificate or a local CA, and supports a user-supplied certificate; it does not weaken HTTPS to avoid the warning. |

---

## 9. Path to Traceability Matrix

A row per requirement ID in [this plugin's SRS](SRS.md), mapped to the component above (Section 7) and a `TC-WCON-*` test case ID — see [RTM.md](RTM.md).
