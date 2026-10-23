# AllSkyCam Plugin — RTM (Requirements Traceability Matrix)

| | |
|---|---|
| **Project** | Galileo — AllSkyCam Plugin |
| **Document** | RTM (Requirements Traceability Matrix), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-22 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md), [SDD](SDD.md) |
| **Parent project** | [Galileo Core RTM](../../RTM.md) |

---

## 1. Purpose and Method

This RTM maps every requirement in [this plugin's SRS](SRS.md) to the SDD component that satisfies it and to Test Case IDs. **Test Case ID convention:** `TC-<requirement-ID>` (e.g. `TC-ASC-010` verifies `ASC-010`); several test functions may carry one ID. The suite lives beside the package in the [Galileo Plugins repository](https://github.com/gordtulloch/Galileo-Plugins) (`allskycam/tests/test_asc.py`).

**Verification Method:** `Test` (automated). The Qt-backed tests build the real widgets offscreen; `ASC-010`/`ASC-020` additionally run end to end against a local HTTP server that mimics indi-allsky's redirect. Pixel-level appearance and the docked pane inside a full Galileo window are checked by the core suite's `TC-PLUG-130`/`TC-PLUG-140` (window and dock wiring) rather than here.

**Coverage:** 9 requirements, 100% mapped to an SDD component and an automated test.

---

## 2. Traceability Matrix

### `ASC` — All-Sky Camera Viewer

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `ASC-010` | MVP | SDD 3.1 `allskycam` (`client.py`) | Test | `TC-ASC-010` |
| `ASC-020` | MVP | SDD 3.1 `allskycam` (`client.py`, `cycle.py`, `service.py`) | Test | `TC-ASC-020` |
| `ASC-030` | MVP | SDD 3.1 `allskycam` (`daytime.py`, `cycle.py`) | Test | `TC-ASC-030` |
| `ASC-040` | MVP | SDD 3.1 `allskycam` (`config.py`, `service.py`, `ui.py`) | Test | `TC-ASC-040` |
| `ASC-050` | MVP | SDD 3.1 `allskycam` (`ui.py` `LatestView`) | Test | `TC-ASC-050` |
| `ASC-060` | MVP | SDD 3.1 `allskycam` (`buffer.py`, `ui.py` `AnimationView`) | Test | `TC-ASC-060` |
| `ASC-070` | MVP | SDD 3.1 `allskycam` (`__init__.py`, `ui.py` `DockPane`) | Test | `TC-ASC-070` |
| `ASC-080` | MVP | SDD 3.1 `allskycam` (`__init__.py`) | Test | `TC-ASC-080` |
| `ASC-090` | MVP | SDD 3.1 `allskycam` (`__init__.py`, `help/`) | Test | `TC-ASC-090` |

---

## 3. Summary by Domain

| Domain | Requirements | MVP | P2 | P3 |
|---|---|---|---|---|
| `ASC` | 9 | 9 | 0 | 0 |
| **Total** | **9** | **9** | **0** | **0** |

---

## 4. Cross-Reference to Core

Requirements this plugin's rows trace to but do not define: `PLUG-010`–`PLUG-120` (plugin framework), `PLUG-070` and `PLUG-130`–`PLUG-160` (panel placement, top-level section, dock pane, settings, site location), `HELP-060` (plugin help).
