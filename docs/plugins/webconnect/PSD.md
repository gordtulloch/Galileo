# WebConnect Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — WebConnect Plugin (browser control of a Galileo node through a Flask web application) |
| **Document** | PSD (Project Scope Document), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-27 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Sibling plugins** | [MobileConnect](../mobileconnect/PSD.md) — defines the operational surface this plugin reuses (its Section 6.4); [NodeConnect](../nodeconnect/PSD.md) — defines the shared Connect Link facility (its Section 6.2) |
| **Downstream documents** | SRS, SDD, RTM — not yet written; to follow this PSD's approval |

---

## 1. Purpose of This Document

This document defines the scope of the **WebConnect plugin** — a first-party Galileo plugin that lets a user operate a running Galileo node **from any web browser**, through a web application built on **Flask**. It offers the same level of control as [MobileConnect](../mobileconnect/PSD.md) — everything operational, nothing configurational — without installing an app. It follows the same PSD→SRS→SDD→RTM structure as [the core chain](../../PSD.md) and the other plugins' chains, and stays above implementation detail.

## 2. Background and Motivation

The mobile apps cover tablets and phones that the user owns and has set up. A browser covers everything else: a laptop at the kitchen table, a borrowed machine, a Linux desktop, a Chromebook, a kiosk screen in the observatory. It needs nothing installed, so it is also the lowest-friction way to look at a node for the first time.

The operational surface is identical in intent to the mobile one: the node is already configured and running, and the remote user watches and operates it. Defining that surface twice would let the two drift apart. WebConnect therefore **consumes the surface MobileConnect defines** — the Control Surface and the operational scope of MobileConnect §6.4 — rather than redefining it, and differs only in how it is presented and authenticated.

## 3. Vision Statement

> A Galileo user opens a web address on any computer, tablet or phone on the observatory's network, signs in with a client that was approved on the Master, and sees and controls the night exactly as they would in the mobile app — with nothing to install, and with no way to reach the node's configuration.

## 4. Goals and Objectives

| # | Goal |
|---|---|
| G1 | Deliver WebConnect as the `WCON` plugin — a first-party plugin distributed as a ZIP from the Galileo Plugins repository (`PLUG-090`/`PLUG-110`), independently enabled/disabled (`PLUG-060`), not bundled in the installer |
| G2 | **Control parity with MobileConnect.** Every operational area of [MobileConnect §6.4](../mobileconnect/PSD.md) — devices, imaging, sky and framing, plate solving, focus (manual and automatic, in the focus module), guiding, meridian flip, sessions (run **and** author/edit), scheduler (view **and** author/edit), calibration, safety, Library and history, emergency stop — is available in the browser; configuration remains out of reach (G6) |
| G3 | **A Flask web application** serves the user interface and a browser-facing API. It is written against the same Control Surface and Connect Link as every other remote client; it has no private route into Galileo |
| G4 | **Live state without polling**: the browser receives pushed state, progress and alerts (Server-Sent Events, decided in Section 13.1 D1), and shows the same Pier timelines (`OBS-150`) as the Dashboard |
| G5 | **Responsive, tablet-first layout** that also works on a desktop browser and, reduced, on a phone; night-vision (red) theme; usable with touch and with mouse and keyboard |
| G6 | **Same safety and permission model as MobileConnect**: Viewer and Operator roles, per-Pier control lease shared with the desktop and the mobile apps, confirmation on destructive operations, always-available emergency stop, held-motion deadman, audit log; no `config.*` permission ever granted |
| G7 | **Pairing with approval on the Master.** A browser/user is registered by a request that a person approves on the Master (Connect Link L2); only then can it sign in |
| G8 | **Runs on the Master node only, with the Master as proxy.** The Flask application is hosted by the Master (the hub of [NodeConnect](../nodeconnect/PSD.md)'s hub-and-spoke) and is the single web entry point for the whole installation: a browser sees the Master's own Piers and, through the Master, every paired node's Piers. Requests for another node's Pier are relayed by the Master over Connect Link; browsers never contact a spoke node directly |
| G9 | Keep the plugin's own options in Galileo's database, with in-app help for each control (core's definition of done) |

## 5. Non-Goals (Explicitly Out of Scope)

- **No configuration**, on exactly the same boundary as [MobileConnect §5/§6.4](../mobileconnect/PSD.md). Equipment, Observatories, safety rules, Options and plugin options are not exposed.
- **No new operational capability.** WebConnect exposes what the Control Surface offers; a function not on the surface (for MobileConnect too) is out. The two plugins are developed against one catalogue.
- **No reimplementation of Galileo screens.** The browser UI is a purpose-built operating interface, not a port of the PySide6 application, and not a remote-desktop view.
- **No internet exposure.** No tunnelling, port-forwarding assistance, dynamic DNS or cloud relay. The web application is for the user's network (LAN, or a VPN the user already runs); the documentation says so plainly. If the user chooses to publish it, a reverse proxy and its TLS are theirs to provide.
- **No anonymous or guest access**; no public share links.
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
| Core service access via `PluginContext` | `PLUG-080` | Launching and supervising the Flask process; reading its own options |
| Plugin Options page and settings | `PLUG-170`, `PLUG-150` | Port, bind address, allowed-clients list and revocation, session timeout, whether to start with Galileo, TLS certificate source |
| Top-level section | `PLUG-130` | A WebConnect section: address to open, signed-in browsers, lease holders, audit log |
| Event bus, Dashboard timeline model | `galileo.bus`, `OBS-150` | Source of the live state the browser shows |
| Inline help | `HELP-060` | The plugin ships its own help Markdown |

### 6.2 Facilities shared with MobileConnect and NodeConnect (proposed core additions)

| Facility | Defined in | WebConnect's use |
|---|---|---|
| **Connect Link** (pairing with approval and token, scoped permissions, encrypted transport, event stream, resumable binary transfer, version handshake) | [NodeConnect PSD §6.2](../nodeconnect/PSD.md) | The Flask application authenticates to the node with its own paired token and relays on behalf of signed-in browsers |
| **Control Surface** (catalogue of operations and observable state), **control lease**, operation events, server-side previews, held-motion deadman, manual focus in the focus module | [MobileConnect PSD §6.3](../mobileconnect/PSD.md) (C1–C6) | The sole source of operations and state; the browser UI is driven by the catalogue |

### 6.3 Placement and proxying

**One placement: on the Master node.** The plugin starts and supervises a Flask process (under a production server, not Flask's development server) on the Master, alongside Galileo, started and stopped with the plugin. WebConnect is not installed or enabled on spoke nodes; there is no stand-alone or other-machine deployment.

**The Master is the proxy.** For a Pier of the Master itself, the Flask process uses the Master's own Connect Link and Control Surface. For a Pier on a spoke node, the Master relays the browser's request to that node over Connect Link and relays the node's state and events back, so one browser session and one live stream cover the whole installation. The browser sees one address, one sign-in, one lease model and one audit log.

**Trust for proxying.** NodeConnect pairing gives the spoke a token to talk to the Master; operating a spoke from the Master needs the reverse grant. When a node pairs (approved on the Master), the node's own user is additionally asked whether to **allow the Master to operate this node** (`control`/`view` scopes only — never `config.*` — and off unless granted); the grant can be revoked on the node at any time. A node that has not granted it appears in the browser as view-only, or absent if it grants nothing.

**Consequences accepted.**
- A spoke node's operations are unavailable while the Master is down or the spoke is detached (the spoke keeps imaging; only remote operation is affected). The browser shows the node as unreachable.
- The control lease for a spoke's Pier is held on that spoke, so the desktop on the spoke, a MobileConnect client paired to it, and the Master's proxy all contend through one lease.
- Proxy latency is the Master→node latency; previews are rendered on the owning node and relayed, not re-rendered on the Master.

Core's rule against `localhost` in device and PHD2 addresses ([NodeConnect PSD](../nodeconnect/PSD.md) C5) concerns stored equipment addresses; the Flask process reaching its own Master's Connect Link is a managed, plugin-internal link, not a user-entered address, and is unaffected. The SDD confirms this.

## 7. Requirement Domain

One domain, **`WCON`** (WebConnect), specified in a future SRS. Provisional sub-areas:

| Area | Covers |
|---|---|
| Hosting and lifecycle | Flask process start/stop/supervision on the Master, bind address and port, TLS |
| Proxying | Relaying operations, state, events and previews to spoke nodes; the Master-operates-this-node grant; unreachable-node behaviour |
| Pairing, sign-in and roles | Approval on the Master, browser sessions, Viewer / Operator, lease, revocation, session timeout, audit |
| State and events | Pushed live state and alerts, Pier timelines |
| Operations | One screen group per row of MobileConnect §6.4, driven by the Control Surface; session and schedule authoring |
| Images | Server-rendered previews, pan/zoom, optional FITS download |
| Safety and failure behaviour | Interlocks, confirmation, deadman, emergency, reconnect behaviour |
| Web UI (scope level) | Responsive layouts, night theme, browser support matrix, accessibility |
| Options, help and packaging | Options page, in-app help, plugin manifest, dependencies (Flask and its server) |

## 8. Stakeholders and Primary Personas

- **The observatory operator at a computer that isn't the node** — a laptop in the house, a second monitor in the warm room.
- **The user without a mobile app**, or on a platform the apps don't cover.
- **The multi-node operator** who opens one web address on the Master and operates every paired node through it (G8).
- **A guest** (Viewer role) shown the sky in a browser, with no ability to operate anything.

## 9. Project Constraints

| # | Constraint |
|---|---|
| PC1 | Cross-platform (Windows/macOS/Linux, including Raspberry Pi 5-class ARM): the web application must be light enough to run beside imaging on a Pi; previews rendered on demand and cached, state pushed |
| PC2 | All plugin configuration in the shared database (core's firm rule), never a plugin-private file or `QSettings`. Browser-side storage holds only the session cookie and UI preferences |
| PC3 | Network work never runs on the Qt UI thread; the Flask application runs in its own process, so the web workload cannot stall Galileo's UI or the session executor |
| PC4 | Encrypted by default (HTTPS). A self-signed certificate is generated for the node on first use and pinned in the Connect Link pairing; the user may supply their own. There is no plain-HTTP mode except a loopback health check |
| PC5 | Browser hardening is a requirement, not an afterthought: CSRF protection on every state-changing request, strict session cookies, `Content-Security-Policy`, no inline script, rate-limited sign-in, and session expiry. Because the application can move a telescope, an unauthenticated route is a defect |
| PC6 | Imaging continues, unchanged, when the browser closes or the connection drops |
| PC7 | The web application uses the documented wire API ([MobileConnect PC4](../mobileconnect/PSD.md)) and nothing private, so it is also the reference test of that API for other clients |
| PC8 | A defined browser support matrix (current Chrome/Edge, Firefox, Safari on iOS/iPadOS/macOS, Chrome on Android) |
| PC9 | GPL-3.0-or-later, as the other first-party plugins; Flask (BSD-3) and its WSGI/ASGI server dependencies are licence-compatible and are listed in `THIRD_PARTY_NOTICES.md` when the plugin ships |

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | An internet-facing deployment of a web app that can move a telescope | Scope and documentation state LAN/VPN only; PC4/PC5; default bind to the LAN interface, with an explicit setting to widen it; no help offered for exposing it |
| R2 | The two remote front ends (app and browser) diverge in what they offer | One Control Surface catalogue and one operational scope (MobileConnect §6.4); a shared parity test checks each operation in the catalogue is reachable in both |
| R3 | Flask is WSGI, so long-lived push streams and many simultaneous viewers tie up workers | Production server chosen for streaming in the SDD; push by Server-Sent Events from a small number of workers; performance budget checked on a Pi |
| R4 | A session-authoring UI in a browser is a large piece of front-end work | Reuse the block model and validation from the Control Surface; tablet-first design shared in spirit with the mobile apps; authoring can ship after the operating screens |
| R5 | Browser sign-in and CSRF mistakes are the usual way such tools are broken | PC5 as requirements with tests; security review of the web application before release |
| R6 | The Master becomes a single point of access and holds operating rights over spoke nodes | The grant is opt-in per node, limited to `control`/`view`, revocable on the node; the Master's loss never stops a spoke's imaging; every proxied operation is audited on both the Master and the owning node |

## 11. Success Criteria (Scope-Level)

- A browser on another computer, after the node approves it, shows live state for every Pier within seconds, without polling.
- The same night's essentials listed for MobileConnect — connect, find and go to a target, centre by plate solve, focus (manually and automatically), guide, run a session, respond to a flip or safety event, author and run a schedule — can be done entirely in the browser.
- A browser, or a hostile request from it, cannot reach any configuration route; a Viewer cannot issue any operation; a forged or missing CSRF token is rejected.
- With the desktop or a mobile app holding the lease, the browser's mount command is refused with an explanation; Emergency stop still works.
- Closing the tab mid-session does not interrupt the session; a held jog stops within a second of the connection dropping.
- Disabling the plugin leaves no web listener and no running Flask process.

## 12. Glossary

| Term | Meaning |
|---|---|
| **Control Surface** | The proposed core registry of operations and observable state ([MobileConnect PSD](../mobileconnect/PSD.md) C1) |
| **Connect Link** | The proposed shared core transport, pairing and permission facility ([NodeConnect PSD](../nodeconnect/PSD.md) §6.2) |
| **Lease** | The right to issue Pier-affecting operations, one holder per Pier at a time |
| **Viewer / Operator** | The two roles |

## 13. Decisions from Review and Remaining Questions

### 13.1 Decided (review of 2026-10-27)

| # | Decision |
|---|---|
| D1 | **Live updates use Server-Sent Events** for server→browser state; operations are ordinary POSTs. The production server for Flask is chosen in the SDD by measuring on a Pi |
| D2 | **Front end: light JavaScript with server-rendered templates.** A framework such as React is adopted only for a screen where it is warranted (the likely candidate is session/schedule authoring) and is then confined to that screen, built into static files shipped in the plugin ZIP |
| D3 | **Browsers sign in as approved devices**, the same mechanism as MobileConnect; no separate user accounts in v1 |
| D4 | **WebConnect runs on the Master node only and the Master proxies to spoke nodes** (Section 6.3) |
| D5 | **MobileConnect proxies through the Master too**; both front ends share the Master's one relay implementation ([MobileConnect §6.6](../mobileconnect/PSD.md)) |

### 13.2 Remaining

| # | Question | Recommendation |
|---|---|---|
| Q1 | Should WebConnect and MobileConnect be one plugin with two front ends? | Keep two plugins: users want one without the other, each has different dependencies, and `PLUG-060` keeps a disabled plugin fully inert |
