# WandererBox Plugin — SDD (Software Design Description)

| | |
|---|---|
| **Project** | Galileo — WandererBox Plugin |
| **Document** | SDD (Software Design Description), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-30 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md) |
| **Downstream document** | RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SDD](../../SDD.md) |

---

## 1. Introduction

### 1.1 Purpose

This SDD describes the data this plugin supplies and how it attaches to [Galileo core's architecture](../../SDD.md) through the one extension point it uses, `PluginContext.register_switch_profile` (core SDD §4.20, `PLUG-210`).

### 1.2 Scope

Covers this plugin's single module (`wandererbox`), its ADRs, and its data design. Everything that *applies* a profile — property cache, mapping engine, signature resolution, writes, the Switches page — is core SDD §4.1, §4.2 and **§4.2a**, inherited and not restated.

### 1.3 References

- [This plugin's PSD](PSD.md), [SRS](SRS.md)
- [Galileo Core SDD](../../SDD.md): §4.1 (`SwitchProfile`, `SwitchPanel`), §4.2a (mapping engine, signature resolution, Switches page), §4.20 (`galileo.plugins`)

---

## 2. Design Considerations

### 2.1 Profiles as Data, Not a Plugin with Its Own Client and Panel (ADR-WBOX-001)

**Decision:** the plugin contributes three `SwitchProfile` values and nothing else. It has no INDI client, no panel and no settings.

**Rationale:** an earlier draft gave this plugin its own INDI code and tabbed panel, as the Kasa plugin does for TP-Link hardware. Kasa needs that because it speaks its own wire protocol. These devices are INDI devices, and most INDI power boxes (Pegasus, Terrans) use INDI's standard power interface, so core can serve them generically. Duplicating a panel, a polling loop and an INDI mapping in a plugin per vendor would have meant the Wanderer devices looked and behaved differently from every other power box. Making the plugin data-only means the Wanderer devices share core's page, its Sessions integration and its fault handling, and a plugin failure cannot affect the INDI connection.

**Consequence:** the plugin depends on core work (PSD R7), delivered alongside it. The cost accepted for the shared presentation is that Wanderer-specific controls the core model does not know about — dew mode selectors, setpoints, Calibrate — surface in core's generic *Other* group (core SDD §4.2a) rather than beside their channel.

### 2.2 Identification by Property Signature, Not Device Name (ADR-WBOX-002)

**Decision:** each profile declares a signature of `(property name, kind)` pairs and core resolves a connected device by the largest satisfied signature (`EQP-SW-080`).

**Rationale:** the Plus V3 driver's `getDefaultName()` returns `WandererBox Pro V3`, identical to the Pro V3 driver's, so a name cannot tell them apart. Properties can, but the Wanderer drivers define them only after `CONNECT`, so resolution happens on connect. Kinds are part of the signature because names alone also collide: the Plus V3 has a *switch* named `DC2` (the adjustable regulator) while the Dew Terminator has a *number* named `DC2` (a dew PWM). Signature members are restricted to properties each driver defines unconditionally when connected (never the per-channel `PWM`/`DCn` or mode setpoints, which come and go with dew mode, nor `Calibrate_DEVICE`, which depends on firmware).

---

## 3. Module / Component Design

### 3.1 `wandererbox` — Switch Profiles

- **Responsibility:** declare the three profiles and register them at load.
- **`wandererbox.profiles`** — three module-level `SwitchProfile` values, `PRO_V3`, `PLUS_V3`, `DEW_TERMINATOR`, built from the tables below. Pure data; no I/O, no INDI import. Because it is data, the test suite checks it against recorded property sets with no server.
- **`wandererbox.plugin.WandererBoxPlugin`** (`PluginBase` subclass) — `activate(ctx)` calls `ctx.register_switch_profile(p)` for each of the three (and logs a warning, rather than failing, on a Galileo whose context has no such call), and defines no `build_page()`, settings page, dock pane or session block. Per core's `PLUG-060`/`PLUG-120`, disabling or removing the plugin deregisters them.
- **Satisfies:** `WBOX-010`–`WBOX-100`.

### 3.2 Profile contents

Property names are the drivers' own (PSD Section 13). *Optional* means the driver defines the property only in some states; a missing optional property disables that control only (`EQP-SW-120`). Vendor labels are the panel text.

**Device names and signatures** (`WBOX-020`, `WBOX-090`)

| Profile | Claims device names | Signature — all must be defined after connect |
|---|---|---|
| Pro V3 | `WandererBox Pro V3` | switch `USB3.0_1`, `USB3.0_2`, `USB3.0_3`, `USB2.0_1-3`, `USB2.0_4-6`, `DC3-4`, `DC8-9`, `DC10-11`; number `DC34voltageSET`, `POWER_Monitor`, `ENV_Monitor` |
| Plus V3 | `WandererBox Pro V3` | switch `USB`, `DC2`, `DC4-6`, `DC3_DIFF`; number `DC2voltageSET`, `POWER_Monitor`, `ENV_Monitor` |
| Dew Terminator | `Wanderer Dew Terminator` | switch `DC1_DIFF`, `DC2_DIFF`, `DC3_DIFF`; number `POWER_Monitor`, `ENV_Monitor` |

No Pro V3 property set defines `USB`, `DC2` or `DC3_DIFF`; no Plus V3 set defines `USB3.0_1` or `DC1_DIFF`; the Dew Terminator defines none of the Pro or Plus switches and its `DC2` is a number. Each profile is therefore unsatisfied by the other two models' complete property sets.

**Pro V3 channels** (`WBOX-030`, `WBOX-070`)

| Group | Channel (vendor label) | Property → element | Notes |
|---|---|---|---|
| USB | USB 3.1 #1 / #2 / #3 | `USB3.0_1` / `_2` / `_3` → `INDI_ENABLED` | independent toggles |
| USB | USB 2.0 group A (ports 1–3) | `USB2.0_1-3` → `INDI_ENABLED` | one toggle for three ports |
| USB | USB 2.0 group B (ports 4–6) | `USB2.0_4-6` → `INDI_ENABLED` | |
| DC | Adjustable 5–13.2 V (2 ports) | toggle `DC3-4` → `INDI_ENABLED`; volts `DC34voltageSET` → `DC34SET` | variable channel; range from the element (5–13.2, step 0.1) |
| DC | 12 V group A (2 ports) | `DC8-9` → `INDI_ENABLED` | |
| DC | 12 V group B (2 ports) | `DC10-11` → `INDI_ENABLED` | |
| DC | 19 V mini PC | — | display-only; its current is a reading (`V19_CURRENT`), not a channel field |
| DC | 12 V normally open | — | display-only; always on |
| Dew | Dew heater 1 / 2 / 3 | `PWM`→`DC5`, `DC6`→`DC6`, `DC7`→`DC7`, native 0–255 | optional; on = duty > 0 |

**Plus V3 channels** (`WBOX-040`, `WBOX-070`)

| Group | Channel | Property → element | Notes |
|---|---|---|---|
| USB | USB (all 5 ports) | `USB` → `INDI_ENABLED` | one switch for 2× USB 3.1 and 3× USB 2.0 |
| DC | Adjustable 5–13.2 V | toggle `DC2` → `INDI_ENABLED`; volts `DC2voltageSET` → `DC2SET` | variable channel |
| DC | 12 V switched (3 ports) | `DC4-6` → `INDI_ENABLED` | |
| DC | 12 V normally open | — | display-only; always on |
| Dew | Dew heater | `PWM`→`DC3`, native 0–255 | optional; on = duty > 0 |

**Dew Terminator channels** (`WBOX-050`)

| Group | Channel | Property → element | Notes |
|---|---|---|---|
| Dew | Dew heater / switch 1 / 2 / 3 | `PWM`→`DC1`, `DC2`→`DC2`, `DC3`→`DC3`, native 0–255 | optional; on = duty > 0; usable as a plain switch (0 / 255) |

**Dew duty** (`WBOX-060`): the driver exposes no on/off property for a dew channel, so the profile marks its channels *on-via-duty*: core writes native 255 for on and 0 for off. Duty is shown 0–100 % (native ÷ 2.55, clamped, `EQP-SW-060`). The dew mode selectors (`DC5_DIFF`…, `DC3_DIFF`, `DC1_DIFF`…) and setpoints (`DCn_DIFF_SET`, `DCn_CONST_SET`) are deliberately **not** mapped; they surface in core's *Other* group with the driver's labels (ADR-WBOX-001).

**Readings** (`WBOX-080`)

| Reading (unit) | Property → element | Pro | Plus | Dew Terminator |
|---|---|---|---|---|
| Input voltage (V) | `POWER_Monitor` → `VOLTAGE` | ✓ | ✓ | ✓ |
| Total current (A) | `POWER_Monitor` → `TOTAL_CURRENT` | ✓ | ✓ | — |
| 19 V current (A) | `POWER_Monitor` → `V19_CURRENT` | ✓ | — | — |
| Adjustable regulator current (A) | `POWER_Monitor` → `AR_CURRENT` | ✓ | — | — |
| Dew probe 1 / 2 / 3 temperature (°C) | `ENV_Monitor` → `Probe1_Temp` / `Probe2_Temp` / `Probe3_Temp` | 1–3 | 1 | 1–3 |
| Ambient humidity (%) | `ENV_Monitor` → `ENV_Humidity` | ✓ | ✓ | ✓ |
| Ambient temperature (°C) | `ENV_Monitor` → `ENV_Temp` | ✓ | ✓ | ✓ |
| Dew point (°C) | `ENV_Monitor` → `DEW_Point` | ✓ | ✓ | ✓ |

Each probe reading declares −127 as "no reading". The standard weather-interface properties (`WEATHER_*`) are not mapped; the same values are already covered above.

**Unmapped and reachable via *Other*:** `Calibrate_DEVICE` (Pro, Plus), the dew mode and setpoint properties, and anything else a driver defines.

---

## 4. Data Design

| Data | Format | Storage |
|---|---|---|
| Three `SwitchProfile` values | Python module constants (`wandererbox.profiles`) | In the plugin package, loaded and registered in memory each start |
| Selected device | — | Not stored here: saved by core's per-category device configuration |

The plugin has no persistent state of its own and no database access.

---

## 5. Interface Design

- **Plugin boundary:** the plugin calls only `PluginContext.register_switch_profile`. It imports the `SwitchProfile` data types from `galileo.core.devices` and nothing from `galileo.adapters`.
- **External interfaces added:** none. All device I/O is core's shared INDI connection.
- **Prerequisite on the INDI server:** the WandererAstro driver for the model must be loaded. The Wanderer drivers accept an unrecognised model string in their handshake, so a mismatched device may look connected; core reports it as "not recognised" when no signature matches (`EQP-SW-080`).

---

## 6. Path to Traceability Matrix

A row per requirement ID in [this plugin's SRS](SRS.md), mapped to the component in Section 3 and a test case ID — see [RTM.md](RTM.md).

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SDD](../../SDD.md).*
