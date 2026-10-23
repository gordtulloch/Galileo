# SwitchBot Bot Plugin — RTM (Requirements Traceability Matrix)

| | |
|---|---|
| **Document** | RTM, v0.1, draft |
| **Date** | 2026-10-22 |
| **Upstream** | [PSD](PSD.md), [SRS](SRS.md), [SDD](SDD.md) |
| **Parent** | [Galileo Core RTM](../../RTM.md) |

Maps each [SRS](SRS.md) requirement to its SDD component and test. Test IDs are `TC-<requirement-ID>`; the suite is `switchbot_bot/tests/test_switchbot.py` in the [Galileo Plugins repository](https://github.com/gordtulloch/Galileo-Plugins) and uses a faked BLE layer, so it needs no Bluetooth hardware. `SBOT-050` (the panel) is verified manually: the page is built headless as a smoke check, but click-through behaviour and real Bluetooth are not automated, consistent with the other plugins' panels.

**Coverage:** 5 requirements, 100% mapped to an SDD component; 4 of 5 covered by an automated test.

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `SBOT-010` | MVP | SDD 2.1 `switchbot_bot` (`protocol.py`) | Test | `TC-SBOT-010` |
| `SBOT-020` | MVP | SDD 2.1 `switchbot_bot` (`adapter.py`) | Test | `TC-SBOT-020` |
| `SBOT-030` | MVP | SDD 2.1 `switchbot_bot` (`adapter.py`, `protocol.py`) | Test | `TC-SBOT-030` |
| `SBOT-040` | MVP | SDD 2.1 `switchbot_bot` (`protocol.py`) | Test | `TC-SBOT-040` |
| `SBOT-050` | MVP | SDD 2.1 `switchbot_bot` (`ui.py`, `settings.py`) | Manual | `TC-SBOT-050` |

| Domain | Requirements | MVP | P2 | P3 |
|---|---|---|---|---|
| `SBOT` | 5 | 5 | 0 | 0 |

**Cross-reference to core:** `PLUG-010`–`PLUG-120`, `ARCH-070` (device-backend registration), `EQP-SW-010` (Switch port contract), `ARCH-060` (per-device fault isolation, mirrored by each Bot's independent box).
