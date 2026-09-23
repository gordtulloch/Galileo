# VSTarget Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — VSTarget Plugin (variable-star target planning and photometric analysis) |
| **Document** | PSD (Project Scope Document), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-09-23 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Downstream documents** | SRS ([SRS.md](SRS.md)), SDD ([SDD.md](SDD.md)), RTM ([RTM.md](RTM.md)) |

---

## 1. Purpose of This Document

This document defines the scope of the **VSTarget plugin** — a first-party, pre-loaded, independently-disableable Galileo plugin delivering AAVSO variable-star target planning and photometric analysis. It follows the same PSD→SRS→SDD→RTM structure as [Galileo core's own document chain](../../PSD.md), scoped down to this one plugin, and is the reference example other first-party or third-party plugins should follow (`docs/plugins/<plugin-name>/`).

**Why this lives in its own document chain, not the core one:** earlier drafts of Galileo's core PSD/SRS/SDD/RTM embedded `VST`/`VST-AN` as core-adjacent domains — numbered alongside `ARCH`, `EQP`, `SKY`, and so on, with their own SDD module sections and RTM rows. That made it unclear why a variable-star-specific workflow was so deeply woven into documents meant to define Galileo's own baseline scope, when the actual mechanism connecting it to Galileo is — and always was — the generic Plugin Framework (`PLUG` domain, [core PSD Section 8](../../PSD.md#8-functional-requirement-domains-scope-level)). This document chain corrects that: `VST`/`VST-AN` content is removed from the core documents entirely (see core `CHANGELOG.md`) and lives here instead, as a concrete, fully-specified consumer of `PLUG`'s extension points — proving the plugin architecture works by being built against it like any other plugin would be, first-party status notwithstanding.

This document intentionally stays above implementation detail — no UI layouts, class designs, or protocol message schemas. Those belong in [SDD.md](SDD.md).

## 2. Background and Motivation

VSTarget's own background is unchanged from core PSD Section 2: Galileo's author has already built [VSTarget](https://github.com/gordtulloch/VSTarget), a working, GPL-3.0-licensed, Python/PySide6 AAVSO variable-star observation planner and photometric analysis tool (target selection from the AAVSO Target Tool API, remote-telescope observing-script generation, plate-solve/stack/aperture-photometry analysis, and AAVSO WebObs report generation). It runs on the same stack as Galileo core (Python/PySide6/AstroPy), which is why merging it in — as a plugin rather than a bolt-on feature — was judged practical from the start.

**What changed from the original merge plan:** VSTarget's functionality is still delivered in v1, still first-party, still pre-loaded, still enabled by default — none of that changes. What changes is where its *requirements* live: previously decomposed directly into core `SRS.md`/`SDD.md`/`RTM.md` under `VST`/`VST-AN` domain prefixes, now decomposed into this document chain instead, connecting to core exclusively through `PLUG`'s documented extension points (device-port interfaces, the `SequencerNode`/action-block registration surface, `PluginContext`) plus a small number of core capabilities it consumes as a client, not a domain owner (visibility computation from `SKY`, solving from `PLT`, job submission to `SCHED`).

## 3. Vision Statement

> The VSTarget plugin gives Galileo users who submit variable-star observations to AAVSO a first-party-quality planning and photometric-analysis workflow — AAVSO Target Tool sync, observation planning, image retrieval, aperture photometry, and WebObs reporting — delivered as an ordinary plugin against Galileo's own plugin architecture, not as a special-cased core feature.

## 4. Goals and Objectives

| # | Goal |
|---|---|
| G1 | Deliver VSTarget's variable-star target planning (AAVSO catalog integration, observing-script generation) as the `VST` plugin — a first-party, pre-loaded, independently-disableable plugin (core `PLUG-060`), presented as a peer-level UI section to the Sky Atlas/Targets screen (core `SKY`) at the primary navigation level (core `PLUG-070`), not nested beneath it |
| G2 | Deliver VSTarget's photometric analysis/AAVSO-reporting workflow as the separate `VST-AN` plugin, paired with but independently enabled/disabled from `VST` |
| G3 | Reuse core capabilities as a client rather than duplicating them: visibility computation (`SKY-030`), plate solving (`PLT-010`), Scheduler job submission (`SCHED-010`, via `PluginContext`) — this plugin owns no device ports and introduces no new core domain |
| G4 | Demonstrate, not just declare, that Galileo's plugin architecture (core `PLUG`) is sufficient for a first-party workflow of this complexity — every capability below is expressed through `PLUG`'s existing extension points, with no plugin-specific carve-out added to core to make it fit |

## 5. Non-Goals (Explicitly Out of Scope)

- **No changes to core domains.** This plugin adds no new `ARCH`/`EQP`/`SKY`/`PLT`/`SCHED` requirements of its own; where it needs core behavior it consumes an existing, already-numbered core requirement.
- **No general-purpose image stacking.** `VST-AN`'s registered mean-stacking exists solely to improve photometric SNR for a measurement, not as a general "stack my lights" feature (mirrors core PSD Section 5's identical carve-out for calibration-frame stacking).
- **No bundled guiding, dome, or safety-monitor logic.** This plugin captures/retrieves/analyzes images; it has no equipment-control surface of its own beyond what it reaches through core ports it's granted access to via `PluginContext`.

## 6. Reference: VSTarget Feature Inventory

Compiled from [github.com/gordtulloch/VSTarget](https://github.com/gordtulloch/VSTarget); used as the functional baseline for this plugin's `VST` (planning) and `VST-AN` (analysis) domains in Section 8. VSTarget runs Python 3.10+/PySide6/AstroPy — the same stack as Galileo core.

- **Target planning:** AAVSO Target Tool API sync, filterable by observing section (Alerts, Cataclysmic Variables, Eclipsing Variables, Long Period Variables, etc.); sortable/searchable list with priority highlighting and solar-conjunction warnings; observable-only visibility filtering; manual delimited-text import
- **Observation plans:** per-target filter/exposure-count/interval/binning editor; iTelescope ACP observing-script generation sorted by right ascension; plan persistence
- **Image retrieval:** FTP/SFTP calibrated-FITS download from remote-telescope data servers
- **Analysis pipeline:** ASTAP plate-solving; registered mean-stacking (`astroalign`) for photometric SNR improvement; aperture photometry against AAVSO VSP comparison stars with ensemble linear-regression differential photometry
- **Reporting:** AAVSO WebObs Extended-format report generation
- **Calibration:** per-telescope/per-filter transformation-coefficient calculation from standard fields (M67, NGC 7790, M11, NGC 1252, NGC 3532, Melotte 111, Landolt fields), with interactive outlier review; exposure-time calculator

## 7. Dependencies on Galileo Core

This plugin is a client of the following core capabilities — each is an existing, unchanged core requirement this plugin's own requirements (Section 8) trace to, not something this document specifies:

| Core capability | Core requirement | How this plugin uses it |
|---|---|---|
| Plugin loading, manifest/version check, fault isolation | `PLUG-010`–`PLUG-050` | Both `VST` and `VST-AN` are discovered/loaded/isolated the same as any plugin |
| Pre-loaded first-party plugin enable/disable | `PLUG-060` | Both ship pre-loaded, independently toggleable |
| Primary-level UI panel insertion | `PLUG-070` | `VST`'s target-planning UI is a peer section to the Sky Atlas/Targets screen, not nested beneath it |
| `PluginContext` core-service callback surface | `PLUG-080` | `VST`'s Scheduler-submission control (Section 8) calls a `PluginContext`-granted `SchedulerJobSubmitter` handle rather than importing `galileo.scheduler` directly |
| Target visibility computation | `SKY-030` | `VST`'s observable-only filtering reuses this rather than a second rise/transit/set implementation |
| Simbad object-name lookup | Core `EXT-110` (external interface) | `VST`'s coordinate/magnitude fallback lookup |
| Plate solving | `PLT-010` | `VST-AN` solves retrieved/captured images via the existing solver integration rather than embedding its own |
| Remote-telescope FTP/FTPS/SFTP retrieval | Core `EXT-080`, `EXT-120` | `VST-AN`'s calibrated-image download |
| Scheduler job queue | `SCHED-010` | `VST`'s direct-submission control |

## 8. Functional Requirement Domains (Scope-Level)

Domain IDs and numbering (`VST-*`, `VST-AN-*`) are unchanged from their original core-embedded form — only their document location moved, not their identifiers, so any pre-existing references to a specific `VST-*`/`VST-AN-*` ID remain valid.

| ID Prefix | Domain | Scope Description | Priority |
|---|---|---|---|
| `VST` | Variable Star Target Planning | AAVSO variable-star target sync/selection, observable-only filtering, observation-plan editor, remote-telescope observing-script generation. Presented as a peer-level UI section to the Sky Atlas/Targets screen, not nested beneath it | MVP |
| `VST-AN` | Variable Star Analysis & Photometry | Remote-telescope image retrieval, photometric mean-stacking, aperture photometry against AAVSO comparison stars, AAVSO WebObs report generation, transformation-coefficient calibration, exposure calculator | MVP/P2 (mixed — see [SRS.md](SRS.md)) |

## 9. Stakeholders and Primary Persona

| Persona | Description | Primary Interests |
|---|---|---|
| Variable Star Observer (AAVSO contributor) | Plans and executes variable-star observation campaigns, submits photometric measurements to AAVSO | Target selection/scripting (`VST`), photometry/reporting accuracy (`VST-AN`) |

## 10. Assumptions and Constraints

- **PC1** — VSTarget is GPL-3.0 licensed and runs on the same Python/PySide6/AstroPy stack as Galileo core, so this plugin's dependencies (`astroquery`, `paramiko`, `astroalign`, `photutils`, `pandas`, `matplotlib` — see [SDD.md](SDD.md)) are all GPL-3.0-compatible, with no license tension against core PSD Section 11, C4's GPL-3.0 project license.
- **PC2** — Under Galileo's in-process plugin design (core PSD Section 11, C4), this plugin is very likely a "combined work" under GPL-3.0 and must itself be GPL-compatible-licensed to distribute — trivially satisfied since it's first-party and GPL-3.0 itself.
- **PC3** — `matplotlib` (interactive transformation-outlier review, finder-chart rendering) is a second charting library alongside core's Qt Charts (`HIST`). This is scoped as this plugin's own dependency, not a core packaging concern: a plugin process carries whatever charting library its own UI needs, and core is not obligated to unify around it. Accepted because VSTarget's interactive outlier-rejection UX is proven in matplotlib; revisit only if it becomes a genuine cross-plugin packaging problem.

## 11. Risks

| Risk | Impact | Notes |
|---|---|---|
| This plugin's AAVSO photometry/reporting workflow is scientifically specialized and easy to under-test relative to core acquisition workflows | Medium | Treat `VST-AN` as its own testable unit with domain-expert (AAVSO-standard) validation, not folded loosely into core imaging QA |
| A second charting library (`matplotlib`) ships inside this plugin alongside core's Qt Charts | Low | Accepted (Section 10, PC3); revisit only if it becomes a packaging/consistency problem across the plugin ecosystem generally |

## 12. References

- VSTarget (this plugin's origin): https://github.com/gordtulloch/VSTarget
- [Galileo Core PSD](../../PSD.md) — the parent scope document this plugin depends on, particularly Section 8's `PLUG` domain
- AAVSO (American Association of Variable Star Observers): https://www.aavso.org/

## 13. Glossary

Terms not already defined in [Galileo core PSD's Glossary](../../PSD.md#15-glossary) (Section 15) apply unchanged; the following are specific to this plugin:

| Term | Definition |
|---|---|
| AAVSO | American Association of Variable Star Observers — the variable-star catalog/photometry-standards body `VST`/`VST-AN` integrate with |
| VSP | AAVSO's Variable Star Photometry service — the comparison-star data source for `VST-AN` aperture photometry |

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's PSD](../../PSD.md). Open items should be resolved consistently with core scope decisions before SRS authoring proceeds.*
