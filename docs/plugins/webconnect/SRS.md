# WebConnect Plugin — SRS (Software Requirements Specification)

| | |
|---|---|
| **Project** | Galileo — WebConnect Plugin (browser control of a Galileo node through a Flask web application) |
| **Document** | SRS (Software Requirements Specification), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-29 |
| **Upstream document** | [PSD (Project Scope Document)](PSD.md) |
| **Downstream documents** | [SDD](SDD.md), [RTM](RTM.md) |
| **Parent project** | [Galileo Core SRS](../../SRS.md) |
| **Sibling plugins** | [MobileConnect](../mobileconnect/SRS.md) — defines the operational surface this plugin reuses; [NodeConnect](../nodeconnect/PSD.md) — defines Connect Link (its §6.2) |
| **Product repository** | [Galileo-WebConnect](https://github.com/gordtulloch/Galileo-WebConnect) holds the Flask application; this SRS is the requirement baseline for it |

---

## 1. Introduction

### 1.1 Purpose

This SRS decomposes the `WCON` requirement domain of [this plugin's PSD](PSD.md) into individually numbered, verifiable requirements, structurally parallel to [Galileo core's SRS](../../SRS.md) and the [MobileConnect SRS](../mobileconnect/SRS.md).

### 1.2 Scope

The `WCON` domain: the plugin that runs on the Master node and the Flask web application it supervises. WebConnect gives a browser **the same operational reach as MobileConnect** and defines **only what differs**: hosting, browser sign-in, the browser security model, the web user interface, the Master relay that both plugins share, and browser outreach. Where an operational behaviour is identical to MobileConnect's, a requirement here says so and cites the `MCON` requirement it matches instead of restating it, so the two cannot drift (PSD risk R2). What the plugin consumes from core (plugin loading, settings, top-level section, event bus, Dashboard timeline model, help) is existing core requirements, cited by ID; what it needs that does not yet exist is listed in Section 2.6 as **prerequisites**.

### 1.3 Requirement ID Convention

`WCON-<###>`, numbered in increments of 10 (a `1` suffix marks a requirement added beside its neighbour, as `WCON-421`). The **Operations** block deliberately reuses MobileConnect's numbers (`WCON-4xx` ↔ `MCON-4xx`) so parity is checkable by eye. Sub-areas occupy fixed blocks:

| Block | Sub-area | Section |
|---|---|---|
| 010–090 | Hosting, packaging and lifecycle | 3.1 |
| 100–190 | Pairing, sign-in, roles, lease and audit | 3.2 |
| 200–250 | Proxying through the Master (the shared relay) | 3.3 |
| 300–360 | State and events | 3.4 |
| 400–590 | Operations (numbers match `MCON-4xx`) | 3.5 |
| 600–650 | Images, previews and the sky view | 3.6 |
| 700–780 | Safety and failure behaviour | 3.7 |
| 800–890 | Web user interface | 3.8 |
| 900–940 | Options, help and wire API | 3.9 |
| 1000–1070 | Web application security | 3.10 |
| 1200–1330 | Browser outreach | 3.11 |

### 1.4 Priority Convention

MVP / P2 / P3, identical to [core SRS Section 1.4](../../SRS.md#14-priority-convention). "MVP" means the nightly essentials of PSD Section 11 (state, connect, go-to, solve, focus, guide, run a session, respond to a flip or safety event) plus the security requirements of Section 3.10 and browser outreach. Session and schedule authoring and the less frequent areas are P2/P3, following MobileConnect's priorities and PSD risk R4.

### 1.5 References

[This plugin's PSD](PSD.md); [MobileConnect SRS](../mobileconnect/SRS.md) (Sections 3.2–3.7, 3.11 — the behaviour this plugin matches) and [SDD](../mobileconnect/SDD.md); [NodeConnect PSD](../nodeconnect/PSD.md) §6.2 (Connect Link L1–L9); [Galileo Core SRS](../../SRS.md), particularly the `PLUG`, `OBS`, `SES`, `SAFE` and `HELP` domains.

---

## 2. Overall Description

### 2.1 Product Perspective

A first-party plugin, distributed as a ZIP from the Galileo Plugins repository and installed through Options > Plugins (`PLUG-090`/`PLUG-110`), independently enabled/disabled (`PLUG-060`), installed on the **Master only**. It has two parts: a plugin component inside Galileo, and one or two **Flask processes** it supervises — the *operating web application* and, only during a browser-enabled outreach event, the *outreach web application*. The Flask processes have no private route into Galileo: they reach it through Connect Link and the Control Surface exactly as the mobile apps do.

### 2.2 Product Functions (Summary)

Register a browser as an approved device (approved on the Master); sign it in; show live state, timelines, images and alerts for every Pier of the Observatory, including spoke nodes' Piers relayed through the Master; let a Viewer watch and an Operator do everything operational (and nothing configurational), under a per-Pier control lease with confirmation, deadman motion and an always-available Emergency stop; author sessions and scheduler jobs; during an owner-opened outreach event, let an unregistered visitor see the live images of the offered Piers on their phone; keep its options in the database.

### 2.3 User Classes and Characteristics

| Class | Description |
|---|---|
| Observatory operator at a computer that is not the node | Holds an **Operator** pairing for a browser on a laptop, desktop or tablet |
| User without a mobile app | Same, on a platform the apps do not cover |
| Multi-node operator | Opens one address on the Master and operates every paired node through it |
| Viewer | An approved browser that sees state and images and issues nothing |
| Outreach visitor | Never registered; scans a QR code with a phone camera, watches the live image of offered Piers in a browser, can do nothing else |
| Outreach host | The owner, who opens and closes the event on the Master |

### 2.4 Operating Environment

Node side: identical to core including Raspberry Pi 5-class ARM; the plugin must run beside imaging on a Pi (PSD PC1). Client side: current Chrome/Edge, Firefox, Safari (iOS, iPadOS, macOS) and Chrome on Android, on the same LAN as the Master or on a VPN the user already runs. No internet relay, tunnel, cloud account or CDN is involved.

### 2.5 Design and Implementation Constraints

Distributed as a ZIP; loaded only through core's plugin extension points; the web application is Flask under a production server, in a process separate from Galileo (PSD PC3); no import of adapter or UI internals; all configuration in the shared database (PSD PC2); HTTPS only (PSD PC4); GPL-3.0-or-later with Flask (BSD-3) and its server dependencies listed in `THIRD_PARTY_NOTICES.md` (PSD PC9); the web application uses only the documented wire API (PSD PC7).

### 2.6 Assumptions and Dependencies

Prerequisites shared with MobileConnect ([MobileConnect SRS §2.6](../mobileconnect/SRS.md)); until each exists in core or NodeConnect the dependent `WCON` requirements cannot be verified, and each is flagged "(needs …)" below. The same reference codes are used.

| Ref | Prerequisite | Specified in |
|---|---|---|
| CL | **Connect Link** L1–L8: encrypted listener, pairing with approval, scopes and audit, discovery, route registration, event stream, chunked transfer, version handshake | Core SRS `LINK-010`–`090`, `240`–`270` |
| CS | **Control Surface**: registry of operations and observable state, with permission class and lease requirement per operation | Core SRS `CSURF-010`–`250` |
| LS | **Control lease** per Pier | Core SRS `LEASE-010`–`080` |
| OE | **Operation results as events** with correlation id | Core SRS `CSURF-070` |
| PV | **Server-side preview rendering** | Core SRS `PREV-010`–`060` |
| DM | **Deadman semantics** for held manual motion | Core SRS `CSURF-400`–`420` |
| MF | **Manual focus owned by the focus module** | Core SRS `FOC-100`–`130` |
| SK | **Sky-data streaming service** | Core SRS `SKYSTR-010`–`080` |
| OF | **Outreach event facility** (Connect Link L9) | NodeConnect PSD §6.2 / core SRS (new) |
| WR | **Master relay**, in core and shared with MobileConnect | Core SRS `LINK-220` (consumed here: Section 3.3) |
| GW | **Request pipeline**, in core and shared with MobileConnect | Core SRS `LINK-230` |
| DG | **Delegated identity**: Connect Link lets a trusted service peer present a request on behalf of an approved client of the same plugin, with the audit log recording the client, not the service | Core SRS `LINK-090` (Section 3.2 note) |

---

## 3. Functional Requirements

### 3.1 Hosting, packaging and lifecycle

| ID | Requirement | Priority |
|---|---|---|
| WCON-010 | The system shall be delivered as a first-party plugin with the manifest identity `WCON`, distributed as a ZIP from the Galileo Plugins repository and installed through `PLUG-090`/`PLUG-110`; it shall not be bundled in the Galileo installer. | MVP |
| WCON-020 | The system shall be enabled only on a Master node. On a node that is a spoke it shall report that WebConnect belongs on the Master, start no process and open no listener. | MVP |
| WCON-030 | While enabled, the system shall run the operating web application as a Flask application under a production WSGI server (never Flask's development server) in a **separate operating-system process** that the plugin starts, supervises and stops with the plugin. A crash of that process shall be detected and the process restarted with back-off, without affecting Galileo, a running session or any device. | MVP |
| WCON-040 | While disabled, the system shall be fully inert (`PLUG-060`): every web process stopped, every listener closed, every browser session ended, no background activity. Re-enabling shall restore approved browsers and options without re-pairing. | MVP |
| WCON-050 | The system shall add a top-level **WebConnect** section (`PLUG-130`) showing the address to open, signed-in browsers (name, browser and platform, role, Piers they hold a lease on, sign-in time), pending pairing requests, recent alerts forwarded, and the audit log (`WCON-190`). | MVP |
| WCON-060 | The system shall bind the operating web application to a configurable address and port, defaulting to the Master's LAN interface and not to all interfaces; binding more widely shall require an explicit setting. | MVP |
| WCON-070 | The system shall serve the operating web application over HTTPS only. It shall generate a self-signed certificate for the Master on first use, pin it in the web process's Connect Link pairing, and accept a user-supplied certificate in its place. There shall be no plain-HTTP mode other than a loopback-only health check. | MVP |
| WCON-080 | The system shall never run network or rendering work on the Qt UI thread, and shall keep serving cost bounded so a Raspberry Pi 5-class Master running a session is not disturbed: previews rendered on demand and cached, state delivered by push with no polling loop, and previews and sky data dropped or delayed before session work is. | MVP |
| WCON-090 | The web processes shall reach Galileo only through Connect Link, authenticated with their own paired credential (needs CL), and shall use only the documented wire API (PSD PC7). They shall import no Galileo adapter, domain or UI internals. A managed link from a web process to its own Master is not a user-entered address and is outside core's rule against `localhost` in stored equipment addresses. | MVP |

### 3.2 Pairing, sign-in, roles, lease and audit

A browser is an *approved device*, as an app is (PSD D3). The web application runs outside Galileo, so the browser's identity is **delegated**: the web process holds one Connect Link credential of its own and presents each request on behalf of the approved browser that made it (needs DG); role, scope, lease, confirmation and audit are enforced on the Master against that browser, never against the web process.

| ID | Requirement | Priority |
|---|---|---|
| WCON-100 | The system shall register a browser only through Connect Link's pairing flow (needs CL, L2): the browser submits a pairing request identifying itself (a name the user types, browser and platform), the request and a short confirmation code are shown on the Master for approval by a person, the browser displays the same code, and a device credential is issued only after approval. There shall be no unauthenticated route and no standing anonymous access, other than the pairing-request page itself and the outreach listener (Section 3.11). | MVP |
| WCON-110 | The system shall assign every approved browser one of two roles, **Viewer** (state, events and images only) or **Operator** (Viewer plus operations). A new pairing shall be Viewer; promotion to Operator shall be a deliberate action on the Master and never in the browser. | MVP |
| WCON-120 | The system shall enforce the role on the Master for every request: a Viewer's operation request is refused with a reason and audited. The browser's hiding of controls is a convenience, not the control. | MVP |
| WCON-130 | The system shall never grant an approved browser the `config.*` scope and shall register no route, in the web application or on the Master, that creates, edits or deletes any item in the configuration list of PSD §5, whatever the browser's role. | MVP |
| WCON-140 | The system shall apply the **control lease** per Pier (needs LS) with the semantics of `MCON-140`: an Operator holds a Pier's lease to issue a Pier-affecting operation; the lease is shared with the desktop and with MobileConnect clients; it is released on request, on sign-out, when the browser's event stream closes, or after a configurable idle time; any number of Viewers may observe. | MVP |
| WCON-150 | When an operation is refused because another party holds the lease, the refusal shall identify the holder and offer the confirmation of `WCON-180` to take it, as `MCON-150`. The displaced holder shall be told. | MVP |
| WCON-160 | The Emergency operations (`WCON-710`) shall not require the lease and shall be permitted to any approved **Operator**. | MVP |
| WCON-170 | The system shall let the user on the Master revoke any approved browser — immediately ending its sessions and open streams and invalidating its device credential — and optionally set a per-browser expiry. A revoked or expired browser shall be refused and shall need a new approval. | MVP |
| WCON-180 | The system shall require confirmation for the destructive or hard-to-reverse operations defined by the Control Surface permission class (at least those listed in `MCON-180`), enforced by a **two-step request** whose confirmation token is single-use, short-lived and bound to the browser, the operation and a hash of its arguments — not only by a dialog in the page. | MVP |
| WCON-190 | The system shall record every request by every browser — browser identity, role, Pier, operation and arguments (secrets elided), time, outcome — in the Connect Link audit log, shown on the plugin page, filterable and retained for a configurable period. Refused requests shall be recorded. | MVP |

### 3.3 Proxying through the Master (the shared relay, WR)

The Master relay is a **core service** (core `LINK-220`, decided 2026-10-30) that MobileConnect also uses (MobileConnect PSD §6.6, SRS `WR`). Its behaviour is identical to `MCON-200`–`240`. The requirements below state what WebConnect requires of it and are verified against the core relay; the relay does not depend on either plugin's front end.

| ID | Requirement | Priority |
|---|---|---|
| WCON-200 | The system shall present to a browser the Piers of the Master and, through it, those of every paired spoke node in one list, over one address, one sign-in, one lease model and one audit log. A browser shall never contact a spoke node directly. | MVP |
| WCON-210 | For a spoke's Pier, the system shall relay operations, state, events and previews over Connect Link (needs CL), forwarding the identity of the approved browser so the spoke can audit it. Previews shall be rendered on the owning node and relayed, not re-rendered on the Master. | MVP |
| WCON-220 | The system shall reach a spoke only if the spoke's user has granted the Master the opt-in right to operate it (`control` and `view` scopes, never `config.*`), revocable on the spoke at any time. A spoke without the grant shall appear view-only, or be absent, and the browser shall be told which. | MVP |
| WCON-230 | The control lease for a spoke's Pier shall be held on that spoke, so its desktop, a MobileConnect client and this plugin contend through one lease. | MVP |
| WCON-240 | When the Master cannot reach a spoke, the system shall show that spoke's Piers as unreachable (with the time last heard from), refuse operations to them with that reason, and resume without re-pairing when it returns. The spoke's own imaging shall be unaffected. Operations relayed to a spoke shall be audited on both the Master and the owning node. | MVP |
| WCON-250 | The relay shall be consumed through the one core interface (`RelayPort`, core `LINK-220`) that MobileConnect and WebConnect both use without knowledge of each other, so that either plugin works with the other absent and neither forks the relay. | MVP |

### 3.4 State and events

| ID | Requirement | Priority |
|---|---|---|
| WCON-300 | On opening the event stream the system shall send the browser a complete snapshot of the state of every Pier it may see, then only changes, so that a newly signed-in browser shows live state for every Pier within a few seconds. | MVP |
| WCON-310 | The system shall deliver state, events and alerts to the browser by **Server-Sent Events** (PSD D1), derived from `galileo.bus` events and the Control Surface's observable state (needs CS). Operations shall be ordinary HTTP requests. The page shall not poll for state. | MVP |
| WCON-320 | The state delivered shall include, for each Pier, what `MCON-320` lists, including the same activity record as the Dashboard timelines (`OBS-150`, `galileo.dashboard_timeline`). | MVP |
| WCON-330 | Long-running operations (slew, solve, autofocus run, session, calibration set, flip) shall be reported as started / progress / finished events carrying a correlation id (needs OE), which the page ties to the request that began them and shows as progress and completion notices. | MVP |
| WCON-340 | The system shall forward the node's alerts to the page while it is open, keep a recent-alerts list available on request, and make an alert conspicuous (visual, and audible if the user enables it). It shall not claim background delivery: no service worker, push subscription or notification while no page is open. | MVP |
| WCON-350 | On reconnection after a drop the system shall resume the event stream from the browser's last event id where the events are still held, and otherwise send a fresh snapshot, so the page never shows stale state as current. State shall carry the Master's timestamp so the page can show its age. | MVP |
| WCON-360 | The system shall deliver the state of a Pier to a browser only if that Pier is among those the plugin's options expose (`WCON-910`) and the browser's role permits viewing. | P2 |

### 3.5 Operations

Every operation is a Control Surface entry (needs CS) invoking the same domain service as the desktop screen, subject to the same checks, limits and safety interlocks. The boundary rule of PSD §6.4 of MobileConnect applies unchanged: an operation that takes effect on the sky or on the night's data is in scope; an edit to a stored definition of the observatory is not. **Each requirement below provides in the browser what the `MCON` requirement of the same number provides in the apps**; the numbers match.

| ID | Requirement | Priority |
|---|---|---|
| WCON-400 | The system shall publish the operations to the page as a catalogue from the Control Surface and drive the page from it. Operations of areas not available shall be reported unavailable by the handshake (`WCON-930`), not fail. | MVP |
| WCON-410 | **Observatory and Pier** — as `MCON-410`: list Observatories and Piers, choose the working Pier, view the Dashboard timelines of every Pier. | MVP |
| WCON-420 | **Devices** — as `MCON-420`: connect and disconnect devices and operate the mount, camera, filter wheel, rotator, dome, flat panel and switches; view weather and safety-monitor state; focuser movement only under Focus (`WCON-470`). | MVP |
| WCON-421 | After a mount connects through an operation of this plugin, the same date/time and site latitude/longitude synchronisation shall occur as when connecting at the desktop. | MVP |
| WCON-430 | **Imaging** — as `MCON-430`: live exposure loop, single and series captures, current-frame preview with stretch, histogram, statistics and star metrics, live stack, reject frames. | MVP |
| WCON-440 | **Sky and framing** — as `MCON-440`: sky view with the mount's position, target search and selection, go-to, Framing Assistant, current-object details, Planning and visibility lists, Telescopius and AAVSO targets. | MVP |
| WCON-450 | **Plate solving and alignment** — as `MCON-450`. | MVP |
| WCON-460 | **Guiding** — as `MCON-460`, including the error trace and guide-star cut-out. | MVP |
| WCON-470 | **Focus** — as `MCON-470`: manual focus (relative, absolute, halt, position and temperature) and autofocus (start, cancel, V-curve, result, temperature-compensation state) presented as one place; manual focus invoked through the focus module (needs MF), never a generic focuser operation. | MVP |
| WCON-480 | **Meridian flip** — as `MCON-480`; a trigger is a confirmed operation (`WCON-180`). | MVP |
| WCON-490 | **Sessions, run** — as `MCON-490`: list, load, run, pause, resume, skip and stop, with progress block by block. | MVP |
| WCON-500 | **Sessions, authoring** — as `MCON-500`: add, remove, reorder and nest instruction, condition and trigger blocks, set parameters and save, using the Sessions model of the desktop, with plugin-registered blocks (`SES-340`) in the palette; `.gses` import and export through the browser's file chooser and download. | P2 |
| WCON-510 | **Scheduler** — as `MCON-510`. | P2 |
| WCON-520 | **Calibration** — as `MCON-520`. | P2 |
| WCON-530 | **Safety** — as `MCON-530`: every safety input, overall state and stop reason; an Operator may acknowledge only, and resuming remains the decision of the core safety service. | MVP |
| WCON-540 | **Library and history** — as `MCON-540`: recent sessions and frames, quality metrics, history and charts; explicit FITS download under `WCON-620`. | P2 |
| WCON-550 | **Notifications** — as `MCON-550`: recent alerts visible; channels and rules are configuration and not exposed. | P2 |
| WCON-560 | **Plugin surfaces** — as `MCON-560`: a plugin's registered remote surface is listed and operated from the catalogue, rendered by a generic form view. | P3 |
| WCON-570 | **Per-run parameters** — as `MCON-570`: per-run parameters are accepted; any request on any route that would alter a stored definition listed as configuration is refused. | MVP |
| WCON-580 | The system shall validate every operation's arguments on the Master against the Control Surface's declared types and ranges and return a typed error (refused, invalid, unavailable, busy, unreachable) rather than an exception. A browser-side check is a convenience only. | MVP |
| WCON-590 | **Parity.** An automated check shall confirm that every operation in the Control Surface catalogue that MobileConnect exposes is reachable from the web page, or is listed with a stated reason as unavailable in the browser, and fail the build otherwise (PSD R2). | MVP |

### 3.6 Images, previews and the sky view

| ID | Requirement | Priority |
|---|---|---|
| WCON-600 | The system shall deliver images as server-rendered previews (needs PV): stretched and scaled to a size the page requests, JPEG-encoded, for the current exposure, any Library frame and any guide or focus cut-out. FITS shall not be sent unless requested under `WCON-620`; no FITS processing shall run in the browser. | MVP |
| WCON-610 | The system shall offer a preview as tiles of a pyramid for pan and zoom, with a bounded server-side cache so repeated requests do not re-render. | P2 |
| WCON-620 | The system shall allow an Operator to download a full FITS frame as an explicit action, with its size reported beforehand. A Viewer shall not be able to download FITS. | P3 |
| WCON-630 | The system shall expose preview quality and maximum size as options (`WCON-910`), let the page request a lower quality, and give session work priority over preview rendering. | P2 |
| WCON-640 | The page shall let the user hold the tiles of two frames at once for blink and side-by-side comparison, as `MCON-670`. | P2 |
| WCON-650 | The page shall present the sky view from sky data held by the Master (needs SK; `MCON-640`, `MCON-660`): the browser shall ship no catalog and compute no ephemeris. **Delivery order (decided 2026-10-30):** the first release presents a **server-rendered static sky image** (with the mount position, field of view and horizon, refreshed on demand and on a slew); the interactive in-browser canvas rendering from streamed sky data follows the operating screens and is **P2**, not required for the first release. On a Master that cannot meet the streaming load it shall report the sky view as reduced or unavailable with a reason, never attempt it, and leave the rest of the page working. | MVP |

### 3.7 Safety and failure behaviour

| ID | Requirement | Priority |
|---|---|---|
| WCON-700 | Every operation shall pass through the same core services and safety interlocks as the desktop UI. The system shall not disable the safety monitor, clear an unsafe state or override a mount limit, and shall provide no route that does. | MVP |
| WCON-710 | The system shall provide Emergency operations — **Stop everything**, **Park**, **Close dome** — callable by any approved Operator without the lease, present on every page, confirmed in the page by a deliberate gesture, succeeding in a single request once confirmed, and audited. | MVP |
| WCON-720 | Imaging shall continue, unchanged, when the browser tab is closed, the browser sleeps or the connection is lost; the node shall neither require a browser to remain connected nor stop a session when one disconnects. The sole exception is held motion (`WCON-730`). | MVP |
| WCON-730 | A manual slew or jog and a focuser move started from the browser shall run only while a keep-alive arrives from a pressed control (needs DM). They shall stop within one second of the control being released, the page losing focus or visibility, the page unloading, the keep-alive stopping, the event stream or connection dropping, or the lease being taken. | MVP |
| WCON-740 | An operation shall carry a client-generated idempotency key, and a retried request with the same key shall return the original result rather than repeat the operation, as `MCON-740`. | MVP |
| WCON-750 | Where a command is refused because the lease is held elsewhere, the Pier is unsafe, the device is busy or unconnected, or the target is unreachable, the system shall say so with a reason the page can display, never silently ignore or queue it. | MVP |
| WCON-760 | A lease shall not outlive its holder: on sign-out, session expiry, event-stream close or idle timeout it is released and the desktop and other clients are told. | MVP |
| WCON-770 | A flood of requests from one browser or source shall be rate-limited without affecting other clients, imaging or the Emergency operations. | P2 |
| WCON-780 | While the event stream is down, the page shall mark all state as stale and disable Pier-affecting operations other than the Emergency operations, which shall remain attemptable, until the stream is restored. | MVP |

### 3.8 Web user interface

| ID | Requirement | Priority |
|---|---|---|
| WCON-800 | The web application shall be built from server-rendered templates with light JavaScript (PSD D2). A JavaScript framework may be used only for a screen where it is warranted (session and schedule authoring) and confined to that screen, built into static files shipped in the plugin ZIP. Every script, style, font and image the page uses shall be served by the web application itself; nothing is fetched from a third party. | MVP |
| WCON-810 | The interface shall be responsive and **tablet-first**: the large layout shows the sky view, image and session list side by side; narrower layouts reduce secondary panels progressively down to a phone; it shall be usable by touch and by mouse and keyboard. | MVP |
| WCON-820 | The interface shall provide a screen or section for each operational area of Section 3.5, driven by the catalogue; an area the node does not offer shall be hidden or shown unavailable, never broken. | MVP |
| WCON-830 | The interface shall guide a new browser through pairing (Section 3.2): request, display of the confirmation code, waiting for approval on the Master with a clear refused/expired outcome, and then sign-in. | MVP |
| WCON-840 | The interface shall show at all times the browser's role, the lease state of the selected Pier and who holds it, the connection state, and the age of the state shown. | MVP |
| WCON-850 | The interface shall hide operations a Viewer cannot perform, shall present the confirmation of `WCON-180` for confirmed operations, and shall show the Emergency operations (`WCON-710`) on every page. | MVP |
| WCON-860 | The interface shall provide a night-vision (red) theme that emits no non-red light — including form controls, scrollbars, dialogs, the loading state and the favicon — and shall remember the choice as a browser-side UI preference. | MVP |
| WCON-870 | The interface shall be operable by keyboard and expose roles, names and live regions to assistive technology for its non-imaging controls, targeting WCAG 2.1 level AA. | P2 |
| WCON-880 | The interface shall be tested against the browser support matrix of PSD PC8 (current Chrome and Edge, Firefox, Safari on iOS, iPadOS and macOS, Chrome on Android). A browser outside the matrix that lacks a required feature shall be told so, not shown a broken page. | MVP |
| WCON-890 | The interface shall provide help for each screen, and an About view showing the Galileo, plugin and protocol versions and the browser's own pairing details. | P2 |

### 3.9 Options, help and wire API

| ID | Requirement | Priority |
|---|---|---|
| WCON-900 | The system shall add a **WebConnect** page under Options (`PLUG-170`) in which a Master user manages approved browsers (list, role, revoke, expiry) and pending approvals. | MVP |
| WCON-910 | The system shall provide, and persist in Galileo's database under the plugin's namespace (`PLUG-150`), these options: bind address and port, whether to start with Galileo, TLS certificate source, which Piers are exposed, session idle and absolute timeouts, lease idle timeout, audit retention, and preview quality and maximum size. Values shall be validated and clamped. The system shall write no plugin-private file, use no `QSettings`, and keep in the browser only the session cookies and UI preferences. | MVP |
| WCON-920 | The system shall describe its browser-facing API in a published, language-neutral form (OpenAPI for requests, a schema for the event stream), versioned `/webconnect/v1/...`, generated from the types the server validates against so it cannot drift. The web application's calls into Galileo shall use only the documented Connect Link and MobileConnect-defined wire API, which makes it also the reference test of that API (PSD PC7). | MVP |
| WCON-930 | The system shall perform the Connect Link version handshake (L8) when its web process starts and on reconnection, refuse to operate against an incompatible Galileo with a message naming the versions, and report operation areas available (`WCON-400`). | MVP |
| WCON-940 | The system shall ship help Markdown for every control on its plugin page and Options page (`HELP-060`), registered through the plugin help mechanism, and shall pass the help audit. | MVP |

### 3.10 Web application security

Because the application can move a telescope, an unauthenticated or forgeable route is a defect (PSD PC5).

| ID | Requirement | Priority |
|---|---|---|
| WCON-1000 | Every state-changing request (any method other than GET, HEAD, OPTIONS) shall be rejected unless it carries a valid CSRF token bound to the session and comes from the application's own origin. A missing, forged or replayed token shall be refused and counted. | MVP |
| WCON-1010 | Session and device cookies shall be `HttpOnly`, `Secure` and `SameSite=Strict`, host-bound (`__Host-` prefix), and a session identifier shall be regenerated at sign-in, on role change and at sign-out. | MVP |
| WCON-1020 | Every response shall carry a strict `Content-Security-Policy` that permits no inline script, no inline event handler and no third-party origin, and also `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and a frame-embedding denial. State and image responses shall be `Cache-Control: no-store`. | MVP |
| WCON-1030 | Sign-in, pairing requests and any other unauthenticated entry point shall be rate-limited per source, with an increasing delay on repeated failure. | MVP |
| WCON-1040 | A session shall expire after configurable idle and absolute timeouts, after which the page shall require a new sign-in. The browser shall hold no operational state beyond the page, and the application shall register no service worker and no offline cache. | MVP |
| WCON-1050 | Every route shall require an authenticated session, a role check and (for state-changing routes) a CSRF check, except those named in a single explicit public-route list. A test shall enumerate every registered route and fail if one is neither authenticated nor on that list. | MVP |
| WCON-1060 | The application shall reject a request whose `Host` or `Origin` is not one of the addresses it is configured to serve, as a defence against DNS rebinding and cross-origin use. | MVP |
| WCON-1070 | The web application shall undergo a documented security review (CSRF, session handling, header policy, route enumeration, dependency audit) before each release that changes it, with its findings resolved or recorded. | P2 |

### 3.11 Browser outreach

Browser outreach is the web counterpart of [MobileConnect outreach](../mobileconnect/SRS.md#311-outreach-mode-unregistered-image-viewers) and is **the same event with the same rules**. The event — its lifecycle and timer, per-event secret, source-subnet confinement, guest tokens and `outreach.view` scope, caps, aggregate audit, guest previews, and event display — is hosted in core by Connect Link's outreach facility (needs OF, L9). Requirements marked (needs OF) state what this plugin relies on and verifies through its browser surface; `WCON-1210`–`1260`, `1290` and `1300` are the browser surface's own. A guest is not a role under `WCON-110`; none of Section 3.2 applies to a guest except where stated.

| ID | Requirement | Priority |
|---|---|---|
| WCON-1200 | (needs OF) The owner shall choose, on Connect Link's Outreach page, whether an event is offered to apps, to browsers or to both. With browsers off, the outreach web application shall not start and nothing browser-related shall listen. While no event is open nothing outreach-related shall answer. | MVP |
| WCON-1210 | The system shall serve browser outreach from a **separate, minimal Flask application** with its own process and listener, **bound to the outreach network's address** and port and started only while a browser-enabled event is open and stopped when it ends. It shall serve the outreach page, its static assets and the guest routes of `WCON-1250` and nothing else. | MVP |
| WCON-1220 | The operating web application shall not be reachable on the outreach listener, and shall itself refuse any request whose source address lies in a configured outreach subnet. | MVP |
| WCON-1230 | (needs OF) The event display shall include a **web QR code** encoding an HTTPS address of the outreach page with the event identifier and secret in the URL **fragment** (`https://<host>:<port>/outreach#e=<event>&s=<secret>`), and the address as short text to type. The fragment shall not be sent to any server, so the secret appears in no server log, proxy log or `Referer`. | MVP |
| WCON-1240 | The outreach page shall read the fragment, exchange the secret for a guest token by a single enrolment request, remove the fragment from the address bar and history, and hold the token only in a `HttpOnly`, `Secure`, `SameSite=Strict`, host-bound cookie that expires when the event ends. There shall be no name, account, sign-in form or per-device approval. Ending the event, ejecting guests or re-issuing the secret shall end the session. | MVP |
| WCON-1250 | A guest token (`outreach.view` and nothing else) shall permit exactly: listing the Piers offered (display names only), receiving the live image of an offered Pier, and switching between offered Piers. Every other route — operations, state, timelines, alerts, Library, history, FITS, sky data, previews of arbitrary frames, leases and configuration — shall refuse a guest, and each refusal shall be counted. The guest routes shall be an allowlist. | MVP |
| WCON-1260 | The system shall push to each visitor the **live image of the chosen Pier as each frame completes**, by Server-Sent Events, with the image's age; a visitor who joins or switches Pier shall receive the latest image at once; a Pier going unavailable or the event ending shall be reported to the page, not left blank. The page shall show nothing else. | MVP |
| WCON-1270 | (needs OF) Images sent to visitors shall be the facility's guest previews: limited to the guest size and quality, and carrying no FITS header, EXIF, GPS or other embedded metadata. | MVP |
| WCON-1280 | The outreach application shall be hardened for the public: a strict `Content-Security-Policy` with no inline script and no third-party resource of any kind (the outreach network may have no internet), `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on images, no service worker, rate-limited enrolment, the concurrent-guest cap and guest load rules of `MCON-1280` (needs OF), and an access log that records neither cookies nor secrets. | MVP |
| WCON-1290 | The outreach listener shall serve HTTPS only, using a certificate the owner supplies for a stable name on the outreach network. The system shall refuse to open a browser-enabled event without one and shall offer no plain-HTTP mode. The operating web application keeps its own certificate (`WCON-070`). | MVP |
| WCON-1300 | The outreach page shall be designed for a phone held by a visitor: usable on any current browser, dark and dim by default, with a red-light toggle, and nothing to install. | MVP |
| WCON-1310 | (needs OF) The system shall confine outreach enrolment and guest requests to source addresses inside the outreach subnet(s), checking the source on the outreach listener as well as in the facility, and shall refuse everything else without revealing the node's identity. If no subnet is configured, or the outreach certificate is missing, a browser-enabled event shall not open. | MVP |
| WCON-1320 | The system shall provide, and persist in Galileo's database (`PLUG-150`), these browser-outreach options: the outreach listener address and port, the outreach hostname, the certificate source (its private key held as a secret, never logged or audited), and whether events are offered to browsers by default. Values shall be validated and clamped. The SSID, subnets, duration, guest cap, preview limits and offered Piers are Connect Link's shared outreach options (`MCON-1310`) and shall not be duplicated. | MVP |
| WCON-1330 | (needs OF) The system shall contribute to the facility's aggregate audit the number of browser guests per Pier, and shall retain no personal data about visitors: a guest is a random token and a source address held only for the event's duration. | P2 |

---

## 4. Non-Functional Requirements

Cross-cutting qualities are verified through the requirements above and the core `NFR` requirements, listed here for traceability only:

| Quality | Source | Requirement |
|---|---|---|
| Light enough for a Raspberry Pi 5 beside imaging | PSD PC1 | `WCON-080`, `WCON-030`; performance budget measured on a Pi (SDD P2) |
| Config in database | PSD PC2 | `WCON-910`, `WCON-1320` |
| UI-thread discipline; web workload cannot stall Galileo | PSD PC3 | `WCON-030`, `WCON-080` |
| Encrypted by default | PSD PC4 | `WCON-070`, `WCON-1290` |
| Browser hardening | PSD PC5 | Section 3.10, `WCON-1280` |
| Imaging unaffected by the browser | PSD PC6 | `WCON-030`, `WCON-720` |
| Documented API only | PSD PC7 | `WCON-090`, `WCON-920` |
| Browser matrix | PSD PC8 | `WCON-880` |
| Licensing | PSD PC9 | Flask and server dependencies listed in `THIRD_PARTY_NOTICES.md` when the plugin ships |
| Portability | Core `NFR-PORT-010` | The plugin uses `galileo.platform` for any paths and has no OS-specific code; the chosen server runs on Windows, macOS, Linux and Raspberry Pi OS |

---

## 5. Requirement Summary Counts (for RTM Seeding)

| Sub-area | Count | MVP | P2 | P3 |
|---|---|---|---|---|
| Hosting, packaging and lifecycle (010–090) | 9 | 9 | 0 | 0 |
| Pairing, sign-in, roles, lease and audit (100–190) | 10 | 10 | 0 | 0 |
| Proxying (200–250) | 6 | 6 | 0 | 0 |
| State and events (300–360) | 7 | 6 | 1 | 0 |
| Operations (400–590) | 21 | 15 | 5 | 1 |
| Images, previews and the sky view (600–650) | 6 | 2 | 3 | 1 |
| Safety and failure behaviour (700–780) | 9 | 8 | 1 | 0 |
| Web user interface (800–890) | 10 | 8 | 2 | 0 |
| Options, help and wire API (900–940) | 5 | 5 | 0 | 0 |
| Web application security (1000–1070) | 8 | 7 | 1 | 0 |
| Browser outreach (1200–1330) | 14 | 13 | 1 | 0 |
| **Total** | **105** | **89** | **14** | **2** |

---

## 6. Open Points for Review

| # | Point | Where |
|---|---|---|
| O1 | The core prerequisites (Control Surface, lease, operation events, preview, deadman, manual focus, sky streaming) and Connect Link L1–L9 are not yet in the core or NodeConnect SRS. Every "(needs …)" requirement is reserved but unverifiable until they exist; the plugin is developed against stubs. **Update 2026-10-30: all are now specified in the core SRS (`LINK`, `CSURF`, `LEASE`, `PREV`, `SKYSTR`, `FOC-100`–`130`) and designed at component level in core SDD §4.28–4.32; none is built.** | §2.6 |
| O2 | **Delegated identity (DG) — decided: delegation.** Because the web application is a separate process, it presents requests on behalf of an approved browser; Connect Link supports a service peer acting for a named client, with the audit log recording the client (core `LINK-090`). The per-browser-peer alternative is not pursued. | §3.2, SDD P3 |
| O3 | **Sign-in without accounts.** With device approval as the only identity (PSD D3), "session expiry" (`WCON-1040`) ends a session but a valid device credential can start another with one click, so expiry limits cookie lifetime rather than guarding against someone at an unattended approved browser. Options: accept; require a per-device PIN set at approval; or require re-approval after a longer period (the per-browser expiry of `WCON-170`). Recommendation: accept for v1 and offer the per-browser expiry. **Decided 2026-10-30: accept for MVP; PIN later.** | `WCON-1040` |
| O4 | **Shared pipeline.** The request pipeline (identify, authorise, validate, lease, confirm, idempotency, dispatch, audit), confirmation tokens, idempotency store and load governor are the same in MobileConnect and WebConnect. `WCON-250` shares the relay; the pipeline should be shared the same way, as a core or shared package, rather than copied (SDD P1). | `WCON-120`, `180`, `740` |
| O5 | **Pairing code display.** `WCON-100` adds a short confirmation code shown on both the Master and the browser to defeat approving the wrong request; MobileConnect's SRS does not state this explicitly. Confirm it is wanted for both plugins. **Decided 2026-10-30: wanted for both plugins; MobileConnect adopts it.** | `WCON-100` |
| O6 | **Production server.** PSD D1 leaves the choice to a measurement on a Pi. The SDD proposes gevent's WSGI server provisionally (ADR-WCON-004) and a spike to confirm before MVP. | `WCON-030` |
| O7 | **Held-motion keep-alive transport.** SSE is server-to-browser only, so keep-alives travel as small HTTP requests (SDD P4); the 250 ms beat / 600 ms deadman timings carry over from MobileConnect and need measuring over browser Wi-Fi. | `WCON-730` |
| O8 | **Source address of outreach guests.** The facility's subnet guard must be told the visitor's address by the trusted outreach application, since the facility never sees the visitor's connection. The facility (OF) must accept an asserted source from a registered surface; WebConnect checks it too (`WCON-1310`). | `WCON-1310` |
| O9 | **Plain HTTP on the outreach listener.** PSD Q2 recommended an off-by-default option; PSD decision D9 settled on HTTPS only. This SRS follows D9 (`WCON-1290`). | `WCON-1290` |
| O10 | **Sky view rendering in the browser** (`WCON-650`) is a substantial front-end piece that the PSD does not explicitly mention; it follows from `MCON-440` and the "no catalog in the client" rule. Confirm it is wanted at MVP rather than a static server-rendered sky image first. **Decided 2026-10-30: static server-rendered sky image first; canvas view after MVP.** | `WCON-650` |
| O11 | A showcase image set for outreach, offered in addition to the live image (MobileConnect PSD Q4), is undecided and not specified here. **Decided 2026-10-30: deferred to P2 (see MobileConnect SRS O13).** | §3.11 |

---

## 7. Path to SDD / Traceability Matrix

1. **Core, NodeConnect and MobileConnect** — the prerequisites of Section 2.6.
2. **SDD** — [SDD.md](SDD.md), how the plugin's modules satisfy the requirements above.
3. **Traceability Matrix** — [RTM.md](RTM.md), a row per requirement ID here, mapped to its SDD component and a `TC-WCON-*` test case ID.

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SRS](../../SRS.md).*
