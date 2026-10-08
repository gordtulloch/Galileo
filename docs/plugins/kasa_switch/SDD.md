# Kasa Switch Plugin — SDD (Software Design Description)

| | |
|---|---|
| **Project** | Galileo — Kasa Switch Plugin |
| **Document** | SDD (Software Design Description), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-05 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md) |
| **Downstream document** | RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SDD](../../SDD.md) |

---

## 1. Introduction

### 1.1 Purpose

This SDD describes how this plugin's module satisfies the requirements enumerated in [its SRS](SRS.md), and how it attaches to [Galileo core's architecture](../../SDD.md) exclusively through the plugin extension points core `galileo.plugins` (core SDD Section 4.20) already exposes.

### 1.2 Scope

Covers this plugin's single module (`kasa_switch`), its own ADR (protocol/dependency decisions specific to this plugin), and its data design. It does not restate core architecture — that is [core SDD Sections 2–3](../../SDD.md), unchanged and inherited as-is.

### 1.3 References

- [This plugin's PSD](PSD.md), [SRS](SRS.md)
- [Galileo Core SDD](../../SDD.md), particularly Section 2.2 (the ports-and-adapters/plugin boundary this plugin is built against), Section 4.2 (`galileo.adapters.indi`/`.alpaca`, whose `_SwitchBackend` protocol this plugin's adapter also satisfies), Section 4.20 (`galileo.plugins`), and Section 6.3 (Plugin API Surface)

---

## 2. Design Considerations

### 2.1 Local-Protocol Reimplementation, Not a `python-kasa` Dependency (ADR-KASA-001)

**Decision:** `kasa_switch.protocol` reimplements TP-Link's local-network wire format (a length-prefixed, one-byte-feedback XOR "cipher" keyed on 171, over TCP port 9999) directly against the Python standard library (`socket`, `struct`, `json`), following the format documented by [Python-KasaSmartPowerStrip](https://github.com/p-doyle/Python-KasaSmartPowerStrip), rather than adding a dependency on the third-party `python-kasa` PyPI package.

**Rationale:** two independent reasons, either alone sufficient. First, dependency footprint — this plugin's `pyproject.toml` declares only `galileo`, nothing else, since the "cipher" is simple XOR rather than real cryptography and needs no library. Second, and more importantly, naming — `python-kasa` is itself distributed under the top-level module name `kasa`, which is also commonly pre-installed for Home Assistant's Kasa integration. A plugin named `kasa` would either collide with an already-installed `python-kasa` or be shadowed by it depending on import order, either way breaking unpredictably. This plugin's package is named `kasa_switch` specifically to make that collision structurally impossible, independent of whatever else happens to be on the user's Python path.

**Physical location:** `kasa_switch.*` — a standalone top-level package (not nested under `galileo.plugins`, unlike VSTarget's historical pre-loaded layout), matching the Galileo Plugins repository's one-top-level-package-per-plugin convention ([`Galileo-Plugins/README.md`](https://github.com/gordtulloch/Galileo-Plugins/blob/main/README.md)). The `plugin.toml` manifest declares `entry_point = "kasa_switch"`, `api_min = "1"`, `api_max = "1"`, and `tier = "first_party"`.

### 2.2 No Device Discovery

Unlike core's Alpaca UDP discovery (`ARCH-050`), this plugin has no LAN broadcast-discovery step — a device is added by typing its IP/hostname (PSD Section 5, non-goal). TP-Link's own discovery broadcast is part of the cloud-linked mobile-app flow this plugin deliberately avoids (PSD Section 5); a user already knows their device's IP from their router or the Kasa app's own device list.

---

## 3. Module / Component Design

### 3.1 `kasa_switch` — Kasa Smart Plug / Power Strip Control

- **Responsibility:** Local-network protocol client, Switch device backend, and the tabbed device panel.
- **`kasa_switch.protocol`** — `encrypt`/`decrypt` (the XOR framing) and `send_command(host, command, port=9999)`, which opens a fresh TCP connection per call (ARCH-060-style fault isolation: a device that drops off the network fails this one call with a clear exception rather than leaving a stale connection for the next command to trip over) and returns the parsed JSON response.
- **`kasa_switch.adapter.KasaSwitchAdapter`** (`galileo.core.devices.DeviceBackend` subclass) — satisfies `EQP-SW-010`/the `_SwitchBackend` protocol core's `SwitchController` already drives. `connect()` queries `system.get_sysinfo`; if the response has a `children` list (a power strip), one `KasaOutlet` is built per child, named from its own `alias` and carrying its `id` for scoped commands; otherwise (a single plug) one `KasaOutlet` is built from the device's own `alias`/`relay_state`. `set_switch(name, value)` looks up the outlet by name and sends `system.set_relay_state`, scoped to the outlet's `child_id` via a `context.child_ids` envelope when present — satisfies `KASA-010`–`KASA-040`.
- **`kasa_switch.settings.KasaSettings`** — `QSettings`-backed, JSON-encoded list of `{"host", "label"}` entries under the `Galileo` organisation (the same pattern `vstarget.settings` uses), since the panel hosts any number of devices rather than one.
- **`kasa_switch.ui.build_kasa_page`** — one `_DeviceTab` per configured device inside a `QTabWidget` with `tabsClosable(True)`; a "+" corner widget opens `AddKasaDeviceDialog` (host/IP + optional label) and persists the new entry via `KasaSettings.add_device`; closing a tab calls `KasaSettings.remove_device` and stops that tab's poll timer without touching any other tab. Each tab polls its own adapter every 5 seconds (`QTimer`) and renders a table of switch name + a checkable toggle button showing On/Off — satisfies `KASA-050`.
- **Satisfies:** `KASA-010`–`KASA-050`.

---

## 4. Data Design

| Data | Format | Storage |
|---|---|---|
| Configured device list (host, label) | `QSettings`, JSON-encoded list value | Platform-native settings store under the `Galileo` organisation / `KasaSwitch` application, the same mechanism `vstarget.settings` uses |

This plugin adds no database of its own — switch state itself is not persisted at all (it is polled live from the device on each refresh), and the device list is the only configuration that needs to survive a restart.

---

## 5. Interface Design

- **Plugin boundary:** this plugin depends only on core's device port interfaces (`galileo.core.devices.DeviceBackend`/`DeviceCategory.SWITCH`) and the `PluginContext.register_device_backend` call it is given at load time — identical to core SDD Section 6.3's Plugin API Surface description.
- **External interface this plugin adds:** a direct TCP/9999 connection to each configured Kasa device on the LAN (`kasa_switch.protocol`). This is a device-port-level interface (the same category of thing core's own `galileo.adapters.indi`/`.alpaca` are to their devices), not a third-party web API, so it is not an `EXT`-domain requirement.

---

## 6. Path to Traceability Matrix

A row per requirement ID in [this plugin's SRS](SRS.md), mapped to the module in Section 3 above and a test case ID — see [RTM.md](RTM.md).

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SDD](../../SDD.md).*
