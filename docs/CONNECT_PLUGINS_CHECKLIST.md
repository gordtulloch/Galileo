# NodeConnect / MobileConnect / WebConnect — Implementation Checklist

Tracks the work to build the three "Connect" plugins. Sources: `docs/plugins/{nodeconnect,mobileconnect,webconnect}/{PSD,SRS,SDD,RTM}.md` (design drafts v0.2, 2026-10-29), core SRS §4.24 (`LINK`), core SDD §4.28 (`galileo.connect_link`).

## 0. Where things stand (verified 2026-10-30)

| Item | State |
|---|---|
| Plugin code | **NodeConnect: sync engine and plugin shell built (2026-11-02), no UI yet; uncommitted** — see §3 and its handover notes. `Galileo-Plugins/mobileconnect` holds a README only (no `plugin.toml`, so `build_plugins.py` skips it); `Galileo-Plugins/webconnect` is where WebConnect will be built (README only today; the separate `Galileo-WebConnect` repository is retired, 2026-10-31) |
| Requirements | NCON 45 (41 MVP), MCON 107 (93 MVP), WCON 120 (102 MVP); each has an RTM with reserved `TC-*` IDs |
| Tests | `tests/test_wcon.py` exists: 6 doc-chain tests pass, 120 requirement tests skip (`importorskip`). **No `test_ncon.py` / `test_mcon.py`** |
| Core prerequisites | **Built, tested, not yet wired in (code checked 2026-11-02).** Connect Link L1–L8 and the pipeline: listener, certificates, pairing, permissions/peers/audit, routes, stream, handshake, delegation, transfer (`LINK-070`), discovery (`LINK-040`), `Gateway` (`LINK-230`), Master relay (`LINK-220`), the service with settings/start-stop/disable (`LINK-260`, `LINK-270`) and the outreach facility (`LINK-100`–`210`); the Control Surface registry, state, events, lease, held motion and emergency operations; the preview service; sky streaming; replication support (tracking, tombstones, registry, busy signal, sync tables, revisions); manual focus; the Library *On Master* state with Retrieve; history transfer; the loopback check. **Not built:** a `DeviceAccess` that finds each Pier's connected devices (the catalogue for devices, focus and safety is built and tested but nothing registers it); the other catalogue areas (`CSURF-120`–`210`, `230`, `240`: imaging, sky, solve, guiding, flip, sessions, scheduler, calibration, Library, notifications); any outreach surface; Options > Connect Link (`LINK-250`) and Options > Outreach (`LINK-190`) are built with help; the per-area Control Surface inventory (`CSURF-100`–`240`: no service registers an operation yet); `scheduler_jobs` is the only configuration table not yet replicable; the loopback refusal is applied to every device and PHD2 host field; `HIST-050` is in `SessionHistory` but nothing calls it; `PLUG-200` is done. The Library On Master action is the only part a user can see today. Not measured yet, and not covered by tests: discovery over a real LAN, held-motion timing on Wi-Fi, and sky-streaming/preview speed on a Raspberry Pi 5 |
| App repo | `Galileo-MobileConnect` is the iOS/Android/Quest *apps* (not the plugin): PSD, SRS, a Quest atlas spike. **It stays a separate repository (decided 2026-10-31, MobileConnect PSD D22)** because the apps are developed there. Out of scope here except for the wire contract (§5) |

**Consequence:** the plugins are thin layers over core facilities that do not exist. Each design codes against `typing.Protocol` ports with test stubs, so plugin work can start early, but nothing can be verified end to end until core catches up. Build order below follows that.

## 1. Decisions to close before coding

- [x] **Shared pipeline and relay home** (MCON SDD P3, WCON SDD P1): **decided — both live in core** (`galileo.connect_link`), so the two plugins can't drift. Still to do: record this in MCON SDD P3 / WCON SDD P1 and the core SDD §4.28, and move `Gateway`/relay requirements into core SRS
- [x] **Delegated identity (DG)** (WCON SDD P3): **decided — delegation (option 1).** Connect Link lets a service peer act for a named browser and logs the browser as actor; recorded as core `LINK-090` (outline). Still to do: expand `LINK-090` with Connect Link's design and write `TC-LINK-090`
- [x] **Audit store** (MCON SDD P1): **decided** — Connect Link's audit log carries plugin fields and configurable retention (a Connect Link requirement); core owns the table either way
- [x] **Plugin dependencies in the ZIP**: **decided** — declare them in `plugin.toml` and have `PluginManager.install()` resolve them (no vendored wheels: they break across Windows, macOS and Pi ARM). Core work, tracked in §2d; must land before WebConnect
- [x] **WebConnect repo split**: **decided 2026-10-31 (supersedes the earlier "own repository" decision)** — there is no separate repository. Documents and core facilities live in `Galileo` (`docs/plugins/webconnect/`); the plugin, Flask applications and packaging are built in `Galileo-Plugins/webconnect`; `Galileo-WebConnect` is retired (WebConnect PSD D12)
- [ ] **Role of NodeConnect for the other two:** none by dependency (they need Connect Link, not NodeConnect), so NodeConnect can ship independently
- [ ] Review each port stub against core's real SRS once written (MCON SDD P2, SRS O1)
- [x] **Product decisions** (2026-10-30, recorded in the SRS/SDD open-point tables): sign-in is one-click device-cookie for MVP (PIN later); pairing confirmation code for browsers *and* apps; static server-rendered sky image first, canvas sky view after the operating screens; idempotency keys, event replay and rate limiting stay MVP; no background push alerts in v1; showcase image set deferred to P2; outreach events carry per-surface toggles (apps, browsers); outreach's event-scoped enrolment exception (L2/L3) accepted

## 2. Core prerequisites (in `Galileo`, not the plugins)

**Status 2026-10-30:** the requirements, RTM rows and component designs below are written (ticked `[x] Specified`); the items are *built* only when their code and `TC-*` tests exist. Remaining design depth is noted per item.

Each needs SRS + SDD + RTM rows + tests per CLAUDE.md before the dependent plugin work can be verified.

| Item | Requirements | Core SDD | Spec status |
|---|---|---|---|
| Connect Link L1–L8, delegation, relay, pipeline, audit, Options, secrets, disable | `LINK-010`–`090`, `220`–`270` | §4.28 | [x] Built and tested, including the Options page (`LINK-250`); wire details (OpenAPI) still to be written |
| Outreach facility (L9) | `LINK-100`–`210` | §4.28 | [x] Facility built and tested; **no surface and no Outreach page yet** (`LINK-190` screen) |
| Control Surface, operation events, held motion, emergency | `CSURF-010`–`420` | §4.29 | [x] Registry, schema, events, state, held motion and emergency built and tested; **the per-area inventory `CSURF-100`–`240` is not**: no service registers its operations yet |
| Control lease | `LEASE-010`–`080` | §4.29 | [x] Built and tested (broker, gateway check, spoke-held via the relay); **the desktop does not yet honour or show it** (`LEASE-060`) |
| Preview service | `PREV-010`–`060` | §4.30 | [x] Built and tested; nothing calls it yet (no frame sources are registered) |
| Sky streaming | `SKYSTR-010`–`080` | §4.31 | [x] Built and tested (encoding schema v1 is in code; the Quest SDD must adopt it); nothing calls it yet |
| Replication support (C1–C6) | `REPL-010`–`080`, `PROF-130`, `GUIDE-100` | §4.32, §4.4, §4.14 | [x] Tracking, tombstones, registry, busy signal, settings-changed event, sync tables and revisions built and tested for `app_settings`; **12 other configuration tables are listed as pending registration**; the loopback check exists but is not applied to the UI |
| Library On Master (C7), history transfer form | `LIB-200`–`220`, `HIST-050` | §4.23, §4.17 | [x] Built and tested, including the Library > Images Retrieve action and help; moving frames to a Master awaits NodeConnect |
| Manual focus in the focus module | `FOC-100`–`130` | §4.11 | [x] `ManualFocus` built and tested; the Focus screen uses it; the Control Surface operations for it are not registered yet |
| Plugin dependencies | `PLUG-200` | §4.20 | [x] Specified; `requires` format to be finalised in code |

### 2a. Connect Link — unlocks all three plugins
- [ ] Expand `LINK-010`–`080` from outline to full requirements (the code now exists; the SRS text still needs updating to match it)
- [x] **Built (2026-10-31, tested):** L1 encrypted listener + certificate; L2 pairing with approval, per-peer tokens; L3 scopes + audit log; L5 plugin-registered versioned routes; L6 server-push stream; L4 LAN discovery (`discovery.py`, `TC-LINK-040`, 2026-11-02); L7 resumable chunked SHA-256 transfer (`transfer.py`, `TC-LINK-070`, 2026-11-02); L8 version handshake with plugin extension
- [x] L1–L8 and the shared pipeline are built. Remaining for them: a real-multicast check of discovery on Windows, macOS and Pi (the tests use a fake backend), and a real HTTPS soak with a phone or tablet
- [x] L9 outreach event facility (`LINK-100`–`210`) built and tested (2026-11-02): lifecycle/timer, event secret, subnet guard, guest tokens, caps, aggregate audit, QR payloads and SVG, surface registration. Still to do: a surface (MobileConnect / WebConnect), and the Outreach page (`LINK-190`)
- [x] Delegated identity (`LINK-090`): built in `peers.py` with `TC-LINK-090` tests (service credential, client's own scopes/expiry, refusal of revoked/expired/unknown/other-plugin clients)
- [ ] Still open for `LINK-090`: asserted source address for the browser surface (WCON SDD P5)
- [x] Outreach amendment (event-scoped enrolment L2, `outreach.view` L3, per-surface toggles `LINK-110`/`200`) was already in core SRS `LINK-020`/`030`/`110`/`200`; audit-log plugin fields and retention added to `LINK-030` (2026-10-30)
- [x] Pairing confirmation code added to core `LINK-020` and to `MCON-100` / `WCON-100` (2026-10-30)
- [x] `Delegation`, `PairingConfirmation`, `Gateway`, `MasterRelay` are built (2026-11-02); write the design text in core SDD §4.28 to match the code
- [x] `TC-LINK-090`, `220`, `230`, `240`, `260`, `270` written (2026-11-02); `TC-LINK-250` is partly covered by the service tests, the page itself is not built
- [x] Options > Connect Link page, inline help (`options.connect_link.md`) and wiki section (2026-11-02)
- [x] Options > Outreach page (`LINK-190`) with help, and the live-image feed (`LINK-160`) (2026-11-02). Still to do: a surface to carry it, and a wiki article

### 2b. NodeConnect prerequisites (C1–C7)
- [x] C1 change tracking for `app_settings` (triggers, tombstones, `apply_mode`; migration 034). Add the same to each table as it is registered
- [x] C2 registry with natural keys, node-local/secret fields, row filter and dependency order; coverage test with a visible pending list. 11 configuration tables are now registered (migration 037); only `scheduler_jobs` is pending
- [x] C3 settings-changed event; C4 session busy signal; C5 loopback guard (`is_loopback`). Still to do: Options pages subscribing to reload (C3), calibration runs setting the busy signal (C4), applying the refusal in the device and PHD2 host fields (C5)
- [x] C6 core-owned sync tables (migration 035) and `SyncStore` / `SyncStorePort`
- [x] C7 Library *On Master* state, Retrieve action, `ensure_local` hook, inline help (migration 036). Still to do: call `ensure_local` from the remaining pixel-reading Library operations (quality analysis, calibration)

### 2c. MobileConnect / WebConnect prerequisites
- [x] **CS Control Surface** registry built. the device/focus/safety catalogue is written (`control_surface/catalogue.py`); the other areas and the real `DeviceAccess` remain
- [x] **LS** control lease built; the desktop UI still has to take, show and honour it (`LEASE-060`)
- [x] **OE** operation events (started/progress/finished) built
- [x] **PV** preview service built (stretch, bin, JPEG, tiles, cache, guest mode)
- [x] **DM** deadman built (250 ms / 600 ms defaults, validated); measure on Wi-Fi with a phone and headset
- [x] **MF** manual focus moved into the focus module; the desktop screen uses it
- [x] **SK** sky streaming built (catalog, ephemeris, site, capability, static image)

### 2c-bis. Headless engine and the desktop as a client (`HEAD-010`–`180`, core SDD §4.33)
Specified 2026-11-02 (SRS §4.30, SDD §4.33, RTM, `tests/test_head.py` with 18 reserved tests); **not built**. Needed before WebConnect can run on a controller with no screen. Order (the desktop's own path is touched last):
- [x] **Step 1 built (2026-11-02):** `engine.main`, `engine.lock`, `engine.service`, `Galileo --engine`, and the test that importing the engine never imports `PySide6` (`HEAD-010`, `020`, `030`; `TC-HEAD-010`/`020`/`030`). `HEAD-160` (safety and watchdog in the engine) waits for step 4
- [~] `engine.devices` **built (2026-11-02, `TC-HEAD-040`):** UI-free `DeviceService` (connect/auto-connect per Pier, bus events, time/site push, `DeviceAccess`), started by the engine. **Still to do:** the desktop pages move onto it (they keep their own connections and adapter factory), and a real-hardware check
- [~] `engine.runner` **built (2026-11-02, `TC-HEAD-050`):** `run_session` (shared; the desktop's `_RunThread` now calls it) and `SessionRunner` (asyncio loop, per-Pier runs, bus events, stop/pause/resume, shutdown). **Still to do:** the scheduler tick and safety pause move out of the Qt controller; the engine builds a `SessionContext` from `DeviceService` (today only `ui/session_runner.build_session_context` does, from the desktop's pages), so the engine cannot yet start a session itself
- [~] `engine.helpers` **built (2026-11-02, `TC-HEAD-060`):** pointing poll, weather history, `slew_then_track`, published as `mount.position` / `mount.tracking` / `weather.readings`. **Still to do:** a test of the slew-then-track happy path; the desktop adopts these values (it keeps its own copies until it is the engine's client)
- [~] `engine.channel` + `engine.client` **built (2026-11-02, `TC-HEAD-070/080/110/120/180`):** local channel through `Gateway` (token-authenticated; Unix socket on POSIX, loopback on Windows), lease as `desktop`, version check, event stream, stale/retry. **Still to do:** run the Unix-socket path on Linux/macOS/Pi; the desktop actually uses `EngineClient`; session/scheduler/imaging operations are not in the catalogue yet so the channel cannot start a session
- [~] `engine.embedded` **built (2026-11-03)**: `attach_or_host` hosts an engine or returns a client, with the close rules (`HEAD-090`, `100`). Not yet called from `galileo/app.py`: the desktop still connects its own devices, so wiring it in waits for the desktop to move onto `DeviceService`
- [x] `HEAD-130`/`140` built (2026-11-03, `TC-HEAD-130`/`140`): `engine.config`, last-used Observatory, retry within limit, problems in `--status`. **Still to do:** an Options page for the engine settings
- [~] `HEAD-160` safety + watchdog in the engine **built (2026-11-03, `TC-HEAD-160`)**. **Still to do:** the trip notification (e-mail/SMS) and weather-rule evaluation in the engine; the desktop still runs its own copy of both
- [~] `HEAD-150` unit file written (2026-11-03, `TC-HEAD-150`) in galileo-astroberry `packaging/systemd/`. **Still to do:** run it on an Astroberry image, confirm `User=` and the INDI unit names, package it (enable/disable with the package)
- [x] `HEAD-170` `Galileo --engine --status` (2026-11-03, `TC-HEAD-170`); exit codes 0/3/1, `--json`

### 2d. Plugin loader
- [x] Specified as core `PLUG-200` (SRS, RTM row, SDD §4.20 install step 4a: `requires` in `plugin.toml`, private `.deps/` directory per plugin, rollback on failure, offline refusal)
- [x] Implemented 2026-10-30 in `galileo.plugins` (`install_requirements`, `PluginManifest.requires`); `TC-PLUG-200` in `tests/test_plug.py` (3 tests). No control changed, so no inline-help change.

## 3. Phase A — NodeConnect (needs 2a L1–L8 and 2b only)

Design: `docs/plugins/nodeconnect/SDD.md` §3.1–3.12. Package `nodeconnect`.

**Status 2026-11-02 — built, all in `C:\Users\gordt\Projects\Galileo-Plugins\nodeconnect`, none of it committed.** 59 tests pass (`tests/test_ncon*.py`), ruff clean, `build_plugins.py nodeconnect` builds the ZIP. Run them with the core venv: `cd Galileo-Plugins/nodeconnect && ..\..\Galileo\.venv\Scripts\python -m pytest tests` (Python 3.11; ruff is `python -m ruff`).

- [x] Scaffold: `plugin.toml` (name `nodeconnect`, 0.1.0, api 1–1, `nav_level = "primary"`, `entry_point = "nodeconnect"`), `build_zip.py`, `CHANGELOG.md`, `tests/conftest.py` (markers, autouse `register_defaults`, `settings_db`). No `ports.py`: the plugin imports core's real services (`galileo.replication`, `galileo.connect_link`) and tests use two real databases, so the planned Protocol stubs were dropped
- [x] `plugin` shell (`plugin.py`, `runtime.py`): `NodeConnectPlugin` (name must stay `"NodeConnect"` — it is the settings namespace `plugin.NodeConnect`), `Runtime`, `SyncWorker`. A node with a Master designated is a **spoke** (one background thread, 300 s default via setting `sync_interval_s`, jittered back-off after a failure, `sync_now`, no listener); any other node is a **Master/standalone** (`host.acquire("nodeconnect", NODE_PERMISSIONS, install)`). Disable stops the thread and releases the listener (`NCON-310`); an exception in a pass never kills the worker (`NCON-530`); manifest matches the class (`NCON-520`). `build_runtime(ctx)` wires the real core services and is **untested** (needs a live host)
- [x] `roles` + `pairing` (`NCON-020`–`060`): derived exclusive roles; `PairingDesk`/`PairingClient` wrap core's Connect Link pairing; token in the OS credential store, address and certificate fingerprint in `plugin.NodeConnect` settings; scopes `config.read`, `config.write`, `data.push`, `data.pull`
- [x] `repl` + `codec` (`NCON-100`, `110`, `210`): ported to core's replication registry; node-local/secret `ItemFilter`, 200-row paged codec, field-level merge
- [x] `master`, `sync`, `conflict`, `apply`, `compat`, `store`, `wire`, `link` (`NCON-120`–`230`, `300`, `305`, `320`): see ADRs below
- [~] `snapshot` + `report`: `NodeStore` can save/read snapshots and run reports, but **retention/pruning, the undo action and the report view are not built**
- [x] `transfer` + `history` built (2026-11-02, `TC-NCON-400`–`460`, 59 tests): scan, durable queue by hash, worker, limits, remove-after-receipt, Master-side ingest through the Library (`ingest.py`), history push/upsert (`history.py`), retriever for On Master frames, window/removal controls and help. **Still to do:** feed the queue from the bus (`frame written`; today the per-pass scan queues), a real two-machine run, and the Master keeping a second copy (transfer store + Library) of each frame
- [~] **`ui`/Options built (2026-11-02):** `nodeconnect.ui.NodeConnectOptions` (pairing with confirmation code, approve/reject/revoke/remove, sync now, interval, status) via `build_options_page`, help `help/plugin.NodeConnect.md`, `TC-NCON-330` (59 tests pass). **Still to do:** notifications (`NCON-340`, P2), the full status view (`NCON-330`: last success, revision, queue, run reports) beyond the Options page, a wiki article. Not tried in the running app or against a real Master yet
- [ ] `wire`: write the `/nodeconnect/v1` OpenAPI document (`NCON-NFR-030`); routes are in `wire.py` (handshake, pull, push, ack)
- [ ] `tests/test_ncon.py` has far fewer than the 45 reserved `TC-NCON-*` (tests are spread across `test_ncon*.py`); map every RTM row to a test and add doc-chain tests like `test_wcon.py`
- [ ] Help content, wiki article, `docs/plugins/nodeconnect/` status updates, `plugins.json` entry (**deliberately absent**: `build_plugins.py` adds one pointing at a release that doesn't exist; revert it if it reappears), release `nodeconnect-v<version>` (never dispatch GitHub builds without asking)

**Handover notes (NodeConnect)**

Design decisions already made and implemented — don't revisit without cause:
- The **Master issues revisions** (`RevisionIssuer(is_master)`); no clock comparison decides what changed. A spoke pushes dirty rows with `base_rev`; a stale base revision is the exact conflict signal. On conflict the later edit (clock-offset corrected) wins, a tie goes to the Master, the loser is saved as a snapshot.
- Pulled changes go into an **inbox** and are applied only when no session is running (`ApplyGate`, core's `get_session_busy()`); `apply_mode` suppresses change tracking while applying.
- **Deletions** travel by a per-table tombstone cursor named `"<table>#t"` (the tombstone id). A deletion counts as a change after the row's last revision (the Master arbitrates with `tomb["rev"] + 1`). Tombstones are released by id once every paired node has acknowledged them; tombstones of node-local rows are never sent.
- Core API quirks: `from galileo.replication import registry` is the registry *object* (it shadows the submodule) — use `from galileo.replication.registry import ...` for module-level names. Route handlers are `handler(peer, request)` and return a dict. Parents are named by natural key on the wire; `UnresolvedParent` is a `LookupError`. Tests that need a Pier must use the `make_pier()` helper (a fake `pier_id=0` raises `UnresolvedParent`).
- Core change made for the plugin: `ConnectLinkService.acquire` / `LinkHost.acquire` take `install(server)`, which runs on every listener start (the server is rebuilt each time, so routes registered once would be lost). Test `TC-LINK-270` (a); SDD §4.28.

Known gaps and limits:
- Pull/push database work runs on the event loop. The listener tests use one database, so they cover the network path only; the two-database `World` tests cover the logic.
- A node pulls its own pushed change back once (harmless).
- Cascaded-delete tombstones are untested against origin's triggers (child tombstone keys may not resolve).
- `scheduler_jobs` is not replicated (the one unregistered configuration table).
- The full core suite has not been re-run since the origin merge (only ~230 related tests plus the plugin's 48). Two outreach tests fail only because `segno` is not installed in `.venv`: `pip install -e ".[test,dev]"`.
- Not measured: real two-machine sync, discovery over a real LAN.

Uncommitted state to be aware of (commit only when the user asks):
- Core repo, mine: `galileo/connect_link/service.py`, `galileo/connect_link/host.py`, `tests/test_link_service.py`, `docs/SDD.md` (§4.28 sentence), `CHANGELOG.md`, and this file. Merge commit `e5f68d8` already holds the origin merge.
- Core repo, **not mine — leave alone**: `docs/RTM.md`, `docs/SRS.md`, `docs/UAT*.md`, `docs/plugins/webconnect/{PSD,SDD,SRS}.md`, `galileo/app.py`, the planning/What's-Up pages and help, `galileo/ui/solve*.py`, `tests/test_wut.py`, untracked `galileo/engine/` and `tests/test_head.py`.
- `Galileo-Plugins/nodeconnect/` is entirely uncommitted (new).

## 4. Phase B — shared pipeline + relay (needs 2c, and the §1 home decision)

Design: MCON SDD §3.2–3.13; WCON SDD §3.9. Do this once, before either front end.

- [ ] `Gateway` stages: Identify → Authorise → Validate → Lease → Confirm → Idempotency → Dispatch → Audit (audit in a `finally`); typed results `ok/refused/invalid/unavailable/busy/unreachable`; never swallow a safety refusal (`MCON-700`)
- [ ] `catalogue` registry that rejects any *config*-class entry at startup (`MCON-1000`, `570`, `580`); `dispatch` to `ControlSurfacePort.invoke` or `RelayPort.call`
- [ ] Guest deny-by-default allowlist (ADR-MCON-003); `confirm` two-step tokens; `idempotency`; `LoadGovernor` with strict priority order (`MCON-750`)
- [ ] `lease` broker, `hold` + `emergency` (lease-free, Operator-only, single request)
- [ ] `state` + `events` hub: snapshot then delta with sequence numbers (ADR-MCON-004)
- [ ] `RelayPort` master relay to paired spokes, opt-in per node, spokes render previews (ADR-MCON-005)
- [ ] Contract tests run against both plugins' stubs

## 5. Phase C — MobileConnect plugin (server side only)

Design: `docs/plugins/mobileconnect/SDD.md`. Package `mobileconnect`; the apps live in `Galileo-MobileConnect` and are a separate project.

- [ ] Scaffold `Galileo-Plugins/mobileconnect/` as in Phase A
- [ ] `plugin`, `clients` (viewer default; role promotion only from the Master UI controller, never a route; platform never read by `Authorise`) (`MCON-010`–`070`, `110`, `170`, `1010`)
- [ ] `audit`, `previews` (guest previews re-encoded from pixels, ADR-MCON-010), `skystream`, `governor`
- [ ] `outreach` app surface: owner-supplied enrolment payload, QR codes (`segno` proposed), guest viewer over the L9 facility (`MCON` §3.11)
- [ ] `ui`/`config`: clients page, Options, help; settings in `plugin.MobileConnect` namespace; tokens and secrets memory-only (ADR-MCON-009)
- [ ] `wire`: `/mobileconnect/v1` OpenAPI + `events.schema.json`, capability handshake; publish pinned copy for the app repo's `api/` folder
- [ ] `tests/test_mcon.py` (107 `TC-MCON-*`)
- [ ] Docs, wiki, `plugins.json`, release
- [ ] Measure: hold timing on Wi-Fi with phone and headset; concurrent-stream cap and Pi-class criterion (P4, P6)

## 6. Phase D — WebConnect plugin (Master half + Flask web half)

Design: `docs/plugins/webconnect/SDD.md`. Do after Phase B; reuses it wholesale.

- [ ] **Spike first** (P2): Raspberry Pi 5 with 50 idle SSE streams, a running session and preview rendering — decides gevent vs Cheroot and sets `WCON-080` figures
- [ ] Scaffold; `plugin` (Master only; spoke shows a message, `WCON-020`)
- [ ] `supervisor` (self-hosted profile): child `python -I -m webconnect.web`, config handed over stdin only, heartbeat and back-off restart, no listener or process left when disabled, LAN-interface bind not `0.0.0.0`, `CertificateStore` with self-signed cert in the secret store (`WCON-030`, `060`, `070`, `910`)
- [ ] `delegate` + `BrowserRegistry`: delegated routes, pairing with confirmation code, expiry (`WCON-090`–`190`)
- [ ] Web half: `session` (`__Host-` device cookie, server-side sessions, CSRF, Origin/Sec-Fetch-Site), `security` (headers, host checks, rate limits, route-audit test that only `PUBLIC_ROUTES` are unauthenticated), `api`, `events` (SSE hub with replay ring), `hold`
- [ ] `web.ui` screens, tablet first, server-rendered templates + light JS; static server-rendered sky image first, canvas sky view and session/schedule authoring after the operating screens (P8, decided)
- [ ] Browser outreach: `outreach` (Master half) + `outreach_app` (separate process/listener, owner-supplied certificate required), secret in URL fragment, guest images fetched not streamed (`WCON` §3.11)
- [ ] `config`/`ui`, help, wire + `parity check` against MobileConnect's catalogue
- [ ] Fill `tests/test_wcon.py` (120 `TC-WCON-*`; `_pending` makes unwritten ones fail once the package exists)
- [ ] Docs, wiki, marketplace entry (the SRS/SDD/RTM stay here in core `docs/plugins/webconnect/`; no separate repository)

**Astroberry profile** (PSD §6.5, `WCON-1400`–`1530`; do after the operating screens, in this order):

- [ ] **Decide** PSD Q4–Q11 — hosting profiles, lifecycle owner, how the route reaches Caddy, headless approval, Manager entry, where `debian/` lives, the galileo-astroberry principle conflict, socket vs loopback port
- [ ] **Spike P10 on the official Astroberry OS image** (Pi 5 and amd64): Caddy → gevent over a Unix socket under `/galileo/`, unbuffered SSE, forwarded headers, `Host` as received, `/api*` not capturing `/galileo/api/…`
- [ ] `web.proxy`: `PrefixMiddleware`, `TrustedProxy`, `SecureOnly`, `CookiePolicy`, `MasterDownView`; template/module scan for root-absolute URLs (`WCON-1420`–`1470`, `1490`)
- [ ] `hosting`: `UnitController`, control socket (ADR-WCON-010), unit file, polkit rule for one unit, route file, Manager entry; test that disabling leaves no listener with and without authorisation (`WCON-1410`, `1450`, `1500`; P13)
- [ ] `AdminView` — PAM approval page, only after P12 shows PAM works from the service account (`WCON-1481`, P2)
- [ ] Debian package in `Galileo-Plugins/webconnect/debian` (arm64, amd64, Trixie, own venv); install/upgrade/remove/purge tested on stock Astroberry (`WCON-1520`)
- [ ] **Upstream register** (`WCON-1530`): propose the Caddy include to `astroberry-os-sysmod` and the application-registration extension to the Manager fork; raise front-door authentication on `/websockify*` and `/api*` and the constant `APP_KEY` default with Astroberry (PSD R12)
- [ ] Reconcile with the galileo-astroberry PSD (principle 1, WEB-02/03) — PSD Q10

## 7. Per-plugin definition of done (CLAUDE.md)

- [ ] `CHANGELOG.md` entry in Galileo and in the plugin's own CHANGELOG
- [ ] Inline help for every control; `python -m galileo.ui.help --audit` clean
- [ ] Wiki overview article (`../Galileo.wiki`) and `Home.md` link
- [ ] SRS/SDD/RTM updated when a port shape or decision changes (resolve the open-point tables in each SDD §8)
- [ ] `README.md` status section; plugin README replaced when code lands
- [ ] `ruff check .`, `mypy .`, and `pytest -m "not soak and not hardware and not integration"` green
- [ ] Packaged ZIP installs on a fresh `plugins_dir` via `PluginManager.install()`; enable/disable/remove leaves nothing running
- [ ] Hardware/integration tests marked `hardware` / `integration` (Pi 5 spike, Wi-Fi hold timing, real spoke relay)

## 8. Suggested order

1. §1 decisions → 2. Connect Link L1–L8 (§2a) → 3. NodeConnect prereqs C1–C7 and **Phase A** (independent track) → in parallel 4. Control Surface/lease/events/preview/hold (§2c) → 5. **Phase B** → 6. **Phase D** WebConnect (testable in any browser, so it exercises the pipeline sooner than the apps can) → 7. **Phase C** MobileConnect plugin → app repo work against the pinned wire API.
