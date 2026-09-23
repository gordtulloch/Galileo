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

**Decision:** VSTarget's planning module (AAVSO client, target list, plan editor, script export) and analysis module (download, plate-solve orchestration, photometric stacking, aperture photometry, transformation calibration, reporting, exposure calculator) are packaged as two separate first-party pre-loaded plugins, `galileo.plugins.vstarget.planning` and `galileo.plugins.vstarget.analysis` (Sections 3.1–3.2), mirroring VSTarget's own module split. VSTarget's standalone entry point and GUI shell are retired; the planning view is exposed as a new UI panel presented as a **peer to the Sky Atlas/Targets tab**, not nested under it, per the parent PSD's explicit UI-placement requirement (`VST-090` is a UI-placement, not a functional, requirement enforced at the shell level rather than the module level).

**This supersedes the plugin's earlier treatment as a core-embedded merge** (previously "ADR-003" in [core SDD](../../SDD.md)): the *packaging outcome* — two pre-loaded plugins, same module split, same dependencies — is unchanged; what changed is that this decision, and the module design it governs, now lives in this plugin's own document chain rather than asserting a core architectural position. Nothing here required a change to core's plugin extension points (core `PLUG-010`–`PLUG-080`) to express correctly — which is itself the point of extracting this content: if it had, that would have meant `PLUG` was under-specified, not that VSTarget needed a special case.

**Physical location:** the code itself moved from `galileo.vstarget.*` to `galileo.plugins.vstarget.*` — nested under core's own `galileo.plugins` package rather than sitting beside it — so the module tree visibly reflects "first-party plugin" rather than looking like an ordinary core domain module. This is a relocation only: still pre-loaded and imported directly by `galileo.plugins.PluginManager.initialize_preloaded()` (Section 4.20 in core SDD), not yet installed/discovered via `PLUG-030`'s entry-points mechanism — that conversion to a genuinely separate, independently-developed distribution is deferred until the plugin architecture (marketplace, versioned install) is built out.

**Dependency reuse, not duplication:** VSTarget already depends on `astropy`, `numpy`, and `astroalign` — no new choice needed there. `photutils` — dropped from core `galileo.autofocus`/`galileo.ui.imaging`/`galileo.library` in favor of `SEP` (core SDD ADR-002) — is **reintroduced here deliberately, not by oversight**: SEP is a source-extraction/star-detection library, while this plugin's aperture-photometry engine (ensemble differential photometry against AAVSO comparison stars, with linear regression) is a different problem that `photutils.aperture` solves and SEP does not attempt. The two libraries serve different processes for different reasons; there is no redundant overlap to resolve, and core is not obligated to standardize on either for a plugin's own internal dependency choice.

**New dependencies:** `requests` (AAVSO Target Tool/VSP API client), `astroquery` (Simbad lookup, consuming core `EXT-110`), `paramiko` (SFTP, consuming core `EXT-120`), `pandas` (photometry tables), `matplotlib` (interactive transformation-outlier review, embedded via `FigureCanvasQTAgg`). All are GPL-3.0-compatible (this plugin's PSD Section 10, PC1). `matplotlib` is a second charting library alongside core Qt Charts (used by core `galileo.history`); this is an accepted, plugin-local inconsistency (this plugin's PSD Section 11 risk table), not a unification target, because VSTarget's interactive outlier-rejection UX is proven in matplotlib and re-implementing it in Qt Charts would be pure risk with no requirement-level benefit.

**Plate solving reuse:** `galileo.plugins.vstarget.analysis` calls into core's existing `galileo.platesolve` module (core `PLT-010`) rather than embedding its own ASTAP integration, even though VSTarget's original codebase has one — this collapses two independent ASTAP adapters into one.

---

## 3. Module / Component Design

### 3.1 `galileo.plugins.vstarget.planning` — Variable Star Target Planning

- **Responsibility:** AAVSO target sync/filtering, variable-star list display, observable-only filtering, manual import, observation-plan editor, ACP observing-script generation, Simbad lookup, direct submission of a target/plan to core's `galileo.scheduler` job queue. Packaged as the first-party pre-loaded plugin `plugins/vstarget/` (core SDD Section 4.20), registering a primary-level UI panel (core `PLUG-070`) presented as a peer section to core `galileo.planning.sky_atlas`, not nested beneath it, when enabled.
- **Key design:** Reuses core `galileo.planning.sky_atlas`'s visibility-computation service (core SDD Section 4.8) for the observable-only filter (`VST-030`) rather than duplicating rise/transit/set logic. Scheduler submission (`VST-090`) goes through the `PluginContext`-granted `SchedulerJobSubmitter` handle (core SDD Section 4.20, `PLUG-080`) rather than a direct import of `galileo.scheduler`, keeping the plugin/core boundary consistent even for a first-party plugin.
- **Libraries:** `requests` (AAVSO Target Tool/VSP API client), `astroquery` (Simbad lookup).
- **Satisfies:** `VST-010`–`VST-090`, `VST-EXT-010`.

### 3.2 `galileo.plugins.vstarget.analysis` — Variable Star Analysis & Photometry

- **Responsibility:** Remote-telescope image retrieval, plate-solve orchestration (via core `galileo.platesolve`), photometric mean-stacking, aperture photometry against AAVSO VSP comparison stars, AAVSO WebObs report generation, transformation-coefficient calibration, exposure calculator, AAVSO finder-chart generation. Packaged as its own first-party pre-loaded plugin (`plugins/vstarget_analysis/`, paired with but independently enabled/disabled from `plugins/vstarget/`, Section 3.1) — a user can run target planning without the analysis pipeline, or vice versa.
- **Key design:** Photometric stacking (`VST-AN-030`) is a distinct, bounded operation from any general-purpose image stacking — it exists solely to improve SNR for a photometric measurement and is not exposed as a general "stack my lights" feature. Star registration runs in core's process pool (core SDD Section 2.3) alongside the rest of Galileo's CPU-bound work, the same pooling mechanism any plugin's CPU-bound work uses. Comparison-star retrieval and finder-chart rendering (`VST-AN-090`) were originally adapted from AstroLlama's `variable_comparison_stars_tool.py`/`generate_aavso_map_tool.py` (core SDD ADR-004) during the original VSTarget merge design work — that provenance note is preserved here since it describes where this plugin's own code came from, not a core architectural fact.
- **Libraries:** `astroalign` (registration), `photutils` (aperture photometry — see Section 2.1 for why this is not a core-SEP duplication), `pandas` (photometry tables), `matplotlib` (interactive transformation-outlier review, and finder-chart rendering), `paramiko` (SFTP).
- **Satisfies:** `VST-AN-010`–`VST-AN-090`.

---

## 4. Data Design

| Data | Format | Storage |
|---|---|---|
| Variable-star observation plans, target lists, transformation coefficients | Peewee models in Galileo core's shared database (core SDD ADR-002), superseding VSTarget's original separate SQLite file | Per-platform user data directory (same database core uses, per core's persistence-unification decision) |

This plugin adds no new database of its own — it adds Peewee models to the one project-wide database core `galileo.library`/`galileo.history`/`galileo.scheduler` already share (core SDD Section 2.5/ADR-002), consistent with core's persistence-unification decision applying to every module, plugins included.

---

## 5. Interface Design

- **Plugin boundary:** this plugin depends only on core's device port interfaces, the `SequencerNode`/action-block registration surface (core SDD Section 4.7/6.3), and the `PluginContext` object (logging, config directory, event-bus handle, and the granted `SchedulerJobSubmitter` handle) injected at load time — identical to core SDD Section 6.3's Plugin API Surface description, since this plugin is not a special case of it.
- **External process interfaces this plugin adds:** AAVSO Target Tool and VSP REST API calls (`requests`), Simbad queries (`astroquery`, consuming core `EXT-110`), and SFTP image retrieval (`paramiko`, consuming core `EXT-120`) — used by `galileo.plugins.vstarget.planning`/`galileo.plugins.vstarget.analysis` (Sections 3.1–3.2).

---

## 6. Path to Traceability Matrix

A row per requirement ID in [this plugin's SRS](SRS.md), mapped to the module(s) in Section 3 above and a test case ID — see [RTM.md](RTM.md).

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SDD](../../SDD.md).*
