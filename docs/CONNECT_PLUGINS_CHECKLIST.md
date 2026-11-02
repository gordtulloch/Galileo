# NodeConnect / MobileConnect / WebConnect — Implementation Checklist

Tracks the work to build the three "Connect" plugins. Sources: `docs/plugins/{nodeconnect,mobileconnect,webconnect}/{PSD,SRS,SDD,RTM}.md` (design drafts v0.2, 2026-10-29), core SRS §4.24 (`LINK`), core SDD §4.28 (`galileo.connect_link`).

## 0. Where things stand (verified 2026-10-30)

| Item | State |
|---|---|
| Plugin code | **None.** `Galileo-Plugins/{nodeconnect,mobileconnect}` hold a README only (no `plugin.toml`, so `build_plugins.py` skips them); `Galileo-Plugins/webconnect` is where WebConnect will be built (README only today; the separate `Galileo-WebConnect` repository is retired, 2026-10-31) |
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

### 2d. Plugin loader
- [x] Specified as core `PLUG-200` (SRS, RTM row, SDD §4.20 install step 4a: `requires` in `plugin.toml`, private `.deps/` directory per plugin, rollback on failure, offline refusal)
- [x] Implemented 2026-10-30 in `galileo.plugins` (`install_requirements`, `PluginManifest.requires`); `TC-PLUG-200` in `tests/test_plug.py` (3 tests). No control changed, so no inline-help change.

## 3. Phase A — NodeConnect (needs 2a L1–L8 and 2b only)

Design: `docs/plugins/nodeconnect/SDD.md` §3.1–3.12. Package `nodeconnect`.

- [ ] Scaffold `Galileo-Plugins/nodeconnect/`: `plugin.toml` (hard dependency on Connect Link, `nav_level = "primary"`), `pyproject.toml`, `build_zip.py`, `CHANGELOG.md`, `tests/` per the `kasa_switch` layout; the presence of `plugin.toml` makes `build_plugins.py` pick it up, so add it only when installable
- [ ] `nodeconnect.ports` Protocols (`LinkPort`, `ChangeTrackingPort`, `RegistryPort`, `SettingsChangedPort`, `SessionBusyPort`, `LoopbackGuardPort`, `SyncStorePort`, `LibraryPort`, `HistoryPort`, `NotifyPort`) + stubs in `tests/`
- [ ] `plugin` shell: panel, Options page, enable/disable leaves no listener or worker (`NCON-310`), fault isolation (`NCON-530`), version refusal (`NCON-520`)
- [ ] `roles` + `pairing`: derived exclusive roles, single Master, pairing request/approval/revoke/delete, scopes limited to `config.*`, `data.*` (`NCON-020`–`060`)
- [ ] `registry` + `codec`: replicable set, node-local/secret `ItemFilter`, 200-row paged codec with field-level merge (`NCON-100`, `110`, `210`)
- [ ] `sync` engine, `conflict` (later edit wins, loser kept), `tombstones`, `apply` (transactional, session gate, safety checks), `snapshot` + `report` (undo), `compat` (handshake, clock offset) (`NCON-120`–`230`, `300`, `305`, `320`)
- [ ] `transfer` (durable queue, content-hash identity, resumable, lowest priority for bytes) and `history` (`(origin_node_id, local_key)` upsert) (`NCON-400`–`490`)
- [ ] `ui`/`config`: status view, Options, notifications; plugin settings in `app_settings` namespace `plugin.NodeConnect` — no JSON files (`NCON-330`, `340`, `500`, `510`)
- [ ] `wire`: `/nodeconnect/v1` OpenAPI (`NCON-NFR-030`)
- [ ] `tests/test_ncon.py` (one function per RTM row, 45 `TC-NCON-*`) with doc-chain tests like `test_wcon.py`
- [ ] Help content, wiki article, `docs/plugins/nodeconnect/` status updates, `plugins.json` entry, release `nodeconnect-v<version>`

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
