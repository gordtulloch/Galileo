# NodeConnect Plugin — SRS (Software Requirements Specification)

| | |
|---|---|
| **Project** | Galileo — NodeConnect Plugin |
| **Document** | SRS (Software Requirements Specification), v0.2, draft — revised after SDD review (Section 6) |
| **Status** | Draft — for review |
| **Date** | 2026-10-29 |
| **Upstream document** | [PSD (Project Scope Document)](PSD.md), v0.2 |
| **Downstream documents** | [SDD](SDD.md), [RTM](RTM.md) |
| **Parent project** | [Galileo Core SRS](../../SRS.md) |

---

## 1. Introduction

### 1.1 Purpose

This SRS decomposes the `NCON` requirement domain of [this plugin's PSD](PSD.md) into individually numbered, verifiable requirements, structurally parallel to [Galileo core's SRS](../../SRS.md) and the other plugins' SRS documents.

### 1.2 Scope

The `NCON` domain only. What the plugin consumes from core is either an existing requirement (`PLUG`, `LIB`, `HELP`, …), cited by ID, or one of the **proposed core additions** of [PSD Section 6](PSD.md#6-dependencies-on-galileo-core): the Connect Link facility (`LINK-*`, PSD 6.2, decision D1) and the change-tracking, registry, notification, busy-signal, loopback-guard, sync-table and Library-state additions C1–C7 (PSD 6.3, decisions D2, D12, D13, D14). Those are specified in the core SRS, not here; Section 2.6 lists what this SRS assumes of each so the two can be reviewed together.

### 1.3 Requirement ID Convention

`NCON-<###>`, numbered in increments of 10, grouped by the sub-areas of PSD Section 7.

### 1.4 Priority Convention

MVP / P2 / P3, identical to [core SRS Section 1.4](../../SRS.md#14-priority-convention).

### 1.5 Terminology

As the [PSD glossary](PSD.md#12-glossary): **node**, **Master**, **spoke**, **change set**, **revision**, **node-local**, **Connect Link**. "Replicable record" means a row of a table that has registered itself as replicable (C2).

### 1.6 References

[This plugin's PSD](PSD.md); [Galileo Core SRS](../../SRS.md), particularly the `PLUG` and `LIB` domains; [MobileConnect PSD](../mobileconnect/PSD.md) and [WebConnect PSD](../webconnect/PSD.md), the other consumers of Connect Link.

---

## 2. Overall Description

### 2.1 Product Perspective

A first-party plugin distributed as a ZIP from the Galileo Plugins repository and installed through Options > Plugins (`PLUG-090`/`PLUG-110`), independently enabled/disabled (`PLUG-060`) and not bundled in the installer. It registers a handler and versioned routes (`/nodeconnect/v1/...`) with core's Connect Link and does all of its work through `PluginContext` and the event bus; it never imports adapter or UI internals.

### 2.2 Product Functions (Summary)

Pair a node with a Master (request on the node, approval on the Master, token issued); replicate every replicable configuration record in both directions through the Master, by revision, on start-up and whenever a change is made; ship session history, FITS frames and their catalog rows to the Master through a durable, resumable queue; show link status and per-run reports; snapshot replaced values so a sync can be undone; keep its options in the database.

### 2.3 User Classes and Characteristics

The multi-site imager, the multi-Pier observatory operator and the user replacing hardware ([PSD Section 8](PSD.md#8-stakeholders-and-primary-personas)). A user on the Master's machine additionally acts as approver of pairing requests.

### 2.4 Operating Environment

Identical to core, including Raspberry Pi 5-class ARM. Nodes reach one another directly over the user's LAN or a VPN the user runs; no cloud service is involved. Nodes may run different Galileo versions (PSD PC4).

### 2.5 Design and Implementation Constraints

PSD constraints PC1–PC7 apply and are not restated, except where a requirement below makes one testable. In particular: all NodeConnect configuration is in the shared database (PC2); no network or file I/O on the UI thread, and no core import of the plugin (PC3).

### 2.6 Assumptions and Dependencies

| Assumed of core | Detail |
|---|---|
| Connect Link (`LINK-*`) | Provides, per PSD 6.2: an authenticated, encrypted listener (L1); pairing with approval that issues a per-peer token and pinned certificate, with no endpoint answering a caller lacking a token (L2); scoped per-peer permissions including `config.read`, `config.write`, `data.push`, and an audit log (L3); LAN discovery and manual address entry (L4); plugin-registered versioned routes (L5); a server-push stream (L6); resumable, chunked, checksummed binary transfer (L7); and a version handshake reporting Galileo version, plugin API version, schema level and protocol version (L8). NodeConnect adds no transport, TLS or token code of its own. |
| C1 change tracking | Replicable tables carry a modification timestamp, a Master-issued monotonic revision, a `dirty` flag and the `base_rev` an edit started from, with a write hook; deletions leave a tombstone. |
| C2 replicable-table registry | A model declares itself replicable with its natural key and node-local fields. |
| C3 settings-changed event | Published on the event bus after a bulk apply. |
| C4 busy signal | The session executor exposes whether a session is running. |
| C5 loopback guard | Device and PHD2 addresses may not be `localhost`, `127.0.0.0/8`, `::1` or `0.0.0.0` (only loopback; D10). |
| C6 sync tables | Core owns, by numbered migration, the tables NodeConnect needs (outbox, inbox, snapshots, run reports, transfer queue, peer state) and offers them to the plugin through a port. |
| C7 Library location state | `fitsFile` records whether the file is *Local* or *On Master*, with retrieval support, alongside the existing cloud-backed state. |
| Library ingest (`LIB-*`) | The Master receives transferred frames through the normal Library ingest path. |

---

## 3. Functional Requirements

### 3.1 `NCON` — Roles and Pairing

| ID | Requirement | Priority |
|---|---|---|
| NCON-010 | The system shall be delivered as a first-party plugin (domain `NCON`) installable and removable through Options > Plugins, independently enabled/disabled (`PLUG-060`), with a top-level sidebar section (`PLUG-130`) and its own page under Options (`PLUG-170`). | MVP |
| NCON-020 | The system shall let the user designate a **Master** for the node in the plugin's Options page, by discovered service (Connect Link L4) or by manually entered address. A node shall have at most one Master. A node that is itself designated as the Master by others shall serve them; a node shall not be both a spoke and a Master (no chaining). | MVP |
| NCON-030 | The system shall not exchange configuration or data with a Master until the node is **paired**. Pairing shall be requested by the node, shall identify the node and show a short confirmation code, and shall remain pending until a person **approves it on the Master**; only then shall the node be issued its token. Until approved, no NodeConnect route shall return any data to the node. | MVP |
| NCON-040 | The system shall, on the Master, list pending and paired nodes with name, address, schema level, last sync and permissions, and let the user approve, reject, **revoke** or **delete** each. Revocation shall take effect for the next request and shall end any open event stream. A rejected or revoked node shall be told so in a readable status message rather than retrying indefinitely. Deleting a node shall revoke it if paired, remove its record and sync state, and release the tombstones it was holding back (NCON-180); a deleted node that returns shall have to pair again and take a full sync (NCON-130). | MVP |
| NCON-050 | The system shall grant a paired node only the permissions `config.read`, `config.write`, `data.push` and `data.pull` (Connect Link L3) and shall never request `control` or `view`. Every request to the Master shall present the node's token, and every authenticated action shall be recorded in the Connect Link audit log. | MVP |
| NCON-060 | The system shall keep the node's identity, pairing token and pinned certificate node-local: they shall not be replicated, exported, written to a run report, or logged. | MVP |

### 3.2 `NCON` — Configuration Replication

| ID | Requirement | Priority |
|---|---|---|
| NCON-100 | The system shall treat as replicable every table that has registered as replicable (C2), which shall include at least: Options settings (`app_settings`), equipment profiles (Piers, optical trains, device configuration), Observatories, horizon points, filter offsets, weather-safety rules, solver and autofocus settings, session templates, scheduler job definitions, and the settings of installed plugins. A configuration table registered after NodeConnect is installed shall replicate with no change to NodeConnect. | MVP |
| NCON-110 | The system shall exclude **node-local** items from replication by default: the node's identity and token (NCON-060), NodeConnect's own link settings, filesystem paths (Library root, data, cache and log folders) and the database location, plus any field a model marks node-local at registration. The Options page shall list the node-local items and shall let the user opt an individual item in; the plugin shall not rewrite a node-local value it replicates. Device and PHD2 addresses shall be replicated. | MVP |
| NCON-120 | The system shall, at start-up, ask the Master for the change set since the node's last-synced **revision** and apply it, then send the node's own unsent changes, then record the new sync point. Only additions, changes and tombstones since that revision shall be transferred. | MVP |
| NCON-130 | The system shall, when a pairing is first approved, perform a **full** sync in place of an incremental one; this shall be the only way a new or replacement node acquires its configuration, and it shall precede any incremental sync. A full sync shall offer a **dry-run preview** of what would change before it is applied for the first time. | MVP |
| NCON-140 | The system shall, when a replicable record changes on a node, **ship that change to the Master** promptly and, if the Master is unreachable, queue it durably and send it on reconnection or start-up. A change originating from a sync apply shall not be shipped back. | MVP |
| NCON-150 | The system shall, on the Master, **push** every change it holds (its own and those received from nodes) to every other connected node over the Connect Link event stream (L6), excluding the originating node. A node that is not connected shall receive it at its next start-up or reconnection (NCON-120). Nodes shall never communicate with one another directly. | MVP |
| NCON-160 | The system shall decide *what has changed* from the Master-issued revision counter and not by comparing wall clocks. Wall-clock time shall be used only for display and, with the clock offset measured at the handshake, to order two conflicting edits (NCON-170). | MVP |
| NCON-170 | The system shall detect a **conflict** exactly: each change carries the revision it was based on, and a change whose base is not the record's current revision conflicts. The later edit, by offset-corrected timestamp, shall win; the losing value shall be kept in the pre-sync snapshot (NCON-220) and listed in the run report (NCON-320). Conflicts shall never block a sync. | MVP |
| NCON-180 | The system shall propagate **deletions** by tombstone (C1): a record deleted on one node shall be removed on the others, and a tombstone shall not be discarded until every paired node has acknowledged a revision at or beyond it. Deleting a node (NCON-040) removes it from that condition at once, and shall discard the tombstones only it was holding back. | MVP |
| NCON-190 | The system shall apply each table's changes **atomically**, inside a database transaction, so that a failure leaves the table unchanged. Changes shall be applied by natural key through Galileo's own models, never by copying database files. After a bulk apply the system shall publish the settings-changed event (C3) so that open pages and screens reload. | MVP |
| NCON-200 | The system shall **hold** received changes while a session is running on the node (C4) and apply them automatically when it ends; it shall never change configuration under a running session. A Master in a session shall still accept and store changes from nodes at once and apply them after its own session. There shall be no manual "apply now" step or per-change prompt (D11). | MVP |
| NCON-210 | The system shall exclude **secrets** (API keys, passwords and tokens held in settings) from replication by default, and shall replicate a secret only when the user opts that item in on the Options page. Secrets shall never appear in a run report, log, snapshot export or error message. | MVP |
| NCON-220 | The system shall, before applying a change set, store a **snapshot** of every value it is about to replace or delete, and shall let the user restore a chosen run from the status view. A restore shall itself be a recorded change that replicates normally, and snapshots shall be pruned by a user-configurable age and count. | MVP |
| NCON-230 | The system shall, when device and PHD2 addresses in a received change set contain a loopback address (C5), still apply the change but flag the record in the run report. It shall not itself rewrite the address. | P2 |

### 3.3 `NCON` — Startup, Scheduling and Version Compatibility

| ID | Requirement | Priority |
|---|---|---|
| NCON-300 | The system shall start its sync at application start-up without blocking start-up or the UI thread, and shall retry a failed or interrupted sync with exponential back-off while the Master is unreachable, resuming from the last committed point. | MVP |
| NCON-305 | The system shall perform a Connect Link version handshake (L8) before every sync. Where schema levels are equal it shall sync everything replicable. Where the node's schema is older than the Master's it shall sync only the tables both understand and report the rest. Where the Connect Link protocol is incompatible it shall refuse and say why, naming the version that must be upgraded. Unknown columns shall never be guessed at, and a half-applied sync shall not result (per-table all-or-nothing, NCON-190). | MVP |
| NCON-310 | The system shall keep all background activity (link, queue worker, event-stream subscription) off the Qt UI thread, and shall be fully inert while the plugin is disabled: no listener, no queue worker, no subscription and no UI (`PLUG-060`). Re-enabling shall resume from the persisted state. | MVP |

### 3.4 `NCON` — Status and Reporting

| ID | Requirement | Priority |
|---|---|---|
| NCON-320 | The system shall produce a **run report** for every sync recording: direction, time, revision range, counts of records added, changed and deleted per table, conflicts and their winners, items deferred or skipped (version skew, session in progress, loopback flags) and any error. Reports shall be retained under a user-configurable limit and shall omit secret values. | MVP |
| NCON-330 | The system shall provide a **status view** showing: the Master and pairing state, connection state, last successful sync, sync revision, the pending configuration changes and the pending transfer queue (counts and bytes), the last error, and the list of recent run reports. On the Master it shall show each paired node's state as in NCON-040. | MVP |
| NCON-340 | The system shall raise a notification through Galileo's notification service when a sync or transfer has been failing for a user-configurable period, when a pairing request awaits approval on the Master, and when a conflict was resolved. Notifications shall be individually switchable on the Options page. | P2 |

### 3.5 `NCON` — History and Image Transfer

| ID | Requirement | Priority |
|---|---|---|
| NCON-400 | The system shall send each node's **session history and metrics** to the Master asynchronously. The merge on the Master shall be idempotent: a record received twice, or received after a partial earlier transfer, shall produce one record. Records shall be identified so that two nodes' histories never collide on the Master. | MVP |
| NCON-410 | The system shall transfer **FITS frames and their Library catalog rows** (`fitsFile`, `fitsSession`, and related rows) from a node to the Master. FITS shall remain the sole working format; no conversion shall occur in transit. The Master shall ingest through its normal Library ingest path and shall perform no stacking, calibration or re-measurement on receipt. | MVP |
| NCON-420 | The system shall feed the transfer queue from the event bus (`frame written`, `session ended`) and, at first pairing and on demand, from a scan of the node's Library for frames the Master does not hold. The queue shall be **durable** across application and machine restarts, held in the shared database. | MVP |
| NCON-430 | The system shall transfer frames in chunks using Connect Link L7, streamed so that neither a whole frame nor a whole table is held in memory (PC1), with **resume** from the last acknowledged chunk and **verification by checksum** on the Master before acknowledgement. A frame shall be transferred at most once: the Master shall de-duplicate by content hash and a duplicate shall be acknowledged without being stored again. | MVP |
| NCON-440 | The system shall keep a detached node working: capture, history and queueing shall continue with the Master unreachable, and the queue shall drain automatically on reconnection (PC5, D7). Transfer shall run at lower priority than anything a running session needs. | MVP |
| NCON-450 | The system shall provide on the Options page a **bandwidth limit** and an **allowed-hours window** for image transfer. Configuration replication shall not be subject to either. | P2 |
| NCON-460 | The system shall provide on the Options page a setting, **off by default**, to remove a node's local image after it has been verified received by the Master (NCON-430). A frame shall never be removed before verified receipt, a frame referenced by a running session shall never be removed, and the Library catalog row shall be set to the **On Master** state (NCON-480) so the frame stays listed and can be retrieved (D4). | MVP |
| NCON-470 | The system shall not attempt to merge two independently grown Libraries or reconcile user-edited catalog fields beyond those carried by NCON-410. | MVP |
| NCON-480 | The Library shall record, for each frame, a **location state** of *Local* or *On Master* (analogous to the existing cloud-backed state), changed to *On Master* only by NCON-460 after verified receipt and shown in Library screens. A frame that is On Master shall remain listed with its catalog data, thumbnail and quality metrics, and shall be identifiable as such. | MVP |
| NCON-490 | The system shall let the user **retrieve** an On Master frame (one or many) to the node: it shall request the frame from the Master by content hash, transfer it by the resumable, checksummed route of NCON-430 in the reverse direction under the `data.pull` permission, verify it, restore it to the Library and set it back to *Local*. Retrieval shall run under the same bandwidth and time-window limits as NCON-450, shall be offered wherever the Library needs the file (opening or processing it), and shall fail with a readable message if the Master is unreachable or no longer holds the frame. | MVP |

### 3.6 `NCON` — Options, Help and Packaging

| ID | Requirement | Priority |
|---|---|---|
| NCON-500 | The system shall persist all of its own options in Galileo's database through `ctx.settings()` (`PLUG-150`) — never in a plugin-private file or `QSettings` (PC2) — and shall validate and clamp stored values to sane ranges. The options shall include: the Master, the node-local opt-ins, the secrets opt-in, the snapshot and report retention, the notification switches, the bandwidth limit, the allowed-hours window and the local-image removal setting. | MVP |
| NCON-510 | The system shall provide in-app help (`HELP-060`) for every control on its section and its Options page, shipped in the plugin's own help Markdown, and shall pass `python -m galileo.ui.help --audit` clean. | MVP |
| NCON-520 | The system shall ship a manifest declaring its minimum Galileo and plugin-API versions and its dependency on Connect Link, so that a Galileo release that lacks Connect Link refuses to load it with a clear message (`PLUG-020`/`PLUG-030`). | MVP |
| NCON-530 | The system shall isolate faults (`PLUG-050`): a failure in sync, transfer or reporting shall be logged and shown in the status view and shall not affect the application, the session executor or any other plugin. | MVP |

---

## 4. Non-Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| NCON-NFR-010 | A sync of a typical incremental change set (≤ 500 records) shall complete in under 5 seconds on a Raspberry Pi 5-class node over a LAN, excluding image transfer. | P2 |
| NCON-NFR-020 | Memory used by transfer shall be bounded by a small constant number of chunk buffers independent of frame size or queue length. | MVP |
| NCON-NFR-030 | All traffic shall be carried by Connect Link's encrypted, authenticated transport. A request without a valid token, with a revoked token, or with a forged token shall receive no data. | MVP |
| NCON-NFR-040 | The plugin shall contain no platform-specific code and shall run unchanged on Windows, macOS and Linux (including ARM). | MVP |

---

## 5. Requirement Summary Counts (for RTM Seeding)

| Sub-area | Requirement Count | MVP | P2 | P3 |
|---|---|---|---|---|
| Roles and pairing (010–060) | 6 | 6 | 0 | 0 |
| Configuration replication (100–230) | 14 | 13 | 1 | 0 |
| Startup, scheduling, compatibility (300–310) | 3 | 3 | 0 | 0 |
| Status and reporting (320–340) | 3 | 2 | 1 | 0 |
| History and image transfer (400–490) | 10 | 9 | 1 | 0 |
| Options, help, packaging (500–530) | 4 | 4 | 0 | 0 |
| Non-functional (NFR-010–040) | 4 | 3 | 1 | 0 |
| **Total** | **44** | **40** | **4** | **0** |

---

## 6. Open Points for Review

Resolved at review of 2026-10-29: tombstone retention is released by deleting a node (NCON-040, NCON-180); the Library gains an *On Master* location state with retrieval (NCON-480, NCON-490); the corrected-timestamp conflict rule, history identity and the configuration boundary are accepted; Master redundancy is deferred to v2.

1. **Conflict rule (NCON-170):** "later edit wins" follows PSD R2; ties within the measured clock-offset error go to the Master (SDD ADR-NCON-004). Accepted.
2. **Core dependencies:** `LINK-*`, C1–C5 and the new C6 (core-owned sync tables) and C7 (Library location state) must reach the core SRS, SDD and RTM before this SRS's RTM can be verified; they are the critical path (PSD R6).
3. **Retrieval permission:** NCON-490 adds the `data.pull` Connect Link scope, a small extension to L3.

---

## 7. Path to SDD / Traceability Matrix

1. **SDD** — describing how the plugin's modules satisfy the requirements above.
2. **Traceability Matrix** — a row per requirement ID here, mapped to its SDD component and a reserved `TC-NCON-*` test case ID.

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SRS](../../SRS.md).*
