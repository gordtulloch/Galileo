# Generic Relay Plugin — SRS (Software Requirements Specification)

| | |
|---|---|
| **Project** | Galileo — Generic Relay Plugin |
| **Document** | SRS (Software Requirements Specification), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-05 |
| **Upstream document** | [PSD (Project Scope Document)](PSD.md) |
| **Downstream documents** | SDD ([SDD.md](SDD.md)), RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SRS](../../SRS.md) |

---

## 1. Introduction

### 1.1 Purpose

This SRS decomposes the `RELAY` requirement domain identified in [this plugin's PSD](PSD.md) (Section 7) into individually numbered, verifiable requirements, structurally parallel to [Galileo core's own SRS](../../SRS.md) and [the VSTarget plugin's SRS](../vstarget/SRS.md).

### 1.2 Scope

Covers the `RELAY` domain only. Everything else this plugin depends on (plugin loading/versioning/isolation, device-backend registration, secondary-panel UI insertion) is an existing core requirement, listed in [PSD.md Section 6](PSD.md#6-dependencies-on-galileo-core) and cited by ID below rather than redefined here.

### 1.3 Requirement ID Convention

Unchanged from core: `<DOMAIN>-<###>`, numbered in increments of 10.

### 1.4 Priority Convention

Identical to [core SRS Section 1.4](../../SRS.md#14-priority-convention): MVP / P2 / P3.

### 1.5 References

- [This plugin's PSD](PSD.md)
- [Galileo Core SRS](../../SRS.md), particularly `EQP-SW-010` and the `PLUG` domain

---

## 2. Overall Description

### 2.1 Product Perspective

This plugin is not a standalone product — it is a first-party plugin against Galileo core's plugin architecture (core `PLUG` domain), distributed as a downloadable ZIP from the Galileo Plugins repository and installed by the user through the Options > Plugins screen (core `PLUG-090`/`PLUG-110`). Once installed, it is independently enabled/disabled by the user (core `PLUG-060`).

### 2.2 Product Functions (Summary)

Toggle the relays of a generic HTTP relay board by issuing a GET built from a configurable URL template, presented as a tabbed panel supporting any number of boards.

### 2.3 User Classes and Characteristics

See [this plugin's PSD Section 8](PSD.md#8-stakeholders-and-primary-persona) — the Observatory Operator persona.

### 2.4 Operating Environment

Identical to core (Windows/macOS/Linux) — this plugin introduces no additional platform constraint. Requires the relay board to be reachable via HTTP from the Galileo host.

### 2.5 Design and Implementation Constraints

- Distributed as a ZIP installable via core `PLUG-090`/`PLUG-110`; loaded exclusively through core's plugin extension points (`PLUG-010`–`PLUG-120`); no direct import of core adapter internals.
- No board-specific vendor code — every board is addressed through the same configurable template (PSD Section 5, non-goal: no auto-detection).

### 2.6 Assumptions and Dependencies

See [this plugin's PSD Section 6](PSD.md#6-dependencies-on-galileo-core) (core capabilities consumed) and Section 9 (PC1–PC3).

---

## 3. Functional Requirements

### 3.1 `RELAY` — Generic Internet Relay Control

Delivered as a first-party, independently-installable, independently-disableable plugin (core `PLUG-060`) — not a core-compiled module. Presented as a secondary-level panel (core `PLUG-070`) when enabled.

| ID | Requirement | Priority |
|---|---|---|
| RELAY-010 | The system shall build each relay-toggle request from a user-configurable URL template with `{ip}`, `{port}` (zero-based relay index), and `{state}` (1/0) placeholders, defaulting to a template that reproduces the motivating reference example exactly: relay 1 on → `http://<ip>/30000/01`, relay 1 off → `http://<ip>/30000/00`. | MVP |
| RELAY-020 | The system shall allow the user to configure, per relay board, its host/IP, its number of relays, and its URL template; the system shall enumerate exactly that many Switches (traces to core `EQP-SW-010`), named `Relay 1`…`Relay N`. | MVP |
| RELAY-030 | The system shall toggle a relay by issuing an HTTP GET to the URL built from the configured template with that relay's zero-based index and the requested state, and shall update its own tracked state only on a successful response. | MVP |
| RELAY-040 | The system shall raise a reportable error, rather than silently succeeding, when asked to toggle a relay name that is not among the configured relays, or when the HTTP request fails (unreachable host, non-success response). | MVP |
| RELAY-050 | The system shall present a panel listing every configured relay board as its own tab, each a table of that board's relays with a click-to-toggle status cell; a new board shall be addable via a "+" control (prompting for host/IP, relay count, and the URL template, pre-filled with the default from `RELAY-010`), an existing board removable by closing its tab, and the configured board list shall persist across application restarts. | MVP |

---

## 4. Requirement Summary Counts (for RTM Seeding)

| Domain | Requirement Count | MVP | P2 | P3 |
|---|---|---|---|---|
| RELAY | 5 | 5 | 0 | 0 |
| **Total** | **5** | | | |

---

## 5. Path to SDD / Traceability Matrix

1. **SDD** — [SDD.md](SDD.md), describing how this plugin's module satisfies the requirements above and which core ports/services it consumes.
2. **Traceability Matrix** — [RTM.md](RTM.md), a row per requirement ID here, mapped to its SDD component and a test case ID.

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SRS](../../SRS.md).*
