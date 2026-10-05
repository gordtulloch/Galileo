# VSTarget Plugin — SDD (Software Design Description)

| | |
|---|---|
| **Project** | Galileo — VSTarget Plugin |
| **Document** | SDD (Software Design Description), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-09-23 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md) |
| **Downstream document** | RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SDD](../../SDD.md) |

---

## 1. Introduction

### 1.1 Purpose

This SDD describes how this plugin's module decomposition satisfies the requirements enumerated in [its SRS](SRS.md), and how it attaches to [Galileo core's architecture](../../SDD.md) exclusively through the plugin extension points core `galileo.plugins` (core SDD Section 4.20) already exposes.

### 1.2 Scope

Covers this plugin's two modules (`galileo.plugins.vstarget.planning`, `galileo.plugins.vstarget.analysis`), its own ADR (packaging/dependency decisions specific to this plugin), and its data design. It does not restate core architecture (concurrency model, device abstraction, event bus) — those are [core SDD Sections 2–3](../../SDD.md), unchanged and inherited as-is.

### 1.3 References

- [This plugin's PSD](PSD.md), [SRS](SRS.md)
- [Galileo Core SDD](../../SDD.md), particularly Section 2.2 (Architectural Style — the ports-and-adapters/plugin boundary this plugin is built against), Section 4.20 (`galileo.plugins`), and Section 6.3 (Plugin API Surface)

---

## 2. Design Considerations

### 2.1 VSTarget Plugin Packaging Strategy (ADR-VST-001)

**Decision:** VSTarget's planning module (AAVSO client, target list, plan editor, script export) and analysis module (download, plate-solve orchestration, photometric stacking, aperture photometry, transformation calibration, reporting, exposure calculator) are packaged as a single distributable ZIP (`vstarget-<version>.zip`) containing both `galileo.plugins.vstarget.planning` and `galileo.plugins.vstarget.analysis` (Sections 3.1–3.2), mirroring VSTarget's own module split. VSTarget's standalone entry point and GUI shell are retired; the planning view is exposed as a new UI panel presented as a **peer to the Sky Atlas/Targets tab**, not nested under it, per the parent PSD's explicit UI-placement requirement (`VST-090` is a UI-placement, not a functional, requirement enforced at the shell level rather than the module level).

**This supersedes the plugin's earlier treatment as a core-embedded merge** (previously "ADR-003" in [core SDD](../../SDD.md)): VSTarget is now distributed as a downloadable ZIP from galileo-imaging.com, installed by the user through the Options > Plugins screen (core `PLUG-090`/`PLUG-110`), and discovered at startup via `initialize_from_disk()` (core SDD Section 4.20). The module tree — `galileo.plugins.vstarget.*` — remains unchanged; what changed is that the plugin is no longer bundled with the installer or pre-loaded unconditionally by `initialize_preloaded()`.

**Physical location:** `galileo.plugins.vstarget.*` — nested under core's own `galileo.plugins` package so the module tree visibly reflects "first-party plugin." The `plugin.toml` manifest at the root of the ZIP (and in the source tree at `galileo/plugins/vstarget/plugin.toml`) declares `entry_point = "galileo.plugins.vstarget"`, `api_min = "1"`, `api_max = "1"`, and `tier = "first_party"`.

**Dependency reuse, not duplication:** VSTarget already depends on `astropy`, `numpy`, and `astroalign` — no new choice needed there. `photutils` — dropped from core `galileo.autofocus`/`galileo.ui.imaging`/`galileo.library` in favor of `SEP` (core SDD ADR-002) — is **reintroduced here deliberately, not by oversight**: SEP is a source-extraction/star-detection library, while this plugin's aperture-photometry engine (ensemble differential photometry against AAVSO comparison stars, with linear regression) is a different problem that `photutils.aperture` solves and SEP does not attempt. The two libraries serve different processes for different reasons; there is no redundant overlap to resolve, and core is not obligated to standardize on either for a plugin's own internal dependency choice.

**New dependencies:** `requests` (AAVSO Target Tool/VSP API client), `astroquery` (Simbad lookup, consuming core `EXT-110`), `pandas` (photometry tables), `matplotlib` (interactive transformation-outlier review, embedded via `FigureCanvasQTAgg`). All are GPL-3.0-compatible (this plugin's PSD Section 10, PC1). `matplotlib` is a second charting library alongside core Qt Charts (used by core `galileo.history`); this is an accepted, plugin-local inconsistency (this plugin's PSD Section 11 risk table), not a unification target, because VSTarget's interactive outlier-rejection UX is proven in matplotlib and re-implementing it in Qt Charts would be pure risk with no requirement-level benefit.

**Plate solving reuse:** `galileo.plugins.vstarget.analysis` calls into core's existing `galileo.platesolve` module (core `PLT-010`) rather than embedding its own ASTAP integration, even though VSTarget's original codebase has one — this collapses two independent ASTAP adapters into one.

---

## 3. Module / Component Design

### 3.1 `galileo.plugins.vstarget.planning` — Variable Star Target Planning

- **Responsibility:** AAVSO target sync/filtering, variable-star list display, observable-only filtering, manual import, observation-plan editor, ACP observing-script generation, Simbad lookup, direct submission of a target/plan to core's `galileo.scheduler` job queue. Distributed as part of the `vstarget-<version>.zip` first-party plugin package (core `PLUG-090`/`PLUG-110`); discovered via `initialize_from_disk()` at startup (core SDD Section 4.20); registers a primary-level UI panel (core `PLUG-070`) presented as a peer section to core `galileo.planning.sky_atlas`, not nested beneath it, when enabled.
- **Key design:** Reuses core `galileo.planning.sky_atlas`'s visibility-computation service (core SDD Section 4.8) for the observable-only filter (`VST-030`) rather than duplicating rise/transit/set logic. Scheduler submission (`VST-090`) goes through the `PluginContext`-granted `SchedulerJobSubmitter` handle (core SDD Section 4.20, `PLUG-080`) rather than a direct import of `galileo.scheduler`, keeping the plugin/core boundary consistent even for a first-party plugin.
- **Libraries:** `requests` (AAVSO Target Tool/VSP API client), `astroquery` (Simbad lookup).
- **Session hand-off (`VST-100`):** the planning panel turns a plan into one core `SES` session rather than writing a script — `vstarget.planning.session_builder` emits the same `galileo.ui.sessions` block types a user would drag in by hand (`TargetBlock` + one `ImageBlock` per filter, plus optional `PlateSolveBlock`/`AutofocusBlock`/`DitherBlock`/`GuideStart`/`GuideStopBlock`), in RA order. The panel attaches it through the host's own `SessionsPageWidget.create_session_for_target` entry point so the new region inherits the active Pier and that Pier's scheduler, falling back to `SessionRegion.save()` on disk when no host window is present. `VST-060`'s ACP exporter is unchanged and still serves remote-telescope networks that take scripts.
- **Satisfies:** `VST-010`–`VST-100`, `VST-EXT-010`.

### 3.2 `galileo.plugins.vstarget.analysis` — Variable Star Analysis & Photometry

- **Responsibility:** Remote-telescope image retrieval, plate-solve orchestration (via core `galileo.platesolve`), photometric mean-stacking, aperture photometry against AAVSO VSP comparison stars, AAVSO WebObs report generation, transformation-coefficient calibration, exposure calculator, AAVSO finder-chart generation. Distributed as part of the same `vstarget-<version>.zip` package as `galileo.plugins.vstarget.planning` (Section 3.1), but registered as a distinct plugin entry point so it can be independently enabled/disabled — a user can run target planning without the analysis pipeline, or vice versa.
- **Key design:** Photometric stacking (`VST-AN-030`) is a distinct, bounded operation from any general-purpose image stacking — it exists solely to improve SNR for a photometric measurement and is not exposed as a general "stack my lights" feature. Star registration runs in core's process pool (core SDD Section 2.3) alongside the rest of Galileo's CPU-bound work, the same pooling mechanism any plugin's CPU-bound work uses. Comparison-star retrieval and finder-chart rendering (`VST-AN-090`) were originally adapted from AstroLlama's `variable_comparison_stars_tool.py`/`generate_aavso_map_tool.py` (core SDD ADR-004) during the original VSTarget merge design work — that provenance note is preserved here since it describes where this plugin's own code came from, not a core architectural fact.
- **Library-backed input (`VST-AN-100`):** the analysis panel's input is a session list, not a folder chooser. `vstarget.analysis.library_sessions` reads core `galileo.library`'s own catalog — the `VariableStars` table the Images tab's *Add Variable Star* action writes, joined to the `fitsSession`/`fitsFile` rows of those targets — and returns the sessions the panel lists and the frame paths photometry runs over. Object names are matched case-insensitively and reported under the designated spelling, so one star cannot split into two groups; a session with no light frames is dropped; a session's calibrated frames are used where it has them, falling back to its raw lights where it does not. The module holds no Qt, so the queries are testable against a migrated database alone, and it reads the catalog through the library's own models rather than opening a database of its own (core SDD ADR-002).
- **Measuring off the UI thread (core `NFR-PERF-020`):** a run is split by `vstarget.analysis.runner`. `build_jobs()` stays on the UI thread, where the library and plan-store connections live, and resolves the selected sessions into self-contained jobs (frames, target with coordinates, filter band); `run_jobs()` does the measuring with no database or Qt involvement, reporting progress per frame and checking a cancel flag between frames so a stopped run keeps what it has already measured. `PhotometryThread` wraps `run_jobs()` in a `QThread` with one event loop for the batch, following the same lazily-built-class pattern as the planning panel's `FetchTargetsThread` so the module imports without Qt present. The panel's aperture radius is passed to `VariableStarAnalysis`, which scales the sky annulus with it (1.5x/2.5x the radius) rather than leaving the engine's fixed 12-20 px annulus inside a widened aperture.
- **Libraries:** `astroalign` (registration), `photutils` (aperture photometry — see Section 2.1 for why this is not a core-SEP duplication), `pandas` (photometry tables), `matplotlib` (interactive transformation-outlier review, and finder-chart rendering).
- **Satisfies:** `VST-AN-020`–`VST-AN-100` (`VST-AN-010` retired).

---

## 4. Data Design

| Data | Format | Storage |
|---|---|---|
| Variable-star observation plans, target lists, transformation coefficients | Peewee models in Galileo core's shared database (core SDD ADR-002), superseding VSTarget's original separate SQLite file | Per-platform user data directory (same database core uses, per core's persistence-unification decision) |

This plugin adds no new database of its own — it adds Peewee models to the one project-wide database core `galileo.library`/`galileo.history`/`galileo.scheduler` already share (core SDD Section 2.5/ADR-002), consistent with core's persistence-unification decision applying to every module, plugins included.

---

## 5. Interface Design

- **Plugin boundary:** this plugin depends only on core's device port interfaces, the `SequencerNode`/action-block registration surface (core SDD Section 4.7/6.3), and the `PluginContext` object (logging, config directory, event-bus handle, and the granted `SchedulerJobSubmitter` handle) injected at load time — identical to core SDD Section 6.3's Plugin API Surface description, since this plugin is not a special case of it.
- **External process interfaces this plugin adds:** AAVSO Target Tool and VSP REST API calls (`requests`), and Simbad queries (`astroquery`, consuming core `EXT-110`) — used by `galileo.plugins.vstarget.planning`/`galileo.plugins.vstarget.analysis` (Sections 3.1–3.2).

---

## 6. Path to Traceability Matrix

A row per requirement ID in [this plugin's SRS](SRS.md), mapped to the module(s) in Section 3 above and a test case ID — see [RTM.md](RTM.md).

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SDD](../../SDD.md).*
