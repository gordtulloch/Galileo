# MobileConnect Plugin — SRS (Software Requirements Specification)

| | |
|---|---|
| **Project** | Galileo — MobileConnect Plugin (iOS/Android remote control of a Galileo node) |
| **Document** | SRS (Software Requirements Specification), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-29 |
| **Upstream document** | [PSD (Project Scope Document)](PSD.md) |
| **Downstream documents** | SDD, RTM — not yet written; to follow this SRS's approval |
| **Parent project** | [Galileo Core SRS](../../SRS.md) |
| **Sibling plugins** | [NodeConnect](../nodeconnect/PSD.md) (defines Connect Link, its §6.2); [WebConnect](../webconnect/PSD.md) (same control surface from a browser) |
| **Client apps** | The iOS/iPadOS and Android apps are specified at scope level here (Section 3.7) and in detail in the [Galileo-MobileConnect](https://github.com/gordtulloch/Galileo-MobileConnect) repository |

---

## 1. Introduction

### 1.1 Purpose

This SRS decomposes the `MCON` requirement domain of [this plugin's PSD](PSD.md) into individually numbered, verifiable requirements, structurally parallel to [Galileo core's SRS](../../SRS.md) and the other plugins' SRS documents.

### 1.2 Scope

The `MCON` domain: the **plugin** that runs on the Master node, and — at requirement level only — the **mobile apps** that are its counterpart. What the plugin consumes from core (plugin loading, settings, top-level section, event bus, safety, Dashboard timeline model, help) is existing core requirements, cited by ID. What it needs from core that does not yet exist (Control Surface, control lease, operation-result events, preview rendering, manual focus in the focus module, deadman motion, sky-data streaming) and from NodeConnect (Connect Link) is listed in Section 2.6 as **prerequisites**; those are specified in the core SRS and the NodeConnect SRS, not here.

### 1.3 Requirement ID Convention

`MCON-<###>`, numbered in increments of 10. Sub-areas occupy fixed blocks so that later additions stay grouped:

| Block | Sub-area | Section |
|---|---|---|
| 010–090 | Packaging, lifecycle and placement | 3.1 |
| 100–190 | Pairing, roles, lease and audit | 3.2 |
| 200–240 | Proxying through the Master | 3.3 |
| 300–360 | State and events | 3.4 |
| 400–590 | Operations (one decade per area of PSD §6.4) | 3.5 |
| 600–640 | Images and previews | 3.6 |
| 700–790 | Safety and failure behaviour | 3.7 |
| 800–890 | Mobile apps (scope level) | 3.8 |
| 900–940 | Options, help and wire API | 3.9 |

### 1.4 Priority Convention

MVP / P2 / P3, identical to [core SRS Section 1.4](../../SRS.md#14-priority-convention). "MVP" for this plugin means the nightly essentials of PSD Section 11 (state, connect, go-to, solve, focus, guide, run a session, respond to a flip or safety event); authoring and the less frequent areas are P2/P3, per PSD risk R7.

### 1.5 References

[This plugin's PSD](PSD.md); [Galileo Core SRS](../../SRS.md), particularly the `PLUG`, `OBS`, `SES`, `SAFE` and `HELP` domains; [NodeConnect PSD](../nodeconnect/PSD.md) §6.2 (Connect Link L1–L8); [WebConnect PSD](../webconnect/PSD.md) §6.3.

---

## 2. Overall Description

### 2.1 Product Perspective

A first-party plugin, distributed as a ZIP from the Galileo Plugins repository and installed through Options > Plugins (`PLUG-090`/`PLUG-110`), independently enabled/disabled (`PLUG-060`), and installed on the **Master only**. It is a second front end to the same domain services as the desktop UI, reached through the core Control Surface and carried over Connect Link. It has no transport, authentication or discovery of its own.

### 2.2 Product Functions (Summary)

Pair a tablet, phone or Meta Quest headset with the Master (approved on the Master); show live state, timelines, images and alerts for every Pier of the Observatory, including spoke nodes' Piers relayed through the Master; let a Viewer watch and an Operator do everything operational (and nothing configurational), under a per-Pier control lease with confirmation, deadman motion and an always-available Emergency stop; author and edit sessions and scheduler jobs; keep its options in the database.

### 2.3 User Classes and Characteristics

| Class | Description |
|---|---|
| Observatory Operator | The backyard or remote-site imager; holds an **Operator** pairing |
| Multi-Pier operator | Runs several Piers; needs the whole-Observatory overview |
| Viewer | A guest or family member; sees state and images, issues nothing |
| Outreach host / visitor | The host opens an outreach event on the Master; a visitor, never registered, watches the live image of offered Piers on their own phone or tablet and can do nothing else (PSD Section 6.8) |
| Headset user | An Operator (or Viewer) using a Meta Quest 2/3 as a client fully equal to a tablet; works seated and indoors (PSD Section 6.7) |

### 2.4 Operating Environment

Node side: identical to core, including Raspberry Pi 5-class ARM, except that sky streaming for Meta Quest headsets (`MCON-640`, `MCON-680`) needs a PC/Mac-class Master. Client side: iPadOS/iOS and Android tablets and phones, and Meta Quest 2/3 headsets (Quest 2 the acceptance device), on the same LAN as the Master or on a VPN the user already runs. No internet relay, cloud account or push service is involved.

### 2.5 Design and Implementation Constraints

Distributed as a ZIP; loaded only through core's plugin extension points; no import of adapter or UI internals; no network I/O on the Qt UI thread (PSD PC3); all configuration in the shared database (PSD PC2); GPL-3.0-or-later plugin, proprietary free app, open documented wire API (PSD PC8); native Swift/SwiftUI and Kotlin/Jetpack Compose clients with shared non-UI layers (PSD PC9).

### 2.6 Assumptions and Dependencies

The following are **prerequisites** accepted by PSD decision D8. Until each exists in core or NodeConnect, the `MCON` requirements that depend on it cannot be verified; each is flagged "(needs …)" in the tables below.

| Ref | Prerequisite | Specified in | PSD |
|---|---|---|---|
| CL | **Connect Link** L1–L8: encrypted listener, pairing with approval, scopes, discovery, route registration, event stream, chunked binary transfer, version handshake | NodeConnect SRS | G4, §6.2 |
| CS | **Control Surface**: registry of operator-level operations and observable state, with permission class and lease requirement per operation | Core SRS (new) | C1 |
| LS | **Control lease** per Pier, shared by desktop and remote clients | Core SRS (new) | C2 |
| OE | **Operation results as events** with correlation id (started / progress / finished) | Core SRS (new) | C3 |
| PV | **Server-side preview rendering** (stretch, bin, JPEG, tiles) | Core SRS (new) | C4 |
| DM | **Deadman semantics** for held manual motion | Core SRS (new) | C5 |
| MF | **Manual focus owned by the focus module**, consumed by the desktop focus screen | Core SRS (new) | C6 |
| SK | **Sky-data streaming service** | Core SRS (new) | C7 |
| WR | **Master relay** shared with WebConnect | WebConnect SRS | G10, §6.6 |
| OF | **Outreach event facility** (Connect Link L9): event lifecycle and timer, per-event secret, subnet guard, guest tokens, caps, aggregate audit, guest previews, event display and QR codes | NodeConnect PSD §6.2 / core SRS (new) | D21 |

---

## 3. Functional Requirements

### 3.1 Packaging, lifecycle and placement

| ID | Requirement | Priority |
|---|---|---|
| MCON-010 | The system shall be delivered as a first-party plugin with the manifest identity `MCON`, distributed as a ZIP from the Galileo Plugins repository and installed through `PLUG-090`/`PLUG-110`; it shall not be bundled in the Galileo installer. | MVP |
| MCON-020 | The system shall be installable and enabled only on a Master node. On a node that is a spoke it shall report that MobileConnect belongs on the Master and shall register no route. | MVP |
| MCON-030 | While enabled, the system shall register its versioned routes and event topics with Connect Link (needs CL) and obtain the specific core services it operates through `PluginContext` (`PLUG-080`). It shall not open a listener, port or transport of its own. | MVP |
| MCON-040 | While disabled, the system shall be fully inert (`PLUG-060`): every MobileConnect route is unregistered, every connected app is disconnected, and no background activity runs. Re-enabling shall restore pairings and options without re-pairing. | MVP |
| MCON-050 | The system shall add a top-level **MobileConnect** section (`PLUG-130`) showing connected clients (name, platform, role, Piers they hold a lease on, connect time), pending pairing requests, recent alerts forwarded, and the audit log (`MCON-190`). | MVP |
| MCON-060 | A fault in the plugin or in any client session (malformed request, abrupt disconnect, a crash in a handler) shall be isolated: it shall not interrupt a running session, a device, or any other client, and shall be logged. | MVP |
| MCON-070 | The system shall never run network or rendering work on the Qt UI thread; operations shall be dispatched to the executors the desktop UI uses for the same operation. | MVP |
| MCON-080 | The system shall keep serving cost bounded so a Raspberry Pi 5-class Master running a session is not disturbed: previews rendered on demand and cached, state delivered by event push with no polling loop, and previews and sky data dropped or delayed before session work is. | MVP |

### 3.2 Pairing, roles, lease and audit

| ID | Requirement | Priority |
|---|---|---|
| MCON-100 | The system shall accept a pairing request from an app only through Connect Link's pairing flow (needs CL, L2): the request identifies the client (name, platform, app version), is shown on the Master for approval by a person, and a credential is issued only after approval. There shall be no unauthenticated route, no standing anonymous viewing and no guest link, with the single exception of outreach mode (Section 3.11), which is owner-opened, time-limited, confined to a designated network and authenticated by a per-event secret. | MVP |
| MCON-110 | The system shall assign every paired client one of two roles, **Viewer** (state, events and images only) or **Operator** (Viewer plus operations). A new pairing shall be Viewer; promotion to Operator shall be a deliberate action on the Master and never on the client. | MVP |
| MCON-120 | The system shall enforce the role on the Master for every request: a Viewer's operation request is refused with a reason and audited; the app's own hiding of controls is a convenience, not the control. | MVP |
| MCON-130 | The system shall never grant a paired client the `config.*` scope (Connect Link L3) and shall register no route that creates, edits or deletes any item in the configuration list of PSD §5 / §6.4, whatever the client's role. | MVP |
| MCON-140 | The system shall provide a **control lease** per Pier (needs LS). An Operator shall hold a Pier's lease to issue a Pier-affecting operation. The lease shall be granted if free; offered by confirmation if held by the desktop or another client; and released on request, on disconnect, or after a configurable idle time. Any number of Viewers may observe a Pier whatever the lease state. | MVP |
| MCON-150 | When an operation is refused because another party holds the lease, the refusal shall identify the holder (desktop, or client name) and shall offer the confirmation of `MCON-140` to take it. The holder shall be told when the lease is taken from them. | MVP |
| MCON-160 | The Emergency operations (`MCON-710`) shall not require the lease and shall be permitted to any paired **Operator**. | MVP |
| MCON-170 | The system shall let the user on the Master revoke any paired client, immediately and permanently dropping its connection and credential, and optionally set a per-client expiry. A revoked or expired client shall be refused, and shall need a new approval to pair again. | MVP |
| MCON-180 | The system shall require confirmation for operations that are destructive or hard to reverse, defined by the Control Surface permission class: at minimum aborting an exposure series, stopping a session, park, unpark when a dome is present, run a meridian flip, delete a session or job, and taking a lease from another holder. The confirmation shall be enforced by a two-step request, not only by the app's dialog. | MVP |
| MCON-190 | The system shall record every request by every client — client, role, Pier, operation and arguments (secrets elided), time, outcome — in an audit log stored in the database, shown on the plugin page, filterable, and retained for a configurable period. Refused requests shall be recorded. | MVP |

### 3.3 Proxying through the Master

| ID | Requirement | Priority |
|---|---|---|
| MCON-200 | The system shall present to a client the Piers of the Master and, through it, those of every paired spoke node in one list, over one connection, one pairing, one lease model and one audit log. The client shall never contact a spoke directly. | MVP |
| MCON-210 | For a spoke's Pier, the system shall relay operations, state, events and previews over Connect Link (needs WR), sharing the relay implementation with WebConnect. Previews shall be rendered on the owning node, not re-rendered on the Master. | MVP |
| MCON-220 | The system shall reach a spoke only if the spoke's user has granted the Master the opt-in right to operate it (`control` and `view` scopes, never `config.*`), revocable at any time on the spoke. A spoke without the grant shall appear view-only, or be absent, and the client shall be told which. | MVP |
| MCON-230 | The control lease for a spoke's Pier shall be held on that spoke, so the spoke's desktop, this plugin and WebConnect contend through one lease. | MVP |
| MCON-240 | When the Master is down or a spoke is detached or unreachable, the system shall show that spoke's Piers as unreachable (with the time last heard from), refuse operations to them with that reason, and resume without re-pairing when the spoke returns. The spoke's own imaging shall be unaffected. Operations relayed to a spoke shall be audited on both the Master and the owning node. | MVP |

### 3.4 State and events

| ID | Requirement | Priority |
|---|---|---|
| MCON-300 | On connection the system shall send each client a complete snapshot of the state of every Pier it may see, then only changes, so that a newly paired client shows live state for every Pier within a few seconds. | MVP |
| MCON-310 | The system shall deliver state and events by push over the Connect Link event stream (needs CL, L6), derived from `galileo.bus` events and the Control Surface's observable state. It shall not require the client to poll. | MVP |
| MCON-320 | The state delivered shall include, for each Pier, the same activity record as the Dashboard timelines (`OBS-150`, `galileo.dashboard_timeline`) and the status of each device category, session progress by block, guiding error, focus state, meridian-flip state and time to flip, safety inputs and overall state, and weather. | MVP |
| MCON-330 | Long-running operations (slew, solve, autofocus run, session, calibration set, flip) shall be reported as started / progress / finished events carrying a correlation id (needs OE), which the client turns into progress and completion notices and ties to the request that began them. | MVP |
| MCON-340 | The system shall forward the node's alerts to connected clients and keep a recent-alerts list available on request. It shall not claim background push: alerts arrive while the app is connected (PSD D4). | MVP |
| MCON-350 | On reconnection after a drop the system shall resend a snapshot, and events missed in a short window shall be recoverable by sequence number, so a client never shows stale state as current. State shall carry a timestamp so a client can show its age. | MVP |
| MCON-360 | The system shall deliver the state of a Pier to a client only if that Pier is among those the plugin's options expose (`MCON-910`) and the client's role permits viewing. | P2 |

### 3.5 Operations

Every operation is a Control Surface entry (needs CS) invoking the same domain service as the desktop screen, subject to the same checks, limits and safety interlocks. The boundary rule of PSD §6.4 applies throughout: an operation that takes effect on the sky or on the night's data is in scope; an edit to a stored definition of the observatory is not.

| ID | Requirement | Priority |
|---|---|---|
| MCON-400 | The system shall publish the operations to a client as a catalogue from the Control Surface — name, arguments, result, permission class, lease requirement — and a client shall be driven by it. Operations of areas not available in this plugin version shall be reported as unavailable by the handshake (`MCON-930`), not fail. | MVP |
| MCON-410 | **Observatory and Pier.** The system shall let a client list Observatories and Piers, choose the working Pier, and view the Dashboard timelines of every Pier. | MVP |
| MCON-420 | **Devices.** The system shall let an Operator connect and disconnect devices; for the mount: slew, sync, track on/off and rate, park/unpark, find home, pulse, and held jog (`MCON-730`); for the camera: set cooling and temperature, set gain/offset/binning/ROI per exposure, expose, abort; filter wheel: select; rotator: move; dome: open, close, slew, follow; flat panel: on/off and brightness; switches: toggle. Weather and safety-monitor state shall be viewable. Focuser movement shall be offered only under Focus (`MCON-470`). | MVP |
| MCON-421 | After a mount connects through an operation of this plugin, the same date/time and site latitude/longitude synchronisation shall occur as when connecting at the desktop; it shall not be skipped because the connect came from a remote client. | MVP |
| MCON-430 | **Imaging.** The system shall let an Operator run the live exposure loop and single and series captures; view the current-frame preview with stretch, histogram, image statistics, star count / HFR / FWHM, and the live-stack view; and reject frames. | MVP |
| MCON-440 | **Sky and framing.** The system shall let a client view the sky with the mount's position; search and select a target; go to it; use the Framing Assistant (field of view, rotation, mosaic panels); see current-object details, Planning and visibility lists, and the Telescopius and AAVSO targets already available to the node. | MVP |
| MCON-450 | **Plate solving and alignment.** The system shall let an Operator solve the current or last frame, centre on a target, sync, and run a polar-alignment routine. | MVP |
| MCON-460 | **Guiding.** The system shall let an Operator connect and disconnect the guider service, start and stop guiding, dither and recalibrate, and shall show the error trace and the guide-star cut-out. | MVP |
| MCON-470 | **Focus.** The system shall present the focus module as one place: manual focus — move in or out by a chosen step, move to an absolute position, halt, show position and temperature — and autofocus — start and cancel a run, show the V-curve and result, show temperature-compensation state. Manual focus shall be invoked through the focus module (needs MF) and not through a generic focuser-device operation. | MVP |
| MCON-480 | **Meridian flip.** The system shall show flip state, the time to flip and the outcome, and let an Operator trigger or defer a flip when the core service allows it; a trigger shall be a confirmed operation (`MCON-180`). | MVP |
| MCON-490 | **Sessions, run.** The system shall let an Operator list saved sessions, load one, and run, pause, resume, skip a step and stop it, and shall show progress block by block. | MVP |
| MCON-500 | **Sessions, authoring.** The system shall let an Operator add, remove, reorder and nest instruction, condition and trigger blocks, set their parameters, and save the session, using the same Sessions model as the desktop. The palette shall include blocks registered by plugins (`SES-340`). The session interchange file shall be the `.gses` file for import and export; saving on the node shall use its database. | P2 |
| MCON-510 | **Scheduler.** The system shall let a client see the job queue and next job, and an Operator create, edit, delete, enable/disable, reorder and run-now jobs, including adding a job from a target chosen in the sky view. | P2 |
| MCON-520 | **Calibration.** The system shall let an Operator start dark, flat and bias sets and shall show their progress. | P2 |
| MCON-530 | **Safety.** The system shall show every safety input and the overall state and the reason a session stopped, and let an Operator **acknowledge** an event. After a safety stop an Operator shall be able to acknowledge only: resuming remains the decision of the core safety service (PSD D7). | MVP |
| MCON-540 | **Library and history.** The system shall let a client browse recent sessions and frames (thumbnails, quality metrics), view a frame preview, and see session history and charts; an Operator may explicitly download a full FITS frame (`MCON-620`). | P2 |
| MCON-550 | **Notifications.** The system shall let a client see recent alerts (`MCON-340`). Notification channels and rules are configuration and not exposed. | P2 |
| MCON-560 | **Plugin surfaces.** The system shall let a plugin that registers a mobile surface through the Control Surface expose it to clients; a client shall list and operate it by the catalogue (`MCON-400`). | P3 |
| MCON-570 | **Per-run parameters.** The system shall accept per-run parameters (an exposure time, a focus step, a target, a binning) as part of an operation, and shall refuse any request, on any route, that would alter a stored definition listed as configuration in PSD §6.4. | MVP |
| MCON-580 | The system shall validate every operation's arguments on the Master against the Control Surface's declared types and ranges before invoking the service, and shall return a typed error (refused, invalid, unavailable, busy, unreachable) rather than an exception. | MVP |

### 3.6 Images and previews

| ID | Requirement | Priority |
|---|---|---|
| MCON-600 | The system shall deliver images as server-rendered previews (needs PV): stretched, binned or scaled to a size the client requests, JPEG-encoded, for the current exposure, any Library frame, and any guide or focus cut-out. FITS shall not be sent unless requested under `MCON-620`. | MVP |
| MCON-610 | The system shall offer a preview as tiles of a pyramid for pan and zoom, and shall cache rendered previews with a bounded size so that repeated requests do not re-render. Previews shall be sent over Connect Link's chunked, resumable, checksummed transfer (needs CL, L7). | P2 |
| MCON-620 | The system shall allow an Operator to download a full FITS frame as an explicit action, reported by size beforehand. A Viewer shall not be able to download FITS. | P3 |
| MCON-630 | The system shall expose the preview quality and maximum size as options (`MCON-910`) and shall let a client request a lower quality to suit its link; the node's session work shall take priority over preview rendering. | P2 |
| MCON-640 | The system shall stream sky data to clients that render the sky locally (needs SK): catalog by region, limiting magnitude and level of detail; ephemeris; Observatory location and horizon; live pointing and field of view; and the tile pyramid. The Master shall be the sole source: no client is required to carry a catalog or compute an ephemeris. Streaming is required for the Meta Quest edition (`MCON-1050`) and is offered equally to tablets and phones. | MVP |
| MCON-650 | The system shall report in the capability handshake (`MCON-930`) whether sky streaming is available and at what limits (detail, rate, concurrent clients). On a Master that cannot meet the load (a Raspberry Pi-class computer) it shall tell a headset that VR streaming is unavailable, with a reason the app can display, shall not attempt it, and shall serve tablet, phone and web clients with reduced limits. | MVP |
| MCON-660 | Sky streaming shall be requested by region, limiting magnitude and level of detail, progressive (bright objects first, fainter as they arrive), compact and delta-coded; ephemeris shall be offered for an instant and for a time range so that a client can scrub time without computing positions; every response shall carry the Master's as-of time so that clients agree with the Master on time and pointing. A stream interrupted by a client suspending shall resume from a cursor, not restart. | MVP |
| MCON-670 | The tile pyramid of `MCON-610` shall be available for the current exposure, the live stack and any Library frame, with stretch applied on the node, and a client shall be able to hold tiles of two frames at once for blink and side-by-side comparison. | MVP |
| MCON-680 | Streaming shall always yield to a running session, shall be rate-limited per client, shall limit the number of concurrently streaming clients to a figure the Master derives from its capability, and shall degrade detail before it delays anything else. Streaming load shall not interrupt imaging or the Emergency operations. | MVP |

### 3.7 Safety and failure behaviour

| ID | Requirement | Priority |
|---|---|---|
| MCON-700 | Every operation shall pass through the same core services and safety interlocks as the desktop UI. The system shall not disable the safety monitor, clear an unsafe state, or override a mount limit, and shall provide no route that does. | MVP |
| MCON-710 | The system shall provide Emergency operations — **Stop everything**, **Park**, **Close dome** — callable by any paired Operator without the lease, available on every client screen, and audited. They shall be confirmed on the client by a deliberate gesture and shall not require a second round trip to succeed once confirmed. | MVP |
| MCON-720 | Imaging shall continue, unchanged, when a client disconnects, sleeps or loses signal; the node shall neither require a client to remain connected nor stop a session when one disconnects. The sole exception is held motion (`MCON-730`). | MVP |
| MCON-730 | A manual slew or jog and a focuser move started from a client shall run only while its keep-alive arrives (needs DM). They shall stop within one second of the keep-alive stopping or the connection dropping, and shall stop when the lease is taken. | MVP |
| MCON-740 | Reconnection shall restore the live view and shall not repeat any operation that was in flight: an operation shall carry a client-generated idempotency key, and a retried request with the same key shall return the original result. | MVP |
| MCON-750 | Where a command is refused because the lease is held elsewhere, the Pier is unsafe, the device is busy or unconnected, or the target is unreachable, the system shall say so with a reason the app can display, never silently ignore or queue it. | MVP |
| MCON-760 | The lease shall not be silently held by a client that has gone away: on disconnect or idle timeout the lease is released and the desktop and other clients are told. | MVP |
| MCON-770 | A flood of requests from one client shall be rate-limited per client without affecting other clients, imaging or the Emergency operations. | P2 |

### 3.8 Mobile apps (scope level)

These requirements fix what the apps must do; layouts, navigation and visual design belong to the [Galileo-MobileConnect](https://github.com/gordtulloch/Galileo-MobileConnect) documents.

| ID | Requirement | Priority |
|---|---|---|
| MCON-800 | The system shall include native apps for iPadOS/iOS (Swift, SwiftUI) and Android (Kotlin, Jetpack Compose), distributed through the Apple App Store and Google Play, free of charge initially. | MVP |
| MCON-810 | The apps shall be **tablet-first**: the tablet layout shows the sky view, image and session list side by side; the phone layout drops secondary panels and condenses the rest. The panels the phone drops shall be decided from tablet wireframes (PSD Q1). | MVP |
| MCON-820 | The apps shall provide a screen or section for each operational area of Section 3.5, driven by the Control Surface catalogue; an area the node does not offer shall be hidden or shown as unavailable, never broken. | MVP |
| MCON-830 | The apps shall pair with the Master by discovery on the LAN (Connect Link L4) or manual address entry, request pairing, wait for approval on the Master, and store only the issued credential in the platform's secure storage. | MVP |
| MCON-840 | The apps shall show the client's role, the lease state of the selected Pier and who holds it, the connection state, and the age of the state shown, at all times. | MVP |
| MCON-850 | The apps shall hide operations a Viewer cannot perform, shall mark every confirmed operation with the confirmation of `MCON-180`, and shall provide the Emergency operations (`MCON-710`) on every screen. | MVP |
| MCON-860 | The apps shall provide a night-vision (red) theme that does not emit non-red light, including the system status elements the platform lets the app control. | MVP |
| MCON-870 | The apps shall comply with each store's policies, including the iOS local-network permission prompt and Android foreground-service rules, and shall tell the user in-app that supported use is on the LAN or a VPN the user runs, offering no UPnP or port-forwarding help. | MVP |
| MCON-880 | The apps shall be generated from, and tested against, one OpenAPI description and one shared protocol test-vector suite, so the two clients and any third-party client agree with the node; shared model, business logic, design tokens, icons and localisation strings shall be maintained once. | P2 |
| MCON-890 | The apps shall provide an in-app help for each screen, and an About screen showing the app version and the Master's Galileo, plugin and protocol versions. | P2 |

### 3.9 Options, help and wire API

| ID | Requirement | Priority |
|---|---|---|
| MCON-900 | The system shall add a **MobileConnect** page under Options (`PLUG-170`) in which a Master user manages paired clients (list, role, revoke, expiry), and pending approvals. | MVP |
| MCON-910 | The system shall provide, and persist in Galileo's database under the plugin's namespace (`PLUG-150`), these options: which Piers are exposed to clients; lease idle timeout; audit retention; preview quality and maximum size; per-client role and expiry. Values shall be validated and clamped. The system shall write no plugin-private file and use no `QSettings`. | MVP |
| MCON-920 | The system shall describe its wire API in a published, language-neutral form: an OpenAPI description of the request routes and a schema for the event stream, versioned `/mobileconnect/v1/...` (Connect Link L5). A breaking change shall be a new version, with the previous kept for a stated period. | MVP |
| MCON-930 | The system shall perform the Connect Link version handshake (L8) and extend it with the plugin's API version and the list of operation areas available, so that an old app is told to update, an old node is detected by a new app, and unavailable areas are reported (`MCON-400`). | MVP |
| MCON-940 | The system shall ship in-app help Markdown for every control on its plugin page and Options page (`HELP-060`), registered through the plugin help mechanism, and shall pass the help audit. | MVP |

### 3.10 Meta Quest headset clients (scope level)

A Meta Quest 2/3 is a client fully equal to a tablet for v1 (PSD D15). These requirements fix what falls on the node and on the headset edition at scope level; scene design, rendering stack, input and comfort belong to the [Galileo-MobileConnect](https://github.com/gordtulloch/Galileo-MobileConnect) documents (its PSD §4a and Quest SDD).

| ID | Requirement | Priority |
|---|---|---|
| MCON-1000 | **Parity.** The system shall make every view and operation of Sections 3.4–3.7 available to a headset client that it makes available to a tablet, under the same roles. It shall withhold nothing from, and add nothing for, a client because it is a headset; clients differ only by capabilities reported in the handshake (`MCON-650`). | MVP |
| MCON-1010 | **Pairing and identification.** A headset shall pair through the flow of `MCON-100`, defaulting to Viewer. The pairing request shall carry the client platform and device model, shown on the Master's client list and in the audit log (`MCON-190`) as a distinct client type. The platform shall be used for display and diagnosis only and never to grant or refuse a permission. | MVP |
| MCON-1020 | **Same safety model.** Roles, the lease, confirmation by two-step request (`MCON-180`), the Emergency operations (`MCON-710`) and audit shall apply to a headset identically. The Emergency operations shall be reachable from every panel and immersive scene of the Quest edition. | MVP |
| MCON-1030 | **Held motion.** A headset shall start a held slew, jog or focuser move only from a held controller button, never from a hand-tracking gesture, and shall keep the keep-alive of `MCON-730` alive only while the button is held. The node cannot tell the input apart; this is a requirement on the Quest edition. | MVP |
| MCON-1040 | **Suspension.** A headset removed from the head, put to sleep or out of range shall be treated as a disconnect under `MCON-720`, `MCON-730` and `MCON-760`. On resume it shall resynchronise from the replay of `MCON-350` and shall not repeat an in-flight operation (`MCON-740`). | MVP |
| MCON-1050 | **Immersive planetarium.** The Quest edition shall render the sky as a dome for the Observatory's location and a chosen time from data streamed under `MCON-640` and `MCON-660`, showing the horizon profile, live mount pointing and the optical train's field of view, with time scrubbing, and shall make go-to from a selected object an Operator operation with confirmation (`MCON-440`, `MCON-180`). It shall ship no catalog and compute no ephemeris; any cache shall be short-lived and bounded. | MVP |
| MCON-1060 | **Immersive image viewer.** The Quest edition shall show the current exposure, the live stack and any Library frame as a large virtual display with pan, zoom, stretch and compare, from the tiles of `MCON-670`, and shall not receive or request FITS except under `MCON-620`. | MVP |
| MCON-1070 | **Wearer safety.** The Quest edition shall make camera passthrough available at one gesture or button, and shall present a first-run notice and documentation stating the headset is for seated or indoor use, never while walking at the telescope. | MVP |
| MCON-1080 | **Platform and distribution.** The Quest edition shall run on Meta Quest 2 (the acceptance device and performance budget) and run the same build on Quest 3; shall depend on no Google services; and shall be distributed through the Meta Horizon Store with SideQuest side-loading as a supported fall-back. | MVP |
| MCON-1090 | **Master tier disclosure.** The Quest edition shall tell the user, in its first-run screen and on connecting to a Master that reports streaming unavailable (`MCON-650`), that a PC/Mac-class Master is required and why. | MVP |
| MCON-1100 | **Further VR adaptations.** A Quest-edition feature beyond `MCON-1050` and `MCON-1060` that needs data or an operation the wire API does not offer shall be added here as a requirement and to the Control Surface or streaming service before it is built. The adaptations are chosen and ordered from the app repository's Quest analysis. | P3 |

### 3.11 Outreach mode (unregistered image viewers)

Outreach lets visitors on their own phones or tablets watch live images without being paired (PSD Section 6.8, D18–D20). The event itself is hosted in core by Connect Link's outreach facility (needs OF, L9; PSD D21), shared with WebConnect's browser outreach; the requirements marked (needs OF) state the behaviour this plugin relies on and verifies through its app surface, and `MCON-1240`, `1250`, `1260` and `1330` are the app surface's own. Guest enrolment and the `outreach.view` scope are Connect Link's (L2/L3). A guest is not a role under `MCON-110`; none of the paired-client requirements of Section 3.2 applies to a guest except where stated.

| ID | Requirement | Priority |
|---|---|---|
| MCON-1200 | (needs OF) The system shall provide outreach mode that is **off by default** and operates only within an **event** the owner opens on the Master with a duration (and ends early at will). While no event is open nothing outreach-related shall listen or answer. When an event ends, the plugin is disabled or the Master restarts, every guest shall be disconnected and every guest token invalidated. | MVP |
| MCON-1210 | (needs OF) On opening an event the system shall display on the Master a **QR code** carrying the Master's address, a random per-event secret, a version, and the outreach **SSID** (and, if the owner has entered it, the Wi-Fi passphrase in a form standard Wi-Fi QR scanners accept), so that a visitor can join the outreach network and then the app. The secret shall be cryptographically random, differ for every event, and be re-issuable during an event, which shall stop new enrolments with the old secret. | MVP |
| MCON-1220 | (needs OF) The system shall enrol a device that presents a valid event secret by issuing it an **anonymous guest token** (needs CL) that is short-lived, tied to the event, carries only the `outreach.view` scope, and is refused after the event ends or the owner ejects guests. Enrolment shall require no name, account or per-device approval. A request without a valid event secret or guest token shall receive no data. | MVP |
| MCON-1230 | (needs OF) The system shall answer outreach enrolment and guest requests **only from source addresses inside the outreach subnet(s)** the owner has configured, and shall refuse any other source — including routed, forwarded or internet-originating requests — without revealing the node's identity. If no outreach subnet is configured an event shall not open. | MVP |
| MCON-1240 | A guest token shall permit exactly: listing the Piers offered for outreach (display names only), receiving the live image of an offered Pier, and switching between offered Piers. Every other route — operations, device or session state, timelines, alerts, Library, history, FITS, sky streaming, previews of arbitrary frames, leases and all configuration — shall refuse a guest, and each refusal shall be counted. A guest shall hold no lease and be in no role. | MVP |
| MCON-1250 | The system shall push to each guest the **live image of the Pier it is viewing as each frame is made**: the server-rendered preview (`MCON-600`) of each completed frame of the current exposure series or live loop, and the live stack where the owner offers it, sent over the event stream on completion rather than polled. A guest that joins or switches Pier shall receive the most recent preview at once, with its age. | MVP |
| MCON-1260 | The system shall let the owner choose which Piers an event offers (`MCON-1310`); a Pier not offered shall be invisible to guests. A spoke node's Pier shall be offered only if its node has granted the Master `view` (`MCON-210`) and the owner has offered it. A guest shall be able to switch between offered Piers at any time, and a Pier going unavailable shall be reported to the guest, not left blank. | MVP |
| MCON-1270 | Previews sent to guests shall carry **no FITS header, EXIF, GPS or other embedded metadata**, so the site location and equipment details are not disclosed, and shall be limited to the guest preview size and quality (`MCON-1280`). | MVP |
| MCON-1280 | (needs OF) The system shall bound guest load: a configurable cap on concurrent guests (refusing further enrolments with a readable reason), a reduced preview size and quality for guests, per-guest rate limits, and guest traffic of lower priority than a running session and than any paired client. Guests shall not delay imaging or the Emergency operations (`MCON-710`). | MVP |
| MCON-1290 | (needs OF) The system shall audit each event (who opened and closed it, when, which Piers were offered, peak and total guests, refusals) and aggregate guest counts per Pier. It shall record no personal data about guests: a guest is a random token and a source address held only for the event's duration. | MVP |
| MCON-1300 | (needs OF) The system shall show the owner on the Master, while an event is open, the QR code, the time remaining, the connected guest count and the offered Piers, and shall let the owner end the event, extend it, eject all guests, and re-issue the secret. | MVP |
| MCON-1310 | (needs OF) The system shall provide, and persist in Galileo's database (`PLUG-150`), these outreach options: the outreach SSID and optional passphrase, the outreach subnet(s), the default duration, the concurrent-guest cap, the guest preview size and quality, and which Piers are offered. Values shall be validated and clamped; the passphrase shall be stored as a secret and never logged or audited. | MVP |
| MCON-1320 | The handshake (`MCON-930`) shall tell an app whether an outreach event is open and the limits that apply, so a guest app can show a closed, full or ended state with a reason. | P2 |
| MCON-1330 | The iOS/iPadOS and Android apps shall offer a **guest entry**, reached by scanning the event QR code or opening the app on the outreach network, that shows only the Pier switcher and the live image, stores the guest token only for the event, offers no other screen, and tells the visitor when the event ends. A headset shall not be a guest client in v1. | MVP |

---

## 4. Non-Functional Requirements

Cross-cutting qualities are verified through the plugin's requirements above and the core `NFR` requirements, and listed here for traceability only:

| Quality | Source | Requirement |
|---|---|---|
| Encryption and authentication of all traffic | PSD PC6 | Provided by Connect Link; `MCON-100`, `MCON-030` forbid any other path |
| Imaging unaffected by clients | PSD PC5 | `MCON-060`, `MCON-720` |
| Pi-class load | PSD PC1 | `MCON-080` |
| UI-thread discipline | PSD PC3 | `MCON-070` |
| Config in database | PSD PC2 | `MCON-910` |
| Portability | Core `NFR-PORT-010` | The plugin uses `galileo.platform` for any paths and has no OS-specific code |

---

## 5. Requirement Summary Counts (for RTM Seeding)

| Sub-area | Count | MVP | P2 | P3 |
|---|---|---|---|---|
| Packaging, lifecycle and placement (010–080) | 8 | 8 | 0 | 0 |
| Pairing, roles, lease and audit (100–190) | 10 | 10 | 0 | 0 |
| Proxying (200–240) | 5 | 5 | 0 | 0 |
| State and events (300–360) | 7 | 6 | 1 | 0 |
| Operations (400–580) | 20 | 14 | 5 | 1 |
| Images and previews, sky streaming (600–680) | 9 | 6 | 2 | 1 |
| Safety and failure behaviour (700–770) | 8 | 7 | 1 | 0 |
| Mobile apps (800–890) | 10 | 8 | 2 | 0 |
| Options, help and wire API (900–940) | 5 | 5 | 0 | 0 |
| Meta Quest headset clients (1000–1100) | 11 | 10 | 0 | 1 |
| Outreach mode (1200–1330) | 14 | 13 | 1 | 0 |
| **Total** | **107** | **92** | **12** | **3** |

(The counts were recomputed from the tables; the previous Operations and Images rows, and so the previous total of 76, understated the requirements actually listed.)

---

## 6. Open Points for Review

| # | Point | Where |
|---|---|---|
| O1 | The core Control Surface, lease, operation-event, preview, deadman, manual-focus and sky-streaming requirements (PSD C1–C7) do not yet exist in the core SRS. This SRS cites them as prerequisites; they need to be written there before the RTM can reserve test cases for the dependent requirements. | §2.6 |
| O2 | Which panels the phone layout drops (PSD Q1) — `MCON-810` defers this to tablet wireframes. | `MCON-810` |
| O3 | `MCON-180` lists the confirmed operations at minimum; the full list should come from the Control Surface's permission classes once defined. | `MCON-180` |
| O4 | `MCON-740` (idempotency keys) is new in this SRS and not in the PSD; confirm it is wanted as MVP. | `MCON-740` |
| O5 | `MCON-350` (sequence-numbered replay of missed events) and `MCON-770` (rate limiting) are also additions beyond the PSD. | §3.4, §3.7 |
| O6 | Background push alerts (PSD D4, Q4 earlier) are excluded from v1; `MCON-340` states alerts arrive while connected. | `MCON-340` |
| O7 | The Meta Quest is fully equal to the tablet for v1 (PSD D15), so `MCON-640` moves from P3 to MVP and `MCON-650`–`680` and Section 3.10 are new. Sky streaming (PSD C7) therefore joins the MVP critical path of core prerequisites. | §3.6, §3.10 |
| O8 | The rendering stack for the immersive scenes (native Android SDK or a game engine) is open in the app PSD (Q6) and is decided in the Quest SDD from a Quest 2 spike; it does not affect this SRS unless it changes the streaming protocol of `MCON-660`. | `MCON-660` |
| O9 | `MCON-650` says the Master "derives" its concurrent-streaming limit from its capability; the figures (and the exact Pi/PC boundary) need a measurement on real hardware. | `MCON-650`, `MCON-680` |
| O11 | Outreach (PSD D18) is an exception to Connect Link's rule that nothing answers a caller without a token issued after approval. It needs an amendment to core's Connect Link (L2 event-scoped enrolment, L3 `outreach.view`) — already noted in the NodeConnect PSD §6.2 — before `MCON-1200`–`1330` can be verified. | §3.11 |
| O12 | `MCON-1230` confines guests by source subnet, which protects against internet reach but not against a visitor's device being on a network that can also reach the observatory's equipment. Isolation of the outreach SSID is the owner's responsibility (PSD R15); the plugin can only document it and refuse to open an event without a subnet. | `MCON-1230` |
| O13 | Outreach is also offered to browsers through WebConnect (PSD Q3 resolved; WebConnect PSD §6.4), which will specify its own requirements against this event; this SRS stays app-only, but `MCON-1200`/`1300` may need an option to offer an event to apps, browsers or both, and the shared event's home is open (WebConnect PSD Q3). Whether a fixed showcase set may be offered as well as the live image (PSD Q4) is undecided. | PSD Q3, Q4 |
| O10 | `MCON-1030` and `MCON-1070` bind the Quest edition, which this SRS cannot verify on the node; they will be tested in the app repository, with the node-side keep-alive behaviour tested here. | §3.10 |

---

## 7. Path to SDD / Traceability Matrix

1. **Core and NodeConnect SRS additions** — the prerequisites of Section 2.6.
2. **SDD** — `SDD.md`, describing how the plugin's modules satisfy the requirements above.
3. **Traceability Matrix** — `RTM.md`, a row per requirement ID here, mapped to its SDD component and a `TC-MCON-*` test case ID.

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SRS](../../SRS.md).*
