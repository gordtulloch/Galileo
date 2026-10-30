# NodeConnect Plugin — RTM (Requirements Traceability Matrix)

| | |
|---|---|
| **Project** | Galileo — NodeConnect Plugin |
| **Document** | RTM (Requirements Traceability Matrix), v0.1, draft — **seeded from the SRS; SDD components mapped, tests not yet written** |
| **Status** | Draft — for review |
| **Date** | 2026-10-29 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md), [SDD](SDD.md) |
| **Parent project** | [Galileo Core RTM](../../RTM.md) |

---

## 1. Purpose and Method

This RTM seeds a row for every requirement in [this plugin's SRS](SRS.md) with a reserved Test Case ID, so tests can be written against stable IDs. **Test Case ID convention:** `TC-<requirement-ID>` (e.g. `TC-NCON-010` verifies `NCON-010`); several test functions may carry one ID. The **SDD Component** column maps each row to its section of the [SDD](SDD.md). Counts follow the SRS summary table.

**Verification Method:** `Test` (automated) unless stated. `Test (app repo)` and `Inspection (app repo)` mark requirements that bind the client apps and are verified in the [Galileo-MobileConnect](https://github.com/gordtulloch/Galileo-MobileConnect) repository, with only the node side tested here.

**Core prerequisite:** the proposed core capability a row cannot be verified without, as flagged "(needs …)" in the SRS. Until that capability exists in the core SRS the row stays reserved but unverifiable.

**Coverage:** 44 requirements, 100% mapped to an SDD component; 0 tests written.

---

## 2. Traceability Matrix


### `NCON` — Roles and pairing

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `NCON-010` | MVP | be delivered as a first-party plugin (domain NCON) installable and remova… | SDD 3.1 `plugin` | — | Test | `TC-NCON-010` |
| `NCON-020` | MVP | let the user designate a **Master** for the node in the plugin's Options … | SDD 3.2 `roles, pairing` | — | Test | `TC-NCON-020` |
| `NCON-030` | MVP | not exchange configuration or data with a Master until the node is **pair… | SDD 3.2 `roles, pairing` | — | Test | `TC-NCON-030` |
| `NCON-040` | MVP | The system shall, on the Master, list pending and paired nodes with name, address, schema … | SDD 3.2 `roles, pairing`; SDD 3.5 `conflict, tombstones` | — | Test | `TC-NCON-040` |
| `NCON-050` | MVP | grant a paired node only the permissions config.read, config.write and da… | SDD 3.2 `roles, pairing` | — | Test | `TC-NCON-050` |
| `NCON-060` | MVP | keep the node's identity, pairing token and pinned certificate node-local… | SDD 3.2 `roles, pairing`; SDD 3.3 `registry, codec` | — | Test | `TC-NCON-060` |

### `NCON` — Configuration replication

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `NCON-100` | MVP | treat as replicable every table that has registered as replicable (C2), w… | SDD 3.3 `registry, codec` | — | Test | `TC-NCON-100` |
| `NCON-110` | MVP | exclude **node-local** items from replication by default: the node's iden… | SDD 3.3 `registry, codec` | — | Test | `TC-NCON-110` |
| `NCON-120` | MVP | The system shall, at start-up, ask the Master for the change set since the node's last-syn… | SDD 3.4 `sync` | — | Test | `TC-NCON-120` |
| `NCON-130` | MVP | The system shall, when a pairing is first approved, perform a **full** sync in place of an… | SDD 3.4 `sync` | — | Test | `TC-NCON-130` |
| `NCON-140` | MVP | The system shall, when a replicable record changes on a node, **ship that change to the Ma… | SDD 3.4 `sync` | — | Test | `TC-NCON-140` |
| `NCON-150` | MVP | The system shall, on the Master, **push** every change it holds (its own and those receive… | SDD 3.4 `sync` | — | Test | `TC-NCON-150` |
| `NCON-160` | MVP | decide *what has changed* from the Master-issued revision counter and not… | SDD 3.5 `conflict, tombstones`; SDD 3.8 `compat` | — | Test | `TC-NCON-160` |
| `NCON-170` | MVP | detect a **conflict** exactly: each change carries the revision it was ba… | SDD 3.5 `conflict, tombstones`; SDD 3.7 `snapshot, report` | — | Test | `TC-NCON-170` |
| `NCON-180` | MVP | propagate **deletions** by tombstone (C1): a record deleted on one node s… | SDD 3.5 `conflict, tombstones` | — | Test | `TC-NCON-180` |
| `NCON-190` | MVP | apply each table's changes **atomically**, inside a database transaction,… | SDD 3.6 `apply` | — | Test | `TC-NCON-190` |
| `NCON-200` | MVP | **hold** received changes while a session is running on the node (C4) and… | SDD 3.6 `apply` | — | Test | `TC-NCON-200` |
| `NCON-210` | MVP | exclude **secrets** (API keys, passwords and tokens held in settings) fro… | SDD 3.3 `registry, codec` | — | Test | `TC-NCON-210` |
| `NCON-220` | MVP | The system shall, before applying a change set, store a **snapshot** of every value it is … | SDD 3.7 `snapshot, report` | — | Test | `TC-NCON-220` |
| `NCON-230` | P2 | The system shall, when device and PHD2 addresses in a received change set contain a loopba… | SDD 3.6 `apply` | — | Test | `TC-NCON-230` |

### `NCON` — Startup, scheduling and compatibility

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `NCON-300` | MVP | start its sync at application start-up without blocking start-up or the U… | SDD 3.4 `sync` | — | Test | `TC-NCON-300` |
| `NCON-305` | MVP | perform a Connect Link version handshake (L8) before every sync | SDD 3.8 `compat`; SDD 3.6 `apply` | — | Test | `TC-NCON-305` |
| `NCON-310` | MVP | keep all background activity (link, queue worker, event-stream subscripti… | SDD 3.1 `plugin` | — | Test | `TC-NCON-310` |

### `NCON` — Status and reporting

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `NCON-320` | MVP | produce a **run report** for every sync recording: direction, time, revis… | SDD 3.7 `snapshot, report` | — | Test | `TC-NCON-320` |
| `NCON-330` | MVP | provide a **status view** showing: the Master and pairing state, connecti… | SDD 3.11 `ui, config` | — | Test | `TC-NCON-330` |
| `NCON-340` | P2 | raise a notification through Galileo's notification service when a sync o… | SDD 3.11 `ui, config` | — | Test | `TC-NCON-340` |

### `NCON` — History and image transfer

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `NCON-400` | MVP | send each node's **session history and metrics** to the Master asynchrono… | SDD 3.10 `history` | — | Test | `TC-NCON-400` |
| `NCON-410` | MVP | transfer **FITS frames and their Library catalog rows** (fitsFile, fitsSe… | SDD 3.9 `transfer` | — | Test | `TC-NCON-410` |
| `NCON-420` | MVP | feed the transfer queue from the event bus (frame written, session ended)… | SDD 3.9 `transfer` | — | Test | `TC-NCON-420` |
| `NCON-430` | MVP | transfer frames in chunks using Connect Link L7, streamed so that neither… | SDD 3.9 `transfer` | — | Test | `TC-NCON-430` |
| `NCON-440` | MVP | keep a detached node working: capture, history and queueing shall continu… | SDD 3.9 `transfer` | — | Test | `TC-NCON-440` |
| `NCON-450` | P2 | provide on the Options page a **bandwidth limit** and an **allowed-hours … | SDD 3.9 `transfer` | — | Test | `TC-NCON-450` |
| `NCON-460` | MVP | provide on the Options page a setting, **off by default**, to remove a no… | SDD 3.9 `transfer` | — | Test | `TC-NCON-460` |
| `NCON-470` | MVP | not attempt to merge two independently grown Libraries or reconcile user-… | SDD 3.9 `transfer` | — | Test | `TC-NCON-470` |
| `NCON-480` | MVP | Library records a location state of Local or On Master | SDD 3.9 `transfer` | C7 | Test | `TC-NCON-480` |
| `NCON-490` | MVP | Retrieve an On Master frame to the node | SDD 3.9 `transfer` | C7 | Test | `TC-NCON-490` |

### `NCON` — Options, help and packaging

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `NCON-500` | MVP | persist all of its own options in Galileo's database through ctx.settings… | SDD 3.11 `ui, config` | — | Test | `TC-NCON-500` |
| `NCON-510` | MVP | provide in-app help (HELP-060) for every control on its section and its O… | SDD 3.11 `ui, config` | — | Test | `TC-NCON-510` |
| `NCON-520` | MVP | ship a manifest declaring its minimum Galileo and plugin-API versions and… | SDD 3.1 `plugin` | — | Test | `TC-NCON-520` |
| `NCON-530` | MVP | isolate faults (PLUG-050): a failure in sync, transfer or reporting shall… | SDD 3.1 `plugin` | — | Test | `TC-NCON-530` |

### Non-functional

| SRS ID | Priority | Requirement | SDD Component | Core prerequisite | Verification | Test Case |
|---|---|---|---|---|---|---|
| `NCON-NFR-010` | P2 | A sync of a typical incremental change set (≤ 500 records) shall complete in under 5 secon… | SDD 3.4 `sync`; SDD 3.6 `apply` | — | Test | `TC-NCON-NFR-010` |
| `NCON-NFR-020` | MVP | Memory used by transfer shall be bounded by a small constant number of chunk buffers indep… | SDD 3.9 `transfer` | — | Test | `TC-NCON-NFR-020` |
| `NCON-NFR-030` | MVP | All traffic shall be carried by Connect Link's encrypted, authenticated transport | SDD 3.12 `wire`; SDD 3.2 `roles, pairing` | — | Test | `TC-NCON-NFR-030` |
| `NCON-NFR-040` | MVP | The plugin shall contain no platform-specific code and shall run unchanged on Windows, mac… | SDD 3.1 `plugin` | — | Test | `TC-NCON-NFR-040` |

---

## 3. Summary by Domain

| Domain | Requirements | MVP | P2 | P3 |
|---|---|---|---|---|
| `NCON` | 44 | 40 | 4 | 0 |
| **Total** | **44** | **40** | **4** | **0** |

---

## 4. Cross-Reference to Core

Requirements this plugin's rows trace to but do not define: `PLUG-010`–`PLUG-190` (plugin framework, settings, panel placement), `HELP-060` (plugin help), and the proposed Connect Link (`LINK-*`) and related core additions listed in the SRS Section 2.6 / PSD Section 6, which are not yet in the core SRS.
