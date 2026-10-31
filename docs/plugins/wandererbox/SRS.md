# WandererBox Plugin — SRS (Software Requirements Specification)

| | |
|---|---|
| **Project** | Galileo — WandererBox Plugin |
| **Document** | SRS (Software Requirements Specification), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-30 |
| **Upstream document** | [PSD (Project Scope Document)](PSD.md) |
| **Downstream documents** | SDD ([SDD.md](SDD.md)), RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SRS](../../SRS.md) |

---

## 1. Introduction

### 1.1 Purpose

This SRS decomposes the `WBOX` requirement domain identified in [this plugin's PSD](PSD.md) (Section 7) into individually numbered, verifiable requirements, structurally parallel to [Galileo core's own SRS](../../SRS.md) and the [Kasa Switch plugin's SRS](../kasa_switch/SRS.md).

### 1.2 Scope

Covers the `WBOX` domain only: the switch **profiles** for the WandererBox Pro V3, Plus V3 and Dew Terminator. Everything the profiles are *applied by* — INDI connection, discovery, the Switch model, the mapping engine, writes, the Equipment > Switches page, and the profile registry — is **core** (`EQP-SW-020`–`EQP-SW-120`, `PLUG-210`) and is cited by ID below, not redefined. In particular this plugin has no panel, no device protocol and no configuration of its own.

### 1.3 Requirement ID Convention

Unchanged from core: `<DOMAIN>-<###>`, numbered in increments of 10.

### 1.4 Priority Convention

Identical to [core SRS Section 1.4](../../SRS.md#14-priority-convention): MVP / P2 / P3. These requirements are MVP *for this plugin*; they can only be exercised on a Galileo that includes the P2 core requirements they depend on (PSD R7).

### 1.5 References

- [This plugin's PSD](PSD.md), particularly Section 13 (the driver facts the profiles are built from)
- [Galileo Core SRS](../../SRS.md): `EQP-SW-020`–`EQP-SW-120`, `PLUG-060`, `PLUG-120`, `PLUG-210`
- The three INDI driver sources listed in the PSD's References

---

## 2. Overall Description

### 2.1 Product Perspective

This plugin is not a standalone product. It is a first-party plugin distributed as a downloadable ZIP from the Galileo Plugins repository and installed through Options > Plugins (core `PLUG-090`/`PLUG-110`), independently enabled/disabled (`PLUG-060`). Its only contribution is a set of declarative switch profiles registered through `PluginContext` (`PLUG-210`); core applies them with the same engine it uses for INDI power-interface devices.

### 2.2 Product Functions (Summary)

Teach core to present three Wanderer Astro power products — whose INDI drivers use custom properties — as grouped, labelled, toggleable Switch devices with dew duty, regulator voltage and sensor read-outs.

### 2.3 User Classes and Characteristics

See [this plugin's PSD Section 8](PSD.md#8-stakeholders-and-primary-persona).

### 2.4 Operating Environment

Identical to core. Requires an INDI server reachable from the Galileo host with the matching WandererAstro driver loaded (PSD PC1).

### 2.5 Design and Implementation Constraints

- Loaded only through core's plugin extension points; no import of adapter internals.
- Contains no INDI client code and opens no connection (PSD G7).
- Stores no configuration (CLAUDE.md firm rule: configuration lives in the database; the chosen device is saved by core's device-configuration flow).

### 2.6 Assumptions and Dependencies

See [this plugin's PSD Section 6](PSD.md#6-dependencies-on-galileo-core) (core capabilities consumed; those marked ★ were added to core together with this plugin) and Section 9 (PC1–PC5).

---

## 3. Functional Requirements

### 3.1 `WBOX` — Wanderer Switch Profiles

Delivered as a first-party, independently-installable, independently-disableable plugin (core `PLUG-060`). Channel names below are the vendor's port names, not the driver's internal numbering; the driver property each maps to is given in the SDD.

| ID | Requirement | Priority |
|---|---|---|
| WBOX-010 | The plugin shall register exactly three switch profiles — WandererBox Pro V3, WandererBox Plus V3 and Wanderer Dew Terminator — through core's profile registration (`PLUG-210`), and shall register nothing else: no device backend, panel, settings page, dock pane or session block. | MVP |
| WBOX-020 | Each profile shall declare the INDI device names it may report and a property signature (`EQP-SW-080`) sufficient to identify its model after connecting. The Pro V3 and Plus V3 profiles shall both claim the device name `WandererBox Pro V3` (the Plus V3 driver reports that name) and the Dew Terminator profile shall claim `Wanderer Dew Terminator`; identification shall never depend on the name alone. | MVP |
| WBOX-030 | The **Pro V3** profile shall present: the three USB 3.1 ports as three independent toggles; the two USB 2.0 groups of three as two toggles; the adjustable 5–13.2 V pair as one toggle with a voltage setting; the two 12 V groups as two toggles; and the three dew heater channels, each with the vendor's port names. | MVP |
| WBOX-040 | The **Plus V3** profile shall present: all USB ports as a single toggle; the adjustable 5–13.2 V port as one toggle with a voltage setting; the three 12 V switched ports as a single toggle; and the one dew heater channel, each with the vendor's port names. | MVP |
| WBOX-050 | The **Dew Terminator** profile shall present its three dew heater channels, each usable as a heater (duty) or as a plain switch, and shall present no USB, regulator or 12 V switch groups, which the device does not have. | MVP |
| WBOX-060 | For every dew heater channel the profile shall declare the driver's native duty range 0–255 so core presents 0–100 % (`EQP-SW-060`); because the drivers define no separate on/off property for a dew channel, switching one on shall set the maximum duty and off shall set zero, and a channel shall read as on when its duty is above zero. A channel whose PWM property the driver has removed (the driver is in a dew-point-difference or constant-temperature mode) shall have its duty control disabled, not fail. | MVP |
| WBOX-070 | The Pro V3 and Plus V3 profiles shall declare the 12 V normally-open port, and the Pro V3 profile also the 19 V mini-PC port, as display-only channels (`EQP-SW-080`): shown with their vendor names, with no toggle, and absent from the flat switch list (`EQP-SW-100`), since the hardware cannot switch them. | MVP |
| WBOX-080 | Each profile shall map the driver's read-only values to readings with units — input voltage, the currents the model measures (Pro: total, 19 V, adjustable regulator; Plus: total; Dew Terminator: none), the temperature probes the model has (Pro 3, Plus 1, Dew Terminator 3), ambient humidity, ambient temperature and dew point — and shall declare −127 as "no reading" for a temperature probe, so a missing probe shows as unavailable rather than −127 °C. | MVP |
| WBOX-090 | The three profiles' signatures shall be distinct: given the complete property set of any one of the three models, the intended profile shall be the one resolved (`EQP-SW-080`), including the Plus V3 resolving to the Plus V3 profile despite sharing the Pro V3's device name and the Dew Terminator's `DC2` (a number) not being mistaken for the Plus V3's `DC2` (a switch). | MVP |
| WBOX-100 | The plugin shall be data-only and inert when disabled: it shall hold no INDI connection and write no device-protocol code, and when it is disabled or removed its profiles shall not be offered (`PLUG-060`, `PLUG-120`), leaving the devices reachable through the Aux category. No profile shall claim any device name other than the two in `WBOX-020`, so no WandererBox Lite V3 or other Wanderer product is presented as supported. | MVP |

---

## 4. Requirement Summary Counts (for RTM Seeding)

| Domain | Requirement Count | MVP | P2 | P3 |
|---|---|---|---|---|
| WBOX | 10 | 10 | 0 | 0 |
| **Total** | **10** | | | |

---

## 5. Path to SDD / Traceability Matrix

1. **SDD** — [SDD.md](SDD.md), describing the profiles' data and how they attach to core.
2. **Traceability Matrix** — [RTM.md](RTM.md), a row per requirement ID here, mapped to its SDD component and a test case ID.

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SRS](../../SRS.md).*
