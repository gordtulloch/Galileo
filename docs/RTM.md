# Galileo — RTM (Requirements Traceability Matrix)

| | |
|---|---|
| **Project** | Galileo — Cross-Platform Astrophotography Imaging Suite |
| **Document** | RTM (Requirements Traceability Matrix), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-09-16 |
| **Upstream documents** | [PSD (Project Scope Document)](PSD.md), [SRS (Software Requirements Specification)](SRS.md), [SDD (Software Design Description)](SDD.md) |

---

## 1. Purpose and Method

This RTM maps every numbered SRS requirement to the SDD component(s) that satisfy it (per SDD Section 8's construction method: `Satisfies` lines in Section 4, or Section 7 for cross-cutting non-functional requirements) and to a Test Case ID. It was generated directly from the current SRS/SDD text, not hand-transcribed, so it reflects exactly what those documents say as of this revision — regenerate it after any SRS/SDD change rather than hand-editing rows out of sync.

**Test Case ID convention:** `TC-<requirement-ID>` (e.g. `TC-ARCH-010` verifies `ARCH-010`). No test suite exists yet (the project has no implementation beyond `docs/` and prior-turn scaffolding) — these IDs are the reserved identifiers a future test suite should use, not evidence that tests exist.

**Verification Method:** `Test` (automated/manual functional test) unless noted otherwise — `Inspection` for pure documentation deliverables, `Demonstration` for installer/build-pipeline artifacts verified by producing and running them rather than a unit/integration test.

**Coverage:** 272 requirements (258 counted in the SRS's own domain-summary total; the 14 `EXT` external-interface requirements are excluded from that summary by the SRS's own convention but are fully covered here), 100% mapped to an SDD component (0 orphans, verified by cross-check script against SDD Section 4 `Satisfies` lines + Section 7). `VST`/`VST-AN` (19 requirements, including their own `VST-EXT-010`) are the VSTarget plugin's own and are traced separately: [`docs/plugins/vstarget/RTM.md`](../plugins/vstarget/RTM.md).

**`SEQ`/`SEQ-ADV` → `SES`:** this revision replaces the former `SEQ`/`SEQ-ADV` domains with the unified `SES` ("Sessions") domain end to end (SRS Sections 4.5/4.5a/4.6). Every row below uses `SES-*` IDs; there is no `SEQ`/`SEQ-ADV` row remaining in this matrix.

---

## 2. Traceability Matrix

### `EXT` — External Interface Requirements

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `EXT-010` | MVP | SDD Sec 7: Architectural given from ADR-001 (Section 2.1) — Galileo is a PySide6 desktop application by construction, not a per-module design choice | Test | `TC-EXT-010` |
| `EXT-020` | MVP | SDD 4.2 `galileo.adapters.indi`; SDD 4.3 `galileo.adapters.alpaca` | Test | `TC-EXT-020` |
| `EXT-030` | MVP | SDD 4.2 `galileo.adapters.indi`; SDD 4.3 `galileo.adapters.alpaca` | Test | `TC-EXT-030` |
| `EXT-040` | MVP | SDD 4.12 `galileo.platesolve` | Test | `TC-EXT-040` |
| `EXT-050` | MVP | SDD 4.14 `galileo.guiding` | Test | `TC-EXT-050` |
| `EXT-060` | MVP | SDD 4.18 `galileo.metadata` | Test | `TC-EXT-060` |
| `EXT-070` | P3 | SDD 4.19 `galileo.notify` | Test | `TC-EXT-070` |
| `EXT-080` | MVP | SDD 4.23 `galileo.library` | Test | `TC-EXT-080` |
| `EXT-090` | P2 | SDD 4.23 `galileo.library` | Test | `TC-EXT-090` |
| `EXT-110` | MVP | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-EXT-110` |
| `EXT-120` | MVP | SDD 4.23 `galileo.library` | Test | `TC-EXT-120` |
| `EXT-130` | P2 | SDD 4.8 `galileo.planning.sky_atlas`; SDD 4.16 `galileo.safety` | Test | `TC-EXT-130` |
| `EXT-140` | P2 | SDD 4.23 `galileo.library` | Test | `TC-EXT-140` |
| `EXT-150` | P2 | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-EXT-150` |

### `ARCH` — Protocol & Device Abstraction Layer

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `ARCH-010` | MVP | SDD 4.1 `galileo.core.devices`; SDD 4.2 `galileo.adapters.indi`; SDD 4.3 `galileo.adapters.alpaca` | Test | `TC-ARCH-010` |
| `ARCH-020` | MVP | SDD 4.1 `galileo.core.devices`; SDD 4.2 `galileo.adapters.indi`; SDD 4.3 `galileo.adapters.alpaca` | Test | `TC-ARCH-020` |
| `ARCH-030` | MVP | SDD 4.1 `galileo.core.devices`; SDD 4.2 `galileo.adapters.indi`; SDD 4.3 `galileo.adapters.alpaca` | Test | `TC-ARCH-030` |
| `ARCH-040` | MVP | SDD 4.1 `galileo.core.devices` | Test | `TC-ARCH-040` |
| `ARCH-050` | P2 | SDD 4.1 `galileo.core.devices`; SDD 4.2 `galileo.adapters.indi`; SDD 4.3 `galileo.adapters.alpaca` | Test | `TC-ARCH-050` |
| `ARCH-060` | MVP | SDD 4.1 `galileo.core.devices` | Test | `TC-ARCH-060` |
| `ARCH-070` | P2 | SDD 4.1 `galileo.core.devices` | Test | `TC-ARCH-070` |
| `ARCH-080` | MVP | SDD 4.1 `galileo.core.devices` | Test | `TC-ARCH-080` |

### `EQP` — Equipment Control

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `EQP-010` | MVP | SDD 4.1 `galileo.core.devices` | Test | `TC-EQP-010` |
| `EQP-020` | MVP | SDD 4.1 `galileo.core.devices` | Test | `TC-EQP-020` |
| `EQP-030` | MVP | SDD 4.1 `galileo.core.devices` | Test | `TC-EQP-030` |
| `EQP-040` | MVP | SDD 4.1 `galileo.core.devices` | Test | `TC-EQP-040` |
| `EQP-050` | MVP | SDD 4.1 `galileo.core.devices` | Test | `TC-EQP-050` |
| `EQP-060` | P2 | SDD 4.1 `galileo.core.devices` | Test | `TC-EQP-060` |
| `EQP-070` | MVP | SDD 4.1 `galileo.core.devices` | Test | `TC-EQP-070` |
| `EQP-CAM-010` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-CAM-010` |
| `EQP-CAM-020` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-CAM-020` |
| `EQP-CAM-030` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-CAM-030` |
| `EQP-CAM-040` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-CAM-040` |
| `EQP-MNT-010` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-MNT-010` |
| `EQP-MNT-020` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-MNT-020` |
| `EQP-MNT-030` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-MNT-030` |
| `EQP-MNT-040` | P2 | SDD 4.1 `galileo.core.devices` | Test | `TC-EQP-MNT-040` |
| `EQP-MNT-050` | MVP | SDD 4.1 `galileo.core.devices` / `galileo.tracking` | Test | `TC-EQP-MNT-050` |
| `EQP-FW-010` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-FW-010` |
| `EQP-FW-020` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-FW-020` |
| `EQP-FOC-010` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-FOC-010` |
| `EQP-FOC-020` | P2 | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-FOC-020` |
| `EQP-FOC-030` | MVP | SDD 4.1 `galileo.core.devices` | Test | `TC-EQP-FOC-030` |
| `EQP-ROT-010` | P2 | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-ROT-010` |
| `EQP-GDR-010` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-GDR-010` |
| `EQP-SW-010` | P2 | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-SW-010` |
| `EQP-FP-010` | MVP | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-FP-010` |
| `EQP-WX-010` | P2 | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-WX-010` |
| `EQP-DOME-010` | P2 | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-DOME-010` |
| `EQP-SAFE-010` | P2 | SDD 4.2 `galileo.adapters.indi` | Test | `TC-EQP-SAFE-010` |

### `PROF` — Equipment Profiles (Piers)

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `PROF-010` | MVP | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-010` |
| `PROF-020` | MVP | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-020` |
| `PROF-030` | MVP | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-030` |
| `PROF-040` | MVP | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-040` |
| `PROF-050` | P2 | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-050` |
| `PROF-060` | MVP | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-060` |
| `PROF-070` | MVP | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-070` |
| `PROF-080` | MVP | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-080` |
| `PROF-090` | MVP | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-090` |
| `PROF-100` | MVP | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-100` |
| `PROF-110` | MVP | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-110` |
| `PROF-120` | MVP | SDD 4.4 `galileo.equipment.profiles` | Test | `TC-PROF-120` |

### `OBS` — Multi-Mount Observatory Management (exceeds EKOS, Section 6.6)

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `OBS-010` | P2 | SDD 4.4a `galileo.observatory` | Test | `TC-OBS-010` |
| `OBS-020` | P2 | SDD 4.4a `galileo.observatory` | Test | `TC-OBS-020` |
| `OBS-030` | P2 | SDD 4.4a `galileo.observatory` | Test | `TC-OBS-030` |
| `OBS-040` | P2 | SDD 4.4a `galileo.observatory` | Test | `TC-OBS-040` |
| `OBS-050` | P2 | SDD 4.4a `galileo.observatory` | Test | `TC-OBS-050` |
| `OBS-060` | P2 | SDD 4.4a `galileo.observatory` | Test | `TC-OBS-060` |
| `OBS-070` | P2 | SDD 4.4a `galileo.observatory` | Test | `TC-OBS-070` |
| `OBS-080` | P2 | SDD 4.4a `galileo.observatory` | Test | `TC-OBS-080` |
| `OBS-090` | P2 | SDD 4.4a `galileo.observatory` | Test | `TC-OBS-090` |

### `IMG` — Imaging Tab

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `IMG-010` | MVP | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-010` |
| `IMG-020` | MVP | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-020` |
| `IMG-030` | MVP | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-030` |
| `IMG-040` | MVP | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-040` |
| `IMG-050` | P2 | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-050` |
| `IMG-060` | MVP | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-060` |
| `IMG-070` | MVP | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-070` |
| `IMG-080` | P2 | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-080` |
| `IMG-090` | MVP | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-090` |
| `IMG-100` | P2 | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-100` |
| `IMG-110` | MVP | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-110` |
| `IMG-120` | P2 | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-120` |
| `IMG-130` | P2 | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-130` |
| `IMG-140` | P2 | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-140` |
| `IMG-150` | P2 | SDD 4.5 `galileo.ui.imaging` | Test | `TC-IMG-150` |
| `IMG-160` | P2 | SDD 4.5 `galileo.ui.imaging` / `galileo.livestack` | Test | `TC-IMG-160` |
| `IMG-170` | P2 | SDD 4.5 `galileo.ui.imaging` / `galileo.metadata` | Test | `TC-IMG-170` |
| `IMG-180` | MVP | SDD 4.5 `galileo.ui.imaging` / SDD 4.9 `galileo.planning.framing` | Test | `TC-IMG-180` |

### `SES` — Sessions (formerly `SEQ`/`SEQ-ADV`; SRS Sections 4.5/4.5a/4.6)

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `SES-010` | MVP | SDD 4.6 `galileo.sequencer.basic` | Test | `TC-SES-010` |
| `SES-020` | MVP | SDD 4.6 `galileo.sequencer.basic` | Test | `TC-SES-020` |
| `SES-030` | MVP | SDD 4.6 `galileo.sequencer.basic` | Test | `TC-SES-030` |
| `SES-040` | MVP | SDD 4.6 `galileo.sequencer.basic` | Test | `TC-SES-040` |
| `SES-050` | MVP | SDD 4.6 `galileo.sequencer.basic` | Test | `TC-SES-050` |
| `SES-060` | MVP | SDD 4.6 `galileo.sequencer.basic` | Test | `TC-SES-060` |
| `SES-070` | MVP | SDD 4.6 `galileo.sequencer.basic` | Test | `TC-SES-070` |
| `SES-080` | MVP | SDD 4.6 `galileo.sequencer.basic` | Test | `TC-SES-080` |
| `SES-090` | P3 | SDD 4.6 `galileo.sequencer.basic` | Test | `TC-SES-090` |
| `SES-100` | MVP | SDD 4.6a `galileo.ui.sessions` | Test | `TC-SES-100` |
| `SES-110` | MVP | SDD 4.6a `galileo.ui.sessions` | Test | `TC-SES-110` |
| `SES-120` | MVP | SDD 4.6a `galileo.ui.sessions` | Test | `TC-SES-120` |
| `SES-130` | MVP | SDD 4.6a `galileo.ui.sessions` | Test | `TC-SES-130` |
| `SES-140` | P2 | SDD 4.6a `galileo.ui.sessions` | Test | `TC-SES-140` |
| `SES-150` | P3 | SDD 4.6a `galileo.ui.sessions`; SDD 4.19 `galileo.notify` | Test | `TC-SES-150` |
| `SES-160` | MVP | SDD 4.6a `galileo.ui.sessions` | Test | `TC-SES-160` |
| `SES-170` | MVP | SDD 4.6a `galileo.ui.sessions` | Test | `TC-SES-170` |
| `SES-180` | P2 | SDD 4.6a `galileo.ui.sessions` | Test | `TC-SES-180` |
| `SES-190` | P2 | SDD 4.6a `galileo.ui.sessions` | Test | `TC-SES-190` |
| `SES-200` | MVP | SDD 4.6a `galileo.ui.sessions`; SDD 4.9b `galileo.scheduler` | Test | `TC-SES-200` |
| `SES-210` | MVP | SDD 4.6a `galileo.ui.sessions`; SDD 4.9b `galileo.scheduler` | Test | `TC-SES-210` |
| `SES-220` | MVP | SDD 4.6a `galileo.ui.sessions` | Test | `TC-SES-220` |
| `SES-230` | P2 | SDD 4.6a `galileo.ui.sessions` / SDD 4.9 `galileo.planning.framing` | Test | `TC-SES-230` |
| `SES-300` | P2 | SDD 4.7 `galileo.sequencer.advanced` | Test | `TC-SES-300` |
| `SES-310` | P2 | SDD 4.7 `galileo.sequencer.advanced` | Test | `TC-SES-310` |
| `SES-320` | P2 | SDD 4.7 `galileo.sequencer.advanced` | Test | `TC-SES-320` |
| `SES-330` | P2 | SDD 4.7 `galileo.sequencer.advanced` | Test | `TC-SES-330` |
| `SES-340` | P2 | SDD 4.7 `galileo.sequencer.advanced` | Test | `TC-SES-340` |
| `SES-350` | P2 | SDD 4.7 `galileo.sequencer.advanced` | Test | `TC-SES-350` |
| `SES-360` | P3 | SDD 4.7 `galileo.sequencer.advanced` | Test | `TC-SES-360` |

### `SKY` — Sky Atlas / Targets

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `SKY-010` | MVP | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-010` |
| `SKY-020` | MVP | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-020` |
| `SKY-030` | MVP | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-030` |
| `SKY-040` | P2 | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-040` |
| `SKY-050` | MVP | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-050` |
| `SKY-060` | MVP | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-060` |
| `SKY-070` | MVP | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-070` |
| `SKY-080` | MVP | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-080` |
| `SKY-090` | P2 | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-090` |
| `SKY-100` | MVP | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-100` |
| `SKY-110` | P2 | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-110` |
| `SKY-120` | P2 | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-SKY-120` |

### `FRAME` — Framing Assistant

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `FRAME-010` | MVP | SDD 4.9 `galileo.planning.framing` | Test | `TC-FRAME-010` |
| `FRAME-020` | MVP | SDD 4.9 `galileo.planning.framing` | Test | `TC-FRAME-020` |
| `FRAME-030` | MVP | SDD 4.9 `galileo.planning.framing` | Test | `TC-FRAME-030` |
| `FRAME-040` | P2 | SDD 4.9 `galileo.planning.framing` | Test | `TC-FRAME-040` |
| `FRAME-050` | P2 | SDD 4.9 `galileo.planning.framing` | Test | `TC-FRAME-050` |
| `FRAME-060` | P2 | SDD 4.9 `galileo.planning.framing` | Test | `TC-FRAME-060` |
| `FRAME-070` | MVP | SDD 4.9 `galileo.planning.framing` | Test | `TC-FRAME-070` |
| `FRAME-080` | P2 | SDD 4.9 `galileo.planning.framing` | Test | `TC-FRAME-080` |
| `FRAME-090` | P2 | SDD 4.9 `galileo.planning.framing` | Test | `TC-FRAME-090` |

### `SKYMAP` — Interactive Star Map / Planetarium (KStars/EKOS-informed)

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `SKYMAP-010` | MVP | SDD 4.9a `galileo.ui.skymap` | Test | `TC-SKYMAP-010` |
| `SKYMAP-020` | MVP | SDD 4.9a `galileo.ui.skymap` | Test | `TC-SKYMAP-020` |
| `SKYMAP-030` | MVP | SDD 4.9a `galileo.ui.skymap` | Test | `TC-SKYMAP-030` |
| `SKYMAP-040` | P2 | SDD 4.9a `galileo.ui.skymap` | Test | `TC-SKYMAP-040` |
| `SKYMAP-050` | P2 | SDD 4.9a `galileo.ui.skymap` | Test | `TC-SKYMAP-050` |
| `SKYMAP-060` | P2 | SDD 4.9a `galileo.ui.skymap` | Test | `TC-SKYMAP-060` |
| `SKYMAP-070` | P2 | SDD 4.9a `galileo.ui.star_atlas` / `galileo.planning.visibility` | Test | `TC-SKYMAP-070` |
| `SKYMAP-080` | P2 | SDD 4.9a `galileo.core.slew_guard` | Test | `TC-SKYMAP-080` |
| `SKYMAP-090` | P2 | SDD 4.9a `galileo.ui.star_atlas` | Test | `TC-SKYMAP-090` |

### `SCHED` — Observatory Scheduler (KStars/EKOS-informed)

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `SCHED-010` | MVP | SDD 4.9b `galileo.scheduler` | Test | `TC-SCHED-010` |
| `SCHED-020` | MVP | SDD 4.9b `galileo.scheduler` | Test | `TC-SCHED-020` |
| `SCHED-030` | MVP | SDD 4.9b `galileo.scheduler` | Test | `TC-SCHED-030` |
| `SCHED-040` | MVP | SDD 4.9b `galileo.scheduler` | Test | `TC-SCHED-040` |
| `SCHED-050` | MVP | SDD 4.9b `galileo.scheduler` | Test | `TC-SCHED-050` |
| `SCHED-060` | MVP | SDD 4.9b `galileo.scheduler` | Test | `TC-SCHED-060` |
| `SCHED-070` | P2 | SDD 4.9b `galileo.scheduler` | Test | `TC-SCHED-070` |
| `SCHED-080` | P2 | SDD 4.9b `galileo.scheduler` | Test | `TC-SCHED-080` |
| `SCHED-090` | MVP | SDD 4.9b `galileo.scheduler` | Test | `TC-SCHED-090` |
| `SCHED-100` | MVP | SDD 4.9b `galileo.scheduler` | Test | `TC-SCHED-100` |

### `CAL` — Calibration / Flat Wizard

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `CAL-010` | MVP | SDD 4.10 `galileo.calibration` | Test | `TC-CAL-010` |
| `CAL-020` | MVP | SDD 4.10 `galileo.calibration` | Test | `TC-CAL-020` |
| `CAL-030` | MVP | SDD 4.10 `galileo.calibration` | Test | `TC-CAL-030` |
| `CAL-040` | MVP | SDD 4.10 `galileo.calibration` | Test | `TC-CAL-040` |
| `CAL-050` | P2 | SDD 4.10 `galileo.calibration` | Test | `TC-CAL-050` |
| `CAL-060` | MVP | SDD 4.5 `galileo.ui.imaging` | Test | `TC-CAL-060` |

### `FOC` — Autofocus

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `FOC-010` | MVP | SDD 4.11 `galileo.autofocus` | Test | `TC-FOC-010` |
| `FOC-020` | MVP | SDD 4.11 `galileo.autofocus` | Test | `TC-FOC-020` |
| `FOC-030` | MVP | SDD 4.11 `galileo.autofocus` | Test | `TC-FOC-030` |
| `FOC-040` | P2 | SDD 4.11 `galileo.autofocus` | Test | `TC-FOC-040` |
| `FOC-050` | MVP | SDD 4.11 `galileo.autofocus` | Test | `TC-FOC-050` |
| `FOC-060` | P2 | SDD 4.11 `galileo.autofocus` | Test | `TC-FOC-060` |
| `FOC-070` | MVP | SDD 4.11 `galileo.autofocus` | Test | `TC-FOC-070` |
| `FOC-080` | P2 | SDD 4.11 `galileo.autofocus` | Test | `TC-FOC-080` |
| `FOC-090` | MVP | SDD 4.11 `galileo.autofocus` | Test | `TC-FOC-090` |

### `PLT` — Plate Solving

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `PLT-010` | MVP | SDD 4.12 `galileo.platesolve` | Test | `TC-PLT-010` |
| `PLT-020` | MVP | SDD 4.12 `galileo.platesolve` | Test | `TC-PLT-020` |
| `PLT-030` | MVP | SDD 4.12 `galileo.platesolve` | Test | `TC-PLT-030` |
| `PLT-040` | MVP | SDD 4.12 `galileo.platesolve` | Test | `TC-PLT-040` |
| `PLT-050` | MVP | SDD 4.12 `galileo.platesolve` | Test | `TC-PLT-050` |
| `PLT-060` | P2 | SDD 4.12 `galileo.platesolve` | Test | `TC-PLT-060` |
| `PLT-070` | MVP | SDD 4.12 `galileo.platesolve` | Test | `TC-PLT-070` |

### `MFLIP` — Meridian Flip

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `MFLIP-010` | P2 | SDD 4.13 `galileo.meridianflip` | Test | `TC-MFLIP-010` |
| `MFLIP-020` | P2 | SDD 4.13 `galileo.meridianflip` | Test | `TC-MFLIP-020` |
| `MFLIP-030` | P2 | SDD 4.13 `galileo.meridianflip` | Test | `TC-MFLIP-030` |
| `MFLIP-040` | P2 | SDD 4.13 `galileo.meridianflip` | Test | `TC-MFLIP-040` |

### `GUIDE` — Guiding Integration

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `GUIDE-010` | MVP | SDD 4.14 `galileo.guiding` | Test | `TC-GUIDE-010` |
| `GUIDE-020` | MVP | SDD 4.14 `galileo.guiding` | Test | `TC-GUIDE-020` |
| `GUIDE-030` | MVP | SDD 4.14 `galileo.guiding` | Test | `TC-GUIDE-030` |
| `GUIDE-040` | P2 | SDD 4.14 `galileo.guiding` | Test | `TC-GUIDE-040` |
| `GUIDE-050` | MVP | SDD 4.14 `galileo.guiding` | Test | `TC-GUIDE-050` |
| `GUIDE-060` | P2 | SDD 4.14 `galileo.guiding` | Test | `TC-GUIDE-060` |
| `GUIDE-070` | MVP | SDD 4.14 `galileo.guiding` | Test | `TC-GUIDE-070` |
| `GUIDE-080` | MVP | SDD 4.14 `galileo.guiding` | Test | `TC-GUIDE-080` |
| `GUIDE-090` | MVP | SDD 4.14 `galileo.guiding` | Test | `TC-GUIDE-090` |

### `DOME` — Dome Control

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `DOME-010` | P2 | SDD 4.15 `galileo.dome` | Test | `TC-DOME-010` |
| `DOME-020` | P2 | SDD 4.15 `galileo.dome` | Test | `TC-DOME-020` |
| `DOME-030` | P2 | SDD 4.15 `galileo.dome` | Test | `TC-DOME-030` |

### `SAFE` — Safety & Weather Monitoring

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `SAFE-010` | P2 | SDD 4.16 `galileo.safety` | Test | `TC-SAFE-010` |
| `SAFE-020` | P3 | SDD 4.16 `galileo.safety` | Test | `TC-SAFE-020` |
| `SAFE-030` | P2 | SDD 4.16 `galileo.safety` | Test | `TC-SAFE-030` |
| `SAFE-040` | P2 | SDD 4.16 `galileo.safety` | Test | `TC-SAFE-040` |
| `SAFE-050` | P2 | SDD 4.16 `galileo.safety` | Test | `TC-SAFE-050` |
| `SAFE-060` | MVP | SDD 4.16 `galileo.safety` | Test | `TC-SAFE-060` |
| `SAFE-070` | P2 | SDD 4.16 `galileo.safety` | Test | `TC-SAFE-070` |
| `SAFE-080` | MVP | SDD 4.16 `galileo.safety` | Test | `TC-SAFE-080` |
| `SAFE-090` | P3 | SDD 4.16 `galileo.safety` | Test | `TC-SAFE-090` |
| `SAFE-100` | P3 | SDD 4.16 `galileo.safety` | Test | `TC-SAFE-100` |

### `HIST` — Session History & Statistics

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `HIST-010` | P2 | SDD 4.17 `galileo.history` | Test | `TC-HIST-010` |
| `HIST-020` | P2 | SDD 4.17 `galileo.history` | Test | `TC-HIST-020` |
| `HIST-030` | P2 | SDD 4.17 `galileo.history` | Test | `TC-HIST-030` |
| `HIST-040` | P3 | SDD 4.17 `galileo.history` | Test | `TC-HIST-040` |

### `META` — Image Metadata

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `META-010` | MVP | SDD 4.18 `galileo.metadata` | Test | `TC-META-010` |
| `META-020` | P2 | SDD 4.18 `galileo.metadata` | Test | `TC-META-020` |
| `META-030` | MVP | SDD 4.18 `galileo.metadata` | Test | `TC-META-030` |
| `META-040` | MVP | SDD 4.18 `galileo.metadata` | Test | `TC-META-040` |
| `META-050` | P3 | SDD 4.18 `galileo.metadata` | Test | `TC-META-050` |

### `NOTIF` — Notifications

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `NOTIF-010` | P2 | SDD 4.19 `galileo.notify` | Test | `TC-NOTIF-010` |
| `NOTIF-020` | P3 | SDD 4.19 `galileo.notify` | Test | `TC-NOTIF-020` |
| `NOTIF-030` | P3 | SDD 4.19 `galileo.notify` | Test | `TC-NOTIF-030` |
| `NOTIF-040` | P3 | SDD 4.19 `galileo.notify`; SDD 4.4a `galileo.observatory` | Test | `TC-NOTIF-040` |

### `PLUG` — Plugin Framework

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `PLUG-010` | MVP | SDD 4.20 `galileo.plugins` | Test | `TC-PLUG-010` |
| `PLUG-020` | MVP | SDD 4.20 `galileo.plugins` | Test | `TC-PLUG-020` |
| `PLUG-030` | P2 | SDD 4.20 `galileo.plugins` | Test | `TC-PLUG-030` |
| `PLUG-040` | MVP | SDD 4.20 `galileo.plugins` | Test | `TC-PLUG-040` |
| `PLUG-050` | MVP | SDD 4.20 `galileo.plugins` | Test | `TC-PLUG-050` |
| `PLUG-060` | MVP | SDD 4.20 `galileo.plugins` | Test | `TC-PLUG-060` |
| `PLUG-070` | MVP | SDD 4.20 `galileo.plugins` | Test | `TC-PLUG-070` |
| `PLUG-080` | MVP | SDD 4.20 `galileo.plugins` | Test | `TC-PLUG-080` |

### `UI` — Customization & Theming

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `UI-010` | P2 | SDD 4.21 `galileo.ui.theme` | Test | `TC-UI-010` |
| `UI-020` | P2 | SDD 4.21 `galileo.ui.theme` | Test | `TC-UI-020` |
| `UI-030` | P3 | SDD 4.21 `galileo.ui.theme` | Test | `TC-UI-030` |

### `LOG` — Diagnostics & Logging

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `LOG-010` | MVP | SDD 4.22 `galileo.diagnostics` | Test | `TC-LOG-010` |
| `LOG-020` | MVP | SDD 4.22 `galileo.diagnostics` | Test | `TC-LOG-020` |
| `LOG-030` | MVP | SDD 4.22 `galileo.diagnostics` | Test | `TC-LOG-030` |
| `LOG-040` | P2 | SDD 4.22 `galileo.diagnostics` | Test | `TC-LOG-040` |
| `LOG-050` | MVP | SDD 4.22 `galileo.diagnostics` | Test | `TC-LOG-050` |
| `LOG-060` | P2 | SDD 4.22 `galileo.diagnostics` | Test | `TC-LOG-060` |

### `LIB` — Image Library & Repository Management (merged from AstroFiler)

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `LIB-010` | MVP | SDD 4.23 `galileo.library` | Test | `TC-LIB-010` |
| `LIB-020` | MVP | SDD 4.23 `galileo.library` | Test | `TC-LIB-020` |
| `LIB-030` | MVP | SDD 4.23 `galileo.library` | Test | `TC-LIB-030` |
| `LIB-040` | MVP | SDD 4.23 `galileo.library` | Test | `TC-LIB-040` |
| `LIB-050` | MVP | SDD 4.23 `galileo.library` | Test | `TC-LIB-050` |
| `LIB-060` | MVP | SDD 4.23 `galileo.library` | Test | `TC-LIB-060` |
| `LIB-070` | MVP | SDD 4.23 `galileo.library` | Test | `TC-LIB-070` |
| `LIB-080` | MVP | SDD 4.23 `galileo.library` | Test | `TC-LIB-080` |
| `LIB-090` | MVP | SDD 4.23 `galileo.library` | Test | `TC-LIB-090` |
| `LIB-100` | P2 | SDD 4.23 `galileo.library` | Test | `TC-LIB-100` |
| `LIB-110` | P3 | SDD 4.23 `galileo.library` | Test | `TC-LIB-110` |
| `LIB-120` | P2 | SDD 4.23 `galileo.library` | Test | `TC-LIB-120` |
| `LIB-130` | P2 | SDD 4.23 `galileo.library` | Test | `TC-LIB-130` |
| `LIB-140` | P2 | SDD 4.23 `galileo.library` | Test | `TC-LIB-140` |
| `LIB-150` | MVP | SDD 4.23 `galileo.library` | Test | `TC-LIB-150` |
| `LIB-160` | MVP | SDD 4.23 `galileo.library` | Test | `TC-LIB-160` |

### `VST` / `VST-AN` — Moved

Variable Star Target Planning and Variable Star Analysis & Photometry are the VSTarget plugin's own requirements and are traced in its own RTM: [`docs/plugins/vstarget/RTM.md`](../plugins/vstarget/RTM.md).

### `NFR-PERF` — Performance

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `NFR-PERF-010` | MVP | SDD Sec 7: `galileo.ui.imaging` (Section 4.5) rendering pipeline; verified by performance test, not a design-time guarantee any single module line can assert | Test | `TC-NFR-PERF-010` |
| `NFR-PERF-020` | MVP | SDD Sec 2.3 `Concurrency Model` | Test | `TC-NFR-PERF-020` |
| `NFR-PERF-030` | MVP | SDD Sec 7: Cross-cutting outcome of the `ProcessPoolExecutor` CPU-work isolation (Section 2.3) and per-sequence progress persistence (`galileo.sequencer.basic`, Section 4.6) not leaking state across long runs; verified by soak test | Test | `TC-NFR-PERF-030` |

### `NFR-REL` — Reliability

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `NFR-REL-010` | MVP | SDD Sec 2.3 `Concurrency Model` | Test | `TC-NFR-REL-010` |
| `NFR-REL-020` | MVP | SDD Sec 2.3 `Concurrency Model` | Test | `TC-NFR-REL-020` |
| `NFR-REL-030` | MVP | SDD Sec 7: Cross-cutting outcome of `NFR-REL-010`/`020`'s device-error/stall handling (Section 2.3) plus the Watchdog (`galileo.safety`, Section 4.16, `SAFE-060`); verified by soak test, not a single module's responsibility | Test | `TC-NFR-REL-030` |
| `NFR-REL-040` | P2 | SDD 4.6 `galileo.sequencer.basic` | Test | `TC-NFR-REL-040` |

### `NFR-PORT` — Portability

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `NFR-PORT-010` | MVP | SDD Sec 7: ADR-001 (Section 2.1) and the layered/ports-and-adapters architecture (Section 2.2) as a whole — this is the architecture's central premise, not one module's property | Test | `TC-NFR-PORT-010` |
| `NFR-PORT-020` | MVP | SDD Sec 7: `galileo.core.devices`' `DeviceCapabilities` model (Section 4.1) — the mechanism the UI already uses to decide what to render is the same mechanism that lets it disable rather than hide an unavailable control | Test | `TC-NFR-PORT-020` |

### `NFR-EXT` — Extensibility

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `NFR-EXT-010` | P2 | SDD 4.20 `galileo.plugins` | Test | `TC-NFR-EXT-010` |

### `NFR-USE` — Usability

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `NFR-USE-010` | P2 | SDD Sec 7: `galileo.equipment.profiles`/`galileo.observatory` (Sections 4.4/4.4a) own the underlying flow; the guided-wizard UI itself has no dedicated module, it's a UI-layer composition of existing equipment/connection screens | Test | `TC-NFR-USE-010` |
| `NFR-USE-020` | MVP | SDD 4.10 `galileo.calibration` | Test | `TC-NFR-USE-020` |

### `NFR-I18N` — Localization

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `NFR-I18N-010` | MVP | SDD Sec 7: A cross-cutting implementation convention (Qt's `tr()`/`.ts` translation-file mechanism) applied across every `galileo.ui.*` module, not owned by any one of them | Test | `TC-NFR-I18N-010` |

### `NFR-SEC` — Security

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `NFR-SEC-010` | MVP | SDD Sec 7: A cross-cutting constraint on every adapter that talks to an external service (`galileo.adapters.*`, `galileo.vstarget.*`, `galileo.library`'s cloud-sync adapter, Open-Meteo clients) — enforced by code review/security review, not one module | Test | `TC-NFR-SEC-010` |
| `NFR-SEC-020` | P2 | SDD Sec 7: A documentation deliverable (user-facing docs), not a code module — tracked here so it isn't lost, not because it traces to a component | Inspection | `TC-NFR-SEC-020` |

### `NFR-OFFLINE` — Offline Operation

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `NFR-OFFLINE-010` | MVP | SDD 4.8 `galileo.planning.sky_atlas` | Test | `TC-NFR-OFFLINE-010` |
| `NFR-OFFLINE-020` | MVP | SDD Sec 7: `galileo.platesolve` (Section 4.12) — already satisfies `PLT-020`, which this NFR directly restates as a non-functional guarantee rather than a new capability | Test | `TC-NFR-OFFLINE-020` |

### `NFR-INSTALL` — Installability

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `NFR-INSTALL-010` | MVP | SDD Sec 7: Section 2.4's packaging/build-target table — a build-pipeline deliverable, not a `galileo.*` module | Demonstration | `TC-NFR-INSTALL-010` |
| `NFR-INSTALL-020` | MVP | SDD Sec 7: Section 2.4's packaging/build-target table — a build-pipeline deliverable, not a `galileo.*` module | Demonstration | `TC-NFR-INSTALL-020` |
| `NFR-INSTALL-030` | MVP | SDD Sec 7: Section 2.4's packaging/build-target table — a build-pipeline deliverable, not a `galileo.*` module | Demonstration | `TC-NFR-INSTALL-030` |

---

## 3. Summary by Domain

| Domain | Requirements | MVP | P2 | P3 |
|---|---|---|---|---|
| `EXT` | 14 | 9 | 4 | 1 |
| `ARCH` | 8 | 6 | 2 | 0 |
| `EQP` | 27 | 19 | 8 | 0 |
| `PROF` | 12 | 11 | 1 | 0 |
| `OBS` | 9 | 0 | 9 | 0 |
| `IMG` | 18 | 9 | 9 | 0 |
| `SES` (formerly `SEQ`/`SEQ-ADV`) | 30 | 17 | 10 | 3 |
| `SKY` | 12 | 8 | 4 | 0 |
| `FRAME` | 9 | 4 | 5 | 0 |
| `SKYMAP` | 9 | 3 | 6 | 0 |
| `SCHED` | 10 | 8 | 2 | 0 |
| `CAL` | 6 | 5 | 1 | 0 |
| `FOC` | 9 | 6 | 3 | 0 |
| `PLT` | 7 | 6 | 1 | 0 |
| `MFLIP` | 4 | 0 | 4 | 0 |
| `GUIDE` | 9 | 7 | 2 | 0 |
| `DOME` | 3 | 0 | 3 | 0 |
| `SAFE` | 10 | 2 | 5 | 3 |
| `HIST` | 4 | 0 | 3 | 1 |
| `META` | 5 | 3 | 1 | 1 |
| `NOTIF` | 4 | 0 | 1 | 3 |
| `PLUG` | 8 | 7 | 1 | 0 |
| `UI` | 3 | 0 | 2 | 1 |
| `LOG` | 6 | 4 | 2 | 0 |
| `LIB` | 16 | 11 | 4 | 1 |
| `NFR-PERF` | 3 | 3 | 0 | 0 |
| `NFR-REL` | 4 | 3 | 1 | 0 |
| `NFR-PORT` | 2 | 2 | 0 | 0 |
| `NFR-EXT` | 1 | 0 | 1 | 0 |
| `NFR-USE` | 2 | 1 | 1 | 0 |
| `NFR-I18N` | 1 | 1 | 0 | 0 |
| `NFR-SEC` | 2 | 1 | 1 | 0 |
| `NFR-OFFLINE` | 2 | 2 | 0 | 0 |
| `NFR-INSTALL` | 3 | 3 | 0 | 0 |
| **Total** | **272** | **161** | **97** | **14** |
