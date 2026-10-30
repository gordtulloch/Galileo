# WebConnect Plugin — RTM (Requirements Traceability Matrix)

| | |
|---|---|
| **Project** | Galileo — WebConnect Plugin |
| **Document** | RTM (Requirements Traceability Matrix), v0.1, draft — **seeded from the SRS; SDD components mapped; tests in `tests/test_wcon.py` (30 of 105 written, the rest reserved)** |
| **Status** | Draft — for review |
| **Date** | 2026-10-29 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md), [SDD](SDD.md) |
| **Parent project** | [Galileo Core RTM](../../RTM.md) |

---

## 1. Purpose and Method

This RTM seeds a row for every requirement in [this plugin's SRS](SRS.md) with a reserved Test Case ID, so tests can be written against stable IDs. **Test Case ID convention:** `TC-<requirement-ID>` (e.g. `TC-WCON-010` verifies `WCON-010`); several test functions may carry one ID. The **SDD Component** column maps each row to its section of the [SDD](SDD.md). Counts follow the SRS summary table.

**Verification Method:** `Test` (automated) unless stated. `Test (browser matrix)` is the automated suite run across the supported browsers (`WCON-880`); `Test (build check)` is the parity check that fails the build (`WCON-590`); `Inspection` is a documented review (`WCON-1070`).

**Core prerequisite:** the capability a row cannot be verified without, using the reference codes of SRS Section 2.6 (CL Connect Link, CS Control Surface, LS lease, OE operation events, PV preview rendering, DM deadman, MF manual focus, SK sky streaming, OF outreach facility, DG delegated identity). Until that capability exists, the row stays reserved but is verified against a stub. `WR` (the Master relay) is defined by this plugin and so is not a prerequisite here.

**Coverage:** 105 requirements, 100% mapped to an SDD component; 105 test functions in `tests/test_wcon.py`, 30 with bodies (security `WCON-1000`–`1060`, outreach `WCON-1210`–`1310`, role/CSRF/confirmation/idempotency pass-through, SSE resume, configuration) and 75 reserved — they skip until the `webconnect` package exists, then fail until written. The 30 were validated against a throwaway reference implementation, not against the real plugin. Security requirements (`WCON-1000`–`1070`) and outreach confinement (`WCON-1210`, `1220`, `1250`, `1310`) are the highest-priority rows to write tests for first.

**Shared tests.** Several rows are satisfied by the design shared with MobileConnect (pipeline, confirmation, idempotency, relay: SDD §2.3, §3.9). Their tests run against the shared package's contract suite for both plugins, and a `WCON` test asserts the browser path exercises it.

---

## 2. Traceability Matrix

### `WCON` — Hosting, packaging and lifecycle

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `WCON-010` | MVP | be delivered as a first-party plugin with the manifest identity `WCON`,… | SDD 3.1 `plugin` | — | Test | `TC-WCON-010` |
| `WCON-020` | MVP | be enabled only on a Master node. On a node that is a spoke it shall report… | SDD 3.1 `plugin` | — | Test | `TC-WCON-020` |
| `WCON-030` | MVP | While enabled, the system shall run the operating web application as a Flask… | SDD 3.2 `supervisor` | — | Test | `TC-WCON-030` |
| `WCON-040` | MVP | While disabled, the system shall be fully inert (`PLUG-060`): every web process… | SDD 3.1 `plugin`; SDD 3.2 `supervisor` | — | Test | `TC-WCON-040` |
| `WCON-050` | MVP | add a top-level **WebConnect** section (`PLUG-130`) showing the address to… | SDD 3.13 `config, ui` | — | Test | `TC-WCON-050` |
| `WCON-060` | MVP | bind the operating web application to a configurable address and port,… | SDD 3.2 `supervisor` | — | Test | `TC-WCON-060` |
| `WCON-070` | MVP | serve the operating web application over HTTPS only. It shall generate a… | SDD 3.2 `supervisor` | — | Test | `TC-WCON-070` |
| `WCON-080` | MVP | never run network or rendering work on the Qt UI thread, and shall keep serving… | SDD 3.1 `plugin`; SDD 3.2 `supervisor`; SDD 3.6 `web.api` | — | Test | `TC-WCON-080` |
| `WCON-090` | MVP | The web processes shall reach Galileo only through Connect Link, authenticated… | SDD 3.3 `delegate`; SDD 3.14 `wire` | CL | Test | `TC-WCON-090` |

### `WCON` — Pairing, sign-in, roles, lease and audit

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `WCON-100` | MVP | register a browser only through Connect Link's pairing flow (needs CL, L2): the… | SDD 3.3 `delegate`; SDD 3.4 `web.session` | CL, DG | Test | `TC-WCON-100` |
| `WCON-110` | MVP | assign every approved browser one of two roles, **Viewer** (state, events and… | SDD 3.3 `delegate` | — | Test | `TC-WCON-110` |
| `WCON-120` | MVP | enforce the role on the Master for every request: a Viewer's operation request… | SDD 3.3 `delegate` | — | Test | `TC-WCON-120` |
| `WCON-130` | MVP | never grant an approved browser the `config.*` scope and shall register no… | SDD 3.3 `delegate` | — | Test | `TC-WCON-130` |
| `WCON-140` | MVP | apply the **control lease** per Pier (needs LS) with the semantics of… | SDD 3.3 `delegate`; SDD 3.7 `web.events` | LS | Test | `TC-WCON-140` |
| `WCON-150` | MVP | When an operation is refused because another party holds the lease, the refusal… | SDD 3.3 `delegate` | — | Test | `TC-WCON-150` |
| `WCON-160` | MVP | The Emergency operations (`WCON-710`) shall not require the lease and shall be… | SDD 3.3 `delegate` | — | Test | `TC-WCON-160` |
| `WCON-170` | MVP | let the user on the Master revoke any approved browser — immediately ending its… | SDD 3.3 `delegate`; SDD 3.4 `web.session` | DG | Test | `TC-WCON-170` |
| `WCON-180` | MVP | require confirmation for the destructive or hard-to-reverse operations defined… | SDD 3.3 `delegate`; SDD 3.6 `web.api` | — | Test | `TC-WCON-180` |
| `WCON-190` | MVP | record every request by every browser — browser identity, role, Pier, operation… | SDD 3.3 `delegate`; SDD 3.13 `config, ui` | DG | Test | `TC-WCON-190` |

### `WCON` — Proxying through the Master (the shared relay)

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `WCON-200` | MVP | present to a browser the Piers of the Master and, through it, those of every… | SDD 3.9 `relay` | — | Test | `TC-WCON-200` |
| `WCON-210` | MVP | For a spoke's Pier, the system shall relay operations, state, events and… | SDD 3.9 `relay` | CL | Test | `TC-WCON-210` |
| `WCON-220` | MVP | reach a spoke only if the spoke's user has granted the Master the opt-in right… | SDD 3.9 `relay` | — | Test | `TC-WCON-220` |
| `WCON-230` | MVP | The control lease for a spoke's Pier shall be held on that spoke, so its… | SDD 3.9 `relay` | — | Test | `TC-WCON-230` |
| `WCON-240` | MVP | When the Master cannot reach a spoke, the system shall show that spoke's Piers… | SDD 3.9 `relay` | — | Test | `TC-WCON-240` |
| `WCON-250` | MVP | be exposed as one interface (`RelayPort`) that MobileConnect and WebConnect… | SDD 3.9 `relay` | — | Test | `TC-WCON-250` |

### `WCON` — State and events

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `WCON-300` | MVP | On opening the event stream the system shall send the browser a complete… | SDD 3.7 `web.events` | — | Test | `TC-WCON-300` |
| `WCON-310` | MVP | deliver state, events and alerts to the browser by **Server-Sent Events** (PSD… | SDD 3.7 `web.events` | CS | Test | `TC-WCON-310` |
| `WCON-320` | MVP | The state delivered shall include, for each Pier, what `MCON-320` lists,… | SDD 3.7 `web.events` | — | Test | `TC-WCON-320` |
| `WCON-330` | MVP | Long-running operations (slew, solve, autofocus run, session, calibration set,… | SDD 3.7 `web.events` | OE | Test | `TC-WCON-330` |
| `WCON-340` | MVP | forward the node's alerts to the page while it is open, keep a recent-alerts… | SDD 3.7 `web.events` | — | Test | `TC-WCON-340` |
| `WCON-350` | MVP | On reconnection after a drop the system shall resume the event stream from the… | SDD 3.7 `web.events` | — | Test | `TC-WCON-350` |
| `WCON-360` | P2 | deliver the state of a Pier to a browser only if that Pier is among those the… | SDD 3.3 `delegate`; SDD 3.7 `web.events` | — | Test | `TC-WCON-360` |

### `WCON` — Operations

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `WCON-400` | MVP | publish the operations to the page as a catalogue from the Control Surface and… | SDD 3.6 `web.api`; SDD 3.10 `web.ui`; SDD 3.14 `wire` | CS | Test | `TC-WCON-400` |
| `WCON-410` | MVP | **Observatory and Pier** — as `MCON-410`: list Observatories and Piers, choose… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-410` |
| `WCON-420` | MVP | **Devices** — as `MCON-420`: connect and disconnect devices and operate the… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-420` |
| `WCON-421` | MVP | After a mount connects through an operation of this plugin, the same date/time… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | — | Test | `TC-WCON-421` |
| `WCON-430` | MVP | **Imaging** — as `MCON-430`: live exposure loop, single and series captures,… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-430` |
| `WCON-440` | MVP | **Sky and framing** — as `MCON-440`: sky view with the mount's position, target… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-440` |
| `WCON-450` | MVP | **Plate solving and alignment** — as `MCON-450`. | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-450` |
| `WCON-460` | MVP | **Guiding** — as `MCON-460`, including the error trace and guide-star cut-out. | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-460` |
| `WCON-470` | MVP | **Focus** — as `MCON-470`: manual focus (relative, absolute, halt, position and… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | MF, CS | Test | `TC-WCON-470` |
| `WCON-480` | MVP | **Meridian flip** — as `MCON-480`; a trigger is a confirmed operation… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-480` |
| `WCON-490` | MVP | **Sessions, run** — as `MCON-490`: list, load, run, pause, resume, skip and… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-490` |
| `WCON-500` | P2 | **Sessions, authoring** — as `MCON-500`: add, remove, reorder and nest… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-500` |
| `WCON-510` | P2 | **Scheduler** — as `MCON-510`. | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-510` |
| `WCON-520` | P2 | **Calibration** — as `MCON-520`. | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-520` |
| `WCON-530` | MVP | **Safety** — as `MCON-530`: every safety input, overall state and stop reason;… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-530` |
| `WCON-540` | P2 | **Library and history** — as `MCON-540`: recent sessions and frames, quality… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-540` |
| `WCON-550` | P2 | **Notifications** — as `MCON-550`: recent alerts visible; channels and rules… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-550` |
| `WCON-560` | P3 | **Plugin surfaces** — as `MCON-560`: a plugin's registered remote surface is… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | CS | Test | `TC-WCON-560` |
| `WCON-570` | MVP | **Per-run parameters** — as `MCON-570`: per-run parameters are accepted; any… | SDD 3.3 `delegate`; SDD 3.6 `web.api` | — | Test | `TC-WCON-570` |
| `WCON-580` | MVP | validate every operation's arguments on the Master against the Control… | SDD 3.3 `delegate`; SDD 3.6 `web.api` | — | Test | `TC-WCON-580` |
| `WCON-590` | MVP | **Parity.** An automated check shall confirm that every operation in the… | SDD 3.14 `wire` | — | Test (build check) | `TC-WCON-590` |

### `WCON` — Images, previews and the sky view

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `WCON-600` | MVP | deliver images as server-rendered previews (needs PV): stretched and scaled to… | SDD 3.6 `web.api` | PV | Test | `TC-WCON-600` |
| `WCON-610` | P2 | offer a preview as tiles of a pyramid for pan and zoom, with a bounded… | SDD 3.6 `web.api` | — | Test | `TC-WCON-610` |
| `WCON-620` | P3 | allow an Operator to download a full FITS frame as an explicit action, with its… | SDD 3.6 `web.api` | — | Test | `TC-WCON-620` |
| `WCON-630` | P2 | expose preview quality and maximum size as options (`WCON-910`), let the page… | SDD 3.6 `web.api`; SDD 3.13 `config, ui` | — | Test | `TC-WCON-630` |
| `WCON-640` | P2 | let the user hold the tiles of two frames at once for blink and side-by-side… | SDD 3.10 `web.ui` | — | Test | `TC-WCON-640` |
| `WCON-650` | MVP | render the sky view locally in the browser from sky data streamed by the Master… | SDD 3.6 `web.api`; SDD 3.10 `web.ui` | SK | Test | `TC-WCON-650` |

### `WCON` — Safety and failure behaviour

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `WCON-700` | MVP | Every operation shall pass through the same core services and safety interlocks… | SDD 3.3 `delegate` | — | Test | `TC-WCON-700` |
| `WCON-710` | MVP | provide Emergency operations — **Stop everything**, **Park**, **Close dome** —… | SDD 3.3 `delegate`; SDD 3.10 `web.ui` | — | Test | `TC-WCON-710` |
| `WCON-720` | MVP | Imaging shall continue, unchanged, when the browser tab is closed, the browser… | SDD 3.8 `web.hold` | — | Test | `TC-WCON-720` |
| `WCON-730` | MVP | A manual slew or jog and a focuser move started from the browser shall run only… | SDD 3.8 `web.hold` | DM | Test | `TC-WCON-730` |
| `WCON-740` | MVP | An operation shall carry a client-generated idempotency key, and a retried… | SDD 3.3 `delegate`; SDD 3.6 `web.api` | — | Test | `TC-WCON-740` |
| `WCON-750` | MVP | Where a command is refused because the lease is held elsewhere, the Pier is… | SDD 3.3 `delegate`; SDD 3.6 `web.api`; SDD 3.10 `web.ui` | — | Test | `TC-WCON-750` |
| `WCON-760` | MVP | A lease shall not outlive its holder: on sign-out, session expiry, event-stream… | SDD 3.3 `delegate`; SDD 3.4 `web.session`; SDD 3.7 `web.events` | — | Test | `TC-WCON-760` |
| `WCON-770` | P2 | A flood of requests from one browser or source shall be rate-limited without… | SDD 3.5 `web.security` | — | Test | `TC-WCON-770` |
| `WCON-780` | MVP | While the event stream is down, the page shall mark all state as stale and… | SDD 3.7 `web.events`; SDD 3.10 `web.ui` | — | Test | `TC-WCON-780` |

### `WCON` — Web user interface

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `WCON-800` | MVP | be built from server-rendered templates with light JavaScript (PSD D2). A… | SDD 3.10 `web.ui`; SDD 3.5 `web.security` | — | Test | `TC-WCON-800` |
| `WCON-810` | MVP | be responsive and **tablet-first**: the large layout shows the sky view, image… | SDD 3.10 `web.ui` | — | Test | `TC-WCON-810` |
| `WCON-820` | MVP | provide a screen or section for each operational area of Section 3.5, driven by… | SDD 3.10 `web.ui` | — | Test | `TC-WCON-820` |
| `WCON-830` | MVP | guide a new browser through pairing (Section 3.2): request, display of the… | SDD 3.4 `web.session`; SDD 3.10 `web.ui` | — | Test | `TC-WCON-830` |
| `WCON-840` | MVP | show at all times the browser's role, the lease state of the selected Pier and… | SDD 3.10 `web.ui` | — | Test | `TC-WCON-840` |
| `WCON-850` | MVP | hide operations a Viewer cannot perform, shall present the confirmation of… | SDD 3.10 `web.ui` | — | Test | `TC-WCON-850` |
| `WCON-860` | MVP | provide a night-vision (red) theme that emits no non-red light — including form… | SDD 3.10 `web.ui` | — | Test | `TC-WCON-860` |
| `WCON-870` | P2 | be operable by keyboard and expose roles, names and live regions to assistive… | SDD 3.10 `web.ui` | — | Test | `TC-WCON-870` |
| `WCON-880` | MVP | be tested against the browser support matrix of PSD PC8 (current Chrome and… | SDD 3.10 `web.ui` | — | Test (browser matrix) | `TC-WCON-880` |
| `WCON-890` | P2 | provide help for each screen, and an About view showing the Galileo, plugin and… | SDD 3.10 `web.ui` | — | Test | `TC-WCON-890` |

### `WCON` — Options, help and wire API

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `WCON-900` | MVP | add a **WebConnect** page under Options (`PLUG-170`) in which a Master user… | SDD 3.13 `config, ui` | — | Test | `TC-WCON-900` |
| `WCON-910` | MVP | provide, and persist in Galileo's database under the plugin's namespace… | SDD 3.13 `config, ui` | — | Test | `TC-WCON-910` |
| `WCON-920` | MVP | describe its browser-facing API in a published, language-neutral form (OpenAPI… | SDD 3.14 `wire` | — | Test | `TC-WCON-920` |
| `WCON-930` | MVP | perform the Connect Link version handshake (L8) when its web process starts and… | SDD 3.14 `wire` | — | Test | `TC-WCON-930` |
| `WCON-940` | MVP | ship help Markdown for every control on its plugin page and Options page… | SDD 3.13 `config, ui` | — | Test | `TC-WCON-940` |

### `WCON` — Web application security

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `WCON-1000` | MVP | Every state-changing request (any method other than GET, HEAD, OPTIONS) shall… | SDD 3.5 `web.security` | — | Test | `TC-WCON-1000` |
| `WCON-1010` | MVP | Session and device cookies shall be `HttpOnly`, `Secure` and `SameSite=Strict`,… | SDD 3.4 `web.session` | — | Test | `TC-WCON-1010` |
| `WCON-1020` | MVP | Every response shall carry a strict `Content-Security-Policy` that permits no… | SDD 3.5 `web.security` | — | Test | `TC-WCON-1020` |
| `WCON-1030` | MVP | Sign-in, pairing requests and any other unauthenticated entry point shall be… | SDD 3.5 `web.security` | — | Test | `TC-WCON-1030` |
| `WCON-1040` | MVP | A session shall expire after configurable idle and absolute timeouts, after… | SDD 3.4 `web.session` | — | Test | `TC-WCON-1040` |
| `WCON-1050` | MVP | Every route shall require an authenticated session, a role check and (for… | SDD 3.5 `web.security` | — | Test | `TC-WCON-1050` |
| `WCON-1060` | MVP | The application shall reject a request whose `Host` or `Origin` is not one of… | SDD 3.5 `web.security` | — | Test | `TC-WCON-1060` |
| `WCON-1070` | P2 | undergo a documented security review (CSRF, session handling, header policy,… | SDD 3.5 `web.security` | — | Inspection | `TC-WCON-1070` |

### `WCON` — Browser outreach

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `WCON-1200` | MVP | The owner shall choose, on Connect Link's Outreach page, whether an event is… | SDD 3.11 `outreach` | OF | Test | `TC-WCON-1200` |
| `WCON-1210` | MVP | serve browser outreach from a **separate, minimal Flask application** with its… | SDD 3.12 `outreach_app`; SDD 3.2 `supervisor` | — | Test | `TC-WCON-1210` |
| `WCON-1220` | MVP | The operating web application shall not be reachable on the outreach listener,… | SDD 3.5 `web.security`; SDD 3.12 `outreach_app` | — | Test | `TC-WCON-1220` |
| `WCON-1230` | MVP | The event display shall include a **web QR code** encoding an HTTPS address of… | SDD 3.11 `outreach` | OF | Test | `TC-WCON-1230` |
| `WCON-1240` | MVP | read the fragment, exchange the secret for a guest token by a single enrolment… | SDD 3.12 `outreach_app` | — | Test | `TC-WCON-1240` |
| `WCON-1250` | MVP | A guest token (`outreach.view` and nothing else) shall permit exactly: listing… | SDD 3.12 `outreach_app` | — | Test | `TC-WCON-1250` |
| `WCON-1260` | MVP | push to each visitor the **live image of the chosen Pier as each frame… | SDD 3.12 `outreach_app` | — | Test | `TC-WCON-1260` |
| `WCON-1270` | MVP | Images sent to visitors shall be the facility's guest previews: limited to the… | SDD 3.11 `outreach` | OF | Test | `TC-WCON-1270` |
| `WCON-1280` | MVP | be hardened for the public: a strict `Content-Security-Policy` with no inline… | SDD 3.12 `outreach_app` | OF | Test | `TC-WCON-1280` |
| `WCON-1290` | MVP | The outreach listener shall serve HTTPS only, using a certificate the owner… | SDD 3.12 `outreach_app`; SDD 3.2 `supervisor`; SDD 3.11 `outreach` | — | Test | `TC-WCON-1290` |
| `WCON-1300` | MVP | be designed for a phone held by a visitor: usable on any current browser, dark… | SDD 3.12 `outreach_app` | — | Test | `TC-WCON-1300` |
| `WCON-1310` | MVP | confine outreach enrolment and guest requests to source addresses inside the… | SDD 3.12 `outreach_app`; SDD 3.11 `outreach`; SDD 3.2 `supervisor` | OF | Test | `TC-WCON-1310` |
| `WCON-1320` | MVP | provide, and persist in Galileo's database (`PLUG-150`), these browser-outreach… | SDD 3.11 `outreach`; SDD 3.13 `config, ui` | — | Test | `TC-WCON-1320` |
| `WCON-1330` | P2 | contribute to the facility's aggregate audit the number of browser guests per… | SDD 3.11 `outreach` | OF | Test | `TC-WCON-1330` |

---

## 3. Summary by Domain

| Domain | Requirements | MVP | P2 | P3 |
|---|---|---|---|---|
| `WCON` | 105 | 89 | 14 | 2 |
| **Total** | **105** | **89** | **14** | **2** |

---

## 4. Cross-Reference to Core

Requirements this plugin's rows trace to but do not define: `PLUG-010`–`PLUG-190` (plugin framework, settings, panel placement), `OBS-150` (Dashboard timelines), `SES-340` (plugin session blocks), `HELP-060` (plugin help), the `MCON` requirements cited by `WCON-4xx` (the shared operational surface), and the proposed Connect Link (`LINK-*`, including delegated identity and the outreach facility) and Control Surface additions listed in SRS Section 2.6, which are not yet in the core SRS.
