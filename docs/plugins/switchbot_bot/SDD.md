# SwitchBot Bot Plugin — SDD (Software Design Description)

| | |
|---|---|
| **Document** | SDD, v0.1, draft |
| **Date** | 2026-10-22 |
| **Upstream** | [PSD](PSD.md), [SRS](SRS.md) |
| **Downstream** | [RTM](RTM.md) |
| **Parent** | [Galileo Core SDD](../../SDD.md) |

Describes how the plugin's one module satisfies [its SRS](SRS.md), attached to core only through the `galileo.plugins` extension points (core SDD §4.20, §6.3).

## 1. Design Considerations

### 1.1 `bleak` plus a local protocol layer, not `switchbotpy` (ADR-SBOT-001)

**Decision:** `switchbot_bot.protocol` re-implements the Bot's GATT command set on top of [`bleak`](https://github.com/hbldh/bleak), following the protocol as implemented in switchbotpy, instead of depending on switchbotpy.

**Rationale:** switchbotpy drives BlueZ's `gatttool` through `pygatt` and `pexpect`, so it works on Linux only, and it targets Python 3.6–3.8. Galileo runs on Windows, macOS and Linux (including Raspberry Pi) on Python ≥ 3.11. `bleak` uses each platform's native Bluetooth stack. The Bot protocol itself is small: write a command to characteristic `cba20002-…`, receive a status on notify characteristic `cba20003-…`.

**Consequences:** `bleak` is a plugin dependency that Galileo's ZIP install does not fetch, so `bleak` is imported lazily and a missing install surfaces as a `SwitchBotError` telling the user to `pip install bleak` (SBOT-030). Package name `switchbot_bot` follows the one-top-level-package-per-plugin convention; `plugin.toml` sets `entry_point = "switchbot_bot"`, `api_min = api_max = "1"`, `tier = "first_party"`.

### 1.2 One connection per command, no polling

A Bot sleeps between contacts and runs on a coin cell. Each command (and each **Check**) opens a fresh connection, writes, waits for the notification and disconnects. A dropped link therefore fails only that call (ARCH-060). The panel reads status once when a Bot's box appears.

### 1.3 State is the last command

The settings reply (`57 02`) carries battery, firmware and mode, not the arm position, so `BotSwitch.state` is what Galileo last sent. **Press** exists because it is independent of that assumption.

## 2. Module Design

### 2.1 `switchbot_bot`

- **`protocol`** — `Action` (PRESS/ON/OFF suffix bytes), `build_command` (`57 01`+suffix, or `57 11`+big-endian CRC32(password)+suffix), `check_status`/`parse_settings` (status codes 3/7/8/9/11 mapped to messages; battery = byte 1, firmware = byte 2 ÷ 10, dual-state = bit 4 of byte 9), `scan` (recognises service data under `0000fd3d-…` whose low 7 bits of byte 0 are `0x48`), and `send`. Satisfies `SBOT-010`, `SBOT-030`, `SBOT-040`.
- **`adapter.SwitchBotAdapter`** (`DeviceBackend`) — one `BotSwitch` per Bot. `connect()` sends `57 02` and records battery and mode; `set_switch` chooses PRESS in press mode, else ON/OFF, and updates state only after a success status; `press()` is unconditional. Satisfies `SBOT-020`, `SBOT-030`.
- **`settings.SwitchBotSettings`** — `QSettings` (org `Galileo`, app `SwitchBotBot`), JSON list of `{address, label, password}`, same pattern as `kasa_switch.settings`.
- **`ui.build_switchbot_page`** — Scan and Add-by-address (`AddBotDialog`); one `_BotBox` per Bot with On/Off/Press/Check/Remove. Work runs on a daemon thread via `asyncio.run`, results return by Qt signals; buttons are disabled while a command is in flight. Satisfies `SBOT-050`.
- **Help** — `switchbot_bot/help/plugin.SwitchBotPlugin.md`, registered by Galileo when the plugin loads.
- **Satisfies:** `SBOT-010`–`SBOT-050`.

## 3. Data Design

| Data | Format | Storage |
|---|---|---|
| Bot list (address, label, password) | JSON list in `QSettings` | Platform settings store, org `Galileo` / app `SwitchBotBot` |

No database. Switch state is not persisted.

## 4. Interfaces

- **Plugin boundary:** only `galileo.core.devices` (`DeviceBackend`, `DeviceCategory.SWITCH`) and `PluginContext.register_device_backend`.
- **Added external interface:** Bluetooth LE GATT to each Bot, through `bleak`. A device-port-level interface like INDI/Alpaca, so not an `EXT` requirement.
