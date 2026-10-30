# NodeConnect Plugin — SDD (Software Design Description)

| | |
|---|---|
| **Project** | Galileo — NodeConnect Plugin |
| **Document** | SDD (Software Design Description), v0.2, draft — revised after review (Section 8) |
| **Status** | Draft — for review |
| **Date** | 2026-10-29 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md) |
| **Downstream document** | RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SDD](../../SDD.md) |
| **Sibling designs** | [MobileConnect](../mobileconnect/SDD.md) and [WebConnect](../webconnect/PSD.md) share Connect Link with this plugin |

---

## 1. Introduction

### 1.1 Purpose

This SDD describes how the `nodeconnect` package satisfies the requirements in [its SRS](SRS.md): how a node pairs with a Master, how configuration changes are captured, shipped, arbitrated and applied in both directions through the Master, and how history and FITS frames reach the Master through a durable queue.

### 1.2 Scope

The single package `nodeconnect`, its ADRs, data design and wire API. Core architecture is inherited unchanged. Connect Link itself (transport, pairing, tokens, discovery) is a **core service** (PSD D1) and is specified in the core SRS/SDD, not here; this plugin is a client of it.

### 1.3 Design status and prerequisites

The plugin sits on facilities that are **now specified in the core SRS/SDD (2026-10-30: `LINK`, `REPL-010`–`080`, `LIB-200`–`220`, `HIST-050`, `PROF-130`, `GUIDE-100`; core SDD §4.28, §4.32) but not yet built**: Connect Link (CL), per-record change tracking with tombstones (C1), the replicable-table registry (C2), the settings-changed event (C3), the session busy signal (C4), the loopback guard (C5), core-owned sync tables (C6), and the Library *On Master* location state (C7). All are named as ports (Section 3.0) so the plugin can be developed against stubs. Where a port's shape is inferred rather than specified, Section 8 says so.

### 1.4 References

[PSD](PSD.md), [SRS](SRS.md); [Galileo Core SDD](../../SDD.md) Sections 2.3 (concurrency), 4.18 (persistence), 4.20 (`galileo.plugins`); [MobileConnect SDD](../mobileconnect/SDD.md) (shares `LinkPort`).

---

## 2. Design Considerations

### 2.1 The Master Issues Revisions; Nobody Compares Clocks (ADR-NCON-001)

**Decision:** *what changed* is decided by a single monotonic **revision** counter issued by the Master and stamped on every replicable row it commits. A spoke records the highest revision it has applied. The set "changed since this node's last sync" is the rows with `rev > last_rev` plus tombstones with `rev > last_rev`. Wall-clock time is used only to *display* sync times and, corrected by the handshake's measured offset, to order two conflicting edits.

**Rationale:** PC6 forbids trusting clocks across nodes, and a field Raspberry Pi with no RTC and no network at boot is the normal case. A Master-issued counter has no skew, makes incremental sync an indexed range scan, and gives one total order of committed changes. The cost is that a spoke cannot assign final revisions itself, so its local edits wait in an outbox until the Master commits them (ADR-NCON-002).

### 2.2 Spoke Edits Are Dirty Rows Awaiting Arbitration (ADR-NCON-002)

**Decision:** a local write to a replicable row on a spoke marks the row *dirty* and remembers its **base revision** (the revision the edit started from). A dirty row is not overwritten by incoming changes; it is pushed to the Master with its base revision. The Master compares the base revision with the row's current revision: equal → commit and stamp a new revision; unequal → **conflict** (ADR-NCON-004). The Master's answer (the committed or winning row and its revision) comes back through the normal pull/push, clearing the dirty mark.

**Rationale:** it makes conflicts *exact* (a stale base is detectable without clocks, PSD R2), keeps the Master the sole arbiter (hub-and-spoke), and means a detached node simply accumulates dirty rows that are sent on reconnection with no special offline mode (D7). A Master's own local writes are committed immediately with the next revision.

### 2.3 Replicate Through Registered Models by Natural Key (ADR-NCON-003)

**Decision:** every replicable table registers itself in core's registry (C2) with a `ReplicableSpec`: its Peewee model, its **natural key** (never the integer primary key, which differs per node), its node-local fields, its secret fields, its dependencies on other replicable tables, and `to_wire` / `from_wire` functions that translate foreign keys to and from natural keys. NodeConnect knows no table by name; it works only from the registry.

**Rationale:** "complete" configuration replication (G2) must stay true as Galileo grows (C2), and the PSD forbids copying database files. Integer ids differ between nodes, so natural-key references are the only way a Pier's optical trains reattach to the right Pier on another node. The cost is that every core model that holds configuration must write a spec; a test in core (and here) walks the Peewee model list and fails if a model is neither registered nor on an explicit "not configuration" list.

### 2.4 Conflict Rule: Exact Detection, Later Edit Wins, Loser Kept (ADR-NCON-004)

**Decision:** a conflict is detected by a stale base revision. The winner is the edit with the later **offset-corrected** timestamp (the node's timestamp plus the clock offset measured at handshake); ties go to the Master's value. The losing value is written to the snapshot store (Section 3.7) of the node that lost it and listed in the run report. A conflict never blocks a sync.

**Rationale:** SRS `NCON-170` and PSD R2 and D11 (no prompts). Last-writer-wins is the simplest rule with no human in the loop, and because the loser is retained and reported, a wrong guess is recoverable (`NCON-220`). Holding conflicting records for a decision was considered and rejected because it contradicts D11.

### 2.5 Hold While a Session Runs; Stage at Once (ADR-NCON-005)

**Decision:** a node's `ApplyGate` defers *applying* received changes while the session busy signal (C4) is set, and applies them when it clears. Received changes are first written to a durable **inbox** (staging) and acknowledged to the sender, so a Master in a session still accepts pushes immediately (PSD Q1). Locally, nothing is applied under a running session.

**Rationale:** R3 (a sync mid-session must never change a setting the executor is using). Staging makes "accept now, apply later" safe across restarts; acknowledging at staging time means a spoke does not have to retry for the length of a session.

### 2.6 One Queue, Three Kinds, Lowest Priority for Bytes (ADR-NCON-006)

**Decision:** history records, catalog rows and FITS frames all travel through one durable **transfer queue** drained by one worker per Master link, in order: history and catalog rows (small) before frames. The queue is rate-limited by a bandwidth cap and an allowed-hours window, and is throttled further while a session runs. Configuration replication has its own path and is never behind, nor limited by, the queue.

**Rationale:** a night's frames can be gigabytes over a field link, and must not delay a one-line setting change (`NCON-450`), nor starve the session (`NCON-440`). A single queue keeps resume, checksum and de-duplication logic in one place.

### 2.7 Content Hash Is the Identity of an Image (ADR-NCON-007)

**Decision:** a frame is identified for transfer purposes by the SHA-256 of its file contents. The sender asks the Master which hashes it lacks before sending; the Master verifies the hash after receiving and again de-duplicates at commit; a frame the Master already holds is acknowledged without being stored.

**Rationale:** it makes the transfer idempotent whatever the file name, session or path, survives a crash at any point, and implements "verified receipt" (`NCON-430`) exactly, which the optional local-image removal depends on (`NCON-460`).

### 2.9 On Master Is a Library State, Not a Deletion (ADR-NCON-009)

**Decision:** when the remove-after-receipt option deletes a local file, the Library row is kept and its location becomes *On Master* (C7), mirroring the existing cloud-backed state. The frame stays listed with its catalog data, thumbnail and quality metrics, and can be retrieved on demand by content hash.

**Rationale:** removing images to save space on a field node must not make them disappear from the user's catalog or make an unrecoverable decision. Because identity is the content hash (ADR-NCON-007), retrieval needs no extra bookkeeping: it asks the Master for the hash it already recorded and verifies the same way a push does. This adds one narrow scope (`data.pull`) to the node's permissions.

### 2.8 Roles Are Derived and Exclusive (ADR-NCON-008)

**Decision:** a node is a **spoke** when a Master is designated in its Options and a **Master** when at least one spoke is paired with it. The two are mutually exclusive: the plugin refuses to designate a Master while spokes are paired, and refuses to approve a spoke while a Master is designated. There is no persistent "role" setting that can disagree with the pairing table.

**Rationale:** PSD §5 forbids chains of Masters. Deriving the role from facts removes a class of inconsistent states.

---

## 3. Module / Component Design

### 3.0 Ports

Defined in `nodeconnect.ports` as `typing.Protocol` classes; real implementations come from core, stubs in tests.

| Port | Provided by | Operations the plugin uses |
|---|---|---|
| `LinkPort` (CL) | Connect Link (shared with MobileConnect) | register routes/topics; identify caller → principal (peer id, scopes); pairing request/approve/reject/revoke; token storage; discovery (L4); request/response to a peer; event stream push/subscribe; chunked, resumable, checksummed transfer (L7); audit write; handshake extension (L8) |
| `ChangeTrackingPort` (C1) | core persistence | per replicable row: `rev`, `modified`, `dirty`, `base_rev`; tombstones; `dirty_since()`; `on_dirty(callback)`; `commit_rev()` (Master) — see Section 8 P2 |
| `RegistryPort` (C2) | core | `specs()` → list of `ReplicableSpec`; `spec(table)`; the "not configuration" list |
| `SettingsChangedPort` (C3) | core bus | `publish_settings_changed(tables)` after a bulk apply |
| `SessionBusyPort` (C4) | session executor | `is_busy()`; `on_idle(callback)` |
| `LoopbackGuardPort` (C5) | core | `is_loopback(address)` (used only to flag received values) |
| `SyncStorePort` (C6) | core | typed access to the **core-owned** tables for outbox, inbox, snapshots, run reports, transfer queue and per-node sync state; the plugin ships no migrations |
| `LibraryPort` | `galileo.library` | `list_frames()`, `open_frame(hash)`, `ingest(path, metadata)`, `has_hash(hash)`, `set_location(hash, local/on_master, node)`, `delete_local(hash)`, `restore_local(hash, path)`, catalog row export/import (C7) |
| `HistoryPort` | `galileo.history` | export/import session history and metric records |
| `NotifyPort` | core | raise a notification |
| `PluginContext` | `galileo.plugins` | `settings()`, `bus`, panel/Options/help registration |

### 3.1 `nodeconnect.plugin` — Plugin shell and lifecycle

- **`NodeConnectPlugin`** (`PluginBase`): `panel_level = "top"`, `panel_label = "NodeConnect"`; supplies its page and Options page; `activate` builds the object graph and registers its routes and topics with Connect Link; `on_enabled_changed(False)` unregisters routes, stops the `SyncCoordinator` and `TransferWorker`, unsubscribes from the bus and closes event streams, leaving **no listener, worker or UI** (`NCON-310`); re-enabling resumes from persisted state.
- **Manifest:** declares minimum Galileo and plugin-API versions and a hard dependency on Connect Link, so a Galileo release without it refuses to load the plugin with a clear message (`NCON-520`).
- **Fault isolation:** every task is wrapped; an exception in sync, transfer or reporting is logged, recorded in the status view and run report, and never propagates to the session executor, the bus or another plugin (`NCON-530`).
- **Threading:** network, hashing and database apply run on the asyncio loop bridged by `qasync` and on `asyncio.to_thread`; only widgets touch the Qt thread (`NCON-310`, PC3). The plugin is portable: no OS-specific code (`NCON-NFR-040`).
- **Satisfies:** `NCON-010`, `310`, `520`, `530`, `NFR-040`.

### 3.2 `nodeconnect.roles` and `nodeconnect.pairing` — Roles and pairing

- **`RoleGuard`** implements ADR-NCON-008 and the single-Master rule (`NCON-020`).
- **`PairingClient`** (spoke): discovers Masters through `LinkPort` (L4) or accepts a manual address, sends the pairing request with node identity and a short code, then shows the code and waits. Until approval it holds no token and every NodeConnect route on the Master refuses it (`NCON-030`). On approval Connect Link stores the token and pinned certificate node-locally; the plugin never touches them (`NCON-060`).
- **`PairingApproval`** (Master): lists pending and paired nodes with name, address, schema level, last sync and granted scopes; **approve**, **reject**, **revoke**, **delete**. Revoke calls `LinkPort.revoke`, ends the node's event stream and audits. **Delete** (D15) does a revoke if the node is paired, removes the node's `peer_state` and acknowledgement record, and calls `TombstonePruner` (Section 3.5) so the tombstones it was holding back are released; a deleted node that returns must pair again and takes a full sync; a rejected or revoked node's status becomes `rejected`/`revoked` with a readable message and it **stops retrying** (`NCON-040`).
- **Scopes:** the plugin requests only `config.read`, `config.write` and `data.push` and checks the caller's scope on every route; it never requests `control` or `view` (`NCON-050`). Every route call is audited through `LinkPort.audit_write`.
- **Node identity** (`node_id`, a UUID, and display name) is generated once, stored in settings flagged node-local, and excluded from replication, exports, reports and logs (`NCON-060`).
- **Satisfies:** `NCON-020`, `030`, `040`, `050`, `060`.

### 3.3 `nodeconnect.registry` and `nodeconnect.codec` — Replicable set, node-local items, secrets

- **`ReplicableSet`** reads `RegistryPort.specs()` at start and whenever a plugin is installed, producing the dependency-ordered list of tables to sync (`NCON-100`). A table registered later replicates with no change here.
- **`ItemFilter`** decides, per `(table, field)`, whether a value crosses the wire: it drops **node-local** fields (the spec's own, plus the defaults — NodeConnect's link settings, filesystem paths, database location, `node_id`/token) unless the user has opted that item in, and drops **secret** fields (API keys, passwords) unless opted in. Opt-ins are stored in the plugin's settings (`NCON-110`, `210`). Device and PHD2 addresses are ordinary replicable fields; a received value that `LoopbackGuardPort.is_loopback` flags is applied but reported (`NCON-230`, Section 3.6).
- **`Codec`** converts rows to and from the wire form with `spec.to_wire`/`from_wire` (ADR-NCON-003), batches them into pages of at most 200 rows, and never builds a whole table in memory (PC1). A received row is **merged** into the existing row field by field: node-local fields on the receiving node are never overwritten, even when the sender did not send them.
- **Registry coverage test:** a test enumerates all Peewee models and requires each to be registered or on the "not configuration" list, so "complete" stays true (`NCON-100`).
- **Satisfies:** `NCON-060` (node-local part), `100`, `110`, `210`.

### 3.4 `nodeconnect.sync` — Sync engine

- **`SyncCoordinator`** is a small state machine: `Idle → Connecting → Handshake → Pulling → Applying → Pushing → Idle`, with `Backoff` and `Blocked(reason)` (revoked, incompatible, no Master). Triggers: application start-up, link (re)connection, a debounced (2 s) local dirty notification, and a Master `changes` push. It runs without blocking start-up (`NCON-300`). A failure enters `Backoff` with exponential delay from 5 s to 15 min plus jitter, and resumes from the last **committed** point, since each page applies in its own transaction and `last_rev` advances only after a page commits.
- **Start-up sync (`NCON-120`):** handshake (Section 3.8) → `GET changes?since=<last_rev>` in pages → stage in the inbox (3.6) → apply → push the outbox → record the new `last_rev`. Only additions, changes and tombstones above `last_rev` cross the wire.
- **First sync (`NCON-130`):** a node with no `last_rev` performs a **full** sync of every replicable table, in dependency order. Before the first full apply it computes a **dry-run preview** locally (counts of rows to add/replace/leave per table, with samples) from the staged inbox and shows it; the apply proceeds when the user continues or after the preview has been shown for a dry-run-only setting. An incremental sync never repeats the preview.
- **Shipping local changes (`NCON-140`):** `Outbox` holds one entry per dirty row (table, natural key, `base_rev`, wire payload, local timestamp, tombstone flag), durable in the shared database. `ChangeTrackingPort.on_dirty` wakes the coordinator, which pushes in pages; if the Master is unreachable the entries stay queued. Changes that arrived by sync apply are written with `dirty = 0` and are therefore never shipped back (a sync apply holds a re-entrancy flag so C1's hook ignores it).
- **Master push (`NCON-150`):** on the Master, a committed change (its own, or arbitrated from a node) is broadcast to every other connected node as a `changes` message on the event stream, excluding the originator; payloads up to 64 KB are inline, larger sets send only a `pull_hint(rev)` and the node pulls. Disconnected nodes receive the change at their next start-up or reconnection through the same `since=<last_rev>` pull.
- **Satisfies:** `NCON-120`, `130`, `140`, `150`, `300`, `NFR-010`.

### 3.5 `nodeconnect.conflict` and `nodeconnect.tombstones` — Arbitration and deletions

- **`Arbiter`** (Master) processes a pushed change: if `change.base_rev == row.rev` → commit with the next revision. Otherwise a **conflict**: compute the winner by ADR-NCON-004, commit the winning value with the next revision, snapshot the losing value (on the Master if the node's edit lost; the response tells the node to snapshot its own overwritten value if the Master's lost the comparison), and add the conflict to the run report. Arbitration is serialised per table so revisions are assigned in a single order (`NCON-160`, `170`).
- **`ClockOffset`** (Section 3.8) supplies the correction applied to a node's timestamps.
- **Tombstones (`NCON-180`):** a deletion is a tombstone row with a revision and travels as an ordinary change. The Master keeps `peer_ack(node_id) = highest revision acknowledged`; `TombstonePruner` removes tombstones with `rev <= min(peer_ack over paired, non-revoked nodes)`, so no paired node can miss a deletion. Deleting a node (`NCON-040`) removes it from the minimum immediately and discards the tombstones only it was holding back; a revoked but not deleted node still holds them. No maximum-age rule is added.
- **Delete versus edit:** a push that edits a row the Master has tombstoned (or deletes one it has edited) is a conflict decided by the same rule; the losing form is snapshotted.
- **Satisfies:** `NCON-040` (delete), `160`, `170`, `180`.

### 3.6 `nodeconnect.apply` — Transactional apply, session gate, safety checks

- **`Inbox`**: durable staging table; every received change set is written here and **acknowledged** (ADR-NCON-005) before any apply.
- **`ApplyGate`**: if `SessionBusyPort.is_busy()` the gate holds the staged sets and subscribes to `on_idle`; otherwise it applies. There is no manual "apply now" and no per-change prompt (D11, `NCON-200`). A Master in a session still accepts and stages pushes, and arbitrates when it applies.
- **`Applier`**: for each table in dependency order, in **one database transaction**, merge the staged rows by natural key through `spec.from_wire` (`NCON-190`). A failure rolls that table back and the set is retried or reported; other tables already committed stay committed (per-table all-or-nothing, `NCON-305`). A child whose parent is not yet present is deferred to the next pass and reported, never inserted with a dangling reference. Before replacing or deleting a value the applier asks `SnapshotStore` to record it (Section 3.7). After a bulk apply it publishes the settings-changed event (C3) with the affected tables so open pages reload; applies originating from sync set the re-entrancy flag so they are not re-shipped.
- **Loopback flag:** a received device or PHD2 address that C5 flags is applied but listed in the run report; the applier never rewrites it (`NCON-230`).
- **Satisfies:** `NCON-190`, `200`, `230`, `NFR-010`.

### 3.7 `nodeconnect.snapshot` and `nodeconnect.report` — Undo and reporting

- **`SnapshotStore`**: before each apply, writes the old value of every row about to be replaced or deleted into `nc_snapshot(run_id, table, natural_key, old_value, kind)`. **Restore** of a chosen run writes those values back as ordinary local edits (dirty rows), so the restore itself replicates normally (`NCON-220`). Snapshots are pruned by user-configurable age and count. Secret fields in snapshots are stored through the secret store, never in the clear in the table.
- **`RunReport`**: one `nc_run` row per sync with direction, times, revision range, per-table counts of added/changed/deleted, conflicts and winners, items deferred or skipped (version skew, session in progress, loopback flags, parent missing) and errors. Secret values are never written (the `Codec` marks them, and `RunReport` stores only that a secret field changed). Retention is limited by option (`NCON-320`).
- **Satisfies:** `NCON-170` (loser retained), `220`, `320`.

### 3.8 `nodeconnect.compat` — Handshake, compatibility, clock offset

- **`Handshake`**: before every sync, exchange Galileo version, plugin-API version, schema (migration) level, Connect Link protocol version (L8) and, per replicable table, a **column fingerprint**. `ClockOffset` is measured with a round trip (client send time, server receive/send times, client receive time → offset and error bound), re-measured every handshake (`NCON-160`).
- **`CompatPolicy.decide(local, remote)`** returns `full` (equal schema level), `partial(tables)` (tables whose fingerprints match; the rest reported, e.g. a Pi node older than the Master), or `refuse(reason, must_upgrade)` for an incompatible protocol with a clear message. Unknown columns are never guessed at (`NCON-305`).
- **Satisfies:** `NCON-160` (clock part), `305`.

### 3.9 `nodeconnect.transfer` — Image and catalog transfer

| Component | Responsibility | Requirements |
|---|---|---|
| `TransferQueue` | Durable `nc_transfer` table: kind (`history`, `catalog`, `frame`), reference, content hash, bytes total and acknowledged, state (`queued`, `sending`, `acked`, `verified`, `failed`), attempts. Fed from the bus (`frame written`, `session ended`) and by a **scan** at first pairing and on demand (`LibraryPort.list_frames()`; `POST /have` returns the hashes the Master lacks) | `410`, `420` |
| `TransferWorker` | One worker per Master link; drains history/catalog before frames; runs only when the link is up; uses `LinkPort` L7 chunked transfer **streaming** from disk with a few fixed-size buffers (no whole frame or table in memory); resumes from `bytes_acked`; a lost connection never loses queue state | `410`, `430`, `440`, `NFR-020` |
| `Receiver` (Master) | Accepts chunks into a staging file, verifies SHA-256 against the declared hash, **de-duplicates** (`LibraryPort.has_hash`) and, if new, hands the file to `LibraryPort.ingest` with provenance metadata (origin node, original session) so the Master's normal Library ingest does whatever it already does; no stacking, calibration or re-measurement (`NCON-410`). Acknowledges only after verification (`verified`) | `410`, `430` |
| `HistoryTransfer` (3.10) | Session history/metrics records | `400` |
| `Limits` | Token bucket for the **bandwidth cap**, the **allowed-hours window**, and a reduced rate while the session busy signal is set; the worker pauses outside the window. Configuration replication does not use `Limits` | `440`, `450` |
| `LocalCleaner` | When the **remove-after-receipt** option is on (default off), and only for frames in state `verified`: skip a frame referenced by a running session, delete the local file via `LibraryPort.delete_local`, and `set_location(hash, on_master, master)` so the frame stays listed in the Library with its catalog data, thumbnail and metrics. Never runs on `acked` but unverified frames | `460`, `480` |
| `RetrievalService` | Retrieves On Master frames (ADR-NCON-009): for each hash, `GET /frame/{hash}` over L7 in the reverse direction (scope `data.pull`), streamed to a staging file, SHA-256 verified, moved into the Library via `LibraryPort.restore_local`, location set back to *Local*. Subject to `Limits`, queued in `nc_transfer` (kind `retrieve`) so it resumes after a drop, and invoked by the Library's *Retrieve* action and wherever the Library needs the file (open, process). Fails with a readable reason if the Master is unreachable or no longer holds the hash | `490` |
| (Library merge rule) | Catalog rows travel with the frame; the Master merges by content hash and natural key (`fitsSession`) and does not reconcile user-edited fields of two grown Libraries | `470` |

- **Detached operation:** capture, history and queueing continue with the Master unreachable; on reconnection the worker drains the queue (`NCON-440`, PC5).
- **Satisfies:** `NCON-410`, `420`, `430`, `440`, `450`, `460`, `470`, `480`, `490`, `NFR-020`.

### 3.10 `nodeconnect.history` — Session history and metrics

- Session history and metric records are exported by `HistoryPort` as **append-style** records keyed by `(origin_node_id, local_key)`, so two nodes' histories never collide on the Master (`NCON-400`). `HistoryTransfer` enqueues new/changed records on `session ended`, and the Master's importer **upserts** on that composite key, making a record received twice, or after a partial earlier transfer, produce one row. History is one-way (node → Master); it is not part of configuration replication and has no revision or conflict handling.
- **Satisfies:** `NCON-400`.

### 3.11 `nodeconnect.ui` and `nodeconnect.config` — Status, options, help, notifications

- **`NodeConnectConfig`**: plain data, clamped on load: designated Master, node-local opt-ins, secrets opt-in, snapshot and report retention, notification switches, bandwidth cap, allowed-hours window, remove-after-receipt flag; stored under `plugin.NodeConnect` via `PluginContext.settings()` (`NCON-500`, PC2). No file or `QSettings`.
- **`NodeConnectPage`** (top-level section): **Status** (Master and pairing state, connection state, last sync, sync revision, pending configuration changes and transfer queue in counts and bytes, last error), **Runs** (run reports, restore a run), and on the Master **Nodes** (pending/paired list from 3.2). The node-local list and opt-ins appear on the Options page (`NCON-040`, `110`, `330`).
- **Notifications:** `NotifyPort` events when a sync or transfer has been failing longer than the configured period, when a pairing awaits approval on the Master, and when a conflict was resolved; each individually switchable (`NCON-340`).
- **Help:** `nodeconnect/help/plugin.NodeConnectPlugin.md`, one section per control; the help audit runs in the test suite (`NCON-510`).
- **Satisfies:** `NCON-330`, `340`, `500`, `510`.

### 3.12 `nodeconnect.wire` — Wire API

Routes are registered with Connect Link under `/nodeconnect/v1/...` (`LinkPort`, L5). Request/response bodies are pydantic models, and the OpenAPI description is generated from them and checked in a test against the committed file. All traffic uses Connect Link's encrypted, authenticated transport; no route answers a caller without a valid token (`NCON-NFR-030`).

---

## 4. Data Design

| Data | Format | Storage | Lifetime |
|---|---|---|---|
| Plugin options | JSON-valued keys | `app_settings`, namespace `plugin.NodeConnect` (`PLUG-150`) | Persistent |
| Node identity (`node_id`, name), designated Master | Settings flagged node-local | `app_settings` | Persistent; never replicated |
| Pairing token, pinned certificate | Connect Link | Connect Link | Persistent; never read by the plugin |
| Per-row `rev`, `modified`, `dirty`, `base_rev`; tombstones | Columns/tables on replicable tables | Core (C1) | Persistent |
| `nc_peer_state` (node, `last_rev`, `last_sync`, clock offset, schema info; on the Master also `peer_ack`) | Table | Core-owned (C6) | Persistent |
| `nc_outbox`, `nc_inbox` | Tables | Core-owned (C6) | Until acknowledged/applied |
| `nc_snapshot`, `nc_run` | Tables | Core-owned (C6) | Per retention options |
| `nc_transfer` | Table | Core-owned (C6) | Until verified, then pruned |
| FITS frames in transit | Staging files under the Library staging folder | Filesystem (via `galileo.platform` paths) | Until ingested |

The sync tables are created by **numbered core migrations** under `galileo/library/migrations/` (C6, decision D12) and reached only through `SyncStorePort`; the plugin ships no migration. The `fitsFile` location state is a further core migration (C7).

---

## 5. Interface Design

### 5.1 Plugin boundary

Depends only on `galileo.plugins`, the ports of Section 3.0, `galileo.bus` (read/publish through ports) and `galileo.platform` for paths. No import of `galileo.adapters.*`, UI internals (except the help-audit test) or model modules by name — Peewee models are reached only through the registry. External dependency: `pydantic` (already core).

### 5.2 Wire API (`/nodeconnect/v1`)

All routes require an authenticated, paired node; `Master` routes are served only by a Master, `Spoke` routes by a spoke.

| Method & path | Direction | Purpose | Requirements |
|---|---|---|---|
| `POST /handshake` | spoke → Master | Versions, schema level, table fingerprints, clock samples → `full`/`partial`/`refuse`, offset | `305`, `160` |
| `GET /changes?since=<rev>&table=&page=` | spoke → Master | Paged change set (rows and tombstones) above a revision | `120`, `130` |
| `POST /changes` | spoke → Master | Push outbox entries (with `base_rev`, timestamp); response: staged ack, later resolved | `140`, `170` |
| `WS /stream` | Master → spoke | `changes` (inline ≤ 64 KB) and `pull_hint(rev)`; spoke → Master: `ack(rev)` | `150`, `180` |
| `POST /have` | spoke → Master | Hashes of local frames → hashes the Master lacks | `420`, `430` |
| `PUT /frame/{hash}` (L7 chunked) | spoke → Master | Frame transfer; resumable; verified (`data.push`) | `410`, `430` |
| `GET /frame/{hash}` (L7 chunked) | Master → spoke | Retrieve an On Master frame; resumable; verified (`data.pull`) | `490` |
| `POST /history` | spoke → Master | History/metric records (upsert on `(origin, key)`) | `400` |
| `POST /pair`, `GET /pair/{id}` | spoke → Master (Link) | Pairing request and status | `030` |
| `GET /nodes`, `POST /nodes/{id}/approve\|reject\|revoke`, `DELETE /nodes/{id}` | Master UI | Pairing management and node deletion | `040` |

Errors are typed (`unauthorised`, `revoked`, `incompatible`, `busy`, `invalid`, `conflict_resolved`); none is an HTTP 500 for an expected condition.

### 5.3 External interfaces added

None of its own: no listener, socket or file transport. Traffic is Connect Link's.

---

## 6. Concurrency, Failure and Security Notes

- **Atomicity and ordering:** apply is per-table transactional in dependency order; the Master serialises arbitration per table so revisions are one total order; `last_rev` advances only after a page commits, so an interrupted sync resumes without loss or repetition.
- **Idempotence:** pushes carry `(node_id, entry_id)` so a retried push is a no-op; frame transfer is idempotent by content hash; history upserts on a composite key.
- **Durability of intent:** outbox, inbox and transfer queue are in the database, so a power loss on a field node at any point loses nothing it had accepted from the user.
- **Never under a session:** the `ApplyGate` is the only path to the applier.
- **Security:** no route without a token; scopes limited to `config.*`/`data.push`/`data.pull`; secrets excluded by default and never in reports, snapshots in clear, logs or errors; node identity and token node-local; revocation ends the stream at once; pairing requires a person on the Master.
- **Failure of a table:** a table whose apply fails is reported and retried next sync without blocking other tables or imaging.

---

## 7. Requirement-to-Component Map

| Requirements | Component (this SDD) |
|---|---|
| `NCON-010`, `310`, `520`, `530`, `NFR-040` | 3.1 `plugin` |
| `NCON-020`, `030`, `040`, `050`, `060` | 3.2 `roles`/`pairing` (`040` also 3.5; `060` also 3.3) |
| `NCON-100`, `110`, `210` | 3.3 `registry`/`codec` |
| `NCON-120`, `130`, `140`, `150`, `300` | 3.4 `sync` |
| `NCON-160` | 3.5 `conflict`, 3.8 `compat` |
| `NCON-170` | 3.5 `conflict`, 3.7 `snapshot`/`report` |
| `NCON-180` | 3.5 `tombstones` (with 3.2 for node deletion) |
| `NCON-190`, `200`, `230` | 3.6 `apply` |
| `NCON-220`, `320` | 3.7 `snapshot`/`report` |
| `NCON-305` | 3.8 `compat` (with 3.6) |
| `NCON-330`, `340`, `500`, `510` | 3.11 `ui`/`config` |
| `NCON-400` | 3.10 `history` |
| `NCON-410`, `420`, `430`, `440`, `450`, `460`, `470`, `480`, `490`, `NFR-020` | 3.9 `transfer` |
| `NCON-NFR-010` | 3.4 `sync`, 3.6 `apply` |
| `NCON-NFR-030` | 3.12 `wire`, 3.2 `pairing` |

---

## 8. Design Points — Review Outcomes

Resolved at review of 2026-10-29.

| # | Point | Outcome |
|---|---|---|
| P1 | Plugin-owned tables | **Core owns the tables** (C6, D12): numbered core migrations, accessed through `SyncStorePort`. The plugin ships no migration. (MobileConnect's audit store is unaffected: it uses Connect Link's log.) |
| P2 | Shape of C1 | **Extended** with `dirty`, `base_rev` and a write hook (D13). The contract is the one in Section 3.0 and PSD 6.3. |
| P3 | Registry specs (C2) carry real work | Acknowledged. The registry-coverage test (3.3) lists models lacking a natural key. |
| P4 | Library remote-file state | **Adopted**: an *On Master* location state like the cloud-backed state, with retrieval (C7, ADR-NCON-009, `NCON-480`, `490`, scope `data.pull`). |
| P5 | Tombstone retention | **Deleting a node** on the Master releases its tombstones (D15, `NCON-040`, `180`). No maximum-age rule. |
| P6 | Conflict by corrected timestamp | Accepted, including ties within the clock-offset error going to the Master. |
| P7 | History identity | Accepted: `(origin_node_id, local_key)`. |
| P8 | Configuration boundary | Confirmed: Library catalog tables are not configuration and are never in the full sync; the registry boundary matches PSD G2. |
| P9 | Master redundancy | **Deferred to v2** (D16); not designed. |

### 8.1 Remaining dependency to confirm

The *Retrieve* action and the "open or process needs the file" hook live in Library screens, which belong to core (C7); this plugin supplies `RetrievalService` and relies on the Library to call it. The core inline help for the Library will need the On Master state and the Retrieve action when C7 is built.

---

## 9. Path to Traceability Matrix

A row per requirement ID in [this plugin's SRS](SRS.md), mapped to the component above (Section 7) and a `TC-NCON-*` test case ID — see [RTM.md](RTM.md).
