# NodeConnect / MobileConnect / WebConnect — Implementation Checklist

Tracks the work to build the three "Connect" plugins. Sources: `docs/plugins/{nodeconnect,mobileconnect,webconnect}/{PSD,SRS,SDD,RTM}.md` (design drafts v0.2, 2026-10-29), core SRS §4.24 (`LINK`), core SDD §4.28 (`galileo.connect_link`).

## 0. Where things stand (verified 2026-11-04)

| Item | State |
|---|---|
| NodeConnect | **Built and committed** (`Galileo-Plugins/nodeconnect`): pairing, roles, sync with conflict handling and undo, push hints, frame and history transfer, Master-side ingest, notifications, status view, Options page with inline help, OpenAPI document, wiki article. 80 tests, ruff clean, **all 44 `TC-NCON-*` rows have a test**. Left: the Raspberry Pi 5 figure for `NCON-NFR-010`, a real two-machine run, and cutting a release (`nodeconnect-v<version>`, only when you say so). |
| WebConnect | **Started 2026-11-04** (`Galileo-Plugins/webconnect`, uncommitted): the Master half (browser pairing, roles, delegated operations through the engine's shared pipeline, revocation) and the web half (sessions, CSRF, headers, own TLS process, pairing/sign-in page, Options page, live events over SSE, and a first Pier screen with live state, lease bar and catalogue-built operations). 47 tests, including a real `python -I` child over HTTPS and the pinned client against a real Connect Link listener. See section 6 for what remains. |
| MobileConnect plugin | README only. Not started. |
| Core prerequisites | **Built and tested**, and now reachable by plugins: Connect Link L1-L9, delegation, relay, `Gateway`; Control Surface registry, state, events, lease, held motion, emergency; preview, sky streaming, replication, Library *On Master*; **the headless engine (`HEAD-010` to `180`, all built)**; and **`galileo.control_surface.service` (2026-11-04), which publishes the engine's registry, lease, pipeline and state to plugins**. The engine registers the device, session, Pier, imaging, flip and safety catalogues. **Registered by the engine:** device, session, Pier, imaging, flip, safety, history, scheduler (read), guiding, solve, and sky and framing catalogues. **Not registered yet:** session authoring (`190`), scheduler editing, calibration (`210`), Library thumbnails and FITS download, notifications (`240`). The desktop does not yet honour or show the lease (`LEASE-060`). |
| Not measured | Discovery over a real LAN, held-motion timing on Wi-Fi, sky-streaming and preview speed on a Raspberry Pi 5, gevent with 50 idle streams on a Pi 5. |
| Known unrelated failure | `tests/test_sky.py::test_tc_sky_020_...` fails (fixed date `2026-09-16`, empty result); not touched by any Connect work. |
| App repo | `Galileo-MobileConnect` is the iOS/Android/Quest *apps* and stays a separate repository (MobileConnect PSD D22). Out of scope here except for the wire contract (section 5). |

**Consequence:** the front ends are thin layers over core facilities that now exist. The build order below follows that.

## 0a. Resume here (written 2026-11-04, end of session)

**Everything below is uncommitted in both repositories** (`Galileo`: 37 changed or new files; `Galileo-Plugins`: the whole `webconnect/` tree). Nothing was committed, pushed, tagged or built on GitHub. Commit when you are ready; the plugin repo's `webconnect/CHANGELOG.md` and the core `CHANGELOG.md` `[Unreleased]` section list what each change was.

**Built this session (core `Galileo`):** the event feed (`CSURF-260`) and, as Control Surface catalogue areas with engine adapters: history and scheduler reads (`CSURF-230`, `200`), guiding (`160`), plate solving (`140`), sky and framing (`130`). Tests: `tests/test_csurf.py` (`TC-CSURF-130/140/160/200/230/260`), 68 pass across csurf, head and help.
**Built this session (`Galileo-Plugins/webconnect`):** the live event stream, a gevent fix, and the first operating screen (`static/pier.js`). 47 tests pass, ruff clean.

**Never run for real:** guiding against a real PHD2; plate solving against a real camera, mount and solver; the browser screen in an actual browser or on a tablet. All are tested only against fakes or Flask's test client.

**Known, unrelated, not fixed:** 5 failures in `tests/test_sky.py` against the already-modified `galileo/planning/*` files from before this session; about 40 ruff findings and about 86 mypy errors elsewhere in `galileo/`. The full core suite was not re-run after the catalogue work.

**Next, in the order I would take it:**
1. Run Galileo with WebConnect, pair a browser, open a Pier and walk through the screen (ideally on a tablet). Fix what the tests could not show.
2. With a PHD2 simulator and simulator camera and mount, try `guiding.*` and `solve.*` for real.
3. Purpose-built panels over the same catalogue: guiding (star cut-out, error trace), sky (search, framing preview).
4. Held motion and previews (`WCON-600` to `640`, `720`, `730`), then the page marking state stale on stream loss (`WCON-780`) and the first all-Pier snapshot (`WCON-300`).
5. Remaining catalogue areas: calibration (`210`), notifications (`240`), scheduler editing, Library thumbnails and FITS download.
6. MobileConnect plugin server side (section 5), not started.
7. Core: the desktop honouring the lease (`LEASE-060`); SRS/SDD/RTM text for `LINK-010` to `080`.
8. Hardware: Raspberry Pi 5 and Astroberry spikes, NodeConnect two-machine run. Releases only when you say so.

**Tooling notes:** use the project venv (`.venv/Scripts/python`); bare `python` is the Windows Store stub. The Bash tool mangles backslashes and complex heredocs, so write scripts to a file or use the edit tools.

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

### 2c-bis. Headless engine and the desktop as a client (`HEAD-010` to `180`, core SDD section 4.33)
**Built** (verified 2026-11-04; `tests/test_head.py`, 29 tests): lock and `--engine` start-up, device service, session runner, Pier helpers, local channel and client, embedded mode, configuration from the database, systemd unit, `--status`, safety guard. Left: decide whether the desktop should attach to the engine by default (the Options toggle "Hold devices in the device service" is off by default), and measure on a real Astroberry controller.
- [x] **Plugins can reach the engine's Control Surface (2026-11-04):** `galileo.control_surface.service` (`get_control_surface()`), published by the engine when its channel starts. Test `TC-CSURF-250`.

### 2d. Plugin loader
- [x] Specified as core `PLUG-200` (SRS, RTM row, SDD §4.20 install step 4a: `requires` in `plugin.toml`, private `.deps/` directory per plugin, rollback on failure, offline refusal)
- [x] Implemented 2026-10-30 in `galileo.plugins` (`install_requirements`, `PluginManifest.requires`); `TC-PLUG-200` in `tests/test_plug.py` (3 tests). No control changed, so no inline-help change.

## 3. Phase A: NodeConnect (built)

Design: `docs/plugins/nodeconnect/SDD.md`. Package `nodeconnect`, in `Galileo-Plugins/nodeconnect` (committed). Its `CHANGELOG.md` has the full list and the design decisions; the handover notes that used to be here live there.

Remaining, none of it blocking:
- [ ] Measure `NCON-NFR-010` on a Raspberry Pi 5, and run a real two-machine sync (the two-process TLS test already passes on one machine).
- [ ] Confirm in CI that `segno` is installed so the two outreach tests pass (installed in the local venv 2026-11-04).
- [ ] Cascaded-delete tombstones are untested against core's triggers; `scheduler_jobs` is the one configuration table not replicated.
- [ ] Release `nodeconnect-v<version>` and a `plugins.json` entry (**never dispatch GitHub builds without asking**; `build_plugins.py` adds an entry pointing at a release that does not exist, so revert it if it reappears).

## 4. Phase B: shared pipeline and relay (mostly in core)

Decided: the pipeline and relay live in core (`galileo.connect_link.gateway`, `.relay`), so neither plugin forks them. Built: `Gateway` (identify, authorise, validate, lease, confirm, idempotency, dispatch under a load governor, audit in a `finally`), `LoadGovernor`, confirmation tokens, idempotency, guest allowlist, `MasterRelay`, lease broker, `HoldManager`, emergency operations, observable state with sequence numbers. WebConnect uses them through `get_control_surface()`.

- [ ] Wire `MasterRelay` to paired spokes in the engine (nothing constructs one yet), including the spoke-side grant prompt (`WCON-220`)
- [~] Register the missing catalogue areas (section 0). **Done (2026-11-04), read-only:** session history (`history.*`, `CSURF-230`) and the scheduler queue (`scheduler.jobs`, `CSURF-200`). **Guiding `CSURF-160` also done (2026-11-04):** `guiding.*` over a per-Pier PHD2 connection in the engine, shared with engine-run sessions; never run against a real PHD2. **Plate solving `CSURF-140` also done (2026-11-04):** `solve.capture`/`sync`/`centre`/`stop`/`status` over the Solve screen's own workflow; never run on real hardware; solving a file already on disk and polar alignment are left. **Sky and framing `CSURF-130` also done (2026-11-04):** `sky.search`/`object`/`framing`, read-only, offline catalogue; go-to is `mount.slew`. **Still missing, and why:** calibration `CSURF-210`, scheduler *editing* (the engine does not own a live scheduler), Library thumbnails and FITS download (need a binary route), and notifications `CSURF-240` (nothing keeps a list of recent alerts to read)
- [x] A state/event feed a plugin can read (2026-11-04): `get_control_surface().feed.read(after, timeout)` returns state, lease, device and operation events in order with ids, waits for news, and flags a gap so the reader re-reads state (`galileo.control_surface.feed`, `CSURF-260`). WebConnect serves it to browsers as Server-Sent Events (section 6)
- [ ] Contract tests run against both plugins

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

## 6. Phase D: WebConnect plugin (Master half and Flask web half)

Design: `docs/plugins/webconnect/SDD.md`. Built 2026-11-04 in `Galileo-Plugins/webconnect` (uncommitted); its `CHANGELOG.md` lists exactly what is and is not done.

- [x] Scaffold; `plugin` (Master only; a spoke starts nothing, `WCON-020`)
- [x] `supervisor` (self-hosted): child `python -I`, config over stdin only, heartbeat and back-off restart, no listener or process left when stopped, LAN-interface bind (never `0.0.0.0` unless allowed), own certificate with the key in the secret store (`WCON-030`, `040`, `060`, `070`, `910`)
- [x] `delegate` and `BrowserRegistry`: delegated routes, pairing with a confirmation code, roles, expiry, revocation (part of `WCON-090` to `190`)
- [x] Web half: `session` (`__Host-` cookies, server-side sessions, CSRF, Origin/Sec-Fetch-Site), `security` (headers, host check, rate limits, route registry and audit), `api` (one operations route, typed results), pairing and sign-in page, Master-down page
- [x] `HttpLinkClient` verified against a real Connect Link listener
- [x] **Options page on the Master** (`WCON-050`, `900`): approve, reject, promote, demote, revoke, remove, expiry, address, start/stop, options, recent activity; inline help written and audited (`help/plugin.WebConnect.md`). Left: list signed-in browsers with the Piers they hold
- [~] `web.events`: **server side done (2026-11-04)**: Master route `events` and browser `GET /api/v1/events` (hello, ids, `Last-Event-ID` resume, `resync` on a gap, `down`, `signed-out`, four streams per sign-in, idle sign-out not defeated by an open stream; `WCON-300`, `310`, `350`). Also fixed: the web process did not patch gevent sockets, so one slow Master call stalled every browser. **Left:** the page marking state stale and disabling Pier-affecting operations while the stream is down (`WCON-780`), a first snapshot of every Pier on connect (`WCON-300`), and the event schema in the OpenAPI document
- [ ] `web.hold` held motion (`WCON-720`, `730`); previews, tiles and FITS (`WCON-600` to `640`)
- [~] `web.ui` operating screens, tablet first. **First screen done (2026-11-04):** Pier list, live state, lease bar and a catalogue-built operations panel; untried in a real browser; static sky image first (`WCON-400` to `560`, `650`, `810` to `890`)
- [ ] Relay to spoke Piers (`WCON-200` to `250`); needs section 4
- [ ] **Spike first** (P2): Raspberry Pi 5 with 50 idle SSE streams, a running session and preview rendering; decides gevent vs Cheroot and sets the `WCON-080` figures. *Needs hardware.*
- [ ] Browser outreach: `outreach` (Master half) and `outreach_app` (separate process and listener, owner-supplied certificate required), secret in the URL fragment (`WCON` section 3.11)
- [ ] `wire` OpenAPI and events schema generated from the models, and the `parity check` against MobileConnect's catalogue (`WCON-590`, `920`)
- [ ] Map every `TC-WCON-*` row (120) to a test; `tests/test_wcon.py` in core still skips them
- [ ] Docs, wiki article, marketplace entry (SRS/SDD/RTM stay in core `docs/plugins/webconnect/`)

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
