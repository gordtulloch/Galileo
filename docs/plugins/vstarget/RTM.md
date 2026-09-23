# VSTarget Plugin — RTM (Requirements Traceability Matrix)

| | |
|---|---|
| **Project** | Galileo — VSTarget Plugin |
| **Document** | RTM (Requirements Traceability Matrix), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-09-23 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md), [SDD](SDD.md) |
| **Parent project** | [Galileo Core RTM](../../RTM.md) |

---

## 1. Purpose and Method

This RTM maps every numbered requirement in [this plugin's SRS](SRS.md) to the SDD component(s) that satisfy it and to a Test Case ID, structurally parallel to [Galileo core's own RTM](../../RTM.md). **Test Case ID convention:** `TC-<requirement-ID>` (e.g. `TC-VST-010` verifies `VST-010`). No test suite exists yet for this plugin — these IDs are the reserved identifiers a future test suite should use.

**Verification Method:** `Test` (automated/manual functional test) unless noted otherwise.

**Coverage:** 19 requirements, 100% mapped to an SDD component.

---

## 2. Traceability Matrix

### `VST-EXT` — External Interface Requirements (Plugin-Scoped)

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `VST-EXT-010` | MVP | SDD 3.1 `galileo.plugins.vstarget.planning` | Test | `TC-VST-EXT-010` |

### `VST` — Variable Star Target Planning

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `VST-010` | MVP | SDD 3.1 `galileo.plugins.vstarget.planning` | Test | `TC-VST-010` |
| `VST-020` | MVP | SDD 3.1 `galileo.plugins.vstarget.planning` | Test | `TC-VST-020` |
| `VST-030` | MVP | SDD 3.1 `galileo.plugins.vstarget.planning` | Test | `TC-VST-030` |
| `VST-040` | P2 | SDD 3.1 `galileo.plugins.vstarget.planning` | Test | `TC-VST-040` |
| `VST-050` | MVP | SDD 3.1 `galileo.plugins.vstarget.planning` | Test | `TC-VST-050` |
| `VST-060` | MVP | SDD 3.1 `galileo.plugins.vstarget.planning` | Test | `TC-VST-060` |
| `VST-070` | MVP | SDD 3.1 `galileo.plugins.vstarget.planning` | Test | `TC-VST-070` |
| `VST-080` | MVP | SDD 3.1 `galileo.plugins.vstarget.planning` | Test | `TC-VST-080` |
| `VST-090` | MVP | SDD 3.1 `galileo.plugins.vstarget.planning` | Test | `TC-VST-090` |

### `VST-AN` — Variable Star Analysis & Photometry

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `VST-AN-010` | MVP | SDD 3.2 `galileo.plugins.vstarget.analysis` | Test | `TC-VST-AN-010` |
| `VST-AN-020` | MVP | SDD 3.2 `galileo.plugins.vstarget.analysis` | Test | `TC-VST-AN-020` |
| `VST-AN-030` | MVP | SDD 3.2 `galileo.plugins.vstarget.analysis` | Test | `TC-VST-AN-030` |
| `VST-AN-040` | MVP | SDD 3.2 `galileo.plugins.vstarget.analysis` | Test | `TC-VST-AN-040` |
| `VST-AN-050` | MVP | SDD 3.2 `galileo.plugins.vstarget.analysis` | Test | `TC-VST-AN-050` |
| `VST-AN-060` | P2 | SDD 3.2 `galileo.plugins.vstarget.analysis` | Test | `TC-VST-AN-060` |
| `VST-AN-070` | P2 | SDD 3.2 `galileo.plugins.vstarget.analysis` | Test | `TC-VST-AN-070` |
| `VST-AN-080` | P2 | SDD 3.2 `galileo.plugins.vstarget.analysis` | Test | `TC-VST-AN-080` |
| `VST-AN-090` | P2 | SDD 3.2 `galileo.plugins.vstarget.analysis` | Test | `TC-VST-AN-090` |

---

## 3. Summary by Domain

| Domain | Requirements | MVP | P2 | P3 |
|---|---|---|---|---|
| `VST-EXT` | 1 | 1 | 0 | 0 |
| `VST` | 9 | 8 | 1 | 0 |
| `VST-AN` | 9 | 5 | 4 | 0 |
| **Total** | **19** | **14** | **5** | **0** |

---

## 4. Cross-Reference to Core

Requirements this plugin's own rows trace to but do not define (see [PSD.md Section 7](PSD.md#7-dependencies-on-galileo-core) and [Galileo core's own RTM](../../RTM.md) for their coverage): core `PLUG-010`–`PLUG-080`, `SKY-030`, `EXT-080`, `EXT-110`, `EXT-120`, `PLT-010`, `SCHED-010`.
