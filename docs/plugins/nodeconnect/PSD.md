# NodeConnect Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — NodeConnect Plugin (node-to-node configuration sync and data transfer) |
| **Document** | PSD (Project Scope Document), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-26 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Sibling plugin** | [MobileConnect PSD](../mobileconnect/PSD.md) — consumes the same Connect Link facility (Section 6) |
| **Downstream documents** | SRS, SDD, RTM — not yet written; to follow this PSD's approval |

---

## 1. Purpose of This Document

This document defines the scope of the **NodeConnect plugin** — a first-party Galileo plugin that lets one Galileo **node** (an installation of Galileo running at a Pier, an observatory or a remote site) replicate its configuration from, and ship its history and images to, another node designated as the **Master**. It follows the same PSD→SRS→SDD→RTM structure as [the core chain](../../PSD.md) and the other plugins' chains ([VSTarget](../vstarget/PSD.md), [AllSkyCam](../allskycam/PSD.md), …), and stays above implementation detail; design belongs in the SDD, which is written after this PSD is reviewed.

## 2. Background and Motivation

A user with more than one Galileo installation — a home laptop and a field Raspberry Pi, a remote-observatory node and an indoor processing machine, two Piers each driven by its own small computer — ends up maintaining the same configuration by hand on each: equipment profiles, optical trains, filter offsets, horizon, solver and autofocus settings, notification rules, session templates, plugin options. Every change has to be repeated, and the copies drift.

The data flows the other way as well. A node at the telescope produces session history and FITS frames, but the machine where the user processes, browses and archives them is usually a different one. Today that is a manual copy of folders and, at best, a re-ingest into the Library on the other side.

Galileo already keeps all configuration in one shared database (core's firm rule: *configuration lives in the database, never in JSON files*) and all images in a catalogued Library. That makes both flows tractable without any new storage model: configuration is rows in a known set of tables, and images are files plus catalog rows that carry their own identity.

## 3. Vision Statement

> A Galileo user pairs two nodes once. From then on a configuration change made on the Master appears on every paired node the next time it starts, a new node can be made a faithful copy of an existing one in a single step, and everything a node captures — history, frames, and their catalog entries — arrives at the Master without the user copying a file, even if the link to the Master was down when the frames were taken.

## 4. Goals and Objectives

| # | Goal |
|---|---|
| G1 | Deliver NodeConnect as the `NCON` plugin — a first-party plugin distributed as a ZIP from the Galileo Plugins repository (`PLUG-090`/`PLUG-110`), independently enabled/disabled (`PLUG-060`), not bundled in the installer |
| G2 | **Complete configuration replication.** Every configuration record held in Galileo's shared database — Options settings (`app_settings`), equipment profiles (Piers, optical trains, device configuration), Observatories, horizon points, filter offsets, weather-safety rules, solver/autofocus settings, session templates, scheduler job definitions, and the settings of installed plugins — is replicable, except a short, explicit, user-visible list of **node-local** items (Section 5) |
| G3 | **Sync on startup by last-sync date.** At start-up (and optionally on a schedule), a node asks its Master what has changed since this node's recorded last sync and transfers only that — additions, changes and deletions — then records the new sync point |
| G4 | **Pick-a-direction modes.** *Follow Master* (default: Master is authoritative), *Two-way* (newest change wins, conflicts reported), and a one-shot *Copy to / copy from node* for cloning a node without enrolling it as a follower |
| G5 | **History and image transfer to the Master.** Each node designates a Master in the plugin's page under Options; session history and metrics, FITS frames and their Library catalog rows (`fitsFile`, `fitsSession`, …) are transferred to the Master, resumably, verified by checksum, idempotently (no duplicates if a transfer is repeated), and queued while the Master is unreachable |
| G6 | **Safe by default.** Pairing is explicit and confirmed on both nodes; all traffic is encrypted and authenticated; secrets (API keys, passwords held in settings) are excluded from replication unless the user opts them in; a sync never runs during an active imaging session unless the user allows it |
| G7 | **Visible and recoverable.** A status view (last sync, pending items, last error), a per-run report of what changed, and a pre-sync snapshot of replaced values so a bad sync can be undone |
| G8 | Keep the plugin's own options in Galileo's database, with in-app help for each control (core's definition of done) |

## 5. Non-Goals (Explicitly Out of Scope)

- **No remote control.** NodeConnect moves configuration and data; it does not operate equipment on another node. Controlling a node is [MobileConnect](../mobileconnect/PSD.md)'s purpose, over the same link.
- **No cloud service, relay or account.** Nodes talk to each other directly over the user's network (LAN, or a VPN the user already runs). Reaching a node across the internet is the network's job, not the plugin's.
- **No multi-master consensus.** Each node has at most one Master. A Master serves many nodes. There is no chain of Masters in v1 and no distributed conflict resolution beyond Section 4 G4.
- **No file-level database copy.** Replication is per record through Galileo's own models and migrations, never a copy of the database file; nodes on different schema versions are handled by a handshake (Section 9, PC4), not by copying tables blindly.
- **No translation of node-specific hardware addresses.** The following are **node-local by default** and not replicated: the node's identity and pairing credentials, NodeConnect's own link settings, filesystem paths (Library root, data/cache/log folders), INDI server host/port and Alpaca addresses that point at hardware on one node's own network, and the database location. The user can opt individual node-local items in; the plugin does not try to rewrite them.
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
| L2 | **Pairing**: one-time code / QR shown on one device and entered on the other; yields a per-peer credential and a pinned certificate; revocable per peer | Node↔Master trust | Phone↔node trust |
| L3 | **Scoped permissions** per peer (`config.read`, `config.write`, `data.push`, `control`, `view`) and an audit log of who did what | `config.*`, `data.push` only | `control`, `view` only — never `config.*` |
| L4 | **Discovery** on the LAN (mDNS/zeroconf service advertisement) plus manual address entry | Finding the Master | Finding the node |
| L5 | **Request/response API** with versioned routes that a plugin registers (`/nodeconnect/v1/...`) | Change-set exchange | Operations (Section 6 of the MobileConnect PSD) |
| L6 | **Server-push event stream** (WebSocket) | "Master changed" hints | Live state, progress, alerts |
| L7 | **Resumable, chunked, checksummed binary transfer** in both directions | FITS frames to the Master | Preview images to the phone; frame download |
| L8 | **Version handshake**: Galileo version, plugin API version, schema (migration) level, Connect Link protocol version | Refuse or restrict a sync across incompatible schemas | Tell the app to update |

The Connect Link requirements (`LINK-*`) will be added to the core SRS/SDD if Q1 is accepted. Until then this table is the contract both plugins are designed against.

### 6.3 Other proposed core additions NodeConnect depends on

| # | Addition | Why |
|---|---|---|
| C1 | **Per-record change tracking on replicable tables**: a modification timestamp and a monotonic revision on each row, plus a **tombstone** record for deletions (numbered migration under `galileo/library/migrations/`). Today `app_settings` (`namespace`, `key`, `scope`, `value`) has no modification time, so "changed since last sync" cannot be answered, and a deleted row leaves no trace to propagate | G3 |
| C2 | **A replicable-table registry**: each core model that holds configuration declares itself replicable, with its natural key and its node-local fields. New configuration tables are then replicated by registration, not by editing NodeConnect (the definition of "complete" stays true as Galileo grows) | G2 |
| C3 | **A "settings changed" notification** on the event bus after a bulk apply, so open Options pages and screens reload | G3 |
| C4 | **A busy signal** from the session executor, so a sync can wait out an imaging session | G6 |

## 7. Requirement Domain

One domain, **`NCON`** (NodeConnect), specified in a future SRS. Provisional sub-areas, to be numbered when the SRS is written:

| Area | Covers |
|---|---|
| Roles and pairing | Node, Master, one-shot copy; designating the Master in Options; pairing and revocation |
| Configuration sync | Replicable set, node-local exclusions, last-sync logic, change sets, conflict policy, deletions, secrets, snapshot and undo |
| Startup and scheduling | Sync at start-up, periodic sync, deferral during sessions, retry/backoff |
| History transfer | Session history and metrics to the Master; idempotent merge |
| Image transfer | FITS and catalog rows to the Master; queue, resume, checksum, de-duplication, bandwidth and time-of-day limits, optional local clean-up after verified receipt |
| Status and reporting | Link status, pending queue, per-run report, notifications on failure |
| Options, help and packaging | Options page, in-app help, plugin manifest |

## 8. Stakeholders and Primary Personas

- **The multi-site imager** (core PSD, Observatory Operator persona): a field node and a home node, or a remote observatory and a processing machine, who wants one configuration and one archive.
- **The multi-Pier observatory**: several Piers, each on its own small computer, kept consistent from a single Master, and collecting everything on the Master's Library.
- **The user replacing hardware**: a dead SD card or a new Pi, restored to a working node by *Copy from node* rather than by re-entering everything.

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
| R2 | Two-way mode silently overwrites a deliberate local change | Follow Master is the default; Two-way reports every conflict and keeps the losing value in the snapshot (G7) |
| R3 | A sync lands mid-session and changes a setting the executor is using | Deferred while a session runs (G6, C4); applied between sessions |
| R4 | Secrets leak by being replicated, or are exposed in transit | Excluded by default; encrypted and authenticated transport (L1/L2); never written to the run report or log |
| R5 | A large Library flows over a slow link and starves the node of bandwidth during the night | Bandwidth cap and allowed-hours window; transfer queue is lower priority than anything the session needs |
| R6 | Core changes (C1–C4) land late or are rejected, leaving the plugin without change tracking | They are small and mechanical, but they are the critical path; the PSD is reviewed with them in view (Section 13, Q2). A degraded fallback (full-table compare by content hash) is possible but slower and cannot propagate deletions |
| R7 | Version skew makes a sync half-apply | Handshake (L8), per-table all-or-nothing apply inside a database transaction |

## 11. Success Criteria (Scope-Level)

- Two freshly paired nodes: after *Copy from node*, the new node's replicable configuration is identical to the source's, apart from the node-local list, and the new node starts a session using it.
- A change made on the Master is on a following node after that node's next start, with only the changed records transferred.
- A deletion on the Master removes the record on the follower.
- 1,000 frames captured while the Master was off appear in the Master's Library after it returns, once each, with matching checksums; killing the transfer mid-way and restarting it duplicates nothing and re-sends no completed frame.
- A sync never changes configuration under a running session.
- Disabling the plugin leaves no listener, no queue worker and no UI.

## 12. Glossary

| Term | Meaning |
|---|---|
| **Node** | One Galileo installation with its own database and Library |
| **Master** | The node a given node has designated, in this plugin's Options, as its configuration source and its data destination |
| **Follower** | A node that has a Master |
| **Change set** | The additions, changes and tombstones for the replicable tables since a given revision |
| **Revision** | A Master-issued, monotonically increasing counter stamped on every changed replicable record |
| **Node-local** | A configuration item that is meaningful only on one node and so is not replicated by default |
| **Connect Link** | The proposed shared core facility (Section 6.2) carrying NodeConnect's and MobileConnect's traffic |

## 13. Open Questions for Review

| # | Question | Recommendation |
|---|---|---|
| Q1 | Should Connect Link be a **core service** (new `LINK` domain, offered through `PluginContext`), or a library both plugins bundle? | Core service. One listener, one pairing, one audit log, and security-critical code reviewed once. The cost is a core SRS/SDD addition before either plugin can be completed |
| Q2 | Are the core additions C1–C4 acceptable, in particular a revision/tombstone column on every replicable table? | Yes; they are the only way to make "changed since last sync" exact and to propagate deletions |
| Q3 | Should Follow Master be the only mode in v1, with Two-way deferred? | Ship Follow Master and one-shot copy first (P1); Two-way is P2 because conflict handling is where bugs live |
| Q4 | Should images be removed from the node after verified receipt? | Option, off by default; a field node with a small SD card will want it on |
| Q5 | Should the Master be able to **push** to followers while they are running, or only be pulled from at start-up and on schedule? | Pull-only in v1 (matches "sync on startup"); the event stream (L6) allows a later "Master changed" nudge |
| Q6 | Should one-shot copy include the Library catalog and images, or configuration only? | Configuration only; image movement is the transfer queue's job |
