# SwitchBot Bot Plugin — SRS (Software Requirements Specification)

| | |
|---|---|
| **Document** | SRS, v0.1, draft |
| **Date** | 2026-10-22 |
| **Upstream** | [PSD](PSD.md) |
| **Downstream** | [SDD](SDD.md), [RTM](RTM.md) |
| **Parent** | [Galileo Core SRS](../../SRS.md) |

Covers the `SBOT` domain from [PSD Section 6](PSD.md). IDs follow core's `<DOMAIN>-<###>` convention in steps of 10; priorities are core's MVP/P2/P3. Operating environment is core's (Windows/macOS/Linux) plus a Bluetooth LE adapter in range of the Bot.

## 1. `SBOT` — SwitchBot Bot BLE Control

Delivered as a first-party, independently installable and disableable plugin (core `PLUG-060`), shown on Equipment > Switches (core `PLUG-070`, `panel_level = "equipment:switch"`).

| ID | Requirement | Priority |
|---|---|---|
| SBOT-010 | The system shall command a SwitchBot Bot over Bluetooth LE without any cloud account or hub: press, on and off commands, the password-protected form (CRC32 of the password), and decode the Bot's status reply, treating any status other than success as an error with a readable reason. | MVP |
| SBOT-020 | The system shall expose each Bot as exactly one Switch (traces to core `EQP-SW-010`): in dual-state mode On/Off extend and retract the arm; in press mode both press once. Connecting shall read the Bot's battery level and mode. | MVP |
| SBOT-030 | The system shall raise a reportable error, never silently succeed, when asked to switch a name that does not exist, when the Bot reports a failure status (e.g. wrong password), or when Bluetooth support (`bleak`) is unavailable; a failed command shall not change the state shown. | MVP |
| SBOT-040 | The system shall discover Bots by Bluetooth scan, recognising SwitchBot Bots by their advertised device type and ignoring other devices, strongest signal first. | MVP |
| SBOT-050 | The system shall present a panel with Scan, Add-by-address (address, label, optional password), and per-Bot On / Off / Press / Check controls showing battery and mode; the Bot list shall persist across restarts; Bluetooth I/O shall not block the UI thread; and Bots shall not be polled in the background. | MVP |

## 2. Counts

| Domain | Requirements | MVP | P2 | P3 |
|---|---|---|---|---|
| SBOT | 5 | 5 | 0 | 0 |
