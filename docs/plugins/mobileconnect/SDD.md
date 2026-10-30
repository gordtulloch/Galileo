# MobileConnect Plugin — SDD (Software Design Description)

| | |
|---|---|
| **Project** | Galileo — MobileConnect Plugin |
| **Document** | SDD (Software Design Description), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-29 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md) |
| **Downstream document** | RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SDD](../../SDD.md) |
| **Sibling designs** | [NodeConnect](../nodeconnect/PSD.md) (Connect Link), [WebConnect](../webconnect/PSD.md) (shares the Master relay) |

---

## 1. Introduction

### 1.1 Purpose

This SDD describes how the `mobileconnect` package satisfies the requirements in [its SRS](SRS.md): how a request from a tablet, phone, Meta Quest headset or outreach guest becomes a call on Galileo's own domain services, how state and images flow back, and how safety, lease, audit and outreach confinement are enforced on the Master.

### 1.2 Scope

The single server-side package `mobileconnect`, its ADRs, data design and wire API. The client apps are specified in the [Galileo-MobileConnect](https://github.com/gordtulloch/Galileo-MobileConnect) repository; this document defines only the contract they are written against (Section 5) and the node-side behaviour they rely on. Core architecture is inherited unchanged.

### 1.3 Design status and prerequisites

The plugin is a thin layer over six facilities that **do not exist yet** (SRS Section 2.6): Connect Link (CL), the Control Surface (CS), the control lease (LS), operation-result events (OE), preview rendering (PV), deadman motion (DM), manual focus in the focus module (MF), sky streaming (SK) and the Master relay (WR). The design therefore names them as **ports** (Section 3.0) and codes against the ports; each is built as a stub in the plugin's test suite so the plugin can be developed and tested ahead of core. Where a port's shape is a guess, it is stated in Section 8.

### 1.4 References

[PSD](PSD.md), [SRS](SRS.md); [Galileo Core SDD](../../SDD.md) Sections 2.3 (concurrency), 4.20 (`galileo.plugins`) and 6.3 (plugin API surface); [NodeConnect PSD](../nodeconnect/PSD.md) Section 6.2 (Connect Link).

---

## 2. Design Considerations

### 2.1 A Catalogue-Driven Adapter, Not Per-Module Code (ADR-MCON-001)

**Decision:** the plugin contains no knowledge of the mount, camera, session executor or any other domain service. It exposes whatever the core Control Surface (CS) declares, as a catalogue of operations (name, typed arguments, result, permission class, lease requirement) and of observable state, and invokes an operation by looking it up and calling the handler the owning service registered.

**Rationale:** the alternative — a hand-written route per operation — duplicates core's knowledge in a plugin, drifts as core grows, and was rejected in PSD D1. With a catalogue, a new service operation appears in the apps with no plugin release, and areas an old node lacks are simply absent from the handshake (`MCON-400`). The cost is that the quality of the catalogue (argument types and ranges, permission classes) is a core obligation (SRS O3).

### 2.2 One Pipeline for Every Request (ADR-MCON-002)

**Decision:** every client request, whatever its route or origin (paired client, relayed spoke request, outreach guest), passes through one `Gateway` pipeline of fixed stages: **identify → authorise → validate → lease → confirm → idempotency → dispatch → audit**. No route calls a domain service except through the pipeline's `dispatch` stage.

**Rationale:** the safety properties the SRS demands (role enforced on the Master, never the app, `MCON-120`; no config route, `MCON-130`/`570`; the same interlocks as the desktop, `MCON-700`) are all of the form "nothing bypasses X". A single choke point makes each property one test rather than one test per route, and makes a missed check impossible to add by writing a new handler. Stages are small and independently testable; the order is fixed by the pipeline, not by handlers.

### 2.3 Deny by Default for Guests (ADR-MCON-003)

*(The guest principal type, token and event are provided by Connect Link's outreach facility, D21; this ADR records the rule the Gateway applies to them.)*

**Decision:** outreach guests are a separate *principal type* with an explicit **allowlist** of three operations (offered-Pier list, live image subscription, Pier switch). The Gateway refuses any request from a guest principal that is not on the allowlist before the catalogue is consulted, and a guest never receives the catalogue.

**Rationale:** outreach is the one door that opens without per-device approval (PSD D18). If it were modelled as a very-low-permission *role* it would be one catalogue entry mis-classified away from exposing an operation. A principal type with an allowlist inverts that: a new operation is invisible to guests unless someone deliberately adds it to the list in `outreach/allowlist.py`, and the allowlist is a three-line file that review can read.

### 2.4 Push with Sequence Numbers; Snapshot Then Delta (ADR-MCON-004)

**Decision:** each client has one outbound queue on the Connect Link event stream. On connection it receives a full **snapshot** of every Pier it may see, then **deltas** carrying a per-stream monotonic sequence number. The hub keeps a bounded **replay ring** of recent deltas; a reconnecting client states its last sequence and receives the missed deltas if still in the ring, otherwise a fresh snapshot. State deltas for the same key are **coalesced** while a client's queue is backed up.

**Rationale:** `MCON-300`/`310`/`350` require live state without polling, quick start and no stale state shown as current. Coalescing bounds memory for a slow or sleeping client (a phone in a pocket, a headset taken off) and means a slow client cannot back-pressure the bus. Sequence numbers make the "never show stale as current" test exact. Events that must not be coalesced (alerts, operation start/progress/finish) are marked `reliable` and kept in order.

### 2.5 The Master Relays; Spokes Render (ADR-MCON-005)

**Decision:** for a spoke's Pier the Master forwards the request over Connect Link to the owning node, which runs its own pipeline stages that matter (lease, safety, audit) and returns the result; previews are rendered on the owning node and relayed as bytes. The relay is a **port** (`RelayPort`) whose implementation is shared with WebConnect (SRS `WR`).

**Rationale:** (PSD §6.6) one connection, one lease model and one audit log for the client, with the lease living on the spoke so its desktop, this plugin and WebConnect contend through one authority (`MCON-230`). Rendering on the owner avoids moving frames to the Master and re-rendering. The cost — relay stops when the Master is down — is accepted by PSD §6.6.

### 2.6 Confirmation by Two-Step Request (ADR-MCON-006)

**Decision:** an operation whose permission class is *confirm* is first answered `confirmation_required` with a single-use **confirmation token** bound to the client, the operation, a hash of its arguments, and a short expiry (default 30 s). The operation executes only when a second request presents that token. The client's dialog is a courtesy.

**Rationale:** `MCON-180` requires the confirmation to be enforced by the protocol, not the app. Binding to the argument hash stops a confirmed "park" being replayed as a different operation. Emergency operations (`MCON-710`) are the one class that skips the second round trip once the client has confirmed by its own gesture, because a second round trip during an emergency is itself a hazard; they carry a client-side confirmation flag the Gateway accepts only from an Operator.

### 2.7 Load Is Governed Centrally, With a Strict Priority Order (ADR-MCON-007)

**Decision:** a single `LoadGovernor` classifies every unit of work into one of five classes, in descending priority: **Emergency** > **session-critical** (operations, lease, safety state) > **paired state and events** > **previews and tiles** > **sky streaming and outreach guests**. Lower classes are rate-limited by token buckets whose rates fall as the Master's busy signal (a running session, CPU load) rises, and are the first dropped under pressure. Concurrent sky-streaming clients and concurrent guests are bounded by admission control.

**Rationale:** the Pi-class Master must not be disturbed by a phone (`MCON-080`), VR streaming must yield to a session (`MCON-680`), guests must be lowest of all (`MCON-1280`), and one noisy client must not affect another (`MCON-770`). Spreading these across handlers would give inconsistent behaviour; one governor makes the order a single table.

### 2.8 Audit Through the Connect Link Audit Log (ADR-MCON-008)

**Decision:** the plugin writes its audit records (client, role, Pier, operation, arguments with secrets elided, outcome) into the Connect Link audit log (L3) using a plugin record type, and queries them back for the plugin page. It does not create its own audit table.

**Rationale:** core's rule is that schema changes are numbered migrations, and AllSkyCam shows a plugin can ship with no table; reusing L3's log avoids needing plugin-owned migrations (Section 8, P1) and gives one audit view across NodeConnect, MobileConnect and WebConnect. If L3's store cannot carry the fields or the retention, the fallback is a core-provided plugin audit table, not a plugin-private file (PSD PC2).

### 2.9 Outreach Secrets and Tokens Live in Memory Only (ADR-MCON-009)

**Decision:** (now implemented by Connect Link's outreach facility, L9, D21) the per-event secret and every guest token are held in memory, the secret as a salted hash after display; they are never written to the database or a file. The only persisted outreach data are the owner's options and the aggregate audit entries.

**Rationale:** a Master restart must void every guest, and the safest implementation of "voids" is that the credentials never existed anywhere durable. It also leaves nothing to leak from a backup. The cost is that a restart mid-event ends the event, which is the specified behaviour. This plugin relies on, and tests through its surface, that the facility behaves this way.

### 2.10 Previews for Guests Are Re-Encoded from Pixels (ADR-MCON-010)

*(Implemented in core with the outreach facility, D21, as a guest mode of the preview service; recorded here because the app surface depends on it.)*

**Decision:** the guest preview path takes the core renderer's *pixel* output and encodes the JPEG itself, never forwarding a file or a header block; a final `assert_clean` step rejects any output containing EXIF/APP segments beyond the minimum, as a defence against a future renderer change.

**Rationale:** `MCON-1270` forbids disclosing site location and equipment. Stripping metadata from a file is error-prone; building the output from pixels makes the metadata absent by construction and the check a safety net.

---

## 3. Module / Component Design

### 3.0 Ports (the plugin's view of its prerequisites)

All live in `mobileconnect.ports` as `typing.Protocol` classes. Real implementations are supplied by core/Connect Link when they exist; tests supply stubs.

| Port | Provided by | Operations the plugin uses |
|---|---|---|
| `LinkPort` (CL) | Connect Link | register routes and topics; identify caller → `Principal` (peer id, scopes, source address); issue/revoke tokens; guest enrolment and guest-token issue (event-scoped); event-stream publish to a peer; chunked transfer; audit write/query; peer metadata; capability handshake extension |
| `ControlSurfacePort` (CS) | core | `catalogue()`, `invoke(name, args, pier, principal)`, `observable_state(pier)`, `subscribe(pier, callback)` |
| `LeasePort` (LS) | core | `acquire(pier, holder)`, `release`, `holder(pier)`, `take(pier, holder)`; lease-changed callback |
| `OperationEventsPort` (OE) | core bus | started/progress/finished with correlation id |
| `PreviewPort` (PV) | core | `render(frame_ref, params)` → pixel array; `tile(frame_ref, level, x, y, params)` |
| `HoldPort` (DM) | core | `start_hold(op, args)`, `beat(hold_id)`, `stop(hold_id)`; deadman fires stop |
| `SkyStreamPort` (SK) | core | `catalog(region, limit_mag, lod, cursor)`, `ephemeris(t | range)`, `site()`, `capability()` |
| `RelayPort` (WR) | shared with WebConnect | `piers()`, `call(node, request)`, `events(node)`, `preview(node, ref)`, `reachability(node)` |
| `PluginContext` | `galileo.plugins` | `settings()`, `bus`, `site_location()`, panel and Options registration, help registration |

### 3.1 `mobileconnect.plugin` — Plugin shell and lifecycle

- **`MobileConnectPlugin`** (`PluginBase`): `panel_level = "top"`, `panel_label = "MobileConnect"`, supplies its page and its Options page. `activate` constructs the object graph (Section 3.0 ports → components) and registers routes and topics with Connect Link; `on_enabled_changed(False)` unregisters every route and topic, ends every client and guest session, stops the event hub, governor and outreach manager, and joins workers; re-enabling restores settings and peers without re-pairing (`MCON-040`).
- **Master-only check:** on activation the plugin asks `LinkPort` for the node's role; on a spoke it registers nothing and shows a message that MobileConnect belongs on the Master (`MCON-020`).
- **Isolation:** each client session runs in its own task; the Gateway wraps every handler so an exception becomes a typed error to that client and a log line, never an exception into the session executor or another client (`MCON-060`, `MCON-720`). The plugin opens no listener, port or transport; it only registers with Connect Link (`MCON-030`).
- **Threading:** network handling is on the asyncio loop bridged by `qasync` (core SDD §2.3); blocking calls and rendering go to the same executors the desktop uses for that operation via `asyncio.to_thread` / `run_cpu`; nothing runs on the Qt UI thread except widgets (`MCON-070`).
- **Satisfies:** `MCON-010`, `020`, `030`, `040`, `060`, `070`.

### 3.2 `mobileconnect.gateway` — The request pipeline

`Gateway.handle(request) → Response` implements ADR-MCON-002. Stages, each a small class with `__call__(ctx)` that may short-circuit with a typed error:

| Stage | Behaviour | Requirements |
|---|---|---|
| `Identify` | Obtain the `Principal` from `LinkPort`: `PairedClient(peer, role, platform, client_class)` or `Guest(event_id, token_id, source)`. A request with no principal never reaches the Gateway (Connect Link refuses it) | `MCON-100` |
| `Authorise` | Guest → allowlist check (ADR-MCON-003) and nothing else. Paired → role check: a **Viewer** may call only read-class catalogue entries and subscriptions; refusal carries a reason and is audited. The `config.*` scope is never present on a paired principal and no catalogue entry of class *config* is ever registered (the registry rejects one at startup) | `MCON-110`, `120`, `130`, `1000` |
| `Validate` | Check arguments against the catalogue's declared types and ranges; reject with `invalid` and a field path. Any request naming something outside the catalogue (including anything that would alter a stored definition) is `unavailable` | `MCON-570`, `580` |
| `Lease` | If the entry requires the lease and the principal is not the holder → `refused(lease_held)` naming the holder and offering the take-over confirmation (Section 3.4) | `MCON-140`, `150` |
| `Confirm` | If the entry's class is *confirm* → ADR-MCON-006 (Section 3.5) | `MCON-180` |
| `Idempotency` | Same key from the same client returns the original result (Section 3.5) | `MCON-740` |
| `Dispatch` | Route to `ControlSurfacePort.invoke` (own Pier) or `RelayPort.call` (spoke Pier) under a `LoadGovernor` slot; map any outcome to a typed result (`ok`, `refused`, `invalid`, `unavailable`, `busy`, `unreachable`) with a displayable reason | `MCON-070`, `210`, `750`, `700` |
| `Audit` | Always runs, including on refusal and error (a `finally`): writes the record via `AuditWriter` | `MCON-190` |

The Gateway never catches `BaseException` and never swallows a safety refusal: a refusal from the safety service is returned verbatim as `refused(safety)`. There is no code path that clears an unsafe state or overrides a limit (`MCON-700`).

- **Satisfies:** `MCON-060`, `070`, `100`, `110`, `120`, `130`, `570`, `580`, `700`, `750`, `1000`, `1020`.

### 3.3 `mobileconnect.clients` — Clients, roles and pairing view

- **`ClientRegistry`** wraps Connect Link's peer list with the plugin's metadata, kept in the peer's metadata record (so it is deleted with the peer): `role` (`viewer` default, D6), `expiry`, `platform` (`ios`, `ipados`, `android`, `quest`), `device_model`, `app_version`. The pairing request's identity fields are shown on the Master for approval; the platform is for display and diagnosis and is **never read by `Authorise`** (`MCON-1010`).
- **Role promotion** is a method callable only from the Master's UI controller (`ui.ClientsModel.set_role`), never from a route; there is no wire operation that changes a role (`MCON-110`).
- **Revocation:** `revoke(peer)` asks Link to invalidate the credential, ends the peer's event stream, releases any lease it holds (Section 3.4), cancels any hold (Section 3.13), and records an audit entry; an expired peer is revoked by a timer in the registry. A revoked client must pair anew (`MCON-170`).
- **Satisfies:** `MCON-100`, `110`, `170`, `1010`.

### 3.4 `mobileconnect.lease` — Lease broker

- **`LeaseBroker`** is a thin client over `LeasePort`. It owns only the plugin's side: a per-Pier idle timer (configurable; reset by each lease-requiring operation or lease-keeping heartbeat), release-on-disconnect hooks fed by the session layer, and the take-over flow.
- **Take-over:** if the holder differs, `acquire` returns `held(by=…)`; the Gateway turns this into `refused(lease_held, holder=…, can_take=true)`. A second request with a confirmation token calls `LeasePort.take`; the former holder is notified through its event stream and, if it is the desktop, through the bus (`MCON-150`).
- **Release triggers:** explicit release; the client's event stream closing (disconnect, sleep, headset removed); idle timeout; revocation; plugin disable. No lease outlives its holder's connection (`MCON-140`, `760`).
- **Spoke Piers:** the lease is acquired through the `RelayPort` on the spoke itself; the broker keeps no copy of truth (`MCON-230`).
- **Satisfies:** `MCON-140`, `150`, `230`, `760`.

### 3.5 `mobileconnect.confirm` and `mobileconnect.idempotency`

- **`ConfirmationIssuer`:** issues and redeems tokens per ADR-MCON-006; storage is an in-memory dict with expiry sweep. Tokens are single-use and tied to `(client, operation, args_hash)`. The set of *confirm*-class operations comes from the Control Surface's permission classes; `MCON-180`'s minimum list (abort series, stop session, park, unpark with dome, flip, delete session/job, take lease) is asserted by a startup self-check that fails loudly if the catalogue lacks a *confirm* class on any of them.
- **`IdempotencyStore`:** an in-memory LRU with TTL (default 10 min) keyed `(client, key)` → stored result or in-flight future. A retry while the original is running awaits the same future; after completion it returns the stored result. A Master restart clears it, which is acceptable because in-flight operations do not survive a restart either.
- **Satisfies:** `MCON-180`, `740`.

### 3.6 `mobileconnect.audit` — Audit

- **`AuditWriter`** writes through `LinkPort.audit_write` with the plugin's record type; `AuditReader` queries it with client, Pier, operation, outcome and time filters for the plugin page, honouring the retention option. Arguments are passed through `elide_secrets` (a denylist of argument names declared in the catalogue, plus any value the catalogue marks `secret`). Refusals and errors are recorded; a spoke operation is recorded by the Master and, via the relay, by the owning node (`MCON-240`).
- **Outreach** uses `AuditWriter.event(...)` for event open/close, offered Piers, peaks and totals, and guest counts per Pier; it never records a guest identity (Section 3.14).
- **Satisfies:** `MCON-190`, `240` (spoke side), `1290`.

### 3.7 `mobileconnect.catalogue` and `mobileconnect.dispatch` — Operations

- **`Catalogue`** projects `ControlSurfacePort.catalogue()` to the wire schema: for each entry, `name`, `area` (a row of PSD §6.4), `args` schema, `result`, `class` (`read`, `operate`, `confirm`, `emergency`), `lease` (bool). It adds the node's **area availability** list (an area is available if its CS entries exist) for the handshake (`MCON-400`, `930`). It is rebuilt when a plugin registers a mobile surface (`MCON-560`).
- **`Dispatcher`** is the `Dispatch` stage's implementation. It resolves a name, applies per-run parameters, and invokes. It carries **no per-area code**: areas in SRS 3.5 (`MCON-410`–`550`) are satisfied by their CS entries existing in core and being reachable through it. The plugin's tests assert, area by area, that the catalogue exposes the operations the SRS lists (a *catalogue completeness* test per `MCON-4xx`/`5xx` ID), so a missing core entry is a failing test here rather than a silent gap.
- **Mount connect:** the plugin adds no behaviour; `MCON-421` is satisfied because the CS `mount.connect` entry calls the same service function as the desktop, including the date/time and site sync (a test asserts the sync call occurs when connected via the plugin).
- **Manual focus** is only offered through the focus module's CS entries (`focus.move_relative`, `focus.move_absolute`, `focus.halt`), never a generic focuser entry (`MCON-470`); a startup check rejects a focuser device entry exposing movement.
- **Session and scheduler authoring** (`MCON-500`, `510`) use the CS entries over the same Sessions model; `.gses` import/export is a transfer of a file the user chose, via L7.
- **Satisfies:** `MCON-400`, `410`, `420`, `421`, `430`, `440`, `450`, `460`, `470`, `480`, `490`, `500`, `510`, `520`, `530`, `540`, `550`, `560`, `570`, `580`.

### 3.8 `mobileconnect.state` and `mobileconnect.events` — State and event hub

- **`StateAggregator`** subscribes (on the bus and through `ControlSurfacePort.subscribe`) per exposed Pier and maintains one in-memory `PierState`: the Dashboard activity record (`galileo.dashboard_timeline`, `OBS-150`), device-category status, session progress by block, guiding error, focus state, flip state and time to flip, safety inputs and overall state, weather (`MCON-320`). It stamps each update with the Master's clock so clients can show age (`MCON-350`).
- **`EventHub`** implements ADR-MCON-004: per-client `ClientStream` (bounded queue, coalescing map, last-ack sequence), the shared replay ring (default 2,000 deltas or 60 s), and snapshot construction filtered by what that client may see: the Piers the options expose (`MCON-360`) and the role (a Viewer receives state, not operation results of others). Operation start/progress/finish events from OE are `reliable` and carry the correlation id and the originating request id so the client ties them (`MCON-330`). Alerts are `reliable` and also kept in a bounded recent-alerts list served on request; the hub never claims background delivery (`MCON-340`).
- **Reconnection and suspension:** a stream that closes is not retained beyond the replay ring; a returning client sends its last sequence. A headset taken off or asleep is indistinguishable from a closed stream by design (`MCON-1040`).
- **Bus handling:** handlers run synchronously on the publishing thread (core SDD §2.3), so they only copy into the aggregator and signal the asyncio loop with `call_soon_threadsafe`; no I/O in a bus handler.
- **Satisfies:** `MCON-300`, `310`, `320`, `330`, `340`, `350`, `360`, `1040`.

### 3.9 `mobileconnect.relay` — Master relay adapter

- A thin adapter between the Gateway/EventHub and `RelayPort`. `piers()` merges the Master's Piers with each reachable spoke's (as `PierRef(node, pier)`) into the single list a client sees (`MCON-200`); `call` forwards a request including the originating principal's identity so the spoke can audit it; `events(node)` feeds the spoke's state into the EventHub; `preview` returns bytes rendered on the owner.
- **Grant model:** a spoke appears with `access = control | view | none` according to the opt-in grant it gave the Master; a spoke with `view` only shows its Piers as view-only, with `none` it is absent, and the client is told which (`MCON-220`). Reachability and "last heard" come from `reachability()`; an unreachable spoke's Piers are shown `unreachable(since=…)` and operations to them are refused with that reason; the relay re-attaches when the spoke returns with no re-pairing (`MCON-240`).
- Because the relay implementation is shared with WebConnect (`WR`), its package is owned jointly; this plugin imports it, does not fork it.
- **Satisfies:** `MCON-200`, `210`, `220`, `230`, `240`.

### 3.10 `mobileconnect.previews` — Preview service

- **`PreviewService`** wraps `PreviewPort`. For a paired client it renders to the requested size/quality, clamped to the options and to the client's requested lower quality (`MCON-600`, `630`); for tiles it serves the pyramid levels (`MCON-610`, `670`), with stretch applied in `PreviewPort` on the node so statistics are consistent.
- **Cache:** an LRU keyed by `(frame_ref, params_hash)` bounded by bytes (option), so repeated requests do not re-render. A frame still being written (current exposure) is keyed by its frame id and so naturally replaced.
- **Blink and side-by-side:** the tile API addresses a frame by `frame_ref`, so a client may hold tiles of two frames at once with no server state (`MCON-670`).
- **Transfer:** bytes go out over L7 (chunked, resumable, checksummed) (`MCON-610`).
- **FITS:** the single download route `frames/{id}/fits` is present only for Operator principals, reports size before sending via a `HEAD`-style size call, and is absent from a Viewer's catalogue (`MCON-620`).
- **Guest variant:** `render_guest` follows ADR-MCON-010: pixel array → downscale to the guest size/quality → JPEG encode → `assert_clean`. It is the only preview function a guest principal can reach (Section 3.14).
- **Priority:** rendering runs under the `LoadGovernor` *previews* class (`MCON-630`).
- **Satisfies:** `MCON-600`, `610`, `620`, `630`, `670`, `1060` (node side), `1270`.

### 3.11 `mobileconnect.skystream` — Sky streaming adapter

- **`SkyStreamService`** adapts `SkyStreamPort` to the wire: requests carry `(region, limiting_magnitude, lod, cursor)` and return a **delta-coded binary frame** (objects added/removed relative to the client's previous region at that LOD, positions quantised); progressive responses send bright objects first and refine as the client's cursor advances (`MCON-660`). Ephemeris requests accept an instant or a range; the answer is a sampled time series the client interpolates, so scrubbing needs no further round trips. Every response carries the Master's as-of time and the horizon/site block (changed rarely, versioned so a client re-fetches only on change).
- **Resumption:** the cursor is opaque and stateless (encodes region, LOD and position in the ordering), so a stream interrupted by a headset suspending resumes with no server-side session (`MCON-660`).
- **Availability:** `capability()` reports whether the Master can stream (platform class: PC/Mac vs Pi-class, and measured headroom) and with what limits (maximum LOD, rate, concurrent clients). The handshake publishes this (`MCON-650`); a Pi-class Master reports `sky_stream: {available: false, reason: "master_hardware"}` to a client whose declared class is `quest`, and `reduced` limits to tablets and phones.
- **Admission:** a new streaming client is admitted by the `LoadGovernor` against the concurrent-client cap; a refused client gets a typed `busy` with a reason (`MCON-680`).
- **No client state:** the service holds no per-client catalogue; it is a pure function of the request and the atlas, which also keeps the headset's cache disposable (`MCON-1050`).
- **Satisfies:** `MCON-640`, `650`, `660`, `680`, `1050` (node side).

### 3.12 `mobileconnect.governor` — Load governor

- **`LoadGovernor`** implements ADR-MCON-007. Inputs: the session-busy signal (`ControlSurfacePort`/bus), process CPU load (sampled at 1 Hz), and per-client counters. Per class and per client it owns a token bucket; bucket refill rates are scaled by a pressure factor in [0,1] derived from the inputs; classes below *session-critical* are scaled first and to zero last.
- **API:** `async with governor.slot(cls, client):` waits for or refuses a slot; `governor.admit(kind, client)` for long-lived streaming and guest connections (caps and per-client concurrency).
- **Per-client isolation:** each client has its own bucket in each class, so a flood from one (`MCON-770`) throttles that client and not others; the Emergency class has a reserved lane that is never throttled.
- **Cost on a Pi:** no polling loop; the only periodic work is the 1 Hz load sample and the bucket refill performed lazily on use (`MCON-080`).
- **Satisfies:** `MCON-080`, `630` (priority), `680`, `770`, `1280`.

### 3.13 `mobileconnect.hold` and `mobileconnect.emergency` — Held motion and emergency

- **`HoldController`** handles held manual motion (slew, jog, focuser move). A `hold.start` request goes through the Gateway like any operation (role, lease, confirm if applicable) and then to `HoldPort.start_hold`. The client sends `hold.beat` every **250 ms** over the event stream; `HoldController` forwards each to `HoldPort.beat`. The core deadman stops the motion if no beat arrives within **600 ms**, comfortably inside the one-second bound of `MCON-730`. Independently, the stream closing, the lease being taken, revocation and plugin disable each call `stop` immediately.
- **Headset rule (`MCON-1030`):** the node cannot distinguish a controller button from a gesture; the Quest edition must start `hold.start` only while a controller button is held and stop beating on release. The node's guarantee is the deadman; a test in the app repo verifies the client half.
- **`EmergencyService`** exposes *Stop everything*, *Park* and *Close dome* as catalogue entries of class `emergency`: Operator-only, **lease-free**, never blocked behind the `LoadGovernor`'s throttling (reserved lane), executed in a single round trip once the client sends its confirmation flag, and audited (`MCON-160`, `710`).
- **Disconnects:** `HoldController` and `EmergencyService` subscribe to session-closed notifications; imaging continues untouched on any disconnect, and the only thing a disconnect ever stops is a hold (`MCON-720`).
- **Satisfies:** `MCON-160`, `710`, `720`, `730`, `1030` (node side).

### 3.14 `mobileconnect.outreach` — The app surface of core outreach

The outreach **event** — `OutreachManager` (lifecycle, timer, offered Piers), `QrBuilder` (Wi-Fi and enrolment payloads on the event display), `Enrolment`, `SubnetGuard`, `GuestSessions`, the three-operation allowlist, `LiveImageFeed`, guest-preview rendering (ADR-MCON-010), guest caps and rate limits, and `OutreachAudit` — is hosted in core by Connect Link's outreach facility (L9, decision D21) and shared with WebConnect's browser outreach. Its design is specified with Connect Link in the core SDD; the behaviour this plugin relies on is `MCON-1200`–`1310` (marked "needs OF"). This plugin contributes only the **app surface**:

| Component | Responsibility | Requirements |
|---|---|---|
| `AppOutreachSurface` | Registers with the facility as the surface named `app`: supplies the **enrolment QR payload** (the versioned URI `galileo-outreach://<host>:<port>/v1?e=<event_id>&s=<secret>&n=<ssid>`, which the facility renders beside the Wi-Fi QR on the event display), and declares whether the owner has offered the event to apps. When the owner has not, the facility registers none of this surface's routes | `1210` (payload), `1200` |
| `GuestRoutes` | Maps the facility's three guest operations onto this plugin's Connect Link routes (`/mobileconnect/v1/outreach/piers`, `/stream`, `/switch`, Section 5.2); the enrolment route (`POST /connect/v1/outreach/enrol`) is the facility's own. A guest request is handed to the facility's `Guest` principal and allowlist before it reaches any Gateway code; the Gateway's `Authorise` stage refuses anything else (ADR-MCON-003) | `1240`, `1260` |
| `AppLiveDelivery` | Delivers the facility's guest-sized, metadata-free live images (`image`, `unavailable`, `ended` messages, Section 5.3) over the guest's event stream, and sends the latest image at once on join or switch | `1250`, `1260` |
| `GuestEntryContract` | The contract with the apps' guest entry (Section 3.17): the URI scheme, the enrol call, token held in memory only, "event ended" on stream close | `1330` |

Failure modes stay fail-closed in the facility (no subnet configured, event does not open; secret store lost, event closes). This plugin adds no listener, secret store or token store of its own.

- **Satisfies:** `MCON-1240`, `1250`, `1260`, `1330` (contract); `MCON-1200`–`1230`, `1270`, `1280`, `1290`, `1300`, `1310` via the facility (OF).

### 3.15 `mobileconnect.ui` and `mobileconnect.config` — Options, plugin page, help

- **`MobileConnectConfig`**: plain data with `from_dict` clamping every value (lease idle timeout, audit retention, preview quality/size, cache bytes, guest cap, guest preview size/quality, default event duration), stored under namespace `plugin.MobileConnect` via `PluginContext.settings()` (`PLUG-150`). Per-client role/expiry live in the peer metadata (Section 3.3). The outreach passphrase is stored as a **secret** (core secret store, never in `app_settings` plain, never logged or audited) (`MCON-910`, `1310`).
- **`MobileConnectPage`** (top-level section): tabs for **Clients** (connected: name, platform, role, leases held, connect time; pending approvals; revoke and promote), **Alerts**, **Audit** (filterable), and a short **Outreach** panel that shows whether an event is open, the guest count, and whether the event is offered to apps, linking to the event controls on Connect Link's Outreach page in core (open, extend, end, eject, re-issue the secret, QR codes, time remaining, offered Piers) (`MCON-050`, `1300`).
- **`MobileConnectOptions`** (under Options, `PLUG-170`): the settings above plus the Pier exposure list (`MCON-910`) and, for outreach, only the switch that offers events to apps; the outreach SSID, optional passphrase, subnets, offered Piers, default duration and guest limits (`MCON-1310`) are Connect Link's options in core (OF), shared with WebConnect; nothing applies until **Save**; a subnet field validates as private-range CIDR.
- **Help:** `mobileconnect/help/plugin.MobileConnectPlugin.md`, one section per control; the help audit runs in the test suite (`MCON-940`).
- All widgets read through models fed by signals from the asyncio side; no network work on the UI thread (`MCON-070`).
- **Satisfies:** `MCON-050`, `900`, `910`, `940`, `1300`, `1310`.

### 3.16 `mobileconnect.wire` — Wire API and capability handshake

- **Routes** are registered with Connect Link under `/mobileconnect/v1/...` (Section 5.2). The OpenAPI description (`wire/openapi.yaml`) and the event schema (`wire/events.schema.json`) are **generated from the same Python type definitions the Gateway validates against** (pydantic models), and a test fails if the committed files differ from the generated ones, so the published API cannot drift from the code (`MCON-920`). A breaking change is a new `/v2` with `/v1` retained for the stated period.
- **Capability handshake:** `capabilities()` extends Connect Link's L8 payload with `plugin_api` (the `/mobileconnect/v1` version), `areas` (available operation areas, from the Catalogue), `sky_stream` (Section 3.11), `outreach` (open/closed, remaining time, whether full), and `client_class` echo. An old app is told to update from the version comparison; an old node is detected by a new app from the absence of `areas` (`MCON-930`, `650`, `1320`).
- **Satisfies:** `MCON-400` (catalogue route), `650`, `920`, `930`, `1090` (node side), `1320`.

### 3.17 Client apps — the contract with the app repository

The apps are not part of this package. This section fixes what the node guarantees them and what each requirement of `MCON-800`–`890`, `1000`–`1100` and `1330` asks of the client side; the corresponding rows of the RTM are verified in the app repository.

- **Generated clients:** iOS (Swift) and Android (Kotlin) API clients are generated from `wire/openapi.yaml` and `wire/events.schema.json`; the shared model/logic layer (Kotlin Multiplatform is the candidate), design tokens, icons and localisation strings are maintained once; a shared **protocol test-vector suite** (request/response/event fixtures published from this package's tests) is run against both clients (`MCON-880`).
- **Tablet-first, phone reduced:** a client concern; the node supplies identical data to both (`MCON-810`, `820`).
- **Pairing UX:** discovery (Connect Link L4) or manual address; the app shows the pairing code and waits for approval on the Master; it stores only the issued credential in secure storage (`MCON-830`). It always shows role, lease holder, connection state and state age (`MCON-840`); hides operations a Viewer cannot perform (the node enforces regardless, `MCON-850`); and offers the Emergency operations on every screen.
- **Night theme, store policies, help and About:** client concerns (`MCON-860`, `870`, `890`, `800`).
- **Meta Quest edition:** a distinct app module and SDD in the app repository (rendering stack decided by the Quest 2 spike). To the node it is a paired client with `platform: quest`; it consumes the same catalogue, the sky-streaming service (Section 3.11) and the tile API (Section 3.10). It must start held motion only from a controller button (`MCON-1030`), offer passthrough (`MCON-1070`), run on Quest 2 without Google services and ship through the Horizon Store and SideQuest (`MCON-1080`), and tell the user that a PC/Mac-class Master is needed when the handshake reports streaming unavailable (`MCON-1090`).
- **Outreach guest entry:** the apps handle the `galileo-outreach://` URI (by scanning the QR code or being opened on the outreach network), call `enrol`, then show only the Pier switcher and the live image, hold the guest token only in memory for the event, and display "event ended" when the stream closes (`MCON-1330`). A headset is not a guest client in v1.
- **Satisfies (client side, verified in the app repo):** `MCON-800`–`890`, `1000`, `1030`, `1050`, `1060`, `1070`, `1080`, `1090`, `1100`, `1330`.

---

## 4. Data Design

| Data | Format | Storage | Lifetime |
|---|---|---|---|
| Plugin options (Pier exposure, lease idle timeout, audit retention, preview quality/size and cache bytes, default event duration, guest cap and guest preview size/quality, outreach SSID, subnets, offered Piers) | JSON-valued keys | `app_settings`, namespace `plugin.MobileConnect` (`PLUG-150`) | Persistent |
| Outreach passphrase | Secret | Core secret store | Persistent; never logged or audited |
| Paired clients, tokens, certificates | Connect Link's peer records | Connect Link | Persistent; deleted on revoke |
| Per-client `role`, `expiry`, `platform`, `device_model`, `app_version` | Peer metadata | Connect Link peer record | Same as the peer |
| Audit records | Connect Link audit log (plugin record type) | Shared database via Connect Link | Per retention option |
| Per-Pier live state, replay ring, client queues, confirmation tokens, idempotency results, hold registry | Python objects | Memory | Process |
| Preview cache | Bytes, LRU by size | Memory | Process |
| Outreach event, event secret (hash), guest tokens, guest sessions | Python objects | **Memory only** (ADR-MCON-009) | Event |
| Wire schemas | `openapi.yaml`, `events.schema.json` | Package files, generated | Release |

The plugin adds **no table and no migration** (ADR-MCON-008); if Connect Link's audit store proves insufficient (Section 8, P1) the fallback is a core-provided plugin audit store, not a plugin-private file.

---

## 5. Interface Design

### 5.1 Plugin boundary

Depends only on `galileo.plugins` (`PluginBase`, `PluginContext`), the ports of Section 3.0, `galileo.bus` (read), and `galileo.dashboard_timeline`'s record type. No import of `galileo.adapters.*`, domain-service internals or `galileo.ui.*` internals other than in the help audit test. External Python dependencies: `segno` (QR generation), `pydantic` (already core).

### 5.2 Wire API (`/mobileconnect/v1`)

All routes require an authenticated principal from Connect Link. "Paired" routes require a paired client; "Guest" routes require a guest principal; no route accepts both unless stated.

| Method & path | Principal | Purpose | Requirements |
|---|---|---|---|
| `GET /capabilities` | paired | Handshake extension (Section 3.16) | `930`, `650`, `1320` |
| `GET /catalogue` | paired | Operations by area, with classes and lease flags | `400` |
| `GET /piers` | paired | Observatories and Piers incl. spoke Piers, with access and reachability | `410`, `200`, `220`, `240` |
| `POST /pier/{pier}/ops/{name}` | paired | Invoke an operation (headers `Idempotency-Key`, optional `X-Confirm-Token`); typed result | `410`–`580`, `740`, `180` |
| `POST /pier/{pier}/lease` / `DELETE` | paired (Operator) | Acquire / release; take with confirm token | `140`, `150` |
| `WS /stream` | paired | Snapshot, deltas, operation events, alerts, `hold.beat`; `?last_seq=` to resume | `300`–`360`, `330`, `730` |
| `GET /alerts` | paired | Recent alerts | `340`, `550` |
| `GET /pier/{pier}/preview` | paired | Preview with `w`, `q`, stretch params | `600`, `630` |
| `GET /frame/{id}/tiles/{z}/{x}/{y}` | paired | Pyramid tile | `610`, `670` |
| `GET /frame/{id}/fits` | paired (Operator) | Full FITS, size reported first | `620` |
| `GET /sky/catalog`, `/sky/ephemeris`, `/sky/site` | paired | Sky streaming (Section 3.11) | `640`, `660` |
| `GET /audit` | Master UI only | Audit query for the plugin page | `190` |
| `POST /connect/v1/outreach/enrol` (the facility's own route, `LINK-130`) | none (event secret, subnet-checked) | Exchange the event secret for a guest token | `1220`, `1230` |
| `GET /outreach/piers`, `WS /outreach/stream`, `POST /outreach/switch` | guest | Allowlist (Section 3.14) | `1240`, `1250`, `1260` |

`/outreach/enrol` is the only route reachable without a token, is registered only while an event is open, and answers nothing from outside the outreach subnets. Errors are `{error: refused|invalid|unavailable|busy|unreachable|confirmation_required, reason, detail}`; a typed error is never an HTTP 500 for an expected condition (`MCON-580`, `750`).

### 5.3 Event stream messages

`snapshot`, `delta` (state key, value, seq, as-of), `op.started|progress|finished` (correlation id, request id), `alert`, `lease` (Pier, holder), `access` (spoke access change), `closing(reason)`; client → node: `hold.beat`, `ack(seq)`. Outreach stream: `image` (Pier, JPEG bytes by reference/transfer, age), `unavailable(Pier)`, `ended`.

### 5.4 External interfaces added

None of its own: the plugin adds no listener, socket or file. All traffic is Connect Link's encrypted, authenticated transport (`PC6`); an outreach guest additionally travels only within the owner-designated Wi-Fi subnet.

---

## 6. Concurrency, Failure and Security Notes

- **Isolation:** one task per client stream; handlers wrapped; exceptions to typed errors; a failing client or guest cannot stop another, the session executor or the bus (`MCON-060`).
- **Back-pressure:** per-client bounded queues with coalescing; slow clients are dropped (`closing(slow)`) before they hold memory; the bus is never blocked.
- **Disable/shutdown:** `on_enabled_changed(False)` and application exit close outreach first, then streams, then holds (stop), then unregister routes, then join workers; no lease is left held.
- **Security summary:** deny-by-default guests (ADR-MCON-003); fixed pipeline with no bypass (ADR-MCON-002); no config route registered (the catalogue registry rejects a *config*-class entry); secrets elided from audit; guest secrets and tokens memory-only; outreach confined by source subnet on every message and by fail-closed event opening; previews re-encoded from pixels for guests.
- **Not defended:** a visitor device that is simultaneously on a network reaching the observatory's equipment (the owner's isolated SSID, PSD R15); a physically stolen unlocked client until revoked (`MCON-170`).

---

## 7. Requirement-to-Component Map

| Requirements | Component (this SDD) |
|---|---|
| `MCON-010`–`040`, `060`, `070` | 3.1 `plugin` (with 3.2) |
| `MCON-050`, `900`, `910`, `940`, `1310` | 3.15 `ui`/`config` |
| `MCON-080`, `770`, `1280` | 3.12 `governor` |
| `MCON-100`, `110`, `170`, `1010` | 3.3 `clients` (with 3.2) |
| `MCON-120`, `130`, `570`, `580`, `700`, `750`, `1000`, `1020` | 3.2 `gateway` |
| `MCON-140`, `150`, `230`, `760` | 3.4 `lease` |
| `MCON-160`, `710`, `720`, `730` | 3.13 `hold`/`emergency` |
| `MCON-180`, `740` | 3.5 `confirm`/`idempotency` |
| `MCON-190`, `1290` | 3.6 `audit` |
| `MCON-200`–`240` | 3.9 `relay` |
| `MCON-300`–`360`, `1040` | 3.8 `state`/`events` |
| `MCON-400`, `410`–`580` | 3.7 `catalogue`/`dispatch` (and 3.16 for `400`) |
| `MCON-600`–`630`, `670`, `1270` | 3.10 `previews` |
| `MCON-640`, `650`, `660`, `680` | 3.11 `skystream` (`650` also 3.16; `680` also 3.12) |
| `MCON-920`, `930`, `1320` | 3.16 `wire` |
| `MCON-800`–`890`, `1030`, `1050`, `1060`, `1070`, `1080`, `1090`, `1100`, `1330` | 3.17 client apps (verified in the app repo; node halves in 3.13, 3.10, 3.11, 3.16, 3.14) |
| `MCON-1240`, `1250`, `1260` | 3.14 `outreach` (app surface) |
| `MCON-1200`–`1230`, `1270`, `1280`, `1290`, `1300`, `1310` | Connect Link outreach facility (OF, core); this plugin tests through 3.14 |

---

## 8. Open Design Points

| # | Point |
|---|---|
| P1 | **Audit storage (ADR-MCON-008).** Assumes Connect Link's audit log (L3) can carry the plugin's fields and a configurable retention. If it cannot, the fallback is a **core-owned** audit table (the decision taken for NodeConnect's sync tables, [NodeConnect SDD](../nodeconnect/SDD.md) §8 P1: core owns plugin-needed tables via its own numbered migrations); a plugin-private file or plugin-shipped migration is not an option. |
| P2 | **Port shapes (Section 3.0)** are inferred from the SRS; the Control Surface, lease, preview, deadman, sky-stream and relay interfaces are not written in core, and each could change this design's seams. The stubs in the plugin's tests should be reviewed against core's actual SRS when written (SRS O1). |
| P3 | **Shared relay (`WR`).** Where the Master relay package lives (core, or a shared package distributed with both plugins) and who owns it is undecided; this plugin only consumes `RelayPort`. |
| P4 | **Hold timing.** 250 ms beat / 600 ms deadman are proposals sized for the one-second bound of `MCON-730` on a LAN; they need measuring on Wi-Fi with a headset and a phone. |
| P5 | **Sky-stream encoding.** "Delta-coded, quantised binary" is stated, but the concrete format (and compression) belongs to the Quest SDD in the app repository (PSD Q-13) and the core streaming service; the wire route here carries it opaquely. |
| P6 | **Pi/PC boundary and caps (SRS O9).** The concurrent-stream cap and the criterion for "Pi-class" are to be derived from a measurement, not a platform name; `capability()` is where the number lands. |
| P7 | **Outreach QR format.** Two QR codes (Wi-Fi + enrolment) are specified; a single combined code would need OS-level Wi-Fi join permission in the apps and is not assumed. `segno` as the QR library is a proposal. |
| P8 | **Browser outreach (resolved).** Now in scope through WebConnect (PSD Q3 resolved; [WebConnect PSD](../webconnect/PSD.md) §6.4). It needs the same `OutreachManager`, `SubnetGuard`, allowlist and `render_guest`, so those should not stay private to this plugin: the proposal is to host the event in Connect Link (core) and have each plugin contribute its surface only (WebConnect PSD Q3). **Decided: the event is hosted in core (D21)**, so Section 3.14 now describes only the app surface; the facility itself is specified with Connect Link in the core SDD. |

---

## 9. Path to Traceability Matrix

A row per requirement ID in [this plugin's SRS](SRS.md), mapped to the component above (Section 7) and a `TC-MCON-*` test case ID — see [RTM.md](RTM.md).
