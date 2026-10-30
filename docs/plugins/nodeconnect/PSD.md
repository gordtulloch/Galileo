# NodeConnect Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — NodeConnect Plugin (node-to-node configuration sync and data transfer) |
| **Document** | PSD (Project Scope Document), v0.3, draft — revised after first review and SDD review (Section 13) |
| **Status** | Draft — for review |
| **Date** | 2026-10-27 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Sibling plugins** | [MobileConnect](../mobileconnect/PSD.md) and [WebConnect](../webconnect/PSD.md) — consume the same Connect Link facility (Section 6.2) |
| **Downstream documents** | [SRS](SRS.md), [SDD](SDD.md), [RTM](RTM.md) |

---

## 1. Purpose of This Document

This document defines the scope of the **NodeConnect plugin** — a first-party Galileo plugin that lets Galileo **nodes** (installations of Galileo running at a Pier, an observatory or a remote site) replicate their configuration with each other through a designated **Master** in a hub-and-spoke arrangement, and ship their history and images to that Master. It follows the same PSD→SRS→SDD→RTM structure as [the core chain](../../PSD.md) and the other plugins' chains ([VSTarget](../vstarget/PSD.md), [AllSkyCam](../allskycam/PSD.md), …), and stays above implementation detail; design belongs in the SDD, which is written after this PSD is reviewed.

## 2. Background and Motivation

A user with more than one Galileo installation — a home laptop and a field Raspberry Pi, a remote-observatory node and an indoor processing machine, two Piers each driven by its own small computer — ends up maintaining the same configuration by hand on each: equipment profiles, optical trains, filter offsets, horizon, solver and autofocus settings, notification rules, session templates, plugin options. Every change has to be repeated, and the copies drift.

The data flows the other way as well. A node at the telescope produces session history and FITS frames, but the machine where the user processes, browses and archives them is usually a different one. Today that is a manual copy of folders and, at best, a re-ingest into the Library on the other side.

Galileo already keeps all configuration in one shared database (core's firm rule: *configuration lives in the database, never in JSON files*) and all images in a catalogued Library. That makes both flows tractable without any new storage model: configuration is rows in a known set of tables, and images are files plus catalog rows that carry their own identity.

## 3. Vision Statement

> A Galileo user pairs each node with the Master once, approving the request on the Master. From then on a configuration change made on any node reaches the Master and, through it, every other node — at once when they are connected, and on reconnection or start-up when they were not — and everything a node captures (history, frames and their catalog entries) arrives at the Master without the user copying a file, even if the node was detached when the frames were taken.

## 4. Goals and Objectives

| # | Goal |
|---|---|
| G1 | Deliver NodeConnect as the `NCON` plugin — a first-party plugin distributed as a ZIP from the Galileo Plugins repository (`PLUG-090`/`PLUG-110`), independently enabled/disabled (`PLUG-060`), not bundled in the installer |
| G2 | **Complete configuration replication.** Every configuration record held in Galileo's shared database — Options settings (`app_settings`), equipment profiles (Piers, optical trains, device configuration), Observatories, horizon points, filter offsets, weather-safety rules, solver/autofocus settings, session templates, scheduler job definitions, and the settings of installed plugins — is replicable, except a short, explicit, user-visible list of **node-local** items (Section 5) |
| G3 | **Sync on startup by last-sync date.** At start-up a node asks its Master what has changed since this node's recorded last sync and transfers only that — additions, changes and deletions — in both directions, then records the new sync point. A node's first sync after pairing is a full one, which is how a new or replacement node acquires the configuration |
| G4 | **Two-way replication, hub-and-spoke.** Configuration replicates in both directions through the Master. A change made on a node is **shipped to the Master** when made; the Master **pushes** it on to every other connected node, and pushes its own changes the same way; each node also pulls at start-up. Nodes never talk to each other directly. Where the same record was changed in two places while a node was detached, the conflict is resolved (Section 10, R2) and reported |
| G5 | **Asynchronous history and image transfer to the Master.** Each node designates a Master in the plugin's page under Options. Session history and metrics, FITS frames and their Library catalog rows (`fitsFile`, `fitsSession`, …) flow node→Master through a durable queue: a detached node keeps working and **updates the Master when it reconnects**. Transfers are resumable, verified by checksum and idempotent. Removing local images after verified receipt is a **setting on the NodeConnect Options page** (off by default) |
| G6 | **Safe by default.** A node cannot communicate with the Master until it is **paired**: the node requests pairing, the request is **approved on the Master**, and only then is the node issued a **token** that every later request must present; all traffic is encrypted and authenticated; secrets (API keys, passwords held in settings) are excluded from replication unless the user opts them in; a sync never applies changes under an active imaging session |
| G7 | **Visible and recoverable.** A status view (last sync, pending items, last error), a per-run report of what changed, and a pre-sync snapshot of replaced values so a bad sync can be undone |
| G8 | Keep the plugin's own options in Galileo's database, with in-app help for each control (core's definition of done) |

## 5. Non-Goals (Explicitly Out of Scope)

- **No remote control.** NodeConnect moves configuration and data; it does not operate equipment on another node. Controlling a node is [MobileConnect](../mobileconnect/PSD.md)'s purpose, over the same link.
- **No cloud service, relay or account.** Nodes talk to each other directly over the user's network (LAN, or a VPN the user already runs). Reaching a node across the internet is the network's job, not the plugin's.
- **No topology beyond one hub.** Each node has at most one Master; a Master serves many nodes; there is no chain of Masters, no node-to-node link and no distributed consensus. The Master serialises changes, which is what makes conflict handling tractable.
- **No one-shot "copy node" mode.** Making a new node match an existing one is simply pairing it and letting its first (full) sync run.
- **No file-level database copy.** Replication is per record through Galileo's own models and migrations, never a copy of the database file; nodes on different schema versions are handled by a handshake (Section 9, PC4), not by copying tables blindly.
- **No translation of node-specific values.** The following are **node-local** and not replicated: the node's identity and pairing token, NodeConnect's own link settings, filesystem paths (Library root, data/cache/log folders) and the database location. The user can opt individual node-local items in; the plugin does not try to rewrite them. Device and PHD2 addresses **are** replicated, because core will refuse `localhost`/loopback in them (Section 6.3, C5), so an address stored on one node means the same machine on every other.
- **No Master redundancy or promotion in v1.** If the Master is lost, spokes keep working but configuration cannot converge; promoting a spoke to Master is deferred to v2 (D16).
- **No merging of two Libraries.** Image transfer ingests frames into the Master's Library and de-duplicates by content hash; it does not reconcile two independently grown Libraries or their user-edited catalog fields beyond Section 4 G5.
- **No image processing at the Master.** No stacking, calibration or re-measurement is performed on transfer; the Master's normal Library ingest does whatever it already does.
- **No live mirroring.** Running sessions, mount positions and guiding state are not replicated between nodes.

## 6. Dependencies on Galileo Core

### 6.1 Existing core capabilities

| Core capability | Core requirement | How this plugin uses it |
|---|---|---|
| Plugin loading, manifest/version check, fault isolation | `PLUG-010`–`PLUG-050` | Discovered, loaded and isolated like any plugin; a sync failure never takes the application down |
| Enable/disable, inertness | `PLUG-060` | Disabling stops the link, the queue and all background activity |
| Panel placement; top-level section | `PLUG-070`, `PLUG-130` | A NodeConnect section showing link status, pending transfers and run reports |
| Plugin Options page | `PLUG-170` | Master address, role, sync categories, schedule, bandwidth, secrets opt-in |
| Plugin settings in the database | `PLUG-150` | All options, via `ctx.settings()` |
| Core service access via `PluginContext` | `PLUG-080` | Reading and applying configuration, reading history, enqueuing Library ingest |
| Unified Peewee database and numbered migrations | Core SDD §4.18 | The set of replicable tables; schema version for the handshake |
| Event bus | `galileo.bus` | Subscribing to `frame written` / `session ended` events to feed the transfer queue; publishing "configuration changed by sync" so screens refresh |
| Library ingest | `LIB-*` | The Master's receipt path for transferred frames |
| Inline help | `HELP-060` | The plugin ships its own help Markdown |

### 6.2 The shared facility — Connect Link (proposed core addition)

NodeConnect and MobileConnect must use **the same communication facility** (a stated requirement of both plugins). Two plugins each running their own server would duplicate security-critical code, contend for a port, and pair separately. The proposal, for decision in review (Section 13, Q1), is that the facility is a **core service, "Connect Link"**, offered to plugins through `PluginContext`, in the same way `ctx.settings()` is:

| # | Connect Link capability | Used by NodeConnect for | Used by MobileConnect for |
|---|---|---|---|
| L1 | One authenticated, encrypted listener per node (HTTPS + WebSocket), started only while at least one enabled plugin has registered a handler | Receiving config requests and uploads | Receiving commands, serving state |
| L2 | **Pairing with approval**: a client sends a pairing request to the node it wants to join (identifying itself and showing a short code); **the request is held until a person approves it on the receiving node**; only then is a per-peer **token** (and pinned certificate) issued. No endpoint other than "request pairing" answers a caller without a valid token. Revocable per peer. **One owner-initiated exception — outreach enrolment:** while the node's owner has switched an *outreach event* on (time-limited, off by default), a device that presents the event's secret, shown by the Master as a QR code, and that connects from the event's configured network, is issued a short-lived, anonymous guest token carrying only the `outreach.view` scope (L3). Approval is thereby given by the owner's act of opening the event rather than per device; an unpaired device with no event secret is still answered by nothing (see the [MobileConnect PSD](../mobileconnect/PSD.md) §6.8) | A node asks to join the Master; the Master's user approves; the node is issued its token | A tablet/phone/browser asks to join the node; the node's user approves |
| L3 | **Scoped permissions** per peer (`config.read`, `config.write`, `data.push`, `data.pull`, `control`, `view`, and the guest-only `outreach.view` — live images of owner-selected Piers and nothing else, never granted to a paired peer) and an audit log of who did what | `config.*`, `data.push`, `data.pull` only | `control`, `view` only — never `config.*` |
| L4 | **Discovery** on the LAN (mDNS/zeroconf service advertisement) plus manual address entry | Finding the Master | Finding the node |
| L5 | **Request/response API** with versioned routes that a plugin registers (`/nodeconnect/v1/...`) | Change-set exchange | Operations (Section 6 of the MobileConnect PSD) |
| L6 | **Server-push event stream** (WebSocket) | The Master pushing changes to connected nodes; nodes notifying the Master | Live state, progress, alerts |
| L7 | **Resumable, chunked, checksummed binary transfer** in both directions | FITS frames to the Master | Preview images to the phone; frame download |
| L8 | **Version handshake**: Galileo version, plugin API version, schema (migration) level, Connect Link protocol version | Refuse or restrict a sync across incompatible schemas | Tell the app to update |
| L9 | **Outreach event facility** (owner-opened, time-limited events; per-event secret; source-subnet guard; anonymous `outreach.view` guest tokens, guest caps and rate limits; aggregate-only audit; metadata-free guest previews through the core preview service; the event display with its Wi-Fi and enrolment QR codes). Hosted in core so that every front end shares one implementation; a plugin contributes only a *surface* (its QR payload, its guest routes, how it delivers images) | — | MobileConnect offers the event to apps, [WebConnect](../webconnect/PSD.md) to browsers |

The Connect Link requirements (`LINK-*`) are now in the core SRS (Section 4.24) and SDD (Section 4.28): L1–L8 as outlines, L9 in full. Until then this table is the contract both plugins are designed against.

### 6.3 Other proposed core additions NodeConnect depends on

| # | Addition | Why |
|---|---|---|
| C1 | **Per-record change tracking on replicable tables**: a modification timestamp and a Master-issued monotonic revision on each row, a **`dirty`** flag and the **`base_rev`** an edit started from (with a write hook, so a spoke can ship local edits and the Master can detect conflicts exactly), plus a **tombstone** record for deletions (numbered migration under `galileo/library/migrations/`). Today `app_settings` (`namespace`, `key`, `scope`, `value`) has no modification time, so "changed since last sync" cannot be answered, and a deleted row leaves no trace to propagate | G3 |
| C2 | **A replicable-table registry**: each core model that holds configuration declares itself replicable, with its natural key and its node-local fields. New configuration tables are then replicated by registration, not by editing NodeConnect (the definition of "complete" stays true as Galileo grows) | G2 |
| C3 | **A "settings changed" notification** on the event bus after a bulk apply, so open Options pages and screens reload | G3 |
| C4 | **A busy signal** from the session executor, so a sync can wait out an imaging session | G6 |
| C5 | **No `localhost` in device or PHD2 addresses.** Wherever the user specifies the host/URL of a device (INDI server, Alpaca device) or of PHD2, core validation refuses `localhost`, `127.0.0.0/8`, `::1` and `0.0.0.0` with a message asking for the machine's real hostname or LAN address; existing profiles that contain one are flagged on load. This is a core change, specified in the core SRS (equipment and guiding domains), and applies with or without NodeConnect. It exists so that a stored address means the same machine on every node — the property replication relies on. Consequence to accept: a single-machine user whose INDI server runs on the same computer must enter that computer's hostname or LAN address | G2 |
| C6 | **Core-owned sync tables.** The tables NodeConnect needs to be durable — outbox, inbox, snapshots, run reports, transfer queue and per-node sync state — are created by numbered core migrations (not plugin-owned migrations) and exposed to the plugin through a storage port. Core's migration rule is thereby kept intact | G3, G5, G7 |
| C7 | **Library location state.** `fitsFile` gains a location of *Local* or *On Master* (like the existing cloud-backed state) and Library support for retrieving an On Master frame back to the node; set by NodeConnect after verified receipt, with retrieval over Connect Link under a `data.pull` scope | G5 |

## 7. Requirement Domain

One domain, **`NCON`** (NodeConnect), specified in a future SRS. Provisional sub-areas, to be numbered when the SRS is written:

| Area | Covers |
|---|---|
| Roles and pairing | Node and Master; designating the Master in Options; pairing request, approval on the Master, token issue, revocation |
| Configuration replication | Replicable set, node-local exclusions, last-sync logic, change sets, push and pull, hub-and-spoke fan-out, conflict policy, deletions, secrets, `localhost` guard (C5), snapshot and undo |
| Startup and scheduling | Sync at start-up, change-driven push, deferral during sessions, retry/backoff |
| History transfer | Session history and metrics to the Master; idempotent merge |
| Image transfer | FITS and catalog rows to the Master; durable queue, resume, checksum, de-duplication, bandwidth and time-of-day limits, local clean-up option after verified receipt |
| Status and reporting | Link status, pending queue, per-run report, notifications on failure |
| Options, help and packaging | Options page, in-app help, plugin manifest |

## 8. Stakeholders and Primary Personas

- **The multi-site imager** (core PSD, Observatory Operator persona): a field node and a home node, or a remote observatory and a processing machine, who wants one configuration and one archive.
- **The multi-Pier observatory**: several Piers, each on its own small computer, kept consistent from a single Master, and collecting everything on the Master's Library.
- **The user replacing hardware**: a dead SD card or a new Pi, paired to the Master and restored to a working node by its first full sync rather than by re-entering everything.

## 9. Project Constraints

| # | Constraint |
|---|---|
| PC1 | Cross-platform (Windows/macOS/Linux, including Raspberry Pi 5-class ARM): no platform-specific code; modest memory and CPU (streamed transfer, never whole frames or whole tables in memory) |
| PC2 | All configuration in the shared database (core's firm rule), including NodeConnect's own — never a plugin-private file or `QSettings`. Exported snapshots are user-chosen interchange files (the rule's exception (a)) |
| PC3 | Network and file I/O must never run on the Qt UI thread; the domain core does not import NodeConnect — everything flows through the event bus and `PluginContext` |
| PC4 | Nodes can run **different Galileo versions** (a Pi that was not upgraded). The handshake (L8) decides: same schema level → full sync; a node older than the Master → sync only the tables both understand and report the rest; incompatible protocol → refuse with a clear message. Unknown columns are never guessed at |
| PC5 | Intermittent links are the normal case for a field node: every transfer is resumable and idempotent; the node never loses data because the Master was offline, and removing local images only ever follows a verified receipt |
| PC6 | Clock skew between nodes must not corrupt the result: "last sync date" is recorded locally for display, but *what changed* is decided by the Master-issued revision counter (C1), not by comparing wall clocks |
| PC7 | GPL-3.0-or-later, as the other first-party plugins |

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | Replicating a node-specific value (a device address, a path) breaks the receiving node | Node-local default list (Section 5); C2 lets each model mark its own node-local fields; dry-run preview before the first sync |
| R2 | A detached node and another node (or the Master) change the same record; one change silently overwrites the other | A change carries the revision it was based on, so a conflict is detected exactly, not guessed from clocks. The later edit wins, using timestamps corrected by the clock offset measured at the handshake (PC6); the losing value is kept in the snapshot and listed in the run report (G7) |
| R3 | A sync lands mid-session and changes a setting the executor is using | Deferred while a session runs (G6, C4); applied between sessions |
| R4 | Secrets leak by being replicated, or are exposed in transit | Excluded by default; encrypted and authenticated transport (L1/L2); never written to the run report or log |
| R5 | A large Library flows over a slow link and starves the node of bandwidth during the night | Bandwidth cap and allowed-hours window; transfer queue is lower priority than anything the session needs |
| R6 | Core changes (C1–C7) land late or are rejected, leaving the plugin without change tracking | They are small and mechanical, but they are the critical path; the PSD is reviewed with them in view (Section 13, Q2). A degraded fallback (full-table compare by content hash) is possible but slower and cannot propagate deletions |
| R7 | Version skew makes a sync half-apply | Handshake (L8), per-table all-or-nothing apply inside a database transaction |

## 11. Success Criteria (Scope-Level)

- A node that has not been approved on the Master cannot obtain any data from it, and cannot present a forged or revoked token.
- A freshly paired node, after its first full sync, has configuration identical to the Master's apart from the node-local list, and starts a session using it.
- A change made on one node reaches the Master and every other connected node promptly, and a node that was off receives it at its next start, with only changed records transferred.
- Entering `localhost` as an INDI, Alpaca or PHD2 address is refused.
- A sync never changes configuration under a running session.
- Disabling the plugin leaves no listener, no queue worker and no UI.

## 12. Glossary

| Term | Meaning |
|---|---|
| **Node** | One Galileo installation with its own database and Library |
| **Master** | The hub: the node other nodes designate, in this plugin's Options, as their replication partner and data destination |
| **Spoke** | A node that has a Master |
| **Change set** | The additions, changes and tombstones for the replicable tables since a given revision |
| **Revision** | A Master-issued, monotonically increasing counter stamped on every changed replicable record |
| **Node-local** | A configuration item that is meaningful only on one node and so is not replicated by default |
| **Connect Link** | The proposed shared core facility (Section 6.2) carrying NodeConnect's and MobileConnect's traffic |

## 13. Decisions from Review and Remaining Questions

### 13.1 Decided (review of 2026-10-27)

| # | Decision |
|---|---|
| D1 | Connect Link is a **core service** (new `LINK` domain), offered to plugins through `PluginContext` |
| D2 | Core additions C1–C4 are accepted; C5 (no `localhost`) was added at review |
| D3 | **Two-way replication is initial scope**, not deferred |
| D4 | Removing images from a node after verified receipt is a **setting on the NodeConnect Options page** |
| D5 | The Master **pushes** changes to nodes as well as being pulled from, and each node ships its changes to the Master when made; the topology is hub-and-spoke |
| D6 | The one-shot copy mode is **removed from scope**; a new node is brought up to date by its first full sync |
| D7 | Data flow is **asynchronous**: a detached node updates the Master on reconnection |
| D8 | Pairing is requested by the node, **approved on the Master**, and yields a token required for all later communication |
| D9 | Device and PHD2 addresses may never be `localhost` (C5) |
| D10 | **No hostname guard.** Only loopback (`localhost`, `127.0.0.0/8`, `::1`, `0.0.0.0`) is refused; a node's own hostname is accepted, since a service may reside on a node that other nodes access |
| D11 | **Replication is transparent**: there is no manual "apply now" step or override. Changes are held only while a session runs and then applied automatically; the user sees the result in the status view and run report, not a prompt |
| D12 | **Core owns the sync tables** (C6): NodeConnect does not ship its own migrations |
| D13 | **C1 is extended** with `dirty` and `base_rev` and a write hook, over the PSD's timestamp, revision and tombstone |
| D14 | **Images removed from a node stay listed as *On Master* and can be retrieved** (C7, NCON-480/490), with the `data.pull` scope |
| D15 | **A node can be deleted on the Master**, which revokes it, removes its sync state and releases the tombstones it was holding back; a returning node pairs again and takes a full sync |
| D16 | **Master redundancy and promotion are deferred to v2** |

### 13.2 Remaining

| # | Question | Recommendation |
|---|---|---|
| Q1 | *(Resolved: yes, SRS NCON-200.)* Should the Master accept changes from nodes while it is itself in a session? | Yes — received and stored at once, applied after the Master's session |
| Q2 | Are per-node category filters wanted (e.g. a field Pi that should not take the Master's notification settings)? | Not in v1; the node-local list and per-item opt-in cover it, and filters add a second axis of configuration |
