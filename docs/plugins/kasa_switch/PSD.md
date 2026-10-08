# Kasa Switch Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — Kasa Switch Plugin (TP-Link Kasa smart plug / power strip control) |
| **Document** | PSD (Project Scope Document), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-05 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Downstream documents** | SRS ([SRS.md](SRS.md)), SDD ([SDD.md](SDD.md)), RTM ([RTM.md](RTM.md)) |

---

## 1. Purpose of This Document

This document defines the scope of the **Kasa Switch plugin** — a first-party Galileo plugin that controls TP-Link Kasa smart plugs and power strips (single-outlet devices like the HS100/HS103/HS105, and multi-outlet strips like the HS300/KP303/EP40) as Galileo Switch devices. It follows the same PSD→SRS→SDD→RTM structure as [the core document chain](../../PSD.md) and [the VSTarget plugin's chain](../vstarget/PSD.md), the reference example for how a plugin's own requirements/design are specified in `docs/plugins/<plugin-name>/` rather than embedded in core.

This document intentionally stays above implementation detail — no protocol byte layouts or class designs. Those belong in [SDD.md](SDD.md).

## 2. Background and Motivation

Galileo's core SRS reserves `EQP-SW-010` (enumerate switch/relay devices and their read/write state) at P2, satisfied in core by the generic INDI/Alpaca Switch adapters behind the Equipment > Switches screen. That screen is intentionally left unpopulated for now — a TP-Link Kasa device speaks neither INDI nor Alpaca, and most observatory power-control setups (see the companion write-up at [openastronomy.substack.com — "In the Observatory: Power Control"](https://openastronomy.substack.com/p/in-the-observatory-power-control)) are better served by a focused panel for the specific hardware in hand than by a protocol-agnostic generic screen. This plugin is that focused panel for Kasa devices specifically, registering a Switch device backend through the plugin framework (core `PLUG` domain) exactly as any other plugin would.

The wire protocol itself — TP-Link's local-network "autokey XOR" framing over TCP port 9999 — is well documented by the open-source community; this plugin's implementation follows the format documented by [Python-KasaSmartPowerStrip](https://github.com/p-doyle/Python-KasaSmartPowerStrip) rather than depending on the third-party `python-kasa` package (Section 10, PC2).

## 3. Vision Statement

> The Kasa Switch plugin lets a Galileo user with TP-Link Kasa smart plugs or power strips in their observatory control and monitor them — camera power, mount power, dew heaters, anything wired through a Kasa outlet — directly from Galileo, without a separate app and without any cloud account, delivered as an ordinary plugin against Galileo's own plugin architecture.

## 4. Goals and Objectives

| # | Goal |
|---|---|
| G1 | Deliver Kasa device control as the `KASA` plugin — a first-party plugin distributed as a downloadable ZIP from the Galileo Plugins repository (`PLUG-090`/`PLUG-110`), independently enabled/disabled once installed (core `PLUG-060`). The plugin is **not** bundled in the Galileo installer; users install it from the in-app Plugin Marketplace or by selecting the downloaded ZIP via Install from file |
| G2 | Register a Switch device backend (core `ARCH-070`/`PLUG-010`, satisfying `EQP-SW-010`) that speaks TP-Link Kasa's local-network protocol directly — no cloud account, no internet dependency, no third-party `python-kasa` package |
| G3 | Present a panel (core `PLUG-070`, secondary nav level) where any number of Kasa devices can be added side by side, each as its own tab, with a table of that device's switches (identifier + On/Off status) that toggles on click |
| G4 | Support both a single-outlet plug and a multi-outlet power strip through the same device backend, enumerating one switch per outlet on a strip |

## 5. Non-Goals (Explicitly Out of Scope)

- **No TP-Link cloud/account integration.** Only the local-network protocol is used; a device is addressed by its LAN IP/hostname, never through TP-Link's cloud API.
- **No dimmer/analog brightness control.** Kasa dimmer switches exist, but every outlet this plugin controls is treated as a boolean on/off switch — matching the hardware the plugin was built for (plugs and power strips), not the full Kasa product line.
- **No changes to the Equipment > Switches screen or its generic INDI/Alpaca Switch adapters.** This plugin is a separate, self-contained path to Switch control for this one vendor's hardware, not a replacement for or an extension of that screen.
- **No device discovery/auto-scan.** A device is added by typing its IP/hostname; there is no LAN broadcast-discovery step (unlike core's Alpaca UDP discovery, `ARCH-050`) in v1.

## 6. Dependencies on Galileo Core

This plugin is a client of the following core capabilities — each is an existing, unchanged core requirement this plugin's own requirements (Section 7) trace to, not something this document specifies:

| Core capability | Core requirement | How this plugin uses it |
|---|---|---|
| Plugin loading, manifest/version check, fault isolation | `PLUG-010`–`PLUG-050` | Discovered/loaded/isolated the same as any plugin |
| Installable-plugin enable/disable | `PLUG-060` | Independently toggleable once installed |
| Secondary-level UI panel insertion | `PLUG-070` | The Kasa Switches panel is a secondary panel, not a peer to a built-in primary section |
| Device backend registration | `ARCH-070`/`PLUG-010` | `KasaSwitchAdapter` is registered for `DeviceCategory.SWITCH` via `PluginContext.register_device_backend` |
| Switch device port semantics | `EQP-SW-010` | This plugin's backend satisfies the same read/write switch-state contract the generic INDI/Alpaca Switch adapters do — boolean switches only (no analog outlets) |

## 7. Functional Requirement Domains (Scope-Level)

| ID Prefix | Domain | Scope Description | Priority |
|---|---|---|---|
| `KASA` | Kasa Smart Plug / Power Strip Control | Local-network TP-Link Kasa protocol client, single-plug and power-strip switch enumeration, toggle, error handling, and the tabbed add/remove panel UI | MVP |

## 8. Stakeholders and Primary Persona

| Persona | Description | Primary Interests |
|---|---|---|
| Observatory Operator | Has one or more TP-Link Kasa plugs/power strips controlling observatory equipment power (camera, mount, dew heaters) | Reliable local on/off control from within Galileo, without a separate app or cloud dependency |

## 9. Assumptions and Constraints

- **PC1** — Kasa devices are reachable on the same LAN as the Galileo host; the plugin does not attempt to traverse NAT or reach a device remotely.
- **PC2** — The local-network protocol is reimplemented directly against the standard library (`socket`, `json`) rather than depending on the third-party `python-kasa` PyPI package, both to keep this plugin's dependency footprint to just `galileo` and to avoid a module-name collision — `python-kasa` also claims the top-level `kasa` module name, which is why this plugin's package is named `kasa_switch`.
- **PC3** — Most boards/outlets this plugin targets report their own relay state on query (`system.get_sysinfo`), unlike the Generic Internet Relay plugin's boards — so the panel's displayed status is a true poll of hardware state, not merely the last commanded value.

## 10. Risks

| Risk | Impact | Notes |
|---|---|---|
| TP-Link could change the local-network protocol in a firmware update | Low | The protocol has been stable and community-documented for years across many Kasa product generations; no cloud dependency means no server-side API to deprecate either |
| A device dropping off the LAN mid-poll | Low | Each tab fails independently (its own adapter, its own try/except around the poll) — one unreachable device does not affect the others, matching core's per-device fault-isolation principle (`ARCH-060`) |

## 11. References

- Python-KasaSmartPowerStrip (protocol reference): https://github.com/p-doyle/Python-KasaSmartPowerStrip
- "In the Observatory: Power Control": https://openastronomy.substack.com/p/in-the-observatory-power-control
- [Galileo Core PSD](../../PSD.md) — the parent scope document this plugin depends on, particularly Section 8's `PLUG` domain
- [Galileo Plugins repository](https://github.com/gordtulloch/Galileo-Plugins) — this plugin's source and distribution

## 12. Glossary

Terms not already defined in [Galileo core PSD's Glossary](../../PSD.md#15-glossary) apply unchanged; the following are specific to this plugin:

| Term | Definition |
|---|---|
| Kasa | TP-Link's smart-home product line (plugs, power strips, bulbs, switches) this plugin controls |
| Outlet / child | One controllable socket on a multi-outlet power strip (e.g. HS300); reported in `system.get_sysinfo`'s `children` list, each with its own alias and relay state |

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's PSD](../../PSD.md).*
