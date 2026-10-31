# WandererBox Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — WandererBox Plugin (switch profiles for the Wanderer Astro WandererBox Pro V3, Plus V3 and Dew Terminator) |
| **Document** | PSD (Project Scope Document), v0.3, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-30 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Downstream documents** | SRS ([SRS.md](SRS.md)), SDD ([SDD.md](SDD.md)), RTM ([RTM.md](RTM.md)) |

---

## 1. Purpose of This Document

This document defines the scope of the **WandererBox plugin** — a small first-party Galileo plugin that teaches Galileo's **core INDI Switch support** about three Wanderer Astro products whose INDI drivers do not use INDI's standard power interface: the **WandererBox Pro V3**, the **WandererBox Plus V3** and the **Wanderer Dew Terminator**. It follows the same PSD→SRS→SDD→RTM structure as [the core document chain](../../PSD.md) and the sibling [Kasa Switch](../kasa_switch/PSD.md) / [Generic Relay](../generic_relay/PSD.md) plugin chains.

**Scope history.** Earlier drafts (v0.1/v0.2) scoped this as a self-contained plugin with its own INDI client code and its own tabbed panel. Evaluation of the wider field of INDI power boxes showed that most of them (Pegasus PPBM/PPBA/UPB3, Terrans PowerBoxGo V2/PowerBoxPro V2) use INDI's standard `INDI::PowerInterface`, with identical property names, and so can be served by one generic mechanism in **Galileo core** rather than a plugin per vendor. The scope was therefore split:

| Concern | Owner | Specified in |
|---|---|---|
| Generic INDI power-device support: discovery, structured Switch model, standard-property mapping, writes, the Equipment > Switches panel, the profile registry | **Galileo core** | Core SRS `EQP-SW-020`–`EQP-SW-120`, `PLUG-210`; core SDD §4.2a |
| Mapping for the three Wanderer drivers' *non-standard* properties, supplied as declarative profiles | **This plugin** | This chain: `WBOX-*` |

This plugin has **no panel of its own, no protocol code and no INDI connection**: it contributes data (profiles) that core's mapping engine applies. A Wanderer device then appears on the core Equipment > Switches page exactly like a Pegasus or Terrans one.

This document intentionally stays above implementation detail. The driver facts gathered so far are summarised in Section 13 as scope evidence.

## 2. Background and Motivation

Galileo's core SRS reserves `EQP-SW-010` (enumerate switch/relay devices and their read/write state). Today the core INDI Switch adapter is a stub: it never populates its switch list, and the Equipment > Switches page is populated only by plugin panels. The Aux category can display any driver's properties, but as a flat, driver-shaped dump that does not present port groups and does not distinguish a switchable port from a read-out.

The three Wanderer drivers are AUX + WEATHER drivers with vendor-specific properties (for example `USB3.0_1`, `DC3-4`, `DC34voltageSET`, `DC5_DIFF`). Core cannot map them generically, which is why this plugin exists. Each product's INDI driver owns the serial link to the device; Galileo reaches it through its native INDI client (`galileo.adapters.indi_client`), shared with every other INDI device.

### 2.1 Model support

| Model | Vendor page | INDI driver | Supported by this plugin |
|---|---|---|---|
| WandererBox Pro V3 (WBX3-Pro) | [h-col-135](https://www.wandererastro.com/h-col-135.html) | `wandererbox_pro_v3` | **Yes** |
| WandererBox Plus V3 (WBX3-Plus) | [h-col-134](https://www.wandererastro.com/h-col-134.html) | `wandererbox_plus_v3` | **Yes** |
| Wanderer Dew Terminator (WDT) | [h-col-152](https://www.wandererastro.com/h-col-152.html) | `wanderer_dew_terminator` | **Yes** |
| WandererBox Lite V3 | [h-col-133](https://www.wandererastro.com/h-col-133.html) | none | **No** — no control interface |

### 2.2 Why the Lite V3 is not supported

The vendor states that the WandererBox Lite V3 "does not provide any control functions". It is a passive power and USB hub with power LEDs only: no serial or software interface, no switching, no sensors, and no INDI driver. There is nothing for Galileo to connect to.

### 2.3 Hardware summary

| Capability | Pro V3 | Plus V3 | Dew Terminator |
|---|---|---|---|
| USB ports | 3× USB 3.1 (each switchable) + 6× USB 2.0 in two groups of three (each group switchable); 5 V 6 A shared | 2× USB 3.1 + 3× USB 2.0, **all switched together as one**; 5 V 5 A shared | none |
| 19 V DC (mini PC) | 1 port, 6 A, not switchable | none | none |
| Adjustable 5–13.2 V DC | 2 ports sharing 5 A; switchable, voltage settable | 1 port, 5 A; switchable, voltage settable | none |
| 12 V switched DC | 4 ports in two groups of two (8 A per group) | 3 ports on one switch (8 A combined) | none |
| 12 V normally-open DC | 1 port, 10 A, not switchable | 1 port, 10 A, not switchable | none |
| Dew heater / PWM channels | 3 | 1 | 3 (each can also act as a plain DC switch) |
| Temperature probes | 3 | 1 | 3 |
| Ambient temperature/humidity (DHT22) and dew point | yes | yes | yes |
| Input voltage | yes | yes | yes |
| Current monitoring | total, 19 V, adjustable regulator | total only | none |

## 3. Vision Statement

> A Galileo user with a WandererBox Pro V3, Plus V3 or Dew Terminator picks it on the Equipment > Switches page like any other power box, and gets the same grouped, labelled, toggleable view — USB and DC ports, dew heaters, regulator voltage, voltage/current/temperature read-outs, with the Wanderer-specific knowledge delivered as a small, removable plugin.

## 4. Goals and Objectives

| # | Goal |
|---|---|
| G1 | Deliver the Wanderer mappings as the `WBOX` plugin — a first-party plugin distributed as a downloadable ZIP from the Galileo Plugins repository (`PLUG-090`/`PLUG-110`), independently enabled/disabled once installed (core `PLUG-060`). Not bundled in the Galileo installer |
| G2 | Register three **switch profiles** (Pro V3, Plus V3, Dew Terminator) through core's profile registry (`PLUG-210`, `EQP-SW-080`), each mapping that driver's custom properties onto core's structured Switch model |
| G3 | Identify which Wanderer model a connected INDI device is by its **property signature**, not its INDI device name — the Plus V3 driver reports the same default name as the Pro V3 driver |
| G4 | Make every **switchable** output of each model available as a toggle (USB 3.1 ports, USB 2.0 groups, adjustable-voltage ports, 12 V groups, dew heater channels), and show non-switchable outputs (19 V, normally-open 12 V) as display-only |
| G5 | Expose each model's dew heater duty (normalised to 0–100 %), regulator voltage, and sensor readings (input voltage, currents, temperatures, humidity, dew point) through the core model |
| G6 | Supply vendor-accurate port names (e.g. "USB 3.1 #2", "12 V group A") rather than the driver's internal numbering |
| G7 | Carry no code that talks to a device: profiles are data, so the plugin cannot break the core INDI connection and adding a future Wanderer model is a new profile |

## 5. Non-Goals (Explicitly Out of Scope)

- **No panel, settings page, protocol client or INDI connection in this plugin.** Core owns the panel, the INDI connection and the selection flow. This plugin contributes data only.
- **No generic power-box support here.** Pegasus, Terrans and any other INDI power-interface device are served by core (`EQP-SW-020`–`EQP-SW-120`) with no plugin. Nothing about those devices is specified in this chain.
- **No WandererBox Lite V3 support.** It has no control interface (Section 2.2).
- **No other Wanderer Astro products in v1.** WandererCover, WandererRotator, WandererEclipse, WandererETA and older V2 boxes are separate device categories or generations; none are specified or tested.
- **No firmware update, calibration workflow or driver installation.** The drivers' optional "Calibrate Current" and the dew mode/setpoint properties are reachable through core's "Other" group (`EQP-SW-070`) with the driver's own labels; this plugin adds no dedicated UI for them.
- **No automatic dew-heater control logic in Galileo.** The Manual / DPD (dew-point difference) / CT (constant temperature) modes are implemented by each INDI driver's own 2.5 s poll loop; they work only while the INDI server and driver are running.
- **No two boxes of different Wanderer models on one INDI server in v1.** Because of the shared default name, they are not guaranteed to be distinguishable before connecting.

## 6. Dependencies on Galileo Core

This plugin depends on **new** core requirements as well as existing ones. The new ones (marked ★) were added to core together with this plugin and are what it depends on; a Galileo without them cannot use it (the plugin then logs a warning instead of failing).

| Core capability | Core requirement | How this plugin uses it |
|---|---|---|
| Plugin loading, manifest/version check, fault isolation | `PLUG-010`–`PLUG-050` | Discovered/loaded/isolated like any plugin |
| Installable-plugin enable/disable, inert when disabled | `PLUG-060` | Independently toggleable; profiles are not offered when disabled |
| Plugin removal | `PLUG-120` | Profiles deregistered on removal |
| Plugin profile registration ★ | `PLUG-210` | The plugin registers three profiles through `PluginContext` |
| Switch profile model and signature matching ★ | `EQP-SW-080` | Defines what a profile contains and how a connected device is matched to one |
| Structured Switch model, INDI mapping, writes ★ | `EQP-SW-030`–`EQP-SW-060` | Applies each profile; dew duty normalised to 0–100 % |
| "Other" group for unmapped properties ★ | `EQP-SW-070` | Dew modes, setpoints and Calibrate reach the user without plugin UI |
| Switches panel ★ | `EQP-SW-090` | Renders Wanderer devices exactly like any other power box |
| Flat switch contract ★ | `EQP-SW-100` | Wanderer toggle outputs are addressable by stable id through `list_switches`/`set_switch`, like any other Switch device |
| Switch discovery ★ | `EQP-SW-020` | Lists a device claimed by a profile even though its driver lacks the power interface |
| Native INDI client | `ARCH-020` family / SDD §2.3 | All property reads and writes, via the shared per-server connection |
| Configuration in the database | CLAUDE.md firm rule | This plugin stores **no configuration**; the chosen device is saved by core's normal per-category device configuration |

## 7. Functional Requirement Domains (Scope-Level)

| ID Prefix | Domain | Scope Description | Priority |
|---|---|---|---|
| `WBOX` | Wanderer Switch Profiles | The three profiles' signatures and channel/sensor maps, display-only ports, vendor labels, dew-duty scaling, signature distinctness, and inertness when disabled | MVP |

## 8. Stakeholders and Primary Persona

| Persona | Description | Primary Interests |
|---|---|---|
| Observatory / Field Operator | Runs a WandererBox Pro V3 or Plus V3 as central power distribution, or a Dew Terminator for heaters, with an INDI server (e.g. StellarMate or a Raspberry Pi) attached | Remote power-cycling of a hung camera or mount, seeing supply voltage/current, and setting dew heaters, in the same screen as any other power box |

## 9. Assumptions and Constraints

- **PC1** — The device is attached to a host running an INDI server with the matching WandererAstro driver loaded, and that server is reachable from the Galileo host over the LAN.
- **PC2** — Each driver reports its own output state, so the panel shows polled hardware state, not merely the last commanded value.
- **PC3** — The Wanderer drivers define most properties only **after connect** (and delete them on disconnect), so a model cannot be identified from its properties before connecting; identification happens on connect (`EQP-SW-080`).
- **PC4** — Switching a USB port or group that carries the device used to reach the INDI server can cut the session off. The Plus V3's USB ports switch only all together; the Pro V3's USB 2.0 ports only in two groups of three.
- **PC5** — The plugin ships as its own package in the Galileo Plugins repository (working name `wandererbox`) with its own `plugin.toml`, `pyproject.toml` and `build_zip.py`, matching the sibling plugins.

## 10. Risks

| # | Risk | Impact | Notes |
|---|---|---|---|
| R1 | Driver property sets were read from source (Section 13), not checked against running drivers or real boxes. Driver port numbering (e.g. Pro `DC3-4`, `DC8-9`; Plus `DC2`, `DC4-6`) differs from the vendor pages' grouping, and the sources have quirks | Low | Confirm property names and the DC-number-to-physical-port mapping with `indi_getprop` against real hardware; profile labels follow the vendor's names |
| R2 | Driver support varies by INDI version, and the source read is the author's fork of INDI | Low | Profiles mark every property optional where the driver defines it dynamically (`Calibrate_DEVICE`; per-channel PWM/mode/setpoint); a missing property removes that control only (`EQP-SW-120`) |
| R3 | No physical devices on hand for hardware-marked tests | Medium | Profiles are data, tested against recorded property sets in the repo's INDI mock fixtures; `hardware`-marked tests reserved |
| R4 | The Plus V3 driver's default INDI device name is `WandererBox Pro V3`, identical to the Pro V3 driver's | Medium | Matching is by signature of (property name, kind) pairs, never name alone (`EQP-SW-080`, `WBOX-020`); signatures are distinct, including against the Dew Terminator, whose `DC2` is a *number* where the Plus V3's `DC2` is a *switch* (`WBOX-090`) |
| R5 | A Wanderer handshake accepts an unrecognised model string and still reports connected | Low | Core reports "not recognised" when no signature matches (`EQP-SW-080`) |
| R6 | A missing temperature probe reads −127 °C, outside the properties' declared range | Low | Profile declares −127 as "no reading" and the panel shows it as unavailable (`WBOX-080`) |
| R7 | The plugin depends on core work (`EQP-SW-020`–`140`, `PLUG-210`) that is larger than the plugin itself | Low | Delivered in core alongside this plugin (core CHANGELOG, "Power boxes and relay boards now work on the Equipment > Switches page"). A Galileo without it logs a warning and the Wanderer devices remain reachable through the Aux page |

## 11. References

- Vendor product pages: [Pro V3](https://www.wandererastro.com/h-col-135.html), [Plus V3](https://www.wandererastro.com/h-col-134.html), [Dew Terminator](https://www.wandererastro.com/h-col-152.html), [Lite V3](https://www.wandererastro.com/h-col-133.html) (no control interface)
- INDI driver source (author's fork of indilib/indi), `drivers/auxiliary/`: [wandererbox_pro_v3.cpp](https://github.com/gordtulloch/indi/blob/master/drivers/auxiliary/wandererbox_pro_v3.cpp), [wandererbox_plus_v3.cpp](https://github.com/gordtulloch/indi/blob/master/drivers/auxiliary/wandererbox_plus_v3.cpp), [wanderer_dew_terminator.cpp](https://github.com/gordtulloch/indi/blob/master/drivers/auxiliary/wanderer_dew_terminator.cpp)
- INDI power interface (the standard the generic core support targets): [indipowerinterface.h](https://github.com/indilib/indi/blob/master/libs/indibase/indipowerinterface.h), [indipowerinterface.cpp](https://github.com/indilib/indi/blob/master/libs/indibase/indipowerinterface.cpp)
- [Galileo Core PSD](../../PSD.md), [Core SRS](../../SRS.md) `EQP-SW-*`, [Core SDD](../../SDD.md) §4.2a
- [Kasa Switch plugin PSD](../kasa_switch/PSD.md) — structural template for a switch plugin chain
- [Galileo Plugins repository](https://github.com/gordtulloch/Galileo-Plugins) — where this plugin's source and distribution will live

## 12. Glossary

Terms not already defined in [Galileo core PSD's Glossary](../../PSD.md#15-glossary) apply unchanged; the following are specific to this plugin:

| Term | Definition |
|---|---|
| Switch profile | Declarative data mapping one INDI driver's custom properties onto core's structured Switch model (`EQP-SW-080`) |
| Property signature | The set of (INDI property name, property kind) pairs that must all be defined on a connected device for a profile to apply |
| Power interface | INDI's standard `INDI::PowerInterface`, with fixed property names, served by core without a profile |
| WandererBox Pro V3 / Plus V3 | Wanderer Astro's power boxes (SKU WBX3-Pro / WBX3-Plus): switched USB and DC outputs, PWM dew heater channels, environmental sensors |
| Wanderer Dew Terminator | Wanderer Astro's three-channel dew heater controller (SKU WDT) |
| WandererBox Lite V3 | The passive, control-less hub in the same family; not supported (Section 2.2) |
| Dew heater channel | A PWM output drivable manually by duty or by the driver's CT / DPD modes |
| Display-only channel | A port shown in the panel but with no switch (the 19 V and normally-open 12 V ports) |

## 13. INDI Driver Facts Established So Far

From the three driver sources. Scope-level evidence only; the SRS turns it into requirements. All three poll every 2.5 s over serial at 19200 baud and define the dew mode/setpoint/PWM properties dynamically.

**Pro V3** (`wandererbox_pro_v3.cpp`, v1.1; device name `WandererBox Pro V3`; AUX + WEATHER; handshake model `ZXWBProV3`)
- Switches (`INDI_ENABLED`/`INDI_DISABLED`): `USB3.0_1`, `USB3.0_2`, `USB3.0_3`, `USB2.0_1-3`, `USB2.0_4-6`, `DC3-4` (adjustable pair), `DC8-9`, `DC10-11` (12 V groups).
- Numbers: `DC34voltageSET` (5–13.2 V, step 0.1); dew PWM `PWM` (DC5), `DC6`, `DC7` (0–255, step 5).
- Dew modes `DC5_DIFF`, `DC6_DIFF`, `DC7_DIFF` (Manual / DPD Mode / CT Mode); setpoints `DCn_DIFF_SET`, `DCn_CONST_SET`.
- Read-only: `POWER_Monitor` (`VOLTAGE`, `TOTAL_CURRENT`, `V19_CURRENT`, `AR_CURRENT`), `ENV_Monitor` (`Probe1_Temp`–`Probe3_Temp`, `ENV_Humidity`, `ENV_Temp`, `DEW_Point`), weather parameters.
- Optional: `Calibrate_DEVICE` (firmware ≥ 20240216).

**Plus V3** (`wandererbox_plus_v3.cpp`; device name **`WandererBox Pro V3`** (R4); AUX + WEATHER; handshake model `ZXWBPlusV3`)
- Switches: `USB` (all USB ports together), `DC2` (adjustable regulator), `DC4-6` (the three 12 V switched ports).
- Numbers: `DC2voltageSET` (5–13.2 V); dew PWM `PWM` (DC3, 0–255).
- Dew mode `DC3_DIFF` with `DC3_DIFF_SET` and `DC3_CONST_SET`.
- Read-only: `POWER_Monitor` (`VOLTAGE`, `TOTAL_CURRENT`), `ENV_Monitor` (`Probe1_Temp`, `ENV_Humidity`, `ENV_Temp`, `DEW_Point`), weather parameters.
- Optional: `Calibrate_DEVICE`.

**Dew Terminator** (`wanderer_dew_terminator.cpp`, v1.0; device name `Wanderer Dew Terminator`; AUX only; handshake model `ZXWBDewTerminator`)
- No switches other than dew mode; no regulator; no USB.
- Dew PWM `PWM` (DC1), `DC2`, `DC3` (**numbers**, 0–255); modes `DC1_DIFF`, `DC2_DIFF`, `DC3_DIFF`; setpoints `DCn_DIFF_SET`, `DCn_CONST_SET`.
- Read-only: `POWER_Monitor` (`VOLTAGE` only), `ENV_Monitor` (three probes, humidity, ambient temperature, dew point). No weather interface, no `Calibrate_DEVICE`.
- A channel used as a plain switch is PWM 0 / 255; there is no separate switch property.

**Across models:** the 19 V and normally-open 12 V ports have no property at all, which matches the hardware — they exist only as profile-declared display-only channels.

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's PSD](../../PSD.md).*
