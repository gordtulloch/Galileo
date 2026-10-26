# MobileConnect Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — MobileConnect Plugin (iOS/Android remote control of a Galileo node) |
| **Document** | PSD (Project Scope Document), v0.2, draft — revised after first review (Section 12) |
| **Status** | Draft — for review |
| **Date** | 2026-10-27 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Sibling plugins** | [NodeConnect](../nodeconnect/PSD.md) — defines the shared Connect Link facility (its Section 6.2); [WebConnect](../webconnect/PSD.md) — the same control surface from a web browser |
| **Client apps** | The iOS/iPadOS and Android apps have their own scope in the [Galileo-MobileConnect](https://github.com/gordtulloch/Galileo-MobileConnect) repository (`docs/PSD.md`); this document specifies the plugin and the operational surface, and that one how the apps present it |
| **Downstream documents** | SRS, SDD, RTM — not yet written; to follow this PSD's approval |

---

## 1. Purpose of This Document

This document defines the scope of the **MobileConnect plugin** — a first-party Galileo plugin that lets an **iOS or Android app** — designed for a **tablet first**, usable on a phone with a reduced layout — operate a running Galileo node: watch it, and control everything it does. It also scopes, at requirement level only, the **mobile app** that is the plugin's counterpart. It follows the same PSD→SRS→SDD→RTM structure as [the core chain](../../PSD.md) and the other plugins' chains, and stays above implementation detail; design belongs in the SDD, written after this PSD is reviewed.

In this document "phone" in the sense of "the client device" should be read as *tablet or phone*; the tablet is the primary target (Section 4, G8).

## 2. Background and Motivation

An imaging rig runs outdoors, often at the far end of the garden or at a remote site, while the person running it is indoors, at the eyepiece of another instrument, or in bed. A desktop-only user interface forces a trip to the computer for every check and every correction: is the target still centred, did the guiding recover, is the focus drifting, did the session finish. Remote-desktop tools exist, but they drag a mouse-and-keyboard interface over a phone screen and send a whole desktop's pixels over a weak signal.

A tablet is the right device for a different, narrower job: see the state of the night at a glance, intervene when needed, and do deliberate operations (re-centre, refocus, park, start, stop, adjust the plan) with a touch-sized interface and little data. Its screen is large enough for the planetarium, the image and the session list side by side. A phone can do the same jobs with fewer elements on screen at once.

The expectation, stated in the request for this plugin, is that **the node is already fully set up and running** before the phone is used. The app therefore *operates* a configured observatory; it does not *configure* one. That keeps the app small and keeps the highest-risk edits (equipment definitions, safety limits, site location) at the computer.

## 3. Vision Statement

> A Galileo user pairs a tablet (or phone) with their node once, approving the request on the Master. From then on, anywhere on the observatory's network, the phone shows what every Pier is doing and lets them do anything they could do at the computer during a night's imaging — connect, slew, frame, focus, guide, capture, run and adjust a session, respond to a safety event — without ever being able to reach the configuration screens, and without the night's imaging depending on the phone staying connected.

## 4. Goals and Objectives

| # | Goal |
|---|---|
| G1 | Deliver MobileConnect as the `MCON` plugin — a first-party plugin distributed as a ZIP from the Galileo Plugins repository (`PLUG-090`/`PLUG-110`), independently enabled/disabled (`PLUG-060`), not bundled in the installer |
| G2 | **Full operational control.** Every operational function of Galileo (Section 6.4) is available to the app: nothing a user does *during* a night at the computer requires going back to the computer |
| G3 | **Faithful, live state.** The app shows live state for every Pier of the selected Observatory — the same information as the Dashboard timelines (`OBS-150`) plus the device panels — updated by push, not polling |
| G4 | **Use the same link facility as NodeConnect.** All traffic — pairing, authentication, encryption, discovery, requests, event stream, binary transfer — goes through Connect Link ([NodeConnect PSD](../nodeconnect/PSD.md) §6.2); MobileConnect adds handlers and permissions, not a transport |
| G5 | **Phone-sized data.** Images reach the phone as server-rendered, stretched, scaled previews (with optional tiling for pan/zoom), not FITS; a night's use over a weak link stays within a modest data budget |
| G6 | **Safe remote control.** One controlling client per Pier at a time (a *control lease*); any number of read-only viewers; every operation passes through the same core services and safety interlocks as the desktop UI; destructive operations ask for confirmation; a one-touch *stop / park* is always available |
| G7 | **Configuration is out of reach by construction.** A paired client is never granted `config.*` permission (Connect Link L3); the plugin registers no configuration route |
| G8 | **Native apps for iOS and Android**, built with each platform's native tooling and sharing as much as possible between them (Section 9, PC9), with a night-vision (red) theme. **Tablet is the primary form factor**; the phone layout drops secondary panels and condenses the rest. Free of charge initially; distributed through the App Store and Google Play |
| G9 | Keep the plugin's own options in Galileo's database, with in-app help for each control (core's definition of done) |
| G10 | **Proxy through the Master.** The app pairs with, and connects to, **one** node — the Master — and operates every paired node's Piers through it, exactly as [WebConnect](../webconnect/PSD.md) does (its Section 6.3). The Master relays operations, state, events and previews for spoke nodes over Connect Link; the app never contacts a spoke directly. A single-node installation is simply a Master with no spokes, and needs nothing from NodeConnect |

## 5. Non-Goals (Explicitly Out of Scope)

- **No configuration.** The app cannot create, edit or delete: equipment profiles, Piers, optical trains, device definitions or connection addresses, Observatories, site location, horizon, safety rules and limits, solver/autofocus/guiding/notification settings, plugin options or Options pages. (Setting a *per-run parameter* — an exposure time, a focus step, a target — is operation, not configuration; the boundary is in Section 6.4.) Configuration reaches a node through the desktop UI or [NodeConnect](../nodeconnect/PSD.md).
- **No internet relay, cloud account or push-notification service.** The app talks to the node over the user's network (LAN, or a VPN the user already runs). Because iOS and Android deliver background push only through APNs/FCM — which requires an internet-hosted relay — alerts arrive in the app while it is connected; true background push is a possible later addition and is listed as an open question (Section 12, Q4).
- **No dependency of the night on the phone.** The node must neither require the phone to stay connected nor stop imaging when it disconnects. (The sole exception is a *held* manual motion, Section 6.3.)
- **No bypass of safety.** The app cannot disable the safety monitor, clear an unsafe state, or override a mount limit. It can *acknowledge* a safety event and *request* a retry that the core safety service itself judges.
- **No raw video or desktop mirroring.** The app is a purpose-built interface over operations and state, not a remote-desktop client.
- **No offline operation.** The app controls a node it can reach; it does not cache a plan to execute later.
- **No access for unpaired clients, no anonymous viewing, no guest links.** A client pairs by requesting it; the request is approved on the Master (Connect Link L2) before a token is issued.
- **No FITS processing on the phone.** Previews are rendered on the node; downloading a full FITS frame is an explicit, optional action.
- **No watch layouts.**

## 6. Scope of Control

### 6.1 Principle

The app is a second front end to the **same domain services** the desktop UI drives. It does not get its own copy of the logic, a simplified path, or a back door: a request becomes the same call (`galileo.session_exec`, `galileo.autofocus`, `galileo.platesolve`, `galileo.meridianflip`, the `DevicePool`, …) that the desktop screen would make, and is subject to the same checks.

### 6.2 Dependencies on Galileo Core

| Core capability | Core requirement | How this plugin uses it |
|---|---|---|
| Plugin loading, manifest/version check, fault isolation | `PLUG-010`–`PLUG-050` | Loaded and isolated like any plugin; a crashed app session never affects imaging |
| Enable/disable, inertness | `PLUG-060` | Disabling closes the listener's MobileConnect routes and disconnects every phone |
| Core service access via `PluginContext` | `PLUG-080` | The plugin is granted the specific services it operates (Section 6.4) |
| Plugin Options page and settings | `PLUG-170`, `PLUG-150` | Paired-phone list and revocation, lease timeout, preview quality and size, which Piers are exposed |
| Top-level section | `PLUG-130` | A MobileConnect section: connected phones, current lease holders, the audit log |
| Event bus | `galileo.bus` | Subscribing to every domain event the app displays; the plugin forwards, it does not poll |
| Dashboard timeline model | `OBS-150` (`galileo.dashboard_timeline`) | The same activity record is sent to the app |
| Safety | `SAFE-*` | State shown to the app; operations pass through the safety service |
| Connect Link (**proposed**) | NodeConnect PSD §6.2, L1–L8 | Transport, pairing, scopes, discovery, event stream, binary transfer |
| Inline help | `HELP-060` | The plugin ships its own help Markdown |

### 6.3 Proposed core additions MobileConnect depends on

| # | Addition | Why |
|---|---|---|
| C1 | **A Control Surface**: a registry in which each domain service declares its operator-level operations (name, arguments, result, permission class, whether it needs the Pier's control lease) and its observable state, so a remote client is driven from a *catalogue* rather than by a plugin reaching into each module. The desktop UI is not required to use it in v1; it is the contract MobileConnect (and, later, other remote clients) are written against | G2, G6, and keeps the plugin free of per-module special cases |
| C2 | **A control lease** per Pier in core, taken by the desktop UI or by a remote client and visible to both, so that the desktop and the phone cannot give conflicting commands to a mount at the same moment | G6 |
| C3 | **Operation results as events**: long-running operations (slew, solve, autofocus run, session) publish started / progress / finished events with a correlation id, which the app turns into progress bars and notifications | G3 |
| C4 | **Server-side preview rendering** of the current exposure, any Library frame and any guide/focus cut-out (stretch, binning, JPEG), as a core utility the plugin calls | G5 |
| C6 | **Manual focus owned by the focus module.** Manual focus (move relative / absolute, halt, position and temperature) is a function of core's focus module, alongside autofocus, rather than logic inside the desktop focus screen. The desktop focus screen **consumes** it from the module, and the Control Surface publishes the same operations, so the desktop, MobileConnect and WebConnect all use one implementation and any later platform gets it for free. If the desktop screen currently drives the focuser directly, moving that logic into the module is a core change | G2 |
| C5 | **Deadman semantics for held motion**: a manual slew/jog or focuser move started from a remote client stops when its keep-alive stops or the client disconnects | G6 |
| C7 | **A sky-data streaming service**, so that remote clients (the Meta Quest and tablet planetarium views above all) render the sky from data streamed by the Master rather than from a catalog and ephemeris they carry: catalog by sky region, limiting magnitude and level of detail; ephemeris for a time or time range; Observatory location and horizon profile; the tile pyramid of C4. Compact, delta-coded, per-client rate-limited, and lower priority than the running session. Serving the Meta Quest edition requires the Master to be PC/Mac-class hardware; a Raspberry Pi-class Master serves tablet, phone and web clients with reduced limits and tells a headset that VR streaming is unavailable (capability handshake). Specified in the core SRS with the Control Surface; client-side scope is in the [Galileo-MobileConnect PSD](https://github.com/gordtulloch/Galileo-MobileConnect) (Q-13) | G2, G5 |

### 6.4 Operational surface

"All aspects of Galileo" is defined as every operational screen of the desktop application, **minus configuration**. The boundary rule: an operation that takes effect on the sky or on the night's data is in scope; an edit to a stored definition of the observatory is not.

| Area | In scope for the app | Out of scope (configuration) |
|---|---|---|
| **Observatory / Pier** | See Observatories and Piers; choose the working Pier; the Dashboard timelines for every Pier | Create or edit Observatories, Piers, optical trains |
| **Devices** | Connect / disconnect; mount (slew, sync, track on/off and rate, park/unpark, find home, pulse, held jog); camera (cool, set temperature, gain/offset/binning/ROI per exposure, expose, abort); filter wheel (select); rotator (move); dome (open/close/slew/follow); flat panel (on/off/brightness); switches (toggle); weather and safety monitor state. *(Focuser movement is under **Focus**, below.)* | Driver / profile / address definitions, filter names and offsets, default gain/offset |
| **Imaging** | Live exposure loop; single and series capture; current-frame preview with stretch; histogram and image statistics; star count / HFR / FWHM; live-stack view; frame rejection | Imaging defaults and file-naming settings |
| **Sky and framing** | Star Atlas / planetarium view of the sky with mount position; search and select a target; go-to; Framing Assistant (field of view, rotation, mosaic panels); current-object details; Planning and visibility lists; Telescopius and AAVSO targets already available to the node | Catalog and data-source settings |
| **Plate solving and alignment** | Solve current / last frame; centre on target; sync; polar alignment run | Solver choice, catalogs, tolerances |
| **Focus** | The focus module as one place: **manual focus** (move in / out by a chosen step, move to an absolute position, halt, current position and temperature), and **autofocus** (start / cancel a run, see the V-curve and result, temperature-compensation state). Manual focus is offered from the focus module, not from a generic focuser device page, matching the desktop arrangement | Focuser and autofocus parameters |
| **Guiding** | Connect / disconnect the guider service; start / stop guiding, dither, recalibrate; see error trace and star cut-out | PHD2 address and guiding settings |
| **Meridian flip** | See state and the time to flip; trigger or defer a flip when the core service allows; see the outcome | Flip settings |
| **Sessions** | List saved sessions; load; **run, pause, resume, skip step, stop**; follow progress block by block; **author and edit** session block lists (add, remove, reorder and nest instruction, condition and trigger blocks, set their parameters) and save them, using the same Sessions model as the desktop; the palette includes plugin-registered blocks (`SES-340`) | Session defaults in Options |
| **Scheduler** | See the job queue and the next job; **create, edit, delete**, enable / disable, reorder and run-now jobs, including adding a job from a target chosen in the sky view | Scheduler policy settings |
| **Calibration** | Start dark / flat / bias sets; see progress | Calibration defaults |
| **Safety** | See every input and the overall state; acknowledge an event; read the reason a session stopped | Safety rules, thresholds, limits |
| **Library and history** | Browse recent sessions and frames (thumbnails, quality metrics); view a frame preview; see session history and charts; optionally download a FITS frame | Library paths and ingest settings |
| **Notifications** | Receive the node's alerts while connected; see recent alerts | Notification channels and rules |
| **Plugins** | Operate any plugin's view that elects to expose a mobile surface through the Control Surface (C1) *(P3)* | Plugin installation and options |
| **Emergency** | One-touch **Stop everything / Park / Close dome**, permitted for any paired operator without taking the lease | — |

### 6.5 Control model

- **Pairing**: a client requests pairing; a person approves it on the Master; the Master issues the client's token (Connect Link L2). **Roles**, set per paired client on the node (Options): **Viewer** (state and images only) and **Operator** (viewer plus operations).
- **Lease**: an operator must hold a Pier's control lease to issue Pier-affecting operations. It is granted if free, offered by confirmation if held by the desktop or another phone, released on request, on disconnect, or after a configurable idle time. *Emergency* operations do not need the lease.
- **Confirmation** on operations that are destructive or hard to reverse (abort exposure series, stop session, park, unpark with a dome, run a flip), consistent with the core rule of confirming before irreversible actions.
- **Audit**: every operation by every phone is recorded (who, what, when, result) and shown on the plugin's page.

### 6.6 Placement and proxying through the Master

MobileConnect is installed and enabled on the **Master** only. The app pairs with the Master (request on the tablet, approved on the Master, token issued — Connect Link L2) and sees the Master's own Piers and, through it, every spoke node's Piers in one list, with one connection, one lease model and one audit log.

For a spoke's Pier the Master relays the app's operations and returns the spoke's state, events and previews; previews are rendered on the owning node, not re-rendered on the Master. Reaching a spoke needs the same opt-in grant described in [WebConnect §6.3](../webconnect/PSD.md): the spoke's user allows the Master to operate that node (`control`/`view` scopes, never `config.*`), revocable on the node at any time. A spoke that has not granted it shows as view-only, or is absent. The control lease for a spoke's Pier is held on that spoke, so its desktop, the Master's proxy (and thus both this app and WebConnect) contend through one lease. Because the Master is the single entry point, the app and WebConnect share one relay implementation in the Master rather than each building its own.

Consequences accepted: remote operation of a spoke stops while the Master is down or the spoke is detached (the spoke keeps imaging; the app shows it as unreachable), and the Master holds opt-in operating rights over its spokes, audited on both the Master and the owning node.

## 7. Requirement Domain

One domain, **`MCON`** (MobileConnect), specified in a future SRS. Provisional sub-areas, to be numbered when the SRS is written:

| Area | Covers |
|---|---|
| Pairing, roles and lease | Pairing with approval on the Master (via Connect Link), Viewer / Operator, lease, revocation, audit |
| Proxying | Relaying operations, state, events and previews to spoke nodes through the Master (shared with WebConnect); unreachable-node behaviour |
| State and events | Live state per Pier, event stream, alerts, correlation of long operations |
| Operations | One sub-area per row of Section 6.4 |
| Images and previews | Server-rendered previews, tiling, statistics, download |
| Safety and failure behaviour | Interlocks, confirmation, deadman, emergency, behaviour on disconnect |
| Mobile app (scope level) | Platforms, tablet-first layouts with phone reductions, screens by area, session and schedule authoring, night theme, discovery and connection UX, store distribution |
| Options, help and packaging | Options page, in-app help, plugin manifest |

## 8. Stakeholders and Primary Personas

- **The backyard / remote-site imager** (core PSD, Observatory Operator persona): wants to check on and nudge the night from indoors.
- **The multi-Pier operator**: runs several Piers and needs the whole-observatory overview on one screen, and to intervene on the right Pier.
- **A guest or family member** (Viewer role): can see the sky and the images, and cannot touch anything.

## 9. Project Constraints

| # | Constraint |
|---|---|
| PC1 | The node side is cross-platform (Windows/macOS/Linux, including Raspberry Pi 5-class ARM) and must be light enough that serving a tablet or phone does not disturb imaging on a Pi (VR streaming excepted: it needs a PC/Mac-class Master, C7): previews are rendered on demand and cached, state is event-pushed, nothing is polled in a loop |
| PC2 | All plugin configuration in the shared database (core's firm rule), never a plugin-private file or `QSettings`; the app stores only its pairing credentials in the phone's secure storage |
| PC3 | Network work never runs on the Qt UI thread; operations are dispatched to the same threads/executors the desktop UI uses |
| PC4 | The wire API is **versioned, documented and language-neutral** (an OpenAPI description plus the event schema), so the app and the node can be released independently and a third-party client is possible; the version handshake (Connect Link L8) tells an old app to update |
| PC5 | Imaging continues, unchanged, when the phone disconnects, sleeps or loses signal (mobile operating systems suspend background apps freely) |
| PC6 | All traffic is encrypted and authenticated; there is no unauthenticated route and no plugin-private transport |
| PC7 | Distributed through the Apple App Store and Google Play; the app's source lives in its own repository and release cycle, and must meet both stores' policies (local-network permission prompts on iOS, foreground-service rules on Android) |
| PC8 | The plugin is GPL-3.0-or-later like the other first-party plugins. The **app is not GPL**: proprietary, free of charge initially. The documented wire API (PC4) is open, so the app's licence does not constrain other clients, including [WebConnect](../webconnect/PSD.md) |
| PC9 | Native tooling on each platform (Swift/SwiftUI on iOS, Kotlin/Jetpack Compose on Android), with sharing maximised below the UI: one OpenAPI description from which both API clients are generated, a shared model and business-logic layer (Kotlin Multiplatform is the candidate), shared design tokens and icon set, shared localisation strings, and a shared test-vector suite for the wire protocol. Screens are native on each side. Confirmed in the SDD |

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | A phone command moves a mount into something while the user is not watching the equipment | Lease; Viewer default for new pairings; confirmation; deadman on held motion (C5); core limits and safety interlocks unchanged and not overridable |
| R2 | A conflicting command from the desktop and the phone | Control lease (C2) |
| R3 | A paired phone is lost or stolen | Per-phone revocation from the Master; credential in the phone's secure storage; optional per-phone expiry |
| R9 | Authoring sessions on a phone-size screen is cramped | Tablet is the primary target; on a phone, authoring is available but with a condensed block editor |
| R4 | The Control Surface (C1) is large — it touches every domain service | Deliver it incrementally in the order of Section 6.4's priorities, and keep each service's contribution a thin declaration over what it already exposes; unrelated areas stay "not available in this app version" and are reported by the handshake |
| R5 | iOS/Android restrictions (background execution, local-network permission, push) shape the experience more than the API does | Treated as scope-level constraints (PC7, Q4), prototyped first |
| R6 | Serving previews and state loads a Pi that is also running a session | Rendering budget and cache (PC1); previews dropped before session work is |
| R7 | The scope "all aspects" is unbounded | Section 6.4 is the definition; each row is a separately prioritised SRS area, so the plugin can ship with the nightly essentials first |
| R8 | An app that always works over a LAN is mistaken for a secure remote-access product and exposed to the internet | Documentation and in-app text state the supported network scope; no UPnP/port-forwarding help is offered |

## 11. Success Criteria (Scope-Level)

- A newly paired phone shows live state for every Pier within a few seconds of connecting, and keeps it current without polling.
- From the phone alone, a user can: connect the Pier's devices, pick and go to a target, centre it by plate solve, focus, start guiding, run a saved session to completion, and respond to a meridian flip and to a safety event.
- Killing the phone's network mid-session does not interrupt the session; reconnecting restores the live view.
- A Viewer-role phone cannot issue any operation; a paired phone, whatever its role, cannot reach any configuration route.
- With the desktop UI holding the lease, a phone's mount command is refused with an explanation; the Emergency stop still works.
- A held jog stops within a second of the phone's connection dropping.
- Disabling the plugin leaves no MobileConnect route and disconnects every phone.

## 12. Decisions from Review and Remaining Questions

### 12.1 Decided (review of 2026-10-27)

| # | Decision |
|---|---|
| D1 | Operations are exposed through a **core Control Surface** (C1) |
| D2 | The app can **author and edit sessions and the schedule**, not only run them |
| D3 | Native iOS and Android tooling, sharing as many elements as possible (PC9) |
| D4 | No background push alerts in v1 |
| D5 | The app is **not GPL**, and free initially |
| D6 | A new pairing is Viewer by default; promotion to Operator is deliberate, on the Master |
| D7 | After a safety stop an Operator can **acknowledge only**; resuming stays the core safety service's decision |
| D8 | Connect Link and the core additions are accepted prerequisites |
| D9 | **Tablet is the preferred form factor**; the phone gets a reduced UI |
| D10 | **Manual focus lives in the focus module** (Section 6.4, C6) |
| D11 | Pairing is approved on the Master before the token is issued |
| D12 | The focus screen consumes manual focus from the focus module (C6), so every platform shares it |
| D13 | Gord Tulloch holds the Apple App Store and Google Play accounts |
| D14 | **MobileConnect proxies through the Master** (Section 6.6, G10): installed on the Master only, one pairing, spoke nodes reached via the Master and the per-node grant |

### 12.2 Remaining

| # | Question | Recommendation |
|---|---|---|
| Q1 | **TBD.** Which parts of the phone layout may be dropped? | Decide from tablet wireframes in the SRS; likely the side-by-side planetarium/image and the block-editor canvas |
| Q2 | Does session authoring on the app use the same `.gses` interchange file as the desktop? | Yes for import/export; saving on the node uses its database |

## 13. Glossary

| Term | Meaning |
|---|---|
| **Node** | One Galileo installation |
| **Connect Link** | The shared core facility carrying NodeConnect's and MobileConnect's traffic ([NodeConnect PSD](../nodeconnect/PSD.md) §6.2) |
| **Control Surface** | The proposed core registry of remote-invocable operations and observable state (C1) |
| **Lease** | The right to issue Pier-affecting operations, held by one client per Pier at a time (C2) |
| **Viewer / Operator** | The two per-phone roles (Section 6.5) |
| **Preview** | A server-rendered, stretched, scaled image sent to the phone in place of a FITS frame |
