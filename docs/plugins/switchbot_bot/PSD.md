# SwitchBot Bot Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — SwitchBot Bot Plugin (Bluetooth LE power control, e.g. for a Seestar) |
| **Document** | PSD, v0.1, draft |
| **Date** | 2026-10-22 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Downstream documents** | [SRS](SRS.md), [SDD](SDD.md), [RTM](RTM.md) |

---

## 1. Purpose

This is the scope of the **SwitchBot Bot plugin**, a first-party Galileo plugin that drives [SwitchBot Bot](https://www.switch-bot.com/) devices over Bluetooth Low Energy as Galileo Switch devices. Its main use is a Bot fixed over the power button of a ZWO Seestar, so Galileo (and a session) can power the telescope on and off. It follows the same PSD→SRS→SDD→RTM structure as the [Kasa Switch](../kasa_switch/PSD.md) and [Generic Relay](../generic_relay/PSD.md) chains.

## 2. Background

A Seestar has no network power control and speaks neither INDI nor Alpaca while it is off. A SwitchBot Bot is a small battery-powered arm that presses a button; it is controlled over BLE, with no hub or cloud account needed for direct BLE control. Core `EQP-SW-010` covers Switch devices generally; this plugin supplies the backend for this one class of hardware.

The BLE command set is documented by [switchbotpy](https://github.com/RoButton/switchbotpy) (MIT). That library is not used directly (Section 9, PC2).

## 3. Goals

| # | Goal |
|---|---|
| G1 | Deliver Bot control as the `SBOT` plugin, a first-party ZIP installed from the Marketplace or from file (`PLUG-090`/`PLUG-110`), independently enable/disable-able (`PLUG-060`) |
| G2 | Register a Switch device backend (`ARCH-070`/`PLUG-010`, satisfying `EQP-SW-010`) that speaks the Bot's BLE protocol directly on Windows, macOS and Linux |
| G3 | Present a panel on Equipment > Switches (`PLUG-070`) to scan for Bots, add one by address, and press/switch it |
| G4 | Support Bots in both dual-state (On/Off) and press mode, and Bots with a password |

## 4. Non-Goals

- No SwitchBot cloud/hub/account integration; direct BLE only, so the host needs a Bluetooth adapter within range of the Bot.
- No other SwitchBot devices (curtains, plugs, locks), and no Bot timers, hold-time or mode configuration — use the SwitchBot app for those.
- No background polling: each contact wakes the Bot and drains its battery.
- No true state read-back: a Bot cannot report which way it last moved.

## 5. Dependencies on Galileo Core

| Core capability | Requirement | Use |
|---|---|---|
| Plugin loading, isolation, enable/disable | `PLUG-010`–`PLUG-060` | As any plugin |
| Panel placement | `PLUG-070` | `equipment:switch` |
| Device backend registration | `ARCH-070`/`PLUG-010` | `SwitchBotAdapter` for `DeviceCategory.SWITCH` |
| Switch port semantics | `EQP-SW-010` | Boolean switch, one per Bot |
| Per-device fault isolation | `ARCH-060` | One unreachable Bot only affects its own box |

## 6. Requirement Domain

| Prefix | Domain | Priority |
|---|---|---|
| `SBOT` | SwitchBot Bot BLE control: protocol, switch enumeration/toggle, error handling, panel | MVP |

## 7. Persona

Observatory operator with a Seestar (or any button-operated device) who wants Galileo to power it on and off remotely.

## 8. Risks

| Risk | Impact | Notes |
|---|---|---|
| Bot asleep or out of range, so a command fails | Medium | Reported in the Bot's status line; retry. Each command uses a fresh connection |
| Last-command state drifts from reality (button pressed by hand, app used) | Low | Shown as "last command"; **Press** works regardless |
| BLE stack differences (Windows/macOS/Linux) | Medium | `bleak` abstracts them; macOS identifies devices by UUID rather than MAC |
| Stored Bot password is plaintext in `QSettings` | Low | The Bot password only deters casual BLE control; documented in the plugin help |

## 9. Assumptions and Constraints

- **PC1** — The Bot is within Bluetooth range of the Galileo host.
- **PC2** — `switchbotpy` is not a dependency: it runs on `pygatt`/`pexpect` over BlueZ `gatttool` (Linux only) and targets Python 3.6–3.8, whereas Galileo supports Windows/macOS/Linux on Python ≥ 3.11. The protocol is re-implemented on `bleak` (ADR-SBOT-001).
- **PC3** — `bleak` must be installed in Galileo's Python environment (plugin ZIPs do not install pip dependencies); the plugin loads without it and reports what is missing.

## 10. References

- switchbotpy (protocol reference, MIT): https://github.com/RoButton/switchbotpy
- [Kasa Switch PSD](../kasa_switch/PSD.md) — the sibling plugin this one mirrors
- [Galileo Plugins repository](https://github.com/gordtulloch/Galileo-Plugins)
