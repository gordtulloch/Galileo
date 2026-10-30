# NodeConnect / MobileConnect / WebConnect — Implementation Checklist

Tracks the work to build the three "Connect" plugins. Sources: `docs/plugins/{nodeconnect,mobileconnect,webconnect}/{PSD,SRS,SDD,RTM}.md` (design drafts v0.2, 2026-10-29), core SRS §4.24 (`LINK`), core SDD §4.28 (`galileo.connect_link`). Packaging mechanics are in [`PLUGIN_CHECKLIST.md`](PLUGIN_CHECKLIST.md).

## 0. Where things stand (verified 2026-10-30)

| Item | State |
|---|---|
| Plugin code | **None.** `Galileo-Plugins/{nodeconnect,mobileconnect}` hold a README only (no `plugin.toml`, so `build_plugins.py` skips them); `Galileo-Plugins/webconnect` is a pointer to `Galileo-WebConnect`, which holds a PSD and README only |
| Requirements | NCON 45 (41 MVP), MCON 107 (93 MVP), WCON 137 (90 MVP); each has an RTM with reserved `TC-*` IDs |
| Tests | `tests/test_wcon.py` exists: 6 doc-chain tests pass, 105 requirement tests skip (`importorskip`). **No `test_ncon.py` / `test_mcon.py`** |
| Core prerequisites | **Specified, not built (2026-10-30).** Core SRS/RTM/SDD now hold: `LINK-010`–`270` in full, `CSURF`, `LEASE`, `PREV`, `SKYSTR`, `REPL`, `FOC-100`–`130`, `LIB-200`–`220`, `HIST-050`, `PROF-130`, `GUIDE-100`, `PLUG-200`; designed at component level in core SDD §4.11, §4.17, §4.20, §4.23, §4.28–4.32. No code exists, and every `TC-*` is reserved but unwritten |
| App repo | `Galileo-MobileConnect` is the iOS/Android/Quest *apps* (not the plugin): PSD, SRS, a Quest atlas spike. Out of scope here except for the wire contract (§5) |

**Consequence:** the plugins are thin layers over core facilities that do not exist. Each design codes against `typing.Protocol` ports with test stubs, so plugin work can start early, but nothing can be verified end to end until core catches up. Build order below follows that.

## 1. Decisions to close before coding

- [x] **Shared pipeline and relay home** (MCON SDD P3, WCON SDD P1): **decided — both live in core** (`galileo.connect_link`), so the two plugins can't drift. Still to do: record this in MCON SDD P3 / WCON SDD P1 and the core SDD §4.28, and move `Gateway`/relay requirements into core SRS
- [x] **Delegated identity (DG)** (WCON SDD P3): **decided — delegation (option 1).** Connect Link lets a service peer act for a named browser and logs the browser as actor; recorded as core `LINK-090` (outline). Still to do: expand `LINK-090` with Connect Link's design and write `TC-LINK-090`
- [x] **Audit store** (MCON SDD P1): **decided** — Connect Link's audit log carries plugin fields and configurable retention (a Connect Link requirement); core owns the table either way
- [x] **Plugin dependencies in the ZIP**: **decided** — declare them in `plugin.toml` and have `PluginManager.install()` resolve them (no vendored wheels: they break across Windows, macOS and Pi ARM). Core work, tracked in §2d; must land before WebConnect
- [x] **WebConnect repo split**: **decided** — source stays in `Galileo-WebConnect`; `Galileo-Plugins/webconnect` remains a pointer and the marketplace entry references that repo's release; SRS/SDD/RTM stay in core `docs/plugins/webconnect/`
- [ ] **Role of NodeConnect for the other two:** none by dependency (they need Connect Link, not NodeConnect), so NodeConnect can ship independently
- [ ] Review each port stub against core's real SRS once written (MCON SDD P2, SRS O1)
- [x] **Product decisions** (2026-10-30, recorded in the SRS/SDD open-point tables): sign-in is one-click device-cookie for MVP (PIN later); pairing confirmation code for browsers *and* apps; static server-rendered sky image first, canvas sky view after the operating screens; idempotency keys, event replay and rate limiting stay MVP; no background push alerts in v1; showcase image set deferred to P2; outreach events carry per-surface toggles (apps, browsers); outreach's event-scoped enrolment exception (L2/L3) accepted

## 2. Core prerequisites (in `Galileo`, not the plugins)

**Status 2026-10-30:** the requirements, RTM rows and component designs below are written (ticked `[x] Specified`); the items are *built* only when their code and `TC-*` tests exist. Remaining design depth is noted per item.

Each needs SRS + SDD + RTM rows + tests per CLAUDE.md before the dependent plugin work can be verified.

| Item | Requirements | Core SDD | Spec status |
|---|---|---|---|
| Connect Link L1–L8, delegation, relay, pipeline, audit, Options, secrets, disable | `LINK-010`–`090`, `220`–`270` | §4.28 | [x] Specified; component design written (ADR-LINK-004…007); wire details (route shapes, message formats, OpenAPI) still to be written with the first code |
| Outreach facility (L9) | `LINK-100`–`210` | §4.28 | [x] Specified and designed |
| Control Surface, operation events, held motion, emergency | `CSURF-010`–`420` | §4.29 | [x] Specified; component design written; the per-area operation inventory (`CSURF-100`–`250`) is at area level — each service lists its concrete entries when it registers |
| Control lease | `LEASE-010`–`080` | §4.29 | [x] Specified and designed |
| Preview service | `PREV-010`–`060` | §4.30 | [x] Specified and designed |
| Sky streaming | `SKYSTR-010`–`080` | §4.31 | [x] Specified; byte-level encoding to be fixed with the Quest SDD (versioned schema file) |
| Replication support (C1–C6) | `REPL-010`–`080`, `PROF-130`, `GUIDE-100` | §4.32, §4.4, §4.14 | [x] Specified and designed |
| Library On Master (C7), history transfer form | `LIB-200`–`220`, `HIST-050` | §4.23, §4.17 | [x] Specified and designed |
| Manual focus in the focus module | `FOC-100`–`130` | §4.11 | [x] Specified and designed |
| Plugin dependencies | `PLUG-200` | §4.20 | [x] Specified; `requires` format to be finalised in code |

### 2a. Connect Link — unlocks all three plugins
- [ ] Expand `LINK-010`–`080` from outline to full requirements and write the `galileo.connect_link` design beyond the L9 seams
- [ ] L1 encrypted listener + pinned certificate; L2 pairing with approval, per-peer tokens; L3 scopes (`config.read/write`, `data.push/pull`, `control`, `view`) + audit log; L4 LAN discovery + manual address; L5 plugin-registered versioned routes; L6 server-push stream; L7 chunked, resumable, checksummed transfer; L8 version handshake with plugin extension
- [ ] L9 outreach event facility (`LINK-100`–`210`): lifecycle/timer, event secret, subnet guard, guest tokens, caps, aggregate audit, event display and QR codes, surface registration (`mobile`, `browser`)
- [ ] Delegated identity (`LINK-090`): service credential registered per plugin, client resolved to its own role/scopes/expiry, refusal of revoked/expired/unknown/other-plugin clients, client as audit actor; and asserted source address for the browser surface (WCON SDD P5), per decision above
- [x] Outreach amendment (event-scoped enrolment L2, `outreach.view` L3, per-surface toggles `LINK-110`/`200`) was already in core SRS `LINK-020`/`030`/`110`/`200`; audit-log plugin fields and retention added to `LINK-030` (2026-10-30)
- [x] Pairing confirmation code added to core `LINK-020` and to `MCON-100` / `WCON-100` (2026-10-30)
- [ ] Design the full Connect Link internals: `LINK-010`–`090`, `220`–`230` are outlines; `Delegation`, `PairingConfirmation`, `Gateway` and `MasterRelay` are sketched in core SDD §4.28 (ADR-LINK-004/005)
- [ ] Write `TC-LINK-090`, `220`, `230` (reserved in the RTM; no tests yet)
- [ ] Connect Link Options/Outreach page, inline help (`galileo/help/content/`), wiki article

### 2b. NodeConnect prerequisites (C1–C7)
- [ ] C1 change tracking: `rev`, `modified`, `dirty`, `base_rev`, write hook, tombstones
- [ ] C2 replicable-table registry with natural keys and node-local/secret fields; registry-coverage test listing models without a natural key
- [ ] C3 settings-changed event; C4 session busy signal (`is_busy`, `on_idle`); C5 loopback guard
- [ ] C6 core-owned sync tables via numbered `galileo/library/migrations/` files (outbox, inbox, snapshots, run reports, transfer queue, peer state) + `SyncStorePort`
- [ ] C7 Library *On Master* location state + Retrieve action + hook for "open/process needs the file" (Library screens, inline help)

### 2c. MobileConnect / WebConnect prerequisites
- [ ] **CS Control Surface** — registry of operator-level operations and observable state, with permission class (read / operate / confirm / emergency; never *config*) and lease requirement. Largest item: every operation in MCON §3.5 must be catalogued
- [ ] **LS** control lease per Pier, shared with the desktop UI (desktop must honour and surface it)
- [ ] **OE** operation results as events with correlation id (started/progress/finished)
- [ ] **PV** server-side preview rendering (stretch, bin, JPEG, tiles)
- [ ] **DM** deadman semantics for held motion (proposal 250 ms beat / 600 ms deadman; measure on Wi-Fi)
- [ ] **MF** manual focus moved into the focus module, consumed by the desktop focus screen
- [ ] **SK** sky-data streaming (`catalog`, `ephemeris`, `site`, `capability`)

### 2d. Plugin loader
- [x] Specified as core `PLUG-200` (SRS, RTM row, SDD §4.20 install step 4a: `requires` in `plugin.toml`, private `.deps/` directory per plugin, rollback on failure, offline refusal)
- [ ] Implement in `galileo.plugins` (`PluginManager.install()`), write `TC-PLUG-200` in `tests/test_plug.py`, update the Options > Plugins inline help (`python -m galileo.ui.help --audit`) and `PLUGIN_CHECKLIST.md`

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
- [ ] `supervisor`: child `python -I -m webconnect.web`, config handed over stdin only, heartbeat and back-off restart, no listener or process left when disabled, LAN-interface bind not `0.0.0.0`, `CertificateStore` with self-signed cert in the secret store (`WCON-030`, `060`, `070`, `910`)
- [ ] `delegate` + `BrowserRegistry`: delegated routes, pairing with confirmation code, expiry (`WCON-090`–`190`)
- [ ] Web half: `session` (`__Host-` device cookie, server-side sessions, CSRF, Origin/Sec-Fetch-Site), `security` (headers, host checks, rate limits, route-audit test that only `PUBLIC_ROUTES` are unauthenticated), `api`, `events` (SSE hub with replay ring), `hold`
- [ ] `web.ui` screens, tablet first, server-rendered templates + light JS; static server-rendered sky image first, canvas sky view and session/schedule authoring after the operating screens (P8, decided)
- [ ] Browser outreach: `outreach` (Master half) + `outreach_app` (separate process/listener, owner-supplied certificate required), secret in URL fragment, guest images fetched not streamed (`WCON` §3.11)
- [ ] `config`/`ui`, help, wire + `parity check` against MobileConnect's catalogue
- [ ] Fill `tests/test_wcon.py` (106 `TC-WCON-*`; `_pending` makes unwritten ones fail once the package exists)
- [ ] Add SRS/SDD/RTM to the `Galileo-WebConnect` repo or point to the core docs; docs, wiki, marketplace entry

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
