# Generic Relay Plugin — RTM (Requirements Traceability Matrix)

| | |
|---|---|
| **Project** | Galileo — Generic Relay Plugin |
| **Document** | RTM (Requirements Traceability Matrix), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-05 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md), [SDD](SDD.md) |
| **Parent project** | [Galileo Core RTM](../../RTM.md) |

---

## 1. Purpose and Method

This RTM maps every numbered requirement in [this plugin's SRS](SRS.md) to the SDD component that satisfies it and to a Test Case ID, structurally parallel to [Galileo core's own RTM](../../RTM.md) and [the VSTarget plugin's RTM](../vstarget/RTM.md). **Test Case ID convention:** `TC-<requirement-ID>` (e.g. `TC-RELAY-010` verifies `RELAY-010`). The plugin's own suite lives beside its package in the [Galileo Plugins repository](https://github.com/gordtulloch/Galileo-Plugins) (`generic_relay/tests/test_generic_relay.py`).

**Verification Method:** `Test` (automated) unless noted otherwise. `RELAY-050` (the panel UI) is verified by `Manual`/smoke test — headless construction of the panel widget is checked, but interactive Qt behavior (dialog flow, tab add/remove click-through) has no automated test in this plugin's suite, consistent with the rest of Galileo's UI pages.

**Coverage:** 5 requirements, 100% mapped to an SDD component; 4 of 5 covered by an automated test.

---

## 2. Traceability Matrix

### `RELAY` — Generic Internet Relay Control

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `RELAY-010` | MVP | SDD 3.1 `generic_relay` (`adapter.py`) | Test | `TC-RELAY-010` |
| `RELAY-020` | MVP | SDD 3.1 `generic_relay` (`adapter.py`) | Test | `TC-RELAY-020` |
| `RELAY-030` | MVP | SDD 3.1 `generic_relay` (`adapter.py`) | Test | `TC-RELAY-030` |
| `RELAY-040` | MVP | SDD 3.1 `generic_relay` (`adapter.py`) | Test | `TC-RELAY-040` |
| `RELAY-050` | MVP | SDD 3.1 `generic_relay` (`ui.py`) | Manual | `TC-RELAY-050` |

---

## 3. Summary by Domain

| Domain | Requirements | MVP | P2 | P3 |
|---|---|---|---|---|
| `RELAY` | 5 | 5 | 0 | 0 |
| **Total** | **5** | **5** | **0** | **0** |

---

## 4. Cross-Reference to Core

Requirements this plugin's own rows trace to but do not define (see [PSD.md Section 6](PSD.md#6-dependencies-on-galileo-core) and [Galileo core's own RTM](../../RTM.md) for their coverage): core `PLUG-010`–`PLUG-120` (plugin framework, enable/disable, install from ZIP, marketplace download, and remove), `ARCH-070` (device-backend registration extension point), `EQP-SW-010` (the Switch device-port contract this plugin's backend satisfies).
