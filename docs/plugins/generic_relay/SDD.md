# Generic Relay Plugin — SDD (Software Design Description)

| | |
|---|---|
| **Project** | Galileo — Generic Relay Plugin |
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

Covers this plugin's single module (`generic_relay`), its own ADR (the URL-template design decision specific to this plugin), and its data design. It does not restate core architecture — that is [core SDD Sections 2–3](../../SDD.md), unchanged and inherited as-is.

### 1.3 References

- [This plugin's PSD](PSD.md), [SRS](SRS.md)
- [Galileo Core SDD](../../SDD.md), particularly Section 2.2 (the ports-and-adapters/plugin boundary this plugin is built against), Section 4.2 (`galileo.adapters.indi`/`.alpaca`, whose `_SwitchBackend` protocol this plugin's adapter also satisfies), Section 4.20 (`galileo.plugins`), and Section 6.3 (Plugin API Surface)
- [The Kasa Switch plugin's SDD](../kasa_switch/SDD.md) — a sibling Switch-backend plugin with a very similar panel shape, included here only as a design cross-reference, not a code dependency (the two plugins do not import each other)

---

## 2. Design Considerations

### 2.1 Configurable URL Template Instead of a Fixed API (ADR-RELAY-001)

**Decision:** `GenericRelayAdapter` builds each relay's toggle URL from a user-supplied `str.format()` template carrying three placeholders — `{ip}` (the configured host), `{port}` (the zero-based relay index), `{state}` (`1`/`0`) — rather than implementing any one vendor's fixed API.

**Rationale:** unlike TP-Link Kasa (one documented wire protocol across a whole product line, handled by the sibling `kasa_switch` plugin), the class of board this plugin targets — cheap ESP8266/Arduino-based Ethernet relay boards — has no common protocol at all; each board's firmware author wired up whatever URL scheme was convenient. Hard-coding support for one specific board's scheme would make this plugin useless for the next board a user happens to own. A template is the smallest mechanism that covers the general case: `str.format()`'s own field-spec syntax (e.g. `{port:02d}`) is reused as-is for zero-padding or similar needs, rather than this plugin inventing its own mini-templating language.

**Default template fidelity (`RELAY-010`):** the default, `"http://{ip}/30000/{port}{state}"`, is chosen specifically because it reproduces the motivating reference example byte-for-byte: relay 1 (`port=0`) on (`state=1`) renders `http://<ip>/30000/01`; off (`state=0`) renders `http://<ip>/30000/00`. A user whose board matches that exact scheme needs to change nothing but the host; a user whose board differs edits the template, not the code.

**No readback (PSD Section 5 non-goal):** `RelayOutlet.state` is set only by a successful `set_switch` call — there is no `get_sysinfo`-equivalent to query, unlike `kasa_switch.adapter.KasaSwitchAdapter`. `connect()` is therefore a no-op beyond marking the adapter ready; the relay list is built from the configured `port_count` at construction time rather than from any device enumeration call.

### 2.2 Physical Location

`generic_relay.*` — a standalone top-level package, matching the Galileo Plugins repository's one-top-level-package-per-plugin convention ([`Galileo-Plugins/README.md`](https://github.com/gordtulloch/Galileo-Plugins/blob/main/README.md)). The `plugin.toml` manifest declares `entry_point = "generic_relay"`, `api_min = "1"`, `api_max = "1"`, and `tier = "first_party"`.

---

## 3. Module / Component Design

### 3.1 `generic_relay` — Generic Internet Relay Control

- **Responsibility:** Configurable HTTP relay-toggle client, Switch device backend, and the tabbed device panel.
- **`generic_relay.adapter.GenericRelayAdapter`** (`galileo.core.devices.DeviceBackend` subclass) — satisfies `EQP-SW-010`/the `_SwitchBackend` protocol core's `SwitchController` already drives. Constructed with `host`, `port_count`, and `url_template` (default `DEFAULT_URL_TEMPLATE`, Section 2.1); builds exactly `port_count` `RelayOutlet`s named `Relay 1`…`Relay N` — satisfies `RELAY-020`. `build_url(relay_index_0based, state)` applies the template; `set_switch(name, value)` resolves *name* to its zero-based index, performs the GET via `asyncio.to_thread(requests.get, ...)` so the synchronous `requests` call doesn't block the event loop, calls `raise_for_status()`, and only then updates the tracked `RelayOutlet.state` — satisfies `RELAY-010`, `RELAY-030`, `RELAY-040`.
- **`generic_relay.settings.GenericRelaySettings`** — `QSettings`-backed, JSON-encoded list of `{"host", "label", "port_count", "url_template"}` entries under the `Galileo` organisation (the same pattern `kasa_switch.settings`/`vstarget.settings` use).
- **`generic_relay.ui.build_generic_relay_page`** — one `_DeviceTab` per configured board inside a `QTabWidget` with `tabsClosable(True)`; a "+" corner widget opens `AddRelayDeviceDialog` (host/IP, relay count, URL template pre-filled with the default, with an inline hint explaining the placeholders) and persists the new entry via `GenericRelaySettings.add_device`; closing a tab calls `GenericRelaySettings.remove_device` without touching any other tab. Unlike the Kasa panel, there is no poll timer (Section 2.1 — nothing to poll); the table re-renders immediately after each toggle attempt, success or failure — satisfies `RELAY-050`.
- **Satisfies:** `RELAY-010`–`RELAY-050`.

---

## 4. Data Design

| Data | Format | Storage |
|---|---|---|
| Configured device list (host, label, relay count, URL template) | `QSettings`, JSON-encoded list value | Platform-native settings store under the `Galileo` organisation / `GenericRelay` application |

This plugin adds no database of its own. Relay state is held only in memory (the last commanded value, Section 2.1) and is not persisted — a restart shows every relay as off until the next command, which is the correct reflection of "the panel does not actually know," not a bug to be worked around.

---

## 5. Interface Design

- **Plugin boundary:** this plugin depends only on core's device port interfaces (`galileo.core.devices.DeviceBackend`/`DeviceCategory.SWITCH`) and the `PluginContext.register_device_backend` call it is given at load time — identical to core SDD Section 6.3's Plugin API Surface description.
- **External interface this plugin adds:** a plain HTTP GET to a user-configured URL per relay toggle (`generic_relay.adapter`, via `requests`). Because the target is whatever arbitrary board the user has configured rather than a named third-party service, this is a device-port-level interface rather than an `EXT`-domain requirement, the same framing [the Kasa Switch plugin's SDD](../kasa_switch/SDD.md) Section 5 gives its own device-local protocol.

---

## 6. Path to Traceability Matrix

A row per requirement ID in [this plugin's SRS](SRS.md), mapped to the module in Section 3 above and a test case ID — see [RTM.md](RTM.md).

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SDD](../../SDD.md).*
