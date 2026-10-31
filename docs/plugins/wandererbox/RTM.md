# WandererBox Plugin — RTM (Requirements Traceability Matrix)

| | |
|---|---|
| **Project** | Galileo — WandererBox Plugin |
| **Document** | RTM (Requirements Traceability Matrix), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-30 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md), [SDD](SDD.md) |
| **Parent project** | [Galileo Core RTM](../../RTM.md) |

---

## 1. Purpose and Method

This RTM maps every numbered requirement in [this plugin's SRS](SRS.md) to the SDD component that satisfies it and to a Test Case ID, structurally parallel to [Galileo core's own RTM](../../RTM.md) and the [Kasa Switch plugin's RTM](../kasa_switch/RTM.md). **Test Case ID convention:** `TC-<requirement-ID>` (e.g. `TC-WBOX-010` verifies `WBOX-010`). The plugin's own suite lives beside its package in the [Galileo Plugins repository](https://github.com/gordtulloch/Galileo-Plugins) (`wandererbox/tests/test_wbox.py`).

**Verification Method:** `Test` (automated). Because the plugin is data, its tests need no server and no hardware: they check the profile values directly, and resolve each profile against recorded property sets of the three drivers using core's mapping engine (`EQP-SW-080`).

**Test dependency:** the tests exercise core's mapping engine (`EQP-SW-030`–`EQP-SW-080`, `PLUG-210`), so they need a Galileo that includes it. The profiles are checked against property sets *transcribed from the driver sources*, not captured from a running driver or a real box, so a driver that differs from its source would not be caught; a `hardware`-marked test remains to be written against a real device.

**Coverage:** 10 requirements, 100% mapped to an SDD component; all 10 have an automated test (`wandererbox/tests/test_wbox.py`, 26 tests).

---

## 2. Traceability Matrix

### `WBOX` — Wanderer Switch Profiles

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `WBOX-010` | MVP | SDD 3.1 `wandererbox` (`plugin.py`) | Test | `TC-WBOX-010` |
| `WBOX-020` | MVP | SDD 3.1 `wandererbox` (`profiles.py`); SDD 3.2 device names and signatures; ADR-WBOX-002 | Test | `TC-WBOX-020` |
| `WBOX-030` | MVP | SDD 3.1 `wandererbox` (`profiles.py`); SDD 3.2 Pro V3 channels | Test | `TC-WBOX-030` |
| `WBOX-040` | MVP | SDD 3.1 `wandererbox` (`profiles.py`); SDD 3.2 Plus V3 channels | Test | `TC-WBOX-040` |
| `WBOX-050` | MVP | SDD 3.1 `wandererbox` (`profiles.py`); SDD 3.2 Dew Terminator channels | Test | `TC-WBOX-050` |
| `WBOX-060` | MVP | SDD 3.1 `wandererbox` (`profiles.py`); SDD 3.2 Dew duty | Test | `TC-WBOX-060` |
| `WBOX-070` | MVP | SDD 3.1 `wandererbox` (`profiles.py`); SDD 3.2 Pro V3 / Plus V3 channels | Test | `TC-WBOX-070` |
| `WBOX-080` | MVP | SDD 3.1 `wandererbox` (`profiles.py`); SDD 3.2 Readings | Test | `TC-WBOX-080` |
| `WBOX-090` | MVP | SDD 3.2 device names and signatures; ADR-WBOX-002 | Test | `TC-WBOX-090` |
| `WBOX-100` | MVP | SDD 3.1 `wandererbox` (`plugin.py`); ADR-WBOX-001 | Test | `TC-WBOX-100` |

---

## 3. Summary by Domain

| Domain | Requirements | MVP | P2 | P3 |
|---|---|---|---|---|
| `WBOX` | 10 | 10 | 0 | 0 |
| **Total** | **10** | **10** | **0** | **0** |

---

## 4. Cross-Reference to Core

Requirements this plugin's own rows trace to but do not define (see [PSD.md Section 6](PSD.md#6-dependencies-on-galileo-core) and [Galileo core's own RTM](../../RTM.md) for their coverage): core `PLUG-060`/`PLUG-120` (disabled-inert and removal), `PLUG-210` (profile registration), `EQP-SW-020` (discovery of a profile-claimed device), `EQP-SW-030`–`EQP-SW-060` (structured model, writes, scale), `EQP-SW-070` (*Other* group), `EQP-SW-080` (profile model and signature resolution), `EQP-SW-090` (Switches page), `EQP-SW-100` (flat switch contract), `EQP-SW-120` (dynamic properties).
