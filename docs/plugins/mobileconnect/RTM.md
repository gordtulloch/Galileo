# MobileConnect Plugin — RTM (Requirements Traceability Matrix)

| | |
|---|---|
| **Project** | Galileo — MobileConnect Plugin |
| **Document** | RTM (Requirements Traceability Matrix), v0.1, draft — **seeded from the SRS; SDD components mapped, tests not yet written** |
| **Status** | Draft — for review |
| **Date** | 2026-10-29 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md), [SDD](SDD.md) |
| **Parent project** | [Galileo Core RTM](../../RTM.md) |

---

## 1. Purpose and Method

This RTM seeds a row for every requirement in [this plugin's SRS](SRS.md) with a reserved Test Case ID, so tests can be written against stable IDs. **Test Case ID convention:** `TC-<requirement-ID>` (e.g. `TC-MCON-010` verifies `MCON-010`); several test functions may carry one ID. The **SDD Component** column maps each row to its section of the [SDD](SDD.md). Counts follow the SRS summary table.

**Verification Method:** `Test` (automated) unless stated. `Test (app repo)` and `Inspection (app repo)` mark requirements that bind the client apps and are verified in the [Galileo-MobileConnect](https://github.com/gordtulloch/Galileo-MobileConnect) repository, with only the node side tested here.

**Core prerequisite:** the proposed core capability a row cannot be verified without, as flagged "(needs …)" in the SRS. Until that capability exists in the core SRS the row stays reserved but unverifiable.

**Coverage:** 107 requirements, 100% mapped to an SDD component; 0 tests written. Client-app requirements map to SDD 3.17 and are verified in the app repository.

---

## 2. Traceability Matrix


### `MCON` — Packaging, lifecycle and placement

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `MCON-010` | MVP | be delivered as a first-party plugin with the manifest identity MCON, dis… | SDD 3.1 `plugin` | — | Test | `TC-MCON-010` |
| `MCON-020` | MVP | be installable and enabled only on a Master node | SDD 3.1 `plugin` | — | Test | `TC-MCON-020` |
| `MCON-030` | MVP | While enabled, the system shall register its versioned routes and event topics with Connec… | SDD 3.1 `plugin` | CL | Test | `TC-MCON-030` |
| `MCON-040` | MVP | While disabled, the system shall be fully inert (PLUG-060): every MobileConnect route is u… | SDD 3.1 `plugin` | — | Test | `TC-MCON-040` |
| `MCON-050` | MVP | add a top-level **MobileConnect** section (PLUG-130) showing connected cl… | SDD 3.15 `ui, config` | — | Test | `TC-MCON-050` |
| `MCON-060` | MVP | A fault in the plugin or in any client session (malformed request, abrupt disconnect, a cr… | SDD 3.1 `plugin`; SDD 3.2 `gateway` | — | Test | `TC-MCON-060` |
| `MCON-070` | MVP | never run network or rendering work on the Qt UI thread; operations shall… | SDD 3.1 `plugin`; SDD 3.2 `gateway` | — | Test | `TC-MCON-070` |
| `MCON-080` | MVP | keep serving cost bounded so a Raspberry Pi 5-class Master running a sess… | SDD 3.12 `governor` | — | Test | `TC-MCON-080` |

### `MCON` — Pairing, roles, lease and audit

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `MCON-100` | MVP | accept a pairing request from an app only through Connect Link's pairing … | SDD 3.3 `clients` | CL | Test | `TC-MCON-100` |
| `MCON-110` | MVP | assign every paired client one of two roles, **Viewer** (state, events an… | SDD 3.3 `clients` | — | Test | `TC-MCON-110` |
| `MCON-120` | MVP | enforce the role on the Master for every request: a Viewer's operation re… | SDD 3.2 `gateway` | — | Test | `TC-MCON-120` |
| `MCON-130` | MVP | never grant a paired client the config.* scope (Connect Link L3) and shal… | SDD 3.2 `gateway` | — | Test | `TC-MCON-130` |
| `MCON-140` | MVP | provide a **control lease** per Pier (needs LS) | SDD 3.4 `lease` | LS | Test | `TC-MCON-140` |
| `MCON-150` | MVP | When an operation is refused because another party holds the lease, the refusal shall iden… | SDD 3.4 `lease` | — | Test | `TC-MCON-150` |
| `MCON-160` | MVP | The Emergency operations (MCON-710) shall not require the lease and shall be permitted to … | SDD 3.13 `hold, emergency` | — | Test | `TC-MCON-160` |
| `MCON-170` | MVP | let the user on the Master revoke any paired client, immediately and perm… | SDD 3.3 `clients` | — | Test | `TC-MCON-170` |
| `MCON-180` | MVP | require confirmation for operations that are destructive or hard to rever… | SDD 3.5 `confirm, idempotency` | — | Test | `TC-MCON-180` |
| `MCON-190` | MVP | record every request by every client — client, role, Pier, operation and … | SDD 3.6 `audit` | — | Test | `TC-MCON-190` |

### `MCON` — Proxying through the Master

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `MCON-200` | MVP | present to a client the Piers of the Master and, through it, those of eve… | SDD 3.9 `relay` | — | Test | `TC-MCON-200` |
| `MCON-210` | MVP | For a spoke's Pier, the system shall relay operations, state, events and previews over Con… | SDD 3.9 `relay` | WR | Test | `TC-MCON-210` |
| `MCON-220` | MVP | reach a spoke only if the spoke's user has granted the Master the opt-in … | SDD 3.9 `relay` | — | Test | `TC-MCON-220` |
| `MCON-230` | MVP | The control lease for a spoke's Pier shall be held on that spoke, so the spoke's desktop, … | SDD 3.4 `lease`; SDD 3.9 `relay` | — | Test | `TC-MCON-230` |
| `MCON-240` | MVP | When the Master is down or a spoke is detached or unreachable, the system shall show that … | SDD 3.9 `relay` | — | Test | `TC-MCON-240` |

### `MCON` — State and events

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `MCON-300` | MVP | On connection the system shall send each client a complete snapshot of the state of every … | SDD 3.8 `state, events` | — | Test | `TC-MCON-300` |
| `MCON-310` | MVP | deliver state and events by push over the Connect Link event stream (need… | SDD 3.8 `state, events` | CL | Test | `TC-MCON-310` |
| `MCON-320` | MVP | The state delivered shall include, for each Pier, the same activity record as the Dashboar… | SDD 3.8 `state, events` | — | Test | `TC-MCON-320` |
| `MCON-330` | MVP | Long-running operations (slew, solve, autofocus run, session, calibration set, flip) shall… | SDD 3.8 `state, events` | OE | Test | `TC-MCON-330` |
| `MCON-340` | MVP | forward the node's alerts to connected clients and keep a recent-alerts l… | SDD 3.8 `state, events` | — | Test | `TC-MCON-340` |
| `MCON-350` | MVP | On reconnection after a drop the system shall resend a snapshot, and events missed in a sh… | SDD 3.8 `state, events` | — | Test | `TC-MCON-350` |
| `MCON-360` | P2 | deliver the state of a Pier to a client only if that Pier is among those … | SDD 3.8 `state, events` | — | Test | `TC-MCON-360` |

### `MCON` — Operations

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `MCON-400` | MVP | publish the operations to a client as a catalogue from the Control Surfac… | SDD 3.7 `catalogue, dispatch`; SDD 3.16 `wire` | — | Test | `TC-MCON-400` |
| `MCON-410` | MVP | Observatory and Pier | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-410` |
| `MCON-420` | MVP | Devices | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-420` |
| `MCON-421` | MVP | After a mount connects through an operation of this plugin, the same date/time and site la… | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-421` |
| `MCON-430` | MVP | Imaging | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-430` |
| `MCON-440` | MVP | Sky and framing | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-440` |
| `MCON-450` | MVP | Plate solving and alignment | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-450` |
| `MCON-460` | MVP | Guiding | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-460` |
| `MCON-470` | MVP | Focus | SDD 3.7 `catalogue, dispatch` | MF | Test | `TC-MCON-470` |
| `MCON-480` | MVP | Meridian flip | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-480` |
| `MCON-490` | MVP | Sessions, run | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-490` |
| `MCON-500` | P2 | Sessions, authoring | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-500` |
| `MCON-510` | P2 | Scheduler | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-510` |
| `MCON-520` | P2 | Calibration | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-520` |
| `MCON-530` | MVP | Safety | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-530` |
| `MCON-540` | P2 | Library and history | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-540` |
| `MCON-550` | P2 | Notifications | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-550` |
| `MCON-560` | P3 | Plugin surfaces | SDD 3.7 `catalogue, dispatch` | — | Test | `TC-MCON-560` |
| `MCON-570` | MVP | Per-run parameters | SDD 3.2 `gateway` | — | Test | `TC-MCON-570` |
| `MCON-580` | MVP | validate every operation's arguments on the Master against the Control Su… | SDD 3.2 `gateway` | — | Test | `TC-MCON-580` |

### `MCON` — Images, previews and sky streaming

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `MCON-600` | MVP | deliver images as server-rendered previews (needs PV): stretched, binned … | SDD 3.10 `previews` | PV | Test | `TC-MCON-600` |
| `MCON-610` | P2 | offer a preview as tiles of a pyramid for pan and zoom, and shall cache r… | SDD 3.10 `previews` | CL | Test | `TC-MCON-610` |
| `MCON-620` | P3 | allow an Operator to download a full FITS frame as an explicit action, re… | SDD 3.10 `previews` | — | Test | `TC-MCON-620` |
| `MCON-630` | P2 | expose the preview quality and maximum size as options (MCON-910) and sha… | SDD 3.10 `previews`; SDD 3.12 `governor` | — | Test | `TC-MCON-630` |
| `MCON-640` | MVP | stream sky data to clients that render the sky locally (needs SK): catalo… | SDD 3.11 `skystream` | SK | Test | `TC-MCON-640` |
| `MCON-650` | MVP | report in the capability handshake (MCON-930) whether sky streaming is av… | SDD 3.11 `skystream`; SDD 3.16 `wire` | — | Test | `TC-MCON-650` |
| `MCON-660` | MVP | Sky streaming shall be requested by region, limiting magnitude and level of detail, progre… | SDD 3.11 `skystream` | — | Test | `TC-MCON-660` |
| `MCON-670` | MVP | The tile pyramid of MCON-610 shall be available for the current exposure, the live stack a… | SDD 3.10 `previews` | — | Test | `TC-MCON-670` |
| `MCON-680` | MVP | Streaming shall always yield to a running session, shall be rate-limited per client, shall… | SDD 3.11 `skystream`; SDD 3.12 `governor` | — | Test | `TC-MCON-680` |

### `MCON` — Safety and failure behaviour

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `MCON-700` | MVP | Every operation shall pass through the same core services and safety interlocks as the des… | SDD 3.2 `gateway` | — | Test | `TC-MCON-700` |
| `MCON-710` | MVP | provide Emergency operations — **Stop everything**, **Park**, **Close dom… | SDD 3.13 `hold, emergency` | — | Test | `TC-MCON-710` |
| `MCON-720` | MVP | Imaging shall continue, unchanged, when a client disconnects, sleeps or loses signal; the … | SDD 3.13 `hold, emergency` | — | Test | `TC-MCON-720` |
| `MCON-730` | MVP | A manual slew or jog and a focuser move started from a client shall run only while its kee… | SDD 3.13 `hold, emergency` | DM | Test | `TC-MCON-730` |
| `MCON-740` | MVP | Reconnection shall restore the live view and shall not repeat any operation that was in fl… | SDD 3.5 `confirm, idempotency` | — | Test | `TC-MCON-740` |
| `MCON-750` | MVP | Where a command is refused because the lease is held elsewhere, the Pier is unsafe, the de… | SDD 3.2 `gateway` | — | Test | `TC-MCON-750` |
| `MCON-760` | MVP | The lease shall not be silently held by a client that has gone away: on disconnect or idle… | SDD 3.4 `lease` | — | Test | `TC-MCON-760` |
| `MCON-770` | P2 | A flood of requests from one client shall be rate-limited per client without affecting oth… | SDD 3.12 `governor` | — | Test | `TC-MCON-770` |

### `MCON` — Mobile apps (scope level)

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `MCON-800` | MVP | include native apps for iPadOS/iOS (Swift, SwiftUI) and Android (Kotlin, … | SDD 3.17 `client apps (app repo)` | — | Inspection (app repo) | `TC-MCON-800` |
| `MCON-810` | MVP | be **tablet-first**: the tablet layout shows the sky view, image and sessio… | SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-810` |
| `MCON-820` | MVP | provide a screen or section for each operational area of Section 3.5, drive… | SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-820` |
| `MCON-830` | MVP | pair with the Master by discovery on the LAN (Connect Link L4) or manual ad… | SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-830` |
| `MCON-840` | MVP | show the client's role, the lease state of the selected Pier and who holds … | SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-840` |
| `MCON-850` | MVP | hide operations a Viewer cannot perform, shall mark every confirmed operati… | SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-850` |
| `MCON-860` | MVP | provide a night-vision (red) theme that does not emit non-red light, includ… | SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-860` |
| `MCON-870` | MVP | comply with each store's policies, including the iOS local-network permissi… | SDD 3.17 `client apps (app repo)` | — | Inspection (app repo) | `TC-MCON-870` |
| `MCON-880` | P2 | be generated from, and tested against, one OpenAPI description and one shar… | SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-880` |
| `MCON-890` | P2 | provide an in-app help for each screen, and an About screen showing the app… | SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-890` |

### `MCON` — Options, help and wire API

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `MCON-900` | MVP | add a **MobileConnect** page under Options (PLUG-170) in which a Master u… | SDD 3.15 `ui, config` | — | Test | `TC-MCON-900` |
| `MCON-910` | MVP | provide, and persist in Galileo's database under the plugin's namespace (… | SDD 3.15 `ui, config` | — | Test | `TC-MCON-910` |
| `MCON-920` | MVP | describe its wire API in a published, language-neutral form: an OpenAPI d… | SDD 3.16 `wire` | — | Test | `TC-MCON-920` |
| `MCON-930` | MVP | perform the Connect Link version handshake (L8) and extend it with the pl… | SDD 3.16 `wire` | — | Test | `TC-MCON-930` |
| `MCON-940` | MVP | ship in-app help Markdown for every control on its plugin page and Option… | SDD 3.15 `ui, config` | — | Test | `TC-MCON-940` |

### `MCON` — Meta Quest headset clients

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `MCON-1000` | MVP | Parity | SDD 3.2 `gateway`; SDD 3.17 `client apps (app repo)` | — | Test | `TC-MCON-1000` |
| `MCON-1010` | MVP | Pairing and identification | SDD 3.3 `clients` | — | Test | `TC-MCON-1010` |
| `MCON-1020` | MVP | Same safety model | SDD 3.2 `gateway`; SDD 3.13 `hold, emergency` | — | Test | `TC-MCON-1020` |
| `MCON-1030` | MVP | Held motion | SDD 3.13 `hold, emergency`; SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-1030` |
| `MCON-1040` | MVP | Suspension | SDD 3.8 `state, events`; SDD 3.13 `hold, emergency` | — | Test | `TC-MCON-1040` |
| `MCON-1050` | MVP | Immersive planetarium | SDD 3.11 `skystream`; SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-1050` |
| `MCON-1060` | MVP | Immersive image viewer | SDD 3.10 `previews`; SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-1060` |
| `MCON-1070` | MVP | Wearer safety | SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-1070` |
| `MCON-1080` | MVP | Platform and distribution | SDD 3.17 `client apps (app repo)` | — | Inspection (app repo) | `TC-MCON-1080` |
| `MCON-1090` | MVP | Master tier disclosure | SDD 3.16 `wire`; SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-1090` |
| `MCON-1100` | P3 | Further VR adaptations | SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-1100` |

### `MCON` — Outreach mode

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `MCON-1200` | MVP | provide outreach mode that is **off by default** and operates only within… | SDD 3.14 `outreach` | OF | Test | `TC-MCON-1200` |
| `MCON-1210` | MVP | On opening an event the system shall display on the Master a **QR code** carrying the Mast… | SDD 3.14 `outreach` | OF | Test | `TC-MCON-1210` |
| `MCON-1220` | MVP | enrol a device that presents a valid event secret by issuing it an **anon… | SDD 3.14 `outreach` | CL, OF | Test | `TC-MCON-1220` |
| `MCON-1230` | MVP | answer outreach enrolment and guest requests **only from source addresses… | SDD 3.14 `outreach` | OF | Test | `TC-MCON-1230` |
| `MCON-1240` | MVP | A guest token shall permit exactly: listing the Piers offered for outreach (display names … | SDD 3.14 `outreach` | — | Test | `TC-MCON-1240` |
| `MCON-1250` | MVP | push to each guest the **live image of the Pier it is viewing as each fra… | SDD 3.14 `outreach` | — | Test | `TC-MCON-1250` |
| `MCON-1260` | MVP | let the owner choose which Piers an event offers (MCON-1310); a Pier not … | SDD 3.14 `outreach` | — | Test | `TC-MCON-1260` |
| `MCON-1270` | MVP | Previews sent to guests shall carry **no FITS header, EXIF, GPS or other embedded metadata… | SDD 3.10 `previews`; SDD 3.14 `outreach` | — | Test | `TC-MCON-1270` |
| `MCON-1280` | MVP | bound guest load: a configurable cap on concurrent guests (refusing furth… | SDD 3.12 `governor`; SDD 3.14 `outreach` | OF | Test | `TC-MCON-1280` |
| `MCON-1290` | MVP | audit each event (who opened and closed it, when, which Piers were offere… | SDD 3.6 `audit`; SDD 3.14 `outreach` | OF | Test | `TC-MCON-1290` |
| `MCON-1300` | MVP | show the owner on the Master, while an event is open, the QR code, the ti… | SDD 3.14 `outreach`; SDD 3.15 `ui, config` | OF | Test | `TC-MCON-1300` |
| `MCON-1310` | MVP | provide, and persist in Galileo's database (PLUG-150), these outreach opt… | SDD 3.15 `ui, config`; SDD 3.14 `outreach` | OF | Test | `TC-MCON-1310` |
| `MCON-1320` | P2 | The handshake (MCON-930) shall tell an app whether an outreach event is open and the limit… | SDD 3.16 `wire` | — | Test | `TC-MCON-1320` |
| `MCON-1330` | MVP | The iOS/iPadOS and Android apps shall offer a **guest entry**, reached by scanning the eve… | SDD 3.17 `client apps (app repo)` | — | Test (app repo) | `TC-MCON-1330` |

---

## 3. Summary by Domain

| Domain | Requirements | MVP | P2 | P3 |
|---|---|---|---|---|
| `MCON` | 107 | 92 | 12 | 3 |
| **Total** | **107** | **92** | **12** | **3** |

---

## 4. Cross-Reference to Core

Requirements this plugin's rows trace to but do not define: `PLUG-010`–`PLUG-190` (plugin framework, settings, panel placement), `HELP-060` (plugin help), and the proposed Connect Link (`LINK-*`) and related core additions listed in the SRS Section 2.6 / PSD Section 6, which are not yet in the core SRS.
