# WebConnect Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — WebConnect Plugin (browser control of a Galileo node through a Flask web application) |
| **Document** | PSD (Project Scope Document), v0.3, draft — recast on Astroberry OS (Section 6.5, D11–D12); browser outreach mode added in v0.2 (Section 6.4, D6–D8) |
| **Status** | Draft — for review |
| **Date** | 2026-10-31 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Sibling plugins** | [MobileConnect](../mobileconnect/PSD.md) — defines the operational surface this plugin reuses (its Section 6.4); [NodeConnect](../nodeconnect/PSD.md) — defines the shared Connect Link facility (its Section 6.2) |
| **Deployment counterpart** | [galileo-astroberry PSD](https://github.com/gordtulloch/galileo-astroberry) — layers Galileo and this plugin onto Astroberry OS (packaging, APT repository, service integration); this document owns what WebConnect needs from that layer |
| **Where it is built** | In this repository (documents, core facilities) and [Galileo-Plugins](https://github.com/gordtulloch/Galileo-Plugins) `webconnect/` (plugin, Flask applications, packaging). The separate `Galileo-WebConnect` repository is retired (D12); its v0.1 PSD was a subset of this one |
| **Downstream documents** | [SRS](SRS.md), [SDD](SDD.md), [RTM](RTM.md) — drafted 2026-10-29, for review |

---

## 1. Purpose of This Document

This document defines the scope of the **WebConnect plugin** — a first-party Galileo plugin that lets a user operate a running Galileo node **from any web browser**, through a web application built on **Flask**. It offers the same level of control as [MobileConnect](../mobileconnect/PSD.md) — everything operational, nothing configurational — without installing an app. It follows the same PSD→SRS→SDD→RTM structure as [the core chain](../../PSD.md) and the other plugins' chains, and stays above implementation detail.

The primary deployment is a headless **Astroberry OS** controller, where WebConnect is the way Galileo is operated day to day and is reached from the Astroberry Manager web interface (Section 6.5). The same plugin remains installable on a Master that is not an Astroberry system (the *self-hosted* profile, Section 6.5.4).

## 2. Background and Motivation

The mobile apps cover tablets and phones that the user owns and has set up. A browser covers everything else: a laptop at the kitchen table, a borrowed machine, a Linux desktop, a Chromebook, a kiosk screen in the observatory. It needs nothing installed, so it is also the lowest-friction way to look at a node for the first time.

The operational surface is identical in intent to the mobile one: the node is already configured and running, and the remote user watches and operates it. Defining that surface twice would let the two drift apart. WebConnect therefore **consumes the surface MobileConnect defines** — the Control Surface and the operational scope of MobileConnect §6.4 — rather than redefining it, and differs only in how it is presented and authenticated.

**Astroberry OS.** The project has decided (2026-10-31) to integrate closely with the Astroberry OS distribution and its web interface, Astroberry Manager, rather than have a controller operated through the Galileo desktop client. On a headless Astroberry controller the browser is therefore the primary operating surface, not a convenience, and the desktop client is reached — through Astroberry's browser-based remote desktop — only for what WebConnect deliberately excludes (configuration). That raises the stakes on three things this plugin previously treated as secondary: how it is deployed beside Astroberry's own services; how it shares an address, certificate and web origin with Astroberry Manager; and how a browser is approved when no one is sitting at the Master. Section 6.5 sets these out.

## 3. Vision Statement

> A Galileo user opens a web address on any computer, tablet or phone on the observatory's network, signs in with a client that was approved on the Master, and sees and controls the night exactly as they would in the mobile app — with nothing to install, and with no way to reach the node's configuration *through WebConnect*. On an Astroberry controller that starts from the Galileo entry in Astroberry Manager, on the same address and with the same certificate trust as the rest of the device (Section 6.5).

## 4. Goals and Objectives

| # | Goal |
|---|---|
| G1 | Deliver WebConnect as the `WCON` plugin — a first-party plugin distributed as a ZIP from the Galileo Plugins repository (`PLUG-090`/`PLUG-110`) and, on Astroberry OS, as a Debian package (Section 6.5), independently enabled/disabled (`PLUG-060`), not bundled in the Galileo installer |
| G2 | **Control parity with MobileConnect.** Every operational area of [MobileConnect §6.4](../mobileconnect/PSD.md) — devices, imaging, sky and framing, plate solving, focus (manual and automatic, in the focus module), guiding, meridian flip, sessions (run **and** author/edit), scheduler (view **and** author/edit), calibration, safety, Library and history, emergency stop — is available in the browser; configuration remains out of reach (G6) |
| G3 | **A Flask web application** serves the user interface and a browser-facing API. It is written against the same Control Surface and Connect Link as every other remote client; it has no private route into Galileo |
| G4 | **Live state without polling**: the browser receives pushed state, progress and alerts (Server-Sent Events, decided in Section 13.1 D1), and shows the same Pier timelines (`OBS-150`) as the Dashboard |
| G5 | **Responsive, tablet-first layout** that also works on a desktop browser and, reduced, on a phone; night-vision (red) theme; usable with touch and with mouse and keyboard |
| G6 | **Same safety and permission model as MobileConnect**: Viewer and Operator roles, per-Pier control lease shared with the desktop and the mobile apps, confirmation on destructive operations, always-available emergency stop, held-motion deadman, audit log; no `config.*` permission ever granted |
| G7 | **Pairing with approval on the Master.** A browser/user is registered by a request that a person approves on the Master (Connect Link L2); only then can it sign in |
| G8 | **Runs on the Master node only, with the Master as proxy.** The Flask application is hosted by the Master (the hub of [NodeConnect](../nodeconnect/PSD.md)'s hub-and-spoke) and is the single web entry point for the whole installation: a browser sees the Master's own Piers and, through the Master, every paired node's Piers. Requests for another node's Pier are relayed by the Master over Connect Link; browsers never contact a spoke node directly |
| G9 | Keep the plugin's own options in Galileo's database, with in-app help for each control (core's definition of done) |
| G10 | **Browser outreach.** During an owner-opened outreach event ([MobileConnect §6.8](../mobileconnect/PSD.md)), a visitor scans a QR code with their phone camera, lands in their browser — **nothing to install, no registration** — and sees the live image of each offered Pier as every frame is made, and can switch between offered Piers (Section 6.4) |
| G11 | **First-class on Astroberry OS.** Run as a managed service of an Astroberry OS controller, behind Astroberry's own web front door (its Caddy server), at an address reachable from Astroberry Manager, sharing the device's name and certificate trust, and leaving Astroberry exactly as it was when removed (Section 6.5) |

## 5. Non-Goals (Explicitly Out of Scope)

- **No configuration**, on exactly the same boundary as [MobileConnect §5/§6.4](../mobileconnect/PSD.md). Equipment, Observatories, safety rules, Options and plugin options are not exposed.
- **No new operational capability.** WebConnect exposes what the Control Surface offers; a function not on the surface (for MobileConnect too) is out. The two plugins are developed against one catalogue.
- **No reimplementation of Galileo screens.** The browser UI is a purpose-built operating interface, not a port of the PySide6 application, and not a remote-desktop view.
- **No duplication of Astroberry Manager.** System functions Astroberry already provides — INDI driver and profile management, the web terminal, the remote desktop, operating-system updates, hotspot and Wi-Fi, backup and restore, power — stay in Astroberry Manager and its sibling services. WebConnect links to them and does not re-create them.
- **No internet exposure.** No tunnelling, port-forwarding assistance, dynamic DNS or cloud relay. The web application is for the user's network (LAN, or a VPN the user already runs); the documentation says so plainly. If the user chooses to publish it, a reverse proxy and its TLS are theirs to provide.
- **No standing anonymous or guest access; no public share links.** The one exception is browser outreach (Section 6.4): owner-opened, time-limited, confined to the outreach network, authenticated by a per-event secret, images only. Outside an event nothing answers an unpaired browser.
- **No independent user directory in v1.** Sign-in identities are the approved clients/users registered on the Master (G7), not a separate account system, single sign-on or LDAP.
- **No offline use.** No service-worker caching of operational state; a cached copy of an observatory's state would be a hazard.
- **No FITS processing in the browser.** Previews are rendered on the node; downloading a FITS frame is an explicit action.
- **No dependency of the night on the browser**: closing the tab or losing the connection never stops imaging (apart from a held manual motion, MobileConnect §6.3 C5).

## 6. Dependencies

### 6.1 Galileo core

| Core capability | Core requirement | How this plugin uses it |
|---|---|---|
| Plugin loading, manifest/version check, fault isolation | `PLUG-010`–`PLUG-050` | Loaded and isolated; a failure in the web application never affects imaging |
| Enable/disable, inertness | `PLUG-060` | Disabling stops the web application, closes its listener and ends every browser session |
| Core service access via `PluginContext` | `PLUG-080` | Launching and supervising the Flask process (self-hosted profile), or starting and stopping its service and handing it its settings (Astroberry profile, Section 6.5); reading its own options |
| Plugin Options page and settings | `PLUG-170`, `PLUG-150` | Allowed-clients list and revocation, session timeout, whether to start with Galileo; and, self-hosted profile only, port, bind address and TLS certificate source |
| Top-level section | `PLUG-130` | A WebConnect section: address to open, signed-in browsers, lease holders, audit log |
| Event bus, Dashboard timeline model | `galileo.bus`, `OBS-150` | Source of the live state the browser shows |
| Inline help | `HELP-060` | The plugin ships its own help Markdown |

### 6.2 Facilities shared with MobileConnect and NodeConnect (proposed core additions)

| Facility | Defined in | WebConnect's use |
|---|---|---|
| **Connect Link** (pairing with approval and token, scoped permissions, encrypted transport, event stream, resumable binary transfer, version handshake, **outreach event facility L9**) | [NodeConnect PSD §6.2](../nodeconnect/PSD.md) | The Flask application authenticates to the node with its own paired token and relays on behalf of signed-in browsers |
| **Control Surface** (catalogue of operations and observable state), **control lease**, operation events, server-side previews, held-motion deadman, manual focus in the focus module | [MobileConnect PSD §6.3](../mobileconnect/PSD.md) (C1–C6) | The sole source of operations and state; the browser UI is driven by the catalogue |

### 6.3 Placement and proxying

**One placement: on the Master node.** A Flask process (under a production server, not Flask's development server) runs on the Master, alongside Galileo, and is started and stopped with the plugin: supervised by the plugin itself in the self-hosted profile, or run as a systemd service that the plugin starts and stops on an Astroberry controller (Section 6.5). WebConnect is not installed or enabled on spoke nodes; there is no stand-alone or other-machine deployment.

**The Master is the proxy.** For a Pier of the Master itself, the Flask process uses the Master's own Connect Link and Control Surface. For a Pier on a spoke node, the Master relays the browser's request to that node over Connect Link and relays the node's state and events back, so one browser session and one live stream cover the whole installation. The browser sees one address, one sign-in, one lease model and one audit log.

**Trust for proxying.** NodeConnect pairing gives the spoke a token to talk to the Master; operating a spoke from the Master needs the reverse grant. When a node pairs (approved on the Master), the node's own user is additionally asked whether to **allow the Master to operate this node** (`control`/`view` scopes only — never `config.*` — and off unless granted); the grant can be revoked on the node at any time. A node that has not granted it appears in the browser as view-only, or absent if it grants nothing.

**Consequences accepted.**
- A spoke node's operations are unavailable while the Master is down or the spoke is detached (the spoke keeps imaging; only remote operation is affected). The browser shows the node as unreachable.
- The control lease for a spoke's Pier is held on that spoke, so the desktop on the spoke, a MobileConnect client paired to it, and the Master's proxy all contend through one lease.
- Proxy latency is the Master→node latency; previews are rendered on the owning node and relayed, not re-rendered on the Master.

Core's rule against `localhost` in device and PHD2 addresses ([NodeConnect PSD](../nodeconnect/PSD.md) C5) concerns stored equipment addresses; the Flask process reaching its own Master's Connect Link is a managed, plugin-internal link, not a user-entered address, and is unaffected. The SDD confirms this.

### 6.4 Browser outreach (unregistered image viewers)

Browser outreach is the web counterpart of [MobileConnect's outreach mode](../mobileconnect/PSD.md) (its §6.8, D18–D20) and is **the same event with the same rules**, hosted in core by Connect Link's outreach facility (L9, D10): one outreach event, opened by the owner on the Master, can offer images to apps, to browsers, or to both. Everything in MobileConnect O1–O8 (closed by default and by timer, per-event secret, source-subnet confinement, a single `outreach.view` scope, owner-offered Piers, bounded load, metadata-free previews, aggregate-only audit) applies unchanged. This section lists only what is particular to a browser.

| # | Obligation | Why |
|---|---|---|
| B1 | **Same event, same switch.** The owner chooses on Connect Link's Outreach page whether an event is offered to apps, browsers or both. With browsers off, the outreach web application does not start. WebConnect contributes only the **browser surface**: its QR payload, its guest routes and its SSE delivery; the event, secret, subnet guard, tokens, caps, audit and guest previews are the facility's | G10 |
| B2 | **Scan, then browse.** The event display shows the Wi-Fi QR code (outreach SSID) and a **web QR code** that encodes an HTTPS address of the outreach page with the event secret in the URL **fragment** (`https://<host>:<port>/outreach#e=<event>&s=<secret>`). The fragment is never sent to the server by the browser, so it does not appear in server logs, proxies or the `Referer` header; the page's script reads it and posts it to enrol. The address is also shown as short text to type | G10, R9 |
| B3 | **A separate outreach web application.** Browser outreach is served by its own small Flask application with its own listener, **bound to the outreach network's address** and port and started only while a browser-enabled event is open. It serves the outreach page, its static assets and the guest routes — nothing else. The operating web application (Sections 6.3, G2) is not reachable on the outreach listener, and itself refuses requests from the outreach subnet | R7 |
| B4 | **Guest session.** Enrolment exchanges the event secret for a guest token held in an `HttpOnly`, `Secure`, `SameSite=Strict` cookie that expires when the event ends; there is no name, account or sign-in form. Ending the event, ejecting guests or re-issuing the secret ends the session | G10 |
| B5 | **Live image and Pier switching.** The page shows the **live image of the chosen Pier as each frame completes**, pushed by Server-Sent Events (D1), with the age of the image; a visitor switches between the owner-offered Piers (a new event stream for the chosen Pier), and a joining or switching visitor is sent the latest image at once. Nothing else is shown — no state, timelines, controls, Library or alerts | G10 |
| B6 | **Hardened for the public.** Strict `Content-Security-Policy` with no inline script and **no third-party resource of any kind** (no CDN, font or analytics — the outreach network may have no internet); `Referrer-Policy: no-referrer`; `Cache-Control: no-store` on images; no service worker; rate-limited enrolment; the concurrent-guest cap and guest load rules of MobileConnect O7 | R7, R8 |
| B7 | **Phone-first and night-friendly.** The outreach page is designed for a phone held by a visitor, works on any current browser, defaults to a dark, dim theme and offers a red-light toggle so visitors do not spoil dark adaptation | G10 |
| B9 | **HTTPS with the owner's certificate.** The outreach listener serves HTTPS only, using a certificate the owner supplies for a stable name on the outreach network (for example a local hostname with a certificate from their own CA, or a public CA via DNS challenge); it will not start an event without one, and there is no plain-HTTP mode. The control web application keeps its own certificate (PC4) | R7, D9 |
| B8 | **The same single scope.** The browser holds a guest token with `outreach.view` and nothing else; the outreach routes are an allowlist and every other route refuses, exactly as for an app guest | R7 |

Consequences accepted: the outreach listener is a second, deliberately tiny network service while an event is open (B3); the owner must supply a certificate for the outreach listener (B9) and an outreach hostname that the visitors' network resolves; and the owner provides the isolated outreach network, as for app outreach (MobileConnect R15).

### 6.5 Deployment on Astroberry OS

Astroberry OS is a Debian Trixie / Raspberry Pi OS distribution for astronomy controllers (Pi 4/5 arm64, and amd64 since 3.2). Galileo and WebConnect are layered onto it as additional packages by the [galileo-astroberry](https://github.com/gordtulloch/galileo-astroberry) project, which owns packaging, the APT repository and service integration; its guiding rule is that Astroberry is left untouched. This section records how Astroberry deploys its web interface — because WebConnect must fit that arrangement, not invent its own — and what follows.

#### 6.5.1 What Astroberry deploys

Read on 2026-10-31 from the `astroberry-manager` fork (v1.2) and the upstream `astroberry-os-sysmod` repository (not forked). Re-verify on a running system before the SDD relies on any row.

| Component | How it is deployed |
|---|---|
| **Caddy — the web front door** | The web listener on ports 80 and 443, with no `bind` directive and so on every interface. One catch-all site (`http://, https://`) with `tls internal` and on-demand issuance from Caddy's own local CA; automatic HTTP→HTTPS redirects are disabled, so **plain HTTP is served as well**. Three routes: `/api*` → INDI Web Manager (127.0.0.1:8624), `/websockify*` → the remote-desktop bridge (127.0.0.1:8070), everything else → Astroberry Manager (127.0.0.1:8080). The file is `Caddyfile.astroberry`, owned by the `astroberry-os-sysmod` package and linked as `/etc/caddy/Caddyfile` (the distribution's own file is diverted). **It has no include or drop-in directory.** `caddy trust` is run at first initialisation |
| **Astroberry Manager** | Python package `astroberry-manager` (a Debian package, architecture `all`) from Astroberry's APT repository, run against the **system** Python packages — no virtual environment. One Flask + Flask-SocketIO process under gevent, systemd unit `astroberry-manager.service` (user `astroberry`, `Restart=always`), listening on 127.0.0.1:8080 only. A single-page "desktop" UI of a dock and panels (location, conditions, equipment, almanac, system, star chart), with every script, style and font vendored in the package. Sign-in is **PAM** against the host's accounts, kept in a signed Flask session cookie (`session`, path `/`). It offers a **bash terminal in the browser**, system update, backup, restore, restart and shutdown, and an INDI client on 127.0.0.1:7624 whose proof-of-concept `equipment` event can set the telescope's location and send a go-to |
| **INDI, INDI Web Manager** | INDI server on 7624; `astroberry-indiwebmanager.service` on 127.0.0.1:8624 |
| **Remote desktop** | `astroberry-desktop-web.service` (a TigerVNC server on display :70, localhost only, started with `-SecurityTypes None`) behind `astroberry-websockify.service` on 127.0.0.1:8070; reached from the browser only through Caddy at `/websockify` |
| **Discovery and trust** | Avahi advertises `_http._tcp` on port 80 under the host name. The Manager serves Caddy's root certificate at `/ca.crt` (read from Caddy's admin API on localhost:2019) so a browser can be made to trust the device, after a first-visit "welcome" page |
| **Packaging and updates** | Debian packages for Trixie from `astroberry.io/debian` (`trixie`, `trixie-testing`, `trixie-staging`), each component built by its own workflow in a Docker builder. Updates are APT upgrades |

#### 6.5.2 What follows for WebConnect

| Astroberry fact | Consequence for WebConnect |
|---|---|
| Caddy is the only door; every application listens on loopback | WebConnect listens on loopback (or a Unix socket) only, opens **no LAN-facing port and no listener of its own for the operating application**, and is reached through Caddy. The address is `https://<device name>.local/` plus a prefix — no extra port to remember, to open or to collide |
| Caddy terminates TLS with its local CA; the Manager already tells users how to trust it (`/ca.crt`) | WebConnect generates and pins **no** certificate in this profile. The browser-warning problem of a self-signed certificate (§13.2 Q2 history, SDD P9) is solved once, for the whole device, by Astroberry's own CA step |
| Plain HTTP is also served on port 80 | A session cookie must never travel in clear: WebConnect refuses pairing, sign-in and every state-bearing route unless the request reached Caddy over HTTPS, and redirects its own prefix to HTTPS. It trusts the scheme only from the front door |
| Routing is by path with a root catch-all; `/api*`, `/websockify*` and (via the catch-all) `/socket.io`, `/login`, `/logout`, `/welcome`, `/assets` and `/ca.crt` belong to others | WebConnect lives **under its own path prefix** (default `/galileo/`), generates no root-absolute URL, and its wire API (`/webconnect/v1`) and browser API (`/api/v1/...`) are *beneath* that prefix, which keeps them clear of the `/api*` route. Its route must be evaluated before the catch-all |
| Caddyfile has no include mechanism and belongs to `astroberry-os-sysmod` | Adding the prefix route cleanly needs **one small upstream change** (an include directory inside the site block). Until it is merged, how the route is installed is an open decision (Q6); it is the one place the "leave Astroberry untouched" rule is under pressure |
| The Manager and WebConnect would share one web origin, and the Manager's cookie is `session` on path `/` | WebConnect's cookies use different names, are scoped to its prefix and use `__Secure-` (the `__Host-` prefix of the self-hosted profile needs path `/`). It reads and writes none of the Manager's cookies. A script injected into the Manager runs in WebConnect's origin — this is stated as a risk (R10), not designed away |
| Caddy accepts any `Host` | WebConnect's `Host`/`Origin` allowlist (`WCON-1060`) must list the device's names and addresses (host name, `.local` name, hotspot and LAN addresses), because the front door will not |
| Caddy is the immediate peer for every request | The browser's source address — needed for rate limits, the audit log and the outreach-subnet refusal — comes from the front door's forwarded header, trusted only from the front door |
| The Manager's session is a PAM login; the Manager has a shell in the browser | WebConnect's approved-device sign-in (D3) is a different, narrower mechanism and does **not** rely on the Manager's session. Approving a browser on a headless controller (no one at the Master's screen) therefore needs its own answer (Q7) |
| The Manager runs as a systemd service, independent of any other application | WebConnect's web half is likewise a systemd service with its own lifecycle, so the address answers with a clear "Galileo is not running" page when Galileo is stopped, rather than a bare gateway error from Caddy; the plugin's enable/disable maps to starting/stopping that service (Q5) |
| The controller may have no internet (hotspot) | Already required: nothing is fetched from a third party (`WCON-800`). WebConnect vendors its own assets and does not borrow the Manager's `/assets` |
| The Manager's Equipment panel is a second INDI client able to send a go-to | Galileo's control lease governs Galileo clients only. Documentation must say that Manager's equipment panel and KStars bypass the lease; a Galileo-side warning is a design option (galileo-astroberry PSD §8) |
| The outreach network is likely the Astroberry hotspot, and Caddy listens on every interface | A visitor on that network can reach the front door — and therefore the Manager's login page and `/websockify` — unless the owner firewalls it. WebConnect's own outreach listener is separate (§6.4) and its operating application refuses outreach-subnet sources (`WCON-1220`), but it cannot protect the rest of the device. Documentation must require an outreach network that does not reach the front door (R11) |

#### 6.5.3 Integration levels

| Level | What | Needs from Astroberry |
|---|---|---|
| **0 — Coexist** | WebConnect runs as its own service behind the same Caddy, under its prefix, on the device's name and trust | The Caddy include change (Q6) |
| **1 — Reachable from the Manager** | A **Galileo** entry in the Manager's dock opens WebConnect (a plain link, not an embedded frame — a telescope-control page is not framed, `WCON-1020`); WebConnect carries a link back to the Manager. For each paired node it can also link to that node's own Manager for system tasks | A small, generic "register an application" extension in the Manager (the fork), designed to be upstreamed (Q8) |
| **2 — Status** | The Manager's System panel shows the Galileo and WebConnect services and versions (galileo-astroberry `SVC-06`) | Same extension point |
| **3 — Shared sign-in** | One login for the Manager and WebConnect | **Not pursued.** The Manager's login is a shell-equivalent PAM session with a signed cookie; letting it stand in for a device approval would widen WebConnect's trust to everything that session can do. Reconsidered only if Astroberry adopts a real authentication layer at the front door |

Levels 0 and 1 are in scope for v1; level 2 is a candidate; level 3 is out.

#### 6.5.4 Hosting profiles

| | **Astroberry profile** (primary) | **Self-hosted profile** |
|---|---|---|
| Where | A Master that is an Astroberry OS controller | A Master that is not (Windows, macOS, other Linux) |
| Lifecycle | systemd service; the plugin starts and stops it | The plugin starts and supervises the process |
| Network | Loopback or Unix socket, behind Caddy, under a path prefix | Its own HTTPS listener on the LAN interface |
| TLS | Caddy's local CA | A generated, pinned certificate or the user's own (PC4) |
| Distribution | Debian package, plus the plugin ZIP | Plugin ZIP |
| Browser cookies | `__Secure-`, scoped to the prefix | `__Host-` |

Everything else — pairing, roles, lease, relay, state, operations, images, safety, outreach — is **identical** in both. Whether the self-hosted profile is kept in v1 is Q4.

#### 6.5.5 Security posture of the combined system

WebConnect's boundary (approved devices, roles, no configuration route, audit) is only as strong as the network it sits on, and the Astroberry front door around it is more permissive than WebConnect is. As read from the sources in §6.5.1: nothing at the front door authenticates `/websockify*` or `/api*`, and the desktop behind `/websockify` is a VNC server started with no security; the Manager's signed session cookie is keyed by `APP_KEY`, whose default is a constant in the source, and the service unit does not set it; the Manager's terminal runs as the device's service user, and its restart and shutdown go through `sudo`. A person who can reach port 443 therefore can reach the Galileo desktop application — and its configuration — without going near WebConnect.

This does not change what WebConnect must be, and the PSD does not claim otherwise: WebConnect still gives per-person approval, roles, the lease, confirmation of destructive actions, audit and a deliberately narrow API, and those matter for safety and accountability. But on an Astroberry device they are **not** an access boundary until the front door requires authentication, and the documentation must say so (galileo-astroberry WEB-05). Closing that gap is an upstream matter for Astroberry (R12); WebConnect does not depend on it and does not patch around it.

## 7. Requirement Domain

One domain, **`WCON`** (WebConnect), specified in [the SRS](SRS.md). Provisional sub-areas:

| Area | Covers |
|---|---|
| Hosting and lifecycle | Flask process start/stop/supervision on the Master, bind address and port, TLS (per hosting profile, §6.5.4) |
| Astroberry integration | The Astroberry profile: systemd service, loopback/Unix-socket listener behind Caddy, path prefix, HTTPS enforcement behind the proxy, shared-origin cookies, forwarded client address, independence from the Manager's sign-in, headless approval, Galileo entry in the Manager, packaging, the register of upstream needs |
| Proxying | Relaying operations, state, events and previews to spoke nodes; the Master-operates-this-node grant; unreachable-node behaviour |
| Pairing, sign-in and roles | Approval on the Master, browser sessions, Viewer / Operator, lease, revocation, session timeout, audit |
| State and events | Pushed live state and alerts, Pier timelines |
| Operations | One screen group per row of MobileConnect §6.4, driven by the Control Surface; session and schedule authoring |
| Browser outreach | Offering an outreach event to browsers, the separate outreach listener, QR entry with a fragment-borne secret, guest cookie session, live image and Pier switching by SSE, public-facing hardening, phone-first outreach page |
| Images | Server-rendered previews, pan/zoom, optional FITS download |
| Safety and failure behaviour | Interlocks, confirmation, deadman, emergency, reconnect behaviour |
| Web UI (scope level) | Responsive layouts, night theme, browser support matrix, accessibility |
| Options, help and packaging | Options page, in-app help, plugin manifest, dependencies (Flask and its server) |

## 8. Stakeholders and Primary Personas

- **The observatory operator at a computer that isn't the node** — a laptop in the house, a second monitor in the warm room.
- **The user without a mobile app**, or on a platform the apps don't cover.
- **The multi-node operator** who opens one web address on the Master and operates every paired node through it (G8).
- **A guest** (Viewer role) shown the sky in a browser, with no ability to operate anything. This is an approved, paired Viewer.
- **The outreach visitor**: a member of the public at a star party who scans a QR code with their phone camera and watches the live image in their browser, never registered and unable to touch anything.

## 9. Project Constraints

| # | Constraint |
|---|---|
| PC1 | Cross-platform (Windows/macOS/Linux, including Raspberry Pi 5-class ARM and Astroberry OS on arm64 and amd64): the web application must be light enough to run beside imaging on a Pi; previews rendered on demand and cached, state pushed |
| PC2 | All plugin configuration in the shared database (core's firm rule), never a plugin-private file or `QSettings`. Browser-side storage holds only the session cookie and UI preferences |
| PC3 | Network work never runs on the Qt UI thread; the Flask application runs in its own process, so the web workload cannot stall Galileo's UI or the session executor |
| PC4 | Encrypted by default (HTTPS). Self-hosted profile: a self-signed certificate is generated for the node on first use and pinned in the Connect Link pairing; the user may supply their own. Astroberry profile: TLS is terminated by Astroberry's front door and the application serves only loopback. In neither is there a plain-HTTP mode reachable from the network, apart from a loopback health check |
| PC5 | Browser hardening is a requirement, not an afterthought (and applies with extra force to the outreach page, B6): CSRF protection on every state-changing request, strict session cookies, `Content-Security-Policy`, no inline script, rate-limited sign-in, and session expiry. Because the application can move a telescope, an unauthenticated route is a defect |
| PC6 | Imaging continues, unchanged, when the browser closes or the connection drops |
| PC7 | The web application uses the documented wire API ([MobileConnect PC4](../mobileconnect/PSD.md)) and nothing private, so it is also the reference test of that API for other clients |
| PC8 | A defined browser support matrix (current Chrome/Edge, Firefox, Safari on iOS/iPadOS/macOS, Chrome on Android) |
| PC9 | GPL-3.0-or-later, as the other first-party plugins; Flask (BSD-3) and its WSGI/ASGI server dependencies are licence-compatible and are listed in `THIRD_PARTY_NOTICES.md` when the plugin ships |
| PC10 | On Astroberry OS the application is one of several behind a shared origin: it is served beneath a path prefix, with routes and cookies that cannot collide with Astroberry Manager's, and with every asset vendored (the controller may have no internet) |
| PC11 | Packaging follows Astroberry's conventions as set by the galileo-astroberry PSD: Debian packages per architecture for Trixie, the plugin's own virtual environment (not Astroberry's system Python packages), and no modification of any file owned by an Astroberry package |

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | An internet-facing deployment of a web app that can move a telescope | Scope and documentation state LAN/VPN only; PC4/PC5; self-hosted profile binds to the LAN interface by default, with an explicit setting to widen it; Astroberry profile binds loopback only; no help offered for exposing it |
| R2 | The two remote front ends (app and browser) diverge in what they offer | One Control Surface catalogue and one operational scope (MobileConnect §6.4); a shared parity test checks each operation in the catalogue is reachable in both |
| R3 | Flask is WSGI, so long-lived push streams and many simultaneous viewers tie up workers | Production server chosen for streaming in the SDD; push by Server-Sent Events from a small number of workers; performance budget checked on a Pi |
| R4 | A session-authoring UI in a browser is a large piece of front-end work | Reuse the block model and validation from the Control Surface; tablet-first design shared in spirit with the mobile apps; authoring can ship after the operating screens |
| R5 | Browser sign-in and CSRF mistakes are the usual way such tools are broken | PC5 as requirements with tests; security review of the web application before release |
| R7 | An unregistered, public-facing web listener on the Master | Only while an owner-opened event is open; bound to the outreach address (B3); source-subnet confined; one scope and an allowlist (B8); no third-party resources, strict headers (B6); the operating app is unreachable from it; fails closed if no subnet is configured |
| R8 | A crowd of visitors' browsers loads a Pi-class Master that is imaging | Concurrent-guest cap, small guest previews, lowest priority behind the session (MobileConnect O7); SSE from few workers (R3) |
| R9 | The event secret leaks from a QR code in a photograph or a link shared by a visitor | Secret in the URL fragment, never in logs or `Referer`; per-event, re-issuable, expires with the event; useless off the outreach subnet (MobileConnect O2, O3) |
| R6 | The Master becomes a single point of access and holds operating rights over spoke nodes | The grant is opt-in per node, limited to `control`/`view`, revocable on the node; the Master's loss never stops a spoke's imaging; every proxied operation is audited on both the Master and the owning node |
| R10 | On Astroberry, WebConnect shares a web origin with Astroberry Manager, which has a browser terminal and loads third-party-style libraries: a script injected into the Manager runs in WebConnect's origin | Separate cookie names and prefix-scoped paths (so neither reads the other's); strict CSP and CSRF on WebConnect's side; stated plainly in the documentation; the structural fix (a separate origin) is not available behind one front door and is not pursued |
| R11 | The Astroberry front door listens on every interface, including a hotspot that is likely to be the outreach network | Outreach uses its own listener (§6.4) and the operating application refuses outreach-subnet sources, but neither protects the Manager or the desktop bridge. Documentation requires an outreach network that cannot reach ports 80/443 of the controller; the design records this as an owner obligation |
| R12 | Astroberry's front door does not authenticate `/websockify*` or `/api*`, and the Manager's session key has a constant default (§6.5.5), so WebConnect's roles are not an access boundary on an Astroberry device | Say so in the documentation and the success criteria; raise both upstream with Astroberry (galileo-astroberry UP-01); do not build workarounds into WebConnect, and do not describe WebConnect as securing the device |
| R13 | The route cannot be added to Caddy without changing a file Astroberry's package owns | One small upstream change (an include directory in the site block); register it as an integration point; until merged, a documented interim (Q6) that is removed when upstream lands |
| R14 | Two lifecycles (Galileo's plugin enable/disable, and the web half's systemd service) drift: the plugin is disabled but the service still listens, or the reverse | The plugin starts and stops the service through a unit-specific authorisation; if it cannot, the web half closes itself when the Master half reports "disabled"; a test covers both |

## 11. Success Criteria (Scope-Level)

- A browser on another computer, after the node approves it, shows live state for every Pier within seconds, without polling.
- The same night's essentials listed for MobileConnect — connect, find and go to a target, centre by plate solve, focus (manually and automatically), guide, run a session, respond to a flip or safety event, author and run a schedule — can be done entirely in the browser.
- A browser, or a hostile request from it, cannot reach any configuration route; a Viewer cannot issue any operation; a forged or missing CSRF token is rejected.
- With the desktop or a mobile app holding the lease, the browser's mount command is refused with an explanation; Emergency stop still works.
- Closing the tab mid-session does not interrupt the session; a held jog stops within a second of the connection dropping.
- Disabling the plugin leaves no web listener and no running Flask process.
- With no outreach event open, nothing answers an unpaired browser. With one open, a browser off the outreach subnet or without the event secret is refused, and the operating web application cannot be reached from the outreach listener.
- A visitor scans the QR code with a phone camera, sees the live image of an offered Pier within seconds of each frame completing, switches Piers, and cannot reach any state, operation, Library, FITS or configuration route; ending the event ends every visitor's session.
- On a stock Astroberry OS controller (arm64 and amd64), installing the Galileo packages makes WebConnect answer at `https://<device name>.local/galileo/` with the browser already trusting the device's certificate, with no manual file editing and no extra port; removing them returns the device to stock behaviour.
- The Galileo entry in Astroberry Manager opens WebConnect, and WebConnect links back; each works with the other stopped.
- Over plain HTTP, WebConnect pairs, signs in and carries state for nobody; its cookies never reach, or are read from, the Manager.
- With Galileo stopped, the address says so and links to the Manager; with the plugin disabled, nothing of WebConnect listens.
- On a controller with no one at the screen, a person can approve, promote and revoke browsers.

## 12. Glossary

| Term | Meaning |
|---|---|
| **Control Surface** | The proposed core registry of operations and observable state ([MobileConnect PSD](../mobileconnect/PSD.md) C1) |
| **Connect Link** | The proposed shared core transport, pairing and permission facility ([NodeConnect PSD](../nodeconnect/PSD.md) §6.2) |
| **Lease** | The right to issue Pier-affecting operations, one holder per Pier at a time |
| **Viewer / Operator** | The two roles |
| **Outreach event / guest token** | As in [MobileConnect §6.8](../mobileconnect/PSD.md): the owner-opened, time-limited period, and the anonymous `outreach.view` credential issued within it |
| **Outreach listener** | The separate, minimal web listener bound to the outreach network that serves browser outreach only (B3) |
| **Astroberry OS / Astroberry Manager** | The astronomy-controller distribution Galileo is layered onto, and its web interface (a Flask application with a dock of panels, PAM sign-in, a browser terminal and an INDI client) |
| **Front door** | Astroberry's Caddy web server: the one listener on ports 80/443, terminating TLS and routing by path to the Manager, INDI Web Manager and the remote-desktop bridge |
| **Hosting profile** | The deployment shape of the web half: *Astroberry* (systemd service behind the front door) or *self-hosted* (plugin-supervised, own HTTPS listener) — §6.5.4 |

## 13. Decisions from Review and Remaining Questions

### 13.1 Decided (review of 2026-10-27)

| # | Decision |
|---|---|
| D1 | **Live updates use Server-Sent Events** for server→browser state; operations are ordinary POSTs. The production server for Flask is chosen in the SDD by measuring on a Pi |
| D2 | **Front end: light JavaScript with server-rendered templates.** A framework such as React is adopted only for a screen where it is warranted (the likely candidate is session/schedule authoring) and is then confined to that screen, built into static files shipped in the plugin ZIP |
| D3 | **Browsers sign in as approved devices**, the same mechanism as MobileConnect; no separate user accounts in v1 |
| D4 | **WebConnect runs on the Master node only and the Master proxies to spoke nodes** (Section 6.3) |
| D5 | **MobileConnect proxies through the Master too**; both front ends share the Master's one relay implementation ([MobileConnect §6.6](../mobileconnect/PSD.md)) |
| D6 | **Browser outreach is in scope for v1**, as the web counterpart of MobileConnect outreach, sharing its event, secret, subnet confinement and `outreach.view` scope (Section 6.4). This resolves MobileConnect PSD Q3 |
| D7 | **Browser outreach is served by a separate, minimal listener bound to the outreach network** and started only during a browser-enabled event; the operating web application is never exposed on it (B3) |
| D8 | **The event secret travels in the QR code's URL fragment**, not its path or query (B2) |
| D9 | **Browser outreach is HTTPS-only with a certificate the owner supplies** (B9); no plain-HTTP option |
| D10 | **The outreach event is hosted in core as a Connect Link facility (L9)**, shared with MobileConnect; WebConnect contributes the browser surface only. WebConnect alone is enough to run browser outreach |

### 13.1a Decided (project direction, 2026-10-31)

| # | Decision |
|---|---|
| D11 | **Close integration with Astroberry OS and Astroberry Manager.** On an Astroberry controller the browser, through WebConnect and the Manager, is the primary way to operate Galileo, rather than the Galileo desktop client; the desktop client is reached through Astroberry's remote desktop for configuration. Section 6.5 and the `WCON-14xx` requirements follow |
| D12 | **WebConnect is built inside Galileo and Galileo-Plugins; there is no separate repository.** Documents and core facilities are here; the plugin, the Flask applications and their packaging are in `Galileo-Plugins/webconnect`. The `Galileo-WebConnect` repository (a v0.1 subset of this PSD and a README, no code) is retired. This resolves that repository's open question on where the plugin shim lives, and supersedes the earlier checklist decision to keep the source in its own repository |

### 13.2 Remaining

| # | Question | Recommendation |
|---|---|---|
| Q1 | *(Resolved: keep two plugins.)* Should WebConnect and MobileConnect be one plugin with two front ends? | Keep two plugins: users want one without the other, each has different dependencies, and `PLUG-060` keeps a disabled plugin fully inert |
| Q2 | *(Resolved: HTTPS with an owner-supplied certificate, D9.)* **Certificates for visitors.** PC4 generates a self-signed certificate, which a visitor's browser will warn about — an unfriendly first impression and a bad habit to teach the public. How should the outreach listener be secured? | HTTPS with a certificate the owner supplies for a stable name on the outreach network (for example a local hostname and a certificate from their own CA or a public CA via DNS challenge). As an explicit, **off-by-default** owner setting, allow plain HTTP *on the outreach listener only*, since it carries only images to anonymous visitors on an isolated network; never for the operating application |
| Q3 | *(Resolved: in core, in Connect Link, D10.)* **Where does the shared outreach event live?** The event (open/close, secret, subnet guard, guest tokens, caps, aggregate audit, guest previews) is needed by both MobileConnect and WebConnect, and either may be installed alone | In Connect Link (core), alongside the L2 outreach enrolment already proposed there, with each plugin contributing only its surface (app routes, browser listener). Decide with the core Connect Link SRS |
| Q4 | **Is the self-hosted profile in v1?** The Astroberry profile is the primary target (D11); the plugin-supervised, own-TLS design of v0.2 still serves a Windows, macOS or non-Astroberry Linux Master | Keep it, but build the Astroberry profile first and treat the self-hosted profile as P2. The requirements are written profile-neutral so nothing is lost; if it is dropped, `WCON-060`, `070`, `1010` and the supervisor half of `WCON-030` are removed |
| Q5 | **Who owns the web half's lifecycle on Astroberry?** (a) systemd runs it and the plugin starts/stops the service; (b) the plugin spawns it as in the self-hosted profile, with systemd running only Galileo | (a): it gives a "Galileo is not running" page instead of a bare gateway error, restarts it on failure the way Astroberry restarts its own services, and keeps one process model for the packages. It needs a unit-specific authorisation (polkit) for the plugin to start/stop the service, with the web half closing itself when told it is disabled if that is refused (R14) |
| Q6 | **How does the route reach Caddy** when its Caddyfile belongs to `astroberry-os-sysmod` and has no include? (a) Upstream an include directory, interim local edit; (b) edit the file from our package; (c) add the route at run time through Caddy's admin API; (d) a second Caddy site on another port | (a). (b) breaks the "untouched" rule and is overwritten on a sysmod upgrade; (c) is lost on reload; (d) gives up the single address and trust. The interim edit, its removal when upstream merges, and the effect of a sysmod upgrade are to be specified by galileo-astroberry |
| Q7 | **Headless approval.** A new browser is approved "on the Master" (G7), but an Astroberry controller has no one at its screen. Options: (a) the Galileo desktop in the remote desktop; (b) a WebConnect administration page that signs in with a local Astroberry account by PAM and can only approve, promote and revoke browsers; (c) the Manager's session | (a) works today and is the fallback; add (b) as `WCON-1481` (P2) — it is WebConnect's own check, with no dependency on the Manager, and approving devices gives a person who already holds the device's password nothing new. Not (c) (§6.5.3 level 3) |
| Q8 | **Depth of Manager integration.** A link in the Manager's dock (level 1), plus status (level 2), via a generic "register an application" extension in the fork | Level 1 for v1 and level 2 if the extension point is cheap; the registration is Astroberry integration metadata and is Astroberry's to shape, not Galileo configuration. The fork carries it first, written to be upstreamed |
| Q9 | **Where do the Debian sources live?** In `Galileo-Plugins/webconnect/debian` beside the code (as `astroberry-manager` does), with galileo-astroberry owning the meta-package, repository and units shared by Galileo | In `Galileo-Plugins/webconnect`, so the package and the code version together; the unit, the polkit rule and the Caddy route belong to `galileo-webconnect` |
| Q10 | **Conflicts with the galileo-astroberry PSD.** That document says WebConnect and the Manager are *sibling* applications that link and do not embed, and that Astroberry is never patched; D11 asks for closer integration, which needs a change in the Manager fork (level 1) and in sysmod (Q6) | Amend galileo-astroberry's principle 1 to "no local patches *except* upstream-bound changes carried in the fork", and its WEB-02/WEB-03 to name the front door; keep "neither embeds the other" |
| Q11 | **Internal port and Manager coexistence.** Which loopback port or Unix socket the web half uses, and whether a second INDI client (the Manager's equipment panel) needs a Galileo-side warning | Unix socket if Caddy's group permissions allow; otherwise a fixed loopback port chosen against Astroberry's map (8080, 8624, 8070, 5970, 7624, 2019 are taken). A warning is galileo-astroberry's to decide |
